"""addpause.py: inserting a pause into a synthetic sliced file (no printer or OrcaSlicer needed)."""
import hashlib, importlib.util, os, subprocess, sys, tempfile, unittest, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "addpause.py")
spec = importlib.util.spec_from_file_location("addpause", SCRIPT)
addpause = importlib.util.module_from_spec(spec); spec.loader.exec_module(addpause)


def layer(n, z):
    return (f"; CHANGE_LAYER\n; Z_HEIGHT: {z}\n; LAYER_HEIGHT: 0.2\nG1 E-.4 F1800\n"
            f"; layer num/total_layer_count: {n}/3\n; update layer progress\nM73 L{n}\n"
            f"M991 S0 P{n - 1} ;notify layer change\n; FEATURE: Outer wall\nG1 X1 Y1 E.1\n")


GCODE = "; HEADER_BLOCK_START\n; machine_pause_gcode = M400 U1\n" + layer(1, 0.2) + layer(2, 0.4) + layer(3, 0.6)


class AddPause(unittest.TestCase):
    def test_pause_goes_after_the_layer_notification(self):
        new, n, top = addpause.add_pause(GCODE, layer=2)
        self.assertEqual((n, top), (2, 0.4))
        lines = new.split("\n")
        i = lines.index("M991 S0 P1 ;notify layer change")
        self.assertEqual(lines[i + 1:i + 3], ["; PAUSE_PRINTING", "M400 U1"])
        self.assertEqual(new.count("\nM400 U1\n"), 1)

    def test_by_height_matches_by_layer(self):
        self.assertEqual(addpause.add_pause(GCODE, z=0.6)[0], addpause.add_pause(GCODE, layer=3)[0])

    def test_adds_no_moves_of_its_own(self):
        new, _, _ = addpause.add_pause(GCODE, layer=2)
        added = [l for l in new.split("\n") if l not in GCODE.split("\n")]
        self.assertEqual(added, ["; PAUSE_PRINTING", "M400 U1"])

    def test_refuses_a_second_pause_and_a_missing_layer(self):
        once, _, _ = addpause.add_pause(GCODE, layer=2)
        with self.assertRaises(SystemExit):
            addpause.add_pause(once, layer=2)
        with self.assertRaises(SystemExit):
            addpause.add_pause(GCODE, layer=9)

    def test_gcode_3mf_keeps_members_and_fixes_md5(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "job.gcode.3mf"), os.path.join(d, "job paused.gcode.3mf")
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("Metadata/plate_1.gcode", GCODE)
                z.writestr("Metadata/plate_1.gcode.md5", hashlib.md5(GCODE.encode()).hexdigest().upper())
                z.writestr("Metadata/slice_info.config", "<config/>")
            r = subprocess.run([sys.executable, "-I", SCRIPT, src, out, "--layer", "2"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
                self.assertEqual(a.namelist(), b.namelist())
                g = b.read("Metadata/plate_1.gcode")
                self.assertIn(b"; PAUSE_PRINTING\nM400 U1\n", g)
                self.assertEqual(b.read("Metadata/plate_1.gcode.md5").decode(), hashlib.md5(g).hexdigest().upper())
                self.assertEqual(a.read("Metadata/slice_info.config"), b.read("Metadata/slice_info.config"))


if __name__ == "__main__":
    unittest.main()
