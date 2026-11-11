"""Static Python AST and Rust source performance hazard analyzers."""

from __future__ import annotations

import ast
import re
from typing import Any

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
NON_SQLITE_RECEIVER_NAMES = {
    "executor",
    "runner",
    "engine",
    "client",
    "session",
    "pipeline",
    "command",
    "task",
    "shell",
    "pool",
}
PRAGMA_SYNC_FULL = re.compile(r"PRAGMA\s+synchronous\s*=\s*FULL\b", re.IGNORECASE)
PRAGMA_SYNC_NORMAL = re.compile(r"PRAGMA\s+synchronous\s*=\s*NORMAL\b", re.IGNORECASE)


def is_sqlite_connect_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return bool(
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"sqlite3", "sqlite"}
    )


def collect_sqlite_binding_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                ctx = item.context_expr
                unwrapped = (
                    ctx.args[0]
                    if isinstance(ctx, ast.Call)
                    and isinstance(ctx.func, ast.Name)
                    and ctx.func.id == "closing"
                    and ctx.args
                    else ctx
                )
                if is_sqlite_connect_call(unwrapped) and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and is_sqlite_connect_call(node.value):
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
            if is_sqlite_connect_call(sub_recv) or (
                isinstance(sub_recv, ast.Name) and (sub_recv.id in sqlite_names or sub_recv.id in SQLITE_RECEIVER_NAMES)
            ):
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
            elif (
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
    return bool(isinstance(node.func, ast.Name) and node.func.id in {"run_process", "Popen", "check_output", "check_call"})


def is_uncached_parse_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "yaml" and node.func.attr in {"safe_load", "load"}:
            return True
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "ast" and node.func.attr == "parse":
            return True
    return bool(isinstance(node.func, ast.Name) and node.func.id == "safe_load")


def is_sleep_call(node: ast.Call) -> bool:
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "sleep"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"time", "asyncio"}
    ):
        return True
    return bool(isinstance(node.func, ast.Name) and node.func.id == "sleep")


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
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and (isinstance(stmt.value.value, str) or stmt.value.value is Ellipsis)
        ):
            continue
        if isinstance(stmt, (ast.Pass, ast.Raise)):
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
            if is_pragma_execute_call(node, PRAGMA_SYNC_FULL, sqlite_names) and not any(
                try_node_restores_pragma_normal(t, sqlite_names) for t in active_try_stack
            ):
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
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=False)
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
                    add_finding(
                        "PERF-AUDIT-KWARG-001",
                        line,
                        f"optional parameter '{arg.arg}' in internal helper '{node.name}' is never passed by callers",
                    )

        for arg in defaulted_kwonly:
            if arg.arg.startswith("_"):
                continue
            line = getattr(arg, "lineno", getattr(node, "lineno", 1))
            if arg.arg not in loaded_names:
                add_finding(
                    "PERF-AUDIT-KWARG-001",
                    line,
                    f"optional keyword parameter '{arg.arg}' in '{node.name}' is never read",
                )
                continue
            if helper_calls:
                passed = any(
                    any(kw.arg == arg.arg or kw.arg is None for kw in call.keywords)
                    for call in helper_calls
                )
                if not passed:
                    add_finding(
                        "PERF-AUDIT-KWARG-001",
                        line,
                        f"optional keyword parameter '{arg.arg}' in internal helper '{node.name}' is never passed by callers",
                    )


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
