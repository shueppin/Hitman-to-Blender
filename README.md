# Hitman-to-Blender
A pipeline to allow Hitman maps to be exported to Blender including their texture


## Usage
1. Download the CLI from [RPKG-Tool](https://github.com/glacier-modding/RPKG-Tool)
2. Find the hash for the map you want to export in [this list](map_hashes.md)
3. Run the RPKG CLI from the CMD for the map you want to export. Replace `$RUNTIME_FOLDER$` with the folder where your Hitman Runtime is stored (for example inside the Steam or EpicGames folder). Replace `$HASH$` with the hash of the map. Replace `$OUTPUT_DIR$` with the directory where you want the files to be stored.
```cmd
rpkg-cli.exe -export_map_textured "$RUNTIME_FOLDER$" -filter "$HASH$" -output_path "$OUTPUT_DIR$" -map_filters boxes=false,spheres=false,visible=false
```
4. Download [godot_to_blender.py](godot_to_blender.py) to be able to open the exported files with Blender and not just Godot
5. Run the conversion script from the CMD. Replace `$BLENDER$` with the path of your Blender executable (like `C:\Program Files\Blender Foundation\Blender x.x\blender.exe`). Replace `$INPUT_DIR$` with the directory that was created in the `$OUTPUT_DIR$` from the command before. Replace `$OUTPUT_BLEND$` with the output file for blender (this should have the extension `.blend`).
```cmd
"$BLENDER$" --python godot_to_blender.py -- --project "$INPUT_DIR$" --save "$OUTPUT_BLEND$"
```


## Future plans
- Transparent textures are not rendered correctly. The goal is to fix this. This probably means making changes to RPKG-Tool.
- It would be nice to have an easy interface for the whole finished pipeline.


## Notice
This project is purely for research purposes for private use.  
DO NOT PUBLISH THE MAPS since they are property of [IO Interactive](https://ioi.dk). 

