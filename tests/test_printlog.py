"""Print log: reading sliced files and querying the log, on synthetic files."""
import json, os, subprocess, sys, tempfile, unittest, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "printlog.py")

SETTINGS = {
    "print_settings_id": "0.20mm Standard @BBL X1C", "printer_settings_id": "Bambu Lab X1 Carbon 0.4 nozzle",
    "filament_settings_id": ["My PETG", "My PLA"], "filament_type": ["PETG", "PLA"], "filament_vendor": ["Generic", "Generic"],
    "nozzle_diameter": ["0.4"], "layer_height": "0.2", "nozzle_temperature": ["250", "220"],
    "curr_bed_type": "Textured PEI Plate", "textured_plate_temp": ["70", "55"], "filament_retraction_length": ["nil", "nil"],
    "wall_loops": "3", "different_settings_to_system": ["wall_loops", "nozzle_temperature;", "", ""],
}
SLICE_INFO = """<config><plate><metadata key="prediction" value="7200"/><metadata key="weight" value="40.5"/>
<filament id="1" type="PETG" color="#000000" used_m="13" used_g="40.5"/></plate></config>"""
GCODE = """; HEADER_BLOCK_START
; total estimated time: 1h 30m 0s
; filament used [g] = 12.5
; filament_settings_id = "My TPU"
; print_settings_id = "0.28mm Extra Draft @BBL X1C"
; filament_type = TPU
; nozzle_diameter = 0.4
; nozzle_temperature = 240
; different_settings_to_system = "brim_type;wall_loops";"";""
"""


def run(*args):
    r = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True)
    if r.returncode: raise AssertionError(r.stderr)
    return r.stdout


class PrintLogTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.log, self.pkg, self.gcode = (os.path.join(d, n) for n in ("log.jsonl", "job.gcode.3mf", "job.gcode"))
        with zipfile.ZipFile(self.pkg, "w") as z:
            z.writestr("Metadata/project_settings.config", json.dumps(SETTINGS))
            z.writestr("Metadata/slice_info.config", SLICE_INFO)
        open(self.gcode, "w").write(GCODE)

    def show(self, i):
        return json.loads(run("--log", self.log, "show", str(i)))

    def test_package_keeps_only_used_filament(self):
        run("--log", self.log, "add", "--from", self.pkg, "--result", "success")
        e = self.show(1)
        self.assertEqual(e["material"], "PETG")                    # PLA is configured but unused
        self.assertEqual(e["presets"]["filament"], "My PETG")
        self.assertEqual(e["settings"]["nozzle_temperature"], "250")
        self.assertEqual(e["settings"]["bed_temp"], "70")
        self.assertNotIn("filament_retraction_length", e["settings"])  # 'nil' means no override
        self.assertEqual((e["grams"], e["est_hours"]), (40.5, 2.0))
        self.assertEqual(e["changed_from_system"], ["nozzle_temperature", "wall_loops"])
        self.assertEqual(e["model"], "job")

    def test_plain_gcode_header(self):
        run("--log", self.log, "add", "--from", self.gcode, "--result", "fail", "--issue", "stringing")
        e = self.show(1)
        self.assertEqual((e["material"], e["presets"]["filament"], e["grams"], e["est_hours"]), ("TPU", "My TPU", 12.5, 1.5))
        self.assertEqual(e["changed_from_system"], ["brim_type", "wall_loops"])

    def test_queries(self):
        run("--log", self.log, "add", "--from", self.pkg, "--result", "success")
        run("--log", self.log, "add", "--from", self.pkg, "--result", "success")
        run("--log", self.log, "add", "--from", self.gcode, "--result", "unknown", "--date", "2025-01-02", "--source", "sd:/x")
        run("--log", self.log, "amend", "3", "--result", "fail", "--fix", "dried it")
        self.assertIn("same in all 2", run("--log", self.log, "settings", "--material", "petg"))
        self.assertIn("dried it", run("--log", self.log, "find", "--result", "fail"))
        self.assertEqual(self.show(3)["date"], "2025-01-02")
        self.assertIn("PETG", run("--log", self.log, "stats"))


if __name__ == "__main__":
    unittest.main()
