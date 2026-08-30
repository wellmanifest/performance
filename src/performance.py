#!/usr/bin/env python3
"""Offline Performance v1 conformance and reversible local adoption."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

BEGIN = "# BEGIN wellmanifest/performance v1"
END = "# END wellmanifest/performance v1"
PATTERNS = (
    "/.code2llm_cache/",
    "/.coverage",
    "/.deployments/",
    "/.mypy_cache/",
    "/.nox/",
    "/.planfile/events/",
    "/.planfile/evidence/",
    "/.planfile/index/",
    "/.pytest_cache/",
    "/.ruff_cache/",
    "/.tox/",
    "/.venv/",
    "/.worktrees/",
    "**/__pycache__/",
    "coverage/",
    "dist/",
    "htmlcov/",
    "node_modules/",
    "venv/",
)
TOP_KEYS = {
    "schema", "subject", "profiles", "workload", "baseline", "candidate",
    "budgets", "controls", "invariants", "strategy", "rollout", "rollback",
    "authority",
}
PROFILE_VALUES = {
    "repository", "developer-workstation", "runtime-service",
    "high-throughput-runtime",
}
OUTCOMES = {
    "no_change", "configuration", "packaging", "same_language", "protocol",
    "selective_native", "bounded_replacement",
}
UNITS = {
    "ns", "us", "ms", "s", "bytes", "bytes_per_second",
    "operations_per_second", "percent", "count",
}
INVARIANT_KINDS = {
    "functional", "security", "resource", "authority", "availability",
    "compatibility",
}
CONTROL_KINDS = {
    "repository_working_set", "background_work", "append_only_read",
    "health_probe", "refresh_cache", "concurrency", "process_resource",
    "request_amplification",
}
CONTROL_UNITS = {"bytes", "records", "milliseconds", "percent", "count", "weight"}
PROFILE_CONTROLS = {
    "repository": {"repository_working_set"},
    "developer-workstation": {"background_work", "process_resource"},
    "runtime-service": {"process_resource", "concurrency"},
    "high-throughput-runtime": {"process_resource", "concurrency"},
}
AUDIT_SUFFIXES = {".cjs", ".js", ".mjs", ".py", ".ts", ".yaml", ".yml"}
AUDIT_SKIP_DIRS = {
    ".deployments", ".git", ".mypy_cache", ".nox", ".pytest_cache",
    ".ruff_cache", ".secrets", ".tox", ".venv", ".worktrees",
    "__pycache__", "build", "coverage", "dist", "htmlcov", "node_modules",
    "vendor", "venv",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
UNSAFE_PATH = re.compile(r"(^/|(^|/)\.\.(/|$))")
SECRET_QUERY = re.compile(r"(?:token|api[_-]?key|secret)=", re.IGNORECASE)
SHELL_TEXT = re.compile(r"(?:[`;$|]|\$\(|\b(?:sudo|bash|zsh|pwsh|cmd)\b)", re.IGNORECASE)


class DuplicateKey(ValueError):
    pass


class InvalidJsonNumber(ValueError):
    pass


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def load_plan(path: Path) -> Any:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    return json.loads(
        text,
        object_pairs_hook=strict_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(InvalidJsonNumber(value)),
    )


def finding(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def exact_object(value: Any, required: set[str], path: str, findings: list[dict[str, str]]) -> bool:
    if not isinstance(value, dict):
        findings.append(finding("PERF-SHAPE-001", path, "must be an object"))
        return False
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    for key in missing:
        findings.append(finding("PERF-SHAPE-002", f"{path}.{key}", "required field is missing"))
    for key in unknown:
        findings.append(finding("PERF-SHAPE-003", f"{path}.{key}", "unknown field is forbidden"))
    return not missing and not unknown


def valid_evidence(value: Any, path: str, findings: list[dict[str, str]]) -> None:
    if not exact_object(value, {"uri", "sha256"}, path, findings):
        return
    uri = value["uri"]
    if not isinstance(uri, str) or not uri or SECRET_QUERY.search(uri):
        findings.append(finding("PERF-EVIDENCE-001", f"{path}.uri", "URI is empty or contains secret-like query data"))
    if not isinstance(value["sha256"], str) or not SHA64.fullmatch(value["sha256"]):
        findings.append(finding("PERF-EVIDENCE-002", f"{path}.sha256", "must be a lowercase SHA-256 digest"))


def metric_map(value: Any, path: str, findings: list[dict[str, str]]) -> dict[str, tuple[str, float]]:
    result: dict[str, tuple[str, float]] = {}
    if not isinstance(value, list) or not value:
        findings.append(finding("PERF-METRIC-001", path, "at least one metric is required"))
        return result
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not exact_object(item, {"name", "unit", "value"}, item_path, findings):
            continue
        name, unit, number = item["name"], item["unit"], item["value"]
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
            findings.append(finding("PERF-METRIC-002", f"{item_path}.name", "invalid metric name"))
            continue
        if name in result:
            findings.append(finding("PERF-METRIC-003", f"{item_path}.name", "metric name is duplicated"))
        if unit not in UNITS or not isinstance(number, (int, float)) or isinstance(number, bool):
            findings.append(finding("PERF-METRIC-004", item_path, "metric unit or value is invalid"))
            continue
        result[name] = (unit, float(number))
    return result


def validate_plan(plan: Any) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not exact_object(plan, TOP_KEYS, "$", findings):
        return sorted(findings, key=lambda item: (item["code"], item["path"]))
    if plan["schema"] != "performance.plan/v1":
        findings.append(finding("PERF-SCHEMA-001", "$.schema", "unsupported schema"))

    subject = plan["subject"]
    if exact_object(subject, {"repository", "revision", "component"}, "$.subject", findings):
        if not isinstance(subject["repository"], str) or not REPOSITORY.fullmatch(subject["repository"]):
            findings.append(finding("PERF-SUBJECT-001", "$.subject.repository", "must be owner/repository"))
        if not isinstance(subject["revision"], str) or not SHA40.fullmatch(subject["revision"]):
            findings.append(finding("PERF-SUBJECT-002", "$.subject.revision", "must be an immutable revision"))

    profiles = plan["profiles"]
    if not isinstance(profiles, list) or not profiles or len(profiles) != len(set(profiles)) or any(item not in PROFILE_VALUES for item in profiles):
        findings.append(finding("PERF-PROFILE-001", "$.profiles", "profiles must be unique known values"))

    workload = plan["workload"]
    workload_id = None
    if exact_object(workload, {"id", "description", "method", "warmup", "samples", "evidence"}, "$.workload", findings):
        workload_id = workload["id"]
        if not isinstance(workload_id, str) or not IDENTIFIER.fullmatch(workload_id):
            findings.append(finding("PERF-WORKLOAD-001", "$.workload.id", "invalid workload id"))
        if not isinstance(workload["samples"], int) or isinstance(workload["samples"], bool) or workload["samples"] < 3:
            findings.append(finding("PERF-WORKLOAD-002", "$.workload.samples", "at least three samples are required"))
        valid_evidence(workload["evidence"], "$.workload.evidence", findings)

    measurements: dict[str, dict[str, tuple[str, float]]] = {}
    for label in ("baseline", "candidate"):
        value = plan[label]
        if exact_object(value, {"workloadId", "metrics", "evidence"}, f"$.{label}", findings):
            if value["workloadId"] != workload_id:
                findings.append(finding("PERF-COMPARE-001", f"$.{label}.workloadId", "measurement workload differs"))
            measurements[label] = metric_map(value["metrics"], f"$.{label}.metrics", findings)
            valid_evidence(value["evidence"], f"$.{label}.evidence", findings)
    baseline = measurements.get("baseline", {})
    candidate = measurements.get("candidate", {})
    if baseline and candidate and baseline.keys() != candidate.keys():
        findings.append(finding("PERF-COMPARE-002", "$.candidate.metrics", "metric sets differ"))
    for name in baseline.keys() & candidate.keys():
        if baseline[name][0] != candidate[name][0]:
            findings.append(finding("PERF-COMPARE-003", f"$.candidate.metrics.{name}", "metric units differ"))

    budgets = plan["budgets"]
    if not isinstance(budgets, list) or not budgets:
        findings.append(finding("PERF-BUDGET-001", "$.budgets", "at least one budget is required"))
    else:
        for index, item in enumerate(budgets):
            item_path = f"$.budgets[{index}]"
            if not exact_object(item, {"metric", "unit", "comparison", "threshold"}, item_path, findings):
                continue
            name = item["metric"]
            if name not in candidate or item["unit"] not in UNITS or candidate.get(name, (None,))[0] != item["unit"]:
                findings.append(finding("PERF-BUDGET-002", item_path, "budget metric or unit is not comparable"))
                continue
            threshold, value = item["threshold"], candidate[name][1]
            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or item["comparison"] not in {"at_most", "at_least"}:
                findings.append(finding("PERF-BUDGET-003", item_path, "budget comparison or threshold is invalid"))
            elif (item["comparison"] == "at_most" and value > threshold) or (item["comparison"] == "at_least" and value < threshold):
                findings.append(finding("PERF-BUDGET-004", item_path, "candidate fails budget"))

    controls = plan["controls"]
    observed_controls: set[str] = set()
    if not isinstance(controls, list) or not controls:
        findings.append(finding("PERF-CONTROL-001", "$.controls", "at least one control is required"))
    else:
        required_control_keys = {"kind", "target", "limit", "unit", "mechanism", "verification", "exception"}
        for index, item in enumerate(controls):
            item_path = f"$.controls[{index}]"
            if not exact_object(item, required_control_keys, item_path, findings):
                continue
            if item["kind"] not in CONTROL_KINDS or item["unit"] not in CONTROL_UNITS:
                findings.append(finding("PERF-CONTROL-002", item_path, "control kind or unit is invalid"))
            else:
                observed_controls.add(item["kind"])
            limit = item["limit"]
            if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit < 0 or limit in {float("inf"), float("-inf")}:
                findings.append(finding("PERF-CONTROL-003", f"{item_path}.limit", "control limit must be finite and non-negative"))
            for key in ("target", "mechanism", "verification", "exception"):
                if not isinstance(item[key], str) or (key != "exception" and not item[key].strip()):
                    findings.append(finding("PERF-CONTROL-004", f"{item_path}.{key}", "control text is invalid"))
            if isinstance(item["mechanism"], str) and SHELL_TEXT.search(item["mechanism"]):
                findings.append(finding("PERF-CONTROL-005", f"{item_path}.mechanism", "control contains shell authority"))
    if isinstance(profiles, list):
        for profile in sorted(set(profiles) & PROFILE_VALUES):
            for control in sorted(PROFILE_CONTROLS[profile] - observed_controls):
                findings.append(finding("PERF-CONTROL-006", "$.controls", f"{profile} requires {control}"))

    invariants = plan["invariants"]
    observed_kinds: set[str] = set()
    if not isinstance(invariants, list) or not invariants:
        findings.append(finding("PERF-INVARIANT-001", "$.invariants", "preserved invariants are required"))
    else:
        for index, item in enumerate(invariants):
            item_path = f"$.invariants[{index}]"
            if exact_object(item, {"id", "kind", "verification", "required"}, item_path, findings):
                if item["kind"] not in INVARIANT_KINDS or item["required"] is not True:
                    findings.append(finding("PERF-INVARIANT-002", item_path, "invariant kind or required flag is invalid"))
                else:
                    observed_kinds.add(item["kind"])
    for kind in ("functional", "security", "resource", "authority"):
        if kind not in observed_kinds:
            findings.append(finding("PERF-INVARIANT-003", "$.invariants", f"{kind} invariant is missing"))

    strategy = plan["strategy"]
    if exact_object(strategy, {"outcome", "rationale", "changedPaths", "compatibility"}, "$.strategy", findings):
        if strategy["outcome"] not in OUTCOMES:
            findings.append(finding("PERF-STRATEGY-001", "$.strategy.outcome", "unknown outcome"))
        paths = strategy["changedPaths"]
        if not isinstance(paths, list) or any(not isinstance(item, str) or UNSAFE_PATH.search(item) for item in paths):
            findings.append(finding("PERF-STRATEGY-002", "$.strategy.changedPaths", "changed paths must be bounded and relative"))
        if strategy["outcome"] in {"selective_native", "bounded_replacement"} and not str(strategy["compatibility"]).strip():
            findings.append(finding("PERF-STRATEGY-003", "$.strategy.compatibility", "migration requires compatibility evidence"))

    for label in ("rollout", "rollback"):
        action = plan[label]
        if exact_object(action, {"mechanism", "scope", "observationSeconds", "abortThreshold"}, f"$.{label}", findings):
            if not isinstance(action["observationSeconds"], int) or isinstance(action["observationSeconds"], bool) or not 1 <= action["observationSeconds"] <= 2_592_000:
                findings.append(finding("PERF-ACTION-001", f"$.{label}.observationSeconds", "observation window is invalid"))
            if any(not isinstance(action[key], str) or not action[key].strip() or SHELL_TEXT.search(action[key]) for key in ("mechanism", "scope", "abortThreshold")):
                findings.append(finding("PERF-ACTION-002", f"$.{label}", "action must be descriptive and contain no shell authority"))

    authority = plan["authority"]
    if exact_object(authority, {"requestOnly", "executionGrantEmbedded"}, "$.authority", findings):
        if authority != {"requestOnly": True, "executionGrantEmbedded": False}:
            findings.append(finding("PERF-AUTHORITY-001", "$.authority", "plan must remain request-only"))
    return sorted(findings, key=lambda item: (item["code"], item["path"]))


def audit_repository(root: Path, *, max_files: int = 5000, max_bytes: int = 1_048_576, include_tests: bool = False) -> list[dict[str, Any]]:
    if max_files < 1 or max_bytes < 1:
        raise ValueError("audit_bounds_invalid")
    root = root.resolve()
    findings: list[dict[str, Any]] = []
    scanned = 0
    exhausted = False
    shared_health_refs = 0
    health_default: tuple[str, int, int] | None = None
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in AUDIT_SKIP_DIRS)
        if not include_tests:
            names[:] = [name for name in names if name not in {"test", "tests"}]
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if (path.suffix.lower() not in AUDIT_SUFFIXES and filename != ".env.example") or filename == ".env":
                continue
            if scanned >= max_files:
                exhausted = True
                break
            scanned += 1
            try:
                if path.stat().st_size > max_bytes:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            relative = path.relative_to(root).as_posix()
            compose = "compose" in filename.lower()
            for number, line in enumerate(lines, 1):
                stripped = line.strip()
                if filename == ".env.example":
                    cadence = re.fullmatch(r"HEALTHCHECK_INTERVAL=(\d+)(ms|s)", stripped)
                    if cadence:
                        milliseconds = int(cadence.group(1)) * (1000 if cadence.group(2) == "s" else 1)
                        health_default = (relative, number, milliseconds)
                if compose:
                    if "interval: ${HEALTHCHECK_INTERVAL}" in stripped:
                        shared_health_refs += 1
                    cadence = re.search(r"\binterval:\s*(\d+)(ms|s)\b", stripped)
                    if cadence:
                        milliseconds = int(cadence.group(1)) * (1000 if cadence.group(2) == "s" else 1)
                        if milliseconds < 15_000:
                            findings.append({"code": "PERF-AUDIT-HEALTH-001", "path": relative, "line": number, "message": "healthcheck cadence below 15 seconds needs detection-tier evidence"})
                    if "test:" in stripped and re.search(r'["\'](?:node|python\d*|php)["\']\s*,\s*["\'](?:-e|-c|-r)["\']', stripped):
                        findings.append({"code": "PERF-AUDIT-HEALTH-002", "path": relative, "line": number, "message": "healthcheck starts an interpreter for each probe"})
                growing_source = re.search(
                    r"(?:jsonl|(?:^|[^A-Za-z0-9_])(?:audit|log)(?:File|_file|Path|_path|Log|_log|Jsonl)|(?:Audit|Log)(?:File|Path|Jsonl)|(?:^|[^A-Za-z0-9_])event(?:Log|_log|Jsonl)|Event(?:Log|Jsonl))",
                    stripped,
                )
                if re.search(r"\b(?:readFile|read_text|readText|read_to_string)\s*\(", stripped) and growing_source:
                    findings.append({"code": "PERF-AUDIT-IO-001", "path": relative, "line": number, "message": "probable whole-file read on a growing event or audit source"})
                if re.search(r"Promise\.all\s*\([^\n]*\.map\s*\(", stripped) and not re.search(r"\.slice\s*\(", stripped):
                    findings.append({"code": "PERF-AUDIT-CONCURRENCY-001", "path": relative, "line": number, "message": "mapped Promise.all has no visible local input bound"})
            if exhausted:
                break
        if exhausted:
            break
    if health_default and health_default[2] < 15_000:
        findings.append({"code": "PERF-AUDIT-HEALTH-001", "path": health_default[0], "line": health_default[1], "message": "default healthcheck cadence below 15 seconds needs detection-tier evidence"})
        if shared_health_refs > 1:
            findings.append({"code": "PERF-AUDIT-HEALTH-003", "path": health_default[0], "line": health_default[1], "message": f"one fast healthcheck default fans out to {shared_health_refs} services"})
    if exhausted:
        findings.append({"code": "PERF-AUDIT-LIMIT-001", "path": ".", "line": 0, "message": "repository audit reached its file limit"})
    return sorted(findings, key=lambda item: (item["code"], item["path"], item["line"]))


def parse_inventory(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) >= 5 and columns[4] == "checkout":
            names.append(columns[0])
    return names


def exclude_path(repository: Path) -> Path | None:
    dot_git = repository / ".git"
    if dot_git.is_dir():
        return dot_git / "info" / "exclude"
    return None


def managed_text(existing: str, remove: bool) -> str:
    lines = existing.splitlines()
    output: list[str] = []
    inside = False
    found = False
    for line in lines:
        if line == BEGIN:
            if inside or found:
                raise ValueError("duplicate or nested managed block")
            inside = True
            found = True
            continue
        if line == END:
            if not inside:
                raise ValueError("orphan managed block terminator")
            inside = False
            continue
        if not inside:
            output.append(line)
    if inside:
        raise ValueError("unterminated managed block")
    while output and output[-1] == "":
        output.pop()
    if not remove:
        if output:
            output.append("")
        output.extend((BEGIN, *PATTERNS, END))
    return "\n".join(output) + ("\n" if output else "")


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="performance-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def local_adoption(workspace: Path, inventory: Path, apply: bool, remove: bool) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    for name in parse_inventory(inventory):
        repository = (workspace / name).resolve()
        if repository.parent != workspace.resolve() or repository.name != name:
            entries.append({"repository": name, "status": "unsafe-path"})
            continue
        target = exclude_path(repository)
        if target is None:
            entries.append({"repository": name, "status": "missing-or-noncanonical"})
            continue
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        try:
            expected = managed_text(existing, remove)
        except ValueError:
            entries.append({"repository": name, "status": "malformed-managed-block"})
            continue
        current = existing == expected
        status = "absent" if remove and current else "current" if current else "needs-update"
        if apply and not current:
            atomic_write(target, expected)
            status = "removed" if remove else "updated"
        entries.append({"repository": name, "status": status})
    digest = hashlib.sha256("\n".join(PATTERNS).encode()).hexdigest()
    return {
        "schema": "performance.local-adoption-receipt/v1",
        "workspace": str(workspace.resolve()),
        "patternDigest": f"sha256:{digest}",
        "apply": apply,
        "remove": remove,
        "repositories": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("plan", type=Path)
    audit = commands.add_parser("audit-repository")
    audit.add_argument("root", type=Path)
    audit.add_argument("--max-files", type=int, default=5000)
    audit.add_argument("--max-bytes", type=int, default=1_048_576)
    audit.add_argument("--include-tests", action="store_true")
    for name in ("adopt-local", "check-local"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--remove", action="store_true")
        command.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            findings = validate_plan(load_plan(args.plan))
            print(json.dumps({"schema": "performance.report/v1", "ok": not findings, "findings": findings}, indent=2, sort_keys=True))
            return 1 if findings else 0
        if args.command == "audit-repository":
            findings = audit_repository(args.root, max_files=args.max_files, max_bytes=args.max_bytes, include_tests=args.include_tests)
            print(json.dumps({"schema": "performance.audit-report/v1", "root": str(args.root.resolve()), "ok": not findings, "findings": findings}, indent=2, sort_keys=True))
            return 1 if findings else 0
        result = local_adoption(args.workspace, args.manifest, args.command == "adopt-local", args.remove)
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.receipt:
            atomic_write(args.receipt, encoded)
        print(encoded, end="")
        bad = {"unsafe-path", "missing-or-noncanonical", "malformed-managed-block", "needs-update"}
        return 1 if any(item["status"] in bad for item in result["repositories"]) else 0
    except (UnicodeError, json.JSONDecodeError, DuplicateKey, InvalidJsonNumber) as error:
        print(json.dumps({"schema": "performance.report/v1", "ok": False, "findings": [{"code": "PERF-JSON-001", "path": "$", "message": type(error).__name__}]}, sort_keys=True))
        return 1
    except (OSError, TypeError, ValueError) as error:
        print(json.dumps({"schema": "performance.report/v1", "ok": False, "internalError": type(error).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
