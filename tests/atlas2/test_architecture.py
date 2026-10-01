import ast
import importlib
import pkgutil
import sys
import unittest
from pathlib import Path

import atlas2

ROOT = Path(__file__).resolve().parents[2] / "atlas2"
FORBIDDEN_IMPORT_PREFIXES = (
    "atlas",
    "MetaTrader5",
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "importlib",
)
FORBIDDEN_TOKENS = ("order_send", "order_check")


def _forbidden_import(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_IMPORT_PREFIXES)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_p0_has_no_legacy_broker_or_network_imports(self):
        violations = []
        dynamic = []
        for path in ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if _forbidden_import(name):
                        violations.append((path, name))
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in {"__import__", "import_module"}:
                        dynamic.append((path, node.func.id))
                    elif isinstance(node.func, ast.Attribute) and node.func.attr in {"__import__", "import_module"}:
                        dynamic.append((path, node.func.attr))
        self.assertEqual(violations, [])
        self.assertEqual(dynamic, [])

    def test_p0_source_contains_no_order_api_calls(self):
        hits = []
        for path in ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_TOKENS:
                if token in text:
                    hits.append((path, token))
        self.assertEqual(hits, [])

    def test_importing_all_atlas2_modules_does_not_load_legacy_or_mt5(self):
        before = set(sys.modules)
        for module in pkgutil.walk_packages(atlas2.__path__, atlas2.__name__ + "."):
            importlib.import_module(module.name)
        newly_loaded = set(sys.modules) - before
        forbidden = sorted(
            name for name in newly_loaded
            if name == "atlas" or name.startswith("atlas.") or name == "MetaTrader5" or name.startswith("MetaTrader5.")
        )
        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()
