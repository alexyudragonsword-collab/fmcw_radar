"""The Android app's one entry point (appbridge): the page's whole surface,
exercised on a laptop.  A bridge route with no caller is half a feature, and
a call the page makes with no route behind it is a dead button: both
directions are checked from text."""

import json
import re
import time

import pytest

from fmcw_radar import appbridge, guiutil, webhost

FAST = {"chirp.n_chirps": 8, "lo.engine": "response"}
#: routes the Api answers that the page does not call, and why they are there all the same
API_ONLY = {"validate": "a host or a script checking settings without running them",
            "jobs": "the list of jobs, for a host's own bookkeeping"}


@pytest.fixture(autouse=True)
def fresh():
    appbridge.reset()
    yield
    appbridge.reset()


def _call(route, body=None):
    return json.loads(appbridge.call(route, "{}" if body is None else json.dumps(body)))


def test_the_bridge_is_the_api_on_threads():
    assert _call("version")["backend"] == "thread" and _call("spec") == json.loads(webhost.dumps(webhost.Api(backend="thread").call("spec")[1]))
    run = _call("run", {"values": FAST})
    assert run["ok"] and run["report"] == json.loads(webhost.dumps(guiutil.run_report(FAST)["report"]))
    # a preview, and the cycle-accurate run of it: no worker process on the phone, the same answer
    slow = {"chirp.n_chirps": 8}
    assert _call("run", {"values": slow, "preview": True})["preview"]["shown"] == "response"
    full = _call("run", {"values": slow, "final": True})
    assert "preview" not in full and full["report"]["radar"]["lo_engine"] == "event" and appbridge._api().reports is None
    # the time engine's frame is a job on a thread
    job = _call("frame", {"values": FAST})
    t0 = time.time()
    while _call(f"jobs/{job['id']}")["status"] not in webhost.DONE and time.time() - t0 < 90:
        time.sleep(0.05)
    assert _call(f"jobs/{job['id']}")["result"]["rd_map"]["rows"] == 8
    # a config file is text in, text out
    text = _call("yaml/export", {"values": {"target.range_m": 7.0}})["yaml"]
    assert _call("yaml/load", {"yaml": text})["values"]["target.range_m"] == 7.0


def test_the_bridge_never_raises():
    assert _call("nothing")["error"] == "no such route: nothing"
    for route, args in (("run", "{not json"), ("run", "[1]"), ("run", '"x"'), ("sweep", "{}"), ("run", '{"values": 3}')):
        out = json.loads(appbridge.call(route, args))
        assert "error" in out, (route, args)
    assert json.loads(appbridge.call("version", ""))["name"] == "fmcw_radar" and json.loads(appbridge.call("version", "null"))["name"] == "fmcw_radar"
    assert _call("run", {"values": {"mimo.n_rx": 2}})["field"] == "mimo.angle_window"            # a refusal is an answer


def test_every_call_the_page_makes_has_a_route_and_every_route_a_caller():
    js = "".join((webhost.WWW / f).read_text(encoding="utf-8") for f in ("app.js", "pages.js"))
    literal = set(re.findall(r"api\('([a-z/]+)'", js))
    assert literal >= {"version", "spec", "config", "sources", "configs", "run", "band", "frame", "yaml/export", "yaml/load", "jobs/"}
    # the two job kinds started through one helper, by name
    started = set(re.findall(r"startJob\('([a-z]+)'", js))
    assert started == {"sweep", "bands"} and "await api(kind, body)" in js
    called = (literal - {"jobs/"}) | started                  # 'jobs/' is one job by its id, not the list
    for route in called:
        body = {"values": FAST, "path": "target.range_m", "lo": 2.5, "hi": 5.0, "points": 2, "kind": "60g_sensing", "yaml": "{}"}
        assert "no such route" not in appbridge.call(route, json.dumps(body)), route
    assert "/cancel'" in js and _call("jobs/999/cancel") == {"cancelled": False}
    # the other way: what the Api answers and the page never asks for is listed, with its reason
    api = webhost.Api(backend="thread")
    routes = set(api.GET_ROUTES) | set(webhost.KINDS) | {"run", "validate", "band", "yaml/export", "yaml/load"}
    assert routes - called == set(API_ONLY)
    for route in routes:
        assert api.call(route, {"values": FAST, "path": "target.range_m", "lo": 2.5, "hi": 5.0, "points": 2, "kind": "60g_sensing", "yaml": "{}"})[0] == 200, route
