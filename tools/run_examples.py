"""Run the example scripts end to end, small enough for CI.

Adapted from d2d_link tools/run_examples.py (itself from Halo_Serdes; package
path re-homed, the cap is on ``ChirpConfig.n_chirps`` instead of symbols).

``tests/test_examples.py`` only checks that each example compiles and
that what it imports exists. That misses everything that happens at run
time: a renamed config field, a changed result key, a shape that no longer
lines up, a plot call on an array that became None. This runs them.

``--smoke`` (what CI runs) caps every ``ChirpConfig.n_chirps`` an example
asks for at ``--cap`` chirps, in the child process only: the library stays
as it is, the examples stay as the documentation shows them, and the numbers
they print are meaningless -- the run is checking that the code paths work,
not what they compute. Without ``--smoke`` the examples run at their own
sizes (slow; the numbers the docs quote).

Each example runs in its own interpreter with a non-interactive matplotlib
backend and writes its figures where it always does (``examples/output``,
ignored by git). An example that needs an optional extra that is not
installed (``matplotlib``) is reported as skipped, not failed.

    python tools/run_examples.py --smoke                  # all of them
    python tools/run_examples.py --smoke 05 07            # by number prefix
    python tools/run_examples.py --jobs 3 --save out/     # full size, outputs kept

``--save DIR`` keeps each example's stdout as ``DIR/<name>.txt``: the numbers
the docs quote come from these, so a full-size run is only useful if what it
printed can be compared with the docs (and with the previous full-size run,
by ``diff``) afterwards. ``--jobs N`` runs N examples at once.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"

#: missing modules that make an example a skip rather than a failure: the
#: optional backends (not in any extra CI installs, or the [pll] / [fec] ones)
OPTIONAL = ("matplotlib",)

# The child: cap n_chirps at every ChirpConfig construction (dataclasses.replace
# and load_config build it through __init__ as well), then run the example as
# __main__ from its own directory, as a user would.
_CHILD = r"""
import runpy, sys
cap = int(sys.argv[2])
if cap > 0:
    from fmcw_radar.config import schema
    _init = schema.ChirpConfig.__init__
    def _capped(self, *args, **kw):
        if len(args) >= 4:
            args = args[:3] + (min(int(args[3]), cap),) + args[4:]
        elif "n_chirps" in kw:
            kw["n_chirps"] = min(int(kw["n_chirps"]), cap)
        else:
            kw["n_chirps"] = min(schema.ChirpConfig.__dataclass_fields__["n_chirps"].default, cap)
        _init(self, *args, **kw)
    schema.ChirpConfig.__init__ = _capped
sys.argv = [sys.argv[1]]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


_NO_MODULE = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")


def _missing_optional(stderr: str) -> str | None:
    """The optional package whose absence ended the run, else None. Only a
    ``No module named`` for the package itself (or one of its submodules)
    counts: an ImportError from inside an installed matplotlib is a failure,
    not a skip (third health check)."""
    for line in stderr.splitlines()[::-1]:
        m = _NO_MODULE.search(line)
        if m and m.group(1).split(".")[0] in OPTIONAL:
            return m.group(1).split(".")[0]
    return None


def _one(p: Path, cap: int, timeout: float, env: dict, save: Path | None):
    """Run one example in its own interpreter: (exit code, stderr, seconds)."""
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-c", _CHILD, str(p), str(cap)],
                           cwd=EXAMPLES, env=env, capture_output=True, text=True,
                           timeout=timeout)
        code, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as exc:
        code, out, err = -1, exc.stdout or "", f"timed out after {timeout:.0f} s\n{exc.stderr or ''}"
    if save is not None:
        (save / f"{p.stem}.txt").write_text(out if isinstance(out, str) else out.decode())
    return code, err, time.time() - t0


def run(paths: list[Path], cap: int, timeout: float, jobs: int = 1,
        save: Path | None = None) -> int:
    env = dict(os.environ, MPLBACKEND="Agg",
               PYTHONPATH=os.pathsep.join(filter(None, [str(REPO / "src"),
                                                        os.environ.get("PYTHONPATH")])))
    # the examples whose cost is not in n_chirps (the range sweeps) read this
    # and run a subset under --smoke; their full-size output is unchanged
    env["FMCW_RADAR_SMOKE"] = "1" if cap > 0 else "0"
    if save is not None:
        save.mkdir(parents=True, exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
        # results come back in the examples' order whatever finishes first
        results = pool.map(lambda p: _one(p, cap, timeout, env, save), paths)
        for p, (code, err, dt) in zip(paths, results):
            _report(p, code, err, dt, failed)
    print(f"\n{len(paths) - len(failed)} of {len(paths)} examples ran"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def _report(p: Path, code: int, err: str, dt: float, failed: list) -> None:
    """One line per example; the tail of stderr for a failure."""
    if code == 0:
        print(f"ok    {p.name:<32} {dt:6.1f} s", flush=True)
        return
    opt = _missing_optional(err)
    if opt is not None:
        print(f"skip  {p.name:<32} {dt:6.1f} s  (optional backend '{opt}' not installed)",
              flush=True)
        return
    failed.append(p.name)
    print(f"FAIL  {p.name:<32} {dt:6.1f} s", flush=True)
    print("\n".join("      " + ln for ln in err.strip().splitlines()[-25:]), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("only", nargs="*", help="number prefixes to run (default: all)")
    ap.add_argument("--smoke", action="store_true", help="cap n_chirps (see --cap)")
    ap.add_argument("--cap", type=int, default=8, help="n_chirps cap with --smoke")
    ap.add_argument("--timeout", type=float, default=1200.0, help="seconds per example")
    ap.add_argument("--jobs", type=int, default=1, help="examples run at once")
    ap.add_argument("--save", type=Path, default=None,
                    help="directory to keep each example's stdout in (<name>.txt)")
    a = ap.parse_args(argv)
    paths = sorted(EXAMPLES.glob("[0-9][0-9]_*.py"))
    if a.only:
        paths = [p for p in paths if any(p.name.startswith(o) for o in a.only)]
    return run(paths, a.cap if a.smoke else 0, a.timeout, a.jobs, a.save)


if __name__ == "__main__":
    sys.exit(main())
