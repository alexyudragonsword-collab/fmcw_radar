"""Every example compiles and imports only names that exist; running them is
tools/run_examples.py --smoke's job (CI).  Adapted from d2d_link."""

import ast
import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((REPO / "examples").glob("[0-9][0-9]_*.py"))


def test_milestone_examples_exist():
    assert [p.name[:2] for p in EXAMPLES] == ["00", "01", "02", "03", "04", "05", "06", "07", "08"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_imports_resolve(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fmcw_radar"):
            mod = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(mod, alias.name), f"{path.name}: {node.module}.{alias.name}"


def test_only_a_missing_optional_package_is_a_skip():
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_examples", REPO / "tools" / "run_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._missing_optional("ModuleNotFoundError: No module named 'matplotlib'") == "matplotlib"
    assert mod._missing_optional("ImportError: cannot import name 'x' from 'matplotlib' (/x)") is None
    assert mod._missing_optional("ModuleNotFoundError: No module named 'scipy'") is None
