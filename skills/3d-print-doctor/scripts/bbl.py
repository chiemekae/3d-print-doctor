#!/usr/bin/env python3
"""Talk to a Bambu Lab printer on the LAN with the connection details OrcaSlicer already stores.

macOS Local Network privacy blocks non-Apple binaries (Homebrew python, ffmpeg) from reaching LAN
hosts, so every LAN byte here goes through Apple's /usr/bin/openssl or /usr/bin/curl. This script
itself only talks to localhost and to those subprocesses. Standard library only; Python 3.9+; macOS.

The printer access code is read from OrcaSlicer.conf and never printed (masked as ****).
Settings (data folder, temperature ratings) come from ~/.config/3d-print-doctor/config.json.

  bbl.py setup                               detect printers and tools; create the config if missing
  bbl.py status [--json]                     read-only status, temps, layer, HMS/error codes with meanings, spool
  bbl.py watch [--interval 300] [--exit-on-alert] [--wait-start MIN] [--no-snap] [--dir DIR]
                                             watch a print, one JSON event per line (see below)
  bbl.py code CODE...                        meaning of an HMS (AAAA-BBBB-CCCC-DDDD) or error (8 hex) code
  bbl.py ls [DIR]                            list a folder on the printer's SD card (default /)
  bbl.py get REMOTE LOCAL                    download a file from the SD card (e.g. /timelapse/x.mp4)
  bbl.py snap OUT.jpg                        one camera frame
  bbl.py clip OUT.mp4 [--seconds N]          short camera video (default 10 s)
  bbl.py frames DIR --every S --count N [--assemble OUT.mp4]   self-made timelapse of a live print
  bbl.py print FILE.gcode.3mf --yes [--plate 1] [--no-level] [--no-flow] [--timelapse] [--vibration] [--ams 0,1]
                                             upload + start (default: external spool). Refuses when a
                                             filament's type doesn't match its AMS slot or spool (or the
                                             printer is busy); --force-mapping overrides the type check
  bbl.py pause|resume|stop --yes             change the running job
  bbl.py calibrate --yes [--vibration] [--bed-level] [--lidar]
                                             run printer calibrations on an idle printer (at least one)

Global: --serial SERIAL picks a printer when OrcaSlicer knows several.

watch: read-only. Events: started, progress (every --progress-every min), paused, resumed, alert
(new printer error or HMS code, stall: no new layer or time-left change for --stall-min min while
RUNNING, temperature over the rating), finished, failed, stopped, lost (no contact). Each event is
one JSON line on stdout and in DIR/events.jsonl, with a camera snapshot in DIR unless --no-snap.
DIR defaults to <data_dir>/watch/<date>_<job>/. Codes already active when the watch starts are
listed in the started event, not alerted. Exit: 0 finished or nothing printing, 1 lost contact,
2 failed or cancelled, 3 stopped on an alert (--exit-on-alert).
"""
import argparse, collections, glob, hashlib, json, os, re, shutil, socket, struct, subprocess, sys, tempfile, threading, time, urllib.parse, zipfile

ORCA_CONF = os.path.expanduser("~/Library/Application Support/OrcaSlicer/OrcaSlicer.conf")
ORCA_APP = "/Applications/OrcaSlicer.app"
HMS_DIRS = (os.path.expanduser("~/Library/Application Support/OrcaSlicer/hms"), f"{ORCA_APP}/Contents/Resources/hms")
OPENSSL, CURL = "/usr/bin/openssl", "/usr/bin/curl"
ACTIVE = {"PREPARE", "SLICING", "RUNNING", "PAUSE"}
CONFIG = os.path.expanduser("~/.config/3d-print-doctor/config.json")
# Defaults for a printer whose ratings aren't configured: high enough that no model raises a false alarm.
DEFAULT_CONFIG = {"data_dir": "~/3d-print-doctor", "photo_inbox": None, "max_nozzle_c": 350, "max_bed_c": 120, "notes": []}


def config():
    try: return {**DEFAULT_CONFIG, **json.load(open(CONFIG))}
    except (OSError, ValueError): return dict(DEFAULT_CONFIG)


def data_dir():
    return os.path.expanduser(config()["data_dir"])


class PrinterError(Exception):
    """A failed LAN operation. Messages may contain the access code: mask before printing."""


def die(msg, code=1):
    print(msg, file=sys.stderr); sys.exit(code)


# ---------------------------------------------------------------- printer config
class Printer:
    def __init__(self, serial=None):
        c = json.loads(open(ORCA_CONF).read().split("# MD5")[0])
        machines = c.get("local_machines") or {}
        if serial is None:
            if len(machines) != 1:
                die(f"OrcaSlicer knows {len(machines)} printers; pass --serial one of {list(machines)}")
            serial = next(iter(machines))
        if serial not in machines:
            die(f"serial {serial} not in OrcaSlicer local_machines {list(machines)}")
        self.serial, self.ip = serial, machines[serial]["dev_ip"]
        self.name = machines[serial].get("dev_name")
        self.code = (c.get("user_access_code") or {}).get(serial) or die("no LAN access code stored in OrcaSlicer")

    def mask(self, text):
        return text.replace(self.code, "****")


# ---------------------------------------------------------------- MQTT over openssl
def _str(s):
    b = s.encode(); return struct.pack("!H", len(b)) + b

def _len(n):
    out = b""
    while True:
        d, n = n % 128, n // 128
        out += bytes([d | (0x80 if n else 0)])
        if not n: return out

def _pkt(t, body):
    return bytes([t]) + _len(len(body)) + body


class Mqtt:
    def __init__(self, pr):
        self.pr, self.msgs, self.lock, self.connack = pr, [], threading.Lock(), None
        self.p = subprocess.Popen([OPENSSL, "s_client", "-quiet", "-no_ign_eof", "-connect", f"{pr.ip}:8883"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._reader, daemon=True).start()
        body = _str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60) + _str("3d-print-doctor") + _str("bblp") + _str(pr.code)
        self._w(_pkt(0x10, body))
        t0 = time.time()
        # A LAN connect is answered in about 0.2 s (X1C over Wi-Fi); 10 s is headroom for a slow network,
        # and a refused login still fails at once because the CONNACK arrives with a nonzero code.
        while self.connack is None and time.time() - t0 < 10: time.sleep(0.05)
        if self.connack != 0:
            self.p.terminate()
            raise PrinterError(f"MQTT connect failed (connack={self.connack}); is the printer on and the access code current?")
        self._w(_pkt(0x82, struct.pack("!H", 1) + _str(f"device/{pr.serial}/report") + b"\x00"))
        # SUBACK isn't parsed, so give the subscription time to take effect: without this pause, about 1 in 5
        # requests sent right away got no reply (X1C); with it, none of 10 were missed.
        time.sleep(0.4)

    def _w(self, b):
        try: self.p.stdin.write(b); self.p.stdin.flush()
        except (BrokenPipeError, OSError) as e: raise PrinterError(f"MQTT connection dropped: {e}")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            ch = self.p.stdout.read(n - len(buf))
            if not ch: raise EOFError
            buf += ch
        return buf

    def _reader(self):
        try:
            while True:
                h = self._read(1)[0]; mult = 1; ln = 0
                while True:
                    d = self._read(1)[0]; ln += (d & 127) * mult; mult *= 128
                    if not d & 128: break
                body = self._read(ln)
                if h >> 4 == 2: self.connack = body[1]
                elif h >> 4 == 3:
                    tl = struct.unpack("!H", body[:2])[0]
                    off = 2 + tl + (2 if (h >> 1) & 3 else 0)
                    try:
                        with self.lock: self.msgs.append(json.loads(body[off:]))
                    except ValueError: pass
        except EOFError:
            pass

    def publish(self, obj):
        self._w(_pkt(0x30, _str(f"device/{self.pr.serial}/request") + json.dumps(obj).encode()))

    def pushall(self, wait=5):
        # An idle X1C answers with a full status about 0.5 s after the request; 5 s covers a busy printer.
        self.publish({"pushing": {"sequence_id": "1", "command": "pushall"}})
        time.sleep(wait)
        with self.lock: return list(self.msgs)

    def close(self):
        try: self._w(b"\xe0\x00")
        except Exception: pass
        self.p.terminate()


def hms_codes(hms):
    out = []
    for h in hms or []:
        a, c = int(h.get("attr", 0)), int(h.get("code", 0))
        out.append("%04X-%04X-%04X-%04X" % (a >> 16, a & 0xFFFF, c >> 16, c & 0xFFFF))
    return out


def error_code(v):
    """print_error as the 8 hex digits Bambu's wiki and the printer screen use; None when 0."""
    try: v = int(v or 0) & 0xFFFFFFFF
    except (TypeError, ValueError): return None
    return "%08X" % v if v else None


_CODES = None

def code_meaning(code, serial=""):
    """English text for an HMS or printer error code from OrcaSlicer's bundled HMS tables.
    The tables are per printer model; a file for this printer's serial prefix wins when present,
    otherwise the most common text across the bundled tables is returned, marked approximate."""
    global _CODES
    if _CODES is None:
        _CODES = {}
        for d in HMS_DIRS:
            for f in sorted(glob.glob(os.path.join(d, "hms_en_*.json"))):
                try: data = json.load(open(f))["data"]
                except (OSError, ValueError, KeyError): continue
                model = os.path.basename(f)[len("hms_en_"):-len(".json")]
                for sect in ("device_hms", "device_error"):
                    for e in (data.get(sect) or {}).get("en", []):
                        _CODES.setdefault(e["ecode"].upper(), []).append((model, e["intro"]))
    hits = _CODES.get(re.sub(r"[^0-9A-Fa-f]", "", code).upper())
    if not hits: return None
    exact = [t for m, t in hits if serial and m.upper() == serial[:3].upper()]
    if exact: return exact[0]
    return collections.Counter(t for _, t in hits).most_common(1)[0][0] + " (approximate: other models' table)"


def summarize(msgs, pr=None):
    p = {}
    for m in msgs:
        if "print" in m: p.update(m["print"])
    ams, vt = p.get("ams") or {}, p.get("vt_tray") or {}
    serial = pr.serial if pr else ""
    err = error_code(p.get("print_error"))
    return {
        "gcode_state": p.get("gcode_state"), "job": p.get("subtask_name"), "percent": p.get("mc_percent"),
        "remaining_min": p.get("mc_remaining_time"), "layer": p.get("layer_num"), "total_layers": p.get("total_layer_num"),
        "stage": p.get("stg_cur"),
        "print_error": {"code": err, "meaning": code_meaning(err, serial)} if err else None,
        "hms": [{"code": c, "meaning": code_meaning(c, serial)} for c in hms_codes(p.get("hms"))],
        "nozzle": [p.get("nozzle_temper"), p.get("nozzle_target_temper")], "bed": [p.get("bed_temper"), p.get("bed_target_temper")],
        "chamber": p.get("chamber_temper"), "speed_level": p.get("spd_lvl"),
        "fans_pct": {k: p.get(k) for k in ("cooling_fan_speed", "big_fan1_speed", "big_fan2_speed", "heatbreak_fan_speed")},
        "nozzle_diameter": p.get("nozzle_diameter"), "nozzle_type": p.get("nozzle_type"), "sdcard": p.get("sdcard"),
        "external_spool": {k: vt.get(k) for k in ("tray_type", "tray_color", "tray_info_idx", "nozzle_temp_min", "nozzle_temp_max")},
        "tray_now": ams.get("tray_now"),
        "ams_trays": [{"ams": a.get("id"), "slot": t.get("id"), "type": t.get("tray_type"), "color": t.get("tray_color"),
                       "humidity": a.get("humidity")} for a in ams.get("ams", []) for t in a.get("tray", [])],
        "wifi_signal": p.get("wifi_signal"),
    }


# ---------------------------------------------------------------- FTPS over curl
def curl(pr, path, *extra):
    fd, netrc = tempfile.mkstemp(prefix="bbl-netrc-")
    try:
        os.chmod(netrc, 0o600)
        with os.fdopen(fd, "w") as f: f.write(f"machine {pr.ip} login bblp password {pr.code}\n")
        url = f"ftps://{pr.ip}:990/" + urllib.parse.quote(path.lstrip("/"))   # SD-card names often have spaces
        r = subprocess.run([CURL, "-sS", "-k", "--netrc-file", netrc, *extra, url], capture_output=True)
    finally:
        os.unlink(netrc)
    if r.returncode: raise PrinterError(r.stderr.decode(errors="replace").strip() or f"curl failed ({r.returncode})")
    return r.stdout


# ---------------------------------------------------------------- camera over a localhost relay
def _local_host(n):
    """'127.0.0.1' padded with leading zeros to exactly n chars (9..15)."""
    octs, extra = ["127", "0", "0", "1"], n - 9
    for i in (1, 2, 3):
        add = min(2, extra); octs[i] = "0" * add + octs[i]; extra -= add
    return ".".join(octs)


class Relay:
    """One-shot localhost RTSP relay to the printer's RTSPS port, TLS done by Apple's openssl.
    Rewrites the printer URL to an equal-length localhost URL so RTSP framing stays intact, and leaves
    the Authorization header alone because digest auth hashes the client's URI."""
    def __init__(self, pr):
        self.pr = pr
        remote_len = len(f"rtsps://{pr.ip}:322")
        # Any free port works; these sit near RTSP's usual 8554. Five-digit ports first, then four: the
        # padded loopback host (_local_host) makes up the rest of the length, within its 9..15 characters.
        for port in list(range(18554, 18600)) + list(range(8554, 8600)):
            host_len = remote_len - len(f"rtsp://:{port}")
            if 9 <= host_len <= 15:
                self.srv = socket.socket(); self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try: self.srv.bind(("127.0.0.1", port))
                except OSError: continue
                break
        else:
            raise PrinterError("no free relay port, or the printer IP is too short or long for the equal-length URL rewrite")
        self.local = f"rtsp://{_local_host(host_len)}:{port}"
        self.REMOTE, self.LOCAL = f"rtsps://{pr.ip}:322".encode(), self.local.encode()
        assert len(self.REMOTE) == len(self.LOCAL)
        self.srv.listen(1); self.srv.settimeout(30)
        threading.Thread(target=self._serve, daemon=True).start()

    def url(self):
        return f"rtsp://bblp:{self.pr.code}@{self.local[len('rtsp://'):]}/streaming/live/1"

    def _serve(self):
        try: cl, _ = self.srv.accept()
        except OSError: return
        up = subprocess.Popen([OPENSSL, "s_client", "-quiet", "-no_ign_eof", "-connect", f"{self.pr.ip}:322"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        def c2s():
            try:
                while True:
                    b = cl.recv(65536)
                    if not b: break
                    if not b.startswith(b"$"):
                        b = b"\r\n".join(l if l.lower().startswith(b"authorization:") else l.replace(self.LOCAL, self.REMOTE)
                                         for l in b.split(b"\r\n"))
                    up.stdin.write(b); up.stdin.flush()
            except Exception: pass
            finally:
                try: up.stdin.close()
                except Exception: pass
        def s2c():
            try:
                while True:
                    b = up.stdout.read1(65536)
                    if not b: break
                    cl.sendall(b.replace(self.REMOTE, self.LOCAL))
            except Exception: pass
            finally: cl.close()
        t1 = threading.Thread(target=c2s, daemon=True); t1.start(); s2c(); up.terminate(); self.srv.close()


def ffmpeg(pr, *args):
    exe = shutil.which("ffmpeg") or die("ffmpeg not found (brew install ffmpeg)")
    relay = Relay(pr)
    r = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", relay.url(), *args],
                       capture_output=True)
    if r.returncode:
        raise PrinterError(r.stderr.decode(errors="replace").strip() + "\n(is LAN liveview enabled on the printer?)")


def read_status(pr):
    m = Mqtt(pr)
    try: msgs = m.pushall()
    finally: m.close()
    s = summarize(msgs, pr)
    if s["gcode_state"] is None: raise PrinterError("no status received")
    return s


# ---------------------------------------------------------------- watch
class Watch:
    def __init__(self, pr, a):
        self.pr, self.a, self.dir = pr, a, a.dir
        self.alerted = False

    def _snap(self, kind):
        os.makedirs(self.dir, exist_ok=True)
        out = os.path.join(self.dir, time.strftime("%Y%m%d-%H%M%S") + f"_{kind}.jpg")
        try:
            ffmpeg(self.pr, "-frames:v", "1", "-q:v", "2", "-y", out); return {"snapshot": out}
        except PrinterError as e:
            return {"snapshot_error": self.pr.mask(str(e)).splitlines()[0]}

    def emit(self, kind, severity, message, s=None, snap=True):
        ev = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "severity": severity, "message": message}
        if s:
            ev.update({k: s[k] for k in ("gcode_state", "job", "percent", "layer", "total_layers", "remaining_min", "stage")})
            ev["nozzle"], ev["bed"] = s["nozzle"], s["bed"]
        if snap and not self.a.no_snap: ev.update(self._snap(kind))
        line = json.dumps(ev, ensure_ascii=False)
        print(line, flush=True)
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "events.jsonl"), "a") as f: f.write(line + "\n")
        if severity in ("warning", "critical"): self.alerted = True

    @staticmethod
    def _codes(s):
        out = {h["code"]: h["meaning"] for h in s["hms"]}
        if s["print_error"]: out[s["print_error"]["code"]] = s["print_error"]["meaning"]
        return out

    @staticmethod
    def _progress(s):
        parts = [s["job"] or "print", f"{s['percent']}%", f"layer {s['layer']}/{s['total_layers']}"]
        if s["remaining_min"] is not None: parts.append("%d h %02d min left" % divmod(s["remaining_min"], 60))
        return " · ".join(str(p) for p in parts)

    def start(self, s, now):
        if not self.dir:
            job = re.sub(r"[^\w.-]+", "_", s["job"] or "print")[:60]
            self.dir = os.path.join(data_dir(), "watch", f"{time.strftime('%Y-%m-%d')}_{job}")
        self.seen = set(self._codes(s))
        self.paused = s["gcode_state"] == "PAUSE"
        self.last_key, self.last_change, self.last_progress = (s["layer"], s["remaining_min"]), now, now
        self.stalled, self.hot = False, set()
        msg = f"watching {self._progress(s)} ({s['gcode_state']})"
        if self.seen: msg += "; already active: " + "; ".join(f"{c}: {m}" for c, m in self._codes(s).items())
        self.emit("started", "info", msg, s)

    def check(self, s, now):
        """Announce what changed. Returns an exit code when the job has ended, else None."""
        st = s["gcode_state"]
        if st == "FINISH":
            self.emit("finished", "info", f"{s['job']} finished", s); return 0
        if st == "FAILED":
            err = s["print_error"]
            self.emit("failed", "critical", "print failed" + (f": {err['code']} {err['meaning']}" if err else ""), s); return 2
        if st not in ACTIVE:
            self.emit("stopped", "warning", f"printer is {st}; the job was cancelled", s); return 2

        if st == "PAUSE" and not self.paused:
            self.paused = True
            self.emit("paused", "warning", f"paused at stage {s['stage']} (look it up in printer-lan.md)", s)
        elif st != "PAUSE" and self.paused:
            self.paused = False; self.emit("resumed", "info", self._progress(s), s)

        for c, m in self._codes(s).items():
            if c not in self.seen:
                self.seen.add(c)
                sev = "critical" if s["print_error"] and c == s["print_error"]["code"] else "warning"
                self.emit("alert", sev, f"new code {c}: {m or 'unknown (not in OrcaSlicer HMS tables)'}", s)

        for name, (cur, _), limit in (("nozzle", s["nozzle"], self.a.max_nozzle), ("bed", s["bed"], self.a.max_bed)):
            if cur is not None and cur > limit + 10 and name not in self.hot:
                self.hot.add(name)
                self.emit("alert", "critical", f"{name} at {cur:.0f} °C, above its {limit} °C rating", s)

        key = (s["layer"], s["remaining_min"])
        if st != "RUNNING" or key != self.last_key:
            self.last_key, self.last_change, self.stalled = key, now, False
        elif now - self.last_change >= self.a.stall_min * 60 and not self.stalled:
            self.stalled = True
            self.emit("alert", "warning", f"no new layer and no change in time left for {self.a.stall_min}+ min", s)

        if st == "RUNNING" and now - self.last_progress >= self.a.progress_every * 60:
            self.last_progress = now; self.emit("progress", "info", self._progress(s), s)
        return None

    def run(self):
        a, deadline, failures, watching = self.a, time.time() + self.a.wait_start * 60, 0, False
        while True:
            try:
                s = read_status(self.pr); failures = 0
            except PrinterError as e:
                failures += 1
                print(f"check failed ({failures}/{a.max_failures}): {self.pr.mask(str(e))}", file=sys.stderr, flush=True)
                if failures >= a.max_failures:
                    if self.dir: self.emit("lost", "warning", f"no contact with the printer after {failures} tries", snap=False)
                    return 1
                time.sleep(a.interval); continue
            now = time.time()
            if not watching:
                if s["gcode_state"] in ACTIVE:
                    watching = True; self.start(s, now)
                elif now < deadline:
                    time.sleep(30); continue   # preparation takes minutes; two checks a minute is enough
                else:
                    print(json.dumps({"kind": "idle", "message": f"no print running (printer is {s['gcode_state']})"}), flush=True)
                    return 0
            else:
                code = self.check(s, now)
                if code is not None: return code
            if a.exit_on_alert and self.alerted: return 3
            time.sleep(a.interval)


# ---------------------------------------------------------------- commands
def orca_models():
    """Printer model id (OrcaSlicer.conf printer_type) -> model name, from OrcaSlicer's bundled profiles."""
    out = {}
    for f in glob.glob(f"{ORCA_APP}/Contents/Resources/profiles/BBL/machine/*.json"):
        try: d = json.load(open(f))
        except (OSError, ValueError): continue
        if d.get("model_id"): out[d["model_id"]] = d.get("name")
    return out


def camera_note(model_id):
    if model_id == "BL-P001": return "RTSPS camera: tested"
    if model_id in ("BL-P002", "C13"): return "RTSPS camera (X1 series): expected to work, untested"
    if model_id in ("C11", "C12", "N1", "N2S"):
        return "camera not supported: P1/A1 printers use a different camera protocol (status, SD card, watch without snapshots still work)"
    return "camera untested on this model: try `bbl.py snap`; if it fails, use watch --no-snap"


def cmd_setup(a):
    out = {"config": CONFIG}
    try:
        c = json.loads(open(ORCA_CONF).read().split("# MD5")[0])
        machines, codes = c.get("local_machines") or {}, c.get("user_access_code") or {}
        models = orca_models()
        out["printers"] = [{"name": m.get("dev_name"), "model": models.get(m.get("printer_type"), m.get("printer_type")),
                            "access_code_stored": s in codes, "camera": camera_note(m.get("printer_type"))}
                           for s, m in machines.items()]
        if not machines: out["printers"] = "none bound: connect the printer in OrcaSlicer's Device tab (LAN mode, access code)"
    except (OSError, ValueError):
        out["printers"] = f"OrcaSlicer config not found at {ORCA_CONF}: install OrcaSlicer and bind the printer"
    out["tools"] = {"orcaslicer_app": os.path.isdir(ORCA_APP), "ffmpeg": shutil.which("ffmpeg") or "missing: brew install ffmpeg (camera)",
                    "hms_tables": sum(len(glob.glob(os.path.join(d, "hms_en_*.json"))) for d in HMS_DIRS)}
    if not os.path.exists(CONFIG):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f: json.dump(DEFAULT_CONFIG, f, indent=1)
        out["config_created"] = True
    out["config_contents"] = config()
    print(json.dumps(out, indent=1, ensure_ascii=False))


def cmd_status(pr, a):
    print(json.dumps(read_status(pr), indent=None if a.json else 1))


def cmd_watch(pr, a):
    if a.interval < 60: die("--interval must be at least 60 seconds")
    sys.exit(Watch(pr, a).run())


def cmd_code(pr, a):
    for c in a.codes: print(f"{c}: {code_meaning(c, pr.serial if pr else '') or 'not in OrcaSlicer HMS tables'}")


def cmd_ls(pr, a):
    path = a.dir.rstrip("/") + "/"
    sys.stdout.write(curl(pr, path, "-l").decode(errors="replace"))


def cmd_get(pr, a):
    curl(pr, a.remote, "-o", a.local); print(f"saved {a.local} ({os.path.getsize(a.local)} bytes)")


def cmd_snap(pr, a):
    ffmpeg(pr, "-frames:v", "1", "-q:v", "2", "-y", a.out); print(f"saved {a.out}")


def cmd_clip(pr, a):
    ffmpeg(pr, "-t", str(a.seconds), "-c", "copy", "-y", a.out); print(f"saved {a.out}")


def cmd_frames(pr, a):
    os.makedirs(a.dir, exist_ok=True)
    for i in range(a.count):
        out = os.path.join(a.dir, "frame_%04d.jpg" % i)
        ffmpeg(pr, "-frames:v", "1", "-q:v", "2", "-y", out); print(f"saved {out}", flush=True)
        if i < a.count - 1: time.sleep(a.every)
    if a.assemble:
        exe = shutil.which("ffmpeg")
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-framerate", "8", "-pattern_type", "glob",
                        "-i", os.path.join(a.dir, "frame_*.jpg"), "-pix_fmt", "yuv420p", a.assemble], check=True)
        print(f"saved {a.assemble}")


def need_yes(a, what):
    if not a.yes: die(f"refusing to {what} without --yes (get the user's go-ahead first)")


def sliced_filaments(z, plate=1):
    """[(filament number, type, #RRGGBB)] for the filaments a plate uses, from slice_info.config;
    every project filament from project_settings.config when slice_info has none."""
    out = []
    try:
        info = z.read("Metadata/slice_info.config").decode(errors="replace")
        plates = re.split(r"<plate>", info)[1:]
        for block in plates:
            if re.search(r'key="index" value="(\d+)"', block) and \
               int(re.search(r'key="index" value="(\d+)"', block).group(1)) != plate: continue
            for m in re.finditer(r"<filament ([^>]*)/>", block):
                attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
                out.append((int(attrs.get("id", 0)), attrs.get("type", ""), attrs.get("color", "")))
    except KeyError:
        pass
    if not out:
        try:
            s = json.loads(z.read("Metadata/project_settings.config"))
            types, colors = s.get("filament_type") or [], s.get("filament_colour") or []
            out = [(i + 1, ty, colors[i] if i < len(colors) else "") for i, ty in enumerate(types)]
        except (KeyError, ValueError):
            pass
    return out


def check_mapping(filaments, status, ams):
    """Compare each filament the plate uses with the spool it would print from.
    Returns (errors, lines): errors block the start; lines describe the mapping either way."""
    norm_type = lambda s: (s or "").strip().upper()
    norm_color = lambda s: (s or "").strip().lstrip("#").upper()[:6]
    errors, lines, trays = [], [], {}
    if ams is None:
        if len(filaments) > 1:
            errors.append(f"the plate uses {len(filaments)} filaments, but the external spool feeds one; pass --ams")
        sources = {n: ("the external spool", status.get("external_spool") or {}) for n, _, _ in filaments[:1]}
    else:
        trays = {int(t["ams"]) * 4 + int(t["slot"]): t for t in status.get("ams_trays") or []
                 if str(t.get("ams", "")).isdigit() and str(t.get("slot", "")).isdigit()}
        sources = {}
        for n, _, _ in filaments:
            if n - 1 >= len(ams) or ams[n - 1] < 0:
                errors.append(f"filament {n}: no tray number given (--ams lists one per filament, in order)")
                continue
            tray = ams[n - 1]
            t = trays.get(tray) or {}
            sources[n] = (f"AMS {tray // 4 + 1} slot {tray % 4 + 1} (tray {tray})",
                          {"tray_type": t.get("type"), "tray_color": t.get("color")})
    for n, kind, color in filaments:
        if n not in sources: continue
        where, spool = sources[n]
        have_type, have_color = norm_type(spool.get("tray_type")), norm_color(spool.get("tray_color"))
        lines.append(f"filament {n}: {kind} #{norm_color(color)} -> {where}: "
                     f"{have_type or 'empty'}{' #' + have_color if have_color else ''}")
        if not have_type:
            errors.append(f"filament {n} ({kind}): {where} is empty or unknown to the printer")
        elif have_type != norm_type(kind):
            errors.append(f"filament {n} is {kind}, but {where} holds {have_type}")
        elif color and have_color and norm_color(color) != have_color:
            better = [f"AMS {i // 4 + 1} slot {i % 4 + 1} (tray {i})" for i, tr in sorted(trays.items())
                      if norm_type(tr.get("type")) == have_type and norm_color(tr.get("color")) == norm_color(color)] \
                if ams is not None else []
            if better:
                errors.append(f"filament {n} is #{norm_color(color)} {kind}, which is loaded in {', '.join(better)}, "
                              f"but it maps to {where} (#{have_color})")
            else:
                lines.append(f"  note: color differs (sliced #{norm_color(color)}, loaded #{have_color}); fine if intended")
    return errors, lines


def cmd_print(pr, a):
    need_yes(a, "start a print")
    with zipfile.ZipFile(a.file) as z:
        gpath = f"Metadata/plate_{a.plate}.gcode"
        if gpath not in z.namelist(): die(f"{a.file} has no {gpath}; export it with OrcaSlicer --export-3mf after slicing")
        md5 = hashlib.md5(z.read(gpath)).hexdigest().upper()
        filaments = sliced_filaments(z, a.plate)
    ams = [int(x) for x in a.ams.split(",")] if a.ams else None
    m = Mqtt(pr); status = summarize(m.pushall(), pr); m.close()
    if status.get("gcode_state") is None: die("no status from the printer; not starting")
    if status.get("gcode_state") in ACTIVE:
        die(f"the printer is busy ({status.get('gcode_state')}: {status.get('job')}); not starting another job")
    errors, lines = check_mapping(filaments, status, ams)
    print("\n".join(lines), file=sys.stderr)
    if errors and not a.force_mapping:
        die("filament mapping doesn't match what's loaded:\n  " + "\n  ".join(errors) +
            "\nfix --ams (or load the right spool); --force-mapping starts anyway")
    name = os.path.basename(a.file).replace(" ", "_")
    curl(pr, name, "-T", a.file)
    listing = curl(pr, "/", "-l").decode(errors="replace").split()
    if name not in listing: die(f"upload of {name} not visible on SD card")
    ams = ams or [0]
    req = {"print": {"sequence_id": "20", "command": "project_file", "param": gpath, "project_id": "0", "profile_id": "0",
                     "task_id": "0", "subtask_id": "0", "subtask_name": a.name or os.path.splitext(os.path.basename(a.file))[0],
                     "url": f"file:///sdcard/{name}", "md5": md5, "timelapse": a.timelapse, "bed_type": "auto",
                     "bed_levelling": not a.no_level, "bed_leveling": not a.no_level, "flow_cali": not a.no_flow,
                     "vibration_cali": a.vibration, "layer_inspect": False, "use_ams": bool(a.ams), "ams_mapping": ams}}
    # The wait only decides how fresh the summary printed below is; the start doesn't depend on it.
    # 15 s gives the printer time to pick up the job, so the summary usually shows it starting.
    m = Mqtt(pr); m.publish(req); msgs = m.pushall(wait=15); m.close()
    print(json.dumps(summarize(msgs, pr), indent=1))


def cmd_job(pr, a):
    need_yes(a, a.cmd)
    # As in cmd_print, the wait only decides how fresh the reported state is; 6 s usually shows the change.
    m = Mqtt(pr); m.publish({"print": {"sequence_id": "21", "command": a.cmd}}); msgs = m.pushall(wait=6); m.close()
    s = summarize(msgs, pr); print(json.dumps({k: s[k] for k in ("gcode_state", "job", "percent", "stage", "hms")}))


# Bit positions of the "calibration" command's option field, from Bambu Studio's
# MachineObject::command_start_calibration. Vibration was tested on an X1C; the others are untested.
CALIBRATIONS = {"lidar": 0, "bed_level": 1, "vibration": 2}


def calibration_request(names):
    """The MQTT payload that starts the named calibrations."""
    return {"print": {"sequence_id": "22", "command": "calibration",
                      "option": sum(1 << CALIBRATIONS[n] for n in names)}}


def calibration_reply(msgs):
    """The printer's answer to a calibration command: "success", another result string, or None if none came."""
    for x in msgs:
        p = x.get("print") or {}
        if p.get("command") == "calibration" and "result" in p: return str(p["result"]).lower()
    return None


def cmd_calibrate(pr, a):
    names = [n for n in CALIBRATIONS if getattr(a, n)]
    if not names: die("say which calibration to run: --vibration, --bed-level, --lidar")
    need_yes(a, "start a calibration")
    m = Mqtt(pr); status = summarize(m.pushall(), pr); m.close()
    if status.get("gcode_state") is None: die("no status from the printer; not starting")
    if status.get("gcode_state") in ACTIVE:
        die(f"the printer is busy ({status.get('gcode_state')}: {status.get('job')}); not starting a calibration")
    m = Mqtt(pr); m.publish(calibration_request(names)); msgs = m.pushall(wait=8); m.close()
    reply = calibration_reply(msgs)
    if reply not in ("success", None): die(f"the printer refused the calibration (result: {reply})")
    s = summarize(msgs, pr)
    print(json.dumps({"calibration": names, "accepted": reply == "success",
                      **{k: s.get(k) for k in ("gcode_state", "stage", "hms")}}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serial")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("status"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_status)
    s = sp.add_parser("watch", help="watch a print and report events (read-only)")
    # Each check opens a new TLS session. Every 5 min is plenty for multi-hour prints and the 20-min stall alert;
    # under 60 s would mostly add load on the printer.
    s.add_argument("--interval", type=int, default=300, help="seconds between checks (default 300, min 60)")
    s.add_argument("--exit-on-alert", action="store_true", help="exit (code 3) after the first warning or critical event")
    s.add_argument("--wait-start", type=int, default=0, metavar="MIN", help="wait up to MIN minutes for a print to start")
    s.add_argument("--progress-every", type=int, default=30, metavar="MIN", help="progress event interval (default 30)")
    # One layer of a full plate can take well over 10 min, during which neither the layer nor the time left
    # may change; 20 min avoids false alarms there. Calibration stages are excluded separately (Watch.check).
    s.add_argument("--stall-min", type=int, default=20, help="minutes without progress before a stall alert (default 20)")
    s.add_argument("--max-nozzle", type=int, default=config()["max_nozzle_c"], help="nozzle rating in °C (config max_nozzle_c)")
    s.add_argument("--max-bed", type=int, default=config()["max_bed_c"], help="bed rating in °C (config max_bed_c)")
    # 10 failed checks at the default interval is about 50 min without contact: enough to ride out a Wi-Fi
    # drop or a printer restart, short enough that a dead watch doesn't linger all night.
    s.add_argument("--max-failures", type=int, default=10, help="failed checks in a row before giving up (default 10)")
    s.add_argument("--no-snap", action="store_true", help="skip the camera snapshot on each event")
    s.add_argument("--dir", help="where events.jsonl and snapshots go (default <data_dir>/watch/<date>_<job>/)")
    s.set_defaults(fn=cmd_watch)
    s = sp.add_parser("code"); s.add_argument("codes", nargs="+"); s.set_defaults(fn=cmd_code)
    s = sp.add_parser("ls"); s.add_argument("dir", nargs="?", default="/"); s.set_defaults(fn=cmd_ls)
    s = sp.add_parser("get"); s.add_argument("remote"); s.add_argument("local"); s.set_defaults(fn=cmd_get)
    s = sp.add_parser("snap"); s.add_argument("out"); s.set_defaults(fn=cmd_snap)
    s = sp.add_parser("clip"); s.add_argument("out"); s.add_argument("--seconds", type=int, default=10); s.set_defaults(fn=cmd_clip)
    s = sp.add_parser("frames"); s.add_argument("dir"); s.add_argument("--every", type=float, required=True)
    s.add_argument("--count", type=int, required=True); s.add_argument("--assemble"); s.set_defaults(fn=cmd_frames)
    s = sp.add_parser("print"); s.add_argument("file"); s.add_argument("--yes", action="store_true")
    s.add_argument("--plate", type=int, default=1); s.add_argument("--name"); s.add_argument("--no-level", action="store_true")
    s.add_argument("--no-flow", action="store_true"); s.add_argument("--timelapse", action="store_true")
    s.add_argument("--vibration", action="store_true", help="run vibration compensation before printing")
    s.add_argument("--ams", help="comma-separated tray number per filament, in order: AMS unit x 4 + slot, counting from 0 "
                   "(the 4th slot of the first AMS is 3); omit for the external spool")
    s.add_argument("--force-mapping", action="store_true",
                   help="start even when a filament's type doesn't match the spool it maps to")
    s.set_defaults(fn=cmd_print)
    for c in ("pause", "resume", "stop"):
        s = sp.add_parser(c); s.add_argument("--yes", action="store_true"); s.set_defaults(fn=cmd_job)
    s = sp.add_parser("calibrate", help="run calibrations on an idle printer (needs --yes)")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--vibration", action="store_true", help="vibration compensation (input shaping)")
    s.add_argument("--bed-level", dest="bed_level", action="store_true", help="auto bed leveling")
    s.add_argument("--lidar", action="store_true", help="lidar calibration (X1 series)")
    s.set_defaults(fn=cmd_calibrate)
    sp.add_parser("setup").set_defaults(fn=cmd_setup)
    a = ap.parse_args()
    if a.cmd == "setup": return cmd_setup(a)
    pr = Printer(a.serial)
    try: a.fn(pr, a)
    except PrinterError as e: die(pr.mask(str(e)))


if __name__ == "__main__":
    main()
