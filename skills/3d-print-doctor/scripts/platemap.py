#!/usr/bin/env python3
"""Top-down map of a sliced plate: where each part, the supports, and the purge block will print.

  platemap.py FILE OUT.png [--plate N] [--svg]

FILE is a sliced .gcode.3mf (OrcaSlicer's export, or `bbl.py get /<job>.gcode.3mf`) or a plain
.gcode. The map draws every extrusion seen from above, colored by filament, with the purge block
(prime tower) outlined, the front of the plate marked, a 50 mm grid, and a legend of the filaments.
OrcaSlicer's own thumbnails leave the purge block out, which is why this exists.

Prints one summary line per filament (what it prints: parts, infill, supports, purge block) and
the purge block's position in mm and in words ("back center"), for the agent to describe. Prints a
"warning:" line when a filament is flushed into the infill of parts made of a different material
(PETG flushed into PLA infill, say), since the two may not bond, and when the bed runs well above
the part material's own temperature for the plate (mixed-material projects heat the bed for the
hottest filament by default). Writes the SVG next to OUT and converts it to PNG with
macOS Quick Look (`qlmanage`); --svg writes only the SVG to OUT. Standard library only; Python 3.9+.
"""
import argparse, math, os, re, shutil, subprocess, sys, tempfile, zipfile

SCALE, PAD, GRID = 3, 40, 50          # px per mm, margin px, grid spacing mm
BED, GRID_LINE, EDGE = "#9aa0a6", "#8a9096", "#4a4f55"   # mid-grey bed: white and black filament both show
TOWER = ("prime tower", "wipe tower")
SKIP = ("custom",)                    # filament-change and start/end G-code, not the plate


def read_gcode(path, plate):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = f"Metadata/plate_{plate}.gcode"
            if name not in z.namelist():
                sys.exit(f"{path} has no {name}; is it sliced? (plates: "
                         f"{', '.join(n for n in z.namelist() if n.endswith('.gcode')) or 'none'})")
            return z.read(name).decode(errors="ignore").splitlines()
    with open(path, errors="ignore") as f:
        return f.read().splitlines()


def header_list(lines, key):
    for line in lines:
        if line.startswith(f"; {key} = "):
            return [v.strip().strip('"') for v in re.split(r'";"|;', line.split("=", 1)[1].strip())]
    return []


def arc(x0, y0, x1, y1, i, j, cw):
    """Points along a G2 (cw) / G3 arc; a missing endpoint is a full circle."""
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw and sweep >= 0: sweep -= 2 * math.pi
    if not cw and sweep <= 0: sweep += 2 * math.pi
    n = max(2, int(abs(sweep) * r / 1.0) + 1)   # about 1 mm per step
    return [(cx + r * math.cos(a0 + sweep * k / n), cy + r * math.sin(a0 + sweep * k / n)) for k in range(1, n + 1)]


def parse(lines):
    """Extrusion segments (tool, feature, x0, y0, x1, y1) from the first layer change onward."""
    x = y = 0.0; tool = 0; feat = ""; started = False; segs = []
    num = lambda c, k: (lambda m: float(m.group(1)) if m else None)(re.search(k + r"(-?[\d.]+)", c))
    for line in lines:
        if not started:
            m = re.match(r"M620 S(\d+)A", line)
            if m: tool = int(m.group(1))
            if re.match(r";\s?(CHANGE_LAYER|LAYER_CHANGE)", line): started = True
        if line.startswith("; FEATURE:"):
            feat = line.split(":", 1)[1].strip(); continue
        m = re.match(r"T(\d+)\s*$", line.split(";")[0])
        if m and int(m.group(1)) < 16: tool = int(m.group(1)); continue
        if not line.startswith(("G0", "G1", "G2", "G3")) or line[2:3] not in (" ", ""): continue
        c = line.split(";")[0]
        nx, ny, e = num(c, "X"), num(c, "Y"), num(c, "E")
        x1 = x if nx is None else nx; y1 = y if ny is None else ny
        draw = started and e is not None and e > 0 and not feat.lower().startswith(SKIP)
        if line.startswith(("G2", "G3")):
            i, j = num(c, "I") or 0.0, num(c, "J") or 0.0
            if draw and (i or j):
                px, py = x, y
                for qx, qy in arc(x, y, x1, y1, i, j, line.startswith("G2")):
                    segs.append((tool, feat, px, py, qx, qy)); px, py = qx, qy
        elif draw and (nx is not None or ny is not None) and line.startswith("G1"):
            segs.append((tool, feat, x, y, x1, y1))
        x, y = x1, y1
    return segs


def roles(segs, tool):
    """What a filament prints: parts, infill (purge flushed into objects' infill), supports, purge block."""
    found = set()
    for t, f, *_ in segs:
        if t != tool or not f: continue
        f = f.lower()
        found.add("purge block" if f in TOWER else "supports" if "support" in f
                  else "infill" if f == "sparse infill" else "parts")
    if "parts" in found: found.discard("infill")   # infill of its own parts, not a flush
    return [r for r in ("parts", "infill", "supports", "purge block") if r in found]


PLATE_KEYS = {"textured pei plate": "textured_plate_temp", "high temp plate": "hot_plate_temp",
              "smooth pei plate": "hot_plate_temp", "cool plate": "cool_plate_temp",
              "engineering plate": "eng_plate_temp", "textured cool plate": "textured_cool_plate_temp",
              "supertack plate": "supertack_plate_temp"}


def bed_warning(lines, part_filaments, types):
    """A warning when the bed runs well above the part material's own temperature for this plate.
    With several filaments, OrcaSlicer's default bed_temperature_formula (by_highest_temp) heats the
    bed for the hottest one: PLA parts with PETG supports get PETG's 70 °C."""
    plate = (header_list(lines, "curr_bed_type") or [""])[0]
    key = PLATE_KEYS.get(plate.lower())
    temps = [int(m.group(1)) for l in lines if (m := re.match(r"M1[49]0 S(\d+)", l)) and int(m.group(1)) > 0]
    if not key or not temps: return None
    used = max(temps)
    own = {}
    for k in (key, key + "_initial_layer"):
        for i, v in enumerate(",".join(header_list(lines, k)).split(",")):   # temperatures are comma-separated
            if i in part_filaments and v.isdigit(): own[i] = max(own.get(i, 0), int(v))
    if not own: return None
    t, ref = min(own.items(), key=lambda kv: kv[1])
    if used <= ref + 5: return None   # plate temperatures usually move in 5 °C steps; one step up (PLA 55 -> 60) is an ordinary tweak
    kind = types[t] if t < len(types) else "part"
    formula = (header_list(lines, "bed_temperature_formula") or ["?"])[0]
    return (f"warning: the bed runs at {used} °C, but the {kind} parts' own {plate} temperature is {ref} °C "
            f"(bed_temperature_formula = {formula}). Hot beds soften the bottom of the parts (elephant's foot). "
            f"Lower {key} for the other filaments in a project copy, or set the formula to by_first_filament.")


def where(cx, cy, w, h):
    col = ("left", "center", "right")[min(2, int(3 * cx / w))]
    row = ("front", "middle", "back")[min(2, int(3 * cy / h))]
    return f"{row} {col}"


def render(lines, title):
    area = [tuple(map(float, p.split("x"))) for p in ",".join(header_list(lines, "printable_area")).split(",") if "x" in p] \
        or [(0, 0), (256, 256)]   # the X1/P1 bed, when the header has no printable_area
    bw, bh = max(p[0] for p in area), max(p[1] for p in area)
    colors = header_list(lines, "filament_colour")
    types = header_list(lines, "filament_type")
    names = header_list(lines, "filament_settings_id")
    segs = parse(lines)
    if not segs: sys.exit("no extrusion moves found; is this a sliced file?")
    used = sorted({s[0] for s in segs})
    H = bh * SCALE + 2 * PAD + 30 + 26 * (len(used) + 1)
    W = max(bw * SCALE + 2 * PAD, H)          # square: Quick Look crops its thumbnail to a square
    left = (W - bw * SCALE) / 2
    X = lambda v: left + v * SCALE
    Y = lambda v: PAD + (bh - v) * SCALE
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" font-family="Helvetica, Arial, sans-serif">',
         '<rect width="100%" height="100%" fill="white"/>',
         f'<rect x="{X(0)}" y="{Y(bh)}" width="{bw * SCALE}" height="{bh * SCALE}" fill="{BED}" stroke="{EDGE}" stroke-width="2"/>']
    for g in range(GRID, int(bw), GRID):
        o.append(f'<line x1="{X(g)}" y1="{Y(0)}" x2="{X(g)}" y2="{Y(bh)}" stroke="{GRID_LINE}"/>')
    for g in range(GRID, int(bh), GRID):
        o.append(f'<line x1="{X(0)}" y1="{Y(g)}" x2="{X(bw)}" y2="{Y(g)}" stroke="{GRID_LINE}"/>')
    color = lambda t: colors[t] if t < len(colors) and re.match(r"#[0-9A-Fa-f]{6}", colors[t]) else "#d00"
    for t, f, a, b, c, d in segs:
        o.append(f'<line x1="{X(a):.1f}" y1="{Y(b):.1f}" x2="{X(c):.1f}" y2="{Y(d):.1f}" stroke="{color(t)[:7]}" stroke-width="1.2" stroke-linecap="round"/>')
    summary, warnings = [], []
    tw = [s for s in segs if s[1].lower() in TOWER]
    part_types = {types[t] for t in used if t < len(types) and "parts" in roles(segs, t)}
    hot = bed_warning(lines, {t for t in used if "parts" in roles(segs, t)}, types)
    if hot: warnings.append(hot)
    for t in used:
        kind = types[t] if t < len(types) else "?"
        if "infill" in roles(segs, t) and kind not in part_types:
            warnings.append(f"warning: filament {t + 1} ({kind}) is flushed into the infill of "
                            f"{'/'.join(sorted(part_types))} parts, and different materials may not bond. "
                            "Turn off 'Flush into objects' infill' (flush_into_infill) for this project.")
    if tw:
        xs = [v for s in tw for v in (s[2], s[4])]; ys = [v for s in tw for v in (s[3], s[5])]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        o.append(f'<rect x="{X(x0) - 4:.1f}" y="{Y(y1) - 4:.1f}" width="{(x1 - x0) * SCALE + 8:.1f}" height="{(y1 - y0) * SCALE + 8:.1f}" '
                 'fill="none" stroke="#d00" stroke-width="3" stroke-dasharray="8 5"/>')
        ty = Y(y1) - 12 if Y(y1) - 12 > PAD + 20 else Y(y0) + 28
        anchor, tx = ("end", X(x1)) if x0 > bw / 2 else ("start", X(x0))
        o.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" font-size="20" font-weight="bold" fill="#d00" '
                 'stroke="white" stroke-width="4" paint-order="stroke">Purge block</text>')
        summary.append(f"purge block: x {x0:.0f}-{x1:.0f} mm, y {y0:.0f}-{y1:.0f} mm from the front-left corner "
                       f"({where((x0 + x1) / 2, (y0 + y1) / 2, bw, bh)})")
    else:
        summary.append("purge block: none on this plate")
    o.append(f'<text x="{X(bw / 2)}" y="{Y(0) + 28}" font-size="18" text-anchor="middle" fill="#333">FRONT (door)</text>')
    o.append(f'<text x="{X(bw / 2)}" y="{Y(bh) - 12}" font-size="18" text-anchor="middle" fill="#333">BACK</text>')
    ly = Y(0) + 56
    for t in used:
        kind = types[t] if t < len(types) else "?"
        name = names[t] if t < len(names) else ""
        role = ", ".join(roles(segs, t)) or "?"
        o.append(f'<rect x="{left}" y="{ly - 15}" width="18" height="18" fill="{color(t)[:7]}" stroke="#333"/>')
        label = f"Filament {t + 1}: {kind} ({name}), {role}".replace("&", "&amp;").replace("<", "&lt;")
        o.append(f'<text x="{left + 26}" y="{ly}" font-size="16" fill="#333">{label}</text>')
        summary.insert(len(summary) - 1, f"filament {t + 1}: {kind} {color(t)[:7]} ({name}), {role}")
        ly += 26
    o.append(f'<text x="{left}" y="{ly}" font-size="14" fill="#666">{title} · grid {GRID} mm</text>'
             .replace("&", "&amp;"))
    o.append("</svg>")
    return "\n".join(o), summary + warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file"); ap.add_argument("out")
    ap.add_argument("--plate", type=int, default=1)
    ap.add_argument("--svg", action="store_true", help="write only the SVG to OUT")
    a = ap.parse_args()
    svg, summary = render(read_gcode(a.file, a.plate), os.path.basename(a.file))
    if a.svg:
        open(a.out, "w").write(svg)
    else:
        if not shutil.which("qlmanage"): sys.exit("qlmanage (macOS Quick Look) not found; use --svg")
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "plate.svg")
        open(src, "w").write(svg)
        # 1000 px keeps the legend readable on a phone; Quick Look renders in a second or two, 60 s is a hang guard.
        subprocess.run(["qlmanage", "-t", "-s", "1000", "-o", tmp, src], capture_output=True, timeout=60)
        png = src + ".png"
        if not os.path.exists(png): sys.exit("Quick Look did not render the SVG; use --svg")
        shutil.move(png, a.out)
        shutil.copy(src, os.path.splitext(a.out)[0] + ".svg")
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n".join(summary))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
