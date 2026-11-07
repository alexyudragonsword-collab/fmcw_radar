"""Invariant #5: every external number carries its source; ``grep source:`` lists them all."""

import subprocess

import pytest

from fmcw_radar import sources
from fmcw_radar.config import RadarConfig
from fmcw_radar.link import link_budget


def test_every_entry_is_tagged_and_cited():
    table = sources.all_entries()
    assert len(table) >= 20
    for key, e in table.items():
        assert e.source in sources.SOURCES, key
        assert e.cite, key
        if e.source == "survey":
            assert "未核实" in e.note, f"{key}: a survey entry's note must say it is unverified"
        if e.source == "assumed":
            assert "占位" in e.note, f"{key}: a placeholder's note must say it is one"


def test_grep_lists_every_sourced_number():
    """The command the docs promise -- ``grep -c "source:"`` on the table --
    counts exactly the entries: no header comment may contain the tag."""
    out = subprocess.run(["grep", "-c", "source:", str(sources.SOURCES_FILE)], capture_output=True, text=True)
    assert int(out.stdout.strip()) == len(sources.all_entries())


def test_every_front_end_placeholder_exists_for_every_band():
    for band in ("60g_sensing", "77g_automotive"):
        for name in ("tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi", "rx_gain_db", "nf_db", "p1db_dbm", "lo_mult",
                     "dco_pn_dbchz", "dco_pn_floor_dbchz", "tdc_res_s", "tx_rx_isolation_db", "rx_coupling_c1_db"):
            e = sources.frontend_placeholder(band, name)
            assert e.placeholder, (band, name)


def test_spec_source_needs_a_quote_and_survey_needs_unverified():
    with pytest.raises(ValueError, match="quoted"):
        sources.SourcedNumber("x", 1, "u", "spec", "cite")
    with pytest.raises(ValueError, match="source"):
        sources.SourcedNumber("x", 1, "u", "rumour", "cite")
    with pytest.raises(ValueError, match="未核实"):
        sources.SourcedNumber("x", 1, "u", "survey", "cite", note="read somewhere")
    ok = sources.SourcedNumber("x", 1, "u", "spec", "cite", quote="the text", section="3.1")
    assert ok.tag() == "1 u (source: spec)"


def test_budget_inputs_carry_their_sources():
    b = link_budget(RadarConfig())
    srcs = {k: s for k, (_, s) in b.inputs.items()}
    assert srcs["tx_power_dbm"] == "assumed" and srcs["rcs_dbsm"] == "survey" and srcs["range_m"] == "config"


def test_code_does_not_hardcode_the_table():
    """No engine or config module spells a table value as a literal: the
    oxygen 15 dB/km, the -10 dBsm human, the 10 dBm placeholder power."""
    import re

    from conftest import REPO

    src = REPO / "src" / "fmcw_radar"
    hits = []
    for p in src.rglob("*.py"):
        if "vendor" in p.parts or p.name == "sources.py":
            continue
        code = _code_only(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"oxygen\w*\s*=\s*15\b|rcs\w*\s*=\s*-10\b|tx_power\w*\s*=\s*10\b", code):
            hits.append((p.relative_to(REPO), m.group(0)))
    assert not hits, hits


def _code_only(source: str) -> str:
    import io
    import tokenize

    out = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            out.append(tok.string)
    return " ".join(out)
