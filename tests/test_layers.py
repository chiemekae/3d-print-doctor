"""Layer features: grouping a synthetic sliced file's layers into runs (no printer needed)."""
import os, subprocess, sys, tempfile, unittest, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "layers.py")


def layer(z, *features):
    return f"; CHANGE_LAYER\n; Z_HEIGHT: {z}\n" + "".join(
        f"; FEATURE: {f}\nG1 X1 Y1 E1\n" for f in features)


GCODE = ("; FEATURE: Custom\nG1 X0 Y0 E5\n"
         + layer(0.2, "Outer wall", "Bottom surface", "Custom")
         + layer(0.4, "Outer wall", "Sparse infill")
         + layer(0.6, "Sparse infill", "Outer wall")
         + layer(0.8, "Outer wall", "Top surface")
         + layer(1.0, "Outer wall"))


def run(*args):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "part.gcode.3mf")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Metadata/plate_1.gcode", GCODE)
        return subprocess.run([sys.executable, "-I", SCRIPT, path, *args],
                              capture_output=True, text=True)


class LayersTest(unittest.TestCase):
    def test_lists_every_run_of_matching_layers(self):
        self.assertEqual(run().stdout.splitlines(), [
            "5 layers",
            "layer 1 (z 0.2 mm): Bottom surface, Outer wall",
            "layers 2-3 (z 0.4-0.6 mm): Outer wall, Sparse infill",
            "layer 4 (z 0.8 mm): Outer wall, Top surface",
            "layer 5 (z 1 mm): Outer wall",
        ])

    def test_at_marks_the_current_run_with_its_neighbours(self):
        self.assertEqual(run("--at", "3").stdout.splitlines(), [
            "layer 3 of 5, z 0.6 mm",
            "  layer 1 (z 0.2 mm): Bottom surface, Outer wall",
            "> layers 2-3 (z 0.4-0.6 mm): Outer wall, Sparse infill",
            "  layer 4 (z 0.8 mm): Outer wall, Top surface",
        ])

    def test_at_outside_the_print_is_an_error(self):
        r = run("--at", "9")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("outside 1-5", r.stderr)


if __name__ == "__main__":
    unittest.main()
