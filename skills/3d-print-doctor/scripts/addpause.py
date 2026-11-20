#!/usr/bin/env python3
"""Add a pause before one layer of a sliced file, for dropping in a nut, magnet, or weight.

  addpause.py FILE OUT (--layer N | --z MM) [--plate N]

FILE is a sliced .gcode.3mf or a plain .gcode. The pause goes in before layer N, or before the
layer whose top is at MM, so the printer stops with the layer below finished and the pocket open.
It is the slicer's own pause and nothing else: a `; PAUSE_PRINTING` tag and the file's
`machine_pause_gcode` (M400 U1 on Bambu Lab printers), placed where OrcaSlicer places a pause
added in the app. The printer moves the nozzle aside, cools it, and reheats on resume by itself;
moves of your own around the pause can leave it printing nothing afterwards. In a .gcode.3mf the
plate's .md5 member is rewritten to match. Standard library only; Python 3.9+.
"""
import argparse, hashlib, re, sys, zipfile

TAG = "; PAUSE_PRINTING"


def pause_gcode(lines):
    for line in lines:
        if line.startswith("; machine_pause_gcode = "):
            return line.split("=", 1)[1].strip().replace("\\n", "\n")
    return "M400 U1"


def layer_index(lines, layer=None, z=None):
    """Line index of the target layer's marker, and its layer number and top height."""
    current = None
    for i, line in enumerate(lines):
        if line.startswith("; CHANGE_LAYER"):
            current = None
        elif line.startswith("; Z_HEIGHT:"):
            current = float(line.split(":")[1])
        elif line.startswith("; layer num/total_layer_count:"):
            n = int(line.split(":")[1].split("/")[0])
            if n == layer or (z is not None and current is not None and abs(current - z) < 1e-6):
                return i, n, current
    want = f"layer {layer}" if layer is not None else f"a layer with its top at {z} mm"
    sys.exit(f"no {want} in this file; `layers.py FILE` lists the layers and heights")


def add_pause(text, layer=None, z=None):
    """The G-code with the pause inserted, and the layer number and height it went before."""
    lines = text.split("\n")
    i, n, top = layer_index(lines, layer, z)
    end = next((j for j in range(i, len(lines)) if lines[j].startswith(("; CHANGE_LAYER", "; FEATURE:"))
                and j > i), len(lines))
    if any(l.startswith(TAG) for l in lines[i:end]):
        sys.exit(f"layer {n} already has a pause")
    # OrcaSlicer emits layer-change custom G-code after the printer's layer notification (M991 on
    # Bambu Lab printers); without one, right after the layer marker.
    at = next((j + 1 for j in range(i, min(i + 10, end)) if lines[j].startswith("M991 ")), i + 1)
    lines[at:at] = [TAG] + pause_gcode(lines).split("\n")
    return "\n".join(lines), n, top


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file"); p.add_argument("out")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--layer", type=int, help="pause before this layer (the printer's layer counter)")
    where.add_argument("--z", type=float, help="pause before the layer whose top is at this height (mm)")
    p.add_argument("--plate", type=int, default=1)
    a = p.parse_args()
    if a.out == a.file:
        sys.exit("write to a new file; the original stays untouched")

    if zipfile.is_zipfile(a.file):
        name = f"Metadata/plate_{a.plate}.gcode"
        with zipfile.ZipFile(a.file) as zin:
            if name not in zin.namelist():
                sys.exit(f"{a.file} has no {name}; is it sliced?")
            new, n, top = add_pause(zin.read(name).decode(), a.layer, a.z)
            data = new.encode()
            with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    body = zin.read(item.filename)
                    if item.filename == name:
                        body = data
                    elif item.filename == name + ".md5":
                        body = hashlib.md5(data).hexdigest().upper().encode()
                    zout.writestr(item, body)
    else:
        with open(a.file) as f:
            new, n, top = add_pause(f.read(), a.layer, a.z)
        with open(a.out, "w") as f:
            f.write(new)
    print(f"pause before layer {n} (top at {top} mm): the printer stops with layer {n - 1} finished")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
