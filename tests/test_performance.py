import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "src" / "performance.py"
SPEC = importlib.util.spec_from_file_location("performance", MODULE_PATH)
performance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(performance)


def evidence(seed):
    return {"uri": f"artifact://example/evidence/{seed}", "sha256": seed * 64}


def valid_plan():
    metrics = [
        {"name": "cpu", "unit": "percent", "value": 50},
        {"name": "latency", "unit": "ms", "value": 20},
    ]
    return {
        "schema": "performance.plan/v1",
        "subject": {"repository": "example/service", "revision": "a" * 40, "component": "observer"},
        "profiles": ["repository", "runtime-service"],
        "workload": {"id": "tail", "description": "latest records", "method": "fixed fixture", "warmup": "one pass", "samples": 3, "evidence": evidence("b")},
        "baseline": {"workloadId": "tail", "metrics": copy.deepcopy(metrics), "evidence": evidence("c")},
        "candidate": {"workloadId": "tail", "metrics": copy.deepcopy(metrics), "evidence": evidence("d")},
        "budgets": [{"metric": "cpu", "unit": "percent", "comparison": "at_most", "threshold": 60}],
        "invariants": [
            {"id": kind, "kind": kind, "verification": "bounded test", "required": True}
            for kind in ("functional", "security", "resource", "authority")
        ],
        "strategy": {"outcome": "configuration", "rationale": "reduce repeated scans", "changedPaths": ["src/observer.py"], "compatibility": "same output"},
        "rollout": {"mechanism": "one local service", "scope": "development", "observationSeconds": 60, "abortThreshold": "latency over budget"},
        "rollback": {"mechanism": "restore prior config", "scope": "same service", "observationSeconds": 60, "abortThreshold": "health check fails"},
        "authority": {"requestOnly": True, "executionGrantEmbedded": False},
    }


class PlanTests(unittest.TestCase):
    def test_valid_plan(self):
        self.assertEqual([], performance.validate_plan(valid_plan()))

    def test_unknown_field_and_embedded_authority_fail(self):
        plan = valid_plan()
        plan["unknown"] = True
        self.assertEqual("PERF-SHAPE-003", performance.validate_plan(plan)[0]["code"])
        plan.pop("unknown")
        plan["authority"]["executionGrantEmbedded"] = True
        self.assertIn("PERF-AUTHORITY-001", {item["code"] for item in performance.validate_plan(plan)})

    def test_incomparable_and_failed_budget_fail(self):
        plan = valid_plan()
        plan["candidate"]["workloadId"] = "other"
        plan["candidate"]["metrics"][0]["value"] = 90
        codes = {item["code"] for item in performance.validate_plan(plan)}
        self.assertTrue({"PERF-COMPARE-001", "PERF-BUDGET-004"} <= codes)

    def test_duplicate_keys_exit_one_without_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text('{"schema":"performance.plan/v1","schema":"secret"}')
            result = subprocess.run([sys.executable, str(MODULE_PATH), "validate", str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertNotIn("secret", result.stdout)

    def test_malformed_utf8_is_an_input_finding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_bytes(b'{"schema":"\xff"}')
            result = subprocess.run([sys.executable, str(MODULE_PATH), "validate", str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("PERF-JSON-001", result.stdout)

    def test_all_outcomes_and_deterministic_findings(self):
        for outcome in performance.OUTCOMES:
            plan = valid_plan()
            plan["strategy"]["outcome"] = outcome
            if outcome in {"selective_native", "bounded_replacement"}:
                plan["strategy"]["compatibility"] = "stable interface test"
            self.assertEqual([], performance.validate_plan(plan), outcome)
        plan = valid_plan()
        plan["invariants"] = []
        self.assertEqual(performance.validate_plan(plan), performance.validate_plan(plan))
        self.assertIn("PERF-INVARIANT-003", {item["code"] for item in performance.validate_plan(plan)})


class AdoptionTests(unittest.TestCase):
    def fixture(self, root):
        for name in ("one", "two"):
            (root / name / ".git" / "info").mkdir(parents=True)
        (root / "one" / ".git" / "info" / "exclude").write_text("custom.cache\n")
        manifest = root / "repos.manifest"
        manifest.write_text(
            "# inventory\n"
            "one\tgit@example:one\tpublic\tyes\tcheckout\ttest\n"
            "two\tgit@example:two\tpublic\tno\tcheckout\ttest\n"
            "three\tgit@example:three\tpublic\tno\tmissing\ttest\n"
        )
        return manifest

    def test_adopt_check_and_remove_preserve_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.fixture(root)
            applied = performance.local_adoption(root, manifest, True, False)
            self.assertEqual(["updated", "updated"], [item["status"] for item in applied["repositories"]])
            content = (root / "one" / ".git" / "info" / "exclude").read_text()
            self.assertIn("custom.cache", content)
            self.assertIn("/.planfile/events/", content)
            self.assertNotIn("\n/.planfile/\n", content)
            checked = performance.local_adoption(root, manifest, False, False)
            self.assertEqual(["current", "current"], [item["status"] for item in checked["repositories"]])
            removed = performance.local_adoption(root, manifest, True, True)
            self.assertEqual(["removed", "removed"], [item["status"] for item in removed["repositories"]])
            self.assertEqual("custom.cache\n", (root / "one" / ".git" / "info" / "exclude").read_text())


if __name__ == "__main__":
    unittest.main()
