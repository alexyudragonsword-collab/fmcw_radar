"""The single entry point the Android app calls: ``call(route, args_json)
-> json``.

Same page, third host.  The WebView injects ``window.host`` and the page's
``api()`` sends every request here instead of to the local server; the
routes and payloads are exactly those of ``webhost.Api`` (one dispatch, two
transports), so ``tests/test_appbridge.py`` exercises the phone's whole
surface on a laptop in seconds and the page needs one code path.

What differs on the phone, and why:

* long work runs on threads (``Api(backend="thread")``): Chaquopy has no
  multiprocessing.  A sweep and the band table stop between two steps when
  cancelled; a time-engine frame runs to its end and its result is dropped;
* there is no report worker process either, so the cycle-accurate run of a
  preview is computed here, on the activity's one Python thread, and nothing
  else is answered while it runs -- the page therefore asks for it only when
  the user does (``app.js``: ``ON_DEVICE``);
* a config file is text the user pastes or copies: a WebView has neither a
  file chooser nor downloads without more Kotlin than this app wants.

Kotlin stays inert: a feature is a Python function behind ``Api`` plus a
render in the page, never a change to the activity.
"""
from __future__ import annotations

import json
import traceback

from .webhost import Api, dumps

_API: Api | None = None


def _api() -> Api:
    global _API
    if _API is None:
        _API = Api(backend="thread")
    return _API


def call(route: str, args_json: str = "{}") -> str:
    """``route`` as the page names it (``spec``, ``run``, ``jobs/3/cancel``);
    ``args_json`` the request body.  Never raises: a bad route, bad JSON or
    a bug in the library come back as ``{"ok": false, "error": ...}``."""
    try:
        req = json.loads(args_json or "{}")
        if req is None:
            req = {}
        if not isinstance(req, dict):
            raise ValueError("args must be a JSON object")
        _, obj = _api().call(str(route), req)
    except Exception as exc:                            # noqa: BLE001 (in-band error)
        obj = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    return dumps(obj)


def reset() -> None:
    """Forget the state (tests)."""
    global _API
    _API = None


__all__ = ["call", "reset"]
