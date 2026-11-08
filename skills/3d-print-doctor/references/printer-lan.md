# Printer over the LAN

How `scripts/bbl.py` reaches the printer, and what to know when it fails or when you need something it doesn't do.

## Why everything goes through Apple binaries

macOS Local Network privacy blocks connections from non-Apple programs to LAN addresses, and the failure shows up as `No route to host` (errno 65) while `ping` and `nc` work. Each process in an agent's shell chain is its own responsible process, so the permission has to be on the program making the connection. Homebrew's Python.app and ffmpeg are ad-hoc signed, and adding them under System Settings → Privacy & Security → Local Network had no effect (tested 2026-11). Apple platform binaries are exempt, so:

- **MQTT** (status, commands) runs over `/usr/bin/openssl s_client` on port 8883.
- **FTPS** (SD card) runs over `/usr/bin/curl` on port 990, implicit TLS, user `bblp`. The password is passed in a temporary 0600 netrc file so it stays out of `ps`.
- **Camera** (RTSPS on port 322, needs "LAN liveview" on in the printer's settings) goes through a localhost relay: ffmpeg → `127.0.0.1` → openssl → printer. The relay rewrites the printer URL to an equal-length localhost URL (the server's replies point ffmpeg back at the printer IP otherwise). It leaves the `Authorization` header untouched, because digest auth hashes the client's URI.

The printer's TLS certificate is issued by "BBL CA" to its serial number. That's how to confirm you're talking to the printer.

**Orphaned `openssl` processes spin at 100% CPU.** `-quiet` implies `-ign_eof`, so an `s_client` whose parent died keeps its live printer session and busy-loops on its closed stdin. The symptom is loud fans and a high load average with `openssl` at the top of the CPU list. `bbl.py` passes `-no_ign_eof`, so its children exit within seconds even when `bbl.py` is SIGKILLed (tested). Rules that follow:
- Reach the printer through `bbl.py`. Any `openssl s_client` you start by hand also gets `-no_ign_eof`.
- After LAN work, especially a killed or timed-out command, check for leftovers: `ps -axo pid,ppid,etime,%cpu,args | grep '[s]_client'`. A PPID of 1 or a high %CPU is a leak; kill it, but leave the child of a running `bbl.py watch` alone.

## When commands are ignored

Since Bambu's January 2025 firmware, the printer accepts control commands (start, pause, resume, stop) from third-party software only in **LAN Only Mode with Developer Mode on**. Reading status, the camera, and the SD card work in either mode. Printers on older firmware, or on X1Plus community firmware (an `x1plus/` folder on the SD card), may accept commands without it.

If `print`, `pause`, or `stop` connects fine but the printer doesn't act on it (`gcode_state` unchanged in the output), the mode or firmware is the first suspect: ask the user to check Settings → Network on the printer screen. When you find out which applies, record it in the config's `notes`.

## Connection details

All of these come from `~/Library/Application Support/OrcaSlicer/OrcaSlicer.conf`, which is JSON followed by a `# MD5` trailer:
- `local_machines.<serial>.dev_ip`: the printer's IP
- `local_machines.<serial>.dev_name`: its name
- `user_access_code.<serial>`: the LAN access code

If the printer gets a new IP or access code, re-binding it in OrcaSlicer's Device tab updates the file.

## Status fields

`bbl.py status` summarizes the MQTT `print` report:
- **`gcode_state`**: one of `IDLE`, `PREPARE`, `RUNNING`, `PAUSE`, `FINISH`, `FAILED`.
- **`tray_now`**: `254` means the external spool; 0–15 means an AMS slot.
- **`print_error`**: the printer's error code as 8 hex digits (e.g. `0300400C`), or null.
- **`hms`**: Health Management System codes, formatted `AAAA-BBBB-CCCC-DDDD`.
- **Code meanings** (`meaning` beside each code, and `bbl.py code CODE`) come from OrcaSlicer's bundled HMS tables in `OrcaSlicer.app/Contents/Resources/hms/`. Those tables are per printer model, keyed by the first three characters of the serial. When the printer's own table isn't bundled (the X1 Carbon's isn't, in OrcaSlicer 2.4), the most common text across the other models is used and marked "approximate". They are usually right, but wording varies by model. When a code drives a decision, confirm it on the printer screen, in Bambu Handy, or on wiki.bambulab.com. Report a code with no meaning as unknown rather than guessing.
- **`stage`** (`stg_cur`): codes from community docs (ha-bambulab). Confirm against the printer screen when it matters.

| Stage | Meaning |
|---|---|
| -1 / 255 | idle |
| 0 | printing |
| 1 | auto bed leveling |
| 2 | heatbed preheating |
| 3 | vibration compensation |
| 4 | changing filament |
| 7 | heating hotend |
| 8 | calibrating extrusion |
| 9 | scanning bed surface |
| 10 | first layer inspection |
| 13 | homing |
| 14 | cleaning nozzle |
| 16 | paused by user |
| 17 | front cover fell off |
| 20 | nozzle temperature fault |
| 21 | bed temperature fault |
| 27 | heatbreak fan too slow |
| 34 | first layer error |
| 35 | nozzle clog |

## SD card layout

- `/`: every job sent to the printer (`*.gcode.3mf`); file dates are upload dates. Possibly also firmware files (`*.x1p`, `x1plus/`) and filesystem-repair leftovers (`FSCK*.REC`); leave those alone.
- `/timelapse/`: `video_<date>_<time>.mp4`. These exist only for jobs started with timelapse on. Fetch one with `bbl.py get /timelapse/<file> <local>`.
- `/ipcam/`: camera recordings, when recording is enabled on the printer.

## Request payloads

These are what `bbl.py` publishes to `device/<serial>/request`, for when you need a variant.

- **Start a job (`print`):** `{"print": {"command": "project_file", "param": "Metadata/plate_<n>.gcode", "url": "file:///sdcard/<file>.gcode.3mf", "md5": "<md5 of that plate's gcode>", "bed_leveling": true, "flow_cali": true, "timelapse": false, "use_ams": false, "ams_mapping": [0], ...}}`
  - Use `"use_ams": false` for the external spool.
  - With the AMS, `ams_mapping` lists the tray number (0–15) for each filament in project order. Tray number = AMS unit × 4 + slot, counting from 0, so the 4th slot of the first AMS is tray 3.
  - Don't count on the printer to catch a wrong mapping. `bbl.py print` compares the filaments in `slice_info.config` with the status report's trays first.
- **Change the running job:** `{"print": {"command": "pause" | "resume" | "stop"}}`
- **Run calibrations (`calibrate`):** `{"print": {"command": "calibration", "option": <bits>}}`, adding 1 for lidar, 2 for bed leveling, and 4 for vibration compensation (from Bambu Studio's `command_start_calibration`). The printer acks with `"command": "calibration", "result": "success"`, then reports `RUNNING` with the stage of each step (3 for vibration) and `FINISH` when done. Vibration alone took about 4 minutes on an X1C. Bambu Studio sends this on X1 firmware with AP version 00.00.15.79 or later; the other bits are untested here.
- **Full status push:** `{"pushing": {"command": "pushall"}}`

## Camera support by model

`bbl.py setup` reports this for each bound printer.
- **X1 series** (X1 Carbon, X1, X1E): RTSPS on port 322, with "LAN liveview" on in the printer's settings. Tested on the X1 Carbon.
- **P1 and A1 series**: the camera uses a different protocol, which `bbl.py` doesn't implement. Status, the SD card, the log, and `watch --no-snap` still work.
- **Other models**: untested. Try `bbl.py snap`; if it fails, run the watch with `--no-snap`.

## Live timelapse

`bbl.py frames DIR --every S --count N --assemble OUT.mp4` snaps a frame every S seconds and stitches them at 8 fps. Pick S so you catch the layers you care about: `remaining_min` and `total_layers` from status give the time per layer. Run long captures in the background and look at the frames as they arrive.

Two camera captures at once (a `snap` during a `watch` snapshot) are untested; if one fails, retry it a minute later. A watch with a short `--progress-every` is itself a coarse timelapse: its snapshots are in the watch folder.

## Watch logic

`bbl.py watch` reads one full status every `--interval` seconds, and reconnects each time so a dropped connection costs one check. A stall alert fires only while `RUNNING`: calibration (`PREPARE`) and pauses never count as stalled. Each code, pause, and over-temperature alert fires once per watch. The watch logic is adapted from heyixuan2/bambu-studio-ai's `monitor.py` (MIT).
