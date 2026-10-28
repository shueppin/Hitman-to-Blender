# Hitman-to-Blender
A pipeline to allow Hitman maps to be exported to Blender including their texture


## Usage
1. Download the CLI from [our fork of the RPKG-Tool](https://github.com/shueppin/RPKG-Tool). This fork supports extracting maps with transparent textures (the original RPKG-Tool doesn't).
2. Find the hash for the map you want to export in [this list](map_hashes.md)
3. Run the RPKG CLI from the CMD for the map you want to export. Replace `$RUNTIME_FOLDER$` with the folder where your Hitman Runtime is stored (for example inside the Steam or EpicGames folder). Replace `$HASH$` with the hash of the map. Replace `$OUTPUT_DIR$` with the directory where you want the files to be stored.
```cmd
rpkg-cli.exe -export_map_textured "$RUNTIME_FOLDER$" -filter "$HASH$" -output_path "$OUTPUT_DIR$" -map_filters boxes=false,spheres=false,visible=false
```
4. Download [godot_to_blender.py](godot_to_blender.py) to be able to open the exported files with Blender and not just Godot
5. Run the conversion script from the CMD. Replace `$BLENDER$` with the path of your Blender executable (like `C:\Program Files\Blender Foundation\Blender x.x\blender.exe`). Replace `$INPUT_DIR$` with the directory that was created in the `$OUTPUT_DIR$` from the command before. Replace `$TEMP_BLEND$` with the temporary output file for blender (this should have the extension `.blend`).
```cmd
"$BLENDER$" --python godot_to_blender.py -- --project "$INPUT_DIR$" --save "$TEMP_BLEND$"
```
6. Download [fix_alpha.py](fix_alpha.py) to add an alpha channel to the transparent textures
7. Run the alpha fix script from the CMD. Replace `$BLENDER$` with the path of your Blender executable (like `C:\Program Files\Blender Foundation\Blender x.x\blender.exe`). Replace `$TEMP_BLEND$` with the file that was created from the command before. Replace `$FINAL_BLEND$` with the final output file for blender (this should have the extension `.blend`).
```cmd
"$BLENDER$" "$TEMP_BLEND$" --python fix_alpha.py -- --save "$FINAL_BLEND$"
```
(Both blender scripts can be run in the background with the argument `--background`)


## Future plans
- It would be nice to have an easy interface for the whole finished pipeline.


## Notice
This project is purely for research purposes for private use.  
DO NOT PUBLISH THE MAPS since they are property of [IO Interactive](https://ioi.dk). 

