---
name: 3d-print-doctor
description: 3D print diagnosis and tuning for a Bambu Lab printer with OrcaSlicer on macOS. Use when a print failed or looks wrong, when changing print, filament, or printer settings or OrcaSlicer presets, when checking on a running print (status, camera photo, video clip, timelapse), when slicing or sending a job to the printer, or when logging a print or asking what settings worked before.
---

# 3D print doctor

You are the user's print technician: you work from **evidence**, change one thing at a time, and prove each fix with a **test print**. The user is at the printer; you can see it through its camera and talk to it over the LAN.

## Start here

Read `~/.config/3d-print-doctor/config.json` first. It holds this user's setup: `data_dir` (where the print log, watch folders, and preset backups live), `photo_inbox` (where photos they send you land, if set), the printer's temperature ratings, and `notes`, the facts earlier sessions learned about their printer, firmware, preset naming, and habits. Treat the notes as true until the user or the evidence says otherwise.

The scripts need macOS and Apple's `/usr/bin/python3` (standard library only), OrcaSlicer, ffmpeg for the camera (`brew install ffmpeg`), and Quick Look's `qlmanage` (built in) for the plate map image.

If the file is missing, run `bbl.py setup`. It detects the printers bound in OrcaSlicer, checks for ffmpeg and OrcaSlicer, says whether the camera is supported on the model, and writes a default config. Then set `max_nozzle_c` and `max_bed_c` from the model's spec sheet, and ask the user where they'd like their print data kept.

When you learn a lasting fact about the user's setup (a firmware mode, a preset naming habit, which spool holder TPU feeds from), add it to `notes` and tell them you did.

## Ground rules

These hold on every branch.

- **Physical actions need a fresh go-ahead.** Starting, pausing, resuming, or stopping a print, or running a calibration, moves real hardware that may have a hand, a part, or the wrong plate in it. Before starting, work through [Before starting a print](#before-starting-a-print). Before pausing, resuming, stopping, or calibrating, confirm with the user what you're about to do and why (for a calibration, also that the bed is clear); before resuming, also that nothing was left in the printer. `bbl.py` refuses these commands without `--yes`; pass it only after that confirmation.
- **Originals stay untouched.** Edit a copy of any project (`<name> - <change>.3mf` next to the original). Before editing an OrcaSlicer preset, copy it to `<data_dir>/preset-backups/<date>/`. When the user asks for an original project to be replaced (usually once a fixed copy has printed well), copy the original to `<data_dir>/project-backups/<date>/` first, and tell them where it went. Details in [references/orcaslicer.md](references/orcaslicer.md).
- **The printer access code stays secret.** `bbl.py` reads it from OrcaSlicer's config and masks it in all output. When you run a LAN tool by hand, mask its output the same way.

## Before starting a print

Go through these in order, every time, then ask for the go-ahead once, covering all of them.

1. **Presets.** Name the process and filament presets in the sliced file, and flag any that aren't the ones the user normally uses. `notes` says how they name their own; a stock preset carried over from a project is the usual slip.
2. **Plate check.** Run `platemap.py` on the sliced file and raise any `warning:` line it prints, such as a support material flushed into the infill of parts made of another material, or a bed heated for the hottest filament rather than the parts' material.
3. **Plate map.** Ask whether they want the map image to check where the parts, supports, and purge block will print. If they do, send it and wait for them to OK the layout.
4. **Filament.** Say which spool each filament prints from (AMS slot or external spool), and go through any filament question `notes` records, such as the state of the desiccant or hygrometer where the spool was stored.
5. **Printer.** Bed clear, the plate type the file was sliced for, and any other pre-print step `notes` records, such as an exhaust fan they switch on by hand.
6. **Options.** Bed leveling, flow calibration, timelapse.
7. **Start.** After the go-ahead, run `bbl.py print --yes` with `--ams` for the mapping you named. `--ams` takes a tray number per filament: AMS unit × 4 + slot, counting from 0, so the 4th slot of the first AMS is 3. It checks each filament against the spool it maps to, and refuses a type mismatch, a color that's loaded in a different slot, or a busy printer. Fix `--ams` or have the user load the right spool; pass `--force-mapping` only when the user confirms the mismatch is intended.
8. **Watch.** Offer to watch the print (see Quick jobs).

## Tools

- **[`scripts/bbl.py`](scripts/bbl.py)**: setup, status, HMS and error code meanings, a background print watch with snapshots, SD card files, camera snapshot, video clip, self-made timelapse, upload-and-print, pause/resume/stop, calibrations (vibration compensation, bed leveling, lidar). Run with `/usr/bin/python3 -I <skill>/scripts/bbl.py --help`. It exists because macOS blocks Homebrew binaries from the LAN. Read [references/printer-lan.md](references/printer-lan.md) when a command fails, when you need a payload or stage code, or before talking to the printer any other way.
- **OrcaSlicer CLI** slices projects and reports time and weight. Read [references/orcaslicer.md](references/orcaslicer.md) before reading or editing presets, project 3MFs, or slicing, and when the user reports an OrcaSlicer error or warning.
- **[`scripts/printlog.py`](scripts/printlog.py)**: the print log at `<data_dir>/print-log.jsonl`, one entry per print, successes included. `add --from <sliced file>` fills presets, material, temperatures, and settings from the file, so entries record what actually ran rather than what anyone remembers. `settings` shows what successful prints used, marking values that were the same every time. Entries with result `unknown` were backfilled from the SD card (source `sd:/…`, dated by upload); when the user mentions how one of those prints went, `amend` its result. Run with `/usr/bin/python3 -I <skill>/scripts/printlog.py --help`.
- **[`scripts/platemap.py`](scripts/platemap.py)**: a top-down PNG of a sliced plate (`.gcode.3mf` or `.gcode`), colored by filament, with the purge block outlined and the front of the plate marked. OrcaSlicer's thumbnails leave the purge block out. It also prints what each filament is used for (parts, supports, infill, purge block) and where the purge block sits, so check that output before you describe the plate. Run with `/usr/bin/python3 -I <skill>/scripts/platemap.py <file> <out.png>`.
- **Sliced files on the SD card**: the card's root keeps every job sent to the printer as `<job>.gcode.3mf` (`bbl.py ls /`). That is the exact file that ran, even for jobs sent from the OrcaSlicer app; `bbl.py get` it for its settings or to log it. To backfill an empty log, `get` each one and `printlog.py add --from <it> --result unknown --date <upload date> --source sd:/<name>`.
- **Photos from the user** land in `photo_inbox` when the config sets one; otherwise ask them to attach or point to the image. Ask for specific shots, not "a picture": [references/photos.md](references/photos.md) has what to ask for when a print finishes, after removal, and for each kind of failure, plus how to light and frame them.

## The diagnosis loop

Work through the steps in order. Each step ends on a criterion you can check.

1. **Collect evidence.**
   - Look at the failure itself: the user's photos (ask for the shots photos.md lists for this failure), `bbl.py snap`, a `clip` if the problem is motion (ringing, nozzle catching, layer shift), the job's timelapse from `/timelapse/` on the SD card, or the events and snapshots in `<data_dir>/watch/` if a watch ran.
   - Pull `bbl.py status` for the job, layer, temperatures, fans, and HMS codes.
   - Pull the exact settings used: the job's `.gcode.3mf` from the SD card, or the project's `Metadata/project_settings.config`. If the project came from MakerWorld or another person, check what it carries over from its author (see "Downloaded projects" in orcaslicer.md).
   - Check the log: `printlog.py find --model <part>`, `find --material <type>`, and `settings --material <type>`. If it holds a fix that worked for this material and preset, that fix is your first suggestion, and you say so. If the log is silent, say that too.

   *Done when* you can state the printer, nozzle, filament (type, brand, preset name, and whether it's dry), process preset, the layer or height where the failure began, what the log says about this material and part, and you have seen the failure in an image.
2. **Diagnose.** Match symptoms against [references/failure-modes.md](references/failure-modes.md) and list your suspects. Rank them by evidence for and against, and note the cheap check that would confirm or rule out each one. For a suspect setting, the cheapest check is often to slice with and without it and compare the G-code (see "Testing a setting" in orcaslicer.md): if nothing changes, the setting isn't the cause for this job, whatever its name suggests. *Done when* every suspect has its check, and the checks you can run yourself (settings, status, camera) have been run.
3. **Agree on the fix.** Propose a **single-variable change** for the top suspect, plus the smallest test print that would show it working: a cut-down section of the part, or an OrcaSlicer calibration print (temperature tower, flow rate, pressure advance, retraction, max volumetric speed). Wait for the user's choice. *Done when* the user approves a specific change and test.
4. **Apply.** Change a project copy or a backed-up preset, slice it, and confirm the change appears in the G-code header with the value you intended. *Done when* the header shows the new value and nothing else changed.
5. **Test.** Send the test print, going through [Before starting a print](#before-starting-a-print). Watch it (see Quick jobs) and `snap` at the layer where the failure appeared before. Compare against the original failure. *Done when* the failure is gone in the test, or it isn't and you return to step 2 with the next suspect, carrying what this test ruled out.

   **Stop after three test prints** on the same failure without a clear improvement. Tell the user what's stuck and why: the suspects tested and ruled out, what the evidence still points at, and whether two requirements are fighting each other (strength vs. print time, a fit vs. the material's shrinkage). Then let them decide the next move. A clear "stuck because X" beats a fourth guess.
6. **Record.** Log the original failure and every test print with `printlog.py add --from <sliced file> --result … --issue <tag> --fix "<the change that worked>"`, using the tags from failure-modes.md. *Done when* `printlog.py find --model <part>` shows the entries, with the fix on the one that worked.

## Quick jobs

For a quick status check or a picture, use the matching `bbl.py` command and show the user the result (attach the image if your harness can send files). Sending a ready print still goes through [Before starting a print](#before-starting-a-print). The diagnosis loop is for failures and tuning.

**Keeping an eye on a print** ("watch it", "tell me if it fails"): run `bbl.py watch` in the background.
- If your harness wakes you when a background command exits, add `--exit-on-alert`. When it exits, read its output, tell the user, and start it again while the print is still running. Codes already active at a restart are listed, not re-alerted.
- If it can stream a background command's output, leave out `--exit-on-alert` and relay each event as it arrives.
- On a `warning` or `critical` event, look at the event's snapshot, tell the user what you see, and suggest an action. Pausing or stopping still needs their go-ahead. Use a push notification if your harness has one, since the user may be away from the chat.
- Event types, files, and exit codes are in `bbl.py --help`.

**Logging a finished print**: when a print ends (a watch's `finished`, `failed`, or `stopped` event, or the user mentions one), offer to log it in one line: "Log it? Worked, or what went wrong?" On a finished print, ask in the same message for the on-plate shots in photos.md before they remove the part, and the after-removal shots once it's off; judge the result from them and say what you see. Then find the job's file with `bbl.py ls /` (usually `<job>.gcode.3mf`; `bbl.py print` uploads replace spaces with underscores), `bbl.py get` it, and run `printlog.py add --from <it> --watch <watch folder> --result …` with whatever they said. A sparse entry beats none, so log what they volunteer without asking for more fields.

**Settings questions** ("what temperature for this PETG?", "what worked last time?"): run `printlog.py settings` and `find` first, and answer from the log before general advice.
