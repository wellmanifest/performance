"""Regression tests for modularization, schema parity, unhashable inputs, and symlink safety."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).parents[1]
SRC_DIR = ROOT_DIR / "src"
MODULE_PATH = SRC_DIR / "performance.py"
SPEC = importlib.util.spec_from_file_location("performance_hardening_target", MODULE_PATH)
assert SPEC and SPEC.loader
performance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(performance)


def _evidence(seed: str) -> dict[str, str]:
    return {"uri": f"artifact://example/evidence/{seed}", "sha256": seed * 64}


def _valid_plan() -> dict[str, object]:
    metrics = [
        {"name": "cpu", "unit": "percent", "value": 50},
        {"name": "latency", "unit": "ms", "value": 20},
    ]
    return {
        "schema": "performance.plan/v1",
        "subject": {"repository": "example/service", "revision": "a" * 40, "component": "observer"},
        "profiles": ["repository", "runtime-service"],
        "workload": {
            "id": "tail",
            "description": "latest records",
            "method": "fixed fixture",
            "warmup": "one pass",
            "samples": 3,
            "evidence": _evidence("b"),
        },
        "baseline": {"workloadId": "tail", "metrics": copy.deepcopy(metrics), "evidence": _evidence("c")},
        "candidate": {"workloadId": "tail", "metrics": copy.deepcopy(metrics), "evidence": _evidence("d")},
        "budgets": [{"metric": "cpu", "unit": "percent", "comparison": "at_most", "threshold": 60}],
        "controls": [
            {
                "kind": "repository_working_set",
                "target": "repository",
                "limit": 1000,
                "unit": "count",
                "mechanism": "narrow generated tree exclusions",
                "verification": "bounded file count",
                "exception": "",
            },
            {
                "kind": "process_resource",
                "target": "observer",
                "limit": 50,
                "unit": "percent",
                "mechanism": "runtime cpu budget",
                "verification": "cpu pressure sample",
                "exception": "",
            },
            {
                "kind": "concurrency",
                "target": "refresh",
                "limit": 1,
                "unit": "count",
                "mechanism": "coalesced refresh",
                "verification": "concurrent caller test",
                "exception": "",
            },
        ],
        "invariants": [
            {"id": kind, "kind": kind, "verification": "bounded test", "required": True}
            for kind in ("functional", "security", "resource", "authority")
        ],
        "strategy": {
            "outcome": "configuration",
            "rationale": "reduce repeated scans",
            "changedPaths": ["src/observer.py"],
            "compatibility": "same output",
        },
        "rollout": {
            "mechanism": "one local service",
            "scope": "development",
            "observationSeconds": 60,
            "abortThreshold": "latency over budget",
        },
        "rollback": {
            "mechanism": "restore prior config",
            "scope": "same service",
            "observationSeconds": 60,
            "abortThreshold": "health check fails",
        },
        "authority": {"requestOnly": True, "executionGrantEmbedded": False},
    }


class ModularityAndParityTests(unittest.TestCase):
    def test_owned_source_and_test_modules_stay_under_500_lines(self) -> None:
        for folder in (SRC_DIR, ROOT_DIR / "tests"):
            for py_file in sorted(folder.glob("*.py")):
                line_count = len(py_file.read_text(encoding="utf-8").splitlines())
                self.assertLess(line_count, 500, f"{py_file} has {line_count} lines (>= 500)")

    def test_unhashable_elements_report_findings_without_type_error(self) -> None:
        plan = _valid_plan()
        plan["profiles"] = [{"nested": 1}]
        codes = {item["code"] for item in performance.validate_plan(plan)}
        self.assertIn("PERF-PROFILE-001", codes)

        plan = _valid_plan()
        plan["budgets"][0]["metric"] = ["unhashable"]  # type: ignore[index]
        plan["budgets"][0]["unit"] = {"bad": 1}  # type: ignore[index]
        codes = {item["code"] for item in performance.validate_plan(plan)}
        self.assertIn("PERF-BUDGET-002", codes)

        plan = _valid_plan()
        plan["controls"][0]["kind"] = ["bad"]  # type: ignore[index]
        plan["invariants"][0]["id"] = {"bad": 1}  # type: ignore[index]
        plan["invariants"][0]["kind"] = ["bad"]  # type: ignore[index]
        plan["strategy"]["outcome"] = ["bad"]  # type: ignore[index]
        codes = {item["code"] for item in performance.validate_plan(plan)}
        self.assertTrue({"PERF-CONTROL-002", "PERF-INVARIANT-002", "PERF-INVARIANT-004", "PERF-STRATEGY-001"} <= codes)

    def test_schema_field_parity_in_subject_workload_metrics_invariants_and_strategy(self) -> None:
        plan = _valid_plan()
        plan["subject"]["component"] = "   "  # type: ignore[index]
        plan["workload"]["description"] = ""  # type: ignore[index]
        plan["workload"]["samples"] = 100_001  # type: ignore[index]
        plan["baseline"]["metrics"][0]["name"] = "9starts_with_digit"  # type: ignore[index]
        plan["invariants"][1]["id"] = "functional"  # duplicate id  # type: ignore[index]
        plan["invariants"][1]["verification"] = ""  # type: ignore[index]
        plan["strategy"]["rationale"] = "sudo systemctl restart app"  # type: ignore[index]
        plan["strategy"]["compatibility"] = None  # type: ignore[index]
        plan["strategy"]["changedPaths"] = ["C:\\escape\\path"]  # type: ignore[index]
        codes = {item["code"] for item in performance.validate_plan(plan)}
        expected = {
            "PERF-SUBJECT-003",
            "PERF-WORKLOAD-002",
            "PERF-WORKLOAD-003",
            "PERF-METRIC-002",
            "PERF-INVARIANT-004",
            "PERF-INVARIANT-005",
            "PERF-STRATEGY-002",
            "PERF-STRATEGY-003",
            "PERF-STRATEGY-004",
        }
        self.assertTrue(expected <= codes, f"Missing findings: {expected - codes}")

    def test_bool_audit_bounds_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                performance.audit_repository(root, max_files=True)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                performance.audit_repository(root, max_bytes=True)  # type: ignore[arg-type]

    def test_symlink_plan_and_symlink_exclude_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_plan = root / "real-plan.json"
            real_plan.write_text(json.dumps(_valid_plan()), encoding="utf-8")
            link_plan = root / "link-plan.json"
            link_plan.symlink_to(real_plan)

            with self.assertRaises(OSError):
                performance.load_plan(link_plan)

            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "validate", str(link_plan)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(2, proc.returncode)
            self.assertIn("OSError", proc.stdout)

            outside = root / "outside-target.txt"
            outside.write_text("do-not-overwrite\n", encoding="utf-8")
            repo_info = root / "one" / ".git" / "info"
            repo_info.mkdir(parents=True)
            (repo_info / "exclude").symlink_to(outside)
            manifest = root / "repos.manifest"
            manifest.write_text("one\tgit@example:one\tpublic\tyes\tcheckout\ttest\n", encoding="utf-8")

            receipt = performance.local_adoption(root, manifest, True, False)
            self.assertEqual([{"repository": "one", "status": "unsafe-path"}], receipt["repositories"])
            self.assertEqual("do-not-overwrite\n", outside.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
