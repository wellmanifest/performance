#!/usr/bin/env python3
"""Offline Performance v1 conformance and reversible local adoption."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import performance_ast as _ast_mod
    import performance_plan as _plan_mod
except ModuleNotFoundError:
    _SRC_DIR = str(Path(__file__).resolve().parent)
    if _SRC_DIR not in sys.path:
        sys.path.insert(0, _SRC_DIR)
    import performance_ast as _ast_mod
    import performance_plan as _plan_mod

CLEANUP_PREFIXES = _ast_mod.CLEANUP_PREFIXES
LOOP_NODES = _ast_mod.LOOP_NODES
NON_SQLITE_RECEIVER_NAMES = _ast_mod.NON_SQLITE_RECEIVER_NAMES
PRAGMA_SYNC_FULL = _ast_mod.PRAGMA_SYNC_FULL
PRAGMA_SYNC_NORMAL = _ast_mod.PRAGMA_SYNC_NORMAL
SQLITE_RECEIVER_NAMES = _ast_mod.SQLITE_RECEIVER_NAMES
SUBPROCESS_ATTRS = _ast_mod.SUBPROCESS_ATTRS
audit_python_ast = _ast_mod.audit_python_ast
audit_rust_source = _ast_mod.audit_rust_source
collect_external_helper_calls = _ast_mod.collect_external_helper_calls
collect_sqlite_binding_names = _ast_mod.collect_sqlite_binding_names
is_pragma_execute_call = _ast_mod.is_pragma_execute_call
is_sleep_call = _ast_mod.is_sleep_call
is_sqlite_connect_call = _ast_mod.is_sqlite_connect_call
is_sqlite_execute_call = _ast_mod.is_sqlite_execute_call
is_stub_body = _ast_mod.is_stub_body
is_subprocess_call = _ast_mod.is_subprocess_call
is_uncached_parse_call = _ast_mod.is_uncached_parse_call
strip_rust_comments_and_strings = _ast_mod.strip_rust_comments_and_strings
try_node_restores_pragma_normal = _ast_mod.try_node_restores_pragma_normal

CONTROL_KINDS = _plan_mod.CONTROL_KINDS
CONTROL_UNITS = _plan_mod.CONTROL_UNITS
DuplicateKey = _plan_mod.DuplicateKey
IDENTIFIER = _plan_mod.IDENTIFIER
INVARIANT_KINDS = _plan_mod.INVARIANT_KINDS
InvalidJsonNumber = _plan_mod.InvalidJsonNumber
METRIC_NAME = _plan_mod.METRIC_NAME
OUTCOMES = _plan_mod.OUTCOMES
PROFILE_CONTROLS = _plan_mod.PROFILE_CONTROLS
PROFILE_VALUES = _plan_mod.PROFILE_VALUES
REPOSITORY = _plan_mod.REPOSITORY
SECRET_QUERY = _plan_mod.SECRET_QUERY
SHA40 = _plan_mod.SHA40
SHA64 = _plan_mod.SHA64
SHELL_TEXT = _plan_mod.SHELL_TEXT
TOP_KEYS = _plan_mod.TOP_KEYS
UNITS = _plan_mod.UNITS
UNSAFE_PATH = _plan_mod.UNSAFE_PATH
exact_object = _plan_mod.exact_object
finding = _plan_mod.finding
finite_json_float = _plan_mod.finite_json_float
finite_number = _plan_mod.finite_number
load_plan = _plan_mod.load_plan
metric_map = _plan_mod.metric_map
reject_symlink_path = _plan_mod.reject_symlink_path
strict_pairs = _plan_mod.strict_pairs
valid_evidence = _plan_mod.valid_evidence
validate_plan = _plan_mod.validate_plan

BEGIN = "# BEGIN wellmanifest/performance v1"
END = "# END wellmanifest/performance v1"
PATTERNS = (
    "/.code2llm_cache/", "/.coverage", "/.deployments/", "/.mypy_cache/",
    "/.nox/", "/.planfile/events/", "/.planfile/evidence/", "/.planfile/index/",
    "/.pytest_cache/", "/.ruff_cache/", "/.tox/", "/.venv/", "/.worktrees/",
    "**/__pycache__/", "coverage/", "dist/", "htmlcov/", "node_modules/", "venv/",
)
AUDIT_SUFFIXES = {".cjs", ".js", ".mjs", ".py", ".rs", ".ts", ".yaml", ".yml"}
AUDIT_SKIP_DIRS = {
    ".code2llm_cache", ".deployments", ".git", ".governance", ".koru",
    ".mypy_cache", ".nox", ".planfile", ".pytest_cache", ".ruff_cache",
    ".secrets", ".subactor", ".tox", ".venv", ".worktrees", "__pycache__",
    "_bundled", "build", "code2llm_output", "coverage", "dist", "htmlcov",
    "koru-audits", "koru-worktrees", "node_modules", "preserved-worktrees",
    "site-packages", "target", "vendor", "venv",
}


def audit_repository(
    root: Path,
    *,
    max_files: int = 5000,
    max_bytes: int = 1_048_576,
    include_tests: bool = False,
) -> list[dict[str, Any]]:
    if type(max_files) is not int or type(max_bytes) is not int or max_files < 1 or max_bytes < 1:
        raise ValueError("audit_bounds_invalid")
    reject_symlink_path(root)
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
            if path.is_symlink():
                continue
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
                            findings.append(
                                {
                                    "code": "PERF-AUDIT-HEALTH-001",
                                    "path": relative,
                                    "line": number,
                                    "message": "healthcheck cadence below 15 seconds needs detection-tier evidence",
                                }
                            )
                    if "test:" in stripped and re.search(
                        r'["\'](?:node|python\d*|php)["\']\s*,\s*["\'](?:-e|-c|-r)["\']', stripped
                    ):
                        findings.append(
                            {
                                "code": "PERF-AUDIT-HEALTH-002",
                                "path": relative,
                                "line": number,
                                "message": "healthcheck starts an interpreter for each probe",
                            }
                        )
                growing_source = re.search(r"\b(?:readFile|read_text|readText|read_to_string)\s*\(", stripped) and re.search(
                    r"(?:jsonl|(?:^|[^A-Za-z0-9_])(?:audit|log)(?:File|_file|Path|_path|Log|_log|Jsonl)|(?:Audit|Log)(?:File|Path|Jsonl)|(?:^|[^A-Za-z0-9_])event(?:Log|_log|Jsonl)|Event(?:Log|Jsonl))",
                    stripped,
                )
                if growing_source:
                    findings.append(
                        {
                            "code": "PERF-AUDIT-IO-001",
                            "path": relative,
                            "line": number,
                            "message": "probable whole-file read on a growing event or audit source",
                        }
                    )
                if re.search(r"Promise\.all\s*\([^\n]*\.map\s*\(", stripped) and not re.search(r"\.slice\s*\(", stripped):
                    findings.append(
                        {
                            "code": "PERF-AUDIT-CONCURRENCY-001",
                            "path": relative,
                            "line": number,
                            "message": "mapped Promise.all has no visible local input bound",
                        }
                    )
            if suffix == ".py":
                audit_python_ast(relative, text, findings)
            elif suffix == ".rs":
                audit_rust_source(relative, lines, findings)
            if exhausted:
                break
        if exhausted:
            break
    if health_default and health_default[2] < 15_000:
        findings.append(
            {
                "code": "PERF-AUDIT-HEALTH-001",
                "path": health_default[0],
                "line": health_default[1],
                "message": "default healthcheck cadence below 15 seconds needs detection-tier evidence",
            }
        )
        if shared_health_refs > 1:
            findings.append(
                {
                    "code": "PERF-AUDIT-HEALTH-003",
                    "path": health_default[0],
                    "line": health_default[1],
                    "message": f"one fast healthcheck default fans out to {shared_health_refs} services",
                }
            )
    if exhausted:
        findings.append({"code": "PERF-AUDIT-LIMIT-001", "path": ".", "line": 0, "message": "repository audit reached its file limit"})
    return sorted(findings, key=lambda item: (item["code"], item["path"], item["line"]))


def parse_inventory(path: Path) -> list[str]:
    reject_symlink_path(path)
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
    if dot_git.is_symlink() or not dot_git.is_dir():
        return None
    info_dir = dot_git / "info"
    if info_dir.is_symlink():
        return None
    exclude_file = info_dir / "exclude"
    if exclude_file.is_symlink():
        return None
    return exclude_file


def _has_symlink_git_exclude(repository: Path) -> bool:
    dot_git = repository / ".git"
    info_dir = dot_git / "info"
    exclude_file = info_dir / "exclude"
    return dot_git.is_symlink() or info_dir.is_symlink() or exclude_file.is_symlink()


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
    reject_symlink_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_path(path)
    descriptor, temporary = tempfile.mkstemp(prefix="performance-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def local_adoption(workspace: Path, inventory: Path, apply: bool, remove: bool) -> dict[str, Any]:
    reject_symlink_path(workspace)
    resolved_workspace = workspace.resolve()
    entries: list[dict[str, str]] = []
    for name in parse_inventory(inventory):
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            entries.append({"repository": name, "status": "unsafe-path"})
            continue
        candidate = workspace / name
        if candidate.is_symlink():
            entries.append({"repository": name, "status": "unsafe-path"})
            continue
        repository = candidate.resolve()
        if repository.parent != resolved_workspace or repository.name != name or _has_symlink_git_exclude(repository):
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
        "workspace": str(resolved_workspace),
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
            print(
                json.dumps(
                    {"schema": "performance.audit-report/v1", "root": str(args.root.resolve()), "ok": not findings, "findings": findings},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 1 if findings else 0
        result = local_adoption(args.workspace, args.manifest, args.command == "adopt-local", args.remove)
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.receipt:
            atomic_write(args.receipt, encoded)
        print(encoded, end="")
        bad = {"unsafe-path", "missing-or-noncanonical", "malformed-managed-block", "needs-update"}
        return 1 if any(item["status"] in bad for item in result["repositories"]) else 0
    except (UnicodeError, json.JSONDecodeError, DuplicateKey, InvalidJsonNumber) as error:
        print(
            json.dumps(
                {"schema": "performance.report/v1", "ok": False, "findings": [{"code": "PERF-JSON-001", "path": "$", "message": type(error).__name__}]},
                sort_keys=True,
            )
        )
        return 1
    except (OSError, TypeError, ValueError) as error:
        print(json.dumps({"schema": "performance.report/v1", "ok": False, "internalError": type(error).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
