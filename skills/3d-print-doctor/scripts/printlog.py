#!/usr/bin/env python3
"""Print log: one JSON line per print, filled from the sliced file so nobody types settings.

  printlog.py add --result success|partial|fail|unknown [--from FILE] [--watch DIR] [--model NAME]
                  [--issue TAG]... [--fix TEXT] [--notes TEXT] [--dried TEXT] [--hours H] [--set KEY=VALUE]...
                  [--date YYYY-MM-DD] [--source TEXT]
  (unknown: entries backfilled from the SD card, where the outcome wasn't recorded; amend when learned)
  printlog.py amend ID [same options as add, all optional]   correct or complete an entry
  printlog.py find [--model S] [--material S] [--preset S] [--result R] [--issue TAG] [--limit N]
  printlog.py show ID
  printlog.py settings [--material S] [--preset S] [--model S]   what successful prints used:
                                                 values the same every time vs. values that varied
  printlog.py stats                              success rate by material, common issues, filament used
  printlog.py tags                               the issue tag vocabulary

--from reads a .gcode.3mf (from OrcaSlicer's export, or `bbl.py get /<job>.gcode.3mf`), a project
.3mf, or a plain .gcode: presets, material, nozzle, temperatures, layer height, the settings in
CAPTURED, the keys changed from the system presets, and the slicer's weight and time estimate.
--watch reads a `bbl.py watch` folder: job name and actual print hours.
Log: <data_dir>/print-log.jsonl, data_dir from ~/.config/3d-print-doctor/config.json (default
~/3d-print-doctor; override the file with --log). Standard library only; Python 3.9+.
"""
import argparse, collections, json, os, re, sys, time, zipfile

CONFIG = os.path.expanduser("~/.config/3d-print-doctor/config.json")   # shared with bbl.py (`bbl.py setup`)
try: DATA_DIR = json.load(open(CONFIG)).get("data_dir") or "~/3d-print-doctor"
except (OSError, ValueError): DATA_DIR = "~/3d-print-doctor"
DEFAULT_LOG = os.path.join(os.path.expanduser(DATA_DIR), "print-log.jsonl")
RESULTS = ("success", "partial", "fail", "unknown")   # unknown: backfilled from the SD card, outcome not recorded
# One tag per failure-modes.md row, so `find --issue` matches across entries.
TAGS = ("detached", "warping", "elephant-foot", "first-layer", "under-extrusion", "over-extrusion", "stringing",
        "zits-seam", "clog", "layer-shift", "ringing", "overhang-curl", "bridge-sag", "dimensions", "delamination",
        "pillowing", "wall-gaps", "leaks", "support-removal", "z-banding", "color-bleed", "wet-filament", "spaghetti")
CAPTURED = ("layer_height", "initial_layer_print_height", "nozzle_temperature", "nozzle_temperature_initial_layer",
            "curr_bed_type", "bed_temp", "sparse_infill_density", "sparse_infill_pattern", "wall_loops",
            "top_shell_layers", "bottom_shell_layers", "enable_support", "support_type", "support_top_z_distance",
            "brim_type", "brim_width", "raft_layers", "filament_max_volumetric_speed", "filament_flow_ratio",
            "outer_wall_speed", "initial_layer_speed", "fan_max_speed", "fan_min_speed", "filament_retraction_length",
            "retraction_length", "enable_pressure_advance", "pressure_advance", "seam_position",
            "elefant_foot_compensation", "enable_prime_tower", "flush_multiplier")
BED_KEY = {"Textured PEI Plate": "textured_plate_temp", "Cool Plate": "cool_plate_temp", "Engineering Plate": "eng_plate_temp",
           "High Temp Plate": "hot_plate_temp", "Smooth PEI Plate": "hot_plate_temp",
           "Cool Plate (SuperTack)": "supertack_plate_temp", "Textured Cool Plate": "textured_cool_plate_temp"}


def die(msg):
    print(msg, file=sys.stderr); sys.exit(1)


# ---------------------------------------------------------------- reading sliced files
def _scalar(v):
    """Per-filament/per-extruder arrays collapse to one value when every entry agrees.
    'nil' (OrcaSlicer's "no filament override") and empty values become None."""
    if isinstance(v, str):
        v = v.strip()
        if v.startswith('"') and '";"' in v: v = v.split(";")          # G-code header string arrays
    if isinstance(v, list):
        v = [x for x in (str(x).strip().strip('"') for x in v) if x not in ("nil", "")]
        if not v: return None
        return v[0] if len(set(v)) == 1 else ",".join(v)
    if isinstance(v, str):
        v = v.strip('"')
        return None if v in ("nil", "") else v
    return v


def _hours(text):
    """'18h 41m 1s' / '2d 3h 5m' -> hours."""
    mult = {"d": 24, "h": 1, "m": 1 / 60, "s": 1 / 3600}
    parts = re.findall(r"(\d+)\s*([dhms])", text or "")
    return round(sum(int(n) * mult[u] for n, u in parts), 2) if parts else None


def _gcode_header(text):
    cfg, est = {}, {}
    for line in text.splitlines():
        m = re.match(r";\s*([a-z0-9_]+)\s*=\s*(.*)$", line)
        if m: cfg.setdefault(m.group(1), m.group(2).strip())
        if "total estimated time" in line: est["est_hours"] = _hours(line.split("total estimated time")[-1])
        m = re.match(r";\s*filament used \[g\]\s*=\s*([\d.]+)", line)
        if m: est["grams"] = float(m.group(1))
    return cfg, est


def read_sliced(path):
    if not os.path.isfile(path): die(f"--from: no such file {path}")
    cfg, est = {}, {}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "Metadata/project_settings.config" in names:
                cfg = json.loads(z.read("Metadata/project_settings.config"))
            if "Metadata/slice_info.config" in names:
                info = z.read("Metadata/slice_info.config").decode(errors="replace")
                secs = [int(x) for x in re.findall(r'key="prediction" value="(\d+)"', info)]
                grams = [float(x) for x in re.findall(r'key="weight" value="([\d.]+)"', info)]
                if secs: est["est_hours"] = round(sum(secs) / 3600, 2)       # summed over sliced plates
                if grams: est["grams"] = round(sum(grams), 2)
                if len(secs) > 1: est["plates"] = len(secs)
                used = {}   # filament slot id -> grams actually printed, summed over plates
                for tag in re.findall(r"<filament\b[^>]*/>", info):
                    at = dict(re.findall(r'(\w+)="([^"]*)"', tag))
                    g = float(at.get("used_g") or 0)
                    if g > 0 and at.get("id", "").isdigit(): used[int(at["id"])] = used.get(int(at["id"]), 0) + g
                if used: est["_used"] = sorted(used, key=lambda i: -used[i])   # heaviest first
            elif "Metadata/plate_1.gcode" in names:
                est = _gcode_header(z.read("Metadata/plate_1.gcode").decode(errors="replace"))[1]
    else:
        cfg, est = _gcode_header(open(path, errors="replace").read())
    if not cfg: die(f"{path}: no settings found (expected a .gcode.3mf, project .3mf, or OrcaSlicer .gcode)")
    # Per-filament arrays list every filament in the project; keep only the ones this print used.
    used, n_fil = est.pop("_used", None), len(cfg.get("filament_settings_id") or [])
    def pick(v):
        if used and isinstance(v, list) and len(v) == n_fil and max(used) <= n_fil:
            v = list(dict.fromkeys(v[i - 1] for i in used))
        return _scalar(v)
    cfg = {k: pick(v) for k, v in cfg.items()}
    if used: est["filament_slots"] = used
    s = {k: _scalar(cfg[k]) for k in CAPTURED if k in cfg and _scalar(cfg[k]) is not None}
    bed_key = BED_KEY.get(str(_scalar(cfg.get("curr_bed_type", ""))))
    if bed_key and bed_key in cfg: s["bed_temp"] = _scalar(cfg[bed_key])
    # a JSON list of ';'-joined keys in a 3MF, one quoted string per section in a G-code header
    changed = sorted(set(re.findall(r"[a-z][a-z0-9_]+", str(cfg.get("different_settings_to_system") or ""))))
    return {
        "presets": {"process": _scalar(cfg.get("print_settings_id")), "filament": _scalar(cfg.get("filament_settings_id")),
                    "printer": _scalar(cfg.get("printer_settings_id"))},
        "material": _scalar(cfg.get("filament_type")), "vendor": _scalar(cfg.get("filament_vendor")),
        "nozzle": _scalar(cfg.get("nozzle_diameter")), "settings": s, "changed_from_system": changed, **est,
    }


def read_watch(d):
    try:
        events = [json.loads(l) for l in open(os.path.join(d, "events.jsonl")) if l.strip()]
    except OSError as e:
        die(f"--watch: {e}")
    out = {"watch_dir": os.path.abspath(d)}
    start = next((e for e in events if e["kind"] == "started"), None)
    end = next((e for e in reversed(events) if e["kind"] in ("finished", "failed", "stopped")), None)
    if start and start.get("job"): out["model"] = start["job"]
    if start and end:
        t = lambda e: time.mktime(time.strptime(e["time"], "%Y-%m-%dT%H:%M:%S"))
        out["hours"] = round((t(end) - t(start)) / 3600, 2)
        out["ended"] = end["kind"]
    return out


# ---------------------------------------------------------------- log file
def load(path):
    if not os.path.exists(path): return []
    return [json.loads(l) for l in open(path) if l.strip()]


def save(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def apply_opts(e, a):
    if a.from_file: e.update(read_sliced(a.from_file)); e["source"] = a.source or os.path.abspath(a.from_file)
    elif a.source: e["source"] = a.source
    if a.date: e["date"] = a.date
    if a.watch:
        w = read_watch(a.watch)
        if not e.get("model") and "model" in w: e["model"] = w.pop("model")
        else: w.pop("model", None)
        e.update(w)
    for k in ("model", "result", "fix", "notes", "dried", "hours"):
        v = getattr(a, k, None)
        if v is not None: e[k] = v
    if a.issue:
        unknown = [t for t in a.issue if t not in TAGS]
        if unknown: print(f"note: new tag(s) {unknown}; existing tags: {', '.join(TAGS)}", file=sys.stderr)
        e["issues"] = sorted(set(e.get("issues", [])) | set(a.issue))
    for kv in a.set or []:
        k, sep, v = kv.partition("=")
        if not sep: die(f"--set needs KEY=VALUE, got {kv!r}")
        if k in CAPTURED: e.setdefault("settings", {})[k] = v   # a slicer setting
        else: e[k] = v                                          # an entry field (color, material, ...)
    if not e.get("model") and e.get("source"):
        e["model"] = re.sub(r"(\.gcode)?\.3mf$|\.gcode$", "", os.path.basename(e["source"]))


def cmd_add(a):
    rows = load(a.log)
    e = {"id": max((r["id"] for r in rows), default=0) + 1, "date": time.strftime("%Y-%m-%d")}
    apply_opts(e, a)
    os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
    with open(a.log, "a") as f: f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(line(e))


def cmd_amend(a):
    rows = load(a.log)
    e = next((r for r in rows if r["id"] == a.id), None) or die(f"no entry {a.id}")
    apply_opts(e, a); save(a.log, rows); print(line(e))


# ---------------------------------------------------------------- queries
def matches(r, a):
    has = lambda field, s: s is None or s.lower() in str(field or "").lower()
    return (has(r.get("model"), getattr(a, "model", None)) and has(r.get("material"), getattr(a, "material", None))
            and has(json.dumps(r.get("presets")), getattr(a, "preset", None))
            and (getattr(a, "result", None) in (None, r.get("result")))
            and (getattr(a, "issue", None) in (None, *r.get("issues", []))))


def line(r):
    p = r.get("presets") or {}
    out = f"#{r['id']} {r.get('date')} {r.get('result', '?'):<7} {r.get('model', '?')}"
    out += f" [{r.get('material') or '?'} · {p.get('filament') or '?'} · {p.get('process') or '?'}]"
    if r.get("issues"): out += " issues: " + ", ".join(r["issues"])
    if r.get("fix"): out += f" → fix: {r['fix']}"
    return out


def cmd_find(a):
    rows = [r for r in load(a.log) if matches(r, a)]
    if not rows: print("no matching entries"); return
    for r in rows[::-1][:a.limit]: print(line(r))


def cmd_show(a):
    r = next((r for r in load(a.log) if r["id"] == a.id), None) or die(f"no entry {a.id}")
    print(json.dumps(r, indent=1, ensure_ascii=False))


def cmd_settings(a):
    a.result = "success"; a.issue = None
    rows = [r for r in load(a.log) if matches(r, a)]
    if not rows:
        near = [r for r in load(a.log) if matches(r, argparse.Namespace(**{**vars(a), "result": None}))]
        print("no successful prints match" + (f"; {len(near)} other entr(ies) do, see `find`" if near else "")); return
    print(f"settings from {len(rows)} successful print(s)"
          + (" (only one, so nothing to compare yet):" if len(rows) == 1 else ":"))
    keys = ["nozzle", "presets.filament", "presets.process"] + list(CAPTURED)
    for k in keys:
        get = (lambda r: (r.get("presets") or {}).get(k.split(".")[1])) if k.startswith("presets.") else \
              (lambda r: r.get(k)) if k == "nozzle" else (lambda r: (r.get("settings") or {}).get(k))
        vals = collections.Counter(str(v) for v in map(get, rows) if v is not None)
        if not vals: continue
        if len(vals) == 1: print(f"  {k:<34} {next(iter(vals))}   (same in all {sum(vals.values())})")
        else: print(f"  {k:<34} varies: " + ", ".join(f"{v} ×{n}" for v, n in vals.most_common()))
    fixes = [r for r in rows if r.get("fix")]
    for r in fixes[-5:]: print(f"  fix that worked: #{r['id']} {r.get('model')}: {r['fix']}")


def cmd_stats(a):
    rows = load(a.log)
    if not rows: print("log is empty"); return
    res = collections.Counter(r.get("result") for r in rows)
    print(f"{len(rows)} prints: " + ", ".join(f"{k} {res[k]}" for k in RESULTS if res[k]))
    by = collections.defaultdict(collections.Counter)
    for r in rows: by[r.get("material") or "?"][r.get("result")] += 1
    for m, c in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        n, known = sum(c.values()), sum(c.values()) - c["unknown"]
        rate = f"{100 * c['success'] / known:.0f}% success of {known} with a known result" if known else "no known results"
        print(f"  {m:<10} {n:>3} prints, {rate}")
    issues = collections.Counter(t for r in rows for t in r.get("issues", []))
    if issues: print("common issues: " + ", ".join(f"{t} ×{n}" for t, n in issues.most_common(8)))
    g = sum(r.get("grams") or 0 for r in rows); h = sum(r.get("hours") or r.get("est_hours") or 0 for r in rows)
    print(f"filament ≈ {g:.0f} g, print time ≈ {h:.0f} h (slicer estimates where no actual time)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default=DEFAULT_LOG)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("add", cmd_add), ("amend", cmd_amend)):
        s = sp.add_parser(name)
        if name == "amend": s.add_argument("id", type=int)
        s.add_argument("--result", choices=RESULTS, required=(name == "add"))
        s.add_argument("--from", dest="from_file", metavar="FILE"); s.add_argument("--watch", metavar="DIR")
        s.add_argument("--model"); s.add_argument("--issue", action="append", metavar="TAG")
        s.add_argument("--fix"); s.add_argument("--notes"); s.add_argument("--dried")
        s.add_argument("--hours", type=float, help="actual print time"); s.add_argument("--set", action="append", metavar="KEY=VALUE")
        s.add_argument("--date", help="YYYY-MM-DD (default today)")
        s.add_argument("--source", help="what to record as the source (default: the --from path), e.g. sd:/<file>")
        s.set_defaults(fn=fn)
    s = sp.add_parser("find")
    for f in ("--model", "--material", "--preset", "--issue"): s.add_argument(f)
    s.add_argument("--result", choices=RESULTS); s.add_argument("--limit", type=int, default=20); s.set_defaults(fn=cmd_find)
    s = sp.add_parser("show"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_show)
    s = sp.add_parser("settings")
    for f in ("--model", "--material", "--preset"): s.add_argument(f)
    s.set_defaults(fn=cmd_settings)
    sp.add_parser("stats").set_defaults(fn=cmd_stats)
    sp.add_parser("tags").set_defaults(fn=lambda a: print("\n".join(TAGS)))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
