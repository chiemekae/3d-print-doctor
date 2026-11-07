# OrcaSlicer presets, projects, and slicing

## Where settings live

- **User presets:** `~/Library/Application Support/OrcaSlicer/user/default/{process,filament,machine}/<name>.json`, each with a `<name>.info` beside it.
  - The JSON holds only the user's overrides plus `"inherits": "<parent>"`.
  - To find a setting's effective value, walk the inherits chain into the system profiles.
  - The user's own presets are the default choice for their printing. If they follow a naming habit, it's in the config's `notes`; if not, list this folder and ask which presets they use, then record the answer there.
- **System presets:** `/Applications/OrcaSlicer.app/Contents/Resources/profiles/BBL/{process,filament,machine}/`. These also inherit from each other, and are read-only.
- **App state:** `OrcaSlicer.conf` (JSON plus an `# MD5` trailer). It holds the currently selected presets and the printer binding.

A setting's key name is whatever appears in these JSON files. Grep a system profile to confirm a key exists before you write it into a preset. Many filament keys are arrays, with one value per extruder or filament.

## Editing a preset

1. Ask the user to quit OrcaSlicer. It keeps presets in memory and writes its own copy back when presets are saved, so edits made while it's running get lost.
2. Copy the `.json` and `.info` to `<data_dir>/preset-backups/<YYYY-MM-DD>/` (`data_dir` from the config).
3. Edit only the keys for the agreed change, keeping the file's JSON formatting.
4. Tell the user which preset and keys changed. Their next OrcaSlicer start picks it up.

For a single print, prefer changing the project copy instead (below). It leaves the preset untouched for every other part.

## Project 3MFs

A project is a zip archive containing:
- **`3D/3dmodel.model`**: the build items. The `transform` is the placement on the plate, written as a 3×4 matrix in 3MF's row-vector convention.
- **`3D/Objects/*.model`**: the meshes.
- **`Metadata/project_settings.config`**: one flat JSON with every setting. **When slicing a project, these values win over the live presets.**
  - `print_settings_id`, `filament_settings_id`, and `printer_settings_id` name the presets the project was set up with.
  - `different_settings_to_system` is a list with one entry each for print, filament(s), and printer. Each entry holds `;`-joined keys that differ from the system preset. Add a key there when you change it, so OrcaSlicer shows it as modified.
- **`Metadata/model_settings.config`**: per-object and per-part overrides (`<metadata key=... value=...>`), plus a plate and assemble copy of the transform.

To edit a project, unzip a copy, change only the needed members, and re-zip in the original member order. Verify by diffing every member against the original. Only the members you meant to change should differ.

## Downloaded projects

A project 3MF from MakerWorld or another person carries its author's settings, and they win when it's sliced: their process and filament values, sometimes another printer or nozzle, and possibly their own start G-code. When a downloaded project fails, compare it with the user's setup before diagnosing anything else:
- **Presets:** `printer_settings_id`, `print_settings_id`, and `filament_settings_id` against the user's presets and the filament actually loaded.
- **Author's changes:** `different_settings_to_system` lists every key the author changed from the system presets. Each one is a suspect.
- **Start G-code:** `machine_start_gcode` and `filament_start_gcode` against the system profile for this printer (walk the `inherits` chain). Start G-code written for another printer or firmware can skip calibration or move the toolhead somewhere unexpected.

The usual fix is to keep the author's geometry and plate layout but re-select the user's own printer, filament, and process presets after opening the project, then slice again.

## Slicing from the command line

```
/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer --slice 0 --outputdir <dir> <project.3mf>   # → <dir>/plate_1.gcode
/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer --slice 0 --export-3mf <out.gcode.3mf> <project.3mf>   # printable package for bbl.py print
```

- **Header:** the G-code starts with `; key = value` lines covering every setting, plus `; model printing time:`, `; filament used [g]`, and `; max_z_height:`. Use them to verify a change and to estimate time and weight.
- **Warnings:** `Metadata/slice_info.config` inside the `.gcode.3mf` lists slicer warnings. For example, `bed_temperature_too_high_than_filament` means the bed is set above the filament's softening temperature (`temperature_vitrification`). It's a soft warning: OrcaSlicer's own base TPU profile sets softening at 30 °C and plates at 35 °C, so every stock TPU print raises it. Act on it only when the bed is well above the stock value, or when PLA or TPU runs long in a closed, warm chamber (then open the door or lift the top glass).
- **Settings source:** the command line slices with the project's embedded settings. After a user changes a preset, re-save the project in OrcaSlicer (or update `project_settings.config`) before slicing from the command line.

## Gotchas found so far

- **100% infill:** set `sparse_infill_pattern` to `zig-zag`, which OrcaSlicer reports as rectilinear. Grid and crosshatch don't support 100%.
- **Build volume:** read `printable_height` and `printable_area` from the project's `project_settings.config` (or the machine preset's inherits chain); OrcaSlicer's height can be a little under the spec sheet (250 mm on the X1 series, against 256 mm advertised). A part's orientation decides whether it fits and how its features print. Tall, thin TPU parts wobble, so prefer laying them flat.
- **TPU with an AMS:** regular TPU feeds from the external spool (`tray_now` 254); OrcaSlicer blocks filament type `TPU` in the AMS. The exception is Bambu's "TPU for AMS" (type `TPU-AMS`), which is allowed in AMS slots. Generic TPU's flow limit is around 3.2 mm³/s, so solid TPU parts take a long time. Estimate with the command-line slice before committing.
- **Calibration prints:** OrcaSlicer's Calibration menu (temperature, flow rate, pressure advance, retraction, max volumetric speed, tolerance) only works in the app. Ask the user to run one, then read the result from their photo or a `snap`.
