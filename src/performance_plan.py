"""Performance v1 plan loading and schema-parity validation."""

from __future__ import annotations

import errno
import json
import math
import re
from pathlib import Path
from typing import Any

TOP_KEYS = {
    "schema",
    "subject",
    "profiles",
    "workload",
    "baseline",
    "candidate",
    "budgets",
    "controls",
    "invariants",
    "strategy",
    "rollout",
    "rollback",
    "authority",
}
PROFILE_VALUES = {
    "repository",
    "developer-workstation",
    "runtime-service",
    "high-throughput-runtime",
}
OUTCOMES = {
    "no_change",
    "configuration",
    "packaging",
    "same_language",
    "protocol",
    "selective_native",
    "bounded_replacement",
}
UNITS = {
    "ns",
    "us",
    "ms",
    "s",
    "bytes",
    "bytes_per_second",
    "operations_per_second",
    "percent",
    "count",
}
INVARIANT_KINDS = {
    "functional",
    "security",
    "resource",
    "authority",
    "availability",
    "compatibility",
}
CONTROL_KINDS = {
    "repository_working_set",
    "background_work",
    "append_only_read",
    "health_probe",
    "refresh_cache",
    "concurrency",
    "process_resource",
    "request_amplification",
}
CONTROL_UNITS = {"bytes", "records", "milliseconds", "percent", "count", "weight"}
PROFILE_CONTROLS = {
    "repository": {"repository_working_set"},
    "developer-workstation": {"background_work", "process_resource"},
    "runtime-service": {"process_resource", "concurrency"},
    "high-throughput-runtime": {"process_resource", "concurrency"},
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
METRIC_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
UNSAFE_PATH = re.compile(r"(^/|^[A-Za-z]:|\\|[\x00-\x1f]|(^|/)\.\.(/|$))")
SECRET_QUERY = re.compile(r"(?:token|api[_-]?key|secret)=", re.IGNORECASE)
SHELL_TEXT = re.compile(r"(?:[`;$|]|\$\(|\b(?:sudo|sh|bash|zsh|pwsh|cmd)\b)", re.IGNORECASE)


class DuplicateKey(ValueError):
    """Raised when a JSON object repeats a property key."""


class InvalidJsonNumber(ValueError):
    """Raised when a JSON number is non-finite or out of range."""


def reject_symlink_path(path: Path) -> None:
    """Reject symlinked leaf files or symlinked ancestor directories."""
    lexical = path if path.is_absolute() else (Path.cwd() / path)
    candidates = [*reversed(lexical.parents), lexical]
    for candidate in candidates:
        if candidate.is_symlink():
            raise OSError(errno.ELOOP, "symlink path forbidden", str(path))


def finite_number(value: Any) -> bool:
    """Reject booleans and values outside the runtime's finite numeric domain."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def finite_json_float(value: str) -> float:
    number = float(value)
    if not finite_number(number):
        raise InvalidJsonNumber("non-finite JSON number")
    return number


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def load_plan(path: Path) -> Any:
    reject_symlink_path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    return json.loads(
        text,
        object_pairs_hook=strict_pairs,
        parse_float=finite_json_float,
        parse_constant=lambda value: (_ for _ in ()).throw(InvalidJsonNumber(value)),
    )


def finding(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def exact_object(
    value: Any,
    required: set[str],
    path: str,
    findings: list[dict[str, str]],
) -> bool:
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
    if not isinstance(uri, str) or not uri.strip() or len(uri) > 1000 or SECRET_QUERY.search(uri):
        findings.append(
            finding("PERF-EVIDENCE-001", f"{path}.uri", "URI is empty, oversized, or contains secret-like query data")
        )
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
        if not isinstance(name, str) or not METRIC_NAME.fullmatch(name):
            findings.append(finding("PERF-METRIC-002", f"{item_path}.name", "invalid metric name"))
            continue
        if name in result:
            findings.append(finding("PERF-METRIC-003", f"{item_path}.name", "metric name is duplicated"))
        if not isinstance(unit, str) or unit not in UNITS or not finite_number(number):
            findings.append(finding("PERF-METRIC-004", item_path, "metric unit or value is invalid"))
            continue
        result[name] = (unit, float(number))
    return result


def _validate_controls(
    controls: Any,
    valid_profiles: set[str],
    findings: list[dict[str, str]],
) -> None:
    observed_controls: set[str] = set()
    if not isinstance(controls, list) or not controls:
        findings.append(finding("PERF-CONTROL-001", "$.controls", "at least one control is required"))
    else:
        required_keys = {"kind", "target", "limit", "unit", "mechanism", "verification", "exception"}
        text_bounds = (("target", 300), ("mechanism", 1000), ("verification", 1000), ("exception", 1000))
        for index, item in enumerate(controls):
            item_path = f"$.controls[{index}]"
            if not exact_object(item, required_keys, item_path, findings):
                continue
            kind, unit = item["kind"], item["unit"]
            if not isinstance(kind, str) or kind not in CONTROL_KINDS or not isinstance(unit, str) or unit not in CONTROL_UNITS:
                findings.append(finding("PERF-CONTROL-002", item_path, "control kind or unit is invalid"))
            else:
                observed_controls.add(kind)
            limit = item["limit"]
            if not finite_number(limit) or limit < 0:
                findings.append(finding("PERF-CONTROL-003", f"{item_path}.limit", "control limit must be finite and non-negative"))
            for key, max_len in text_bounds:
                val = item[key]
                if not isinstance(val, str) or (key != "exception" and not val.strip()) or len(val) > max_len:
                    findings.append(finding("PERF-CONTROL-004", f"{item_path}.{key}", "control text is invalid"))
            if isinstance(item["mechanism"], str) and SHELL_TEXT.search(item["mechanism"]):
                findings.append(finding("PERF-CONTROL-005", f"{item_path}.mechanism", "control contains shell authority"))
    for profile in sorted(valid_profiles):
        for control in sorted(PROFILE_CONTROLS[profile] - observed_controls):
            findings.append(finding("PERF-CONTROL-006", "$.controls", f"{profile} requires {control}"))


def _validate_invariants(invariants: Any, findings: list[dict[str, str]]) -> None:
    observed_kinds: set[str] = set()
    seen_ids: set[str] = set()
    if not isinstance(invariants, list) or not invariants:
        findings.append(finding("PERF-INVARIANT-001", "$.invariants", "preserved invariants are required"))
    else:
        for index, item in enumerate(invariants):
            item_path = f"$.invariants[{index}]"
            if not exact_object(item, {"id", "kind", "verification", "required"}, item_path, findings):
                continue
            inv_id = item["id"]
            if not isinstance(inv_id, str) or not IDENTIFIER.fullmatch(inv_id) or inv_id in seen_ids:
                findings.append(finding("PERF-INVARIANT-004", f"{item_path}.id", "invariant id must be unique and valid"))
            else:
                seen_ids.add(inv_id)
            ver = item["verification"]
            if not isinstance(ver, str) or not ver.strip() or len(ver) > 1000:
                findings.append(
                    finding("PERF-INVARIANT-005", f"{item_path}.verification", "invariant verification text is invalid")
                )
            kind = item["kind"]
            if not isinstance(kind, str) or kind not in INVARIANT_KINDS or item["required"] is not True:
                findings.append(finding("PERF-INVARIANT-002", item_path, "invariant kind or required flag is invalid"))
            else:
                observed_kinds.add(kind)
    for kind in ("functional", "security", "resource", "authority"):
        if kind not in observed_kinds:
            findings.append(finding("PERF-INVARIANT-003", "$.invariants", f"{kind} invariant is missing"))


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
        comp = subject["component"]
        if not isinstance(comp, str) or not comp.strip() or len(comp) > 160:
            findings.append(finding("PERF-SUBJECT-003", "$.subject.component", "component must be a non-empty bounded string"))

    profiles = plan["profiles"]
    if (
        not isinstance(profiles, list)
        or not profiles
        or any(not isinstance(item, str) or item not in PROFILE_VALUES for item in profiles)
        or len(profiles) != len(set(profiles))
    ):
        findings.append(finding("PERF-PROFILE-001", "$.profiles", "profiles must be unique known values"))
    valid_profiles = (
        {item for item in profiles if isinstance(item, str) and item in PROFILE_VALUES}
        if isinstance(profiles, list)
        else set()
    )

    workload = plan["workload"]
    workload_id: str | None = None
    if exact_object(workload, {"id", "description", "method", "warmup", "samples", "evidence"}, "$.workload", findings):
        raw_id = workload["id"]
        if not isinstance(raw_id, str) or not IDENTIFIER.fullmatch(raw_id):
            findings.append(finding("PERF-WORKLOAD-001", "$.workload.id", "invalid workload id"))
        else:
            workload_id = raw_id
        samples = workload["samples"]
        if type(samples) is not int or not (3 <= samples <= 100_000):
            findings.append(finding("PERF-WORKLOAD-002", "$.workload.samples", "samples must be an integer in 3..100000"))
        for key, max_len in (("description", 1000), ("method", 1000), ("warmup", 500)):
            val = workload[key]
            if not isinstance(val, str) or not val.strip() or len(val) > max_len:
                findings.append(finding("PERF-WORKLOAD-003", f"$.workload.{key}", "workload text field is invalid"))
        valid_evidence(workload["evidence"], "$.workload.evidence", findings)

    measurements: dict[str, dict[str, tuple[str, float]]] = {}
    for label in ("baseline", "candidate"):
        value = plan[label]
        if exact_object(value, {"workloadId", "metrics", "evidence"}, f"$.{label}", findings):
            wid = value["workloadId"]
            if not isinstance(wid, str) or not IDENTIFIER.fullmatch(wid) or wid != workload_id:
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
            name, unit = item["metric"], item["unit"]
            if (
                not isinstance(name, str)
                or not METRIC_NAME.fullmatch(name)
                or name not in candidate
                or not isinstance(unit, str)
                or unit not in UNITS
                or candidate.get(name, (None,))[0] != unit
            ):
                findings.append(finding("PERF-BUDGET-002", item_path, "budget metric or unit is not comparable"))
                continue
            threshold, value = item["threshold"], candidate[name][1]
            comp = item["comparison"]
            if not finite_number(threshold) or comp not in {"at_most", "at_least"}:
                findings.append(finding("PERF-BUDGET-003", item_path, "budget comparison or threshold is invalid"))
            elif (comp == "at_most" and value > threshold) or (comp == "at_least" and value < threshold):
                findings.append(finding("PERF-BUDGET-004", item_path, "candidate fails budget"))

    _validate_controls(plan["controls"], valid_profiles, findings)
    _validate_invariants(plan["invariants"], findings)

    strategy = plan["strategy"]
    if exact_object(strategy, {"outcome", "rationale", "changedPaths", "compatibility"}, "$.strategy", findings):
        outcome = strategy["outcome"]
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            findings.append(finding("PERF-STRATEGY-001", "$.strategy.outcome", "unknown outcome"))
        paths = strategy["changedPaths"]
        if (
            not isinstance(paths, list)
            or len(paths) > 100
            or any(not isinstance(item, str) or not item.strip() or UNSAFE_PATH.search(item) for item in paths)
        ):
            findings.append(finding("PERF-STRATEGY-002", "$.strategy.changedPaths", "changed paths must be bounded and relative"))
        rationale = strategy["rationale"]
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 1000 or SHELL_TEXT.search(rationale):
            findings.append(finding("PERF-STRATEGY-004", "$.strategy.rationale", "strategy rationale is invalid or contains shell authority"))
        compat = strategy["compatibility"]
        if not isinstance(compat, str) or not compat.strip() or len(compat) > 1000:
            findings.append(finding("PERF-STRATEGY-003", "$.strategy.compatibility", "compatibility evidence must be a non-empty bounded string"))

    for label in ("rollout", "rollback"):
        action = plan[label]
        if exact_object(action, {"mechanism", "scope", "observationSeconds", "abortThreshold"}, f"$.{label}", findings):
            obs = action["observationSeconds"]
            if type(obs) is not int or not (1 <= obs <= 2_592_000):
                findings.append(finding("PERF-ACTION-001", f"$.{label}.observationSeconds", "observation window is invalid"))
            action_bounds = (("mechanism", 1000), ("scope", 500), ("abortThreshold", 500))
            if any(
                not isinstance(action[key], str)
                or not action[key].strip()
                or len(action[key]) > max_len
                or SHELL_TEXT.search(action[key])
                for key, max_len in action_bounds
            ):
                findings.append(finding("PERF-ACTION-002", f"$.{label}", "action must be descriptive and contain no shell authority"))

    authority = plan["authority"]
    if (
        exact_object(authority, {"requestOnly", "executionGrantEmbedded"}, "$.authority", findings)
        and authority != {"requestOnly": True, "executionGrantEmbedded": False}
    ):
        findings.append(finding("PERF-AUTHORITY-001", "$.authority", "plan must remain request-only"))
    return sorted(findings, key=lambda item: (item["code"], item["path"]))
