"""The GUI's local host (webhost): ``Api`` is the interface, HTTP only a
transport; the time engine's frame is a job that can be cancelled."""

import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest

from fmcw_radar import guispec, guiutil, webhost

FAST = {"chirp.n_chirps": 8, "lo.engine": "response"}


def _wait(queue, jid, timeout=90.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = queue.get(jid)
        if job["status"] in webhost.DONE:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {jid} still {queue.get(jid)['status']} after {timeout} s")


def test_api_serves_the_spec_and_runs_the_report():
    api = webhost.Api(backend="thread")
    code, v = api.call("version")
    assert code == 200 and v["name"] == "fmcw_radar" and v["backend"] == "thread"
    assert api.call("spec") == (200, guispec.spec())
    code, cfg = api.call("config")
    assert code == 200 and cfg["values"]["target.range_m"] == 5.0 and cfg["tags"]["frontend.tx_power_dbm"] == "spec"
    assert "leakage.isolation_db" in cfg["inert"] and cfg["refused"] == {}
    code, src = api.call("sources")
    assert len(src["entries"]) == 85 and src["entries"]["60g_sensing.tx_power_dbm"]["source"] == "spec"
    # a run is guiutil's, value for value (the wall time aside)
    code, run = api.call("run", {"values": FAST})
    direct = guiutil.run_report(FAST)
    assert code == 200 and run["ok"] and run["report"] == direct["report"] and run["repro"]["config_sha256"] == direct["repro"]["config_sha256"]
    json.loads(webhost.dumps(run))
    # what the config refuses is an answer, not an error status
    code, bad = api.call("run", {"values": {"mimo.n_rx": 2}})
    assert code == 200 and bad["ok"] is False and bad["field"] == "mimo.angle_window" and "2 virtual elements" in bad["error"]
    code, val = api.call("validate", {"values": {"lo.engine": "response"}})
    assert val["ok"] and val["refused"] == {"lo.dp_cal": ["online"]} and "lo.settle_cycles" in val["inert"]
    assert api.call("validate", {"values": {"frontend.tx_backoff_db": -1}})[1]["field"] == "frontend.tx_backoff_db"
    code, band = api.call("band", {"values": {}, "kind": "77g_automotive"})
    assert band["values"]["band.center_hz"] == 78.5e9 and api.call("band", {"values": {}, "kind": "x"})[0] == 400
    assert api.call("nothing")[0] == 404 and api.call("jobs/999")[0] == 404 and api.call("run", {"values": []})[0] == 400


def test_a_frame_is_a_job_and_the_next_one_knows_how_long_it_took():
    api = webhost.Api(backend="thread")
    code, job = api.call("frame", {"values": FAST})
    assert code == 200 and job["status"] in ("queued", "running") and job["eta_s"] is None       # nothing measured yet
    done = _wait(api.queue, job["id"])
    assert done["status"] == "done" and done["result"]["ok"] and done["result"]["rd_map"]["rows"] == 8
    assert done["result"]["config_sha256"] == done["config_sha256"] == guiutil.run_report(FAST)["repro"]["config_sha256"]
    assert done["elapsed_s"] > 0 and api.queue.last_wall_s == done["result"]["wall_s"]
    code, nxt = api.call("frame", {"values": FAST})
    assert nxt["eta_s"] == done["result"]["wall_s"]                                       # the page's progress bar: elapsed over this
    _wait(api.queue, nxt["id"])
    listing = api.call("jobs")[1]
    assert [j["status"] for j in listing["jobs"]] == ["done", "done"] and "result" not in listing["jobs"][0]
    # a config the schema refuses never becomes a job
    code, bad = api.call("frame", {"values": {"mimo.n_rx": 2}})
    assert bad["status"] == "error" and "2 virtual elements" in bad["error"] and len(api.call("jobs")[1]["jobs"]) == 2


def test_cancel_terminates_the_process_and_a_new_frame_replaces_the_running_one():
    """The desktop backend: each frame in its own spawned process.  Cancel
    is a terminate -- the full 64-chirp frame takes seconds, the cancel
    well under one -- and submitting another frame cancels the one in flight.

    The test watches the job and the process id, never the process object:
    that belongs to the queue's thread (two threads waiting on one
    multiprocessing.Process disagree about whether it is alive)."""
    api = webhost.Api(backend="process")
    slow = {"lo.engine": "response"}                         # the default 64 chirps
    code, job = api.call("frame", {"values": slow})
    t0 = time.time()
    while api.queue.jobs[job["id"]].get("_pid") is None and time.time() - t0 < 30:
        time.sleep(0.02)
    pid = api.queue.jobs[job["id"]]["_pid"]
    assert api.queue.get(job["id"])["status"] == "running" and "_pid" not in api.queue.get(job["id"])
    t_cancel = time.time()
    assert api.call(f"jobs/{job['id']}/cancel", {})[1] == {"cancelled": True}
    gone = _wait(api.queue, job["id"], timeout=15)
    # ended by the cancel, not by the frame finishing (>= 6 s) or by the queue giving up on it (5 s)
    assert gone["status"] == "cancelled" and gone["result"] is None and time.time() - t_cancel < 3
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):                                            # no such process any more
            os.kill(pid, 0)
    assert api.call(f"jobs/{job['id']}/cancel", {})[1] == {"cancelled": False}            # nothing left to cancel
    code, a = api.call("frame", {"values": slow})
    code, b = api.call("frame", {"values": FAST})
    assert _wait(api.queue, a["id"], timeout=15)["status"] == "cancelled"
    done = _wait(api.queue, b["id"])
    assert done["status"] == "done" and done["result"]["time_engine"]["n_chirps"] == 8


def test_a_sweep_and_the_band_table_are_jobs_with_progress():
    """Seconds of work under the cycle-accurate engine, so jobs like the
    frame -- and, unlike the frame, they say how far they are."""
    api = webhost.Api(backend="thread")
    code, job = api.call("sweep", {"values": FAST, "path": "target.range_m", "lo": 2.5, "hi": 10.0, "points": 4})
    assert code == 200 and job["kind"] == "sweep" and job["eta_s"] is None
    done = _wait(api.queue, job["id"])
    direct = guiutil.run_sweep(FAST, "target.range_m", 2.5, 10.0, 4)
    assert done["status"] == "done" and done["progress"] == {"done": 4, "total": 4}
    assert [p["metrics"] for p in done["result"]["points"]] == [p["metrics"] for p in direct["points"]]
    code, bands = api.call("bands", {"values": FAST})
    got = _wait(api.queue, bands["id"])
    assert got["kind"] == "bands" and got["status"] == "done" and len(got["result"]["rows"]) == 5 and got["progress"] == {"done": 5, "total": 5}
    # jobs of different kinds do not cancel each other; a second sweep replaces the first
    code, a = api.call("sweep", {"values": {"lo.engine": "response"}, "path": "target.range_m", "lo": 2.5, "hi": 10.0, "points": 41})
    code, f = api.call("frame", {"values": FAST})
    code, b = api.call("sweep", {"values": FAST, "path": "chirp.n_chirps", "lo": 8, "hi": 9, "points": 2})
    assert _wait(api.queue, a["id"])["status"] == "cancelled" and _wait(api.queue, f["id"])["status"] == "done"
    assert [p["x"] for p in _wait(api.queue, b["id"])["result"]["points"]] == [8, 9]
    # on a thread a cancel lands between two points
    code, long = api.call("sweep", {"values": {"lo.engine": "response"}, "path": "target.range_m", "lo": 2.5, "hi": 10.0, "points": 41})
    t0 = time.time()
    while not (api.queue.get(long["id"])["progress"] or {}).get("done") and time.time() - t0 < 30:
        time.sleep(0.02)
    api.call(f"jobs/{long['id']}/cancel", {})
    gone = _wait(api.queue, long["id"], timeout=15)
    assert gone["status"] == "cancelled" and gone["result"] is None and gone["progress"]["done"] < 41
    # what cannot be a sweep: a job that says so, or a request that is not one
    code, bad = api.call("sweep", {"values": FAST, "path": "target.kind", "lo": 1, "hi": 2, "points": 3})
    assert _wait(api.queue, bad["id"])["status"] == "error" and "not a control a sweep can step" in api.queue.get(bad["id"])["error"]
    assert api.call("sweep", {"values": FAST})[0] == 400 and api.call("sweep", {"values": FAST, "path": "x", "lo": "a", "hi": 2, "points": 3})[0] == 400
    assert api.call("bands", {"values": {"mimo.n_rx": 2}})[1]["status"] == "error"
    # a pinned baseline rides on the run
    code, run = api.call("run", {"values": FAST})
    code, cmp_ = api.call("run", {"values": {**FAST, "target.range_m": 10.0}, "baseline": {"values": FAST, "metrics": run["metrics"]}})
    assert cmp_["baseline"]["metrics"]["snr_cell_db"]["verdict"] == "worse" and "baseline" not in run
    assert api.call("run", {"values": FAST, "baseline": {"values": FAST}})[0] == 400


def test_a_sweep_in_its_own_process_reports_its_progress():
    api = webhost.Api(backend="process")
    code, job = api.call("sweep", {"values": FAST, "path": "target.range_m", "lo": 2.5, "hi": 10.0, "points": 6})
    seen = set()
    t0 = time.time()
    while api.queue.get(job["id"])["status"] not in webhost.DONE and time.time() - t0 < 90:
        seen.add((api.queue.get(job["id"])["progress"] or {}).get("done"))
        time.sleep(0.01)
    done = api.queue.get(job["id"])
    assert done["status"] == "done" and done["progress"] == {"done": 6, "total": 6} and len(done["result"]["points"]) == 6
    assert len(seen - {None}) >= 2                                                         # it was seen moving


@pytest.fixture()
def server():
    srv = webhost.make_server(0, backend="thread")
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _http(url, body=None):
    req = urllib.request.Request(url, data=None if body is None else body, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def test_http_is_only_a_transport(server):
    code, ctype, body = _http(server + "/")
    assert code == 200 and ctype.startswith("text/html") and b"<title>" in body
    # the page and every file it names are served
    import re

    for ref in re.findall(rb'(?:src|href)="([^"#:]+\.(?:js|css))"', body):
        code, ctype, _ = _http(f"{server}/{ref.decode()}")
        assert code == 200 and ("javascript" in ctype or "css" in ctype), ref
    code, ctype, v = _http(server + "/api/version")
    assert code == 200 and ctype.startswith("application/json") and json.loads(v)["name"] == "fmcw_radar"
    code, _, run = _http(server + "/api/run", json.dumps({"values": FAST}).encode())
    assert code == 200 and json.loads(run)["report"] == guiutil.run_report(FAST)["report"]
    # nothing outside the page's directory, no route that does not exist, no body that is not JSON
    assert _http(server + "/../guispec.py")[0] == 404 and _http(server + "/%2e%2e/guispec.py")[0] == 404
    assert _http(server + "/api/nothing")[0] == 404 and _http(server + "/api/run", b"{not json")[0] == 400
    assert _http(server + "/api/run", b"[1]")[0] == 400


def test_the_page_is_packaged_and_the_entry_point_exists():
    assert (webhost.WWW / "index.html").is_file() and (webhost.WWW / "app.js").is_file() and (webhost.WWW / "pages.js").is_file() and (webhost.WWW / "style.css").is_file()
    from conftest import REPO

    meta = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'fmcw-gui = "fmcw_radar.webhost:main"' in meta and '"webui/www/*"' in meta
    with pytest.raises(SystemExit):
        webhost.main(["--help"])


def test_the_page_names_nothing_outside_itself():
    """No library, font, image or stylesheet from anywhere else: the three
    files are the whole page (the same files go into the Android WebView)."""
    import re

    for f in sorted(webhost.WWW.iterdir()):
        text = f.read_text(encoding="utf-8")
        assert f.suffix in (".html", ".js", ".css"), f.name
        assert not re.search(r"(https?:)?//[A-Za-z0-9]", text) and "@import" not in text and not re.search(r"url\((?!#)", text), f.name   # url(#id) is the page's own SVG marker
    html = (webhost.WWW / "index.html").read_text(encoding="utf-8")
    assert set(re.findall(r'(?:src|href)="([^"]+)"', html)) == {"data:,", "style.css", "pages.js", "app.js"}
