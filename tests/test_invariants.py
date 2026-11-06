"""Static guards: no receive-side LO anywhere (invariant #2), engines take the config (invariant #1),
spur claims only from the cycle-accurate engine (invariant #6), no assumed nonlinearity term (invariant #4)."""

import inspect
import re

from conftest import REPO

SRC = REPO / "src" / "fmcw_radar"


def code_only(source: str) -> str:
    import io
    import tokenize

    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            out.append(tok.string)
    return " ".join(out)


def _sources():
    for p in sorted(SRC.rglob("*.py")):
        if "vendor" in p.parts:
            continue
        yield p, code_only(p.read_text(encoding="utf-8"))


def test_law2_no_independent_receive_lo_anywhere():
    """The config has no receive-side oscillator field; only lo.py builds an
    ADPLL and only phase_noise / timedomain synthesise LO noise, and the
    time engine delays the one sequence instead of drawing a second."""
    from fmcw_radar.config.form import schema_paths

    assert not [p for p in schema_paths() if re.search(r"rx\..*(lo|pll|osc|profile)", p)]
    builders = [p.relative_to(REPO) for p, s in _sources() if "ADPLLConfig(" in s and p.name != "lo.py"]
    assert not builders, builders
    synth = [p.relative_to(REPO) for p, s in _sources()
             if "synth_from_psd" in s and p.name not in ("range_correlation.py",)]
    assert not synth, synth
    td = code_only((SRC / "engine" / "timedomain.py").read_text(encoding="utf-8"))
    assert td.count("synthesize_lo") == 1 and re.search(r"rc\s*\.\s*residual\s*\(", td)


def test_law1_engines_take_the_config_first():
    from fmcw_radar.engine import run_radar, run_statistical, run_time
    from fmcw_radar.link import link_budget

    for fn in (run_radar, run_statistical, run_time, link_budget):
        assert next(iter(inspect.signature(fn).parameters)) == "cfg", fn.__name__


def test_law1_examples_read_the_config_file():
    for p in sorted((REPO / "examples").glob("[0-9][0-9]_*.py")):
        s = p.read_text(encoding="utf-8")
        assert "load_config(" in s, f"{p.name} must start from a config file"
        assert not re.search(r"center_hz\s*=\s*[0-9]|sweep_hz\s*=\s*[0-9]", s), f"{p.name} sets a band literal"


def test_law1_engines_hardcode_no_band_or_chirp_number():
    pat = re.compile(r"\b(?:57|58|60|62|64|77)(?:\.\d+)?e9\b|\b4(?:\.0)?e9\b|\b100(?:\.0)?e-6\b")
    hits = [(p.relative_to(REPO), m.group(0)) for p, s in _sources()
            if p.parts[-2] in ("engine", "chirp", "phase_noise", "link", "processing") for m in pat.finditer(s)]
    assert not hits, hits


def test_law4_no_assumed_nonlinearity_term_in_the_engines():
    """The only quadratic frequency error is the labelled reference group,
    and nothing in the engines calls it."""
    users = [p.relative_to(REPO) for p, s in _sources() if "quadratic_reference(" in s and p.name != "engine.py"]
    assert not users, users
    for p, s in _sources():
        if p.parts[-2] == "engine":
            assert "quadratic" not in s, p


def test_law6_only_the_cycle_accurate_engine_vouches_for_spurs():
    from fmcw_radar.chirp import ChirpEngine, quadratic_reference
    from fmcw_radar.config import RadarConfig, apply_overrides

    cfg = apply_overrides(RadarConfig(), {"chirp.n_chirps": 2})
    for eng, vouch in (("event", True), ("response", False), ("ideal", False)):
        r = ChirpEngine(apply_overrides(cfg, {"lo.engine": eng})).run()
        assert r.vouches_for_spurs is vouch, eng
        if not vouch:
            assert "linearised" in r.note or "reference" in r.note
    assert not quadratic_reference(cfg, 1e5, 1).vouches_for_spurs
