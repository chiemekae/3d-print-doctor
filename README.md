# 3d-print-doctor

[![tests](https://github.com/chiemekae/3d-print-doctor/actions/workflows/tests.yml/badge.svg)](https://github.com/chiemekae/3d-print-doctor/actions/workflows/tests.yml)

An agent skill that turns Claude Code (or another agent that reads `SKILL.md` skills) into a print technician for a **Bambu Lab printer + OrcaSlicer on macOS**. It diagnoses failed prints from evidence, tunes print and filament settings one change at a time, watches running prints through the printer's camera, and keeps a print log so the second time a problem shows up it takes minutes, not an evening.

## What it does

- **Diagnoses failures** with a fixed loop: collect evidence (photos, camera, printer status, the exact settings that ran, your print history) → rank suspects → agree on one change and a small test print → apply → test → record. It stops after three failed tests and explains what's stuck instead of guessing.
- **Talks to the printer over the LAN**: status with HMS and error codes explained, camera snapshots and video clips, a self-made timelapse, files on the SD card, and (with your go-ahead each time) start, pause, resume, and stop.
- **Watches a print in the background** and alerts on pauses, new error codes, stalls, over-temperature, and the end of the job, with a camera snapshot for each event.
- **Edits OrcaSlicer presets and projects safely**: originals untouched, presets backed up first, every change verified in the sliced G-code.
- **Keeps a print log** filled from the sliced file itself (presets, material, temperatures, ~30 settings), so it records what actually ran. It answers "what worked last time for this PETG?" and can backfill your history from every job on the printer's SD card.

## Requirements

- **macOS**, with Apple's Command Line Tools (`/usr/bin/python3`, 3.9+). The scripts use only the standard library.
- **OrcaSlicer** (tested with 2.4.2), with the printer bound in its Device tab (LAN, access code).
- **ffmpeg** for the camera: `brew install ffmpeg`, and "LAN liveview" turned on in the printer's settings.
- **Starting, pausing, or stopping prints** from the agent needs the printer to accept third-party commands: on current Bambu firmware that means **LAN Only Mode + Developer Mode**. Status, camera, SD card, and the watch work without it.

### Printer compatibility

| Printer | Status, SD card, log, watch | Camera |
|---|---|---|
| X1 Carbon | tested | tested |
| X1, X1E | expected to work, untested | expected to work (same RTSPS camera), untested |
| P1P, P1S, A1, A1 mini | expected to work, untested | not supported (different camera protocol); use `watch --no-snap` |
| H2 series, P2S, X2D | untested | untested |

Reports from other printers are welcome.

## Install

```sh
git clone https://github.com/chiemekae/3d-print-doctor.git ~/code/3d-print-doctor
ln -s ~/code/3d-print-doctor/skills/3d-print-doctor ~/.claude/skills/3d-print-doctor   # Claude Code
```

For other agents, link it into whichever skills folder they read (for example `~/.agents/skills/`).

Then ask your agent to set it up ("set up 3d-print-doctor"), or run:

```sh
/usr/bin/python3 -I ~/code/3d-print-doctor/skills/3d-print-doctor/scripts/bbl.py setup
```

Setup finds your printer in OrcaSlicer, checks for ffmpeg, says whether your model's camera is supported, and creates the config.

## Configuration

`~/.config/3d-print-doctor/config.json` holds everything specific to you, and lives outside the repo:

```json
{
 "data_dir": "~/3d-print-doctor",
 "photo_inbox": null,
 "max_nozzle_c": 300,
 "max_bed_c": 110,
 "notes": [
  "Printer: X1 Carbon, 0.4 mm nozzle. TPU feeds from the external spool.",
  "My own presets are named 'Mine - …'; prefer them."
 ]
}
```

- `data_dir`: where the print log, watch events and snapshots, and preset backups go.
- `photo_inbox`: a folder where photos you send the agent land (for example from a phone-to-Mac sync), if you have one.
- `max_nozzle_c`, `max_bed_c`: your printer's ratings, for over-temperature alerts.
- `notes`: facts about your setup the agent should know every session. The agent adds to it as it learns, and tells you when it does.

## Safety

- The agent asks before **every** physical action (start, pause, resume, stop), checking the bed is clear and the right filament is loaded. The script refuses these commands without an explicit `--yes`.
- The printer's access code is read from OrcaSlicer's config and masked in all output. Nothing goes to the cloud: every connection is to the printer on your LAN.
- Original projects are never modified, and presets are backed up before any edit.

A printer is a hot machine that runs unattended for hours. Review what the agent proposes before you approve it.

## Why everything goes through Apple's binaries

macOS's Local Network privacy blocks programs like Homebrew's Python and ffmpeg from reaching LAN devices (`No route to host`), and in testing, adding those ad-hoc-signed binaries in System Settings didn't help. Apple's own `/usr/bin/openssl` and `/usr/bin/curl` are exempt, so the scripts speak MQTT through `openssl s_client`, read the SD card through `curl`, and relay the camera through a localhost proxy. Details are in [`references/printer-lan.md`](skills/3d-print-doctor/references/printer-lan.md).

## Development

```sh
/usr/bin/python3 -m unittest discover -s tests
```

The tests use synthetic printer states and sliced files; no printer needed.

CI runs these tests on macOS for every pull request, and `main` only accepts changes through pull requests whose tests pass.

## Credits

- The print watch's event logic is adapted from [heyixuan2/bambu-studio-ai](https://github.com/heyixuan2/bambu-studio-ai) (MIT); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- The print log's design (log every print, query what worked, consistent tags, check the log before advising) was inspired by [TrillyD13/3d-printing-skill](https://github.com/TrillyD13/3d-printing-skill).
- HMS code meanings come from the tables OrcaSlicer bundles; stage codes from the [ha-bambulab](https://github.com/greghesp/ha-bambulab) community docs.

## License

[MIT](LICENSE)
