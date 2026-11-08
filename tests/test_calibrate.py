"""Calibration command payload and reply parsing (no printer needed)."""
import importlib.util, io, os, types, unittest
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
BBL = os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "bbl.py")
spec = importlib.util.spec_from_file_location("bbl", BBL)
bbl = importlib.util.module_from_spec(spec); spec.loader.exec_module(bbl)


class CalibrateTest(unittest.TestCase):
    def test_option_bits_match_bambu_studio(self):
        opt = lambda *n: bbl.calibration_request(n)["print"]["option"]
        self.assertEqual(opt("vibration"), 4)
        self.assertEqual(opt("bed_level"), 2)
        self.assertEqual(opt("lidar"), 1)
        self.assertEqual(opt("vibration", "bed_level"), 6)

    def test_request_shape(self):
        p = bbl.calibration_request(["vibration"])["print"]
        self.assertEqual(p["command"], "calibration")
        self.assertIn("sequence_id", p)

    def test_reply(self):
        # Shapes as an X1C on X1Plus 3.1 sent them: the calibration ack among gcode_line acks.
        msgs = [{"print": {"command": "gcode_line", "result": "SUCCESS"}},
                {"print": {"command": "calibration", "result": "success", "option": 4}}]
        self.assertEqual(bbl.calibration_reply(msgs), "success")
        self.assertEqual(bbl.calibration_reply([{"print": {"command": "calibration", "result": "fail"}}]), "fail")
        self.assertIsNone(bbl.calibration_reply([{"print": {"gcode_state": "IDLE"}}]))

    def test_refuses_without_a_calibration_or_yes(self):
        # Both refusals come before the printer is contacted, so no printer object is needed.
        for flags, want in (({"yes": True}, "say which calibration"), ({"vibration": True}, "without --yes")):
            a = types.SimpleNamespace(**{"yes": False, "vibration": False, "bed_level": False, "lidar": False, **flags})
            err = io.StringIO()
            with redirect_stderr(err), self.assertRaises(SystemExit):
                bbl.cmd_calibrate(None, a)
            self.assertIn(want, err.getvalue())


if __name__ == "__main__":
    unittest.main()
