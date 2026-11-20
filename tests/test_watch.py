"""Watch event logic, fed simulated printer states (no printer needed)."""
import importlib.util, io, os, shlex, sys, tempfile, types, unittest
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
                                     progress_every=30, exit_on_alert=False, exit_on_progress=False)
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

    def test_exit_on_progress(self):
        self.w.a.exit_on_progress = True
        with redirect_stdout(io.StringIO()):
            self.w.start(state(), 0)
            self.assertIsNone(self.w.check(state(layer=6, rem=890), 10 * 60))
            self.assertEqual(self.w.check(state(layer=7, rem=880), 31 * 60), 4)

    def test_calibration_is_not_a_stall(self):
        kinds = self.run_seq([(0, state("PREPARE")), (60 * 60, state("PREPARE")), (61 * 60, state("RUNNING"))])
        self.assertNotIn("alert:warning", kinds)   # an hour of calibration, then printing: no stall

    def test_cancel(self):
        kinds = self.run_seq([(0, state()), (60, state("IDLE"))])
        self.assertEqual(kinds, ["started:info", "stopped:warning"])


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.snap = os.path.join(self.dir, "cur.jpg")
        open(self.snap, "wb").close()
        self.args = types.SimpleNamespace(no_snap=False, dir=self.dir, max_nozzle=300, max_bed=110, stall_min=20,
                                          progress_every=30, exit_on_alert=False, exit_on_progress=True,
                                          judge=None, sliced=None)
        self.w = bbl.Watch(types.SimpleNamespace(serial="TEST", mask=lambda t: t), self.args)
        self.w._snap = lambda kind: {"snapshot": self.snap}

    def judge_cmd(self, code):
        return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"

    def progress(self, judge, layer=34):
        self.args.judge = judge
        out = io.StringIO()
        with redirect_stdout(out):
            self.w.start(state(layer=5), 0)
            code = self.w.check(state(layer=layer, rem=800), 31 * 60)
        events = [json.loads(l) for l in out.getvalue().splitlines()]
        return code, [e for e in events if e["kind"] == "progress"][0]

    def test_ok_keeps_watching_even_with_exit_on_progress(self):
        code, ev = self.progress(self.judge_cmd("print('ok all good')"))
        self.assertIsNone(code)
        self.assertEqual((ev["verdict"], ev["judge_note"]), ("ok", "all good"))

    def test_off_and_failed_exit_5(self):
        for word in ("off", "failed"):
            with self.subTest(word):
                self.setUp()
                code, ev = self.progress(self.judge_cmd(f"print('{word.upper()}: stringing near the top')"))
                self.assertEqual((code, ev["verdict"]), (5, word))
                self.assertEqual(ev["judge_note"], "stringing near the top")

    def test_broken_judge_is_error_and_exits_5(self):
        for cmd in ("import sys; sys.exit(3)", "print('maybe fine')", "pass"):
            with self.subTest(cmd):
                self.setUp()
                code, ev = self.progress(self.judge_cmd(cmd))
                self.assertEqual((code, ev["verdict"]), (5, "error"))

    def test_missing_snapshot_is_error(self):
        self.w._snap = lambda kind: {"snapshot_error": "camera down"}
        code, ev = self.progress(self.judge_cmd("print('ok')"))
        self.assertEqual((code, ev["verdict"]), (5, "error"))

    def test_layer_zero_is_not_judged(self):
        code, ev = self.progress(self.judge_cmd("print('failed')"), layer=0)
        self.assertIsNone(code)
        self.assertNotIn("verdict", ev)

    def test_prompt_carries_the_facts_and_criteria(self):
        sink = os.path.join(self.dir, "stdin.txt")
        cmd = self.judge_cmd(f"import sys; open({sink!r}, 'w').write(sys.stdin.read()); print('ok')")
        self.progress(cmd)
        prompt = open(sink).read()
        self.assertIn(self.snap, prompt)
        self.assertIn("Layer 34 of 131", prompt)
        self.assertIn("Previous snapshot: none", prompt)
        self.assertIn(open(bbl.JUDGE_PROMPT, encoding="utf-8").read().strip(), prompt)
        self.assertIn("should look like now: unknown", prompt)

    def test_sliced_file_describes_the_expected_features(self):
        gcode = os.path.join(self.dir, "p.gcode")
        with open(gcode, "w") as f:
            f.write("; CHANGE_LAYER\n; Z_HEIGHT: 0.2\n; FEATURE: Outer wall\n; CHANGE_LAYER\n; Z_HEIGHT: 0.4\n; FEATURE: Sparse infill\n")
        text, filament = bbl.expected_features(gcode, 2)
        self.assertIn("Sparse infill", text)
        self.assertIsNone(filament)
        self.assertEqual(bbl.expected_features(None, 2), (None, None))
        self.assertEqual(bbl.expected_features(gcode, 99), (None, None))

    def test_second_prompt_names_the_previous_snapshot(self):
        sink = os.path.join(self.dir, "stdin.txt")
        self.args.judge = self.judge_cmd(f"import sys; open({sink!r}, 'w').write(sys.stdin.read()); print('ok')")
        with redirect_stdout(io.StringIO()):
            self.w.start(state(layer=5), 0)
            self.w.check(state(layer=30, rem=800), 31 * 60)
            self.w.check(state(layer=60, rem=700), 62 * 60)
        self.assertIn(f"Previous snapshot: {self.snap}", open(sink).read())


class CodesTest(unittest.TestCase):
    def test_error_code_format(self):
        self.assertEqual(bbl.error_code(50348044), "0300400C")
        self.assertIsNone(bbl.error_code(0))

    def test_hms_format(self):
        self.assertEqual(bbl.hms_codes([{"attr": 0x0C000100, "code": 0x00010004}]), ["0C00-0100-0001-0004"])


if __name__ == "__main__":
    unittest.main()
