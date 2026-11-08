# Failure modes

Symptom → likely causes (most common first) → evidence that tells them apart → the levers to try. Lever names are OrcaSlicer keys. Confirm each key in a profile before editing (see orcaslicer.md). The `tag` beside each symptom is its issue tag in the print log (`printlog.py tags`).

Wet filament and a dirty plate cause a large share of failures, so rule them out before reaching for a setting: a setting change on wet filament treats the symptom and teaches the log the wrong lesson.

## Wet filament first

Ask about moisture before changing settings for stringing, weak layers, rough or bubbly surfaces, popping or hissing at the nozzle, or uneven extrusion. Moisture causes all of these, and no setting compensates for it. Evidence: how long the spool has been out, the AMS humidity in `bbl.py status`, steam or popping in a `clip`, and stringing that doesn't respond to retraction changes.

Typical drying, below each material's softening point so the spool doesn't deform (the spool's label or the maker's page wins when it differs):

| Material | Temperature | Time |
|---|---|---|
| PLA | 45–55 °C | 4–6 h |
| PETG | 60–65 °C | 6–8 h |
| TPU | 50–60 °C | 8–12 h |
| ABS / ASA | 65–75 °C | 4–6 h |
| Nylon (PA) | 70–80 °C | 12 h+ |

The original AMS has no heater, so drying needs a separate dryer; AMS 2 Pro and AMS HT can dry in place. Store dried spools with desiccant; an open spool takes moisture back in days.

## First layer and adhesion

| Symptom | Likely causes | Evidence | Levers |
|---|---|---|---|
| Part detached, spaghetti (`detached`, `spaghetti`) | adhesion lost; corner warp leading to detachment; nozzle knocked a curled edge | where on the plate it let go; the first-layer timelapse; oil from fingerprints on the plate | wash the plate with dish soap (isopropyl alone smears the oil around); `<plate>_plate_temp_initial_layer`; `brim_type` / `brim_width` before a raft (`raft_layers` costs far more time); `initial_layer_speed`; glue stick for PETG/TPU on smooth PEI |
| Corners lift (`warping`) | material shrinkage (ABS, ASA, PA, PC); drafts; bed too cool | lift grows with height; the room is cold or the door is open for high-temperature material | enclosure closed and preheated for ABS-class material; bed temperature; `brim_width`; rounded corners in the model; `fan_max_speed` lower |
| Elephant foot (`elephant-foot`) | first layer squished; bed too hot | bottom edge bulges only in the first layers | `elefant_foot_compensation`; bed temperature down 5 °C |
| Rough or gappy first layer (`first-layer`) | Z offset or bed mesh off; plate type mismatch | gaps between lines (too high) or ridges and scraping (too low) | bed leveling on; the right plate selected (`curr_bed_type`); `initial_layer_print_height` |

## Extrusion

| Symptom | Likely causes | Evidence | Levers |
|---|---|---|---|
| Under-extrusion, gaps, weak walls (`under-extrusion`) | flow-rate limit exceeded; partial clog or heat creep; wet filament; tangled spool | worse on fast or thick sections; clicking extruder; popping sounds | `filament_max_volumetric_speed` down; `nozzle_temperature` up 5–10 °C; dry the filament; flow-rate calibration (`filament_flow_ratio`) |
| Over-extrusion, rough top, blobs (`over-extrusion`) | flow ratio high; pressure advance off | ridges on top surfaces; bulging corners | `filament_flow_ratio`; pressure advance (`enable_pressure_advance`, `pressure_advance`) calibration |
| Stringing (`stringing`) | wet filament; temperature high; too little retraction | fine hairs between islands; worse after the spool sits out | dry the filament first; `nozzle_temperature` down in 5 °C steps; `filament_retraction_length` and `filament_retraction_speed` (keep them short for TPU, where temperature and travel speed matter more); `wipe` |
| Zits and a visible seam (`zits-seam`) | seam placement; pressure at the start and end of loops | dots lined up on one side | `seam_position`; `seam_gap`; `wipe_distance`; pressure advance |
| Mid-print stop extruding, clog (`clog`) | heat creep (PLA/TPU in a warm enclosure); wet or brittle filament; spool snag | stage 35 or a heatbreak-fan HMS code (`bbl.py code` gives the meaning); chamber temperature high; bed set well above the profile's stock value | door open or top glass off; `during_print_exhaust_fan_speed`; bed back to the stock value; clear the hotend (user task) |
| Color bleed, purge waste (`color-bleed`) | too little flush between colors; dark-to-light changes; wet filament stringing across the prime tower | the new color is tinted for the first layers after a change; strings on the tower | `flush_multiplier` or the per-pair `flush_volumes_matrix`; order colors light to dark where the model allows; `flush_into_infill` / `flush_into_support` / `flush_into_objects` to reuse purge; `prime_volume` |

## Motion and geometry

| Symptom | Likely causes | Evidence | Levers |
|---|---|---|---|
| Layer shift (`layer-shift`) | nozzle hit curled-up plastic; speed or acceleration too high for the part; loose belt | `clip` around the shift height; curl visible before it | `z_hop` / `z_hop_types`; `slowdown_for_curled_perimeters`; lower `outer_wall_speed` and `default_acceleration`; belt check (user) |
| Ringing, ghosting (`ringing`) | acceleration high; vibration compensation stale | ripples after corners, in the direction of motion | `bbl.py print --vibration` (runs vibration compensation first); `outer_wall_acceleration` |
| Z banding (`z-banding`) | binding or dirty Z axis; inconsistent extrusion | horizontal bands at a regular height interval on every side | measure the band spacing: a regular mechanical pitch points at the Z axis (clean and lubricate, user task); irregular bands point at extrusion (see Under-extrusion) |
| Overhangs curl or droop (`overhang-curl`) | cooling short; overhang speed high; angle beyond the material | worse on the side away from the fan; steep slopes | `overhang_fan_speed` / `overhang_fan_threshold`; `overhang_1_4_speed` … `overhang_4_4_speed`; `enable_support`; reorient the part |
| Bridges sag (`bridge-sag`) | flow and cooling on bridges | strands hang between supports | `bridge_flow`; `bridge_speed`; fan; shorter span by orientation |
| Dimensions off, holes tight (`dimensions`) | shrinkage; flow; elephant foot | measure with calipers on a known feature | `xy_hole_compensation` / `xy_contour_compensation`; flow calibration. For anything that has to fit (magnets, bearings, inserts, a rim), print a small test piece of just that feature first |

## Strength and surfaces

| Symptom | Likely causes | Evidence | Levers |
|---|---|---|---|
| Layers split or delaminate (`delamination`) | layer adhesion: temperature too low or cooling too high; wet filament; layer too tall for the nozzle; drafts (ABS) | break follows a layer line | `nozzle_temperature` up; `fan_max_speed` down (PETG, ABS, ASA, PA want little fan); `layer_height` at most about 75% of the nozzle diameter; enclosure; reorient so the load runs along layers |
| Pillowing or holes in the top (`pillowing`) | too few top layers over sparse infill; low infill | dimples over infill gaps | `top_shell_layers` / `top_shell_thickness`; `sparse_infill_density`; `ironing_type` |
| Walls not bonded to infill (`wall-gaps`) | overlap low; speed difference | infill visible through the wall seam | `infill_wall_overlap`; `wall_loops` |
| Water or air leaks through a part (`leaks`) | sparse infill and thin shells | — | more `wall_loops`; 100% infill (`zig-zag` pattern) |
| Interface stays on the part, mixed materials (`support-removal`) | branches weaker than the interface's grip (thin tree branches snap first); support standing on the part, wedged into notches and slots; possibly, for PETG on PLA, hot PETG printed onto PLA where supports stand on the part | the support body breaks off and a sheet of interface, or a plug in a notch, stays behind | peel the interface as a separate step: lift an edge with a fingernail, tweezers, or a thin blade. In notches and functional features (locks, rails, slots), test the fit before cleaning, and use a pick or hobby knife rather than flush cutters, which gouge the walls. No heat: PLA softens before PETG does. For a narrow channel supported end to end, try a support blocker and check whether it bridges cleanly in the preview. A zero top Z gap is correct here; don't widen it as you would for one material |
| Supports won't come off (`support-removal`) | top Z gap too small (usually this); interface too dense; flexible material | support fused across the whole contact face | `support_top_z_distance` about one layer height for rigid materials; `support_interface_spacing` up or `support_interface_top_layers` down; `support_type` tree for organic shapes, normal under flat overhangs. TPU fuses to supports whatever the settings: reorient the part to avoid them |

## Material notes

- **TPU:** slow (2–4 mm³/s on generic profiles); short retraction; external spool on AMS printers, except Bambu's "TPU for AMS". OrcaSlicer advises a cold pull before TPU to avoid clogs (the printer has a cold-pull maintenance routine). It prints well on textured PEI. It's very hygroscopic, which shows up as fuzzy stringing and popping.
- **PETG:** sticks too hard to smooth PEI, so use glue stick as a release layer. Little part cooling; full fan gives weak layers. It strings; dry it first, then lower the temperature.
- **ABS/ASA:** enclosure closed, chamber warm, no drafts. It warps on big flat parts, so use a brim.
- **PLA:** heat creep in a closed hot chamber, so open the door or top for long PLA prints.
- **Nylon (PA):** takes up enough moisture in a few hours to ruin a print; dry right before printing and feed from a dry box.

When symptoms point to nothing here, treat it as a new failure mode: diagnose from evidence, add a row once it's solved, and add its tag to `TAGS` in `scripts/printlog.py`.
