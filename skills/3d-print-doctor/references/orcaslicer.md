# OrcaSlicer presets, projects, and slicing

## Where settings live

- **User presets:** `~/Library/Application Support/OrcaSlicer/user/default/{process,filament,machine}/<name>.json`, each with a `<name>.info` beside it.
  - The JSON holds only the user's overrides plus `"inherits": "<parent>"`.
  - To find a setting's effective value, read it from a sliced G-code header (every setting appears as `; key = value`) or from a project's `project_settings.config`. The inherits chain ends in system presets you can't read (below).
  - The user's own presets are the default choice for their printing. If they follow a naming habit, it's in the config's `notes`; if not, list this folder and ask which presets they use, then record the answer there.
- **System presets:** read-only, and they inherit from each other. They ship packed in `/Applications/OrcaSlicer.app/Contents/Resources/profiles/BBL.opc` (copied to `~/Library/Application Support/OrcaSlicer/system/`), a binary format that can't be read or grepped.
- **App state:** `OrcaSlicer.conf` (JSON plus an `# MD5` trailer). It holds the currently selected presets and the printer binding.

A setting's key name is whatever appears in a sliced G-code header or `project_settings.config`. Confirm a key exists there before you write it into a preset or project. Many filament keys are arrays, with one value per extruder or filament.

<details>
<summary>Older versions: OrcaSlicer 2.4 and earlier</summary>

System presets were plain JSON in `/Applications/OrcaSlicer.app/Contents/Resources/profiles/BBL/{process,filament,machine}/`, so you could walk a user preset's `inherits` chain through them and grep them for key names. The G-code header method above works on these versions too.
</details>

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
- **Start G-code:** `machine_start_gcode` and `filament_start_gcode` against the stock ones for this printer: slice any project of the user's own with their usual printer preset and compare the two G-code headers. Start G-code written for another printer or firmware can skip calibration or move the toolhead somewhere unexpected.

The usual fix is to keep the author's geometry and plate layout but re-select the user's own printer, filament, and process presets after opening the project, then slice again.

## Slicing from the command line

```
/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer --slice 0 --outputdir <dir> <project.3mf>   # → <dir>/plate_1.gcode
/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer --slice 0 --export-3mf <out.gcode.3mf> <project.3mf>   # printable package for bbl.py print
```

- **Header:** the G-code starts with `; key = value` lines covering every setting, plus `; model printing time:`, `; filament used [g]`, and `; max_z_height:`. Use them to verify a change and to estimate time and weight.
- **Warnings:** `Metadata/slice_info.config` inside the `.gcode.3mf` lists slicer warnings. For example, `bed_temperature_too_high_than_filament` means the bed is set above the filament's softening temperature (`temperature_vitrification`). It's a soft warning: OrcaSlicer's own base TPU profile sets softening at 30 °C and plates at 35 °C, so every stock TPU print raises it. Act on it only when the bed is well above the stock value, or when PLA or TPU runs long in a closed, warm chamber (then open the door or lift the top glass).
- **Settings source:** the command line slices with the project's embedded settings. After a user changes a preset, re-save the project in OrcaSlicer (or update `project_settings.config`) before slicing from the command line.

### Testing a setting

Before blaming a setting or changing it in a project, check that it changes this job at all. Slice a copy with the setting flipped and compare the motion G-code with the original slice, comment lines removed:

```
diff <(unzip -p a.gcode.3mf Metadata/plate_1.gcode | grep -v '^;') \
     <(unzip -p b.gcode.3mf Metadata/plate_1.gcode | grep -v '^;') | wc -l    # 0: no effect on this job
```

No difference means the setting is irrelevant to this job, however plausible it sounds. On the Knife print, "Flush into objects' support" looked like the reason PETG supports stuck to PLA, but turning it off produced identical G-code: every purge went into the purge block and the infill.

## Gotchas found so far

- **100% infill:** set `sparse_infill_pattern` to `zig-zag`, which OrcaSlicer reports as rectilinear. Grid and crosshatch don't support 100%.
- **Build volume:** read `printable_height` and `printable_area` from the project's `project_settings.config` or a sliced G-code header; OrcaSlicer's height can be a little under the spec sheet (250 mm on the X1 series, against 256 mm advertised). A part's orientation decides whether it fits and how its features print. Tall, thin TPU parts wobble, so prefer laying them flat.
- **TPU with an AMS:** regular TPU feeds from the external spool (`tray_now` 254); OrcaSlicer blocks filament type `TPU` in the AMS. The exception is Bambu's "TPU for AMS" (type `TPU-AMS`), which is allowed in AMS slots. Generic TPU's flow limit is around 3.2 mm³/s, so solid TPU parts take a long time. Estimate with the command-line slice before committing.
- **Mixed materials and flushing:** with "Flush into objects' infill" (`flush_into_infill`) on, purge from each filament change goes into the parts' sparse infill instead of the purge block. That's fine for color changes in one material. When a second material only prints supports or interfaces (PETG supports on PLA, the usual trick for clean support removal), it puts that material inside the parts, where it won't bond. Turn the setting off in the project copy; `platemap.py` warns about this case. "Flush into support" (`flush_into_support`) matters less, since supports get removed anyway.
- **Mixed materials heat the bed for the hottest one:** with `bed_temperature_formula` = `by_highest_temp` (the default), PLA parts with PETG supports get PETG's bed temperature (70 °C on textured PEI), and their bottoms soften. Fix it in the project copy: set the plate temperature (`textured_plate_temp` and `textured_plate_temp_initial_layer`, or the key for the plate in use) to one value both materials accept, such as 60 °C, or set the formula to `by_first_filament`. `platemap.py` warns when the bed runs well above the parts' own temperature.
- **Mixed print temperatures:** OrcaSlicer refuses to slice filaments whose print temperatures fall outside each other's range (PLA 190-240 °C against PETG 255 °C) unless "Remove mixed temperature restriction" is on in Preferences. The command line ignores that preference: pass `--allow-mix-temp`.
  - **When a user hits this error,** check what the second material prints (`support_filament`, `support_interface_filament`, and the objects' `extruder` in `model_settings.config`). If it prints only supports or interface, the mix is almost always deliberate: PETG and PLA don't bond, so a PETG interface at zero top gap peels cleanly off PLA. Say so, then offer the two real choices: keep it and allow mixed temperatures (the preference in the app, `--allow-mix-temp` on the command line), or print the supports in PLA with a top Z gap of about one layer height.
  - **Don't suggest moving the temperatures into the overlap** (PETG at 240 °C or less). It silences the check by printing one material outside its usual range, and it doesn't address why the project mixes materials. If the second material prints parts of the model, ask whether that's intended before suggesting anything.
- **Calibration prints:** OrcaSlicer's Calibration menu (temperature, flow rate, pressure advance, retraction, max volumetric speed, tolerance) only works in the app. Ask the user to run one, then read the result from their photo or a `snap`.
