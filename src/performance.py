#!/usr/bin/env python3
"""Offline Performance v1 conformance and reversible local adoption."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
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
AUDIT_SUFFIXES = {".cjs", ".js", ".mjs", ".py", ".rs", ".ts", ".yaml", ".yml"}
AUDIT_SKIP_DIRS = {
    ".code2llm_cache", ".deployments", ".git", ".governance", ".koru",
    ".mypy_cache", ".nox", ".planfile", ".pytest_cache", ".ruff_cache",
    ".secrets", ".subactor", ".tox", ".venv", ".worktrees", "__pycache__",
    "_bundled", "build", "code2llm_output", "coverage", "dist", "htmlcov",
    "koru-audits", "koru-worktrees", "node_modules", "preserved-worktrees",
    "site-packages", "target", "vendor", "venv",
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
        if unit not in UNITS or not finite_number(number):
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
            if not finite_number(threshold) or item["comparison"] not in {"at_most", "at_least"}:
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
            if not finite_number(limit) or limit < 0:
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


LOOP_NODES = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)
SUBPROCESS_ATTRS = {"run", "Popen", "check_output", "call", "check_call"}
CLEANUP_PREFIXES = ("stop", "terminate", "kill", "cleanup")
SQLITE_RECEIVER_NAMES = {"conn", "connection", "db", "cur", "cursor", "sqlite", "_conn", "_db", "_cursor"}
NON_SQLITE_RECEIVER_NAMES = {"executor", "runner", "engine", "client", "session", "pipeline", "command", "task", "shell", "pool"}
PRAGMA_SYNC_FULL = re.compile(r"PRAGMA\s+synchronous\s*=\s*FULL\b", re.IGNORECASE)
PRAGMA_SYNC_NORMAL = re.compile(r"PRAGMA\s+synchronous\s*=\s*NORMAL\b", re.IGNORECASE)


def is_sqlite_connect_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr == "connect":
        if isinstance(node.func.value, ast.Name) and node.func.value.id in {"sqlite3", "sqlite"}:
            return True
    return False


def collect_sqlite_binding_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                ctx = item.context_expr
                unwrapped = ctx.args[0] if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Name) and ctx.func.id == "closing" and ctx.args else ctx
                if is_sqlite_connect_call(unwrapped) and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if is_sqlite_connect_call(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                val = node.value
                if isinstance(val.func, ast.Attribute) and val.func.attr == "cursor":
                    recv = val.func.value
                    confirmed = (
                        is_sqlite_connect_call(recv)
                        or (isinstance(recv, ast.Name) and recv.id in names)
                        or (
                            isinstance(recv, ast.Attribute)
                            and isinstance(recv.value, ast.Name)
                            and recv.value.id in {"self", "cls"}
                            and recv.attr in SQLITE_RECEIVER_NAMES
                        )
                    )
                    if confirmed:
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id not in names:
                                names.add(target.id)
                                changed = True
    return names


def is_sqlite_execute_call(node: ast.Call, sqlite_names: set[str]) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"execute", "executemany"}:
        return False
    receiver = node.func.value
    if isinstance(receiver, ast.Name):
        if receiver.id in NON_SQLITE_RECEIVER_NAMES and receiver.id not in sqlite_names:
            return False
        if receiver.id in sqlite_names or receiver.id in SQLITE_RECEIVER_NAMES:
            return True
    elif isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name) and receiver.value.id in {"self", "cls"}:
        if receiver.attr in NON_SQLITE_RECEIVER_NAMES:
            return False
        if receiver.attr in SQLITE_RECEIVER_NAMES:
            return True
    elif isinstance(receiver, ast.Call):
        if isinstance(receiver.func, ast.Attribute) and receiver.func.attr in {"_get_connection", "get_connection", "connect"}:
            return True
        if isinstance(receiver.func, ast.Attribute) and receiver.func.attr == "cursor":
            sub_recv = receiver.func.value
            if is_sqlite_connect_call(sub_recv) or (isinstance(sub_recv, ast.Name) and (sub_recv.id in sqlite_names or sub_recv.id in SQLITE_RECEIVER_NAMES)):
                return True
        if is_sqlite_connect_call(receiver):
            return True
    return False


def collect_external_helper_calls(
    root_scope: ast.AST,
    target_fn: ast.FunctionDef | ast.AsyncFunctionDef,
    enclosing_class: ast.ClassDef | None,
) -> list[ast.Call]:
    calls: list[ast.Call] = []
    name = target_fn.name

    def defines_shadow(scope: ast.AST) -> bool:
        for child in ast.iter_child_nodes(scope):
            if child is target_fn:
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name == name:
                return True
            if isinstance(child, ast.Assign):
                for tgt in child.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == name:
                        return True
        return False

    def walk_scope(node: ast.AST) -> None:
        if node is target_fn:
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not root_scope:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arg_names = {
                    a.arg
                    for a in (
                        list(getattr(node.args, "posonlyargs", ()))
                        + list(node.args.args)
                        + list(node.args.kwonlyargs)
                    )
                }
                if name in arg_names:
                    return
            if defines_shadow(node):
                return
        if isinstance(node, ast.Call):
            if enclosing_class is None:
                if isinstance(node.func, ast.Name) and node.func.id == name:
                    calls.append(node)
            else:
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == name
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in {"self", "cls", enclosing_class.name}
                ):
                    calls.append(node)
        for child in ast.iter_child_nodes(node):
            walk_scope(child)

    walk_scope(root_scope)
    return calls


def is_subprocess_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess" and node.func.attr in SUBPROCESS_ATTRS:
            return True
        if node.func.attr == "run_process":
            return True
    if isinstance(node.func, ast.Name) and node.func.id in {"run_process", "Popen", "check_output", "check_call"}:
        return True
    return False


def is_uncached_parse_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "yaml" and node.func.attr in {"safe_load", "load"}:
            return True
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "ast" and node.func.attr == "parse":
            return True
    if isinstance(node.func, ast.Name) and node.func.id == "safe_load":
        return True
    return False


def is_sleep_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute) and node.func.attr == "sleep":
        if isinstance(node.func.value, ast.Name) and node.func.value.id in {"time", "asyncio"}:
            return True
    if isinstance(node.func, ast.Name) and node.func.id == "sleep":
        return True
    return False


def is_pragma_execute_call(node: ast.AST, pattern: re.Pattern[str], sqlite_names: set[str]) -> bool:
    if not isinstance(node, ast.Call) or not is_sqlite_execute_call(node, sqlite_names):
        return False
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return bool(pattern.search(node.args[0].value))
    return False


def try_node_restores_pragma_normal(try_node: ast.Try, sqlite_names: set[str]) -> bool:
    for stmt in try_node.finalbody:
        for sub in ast.walk(stmt):
            if is_pragma_execute_call(sub, PRAGMA_SYNC_NORMAL, sqlite_names):
                return True
    return False


def is_stub_body(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and (isinstance(stmt.value.value, str) or stmt.value.value is Ellipsis):
            continue
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Raise):
            continue
        return False
    return True


def audit_python_ast(relative: str, text: str, findings: list[dict[str, Any]]) -> None:
    try:
        tree = ast.parse(text, filename=relative)
    except (SyntaxError, ValueError, RecursionError):
        return

    sqlite_names = collect_sqlite_binding_names(tree)
    reported: set[tuple[str, int]] = set()

    def add_finding(code: str, line: int, message: str) -> None:
        key = (code, line)
        if key not in reported:
            reported.add(key)
            findings.append({"code": code, "path": relative, "line": line, "message": message})

    def walk_node(
        node: ast.AST,
        in_loop: bool,
        in_while: bool,
        in_finally: bool,
        in_cleanup_fn: bool,
        active_try_stack: tuple[ast.Try, ...],
    ) -> None:
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if is_sqlite_connect_call(item.context_expr):
                    add_finding(
                        "PERF-AUDIT-SQLITE-002",
                        getattr(item.context_expr, "lineno", getattr(node, "lineno", 1)),
                        "with sqlite3.connect(...) does not close connection on exit; wrap in contextlib.closing(...)",
                    )

        if isinstance(node, ast.Call):
            line = getattr(node, "lineno", 1)
            if in_loop:
                if is_sqlite_connect_call(node) or is_sqlite_execute_call(node, sqlite_names):
                    add_finding("PERF-AUDIT-SQLITE-001", line, "N+1 SQLite query or connection inside loop or comprehension")
                if is_subprocess_call(node):
                    add_finding("PERF-AUDIT-SUBPROC-001", line, "subprocess spawn inside loop or comprehension")
                if is_uncached_parse_call(node):
                    add_finding("PERF-AUDIT-PARSE-001", line, "uncached YAML or AST parse inside loop or comprehension")
            if is_sleep_call(node) and (in_finally or (in_cleanup_fn and not in_while)):
                add_finding("PERF-AUDIT-SLEEP-001", line, "unconditional sleep in process cleanup or termination path")
            if is_pragma_execute_call(node, PRAGMA_SYNC_FULL, sqlite_names):
                if not any(try_node_restores_pragma_normal(t, sqlite_names) for t in active_try_stack):
                    add_finding(
                        "PERF-AUDIT-SQLITE-003",
                        line,
                        "PRAGMA synchronous=FULL is not restored to NORMAL in an enclosing try/finally block",
                    )

        if isinstance(node, ast.Try):
            body_try_stack = active_try_stack + (node,)
            for stmt in node.body + node.handlers + node.orelse:
                walk_node(stmt, in_loop, in_while, in_finally, in_cleanup_fn, body_try_stack)
            for stmt in node.finalbody:
                walk_node(stmt, in_loop, in_while, True, in_cleanup_fn, active_try_stack)
            return

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            clean_name = node.name.lstrip("_").lower()
            next_cleanup = any(clean_name.startswith(prefix) for prefix in CLEANUP_PREFIXES)
            for child in ast.iter_child_nodes(node):
                walk_node(child, False, False, False, next_cleanup, ())
            return

        if isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                walk_node(child, False, False, False, False, ())
            return

        next_loop = in_loop or isinstance(node, LOOP_NODES)
        next_while = in_while or isinstance(node, ast.While)
        for child in ast.iter_child_nodes(node):
            walk_node(child, next_loop, next_while, in_finally, in_cleanup_fn, active_try_stack)

    for top_child in ast.iter_child_nodes(tree):
        walk_node(top_child, False, False, False, False, ())

    scoped_functions: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.AST, ast.ClassDef | None]] = []

    def collect_functions(scope: ast.AST, lexical_root: ast.AST, enclosing_class: ast.ClassDef | None) -> None:
        for child in ast.iter_child_nodes(scope):
            if isinstance(child, ast.ClassDef):
                collect_functions(child, child, child)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scoped_functions.append((child, lexical_root, enclosing_class))
                collect_functions(child, child, None)
            else:
                collect_functions(child, lexical_root, enclosing_class)

    collect_functions(tree, tree, None)

    for node, lexical_root, enclosing_class in scoped_functions:
        if node.decorator_list or is_stub_body(node.body):
            continue
        if (node.name.startswith("__") and node.name.endswith("__")) or node.name.startswith(("visit_", "on_", "handle_")):
            continue

        body_module = ast.Module(body=node.body, type_ignores=[])
        loaded_names = {
            sub.id
            for sub in ast.walk(body_module)
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load)
        }
        if "locals" in loaded_names or "vars" in loaded_names:
            continue

        pos_args = list(getattr(node.args, "posonlyargs", ())) + list(node.args.args)
        is_method = bool(pos_args and pos_args[0].arg in {"self", "cls"})
        num_defaults = len(node.args.defaults)
        defaulted_pos: list[tuple[int, ast.arg]] = []
        if num_defaults and pos_args:
            start_idx = max(0, len(pos_args) - num_defaults)
            for idx in range(start_idx, len(pos_args)):
                defaulted_pos.append((idx - (1 if is_method else 0), pos_args[idx]))

        defaulted_kwonly: list[ast.arg] = [
            arg
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
            if default is not None
        ]

        helper_calls: list[ast.Call] = []
        if node.name.startswith("_") and not node.name.startswith("__"):
            helper_calls = collect_external_helper_calls(lexical_root, node, enclosing_class)

        for call_pos_idx, arg in defaulted_pos:
            if arg.arg.startswith("_") or arg.arg in {"self", "cls"}:
                continue
            line = getattr(arg, "lineno", getattr(node, "lineno", 1))
            if arg.arg not in loaded_names:
                add_finding("PERF-AUDIT-KWARG-001", line, f"optional parameter '{arg.arg}' in '{node.name}' is never read")
                continue
            if helper_calls:
                passed = any(
                    any(kw.arg == arg.arg or kw.arg is None for kw in call.keywords)
                    or any(isinstance(a, ast.Starred) for a in call.args)
                    or len(call.args) > call_pos_idx
                    for call in helper_calls
                )
                if not passed:
                    add_finding("PERF-AUDIT-KWARG-001", line, f"optional parameter '{arg.arg}' in internal helper '{node.name}' is never passed by callers")

        for arg in defaulted_kwonly:
            if arg.arg.startswith("_"):
                continue
            line = getattr(arg, "lineno", getattr(node, "lineno", 1))
            if arg.arg not in loaded_names:
                add_finding("PERF-AUDIT-KWARG-001", line, f"optional keyword parameter '{arg.arg}' in '{node.name}' is never read")
                continue
            if helper_calls:
                passed = any(
                    any(kw.arg == arg.arg or kw.arg is None for kw in call.keywords)
                    for call in helper_calls
                )
                if not passed:
                    add_finding("PERF-AUDIT-KWARG-001", line, f"optional keyword parameter '{arg.arg}' in internal helper '{node.name}' is never passed by callers")


def strip_rust_comments_and_strings(line: str) -> str:
    code = line.split("//", 1)[0]
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', code)


def audit_rust_source(relative: str, lines: list[str], findings: list[dict[str, Any]]) -> None:
    block_stack: list[str] = []
    pending_kind: str | None = None
    kill_group_depth: int | None = None

    for number, line in enumerate(lines, 1):
        cleaned = strip_rust_comments_and_strings(line).strip()
        if not cleaned:
            continue

        if re.search(r"\bfn\s+[A-Za-z0-9_]+", cleaned):
            pending_kind = "fn"
        elif re.search(r"\b(?:while|for|loop)\b", cleaned):
            pending_kind = "loop"
        elif re.search(r"\b(?:if|else|match)\b", cleaned):
            pending_kind = "cond"

        in_loop_or_cond = any(kind in {"loop", "cond"} for kind in block_stack) or pending_kind in {"loop", "cond"}

        if "kill_group(" in cleaned and not in_loop_or_cond and block_stack:
            kill_group_depth = len(block_stack)

        if (
            kill_group_depth is not None
            and len(block_stack) == kill_group_depth
            and not in_loop_or_cond
            and re.search(r"\b(?:std::)?thread::sleep\s*\(", cleaned)
        ):
            findings.append(
                {
                    "code": "PERF-AUDIT-SLEEP-001",
                    "path": relative,
                    "line": number,
                    "message": "unconditional thread::sleep after kill_group in process cleanup",
                }
            )

        for ch in cleaned:
            if ch == "{":
                kind = pending_kind or "block"
                if kind == "fn":
                    block_stack = ["fn"]
                    kill_group_depth = None
                else:
                    block_stack.append(kind)
                pending_kind = None
            elif ch == "}":
                if block_stack:
                    block_stack.pop()
                if kill_group_depth is not None and len(block_stack) < kill_group_depth:
                    kill_group_depth = None
        if cleaned.endswith(";"):
            pending_kind = None


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
        if "pyvenv.cfg" in filenames:
            names[:] = []
            continue
        names[:] = sorted(name for name in names if name not in AUDIT_SKIP_DIRS)
        if not include_tests:
            names[:] = [name for name in names if name not in {"test", "tests"}]
        for filename in sorted(filenames):
            path = Path(directory) / filename
            suffix = path.suffix.lower()
            if (suffix not in AUDIT_SUFFIXES and filename != ".env.example") or filename == ".env":
                continue
            if scanned >= max_files:
                exhausted = True
                break
            scanned += 1
            try:
                if path.stat().st_size > max_bytes:
                    continue
                text = path.read_text(encoding="utf-8")
                lines = text.splitlines()
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
                growing_source = re.search(r"\b(?:readFile|read_text|readText|read_to_string)\s*\(", stripped) and re.search(
                    r"(?:jsonl|(?:^|[^A-Za-z0-9_])(?:audit|log)(?:File|_file|Path|_path|Log|_log|Jsonl)|(?:Audit|Log)(?:File|Path|Jsonl)|(?:^|[^A-Za-z0-9_])event(?:Log|_log|Jsonl)|Event(?:Log|Jsonl))",
                    stripped,
                )
                if growing_source:
                    findings.append({"code": "PERF-AUDIT-IO-001", "path": relative, "line": number, "message": "probable whole-file read on a growing event or audit source"})
                if re.search(r"Promise\.all\s*\([^\n]*\.map\s*\(", stripped) and not re.search(r"\.slice\s*\(", stripped):
                    findings.append({"code": "PERF-AUDIT-CONCURRENCY-001", "path": relative, "line": number, "message": "mapped Promise.all has no visible local input bound"})
            if suffix == ".py":
                audit_python_ast(relative, text, findings)
            elif suffix == ".rs":
                audit_rust_source(relative, lines, findings)
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
