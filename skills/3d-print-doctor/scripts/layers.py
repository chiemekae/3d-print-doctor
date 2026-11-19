#!/usr/bin/env python3
"""What a sliced part prints at each height: runs of layers that share the same features.

  layers.py FILE [--at LAYER] [--plate N]

FILE is a sliced .gcode.3mf (OrcaSlicer's export, or `bbl.py get /<job>.gcode.3mf`) or a plain
.gcode. Prints one line per run of consecutive layers with the same slicer features (outer wall,
sparse infill, top surface, bridge...), with their layer numbers and heights in mm. Layer numbers
match the printer's layer counter. With --at, prints only the run holding that layer, marked
with ">", and the runs just before and after it, for briefing a snapshot judge on what the part
should look like now. Standard library only; Python 3.9+.
"""
import argparse, re, sys, zipfile

SKIP = {"custom"}                    # start/end and filament-change G-code, not the part


def read_gcode(path, plate):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = f"Metadata/plate_{plate}.gcode"
            if name not in z.namelist():
                sys.exit(f"{path} has no {name}; is it sliced?")
            return z.read(name).decode(errors="ignore").splitlines()
    with open(path, errors="ignore") as f:
        return f.read().splitlines()


def layer_features(lines):
    """[(z, frozenset of feature names)] for layers 1..N."""
    layers = []
    for line in lines:
        if line.startswith("; CHANGE_LAYER"):
            layers.append([None, set()])
        elif not layers:
            continue
        elif m := re.match(r";\s*Z_HEIGHT:\s*([\d.]+)", line):
            layers[-1][0] = float(m.group(1))
        elif m := re.match(r";\s*FEATURE:\s*(.+)", line):
            name = m.group(1).strip()
            if name.lower() not in SKIP:
                layers[-1][1].add(name)
    return [(z, frozenset(f)) for z, f in layers]


def runs(layers):
    """[(first, last, z_first, z_last, features)] with 1-based layer numbers."""
    out = []
    for i, (z, feats) in enumerate(layers, 1):
        if out and out[-1][4] == feats:
            first, _, z0, _, _ = out[-1]
            out[-1] = (first, i, z0, z, feats)
        else:
            out.append((i, i, z, z, feats))
    return out


def fmt(run):
    first, last, z0, z1, feats = run
    mm = lambda z: "?" if z is None else f"{z:g}"
    span = f"layer {first} (z {mm(z0)} mm)" if first == last else \
        f"layers {first}-{last} (z {mm(z0)}-{mm(z1)} mm)"
    return f"{span}: {', '.join(sorted(feats)) or 'no extrusion'}"


def load_layers(path, plate=1):
    layers = layer_features(read_gcode(path, plate))
    if not layers:
        sys.exit(f"{path} has no '; CHANGE_LAYER' markers; is it sliced by OrcaSlicer or Bambu Studio?")
    return layers


def describe_at(layers, at):
    """The run holding layer `at`, marked with ">", and the runs just before and after it."""
    if not 1 <= at <= len(layers):
        sys.exit(f"layer {at} is outside 1-{len(layers)}")
    all_runs = runs(layers)
    i = next(k for k, r in enumerate(all_runs) if r[0] <= at <= r[1])
    lines = [f"layer {at} of {len(layers)}, z {layers[at - 1][0]:g} mm"]
    for k in range(max(0, i - 1), min(len(all_runs), i + 2)):
        lines.append(("> " if k == i else "  ") + fmt(all_runs[k]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("--at", type=int, metavar="LAYER")
    ap.add_argument("--plate", type=int, default=1)
    a = ap.parse_args()
    layers = load_layers(a.file, a.plate)
    if a.at is None:
        print(f"{len(layers)} layers")
        for r in runs(layers):
            print(fmt(r))
        return
    print(describe_at(layers, a.at))


if __name__ == "__main__":
    main()
