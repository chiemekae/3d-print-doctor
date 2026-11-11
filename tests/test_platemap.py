"""Plate map: parsing a synthetic sliced file (no printer or OrcaSlicer needed)."""
import importlib.util, os, subprocess, sys, tempfile, unittest, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "platemap.py")
spec = importlib.util.spec_from_file_location("platemap", SCRIPT)
platemap = importlib.util.module_from_spec(spec); spec.loader.exec_module(platemap)

GCODE = """; HEADER_BLOCK_START
; filament_colour = #00AE42;#161616
; filament_settings_id = "My PLA";"My PETG"
; filament_type = PLA;PETG
; printable_area = 0x0,256x0,256x256,0x256
M620 S0A
G1 X10 Y-2 E5 ; start purge line, before the first layer: not drawn
T1000
; CHANGE_LAYER
; FEATURE: Outer wall
G1 X50 Y50 F3000
G1 X80 Y50 E1.2
G2 X80 Y70 I0 J10 E0.8
; FEATURE: Prime tower
G1 X200 Y200
G1 X230 Y200 E1
G1 X230 Y230 E1
; FEATURE: Custom
G1 X150 Y250 E3 ; filament change: not drawn
M620 S1A
T1
; FEATURE: Support
G1 X60 Y40
G1 X70 Y40 E0.4
; FEATURE: Sparse infill
G1 X60 Y60 E0.4
; FEATURE: Prime tower
G1 X205 Y205
G1 X210 Y210 E1
G1 X220 Y220
G1 X221 Y220 E-0.8 ; retraction: not drawn
"""


class PlateMapTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.pkg = os.path.join(self.d, "job.gcode.3mf")
        with zipfile.ZipFile(self.pkg, "w") as z:
            z.writestr("Metadata/plate_1.gcode", GCODE)

    def run_map(self, *args):
        out = os.path.join(self.d, "map.svg")
        r = subprocess.run([sys.executable, "-I", SCRIPT, self.pkg, out, "--svg", *args], capture_output=True, text=True)
        return r, out

    def test_segments(self):
        segs = platemap.parse(GCODE.splitlines())
        self.assertFalse([s for s in segs if s[3] < 0 or s[5] < 0], "start purge line drawn")
        self.assertFalse([s for s in segs if s[1] == "Custom"], "filament-change moves drawn")
        self.assertEqual({s[0] for s in segs if s[1] == "Outer wall"}, {0})
        self.assertEqual({s[0] for s in segs if s[1] == "Support"}, {1})
        arc = [s for s in segs if s[1] == "Outer wall"][1:]
        self.assertGreater(len(arc), 5, "arc not interpolated")
        self.assertAlmostEqual(min(s[4] for s in arc), 70, delta=0.5)   # clockwise semicircle bulges left to x = 70
        self.assertEqual(platemap.roles(segs, 0), ["parts", "purge block"])
        self.assertEqual(platemap.roles(segs, 1), ["infill", "supports", "purge block"])

    def test_cli(self):
        r, out = self.run_map()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("purge block: x 200-230 mm, y 200-230 mm", r.stdout)
        self.assertIn("(back right)", r.stdout)
        self.assertIn("filament 2: PETG #161616 (My PETG), infill, supports, purge block", r.stdout)
        self.assertIn("warning: filament 2 (PETG) is flushed into the infill of PLA parts", r.stdout)
        svg = open(out).read()
        self.assertIn("#00AE42", svg); self.assertIn("#161616", svg); self.assertIn("Purge block", svg)

    def test_prints_a_url_that_resolves_to_the_output(self):
        import urllib.parse
        out = os.path.join(self.d, "out dir", "plate map.svg")
        os.makedirs(os.path.dirname(out))
        r = subprocess.run([sys.executable, "-I", SCRIPT, self.pkg, out, "--svg"], capture_output=True, text=True)
        url = r.stdout.strip().splitlines()[-1]
        self.assertTrue(url.startswith("file:///") and " " not in url, url)
        self.assertEqual(os.path.realpath(urllib.parse.unquote(urllib.parse.urlparse(url).path)), os.path.realpath(out))

    def test_missing_plate(self):
        r, _ = self.run_map("--plate", "2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("plate_2.gcode", r.stderr)

    def test_same_material_flush_is_fine(self):
        lines = GCODE.replace("filament_type = PLA;PETG", "filament_type = PLA;PLA").splitlines()
        _, summary = platemap.render(lines, "x")
        self.assertFalse([s for s in summary if s.startswith("warning")], summary)

    def test_bed_hotter_than_the_parts_material(self):
        bed = ["; curr_bed_type = Textured PEI Plate", "; textured_plate_temp = 55,70",
               "; textured_plate_temp_initial_layer = 55,70", "; bed_temperature_formula = by_highest_temp"]
        hot = platemap.bed_warning(bed + ["M190 S70"] + GCODE.splitlines(), {0}, ["PLA", "PETG"])
        self.assertIn("bed runs at 70 °C, but the PLA parts' own Textured PEI Plate temperature is 55 °C", hot)
        self.assertIsNone(platemap.bed_warning(bed + ["M190 S55"] + GCODE.splitlines(), {0}, ["PLA", "PETG"]))
        self.assertIsNone(platemap.bed_warning(bed + ["M190 S70"], {1}, ["PLA", "PETG"]))   # PETG parts at 70: fine
        self.assertIsNone(platemap.bed_warning(["M190 S70"], {0}, ["PLA"]))                 # no plate info: no guess

    def test_raster_cells(self):
        grid = platemap.raster([(0, "Outer wall", 10, 10, 20, 10), (1, "Support", 15, 10, 15, 12)], 30, 30)
        row = grid[int(10 / platemap.CELL)]
        cells = [i for i, v in enumerate(row) if v]
        self.assertEqual(cells, list(range(int(10 / platemap.CELL), int(20 / platemap.CELL) + 1)))   # no gaps along a line
        self.assertEqual(row[int(15 / platemap.CELL)], 2)                    # the later extrusion is on top
        self.assertEqual(platemap.raster([(0, "x", -5, -5, 300, 300)], 30, 30)[0][0], 1)   # off-bed parts are clipped

    def test_no_tower(self):
        lines = [l for l in GCODE.splitlines() if "Prime tower" not in l]
        _, summary = platemap.render(lines, "x")
        self.assertIn("purge block: none on this plate", summary)


if __name__ == "__main__":
    unittest.main()
