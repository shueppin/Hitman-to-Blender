#!/usr/bin/env python3
"""
fix_alpha.py
============
Repairs decal / overlay materials that show up as opaque white rectangles after
importing a Hitman map (see godot_to_blender.py).

Cause: the exported .glb materials are marked OPAQUE, so Blender ignores the
alpha channel stored in the texture. This script finds every material whose
base-colour texture really contains transparency, connects the texture's Alpha
output to the shader, and switches the material to a blended mode.

Run it on the already-built scene (fast, no re-import needed):

    blender map.blend --background --python fix_alpha.py -- --save map_fixed.blend

or open map.blend, then Scripting tab -> open this file -> Run Script.

Options (after the `--`):
    --save FILE        save the result as a new .blend (omit to just modify the open scene)
    --threshold 0.98   a texture counts as transparent if its lowest alpha is below this
    --offset 0.0       push meshes that use fixed materials outwards along their normals
                       by this many metres (fixes z-fighting of decals lying exactly
                       on a wall; try 0.003)
    --report-only      only print what would change
"""
import argparse
import sys

import bpy


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="fix_alpha.py")
    ap.add_argument("--save", default="")
    ap.add_argument("--threshold", type=float, default=0.98)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--report-only", action="store_true")
    return ap.parse_args(argv)


_alpha_cache = {}


def min_alpha(img):
    """Lowest alpha value in an image (measured on a 64x64 shrunken copy)."""
    if img is None:
        return 1.0
    if img.name in _alpha_cache:
        return _alpha_cache[img.name]
    result = 1.0
    if img.depth in (32, 64, 128):                  # has an alpha channel
        try:
            tmp = img.copy()
            tmp.scale(64, 64)
            buf = [0.0] * (len(tmp.pixels))
            tmp.pixels.foreach_get(buf)
            alphas = buf[3::4]
            result = min(alphas) if alphas else 1.0
            bpy.data.images.remove(tmp)
        except Exception as e:                       # noqa
            print("  could not read", img.name, e)
    _alpha_cache[img.name] = result
    return result


def find_base_texture(bsdf):
    """Walk upstream from Base Color to the first Image Texture node."""
    seen, stack = set(), [bsdf.inputs["Base Color"]]
    while stack:
        sock = stack.pop()
        for link in sock.links:
            node = link.from_node
            if node.type == "TEX_IMAGE":
                return node
            if node.name not in seen:
                seen.add(node.name)
                stack.extend(i for i in node.inputs if i.links)
    return None


def main():
    opt = parse()
    fixed, skipped_linked, no_alpha = [], 0, 0

    for mat in bpy.data.materials:
        if not mat.use_nodes or mat.node_tree is None:
            continue
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        if bsdf.inputs["Alpha"].is_linked:
            skipped_linked += 1                      # already handled by the importer
            continue
        tex = find_base_texture(bsdf)
        if tex is None or tex.image is None:
            continue
        lo = min_alpha(tex.image)
        if lo >= opt.threshold:
            no_alpha += 1
            continue
        fixed.append((mat.name, tex.image.name, lo))
        if opt.report_only:
            continue
        mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        if hasattr(mat, "surface_render_method"):    # Blender 4.2+ (EEVEE Next)
            mat.surface_render_method = "BLENDED"
        if hasattr(mat, "blend_method"):             # Blender < 4.2 (EEVEE)
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "HASHED"
        if hasattr(mat, "show_transparent_back"):
            mat.show_transparent_back = False        # avoids sorting artefacts
        mat["alpha_fixed"] = True

    print("\n=== fix_alpha report ===")
    print("materials with real transparency: %d" % len(fixed))
    for name, img, lo in fixed[:40]:
        print("   %-40s texture=%-30s min alpha=%.2f" % (name, img, lo))
    if len(fixed) > 40:
        print("   ... and %d more" % (len(fixed) - 40))
    print("opaque materials left alone: %d   already linked: %d" % (no_alpha, skipped_linked))
    if not fixed:
        print("\nNo texture with an alpha channel was found. The exporter probably dropped the\n"
              "alpha when it converted the textures; the fix then has to happen at extraction\n"
              "(e.g. extracting the TEXT files as TGA with RPKG Tool and re-linking them).")

    # optional z-fighting offset ------------------------------------------------
    if opt.offset and fixed and not opt.report_only:
        names = {n for n, _, _ in fixed}
        done, moved = set(), 0
        for ob in bpy.data.objects:
            if ob.type != "MESH" or ob.data.name in done:
                continue
            if any(s.material and s.material.name in names for s in ob.material_slots):
                me = ob.data
                n = len(me.vertices)
                co = [0.0] * (n * 3)
                me.vertices.foreach_get("co", co)
                for i, v in enumerate(me.vertices):
                    nx, ny, nz = v.normal
                    co[3 * i] += nx * opt.offset
                    co[3 * i + 1] += ny * opt.offset
                    co[3 * i + 2] += nz * opt.offset
                me.vertices.foreach_set("co", co)
                me.update()
                done.add(me.name)
                moved += 1
        print("offset %.4f m applied to %d meshes" % (opt.offset, moved))

    if opt.save and not opt.report_only:
        bpy.ops.wm.save_as_mainfile(filepath=opt.save, compress=True)
        print("Saved:", opt.save)


main()
