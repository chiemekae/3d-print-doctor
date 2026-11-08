"""Filament-to-spool check before a print starts, on synthetic sliced files and printer states."""
import importlib.util, io, json, os, unittest, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("bbl", os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "bbl.py"))
bbl = importlib.util.module_from_spec(spec); spec.loader.exec_module(bbl)

SLICE_INFO = """<config><plate><metadata key="index" value="1"/>
<filament id="1" type="PLA" color="#00AE42" used_g="14"/>
<filament id="2" type="PETG" color="#161616" used_g="4"/></plate>
<plate><metadata key="index" value="2"/><filament id="3" type="TPU" color="#FFFFFF" used_g="9"/></plate></config>"""
STATUS = {"ams_trays": [{"ams": "0", "slot": "0", "type": "PETG", "color": "161616FF"},
                        {"ams": "0", "slot": "1", "type": "PLA", "color": "FFFFFFFF"},
                        {"ams": "0", "slot": "2", "type": "PETG", "color": "FFFFFFFF"},
                        {"ams": "0", "slot": "3", "type": "PLA", "color": "00AE42FF"},
                        {"ams": "1", "slot": "0", "type": "", "color": ""}],
          "external_spool": {"tray_type": "TPU", "tray_color": "161616FF"}}


def package(slice_info=SLICE_INFO, settings=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if slice_info is not None: z.writestr("Metadata/slice_info.config", slice_info)
        if settings is not None: z.writestr("Metadata/project_settings.config", json.dumps(settings))
    return zipfile.ZipFile(buf)


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.fil = bbl.sliced_filaments(package())

    def test_reads_used_filaments_per_plate(self):
        self.assertEqual(self.fil, [(1, "PLA", "#00AE42"), (2, "PETG", "#161616")])
        self.assertEqual(bbl.sliced_filaments(package(), plate=2), [(3, "TPU", "#FFFFFF")])

    def test_falls_back_to_project_settings(self):
        z = package(None, {"filament_type": ["PLA", "PETG"], "filament_colour": ["#00AE42", "#161616"]})
        self.assertEqual(bbl.sliced_filaments(z), self.fil)

    def test_correct_mapping(self):
        errors, lines = bbl.check_mapping(self.fil, STATUS, [3, 0])
        self.assertEqual(errors, [])
        self.assertIn("filament 1: PLA #00AE42 -> AMS 1 slot 4 (tray 3): PLA #00AE42", lines)

    def test_swapped_types_are_refused(self):
        errors, _ = bbl.check_mapping(self.fil, STATUS, [0, 3])
        self.assertEqual(len(errors), 2)
        self.assertIn("filament 1 is PLA, but AMS 1 slot 1 (tray 0) holds PETG", errors)

    def test_wrong_color_when_the_right_one_is_loaded(self):
        errors, _ = bbl.check_mapping(self.fil, STATUS, [3, 2])   # white PETG instead of the black in slot 1
        self.assertEqual(len(errors), 1)
        self.assertIn("loaded in AMS 1 slot 1 (tray 0)", errors[0])

    def test_other_color_is_only_a_note_when_no_match_is_loaded(self):
        fil = [(1, "PLA", "#FF0000")]
        errors, lines = bbl.check_mapping(fil, STATUS, [3])
        self.assertEqual(errors, [])
        self.assertTrue(any("color differs" in l for l in lines))

    def test_missing_and_empty_trays(self):
        errors, _ = bbl.check_mapping(self.fil, STATUS, [3])
        self.assertIn("filament 2: no AMS tray given", errors[0])
        errors, _ = bbl.check_mapping(self.fil, STATUS, [3, 4])
        self.assertIn("empty", errors[0])

    def test_external_spool(self):
        errors, _ = bbl.check_mapping(self.fil, STATUS, None)
        self.assertTrue(any("external spool feeds one" in e for e in errors))
        errors, _ = bbl.check_mapping([(1, "TPU", "#161616")], STATUS, None)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
