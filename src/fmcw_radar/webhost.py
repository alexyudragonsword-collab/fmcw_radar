"""The local host of the GUI: one page, served to a desktop app window or a
browser tab (and, through ``Api.call``, to an Android WebView bridge later).

polar_tx / array_tx's layering: ``guispec`` describes, ``guiutil``
computes, this module **dispatches and queues**, the page draws.  ``Api``
is the whole interface -- ``get`` / ``post`` / ``call(route, req) -> (code,
payload)`` -- and the HTTP handler is only a transport for it.

* The statistical run answers in the request (0.1 s with the linearised
  chirp engine, a few seconds cycle-accurate); one at a time.
* The time engine's frame is a **job** (seconds to half a minute): queued,
  run in its own spawned process on the desktop -- cancel is a terminate --
  or on a thread where there is no multiprocessing (cancel then only drops
  the result).  The library reports no progress inside a frame, so a job
  carries the last measured duration as its estimate and the page shows
  elapsed over estimate.

Standard library only; bound to 127.0.0.1.
"""

from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__, guispec, guiutil
from .config import RadarConfig
from .sources import all_entries

WWW = Path(__file__).resolve().parent / "webui" / "www"
_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8", ".ico": "image/x-icon"}
DONE = ("done", "error", "cancelled")


#: what a job can be: the time engine's frame, a sweep of one control, the band trade-off
KINDS = ("frame", "sweep", "bands")


class _Cancelled(Exception):
    pass


def run_job(kind: str, req: dict, progress=None) -> dict:
    """One job's work, the same on either backend.  ``progress(done, total)``
    is called between the steps of a sweep and of the band table (the
    library reports none inside a frame)."""
    values = req.get("values") or {}
    if kind == "frame":
        return guiutil.run_frame(values)
    if kind == "sweep":
        return guiutil.run_sweep(values, str(req.get("path")), float(req.get("lo")), float(req.get("hi")), int(req.get("points")), progress)
    if kind == "bands":
        return guiutil.band_tradeoff(values, progress)
    raise ValueError(f"no such job kind: {kind}")


def _worker(conn, kind: str, req: dict) -> None:
    """The child process: one job, its progress and then the result (or the
    error) down the pipe."""
    try:
        conn.send(("done", run_job(kind, req, lambda done, total: conn.send(("progress", {"done": done, "total": total})))))
    except Exception as e:                                   # noqa: BLE001 -- whatever it is, the page has to hear of it
        conn.send(("error", f"{type(e).__name__}: {e}"))
    finally:
        conn.close()


class JobQueue:
    """Time-engine frames, one at a time, newest wanted most: submitting a
    frame cancels the ones still queued or running (the page shows one).

    ``backend="process"`` (the desktop): each job in its own spawned
    process; cancel sets a flag and the queue's thread -- the only one that
    touches the process -- terminates it within 0.1 s.  ``backend="thread"`` (where there is no
    multiprocessing): the frame runs to its end on a worker thread and a
    cancelled job's result is dropped."""

    def __init__(self, backend: str = "process"):
        if backend not in ("process", "thread"):
            raise ValueError(f"backend must be process or thread, got {backend!r}")
        self.backend = backend
        self.jobs: dict[str, dict[str, Any]] = {}
        self.last_wall_s: float | None = None                # the estimate the next job carries
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._ctx = mp.get_context("spawn") if backend == "process" else None
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def public(job: dict, with_result: bool = False) -> dict:
        d = {k: v for k, v in job.items() if not k.startswith("_") and k not in ("result", "cancel")}
        d["elapsed_s"] = None if job["started"] is None else round((job["finished"] or time.time()) - job["started"], 3)
        if with_result:
            d["result"] = job["result"]
        return d

    def submit(self, values: dict, kind: str = "frame", req: dict | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError(f"job kind must be one of {KINDS}, got {kind!r}")
        check = guiutil.validate(values)
        if not check["ok"]:
            raise ValueError(check["error"])
        jid = str(next(self._ids))
        job = {"id": jid, "kind": kind, "status": "queued", "created": time.time(), "started": None, "finished": None, "error": None,
               "eta_s": self.last_wall_s if kind == "frame" else None, "progress": None,
               "config_sha256": guiutil.config_hash(check["config"]), "result": None,
               "cancel": False, "_req": {**(req or {}), "values": dict(values)}}
        with self._cv:
            stale = [j["id"] for j in self.jobs.values() if j["status"] not in DONE and j["kind"] == kind]
        for old in stale:
            self.cancel(old)
        with self._cv:
            self.jobs[jid] = job
            self._cv.notify()
        return self.public(job)

    def cancel(self, jid: str) -> bool:
        with self._lock:
            job = self.jobs.get(jid)
            if job is None or job["status"] in DONE:
                return False
            job["cancel"] = True
            if job["status"] == "queued":
                job["status"] = "cancelled"
                job["finished"] = time.time()
        return True                                          # the worker loop sees the flag within 0.1 s and terminates

    def listing(self) -> list[dict]:
        with self._lock:
            return [self.public(j) for j in self.jobs.values()]

    def get(self, jid: str) -> dict | None:
        with self._lock:
            j = self.jobs.get(jid)
            return None if j is None else self.public(j, with_result=True)

    def _loop(self) -> None:
        while True:
            with self._cv:
                job = next((j for j in self.jobs.values() if j["status"] == "queued"), None)
                while job is None:
                    self._cv.wait()
                    job = next((j for j in self.jobs.values() if j["status"] == "queued"), None)
                job["status"] = "running"
                job["started"] = time.time()
            self._run(job)

    def _finish(self, job: dict, msg: str | None, payload: Any) -> None:
        with self._lock:
            if job["cancel"]:
                job["status"] = "cancelled"
            elif msg == "done" and isinstance(payload, dict) and payload.get("ok"):
                job["status"], job["result"] = "done", payload
                if job["kind"] == "frame":
                    self.last_wall_s = payload.get("wall_s") or self.last_wall_s
            else:
                job["status"] = "error"
                job["error"] = (payload.get("error") if isinstance(payload, dict) else payload) or "the worker ended without a result"
            job["finished"] = time.time()

    def _run(self, job: dict) -> None:
        if self.backend == "thread":
            def progress(done, total):                       # between steps: say where it is, and stop if it was cancelled
                job["progress"] = {"done": done, "total": total}
                if job["cancel"]:
                    raise _Cancelled

            try:
                msg, payload = "done", run_job(job["kind"], job["_req"], progress)
            except _Cancelled:
                msg, payload = None, None
            except Exception as e:                           # noqa: BLE001
                msg, payload = "error", f"{type(e).__name__}: {e}"
            self._finish(job, msg, payload)
            return
        parent, child = self._ctx.Pipe(duplex=False)
        p = self._ctx.Process(target=_worker, args=(child, job["kind"], job["_req"]), daemon=True)
        p.start()
        child.close()
        job["_pid"] = p.pid                                  # only this thread touches the process object (it is not thread-safe)
        msg, payload = None, None
        try:
            while True:
                if job["cancel"]:
                    p.terminate()
                    break
                if parent.poll(0.1):
                    try:
                        msg, payload = parent.recv()
                    except EOFError:
                        break
                    if msg == "progress":
                        job["progress"], msg, payload = payload, None, None
                        continue
                    break
                if not p.is_alive():
                    while parent.poll(0.0):                  # its last words may still be in the pipe
                        try:
                            msg, payload = parent.recv()
                        except EOFError:
                            break
                        if msg != "progress":
                            break
                        job["progress"], msg, payload = payload, None, None
                    break
        finally:
            p.join(5)
            if p.is_alive():                                 # it ignored the terminate
                p.kill()
                p.join(5)
            if msg is None and not job["cancel"]:
                payload = f"worker exited with code {p.exitcode}"
            self._finish(job, msg, payload)
            parent.close()


def _report_loop(conn) -> None:
    """The report worker's process: full statistical runs one after another,
    for as long as the host lives -- so the chirp engine's cache stays warm
    between them (a run that keeps the loop's settings is 0.9 s, not 3.3)."""
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        seq, values, baseline = msg
        try:
            out = guiutil.run_report(values, baseline)
        except Exception as e:                               # noqa: BLE001 -- the page has to hear of it
            out = {"ok": False, "error": f"{type(e).__name__}: {e}", "field": None}
        conn.send((seq, out))


class ReportWorker:
    """The full (cycle-accurate) statistical run, out of the host's process.

    The page gets a preview on the linearised chirp engine at once, in the
    host's process, and asks for the full run after it; that one takes
    seconds, and in a thread of this process it would starve the next
    preview (measured: 0.35 s previews became 0.9-2.8 s).  ``run`` blocks
    its caller until its answer is there.  Requests are served newest
    first, one at a time: a request still waiting when a newer one arrives
    is answered ``{"superseded": True}`` -- the page has moved on."""

    def __init__(self):
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._seq = 0
        self._pending: tuple | None = None
        self._running: int | None = None
        self._done: dict[int, dict] = {}
        self._proc = None
        self._conn = None
        self._closed = False
        self._plock = threading.Lock()                       # the process is started by whoever needs it first
        threading.Thread(target=self._serve, daemon=True).start()

    def _ensure(self) -> None:
        with self._plock:
            if self._closed or (self._proc is not None and self._proc.is_alive()):
                return
            parent, child = self._ctx.Pipe()
            self._proc = self._ctx.Process(target=_report_loop, args=(child,), daemon=True)
            self._proc.start()
            child.close()
            self._conn = parent

    def _serve(self) -> None:
        while True:
            with self._cv:
                while self._pending is None and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                seq, values, baseline = self._pending
                self._pending, self._running = None, seq
            try:
                self._ensure()
                self._conn.send((seq, values, baseline))
                while not self._conn.poll(0.2):
                    if not self._proc.is_alive() or self._closed:
                        raise EOFError("the report worker ended")
                _, out = self._conn.recv()
            except (EOFError, OSError) as e:
                out = {"ok": False, "error": f"the report worker failed: {e}", "field": None}
                self._proc = None
            with self._cv:
                self._done[seq] = out
                self._running = None
                self._cv.notify_all()

    def warm(self) -> None:
        """Start the process ahead of the first request (its imports take a second)."""
        self._ensure()

    def run(self, values: dict, baseline: dict | None = None) -> dict:
        with self._cv:
            self._seq += 1
            seq = self._seq
            self._pending = (seq, dict(values), baseline)
            self._cv.notify_all()
            while True:
                if seq in self._done:
                    return self._done.pop(seq)
                if self._closed or (self._running != seq and (self._pending is None or self._pending[0] != seq)):
                    return {"ok": True, "superseded": True}
                self._cv.wait(0.5)

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        with self._plock:
            if self._proc is not None and self._proc.is_alive():
                self._proc.terminate()


class Api:
    """Every route the page uses.  ``call`` is what a transport needs."""

    GET_ROUTES = ("version", "spec", "config", "sources", "jobs", "configs")

    def __init__(self, backend: str = "process"):
        self.queue = JobQueue(backend)
        self._run_lock = threading.Lock()
        # the desktop: full cycle-accurate runs in a process of their own, so a preview is never behind one
        self.reports = ReportWorker() if backend == "process" else None

    def get(self, route: str) -> tuple[int, dict]:
        if route == "version":
            return 200, {"name": "fmcw_radar", "version": __version__, "python": sys.version.split()[0], "backend": self.queue.backend}
        if route == "spec":
            return 200, guispec.spec()
        if route == "config":
            flat = guispec.values_from_config(RadarConfig())
            return 200, {"values": guiutil.plain(flat), "tags": guispec.tags(flat), "inert": guispec.inert(flat),
                         "refused": guispec.refused_choices(flat)}
        if route == "sources":
            return 200, {"entries": {k: {"value": e.value, "unit": e.unit, "source": e.source, "cite": e.cite,
                                         "section": getattr(e, "section", None)} for k, e in all_entries().items()}}
        if route == "configs":
            return 200, {"bundled": guiutil.bundled_configs()}
        if route == "jobs":
            return 200, {"jobs": self.queue.listing(), "last_wall_s": self.queue.last_wall_s}
        if route.startswith("jobs/"):
            job = self.queue.get(route.split("/", 1)[1])
            return (404, {"error": "no such job"}) if job is None else (200, job)
        return 404, {"error": f"no such route: {route}"}

    def post(self, route: str, req: dict) -> tuple[int, dict]:
        values = req.get("values")
        values = {} if values is None else values
        if not isinstance(values, dict):
            return 400, {"error": "values must be a mapping of dotted paths"}
        if route == "run":
            base = req.get("baseline")
            if base is not None and not (isinstance(base, dict) and isinstance(base.get("values"), dict) and isinstance(base.get("metrics"), dict)):
                return 400, {"error": "baseline must be {values, metrics} of an earlier run"}
            if req.get("final") and self.reports is not None:
                return 200, self.reports.run(values, base)
            with self._run_lock:                             # one statistical run at a time in this process
                return 200, guiutil.run_report(values, base, preview=bool(req.get("preview")))
        if route == "yaml/export":
            return 200, guiutil.export_yaml(values)
        if route == "yaml/load":
            if req.get("name") is not None:
                return 200, guiutil.load_bundled(str(req["name"]))
            return 200, guiutil.load_yaml(req.get("yaml"))
        if route == "validate":
            v = guiutil.validate(values)
            out = {k: v[k] for k in v if k != "config"}
            out.update({"tags": guispec.tags(values) if v["ok"] else {}, "inert": guispec.inert(values),
                        "refused": guispec.refused_choices(values)})
            return 200, out
        if route == "band":
            kind = req.get("kind")
            if kind not in guispec.BANDS:
                return 400, {"error": f"band must be one of {sorted(guispec.BANDS)}"}
            return 200, {"values": guiutil.plain(guispec.band_switch(values, kind))}
        if route in KINDS:
            extra = {}
            if route == "sweep":
                try:
                    extra = {"path": str(req["path"]), "lo": float(req["lo"]), "hi": float(req["hi"]), "points": int(req["points"])}
                except (KeyError, TypeError, ValueError):
                    return 400, {"error": "a sweep needs path, lo, hi (config units) and points"}
            try:
                return 200, self.queue.submit(values, route, extra)
            except ValueError as e:
                return 200, {"status": "error", "error": str(e)}
        if route.startswith("jobs/") and route.endswith("/cancel"):
            return 200, {"cancelled": self.queue.cancel(route.split("/")[1])}
        return 404, {"error": f"no such route: {route}"}

    def call(self, route: str, req: dict | None = None) -> tuple[int, dict]:
        route = route.strip("/")
        is_get = route in self.GET_ROUTES or (route.startswith("jobs/") and not route.endswith("/cancel"))
        return self.get(route) if is_get else self.post(route, req or {})


def dumps(obj: Any) -> str:
    return json.dumps(guiutil.plain(obj), ensure_ascii=False, separators=(",", ":"))


class _Handler(BaseHTTPRequestHandler):
    api: Api

    def log_message(self, fmt, *args):                       # quiet: this is a desktop app
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        try:
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                                             # the page went away while its answer was being computed

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, dumps(payload).encode("utf-8"), _TYPES[".json"])

    def do_GET(self):                                        # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            self._json(*self.api.get(path[5:].strip("/")))
            return
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (WWW / rel).resolve()
        if WWW not in f.parents or not f.is_file():          # nothing outside the page's own directory
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, f.read_bytes(), _TYPES.get(f.suffix, "application/octet-stream"))

    def do_POST(self):                                       # noqa: N802
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            if not isinstance(req, dict):
                raise ValueError("the body must be a JSON object")
        except (ValueError, UnicodeDecodeError) as e:
            self._json(400, {"error": f"bad request: {e}"})
            return
        self._json(*self.api.post(path[5:].strip("/"), req))


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Windows: SO_REUSEADDR lets a second socket bind a port that is being listened on (polar_tx's pitfall)
    allow_reuse_address = os.name != "nt"

    def server_close(self):
        api = getattr(self, "api", None)
        if api is not None and api.reports is not None:
            api.reports.close()
        super().server_close()


def make_server(port: int = 0, host: str = "127.0.0.1", backend: str = "process") -> _Server:
    """A server on ``host:port`` (0: any free port), not yet serving."""
    api = Api(backend)
    handler = type("Handler", (_Handler,), {"api": api})
    srv = _Server((host, port), handler)
    srv.api = api                                            # type: ignore[attr-defined]
    return srv


def find_app_browser() -> str | None:
    """A Chromium-family browser that can open an ``--app`` window
    (``FMCW_BROWSER`` overrides), or None."""
    env = os.environ.get("FMCW_BROWSER")
    if env:
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge", "msedge", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if Path(p).exists():
            return p
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fmcw-gui", description="fmcw_radar's workbench, served locally to an app window or a browser tab.")
    ap.add_argument("--port", type=int, default=8766, help="port on 127.0.0.1 (0: any free one)")
    ap.add_argument("--tab", action="store_true", help="open a browser tab instead of an app window")
    ap.add_argument("--no-open", action="store_true", help="serve only; print the address")
    args = ap.parse_args(argv)
    try:
        srv = make_server(args.port)
    except OSError as e:
        print(f"fmcw-gui: cannot listen on 127.0.0.1:{args.port} ({e}); try --port 0", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"fmcw-gui {__version__}: {url}  (Ctrl+C stops it)")
    srv.api.reports.warm()                                   # the report worker's imports, ahead of the first run
    if not args.no_open:
        browser = None if args.tab else find_app_browser()
        if browser:
            subprocess.Popen([browser, f"--app={url}", "--new-window"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


__all__ = ["WWW", "KINDS", "JobQueue", "ReportWorker", "Api", "run_job", "make_server", "find_app_browser", "main", "dumps"]

if __name__ == "__main__":
    raise SystemExit(main())
