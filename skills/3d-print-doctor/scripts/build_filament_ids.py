"""Build references/filament-ids.json, which names the filament IDs the printer reports per spool.

Usage: build_filament_ids.py <BambuStudio checkout>/resources/profiles/BBL/filament
"""
import glob, json, os, sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "filament-ids.json")


def build(profile_dir):
    ids = {}
    for path in sorted(glob.glob(os.path.join(profile_dir, "*.json"))):
        p = json.load(open(path, encoding="utf-8"))
        fid, name = p.get("filament_id"), p.get("name", "")
        if fid and name.endswith(" @base"):
            ids.setdefault(fid, name[: -len(" @base")])
    return dict(sorted(ids.items()))


if __name__ == "__main__":
    if len(sys.argv) != 2: sys.exit(__doc__.strip())
    ids = build(sys.argv[1])
    if not ids: sys.exit(f"no '@base' profiles with a filament_id in {sys.argv[1]}")
    with open(OUT, "w", encoding="utf-8") as f: json.dump(ids, f, indent=1, ensure_ascii=False); f.write("\n")
    print(f"{len(ids)} filament IDs -> {os.path.normpath(OUT)}")
