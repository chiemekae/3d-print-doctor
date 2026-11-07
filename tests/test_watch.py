"""Watch event logic, fed simulated printer states (no printer needed)."""
import importlib.util, io, os, sys, tempfile, types, unittest
from contextlib import redirect_stdout
import json

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("bbl", os.path.join(HERE, "..", "skills", "3d-print-doctor", "scripts", "bbl.py"))
bbl = importlib.util.module_from_spec(spec); spec.loader.exec_module(bbl)


def state(gcode_state="RUNNING", layer=5, rem=900, hms=(), err=None, nozzle=225, bed=35, stage=0):
    return {"gcode_state": gcode_state, "job": "part", "percent": 4, "layer": layer, "total_layers": 131,
            "remaining_min": rem, "stage": stage, "print_error": {"code": err, "meaning": "x"} if err else None,
            "hms": [{"code": c, "meaning": "x"} for c in hms], "nozzle": [nozzle, 225], "bed": [bed, 35]}


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        args = types.SimpleNamespace(no_snap=True, dir=self.dir, max_nozzle=300, max_bed=110, stall_min=20,
                                     progress_every=30, exit_on_alert=False)
        self.w = bbl.Watch(types.SimpleNamespace(serial="TEST", mask=lambda t: t), args)

    def run_seq(self, seq):
        out = io.StringIO()
        with redirect_stdout(out):
            self.w.start(seq[0][1], seq[0][0])
            for t, s in seq[1:]:
                if self.w.check(s, t) is not None: break
        return [json.loads(l)["kind"] + ":" + json.loads(l)["severity"] for l in out.getvalue().splitlines()]

    def test_full_print(self):
        m = 60
        kinds = self.run_seq([
            (0, state(hms=["0C00-0100-0001-0004"])),           # code already active: listed, not alerted
            (1 * m, state(hms=["0C00-0100-0001-0004"])),
            (25 * m, state(hms=["0C00-0100-0001-0004"])),      # no movement for 25 min -> stall
            (26 * m, state(layer=6, rem=890)),
            (31 * m, state(layer=7, rem=880)),                  # 30 min since start -> progress
            (32 * m, state("PAUSE", 7, 880, stage=35, err="0300400C")),
            (33 * m, state("PAUSE", 7, 880, stage=35, err="0300400C")),  # nothing repeated
            (34 * m, state(layer=8, rem=870, nozzle=320)),      # resumed + over temperature
            (35 * m, state("FINISH", 131, 0)),
        ])
        self.assertEqual(kinds, ["started:info", "alert:warning", "progress:info", "paused:warning", "alert:critical",
                                 "resumed:info", "alert:critical", "finished:info"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "events.jsonl")))

    def test_calibration_is_not_a_stall(self):
        kinds = self.run_seq([(0, state("PREPARE")), (60 * 60, state("PREPARE")), (61 * 60, state("RUNNING"))])
        self.assertNotIn("alert:warning", kinds)   # an hour of calibration, then printing: no stall

    def test_cancel(self):
        kinds = self.run_seq([(0, state()), (60, state("IDLE"))])
        self.assertEqual(kinds, ["started:info", "stopped:warning"])


class CodesTest(unittest.TestCase):
    def test_error_code_format(self):
        self.assertEqual(bbl.error_code(50348044), "0300400C")
        self.assertIsNone(bbl.error_code(0))

    def test_hms_format(self):
        self.assertEqual(bbl.hms_codes([{"attr": 0x0C000100, "code": 0x00010004}]), ["0C00-0100-0001-0004"])


if __name__ == "__main__":
    unittest.main()
