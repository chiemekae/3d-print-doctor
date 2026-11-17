"""Specific-filament (Bambu filament ID) check before a print starts, on synthetic sliced files and printer states."""
import importlib.util, io, json, os, unittest, zipfile

spec = importlib.util.spec_from_file_location("bbl", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "3d-print-doctor", "scripts", "bbl.py"))
bbl = importlib.util.module_from_spec(spec); spec.loader.exec_module(bbl)

SLICE_INFO = """<config><plate><metadata key="index" value="1"/>
<filament id="1" tray_info_idx="GFA00" type="PLA" color="#00AE42" used_g="14"/>
<filament id="2" tray_info_idx="GFG99" type="PETG" color="#161616" used_g="4"/></plate>
<plate><metadata key="index" value="2"/><filament id="3" tray_info_idx="GFU01" type="TPU" color="#FFFFFF" used_g="9"/></plate></config>"""
NO_IDX = """<config><plate><metadata key="index" value="1"/>
<filament id="1" type="PLA" color="#00AE42" used_g="14"/></plate></config>"""
STATUS = {"ams_trays": [{"ams": "0", "slot": "0", "type": "PLA", "color": "00AE42FF", "filament_id": "GFA01"},
                        {"ams": "0", "slot": "1", "type": "PLA", "color": "00AE42FF", "filament_id": " gfa00 "},
                        {"ams": "0", "slot": "2", "type": "PLA", "color": "00AE42FF", "filament_id": "GFL99"},
                        {"ams": "0", "slot": "3", "type": "PLA", "color": "00AE42FF", "filament_id": None},
                        {"ams": "1", "slot": "0", "type": "PETG", "color": "00AE42FF", "filament_id": "GFG00"},
                        {"ams": "1", "slot": "1", "type": "PLA", "color": "FF0000FF", "filament_id": "GFA01"}],
          "external_spool": {"tray_type": "PLA", "tray_color": "00AE42FF", "tray_info_idx": "GFA01"}}
PLA = [(1, "PLA", "#00AE42")]


def package(slice_info=SLICE_INFO, settings=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if slice_info is not None: z.writestr("Metadata/slice_info.config", slice_info)
        if settings is not None: z.writestr("Metadata/project_settings.config", settings if isinstance(settings, str) else json.dumps(settings))
    return zipfile.ZipFile(buf)


class FilamentIdTest(unittest.TestCase):
    def test_ids_per_plate(self):
        self.assertEqual(bbl.sliced_filament_ids(package()), {1: "GFA00", 2: "GFG99"})
        self.assertEqual(bbl.sliced_filament_ids(package(), plate=2), {3: "GFU01"})

    def test_ids_fallback(self):
        self.assertEqual(bbl.sliced_filament_ids(package(NO_IDX, {"filament_ids": ["GFA00", "", "GFL99"]})), {1: "GFA00", 3: "GFL99"})
        self.assertEqual(bbl.sliced_filament_ids(package(None, {"filament_ids": ["GFA00"]})), {1: "GFA00"})
        self.assertEqual(bbl.sliced_filament_ids(package(NO_IDX)), {})
        self.assertEqual(bbl.sliced_filament_ids(package(None, "not json")), {})
        self.assertEqual(bbl.sliced_filament_ids(package(None)), {})

    def test_ams_mismatch_message(self):
        errors, _ = bbl.check_mapping(PLA, STATUS, [0], ids={1: "GFA00"})
        self.assertEqual(errors, ["filament 1 is Bambu PLA Basic (GFA00), but AMS 1 slot 1 (tray 0) holds Bambu PLA Matte (GFA01)"])

    def test_external_mismatch(self):
        errors, _ = bbl.check_mapping(PLA, STATUS, None, ids={1: "GFA00"})
        self.assertEqual(errors, ["filament 1 is Bambu PLA Basic (GFA00), but the external spool holds Bambu PLA Matte (GFA01)"])

    def test_unknown_id_label(self):
        errors, _ = bbl.check_mapping(PLA, STATUS, [0], ids={1: "ZZZ12"})
        self.assertEqual(errors, ["filament 1 is ZZZ12, but AMS 1 slot 1 (tray 0) holds Bambu PLA Matte (GFA01)"])

    def test_skips(self):
        for ams, ids in (([1], {1: "GFA00"}),          # padded lowercase equal
                         ([2], {1: "GFA00"}),          # loaded generic
                         ([3], {1: "GFA00"}),          # loaded None
                         ([0], {1: "GFL99"}),          # sliced generic
                         ([0], {1: " gfl99"}),         # sliced generic, messy
                         ([0], {1: ""}), ([0], {1: "  "}), ([0], {1: None}),
                         ([0], {}), ([0], None), ([0], {2: "GFA00"})):
            errors, _ = bbl.check_mapping(PLA, STATUS, ams, ids=ids)
            self.assertEqual(errors, [], (ams, ids))
        self.assertEqual(bbl.check_mapping(PLA, STATUS, [0]), bbl.check_mapping(PLA, STATUS, [0], ids=None))

    def test_type_error_wins(self):
        errors, _ = bbl.check_mapping(PLA, STATUS, [4], ids={1: "GFA00"})
        self.assertEqual(len(errors), 1); self.assertIn("holds PETG", errors[0])
        status = {**STATUS, "ams_trays": STATUS["ams_trays"] + [{"ams": "1", "slot": "2", "type": "", "color": "", "filament_id": "GFA01"}]}
        errors, _ = bbl.check_mapping(PLA, status, [6], ids={1: "GFA00"})
        self.assertEqual(len(errors), 1); self.assertIn("empty", errors[0])

    def test_color_still_checked(self):
        errors, lines = bbl.check_mapping(PLA, STATUS, [5], ids={1: "GFA00"})
        self.assertIn("Bambu PLA Basic (GFA00)", errors[0])
        self.assertTrue(len(errors) == 2 or any("color differs" in l for l in lines), (errors, lines))

    def test_lines_unchanged(self):
        _, a = bbl.check_mapping(PLA, STATUS, [0]); _, b = bbl.check_mapping(PLA, STATUS, [0], ids={1: "GFA00"})
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
