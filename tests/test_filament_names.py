"""summarize() adds filament names from bambu-filament-ids.json."""
import importlib.util, os, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("bbl", os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "bbl.py"))
bbl = importlib.util.module_from_spec(spec); spec.loader.exec_module(bbl)

_STATUS = {
    "gcode_state": "RUNNING",
    "ams": {"ams": [{"id": "0", "humidity": "30", "tray": [
        {"id": "0", "tray_type": "PLA", "tray_color": "FFFFFFFF", "tray_info_idx": "GFL05"},
        {"id": "1", "tray_type": "ABS", "tray_color": "000000FF"},
    ]}], "tray_now": 0},
    "vt_tray": {"tray_type": "PLA", "tray_color": "00AE42FF", "tray_info_idx": "GFL05"},
}

_STATUS_NO_AMS = {"gcode_state": "RUNNING", "ams": {}, "vt_tray": {}}


class FilamentNamesTest(unittest.TestCase):
    def test_known_id(self):
        s = bbl.summarize([{"print": _STATUS}])
        self.assertEqual(s["external_spool"]["filament"], "Overture Matte PLA")
        self.assertEqual(s["ams_trays"][0]["filament_id"], "GFL05")
        self.assertEqual(s["ams_trays"][0]["filament"], "Overture Matte PLA")

    def test_unknown_id(self):
        msg = {
            "gcode_state": "RUNNING",
            "ams": {"ams": [{"id": "0", "humidity": "30", "tray": [
                {"id": "0", "tray_type": "PLA", "tray_color": "FFFFFFFF", "tray_info_idx": "ZZZ99"},
            ]}], "tray_now": 0},
            "vt_tray": {"tray_type": "PLA", "tray_color": "00AE42FF", "tray_info_idx": "ZZZ99"},
        }
        s = bbl.summarize([{"print": msg}])
        self.assertIsNone(s["external_spool"]["filament"])
        self.assertEqual(s["ams_trays"][0]["filament_id"], "ZZZ99")
        self.assertIsNone(s["ams_trays"][0]["filament"])

    def test_tray_no_id(self):
        msg = {
            "gcode_state": "RUNNING",
            "ams": {"ams": [{"id": "0", "humidity": "30", "tray": [
                {"id": "0", "tray_type": "PLA", "tray_color": "FFFFFFFF"},
            ]}], "tray_now": 0},
            "vt_tray": {"tray_type": "PLA", "tray_color": "00AE42FF"},
        }
        s = bbl.summarize([{"print": msg}])
        self.assertIsNone(s["external_spool"]["filament"])
        self.assertIsNone(s["ams_trays"][0]["filament_id"])
        self.assertIsNone(s["ams_trays"][0]["filament"])

    def test_no_ams_no_external(self):
        s = bbl.summarize([{"print": _STATUS_NO_AMS}])
        self.assertIsNone(s["external_spool"]["filament"])
        self.assertEqual(s["ams_trays"], [])

    def test_existing_keys_unchanged(self):
        s = bbl.summarize([{"print": _STATUS}])
        self.assertIn("tray_info_idx", s["external_spool"])
        self.assertEqual(s["external_spool"]["tray_info_idx"], "GFL05")
        for t in s["ams_trays"]:
            for k in ("ams", "slot", "type", "color", "humidity"):
                self.assertIn(k, t)


if __name__ == "__main__":
    unittest.main()
