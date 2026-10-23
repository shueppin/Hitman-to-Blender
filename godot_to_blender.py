#!/usr/bin/env python3
"""
godot_to_blender.py
===================
Rebuilds a Hitman map exported by RPKG Tool (-export_map / -export_map_textured)
inside Blender, WITHOUT going through Godot.

Input  : the export folder
           project.godot
           <HASH>.TEMP.tscn            (the scene: hierarchy + transforms)
           <HASH>.PRIM.glb  ...        (one model per PRIM resource)
Output : a Blender scene (optionally saved as .blend) in which every model is
         placed exactly where the Godot scene places it, with its textures.

How the conversion works
------------------------
* The .tscn is parsed as text. Every [node] has a local Transform3D, a parent
  path, and optionally an `instance=ExtResource(n)` pointing at a PRIM .glb.
* Godot stores Transform3D as 12 numbers: a row-major 3x3 basis followed by the
  origin. (Verified on your file: every scaled node has orthogonal columns,
  which is only true for this reading.)
* The scene root carries a rotation that turns Glacier's Z-up data into
  Godot's Y-up world. Blender is Z-up as well, so that rotation is cancelled
  out by Blender's own glTF Y-up -> Z-up conversion; the script computes this
  explicitly (see ROOT_MATRIX below) instead of assuming it.
* The .glb files contain raw Glacier coordinates, but Blender's glTF importer
  assumes glTF is Y-up and rotates them. Each placed mesh therefore gets a
  corrective -90/+90 degree rotation so that it ends up upright.
* Each .glb is imported only ONCE; every placement is a new object that shares
  the same mesh data (cheap, like linked duplicates).

Usage
-----
  Headless (recommended for big maps):

    blender --background --python godot_to_blender.py -- ^
        --project "C:\\path\\to\\export_folder" ^
        --save    "C:\\path\\to\\map.blend"

  or from Blender's Scripting tab: edit CONFIG below and press "Run Script".

Useful options (put them after the `--`):
    --tscn FILE            scene file, if it cannot be found from project.godot
    --glb-dir DIR          folder with the .glb files (default: folder of the tscn)
    --exclude REGEX        skip nodes whose path matches (repeatable). Children
                           of skipped nodes are skipped as well.
                           e.g. --exclude "FX_Smoke"
                           (do NOT exclude "DONTUSE": the exporter gives almost
                           all real geometry that name)
    --keep-empties         keep hierarchy nodes that have no model below them
    --no-axis-fix          do not apply the per-mesh axis correction
    --transpose-basis      read the 3x3 basis as column-major (debug only)
    --limit N              only place the first N models (quick test)
    --no-clear             do not clear the startup scene (background mode)
"""

import argparse
import glob
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    import bpy
    from mathutils import Matrix
    IN_BLENDER = True
except ImportError:  # the parser below also works in plain Python
    IN_BLENDER = False

# --------------------------------------------------------------------------
# CONFIG - only used when no command line arguments are given
# (i.e. when you run the script from Blender's Scripting tab)
# --------------------------------------------------------------------------
CONFIG = dict(
    project="",            # folder containing project.godot  (or leave empty and set tscn)
    tscn="",               # full path of the .tscn           (optional)
    glb_dir="",            # folder containing the .glb files (optional)
    save="",               # e.g. r"C:\maps\paris.blend"      (optional)
    exclude=[],            # e.g. ["FX_Smoke"]  (regex on the node path)
    keep_empties=False,
    axis_fix=True,
    transpose_basis=False,
    limit=0,
    clear=True,
)


# --------------------------------------------------------------------------
# 1. Parsing (pure Python)
# --------------------------------------------------------------------------
@dataclass
class Node:
    name: str
    parent: Optional[str]          # parent *path* ("." = root, None = this is the root)
    path: str                      # unique path of this node
    transform: Optional[List[float]] = None
    instance_id: Optional[str] = None
    editor_description: str = ""
    children: List["Node"] = field(default_factory=list)


_HDR = re.compile(
    r'(\w+)=(?:"((?:[^"\\]|\\.)*)"'                    # key="string"
    r'|ExtResource\(\s*"?([^")\s]+)"?\s*\)'            # key=ExtResource( 4 )  /  ("4_abc")
    r'|([^\s\]]+))'                                    # key=bare
)
_TF = re.compile(r'Transform3D\(([^)]*)\)')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace('\\\\', '\\')


def find_scene(project_dir: str) -> str:
    """Locate the main .tscn using project.godot, with fallbacks."""
    pg = os.path.join(project_dir, "project.godot")
    cands = []
    if os.path.isfile(pg):
        m = re.search(r'run/main_scene\s*=\s*"res://([^"]+)"',
                      open(pg, encoding="utf-8", errors="replace").read())
        if m:
            rel = m.group(1)
            cands += [rel, rel.replace(".TEMP.", "_TEMP."), rel.replace(".", "_", rel.count(".") - 1)]
    for c in cands:
        p = os.path.join(project_dir, c)
        if os.path.isfile(p):
            return p
    scenes = glob.glob(os.path.join(project_dir, "*.tscn"))
    if not scenes:
        raise FileNotFoundError("No .tscn found in " + project_dir)
    return max(scenes, key=os.path.getsize)


def parse_tscn(path: str):
    """Return (ext_resources {id: 'file.glb'}, nodes [Node, ...] in file order)."""
    ext: Dict[str, str] = {}
    nodes: List[Node] = []
    by_path: Dict[str, Node] = {}
    cur: Optional[Node] = None

    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("["):
                cur = None
                if line.startswith("[ext_resource"):
                    attrs = {m.group(1): (m.group(2) if m.group(2) is not None
                                          else m.group(3) if m.group(3) is not None
                                          else m.group(4))
                             for m in _HDR.finditer(line)}
                    if "path" in attrs and "id" in attrs:
                        ext[attrs["id"]] = _unescape(attrs["path"]).replace("res://", "")
                elif line.startswith("[node"):
                    body = line[len("[node"):].rstrip()
                    if body.endswith("]"):
                        body = body[:-1]
                    attrs = {m.group(1): (m.group(2) if m.group(2) is not None
                                          else m.group(3) if m.group(3) is not None
                                          else m.group(4))
                             for m in _HDR.finditer(body)}
                    name = _unescape(attrs.get("name", "node"))
                    parent = attrs.get("parent")
                    if parent is not None:
                        parent = _unescape(parent)
                    npath = "." if parent is None else (name if parent == "." else parent + "/" + name)
                    cur = Node(name=name, parent=parent, path=npath,
                               instance_id=attrs.get("instance"))
                    if npath in by_path:
                        print("WARNING: duplicate node path, later one wins:", npath)
                    by_path[npath] = cur
                    nodes.append(cur)
                continue
            if cur is None:
                continue
            if line.startswith("transform"):
                m = _TF.search(line)
                if m:
                    vals = [float(x) for x in m.group(1).split(",")]
                    if len(vals) == 12:
                        cur.transform = vals
            elif line.startswith("editor_description"):
                m = re.search(r'"((?:[^"\\]|\\.)*)"', line)
                if m:
                    cur.editor_description = _unescape(m.group(1))

    for n in nodes:
        if n.parent is not None:
            p = by_path.get(n.parent)
            if p is None:
                print("WARNING: parent not found for", n.path)
            else:
                p.children.append(n)
    return ext, nodes, by_path


def resolve_glb(glb_dir: str, rel: str, _cache={}) -> Optional[str]:
    """Find the .glb on disk; tolerant to case and '.' vs '_' in the file name."""
    p = os.path.join(glb_dir, rel)
    if os.path.isfile(p):
        return p
    if glb_dir not in _cache:
        _cache[glb_dir] = {f.lower().replace(".", "_"): f for f in os.listdir(glb_dir)}
    hit = _cache[glb_dir].get(os.path.basename(rel).lower().replace(".", "_"))
    return os.path.join(glb_dir, hit) if hit else None


# --------------------------------------------------------------------------
# 2. Blender side
# --------------------------------------------------------------------------
def _short(name: str, limit: int = 60) -> str:
    return name.encode("utf-8")[:limit].decode("utf-8", "ignore")


def build_in_blender(opts):
    if opts["tscn"]:
        tscn = opts["tscn"]
    else:
        tscn = find_scene(opts["project"])
    glb_dir = opts["glb_dir"] or os.path.dirname(os.path.abspath(tscn))
    print("Scene :", tscn)
    print("GLBs  :", glb_dir)

    ext, nodes, by_path = parse_tscn(tscn)
    root = next((n for n in nodes if n.parent is None), None)
    if root is None:
        raise RuntimeError("No root node found in the scene")
    print("Parsed: %d nodes, %d external resources" % (len(nodes), len(ext)))

    def tf(t):
        if t is None:
            return Matrix.Identity(4)
        if opts["transpose_basis"]:
            return Matrix(((t[0], t[3], t[6], t[9]), (t[1], t[4], t[7], t[10]),
                           (t[2], t[5], t[8], t[11]), (0, 0, 0, 1)))
        return Matrix(((t[0], t[1], t[2], t[9]), (t[3], t[4], t[5], t[10]),
                       (t[6], t[7], t[8], t[11]), (0, 0, 0, 1)))

    # glTF (Y-up) -> Blender (Z-up):  (x, y, z) -> (x, -z, y)
    C = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    C_INV = C.inverted()
    # What Godot does to the whole map, expressed in Blender space.
    # For Hitman maps this is the identity (Godot root rotation undoes the glTF swap).
    ROOT_MATRIX = C @ tf(root.transform)
    print("Root correction matrix (identity expected):")
    for r in ROOT_MATRIX:
        print("   ", [round(v, 4) for v in r])

    # ---- decide which nodes to build -------------------------------------
    excl = [re.compile(p) for p in opts["exclude"]]
    excluded = set()
    for n in nodes:
        if n.parent is None:
            continue
        if n.parent in excluded or any(rx.search(n.path) for rx in excl):
            excluded.add(n.path)

    inst_nodes = [n for n in nodes if n.instance_id is not None and n.path not in excluded]
    if opts["limit"]:
        inst_nodes = inst_nodes[: opts["limit"]]
    keep = set()
    if opts["keep_empties"]:
        keep = {n.path for n in nodes if n.path not in excluded}
    else:
        for n in inst_nodes:
            cur = n
            while cur is not None and cur.path not in keep:
                keep.add(cur.path)
                cur = by_path.get(cur.parent) if cur.parent is not None else None
    keep.add(root.path)
    print("Excluded %d nodes; placing %d models inside %d hierarchy nodes"
          % (len(excluded), len(inst_nodes), len(keep)))

    # ---- scene set-up ------------------------------------------------------
    if opts["clear"] and bpy.app.background:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    coll = bpy.data.collections.new(_short(os.path.splitext(os.path.basename(tscn))[0]))
    scene.collection.children.link(coll)

    # ---- hierarchy ---------------------------------------------------------
    objs = {}
    for n in nodes:
        if n.path not in keep:
            continue
        o = bpy.data.objects.new(_short(n.name), None)
        o.empty_display_type = "PLAIN_AXES"
        o.empty_display_size = 0.25
        coll.objects.link(o)
        if n.editor_description:
            o["glacier_ids"] = n.editor_description
        if n.parent is None:
            o.matrix_basis = ROOT_MATRIX
        else:
            o.parent = objs.get(n.parent)
            o.matrix_basis = tf(n.transform)
        objs[n.path] = o

    # ---- models ------------------------------------------------------------
    template_cache = {}      # glb path -> [(mesh data, matrix, name), ...]
    missing, placed = {}, 0

    def load_template(glb):
        if glb in template_cache:
            return template_cache[glb]
        before = set(bpy.data.objects.keys())
        bpy.ops.import_scene.gltf(filepath=glb)
        new = [bpy.data.objects[k] for k in bpy.data.objects.keys() if k not in before]
        items = []
        for o in new:
            if o.type == "MESH":
                items.append((o.data, o.matrix_world.copy(), o.name))
        for o in new:                      # drop everything the importer created
            bpy.data.objects.remove(o, do_unlink=True)
        template_cache[glb] = items
        return items

    for i, n in enumerate(inst_nodes):
        rel = ext.get(n.instance_id)
        if rel is None:
            missing[n.instance_id] = missing.get(n.instance_id, 0) + 1
            continue
        glb = resolve_glb(glb_dir, rel)
        if glb is None:
            missing[rel] = missing.get(rel, 0) + 1
            continue
        try:
            items = load_template(glb)
        except Exception as e:             # noqa
            print("ERROR importing", glb, e)
            missing[rel] = missing.get(rel, 0) + 1
            template_cache[glb] = []
            continue
        parent = objs[n.path]
        stem = os.path.basename(rel).split(".")[0]
        parent["prim"] = os.path.basename(rel)
        for k, (mesh, mw, oname) in enumerate(items):
            o = bpy.data.objects.new(_short("%s_%s" % (stem, k) if len(items) > 1 else stem), mesh)
            coll.objects.link(o)
            o.parent = parent
            o.matrix_basis = (C_INV @ mw) if opts["axis_fix"] else mw
            placed += 1
        if (i + 1) % 100 == 0:
            print("  placed %d / %d" % (i + 1, len(inst_nodes)))

    # ---- finish ------------------------------------------------------------
    for win in getattr(bpy.context.window_manager, "windows", []):
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                for sp in area.spaces:
                    if sp.type == "VIEW_3D":
                        sp.clip_end = 20000.0

    print("\nDone: %d mesh objects, %d unique models imported." % (placed, len(template_cache)))
    if missing:
        print("MISSING / FAILED resources:")
        for k, v in missing.items():
            print("   %s  (x%d)" % (k, v))
    if opts["save"]:
        bpy.ops.wm.save_as_mainfile(filepath=opts["save"], compress=True)
        print("Saved:", opts["save"])


# --------------------------------------------------------------------------
# 3. Entry point
# --------------------------------------------------------------------------
def get_options():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        return dict(CONFIG)
    ap = argparse.ArgumentParser(prog="godot_to_blender.py")
    ap.add_argument("--project", default="")
    ap.add_argument("--tscn", default="")
    ap.add_argument("--glb-dir", dest="glb_dir", default="")
    ap.add_argument("--save", default="")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--keep-empties", dest="keep_empties", action="store_true")
    ap.add_argument("--no-axis-fix", dest="axis_fix", action="store_false")
    ap.add_argument("--transpose-basis", dest="transpose_basis", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-clear", dest="clear", action="store_false")
    return vars(ap.parse_args(argv))


if __name__ == "__main__":
    if not IN_BLENDER:
        sys.exit("Run this script inside Blender:\n"
                 "  blender --background --python godot_to_blender.py -- --project <folder> --save out.blend")
    o = get_options()
    if not (o["project"] or o["tscn"]):
        sys.exit("Set CONFIG['project'] (or CONFIG['tscn']) at the top of the script, "
                 "or pass --project <folder>.")
    build_in_blender(o)
