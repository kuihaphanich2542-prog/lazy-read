#!/usr/bin/env python3
"""
lazy-read: Polyglot Codebase Skeleton Indexer & Surgical Symbol Slicer
Zero external dependencies (100% Python 3 standard library).

Reverses the paradigm from full file dumping to structured indexed slicing:
Instead of reading hundreds of full files into LLM context, generates a hyper-compact
skeleton index with exact line numbers (start-end), imports, exports, classes,
and functions, plus surgical symbol slicing.

Supported languages:
  Python (native AST), JavaScript, TypeScript, JSX/TSX, C, C++, Go, Rust,
  Java, Kotlin, C#, Swift, Ruby, PHP, Shell, SQL.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.7.2"

NOISE_CALLS = {
    "print", "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "range", "enumerate", "isinstance", "getattr", "setattr", "hasattr", "max", "min",
    "sum", "sorted", " any", "all", "super", "Exception", "ValueError", "TypeError",
    "log", " console.log", "console.warn", "console.error", "Math.max", "Math.min",
    "Math.floor", "Math.round", "String", "Number", "Boolean", "Array", "Object",
    "Promise", "Error", "parseInt", "parseFloat", "isNaN", "push", "pop", "shift",
    "slice", "splice", "join", "split", "trim", "lstrip", "rstrip", "strip",
    "lower", "upper", "toLowerCase", "toUpperCase", "includes", "startsWith",
    "endsWith", "replace", "match", "test", "some", "every", "map", "filter",
    "reduce", "forEach", "find", "indexOf", "append", "extend", "get", "items",
    "keys", "values", "splitlines", "format", "encode", "decode"
}

# Default directories and file patterns to ignore when scanning a repo
IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".env", "dist", "build", "out", "target", ".next", ".nuxt",
    ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "vendor", "third_party", "3rdparty", "externals", "bower_components",
    "lodash", "Pods", "DerivedData", "coverage", ".idea", ".vscode",
    ".gradle", "bin", "obj", ".terraform", ".serverless"
}

LANG_EXTENSIONS: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".swift": "swift",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
}

CONTROL_KEYWORDS = {
    "if", "else", "elif", "for", "while", "do", "switch", "case", "default",
    "catch", "try", "finally", "return", "sizeof", "typeof", "alignof",
    "decltype", "static_assert", "_Static_assert", "__attribute__",
    "__declspec", "synchronized", "using", "namespace", "extern", "delete",
    "new", "throw", "yield", "await", "import", "export", "require", "include"
}


# ============================================================================
# 1. COMMENT & STRING SCRUBBER (Line-Number & Brace Preserving)
# ============================================================================

def scrub_c_family(source: str) -> str:
    """
    Replaces comments (//..., /*...*/) and string/char literals ("...", '...', `...`)
    with spaces while preserving newlines (\n) and structural tokens outside strings.
    Guarantees 100% identical line numbers and accurate brace counting.
    """
    out = list(source)
    n = len(out)
    i = 0
    while i < n:
        ch = out[i]
        # Line comment //
        if ch == "/" and i + 1 < n and out[i + 1] == "/":
            out[i] = " "
            out[i + 1] = " "
            i += 2
            while i < n and out[i] != "\n":
                out[i] = " "
                i += 1
        # Block comment /* ... */
        elif ch == "/" and i + 1 < n and out[i + 1] == "*":
            out[i] = " "
            out[i + 1] = " "
            i += 2
            while i < n:
                if out[i] == "*" and i + 1 < n and out[i + 1] == "/":
                    out[i] = " "
                    out[i + 1] = " "
                    i += 2
                    break
                if out[i] != "\n":
                    out[i] = " "
                i += 1
        # String or char or template literal
        elif ch in ('"', "'", "`"):
            quote = ch
            out[i] = " "
            i += 1
            while i < n:
                c = out[i]
                if c == "\\" and i + 1 < n:
                    if out[i] != "\n":
                        out[i] = " "
                    if out[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                    continue
                if c == quote:
                    out[i] = " "
                    i += 1
                    break
                # Single/double quotes in C/JS/Go/Java cannot span unescaped newlines
                # (also protects against quotes inside JS regex literals like /"/)
                if c == "\n" and quote in ('"', "'"):
                    i += 1
                    break
                if c != "\n":
                    out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def compute_brace_depths(scrubbed_lines: List[str]) -> Tuple[List[int], List[int]]:
    """
    Returns (depth_at_line_start, depth_at_line_end) for each 0-indexed line.
    """
    start_depths: List[int] = []
    end_depths: List[int] = []
    depth = 0
    for line in scrubbed_lines:
        start_depths.append(depth)
        for ch in line:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
        end_depths.append(depth)
    return start_depths, end_depths


def find_block_end_line(
    scrubbed_lines: List[str],
    start_line_idx: int,
    start_depths: List[int],
    end_depths: List[int],
) -> int:
    """
    Given 0-indexed start_line_idx where a block declaration starts, finds the 1-indexed
    line number where its '{ ... }' block closes.
    """
    n = len(scrubbed_lines)
    base_depth = start_depths[start_line_idx]
    # Look for opening brace on start_line_idx or within next 5 lines
    open_line = -1
    for idx in range(start_line_idx, min(n, start_line_idx + 6)):
        if "{" in scrubbed_lines[idx]:
            open_line = idx
            break
        if ";" in scrubbed_lines[idx]:
            return idx + 1  # Prototype / forward declaration without body
    if open_line == -1:
        return start_line_idx + 1

    # If block opened and closed on the same line
    if end_depths[open_line] <= base_depth:
        return open_line + 1

    for idx in range(open_line + 1, n):
        if end_depths[idx] <= base_depth:
            return idx + 1
    return n


def compact_params(params: str, max_len: int = 36) -> str:
    """Compacts a parameter string for Caveman display."""
    cleaned = re.sub(r"\s+", " ", params.strip())
    if not cleaned:
        return ""
    # Strip default values like = ...
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    short_parts = []
    for p in parts:
        p = re.sub(r"\s*=.*$", "", p).strip()
        short_parts.append(p)
    joined = ",".join(short_parts)
    if len(joined) > max_len:
        return joined[: max_len - 2] + ".."
    return joined


_RE_BODY_CALL = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")


def extract_body_calls(
    scrubbed_lines: List[str],
    start_line: int,
    end_line: int,
    own_name: str = "",
    max_calls: int = 4,
) -> List[str]:
    """
    Extracts a compact Call-Graph Fingerprint of functions/APIs invoked inside
    a function body (lines start_line..end_line, 1-indexed) so even obfuscated or
    poorly named functions (e.g. xyz_123, doWork) reveal their true behavior.
    """
    calls: List[str] = []
    seen = {own_name, own_name.split(".")[-1], own_name.split("::")[-1]}
    s_idx = max(0, start_line - 1)
    e_idx = min(len(scrubbed_lines), end_line)
    for idx in range(s_idx, e_idx):
        line = scrubbed_lines[idx]
        for m in _RE_BODY_CALL.finditer(line):
            raw_call = m.group(1)
            base_call = raw_call.split(".")[-1]
            if (
                raw_call in CONTROL_KEYWORDS
                or base_call in CONTROL_KEYWORDS
                or raw_call in NOISE_CALLS
                or base_call in NOISE_CALLS
                or raw_call in seen
                or base_call in seen
            ):
                continue
            # skip line-start declaration of the function itself on first line
            if idx == s_idx and raw_call == own_name:
                continue
            seen.add(raw_call)
            calls.append(raw_call)
            if len(calls) >= max_calls:
                return calls
    return calls


# ============================================================================
# 2. PYTHON NATIVE AST PARSER (100% Exact)
# ============================================================================

def parse_python(source: str) -> Dict[str, Any]:
    lines = source.splitlines()
    result: Dict[str, Any] = {
        "lines": len(lines),
        "imports": [],
        "exports": [],
        "classes": [],
        "functions": [],
        "doc": "",
    }
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return parse_generic_fallback(source, "python")

    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        result["doc"] = mod_doc.strip().splitlines()[0][:80]

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result["imports"].append(node.module.split(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                result["exports"].append(elt.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_info = _extract_py_func(node)
            result["functions"].append(fn_info)
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(_extract_py_func(item))
            cls_doc = ast.get_docstring(node)
            bases = [ast.unparse(b) if hasattr(ast, "unparse") else "" for b in node.bases]
            result["classes"].append({
                "name": node.name,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "bases": [b for b in bases if b],
                "methods": methods,
                "doc": cls_doc.strip().splitlines()[0][:60] if cls_doc else "",
            })

    result["imports"] = sorted(set(result["imports"]))[:12]
    return result


def _extract_py_func(node: ast.AST) -> Dict[str, Any]:
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    doc = ast.get_docstring(node)
    ret = ""
    if node.returns and hasattr(ast, "unparse"):
        try:
            ret = ast.unparse(node.returns)
        except Exception:
            ret = ""
    calls: List[str] = []
    seen = {node.name}
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            cname = ""
            if isinstance(child.func, ast.Name):
                cname = child.func.id
            elif isinstance(child.func, ast.Attribute):
                if isinstance(child.func.value, ast.Name) and child.func.value.id not in ("self", "cls"):
                    cname = f"{child.func.value.id}.{child.func.attr}"
                else:
                    cname = child.func.attr
            base_c = cname.split(".")[-1]
            if (
                cname
                and cname not in CONTROL_KEYWORDS
                and base_c not in CONTROL_KEYWORDS
                and cname not in NOISE_CALLS
                and base_c not in NOISE_CALLS
                and cname not in seen
            ):
                seen.add(cname)
                calls.append(cname)
                if len(calls) >= 4:
                    break
    return {
        "name": node.name,
        "params": ",".join(args),
        "ret": ret[:24],
        "line": node.lineno,
        "end_line": getattr(node, "end_lineno", node.lineno),
        "async": isinstance(node, ast.AsyncFunctionDef),
        "calls": calls,
        "doc": doc.strip().splitlines()[0][:60] if doc else "",
    }


# ============================================================================
# 3. BRACE-AWARE POLYGLOT PARSERS (JS/TS, C/C++, Go, Rust, Java/Kotlin/C#/Swift)
# ============================================================================

def parse_js_ts(source: str) -> Dict[str, Any]:
    raw_lines = source.splitlines()
    scrubbed = scrub_c_family(source)
    s_lines = scrubbed.splitlines()
    start_d, end_d = compute_brace_depths(s_lines)

    imports: List[str] = []
    exports: List[str] = []
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    # Imports & Requires (scan raw lines for module paths)
    re_import = re.compile(r"""(?:import\s+.*?from\s+|import\s+|require\s*\(\s*)['"]([^'"]+)['"]""")
    re_export = re.compile(r"""^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)""")
    re_cjs_export = re.compile(r"""module\.exports\s*=|exports\.([A-Za-z_$][\w$]*)""")

    for rl in raw_lines:
        for m in re_import.finditer(rl):
            mod = m.group(1)
            if not mod.startswith("."):
                mod = mod.split("/")[0] if not mod.startswith("@") else "/".join(mod.split("/")[:2])
            imports.append(mod)
        m_exp = re_export.match(rl)
        if m_exp:
            exports.append(m_exp.group(1))
        for m_cjs in re_cjs_export.finditer(rl):
            if m_cjs.group(1):
                exports.append(m_cjs.group(1))

    re_class = re.compile(r"""^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(class|interface|type|enum)\s+([A-Za-z_$][\w$]*)""")
    re_func = re.compile(r"""^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(([^)]*)\)""")
    re_arrow = re.compile(r"""^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*(?::[^=]+)?=>""")
    re_method = re.compile(r"""^\s*(?:public|private|protected|static|async|readonly|get|set|\s)*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*[^{;]+)?\{""")

    # `obj.method = function name(...) {` / `Foo.prototype.bar = (...) =>` (CommonJS / Express style)
    re_prop_fn = re.compile(
        r"""^\s*([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)\s*=\s*(?:async\s+)?"""
        r"""(?:function\s*\*?\s*[A-Za-z_$][\w$]*?\s*\(([^)]*)\)|function\s*\*?\s*\(([^)]*)\)"""
        r"""|\(([^)]*)\)\s*=>|([A-Za-z_$][\w$]*)\s*=>)"""
    )

    active_class: Optional[Dict[str, Any]] = None

    for idx, s_line in enumerate(s_lines):
        depth = start_d[idx]
        line_no = idx + 1

        if active_class and line_no > active_class["end_line"]:
            active_class = None

        if depth == 0:
            m_prop = re_prop_fn.match(s_line)
            if m_prop:
                full_name = m_prop.group(1)
                params = next((g for g in m_prop.groups()[1:] if g is not None), "")
                end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                functions.append({
                    "name": full_name,
                    "params": compact_params(params),
                    "line": line_no,
                    "end_line": end_ln,
                    "calls": extract_body_calls(s_lines, line_no, end_ln, full_name.split(".")[-1]),
                })
                continue

            m_cls = re_class.match(s_line)
            if m_cls:
                kind, name = m_cls.group(1), m_cls.group(2)
                end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                cls_obj = {
                    "name": name,
                    "kind": kind,
                    "line": line_no,
                    "end_line": end_ln,
                    "methods": [],
                }
                classes.append(cls_obj)
                if kind in ("class", "interface"):
                    active_class = cls_obj
                continue

            m_fn = re_func.match(s_line)
            if m_fn:
                name, params = m_fn.group(1), m_fn.group(2)
                end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                functions.append({
                    "name": name,
                    "params": compact_params(params),
                    "line": line_no,
                    "end_line": end_ln,
                    "calls": extract_body_calls(s_lines, line_no, end_ln, name),
                })
                continue

            m_arr = re_arrow.match(s_line)
            if m_arr:
                name = m_arr.group(1)
                params = m_arr.group(2) if m_arr.group(2) is not None else (m_arr.group(3) or "")
                end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                functions.append({
                    "name": name,
                    "params": compact_params(params),
                    "line": line_no,
                    "end_line": end_ln,
                    "calls": extract_body_calls(s_lines, line_no, end_ln, name),
                })
                continue

        elif depth == 1 and active_class is not None:
            m_meth = re_method.match(s_line)
            if m_meth:
                m_name, m_params = m_meth.group(1), m_meth.group(2)
                if m_name not in CONTROL_KEYWORDS:
                    end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                    active_class["methods"].append({
                        "name": m_name,
                        "params": compact_params(m_params),
                        "line": line_no,
                        "end_line": end_ln,
                        "calls": extract_body_calls(s_lines, line_no, end_ln, m_name),
                    })

    return {
        "lines": len(raw_lines),
        "imports": sorted(set(imports))[:12],
        "exports": sorted(set(exports))[:12],
        "classes": classes,
        "functions": functions,
        "doc": "",
    }


def parse_c_cpp(source: str) -> Dict[str, Any]:
    """
    Brace-aware C / C++ parser.
    Accurately handles pointer returns (char *foo, const struct bar **baz),
    C++ qualified methods (Class::Method), macros, and avoids false positives
    inside function bodies by checking brace depth == 0 (or 1 inside class/struct/namespace).
    """
    raw_lines = source.splitlines()
    scrubbed = scrub_c_family(source)
    s_lines = scrubbed.splitlines()
    start_d, end_d = compute_brace_depths(s_lines)

    imports: List[str] = []
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    re_include = re.compile(r"""^\s*#\s*include\s*[<"]([^>"]+)[>"]""")
    for rl in raw_lines:
        m_inc = re_include.match(rl)
        if m_inc:
            imports.append(m_inc.group(1))

    re_type = re.compile(r"""^\s*(?:typedef\s+)?(struct|class|enum|union|namespace)\s+([A-Za-z_]\w*)""")
    # Function signature pattern for C/C++:
    # Matches return type (including pointers *, references &, templates <...>), function name (or Class::Name), and (...)
    re_c_func = re.compile(
        r"""^\s*(?:[A-Za-z_]\w*(?:::[\w<>]+)?[\s\*&]+)+(\*?[\s\*]*[A-Za-z_]\w*(?:::[~A-Za-z_]\w*)?)\s*\(([^;{}]*)\)"""
    )

    n = len(s_lines)
    idx = 0
    while idx < n:
        depth = start_d[idx]
        s_line = s_lines[idx]
        line_no = idx + 1

        # Skip preprocessor directives
        if s_line.lstrip().startswith("#"):
            idx += 1
            continue

        if depth <= 1:
            m_type = re_type.match(s_line)
            if m_type and ";" not in s_line:
                kind, name = m_type.group(1), m_type.group(2)
                end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                classes.append({
                    "name": name,
                    "kind": kind,
                    "line": line_no,
                    "end_line": end_ln,
                    "methods": [],
                })
                idx += 1
                continue

            # Join previous line if return type is on the line above (e.g. CPython / GNU style)
            combined = s_line
            sig_start_idx = idx
            if (
                re.match(r"^\s*\*?\s*[A-Za-z_]\w*(?:::[~A-Za-z_]\w*)?\s*\(", s_line)
                and idx > 0
                and start_d[idx - 1] == depth
            ):
                prev = s_lines[idx - 1].strip()
                if prev and not prev.startswith("#") and prev[-1] not in ";{}:,":
                    combined = prev + " " + s_line.lstrip()
                    sig_start_idx = idx - 1

            # Join up to 3 lines if signature wraps across lines before ')'
            lookahead = 0
            while "(" in combined and ")" not in combined and idx + lookahead + 1 < n and lookahead < 3:
                lookahead += 1
                combined += " " + s_lines[idx + lookahead].strip()

            # Check if this declaration is followed by '{' (function definition) vs ';' (prototype/call)
            after_paren_idx = idx + lookahead
            has_body = False
            if ")" in combined:
                tail = combined.split(")", 1)[1]
                if "{" in tail:
                    has_body = True
                elif ";" not in tail and after_paren_idx + 1 < n:
                    next_line = s_lines[after_paren_idx + 1].strip()
                    if next_line.startswith("{") or next_line.startswith(":"):
                        has_body = True

            if has_body:
                m_fn = re_c_func.match(combined)
                if m_fn:
                    raw_name = m_fn.group(1).lstrip("* \t")
                    params = m_fn.group(2)
                    base_name = raw_name.split("::")[-1]
                    if base_name not in CONTROL_KEYWORDS and not base_name.isupper():
                        end_ln = find_block_end_line(s_lines, after_paren_idx, start_d, end_d)
                        fn_start = sig_start_idx + 1
                        functions.append({
                            "name": raw_name,
                            "params": compact_params(params),
                            "line": fn_start,
                            "end_line": end_ln,
                            "calls": extract_body_calls(s_lines, fn_start, end_ln, base_name),
                        })
                        idx = max(idx + 1, end_ln)
                        continue

        idx += 1

    return {
        "lines": len(raw_lines),
        "imports": sorted(set(imports))[:12],
        "exports": [],
        "classes": classes,
        "functions": functions,
        "doc": "",
    }


def parse_go_rust(source: str, lang: str) -> Dict[str, Any]:
    raw_lines = source.splitlines()
    scrubbed = scrub_c_family(source)
    s_lines = scrubbed.splitlines()
    start_d, end_d = compute_brace_depths(s_lines)

    imports: List[str] = []
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    if lang == "go":
        re_imp = re.compile(r'"([^"]+)"')
        re_type = re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+(struct|interface)\b")
        re_fn = re.compile(r"^\s*func\s+(?:\(\s*[^)]*?([A-Za-z_]\w*)\s*\)\s*)?([A-Za-z_]\w*)\s*\(([^)]*)\)")
        for rl in raw_lines:
            if "import" in rl or rl.strip().startswith('"'):
                for m in re_imp.finditer(rl):
                    imports.append(m.group(1).split("/")[-1])
        for idx, s_line in enumerate(s_lines):
            if start_d[idx] == 0:
                m_t = re_type.match(s_line)
                if m_t:
                    end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                    classes.append({
                        "name": m_t.group(1),
                        "kind": m_t.group(2),
                        "line": idx + 1,
                        "end_line": end_ln,
                        "methods": [],
                    })
                    continue
                m_f = re_fn.match(s_line)
                if m_f:
                    recv, name, params = m_f.group(1), m_f.group(2), m_f.group(3)
                    full_name = f"{recv}.{name}" if recv else name
                    end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                    functions.append({
                        "name": full_name,
                        "params": compact_params(params),
                        "line": idx + 1,
                        "end_line": end_ln,
                        "calls": extract_body_calls(s_lines, idx + 1, end_ln, name),
                    })
    else:  # rust
        re_use = re.compile(r"^\s*(?:pub\s+)?use\s+([A-Za-z0-9_:]+)")
        re_type = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(struct|enum|trait|impl)\b(?:<[^>]*>)?\s*([A-Za-z_]\w*)")
        re_fn = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(([^)]*)\)")
        for rl in raw_lines:
            m_u = re_use.match(rl)
            if m_u:
                imports.append(m_u.group(1).split("::")[0])
        for idx, s_line in enumerate(s_lines):
            if start_d[idx] <= 1:
                m_t = re_type.match(s_line)
                if m_t and m_t.group(1) != "impl":
                    end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                    classes.append({
                        "name": m_t.group(2),
                        "kind": m_t.group(1),
                        "line": idx + 1,
                        "end_line": end_ln,
                        "methods": [],
                    })
                    continue
                m_f = re_fn.match(s_line)
                if m_f:
                    end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                    functions.append({
                        "name": m_f.group(1),
                        "params": compact_params(m_f.group(2)),
                        "line": idx + 1,
                        "end_line": end_ln,
                        "calls": extract_body_calls(s_lines, idx + 1, end_ln, m_f.group(1)),
                    })

    return {
        "lines": len(raw_lines),
        "imports": sorted(set(imports))[:12],
        "exports": [],
        "classes": classes,
        "functions": functions,
        "doc": "",
    }


def parse_jvm_csharp_swift(source: str) -> Dict[str, Any]:
    raw_lines = source.splitlines()
    scrubbed = scrub_c_family(source)
    s_lines = scrubbed.splitlines()
    start_d, end_d = compute_brace_depths(s_lines)

    imports: List[str] = []
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    re_imp = re.compile(r"^\s*(?:import|using)\s+([A-Za-z0-9_.]+)")
    re_cls = re.compile(r"^\s*(?:public|private|protected|internal|open|abstract|final|sealed|data|static|\s)*(class|interface|enum|struct|protocol|extension|object)\s+([A-Za-z_]\w*)")
    re_fn = re.compile(r"^\s*(?:public|private|protected|internal|open|override|static|final|synchronized|suspend|async|func|fun|\s)+(?:<[^>]+>\s+)?(?:[A-Za-z_][\w<>?,\[\]\s]*\s+)?([A-Za-z_]\w*)\s*\(([^)]*)\)")

    for rl in raw_lines:
        m_i = re_imp.match(rl)
        if m_i:
            imports.append(m_i.group(1).split(".")[0])

    active_class: Optional[Dict[str, Any]] = None
    for idx, s_line in enumerate(s_lines):
        depth = start_d[idx]
        line_no = idx + 1
        if active_class and line_no > active_class["end_line"]:
            active_class = None

        if depth <= 1:
            m_c = re_cls.match(s_line)
            if m_c:
                end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                cls_obj = {
                    "name": m_c.group(2),
                    "kind": m_c.group(1),
                    "line": line_no,
                    "end_line": end_ln,
                    "methods": [],
                }
                classes.append(cls_obj)
                active_class = cls_obj
                continue

            m_f = re_fn.match(s_line)
            if m_f and ("{" in s_line or (idx + 1 < len(s_lines) and "{" in s_lines[idx + 1])):
                fn_name = m_f.group(1)
                if fn_name not in CONTROL_KEYWORDS:
                    end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
                    fn_obj = {
                        "name": fn_name,
                        "params": compact_params(m_f.group(2)),
                        "line": line_no,
                        "end_line": end_ln,
                        "calls": extract_body_calls(s_lines, line_no, end_ln, fn_name),
                    }
                    if active_class is not None and depth >= 1:
                        active_class["methods"].append(fn_obj)
                    else:
                        functions.append(fn_obj)

    return {
        "lines": len(raw_lines),
        "imports": sorted(set(imports))[:12],
        "exports": [],
        "classes": classes,
        "functions": functions,
        "doc": "",
    }


def parse_ruby(source: str) -> Dict[str, Any]:
    """Ruby: classes/modules/defs with real end lines (matching `end` at the same indentation)."""
    lines = source.splitlines()
    re_cls = re.compile(r"^(\s*)(class|module)\s+([A-Z][\w:]*)")
    re_def = re.compile(r"^(\s*)def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)\s*(?:\(([^)]*)\))?(.*)$")
    re_end = re.compile(r"^(\s*)end\b")

    def block_end(idx: int, indent: int) -> int:
        for j in range(idx + 1, len(lines)):
            m = re_end.match(lines[j])
            if m and len(m.group(1)) <= indent:
                return j + 1
        return idx + 1

    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        m_c = re_cls.match(line)
        if m_c:
            classes.append({"name": m_c.group(3), "kind": m_c.group(2), "line": idx + 1,
                            "end_line": block_end(idx, len(m_c.group(1))), "methods": []})
            continue
        m_d = re_def.match(line)
        if m_d:
            indent = len(m_d.group(1))
            rest = (m_d.group(4) or "").strip()
            endless = rest.startswith("=") and not rest.startswith("==")
            end_ln = idx + 1 if endless else block_end(idx, indent)
            fn = {"name": m_d.group(2), "params": compact_params(m_d.group(3) or ""),
                  "line": idx + 1, "end_line": end_ln, "calls": []}
            owner = None
            for cl in classes:  # innermost class containing this def
                if cl["line"] < idx + 1 <= cl["end_line"] and (owner is None or cl["line"] > owner["line"]):
                    owner = cl
            (owner["methods"] if owner else functions).append(fn)
    return {"lines": len(lines), "imports": [], "exports": [], "classes": classes,
            "functions": functions, "doc": ""}


def parse_php(source: str) -> Dict[str, Any]:
    """PHP: classes/interfaces/traits and functions/methods (with visibility modifiers) with brace-matched end lines."""
    raw_lines = source.splitlines()
    s_lines = scrub_c_family(source).splitlines()
    start_d, end_d = compute_brace_depths(s_lines)
    re_cls = re.compile(r"^\s*(?:(?:abstract|final|readonly)\s+)*(class|interface|trait|enum)\s+([A-Za-z_]\w*)")
    re_fn = re.compile(r"^\s*(?:(?:public|protected|private|static|final|abstract)\s+)*function\s+&?([A-Za-z_]\w*)\s*\(([^)]*)")
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []
    for idx, s_line in enumerate(s_lines):
        m_c = re_cls.match(s_line)
        if m_c:
            classes.append({"name": m_c.group(2), "kind": m_c.group(1), "line": idx + 1,
                            "end_line": find_block_end_line(s_lines, idx, start_d, end_d), "methods": []})
            continue
        m_f = re_fn.match(s_line)
        if m_f:
            end_ln = find_block_end_line(s_lines, idx, start_d, end_d)
            fn = {"name": m_f.group(1), "params": compact_params(m_f.group(2)), "line": idx + 1,
                  "end_line": end_ln, "calls": extract_body_calls(s_lines, idx + 1, end_ln, m_f.group(1))}
            owner = None
            for cl in classes:
                if cl["line"] < idx + 1 <= cl["end_line"] and (owner is None or cl["line"] > owner["line"]):
                    owner = cl
            (owner["methods"] if owner else functions).append(fn)
    return {"lines": len(raw_lines), "imports": [], "exports": [], "classes": classes,
            "functions": functions, "doc": ""}


def parse_generic_fallback(source: str, lang: str) -> Dict[str, Any]:
    lines = source.splitlines()
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    re_cls = re.compile(r"^\s*(?:class|module|CREATE\s+TABLE)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
    re_fn = re.compile(r"^\s*(?:def|function|func|fn)\s+([A-Za-z_][\w?!]*)\s*(?:\(([^)]*)\))?")

    for idx, line in enumerate(lines):
        m_c = re_cls.match(line)
        if m_c:
            classes.append({"name": m_c.group(1), "line": idx + 1, "end_line": idx + 1, "methods": []})
            continue
        m_f = re_fn.match(line)
        if m_f:
            functions.append({
                "name": m_f.group(1),
                "params": compact_params(m_f.group(2) or ""),
                "line": idx + 1,
                "end_line": idx + 1,
            })

    return {
        "lines": len(lines),
        "imports": [],
        "exports": [],
        "classes": classes,
        "functions": functions,
        "doc": "",
    }


def parse_file(file_path: Path, lang: str) -> Optional[Dict[str, Any]]:
    try:
        raw_bytes = file_path.read_bytes()
        if b"\x00" in raw_bytes[:4096]:
            return None  # Skip binary files
        source = raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None

    if lang == "python":
        data = parse_python(source)
    elif lang in ("javascript", "typescript"):
        data = parse_js_ts(source)
    elif lang in ("c", "cpp"):
        data = parse_c_cpp(source)
    elif lang in ("go", "rust"):
        data = parse_go_rust(source, lang)
    elif lang in ("java", "kotlin", "csharp", "swift"):
        data = parse_jvm_csharp_swift(source)
    elif lang == "ruby":
        data = parse_ruby(source)
    elif lang == "php":
        data = parse_php(source)
    else:
        data = parse_generic_fallback(source, lang)

    data["lang"] = lang
    data["bytes"] = len(raw_bytes)
    data["sha256"] = hashlib.sha256(raw_bytes).hexdigest()[:16]
    return data


# ============================================================================
# 4. REPOSITORY SCANNER WITH SHA-256 INCREMENTAL CACHE
# ============================================================================

def _cache_path(root_path: Path) -> Path:
    """Cache lives OUTSIDE the scanned repo (never pollutes the user's tree)."""
    base = Path(os.environ.get("LAZYREAD_CACHE_DIR") or os.environ.get("CODEMAP_CACHE_DIR") or (Path.home() / ".cache" / "lazy-read"))
    return base / (hashlib.sha1(str(root_path).encode("utf-8")).hexdigest()[:16] + ".json")


def _is_excluded(rel_path: str, patterns: List[str]) -> bool:
    import fnmatch
    parts = rel_path.split("/")
    for pat in patterns:
        p = pat.strip("/")
        if fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(rel_path, p + "/*") or fnmatch.fnmatch(rel_path, "*/" + p + "/*"):
            return True
        if any(fnmatch.fnmatch(seg, p) for seg in parts):
            return True
    return False


def scan_repository(
    root_path: Path, use_cache: bool = True, excludes: Optional[List[str]] = None
) -> Dict[str, Dict[str, Any]]:
    root_path = root_path.resolve()
    excludes = excludes or []
    if root_path.is_file():
        ext = root_path.suffix.lower()
        lang = LANG_EXTENSIONS.get(ext, "generic")
        parsed = parse_file(root_path, lang)
        return {root_path.name: parsed} if parsed else {}

    cache_file = _cache_path(root_path)
    cache_data: Dict[str, Any] = {}
    if use_cache and cache_file.exists():
        try:
            cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
            if cache_data.get("version") != VERSION:
                cache_data = {}  # parser changed -> invalidate stale skeletons
        except Exception:
            cache_data = {}

    old_files = cache_data.get("files", {})
    new_files: Dict[str, Dict[str, Any]] = {}
    cache_updated = False

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune ignored directories in-place
        dirnames[:] = sorted([
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".")
        ])
        for fname in sorted(filenames):
            ext = Path(fname).suffix.lower()
            if ext not in LANG_EXTENSIONS:
                continue
            fpath = Path(dirpath) / fname
            rel_path = fpath.relative_to(root_path).as_posix()
            if excludes and _is_excluded(rel_path, excludes):
                continue
            try:
                st = fpath.stat()
            except OSError:
                continue

            # Skip huge minified/generated files (> 1 MB)
            if st.st_size > 1_000_000 or fname.endswith(".min.js") or fname.endswith(".bundle.js"):
                continue

            cached = old_files.get(rel_path)
            if (
                cached
                and cached.get("mtime") == int(st.st_mtime)
                and cached.get("bytes") == st.st_size
            ):
                new_files[rel_path] = cached
                continue

            parsed = parse_file(fpath, LANG_EXTENSIONS[ext])
            if parsed:
                parsed["mtime"] = int(st.st_mtime)
                new_files[rel_path] = parsed
                cache_updated = True

    if use_cache and cache_updated:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            keep = new_files if not excludes else {**old_files, **new_files}
            cache_file.write_text(
                json.dumps({"version": VERSION, "files": keep}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    return new_files


# ============================================================================
# 5. CAVEMAN FORMATTERS (ULTRA / FULL / LITE)
# ============================================================================

def format_caveman_index(
    index: Dict[str, Dict[str, Any]], mode: str = "full",
    show_imports: bool = True, show_calls: bool = True,
) -> str:
    out_lines: List[str] = []
    total_raw_bytes = sum(v.get("bytes", 0) for v in index.values())
    total_lines = sum(v.get("lines", 0) for v in index.values())

    if mode == "ultra":
        # Group by directory for ultra-compact architectural overview
        dir_groups: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        for rel_path, info in index.items():
            parent = str(Path(rel_path).parent)
            dir_groups.setdefault(parent, []).append((Path(rel_path).name, info))

        out_lines.append(f"# LAZY-READ [ULTRA] | {len(index)} files | {total_lines} lines")
        for d, items in sorted(dir_groups.items()):
            d_lines = sum(i[1]["lines"] for i in items)
            file_summaries = []
            for fname, info in items:
                n_cls = len(info.get("classes", []))
                n_fn = len(info.get("functions", []))
                tag = f"{fname}({info['lines']}L"
                if n_cls:
                    tag += f",{n_cls}c"
                if n_fn:
                    tag += f",{n_fn}f"
                tag += ")"
                file_summaries.append(tag)
            out_lines.append(f"dir {d}/ [{len(items)}f, {d_lines}L]: " + ", ".join(file_summaries))

    elif mode == "full":
        out_lines.append(f"# LAZY-READ [FULL] | {len(index)} files | {total_lines}L")
        for rel_path, info in sorted(index.items()):
            segs = [f"{rel_path} [{info['lines']}L]"]
            if info.get("imports") and show_imports:
                segs.append("imp:" + ",".join(info["imports"][:6]))
            if info.get("exports"):
                segs.append("exp:" + ",".join(info["exports"][:6]))

            cls_strs = []
            for c in info.get("classes", []):
                rng = f"{c['line']}-{c['end_line']}" if c.get("end_line", c["line"]) != c["line"] else f"{c['line']}"
                m_list = c.get("methods", [])
                if m_list:
                    m_names = ",".join(f"{m['name']}:{m['line']}" for m in m_list[:6])
                    if len(m_list) > 6:
                        m_names += f",+{len(m_list)-6}"
                    cls_strs.append(f"{c['name']}:{rng}[{m_names}]")
                else:
                    cls_strs.append(f"{c['name']}:{rng}")
            if cls_strs:
                segs.append("cls:" + " ".join(cls_strs))

            fn_strs = []
            for f in info.get("functions", []):
                rng = f"{f['line']}-{f['end_line']}" if f.get("end_line", f["line"]) != f["line"] else f"{f['line']}"
                c_tag = f"->[{','.join(f['calls'][:3])}]" if (f.get("calls") and show_calls) else ""
                fn_strs.append(f"{f['name']}({f.get('params','')}):{rng}{c_tag}")
            if fn_strs:
                segs.append("fn:" + " ".join(fn_strs[:10]))
                if len(fn_strs) > 10:
                    segs[-1] += f" +{len(fn_strs)-10}more"

            out_lines.append(" | ".join(segs))

    else:  # lite (detailed signatures + docstrings + call fingerprints)
        out_lines.append(f"# LAZY-READ [LITE] | {len(index)} files | {total_lines}L")
        for rel_path, info in sorted(index.items()):
            hdr = f"## {rel_path} ({info['lines']}L, {info['lang']})"
            if info.get("doc"):
                hdr += f" — {info['doc']}"
            out_lines.append(hdr)
            if info.get("imports") and show_imports:
                out_lines.append("  imp: " + ", ".join(info["imports"]))
            for c in info.get("classes", []):
                out_lines.append(f"  cls {c['name']} (L{c['line']}-{c.get('end_line', c['line'])})")
                for m in c.get("methods", []):
                    m_calls = f" -> [{', '.join(m['calls'])}]" if (m.get("calls") and show_calls) else ""
                    out_lines.append(
                        f"    .{m['name']}({m.get('params','')}) L{m['line']}-{m.get('end_line', m['line'])}{m_calls}"
                    )
            for f in info.get("functions", []):
                f_calls = f" -> [{', '.join(f['calls'])}]" if (f.get("calls") and show_calls) else ""
                doc_str = f" // {f['doc']}" if f.get("doc") else ""
                out_lines.append(
                    f"  fn {f['name']}({f.get('params','')}) L{f['line']}-{f.get('end_line', f['line'])}{f_calls}{doc_str}"
                )

    output_text = "\n".join(out_lines)
    raw_tokens = max(1, total_raw_bytes // 4)
    out_tokens = max(1, len(output_text.encode("utf-8")) // 4)
    saved_pct = max(0.0, (1.0 - (out_tokens / raw_tokens)) * 100.0)
    stats_line = (
        f"\n# [Stats] Raw: ~{raw_tokens:,} tok -> lazy-read: ~{out_tokens:,} tok "
        f"(Saved {saved_pct:.1f}%)"
    )
    return output_text + stats_line


# ============================================================================
# 6. SURGICAL SYMBOL SEARCH & SLICE EXTRACTOR
# ============================================================================

def search_symbols(index: Dict[str, Dict[str, Any]], query: str) -> str:
    q = query.lower()
    hits: List[str] = []
    for rel_path, info in sorted(index.items()):
        if q in rel_path.lower():
            hits.append(f"file  {rel_path} [{info['lines']}L]")
        for c in info.get("classes", []):
            if q in c["name"].lower():
                hits.append(f"cls   {rel_path}:{c['line']}-{c.get('end_line', c['line'])}  {c['name']}")
            for m in c.get("methods", []):
                m_calls = m.get("calls", [])
                calls_str = f" ->[{','.join(m_calls)}]" if m_calls else ""
                if (
                    q in m["name"].lower()
                    or q in f"{c['name']}.{m['name']}".lower()
                    or any(q in call.lower() for call in m_calls)
                ):
                    hits.append(
                        f"meth  {rel_path}:{m['line']}-{m.get('end_line', m['line'])}  {c['name']}.{m['name']}({m.get('params','')}){calls_str}"
                    )
        for f in info.get("functions", []):
            f_calls = f.get("calls", [])
            calls_str = f" ->[{','.join(f_calls)}]" if f_calls else ""
            if q in f["name"].lower() or any(q in call.lower() for call in f_calls):
                hits.append(
                    f"fn    {rel_path}:{f['line']}-{f.get('end_line', f['line'])}  {f['name']}({f.get('params','')}){calls_str}"
                )
    if not hits:
        return f"No symbol matching '{query}'. (For text such as error messages use: codemap.py find <path> '<text>')"
    return f"# Search '{query}' ({len(hits)} hits):\n" + "\n".join(hits[:50])


def slice_symbol(root_path: Path, index: Dict[str, Dict[str, Any]], target: str) -> str:
    """
    Extracts exact source lines for a symbol name (e.g., 'checkAndMarkDailyBroadcast'
    or 'AuthManager.login') or 'file.py:10-40'.
    """
    root_path = root_path.resolve()

    # Case 1: Explicit file:start-end
    m_range = re.match(r"^(.+?):(\d+)(?:-(\d+))?$", target)
    if m_range:
        rel_f, s_ln = m_range.group(1), int(m_range.group(2))
        e_ln = int(m_range.group(3)) if m_range.group(3) else s_ln + 30
        fpath = root_path if root_path.is_file() else (root_path / rel_f)
        if not fpath.exists():
            return f"File not found: {rel_f}"
        return _read_line_slice(fpath, rel_f, s_ln, e_ln)

    # Case 2: Symbol lookup across index
    q = target.lower()
    matches: List[Tuple[str, str, int, int]] = []
    for rel_path, info in sorted(index.items()):
        for c in info.get("classes", []):
            if c["name"].lower() == q:
                matches.append((rel_path, f"class {c['name']}", c["line"], c.get("end_line", c["line"])))
            for m in c.get("methods", []):
                full_m = f"{c['name']}.{m['name']}".lower()
                if m["name"].lower() == q or full_m == q:
                    matches.append((rel_path, f"{c['name']}.{m['name']}", m["line"], m.get("end_line", m["line"])))
        for f in info.get("functions", []):
            if f["name"].lower() == q:
                matches.append((rel_path, f"fn {f['name']}", f["line"], f.get("end_line", f["line"])))

    if not matches:
        return search_symbols(index, target)

    blocks = []
    for rel_path, sym_label, s_ln, e_ln in matches[:5]:
        fpath = root_path if root_path.is_file() else (root_path / rel_path)
        sym_clean = sym_label.split()[-1]
        ctx_hdr = _build_context_header(index, rel_path, sym_clean)
        blocks.append(_read_line_slice(fpath, f"{rel_path} [{sym_label}]", s_ln, e_ln, context_hdr=ctx_hdr))
    return "\n\n".join(blocks)


def _find_callers(index: Dict[str, Dict[str, Any]], sym_name: str) -> List[str]:
    base = sym_name.split(".")[-1].split("::")[-1].lower()
    if not base or len(base) < 3:
        return []
    callers: List[str] = []
    for rel_path, info in sorted(index.items()):
        for c in info.get("classes", []):
            for m in c.get("methods", []):
                if any(base == call.split(".")[-1].lower() for call in m.get("calls", [])):
                    callers.append(f"{rel_path}:{c['name']}.{m['name']}(L{m['line']})")
        for f in info.get("functions", []):
            if f["name"].lower() != base and any(base == call.split(".")[-1].lower() for call in f.get("calls", [])):
                callers.append(f"{rel_path}:{f['name']}(L{f['line']})")
    return callers[:6]


def _build_context_header(index: Dict[str, Dict[str, Any]], rel_path: str, sym_name: str) -> str:
    info = index.get(rel_path, {})
    parts = []
    if info.get("imports"):
        parts.append("imp:" + ",".join(info["imports"][:8]))
    callers = _find_callers(index, sym_name)
    if callers:
        parts.append("called_by:" + ",".join(callers))
    return f"# CONTEXT {' | '.join(parts)}\n" if parts else ""


def _read_line_slice(
    fpath: Path,
    label: str,
    start_line: int,
    end_line: int,
    collapse_blanks: bool = False,
    context_hdr: str = "",
) -> str:
    try:
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"Error reading {fpath}: {e}"
    s = max(1, start_line)
    e = min(len(lines), max(s, end_line))
    numbered = []
    for ln in range(s, e + 1):
        txt = lines[ln - 1]
        if collapse_blanks and not txt.strip():
            continue
        numbered.append(f"{ln:4d} | {txt}")
    return f"# SLICE {label} (L{s}-L{e} of {len(lines)}L)\n{context_hdr}" + "\n".join(numbered)


def _split_camel_snake(s: str) -> List[str]:
    """Splits camelCase or snake_case into lowercase tokens >= 3 chars."""
    s_spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    parts = re.split(r"[^A-Za-z0-9]+", s_spaced.lower())
    stop = {"the", "and", "for", "with", "from", "get", "set", "check"}
    return [p for p in parts if len(p) >= 3 and p not in stop]


def inspect_batch(
    root_path: Path, index: Dict[str, Dict[str, Any]], queries: List[str],
    max_lines: int = 120, max_per_query: int = 2,
) -> str:
    """
    Autonomous 1-Shot Batch Inspector:
    Accepts 1 or more queries (function names, fuzzy names like 'filterEventsForGroup',
    body calls like 'callKv', or raw code keywords like 'SET NX').
    Automatically locates matching functions/lines and returns their exact code slices
    in a single round-trip without losing comments or logic.
    """
    root_path = root_path.resolve()
    out_blocks: List[str] = []
    seen_slices = set()

    for raw_q in queries:
        q = raw_q.strip()
        if not q:
            continue
        q_low = q.lower()
        q_tokens = _split_camel_snake(q)
        matched_items: List[Tuple[int, str, str, int, int, Optional[int]]] = []

        for rel_path, info in sorted(index.items()):
            all_syms = []
            for c in info.get("classes", []):
                all_syms.append((f"class {c['name']}", c["name"], [], c["line"], c.get("end_line", c["line"])))
                for m in c.get("methods", []):
                    all_syms.append((
                        f"{c['name']}.{m['name']}",
                        f"{c['name']}.{m['name']}",
                        m.get("calls", []),
                        m["line"],
                        m.get("end_line", m["line"]),
                    ))
            for f in info.get("functions", []):
                all_syms.append((
                    f"fn {f['name']}",
                    f["name"],
                    f.get("calls", []),
                    f["line"],
                    f.get("end_line", f["line"]),
                ))

            for label, name, calls, s_ln, e_ln in all_syms:
                name_low = name.lower()
                calls_low = " ".join(calls).lower()
                score = 0
                if name == q or name.split(".")[-1] == q:
                    score = 100
                elif name_low == q_low or name_low.split(".")[-1] == q_low:
                    score = 95
                elif q_low in name_low:
                    score = 80
                elif any(q_low in c.lower() for c in calls):
                    score = 75
                elif len(q_tokens) >= 2:
                    sym_tokens = set(_split_camel_snake(name) + _split_camel_snake(calls_low))
                    overlap = sum(1 for t in q_tokens if any(t in st or st in t for st in sym_tokens))
                    if overlap >= max(1, len(q_tokens) - 1):
                        score = 50 + overlap * 10

                if score > 0:
                    matched_items.append((score, rel_path, label, s_ln, e_ln, None))

            # Fallback: scan raw lines in file if no high-confidence symbol match yet
            fpath = root_path if root_path.is_file() else (root_path / rel_path)
            if fpath.exists():
                try:
                    flines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                    for idx, fline in enumerate(flines):
                        fl_low = fline.lower()
                        if q_low in fl_low or (len(q_tokens) >= 2 and all(t in fl_low for t in q_tokens)):
                            hit_ln = idx + 1
                            # Find enclosing function if any
                            enc = None
                            for label, _nm, _cl, s_ln, e_ln in all_syms:
                                if s_ln <= hit_ln <= e_ln:
                                    enc = (65, rel_path, label, s_ln, e_ln, hit_ln)
                                    break
                            if enc:
                                matched_items.append(enc)
                            else:
                                matched_items.append((
                                    55,
                                    rel_path,
                                    f"line-match '{q}'",
                                    max(1, hit_ln - 8),
                                    min(len(flines), hit_ln + 12),
                                    hit_ln,
                                ))
                            break
                except Exception:
                    pass

        matched_items.sort(key=lambda x: (-x[0], x[1], x[3]))
        if not matched_items:
            out_blocks.append(f"# Inspect '{q}': No match found.")
            continue

        # Precision filter:
        # 1) When a Case-Exact symbol match (score == 100, e.g. 'sendFile' -> 'res.sendFile') exists,
        #    automatically lock to score == 100 so lowercase collisions ('sendfile', score 95) are dropped
        #    without needing --max-per-query 1.
        # 2) Otherwise, when real symbol matches (score >= 80) exist, drop fuzzy/call/line noise.
        if matched_items[0][0] == 100:
            matched_items = [m for m in matched_items if m[0] == 100]
        elif matched_items[0][0] >= 80:
            matched_items = [m for m in matched_items if m[0] >= 80]

        count_for_q = 0
        for score, rel_path, label, s_ln, e_ln, hit_ln in matched_items:
            key = (rel_path, s_ln, e_ln)
            if key in seen_slices:
                continue
            if any(r == rel_path and not (e_ln < a or s_ln > b) for (r, a, b) in seen_slices):
                continue  # overlaps a slice already emitted
            seen_slices.add(key)
            fpath = root_path if root_path.is_file() else (root_path / rel_path)
            sym_clean = label.split()[-1]
            ctx_hdr = _build_context_header(index, rel_path, sym_clean)
            # Safety rule: functions <= 60 lines are returned in full (100% lossless).
            # Giant functions (> 60 lines) with a specific hit_ln show header (3 lines) + ±15 lines around hit_ln.
            if (e_ln - s_ln) > 60 and hit_ln is not None:
                hdr_slice = _read_line_slice(fpath, f"{rel_path} [{label} HEADER]", s_ln, s_ln + 3, context_hdr=ctx_hdr)
                win_s = max(s_ln + 4, hit_ln - 15)
                win_e = min(e_ln, hit_ln + 15)
                win_slice = _read_line_slice(fpath, f"{rel_path} [{label} WINDOW L{win_s}-L{win_e}]", win_s, win_e)
                out_blocks.append(hdr_slice + f"\n  ... [L{s_ln+4}-L{win_s-1} folded] ...\n" + win_slice)
            elif max_lines and (e_ln - s_ln + 1) > max_lines:
                cut = s_ln + max_lines - 1
                body = _read_line_slice(fpath, f"{rel_path} [{label} L{s_ln}-L{cut} of L{e_ln}]", s_ln, cut, context_hdr=ctx_hdr)
                out_blocks.append(body + f"\n  ... [{e_ln - cut} more lines folded; use: slice {rel_path}:{cut + 1}-{e_ln}] ...")
            else:
                out_blocks.append(_read_line_slice(fpath, f"{rel_path} [{label}]", s_ln, e_ln, context_hdr=ctx_hdr))
            count_for_q += 1
            if count_for_q >= max_per_query:
                break

    return "\n\n".join(out_blocks)


# ============================================================================
# 7. v1.6.0 DEBUG HELPERS: find (text -> enclosing symbol), trace, history
# ============================================================================

def _symbol_spans(info: Dict[str, Any]) -> List[Tuple[int, int, str]]:
    """All (start, end, label) spans in a file, methods/functions and classes."""
    spans: List[Tuple[int, int, str]] = []
    for c in info.get("classes", []):
        spans.append((c["line"], c.get("end_line", c["line"]), c["name"]))
        for m in c.get("methods", []):
            spans.append((m["line"], m.get("end_line", m["line"]), f"{c['name']}.{m['name']}"))
    for f in info.get("functions", []):
        spans.append((f["line"], f.get("end_line", f["line"]), f["name"]))
    return spans


def _enclosing_symbol(info: Dict[str, Any], line_no: int) -> Optional[Tuple[int, int, str]]:
    """Innermost (smallest) symbol span containing line_no, or None."""
    best: Optional[Tuple[int, int, str]] = None
    for s, e, label in _symbol_spans(info):
        if s <= line_no <= e and (best is None or (e - s) < (best[1] - best[0])):
            best = (s, e, label)
    return best


def _docstring_lines(lines: List[str], s: int, e: int) -> set:
    """Line numbers of the docstring directly under a Python def/class starting at line s."""
    for ln in range(s, min(e, s + 8) + 1):
        if lines[ln - 1].rstrip().endswith(":"):
            nxt = ln + 1
            while nxt <= e and not lines[nxt - 1].strip():
                nxt += 1
            if nxt > e:
                return set()
            first = lines[nxt - 1].strip()
            q = first[:3]
            if q not in ('"""', "'''"):
                return set()
            if first.count(q) >= 2 and len(first) > 3:
                return {nxt}
            end = nxt + 1
            while end <= e and q not in lines[end - 1]:
                end += 1
            return set(range(nxt, min(end, e) + 1))
    return set()


def _render_symbol(
    root_path: Path, index: Dict[str, Dict[str, Any]], rel_path: str,
    span: Tuple[int, int, str], hit_lines: List[int], max_lines: int,
    window: int = 12, no_doc: bool = True, show_context: bool = True,
) -> str:
    """Slice a symbol, marking hit lines with '>>'. Long symbols are windowed around the hits."""
    fpath = root_path if root_path.is_file() else (root_path / rel_path)
    try:
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:  # pragma: no cover
        return f"Error reading {fpath}: {e}"
    s, e, label = span
    doc_lns = _docstring_lines(lines, s, e) if str(fpath).endswith((".py", ".pyi")) else set()
    keep = set(range(s, e + 1))
    if no_doc and doc_lns:
        keep -= (doc_lns - set(hit_lines))
    folded = False
    if (max_lines and len(keep) > max_lines) or not show_context:
        keep = {s} if show_context else set()
        for h in hit_lines:
            keep.update(range(max(s, h - window), min(e, h + window) + 1))
            if window == 0 and h < e and lines[h - 1].rstrip().endswith((",", "(")):
                keep.add(h + 1)
        if no_doc and doc_lns:
            keep -= (doc_lns - set(hit_lines))
        folded = True
    hits = set(hit_lines)
    out: List[str] = []
    prev = None
    for ln in sorted(keep):
        if prev is not None and ln != prev + 1:
            out.append("     | ...")
        txt = lines[ln - 1]
        out.append(f"{ln:4d}>> {txt}" if ln in hits else f"{ln:4d} | {txt}")
        prev = ln
    body = "\n".join(out)
    sym_clean = label.split(".")[-1]
    ctx = _build_context_header(index, rel_path, sym_clean) if show_context else ""
    note = f" folded around hits (symbol is {e - s + 1}L)" if (folded and show_context) else ""
    return f"# SYMBOL {rel_path} [{label}] (L{s}-L{e}){note}\n{ctx}{body}"


def find_text(
    root_path: Path, index: Dict[str, Dict[str, Any]], needle: str,
    regex: bool = False, ignore_case: bool = False, max_symbols: int = 6,
    max_lines: int = 25, no_doc: bool = True, full_symbol: bool = False,
) -> str:
    """Text/regex search over INDEXED SOURCE FILES ONLY (no .pyc/binary/vendor noise).
    Hits are grouped by innermost enclosing symbol, ranked with executable code hits first,
    and automatically windowed in Compact Hit Mode when >= 3 symbols match."""
    flags = re.I if ignore_case else 0
    pat = re.compile(needle if regex else re.escape(needle), flags)
    groups: Dict[Tuple[str, Tuple[int, int, str]], List[int]] = {}
    code_hits_map: Dict[Tuple[str, Tuple[int, int, str]], List[int]] = {}
    loose: List[Tuple[str, int, str]] = []
    total = 0
    for rel_path, info in sorted(index.items()):
        fpath = root_path if root_path.is_file() else (root_path / rel_path)
        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        is_py = str(fpath).endswith((".py", ".pyi"))
        doc_cache: Dict[Tuple[int, int], set] = {}
        for i, txt in enumerate(lines, 1):
            if pat.search(txt):
                total += 1
                sp = _enclosing_symbol(info, i)
                if sp:
                    key = (rel_path, sp)
                    groups.setdefault(key, []).append(i)
                    s, e, _ = sp
                    if is_py:
                        if (s, e) not in doc_cache:
                            doc_cache[(s, e)] = _docstring_lines(lines, s, e)
                        in_doc = i in doc_cache[(s, e)]
                    else:
                        in_doc = False
                    stripped = txt.lstrip()
                    is_comment = stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*")
                    if not in_doc and not is_comment:
                        code_hits_map.setdefault(key, []).append(i)
                else:
                    loose.append((rel_path, i, txt.strip()))
    if not total:
        return f"No text match for {needle!r} in indexed source files."

    # Rank symbols with executable code hits ahead of docstring/comment-only matches
    ordered_items = list(groups.items())
    ordered_items.sort(key=lambda item: (0 if item[0] in code_hits_map else 1))

    broad_mode = (len(ordered_items) >= 3) and not full_symbol
    eff_max_lines = min(max_lines, 3) if (broad_mode and max_lines) else (0 if full_symbol else max_lines)
    eff_window = 0 if broad_mode else 5
    show_ctx = not broad_mode

    out = [f"# FIND {needle!r}: {total} hit(s) in {len(groups)} symbol(s)"
           + (f" + {len(loose)} outside any symbol" if loose else "")]
    for key, all_hl in ordered_items[:max_symbols]:
        rel_path, sp = key
        hl = code_hits_map.get(key, all_hl)
        if broad_mode and len(hl) > 2:
            hl = hl[:2]
        out.append(_render_symbol(
            root_path, index, rel_path, sp, hl, eff_max_lines,
            window=eff_window, no_doc=no_doc, show_context=show_ctx,
        ))
    if len(ordered_items) > max_symbols:
        rest = [f"{p}:{s[2]}" for (p, s), _ in ordered_items[max_symbols:]]
        more_sfx = f" (+{len(rest) - 6} more)" if len(rest) > 6 else ""
        out.append("# MORE symbols (raise --max-symbols): " + ", ".join(rest[:6]) + more_sfx)
    if not broad_mode or not ordered_items:
        for rel_path, i, txt in loose[:8]:
            out.append(f"# LOOSE {rel_path}:{i}: {txt[:140]}")
    return "\n\n".join(out)


_TRACE_PATTERNS = [
    # Python:  File "/a/b.py", line 12, in func
    re.compile(r'File "(?P<f>[^"]+)", line (?P<l>\d+)'),
    # Node/V8:  at fn (/a/b.js:12:5)   |  at /a/b.js:12:5
    re.compile(r'\bat (?:.+? \()?(?P<f>[^\s()]+?\.(?:[cm]?[jt]sx?)):(?P<l>\d+)(?::\d+)?\)?'),
    # Java/Kotlin/C#: at pkg.Cls.m(File.java:12)
    re.compile(r'\bat [\w$.<>]+\((?P<f>[\w$.-]+\.(?:java|kt|cs|scala)):(?P<l>\d+)\)'),
    # Go:  /a/b.go:12 +0x1f
    re.compile(r'(?P<f>[^\s:]+\.go):(?P<l>\d+)'),
    # Rust / generic:  at src/main.rs:12:5  |  --> src/main.rs:12:5
    re.compile(r'(?:-->|\bat)\s+(?P<f>[^\s:]+\.rs):(?P<l>\d+)'),
    # C/C++/PHP/Ruby: file.ext:LINE
    re.compile(r'(?P<f>[^\s:()]+\.(?:c|h|cc|cpp|hpp|php|rb)):(?P<l>\d+)'),
    # PHP stack trace:  #1 /a/b.php(12): Cls->method()
    re.compile(r'^#\d+\s+(?P<f>[^\s()]+\.php)\((?P<l>\d+)\)'),
]


def _match_repo_file(index: Dict[str, Dict[str, Any]], raw: str) -> Optional[str]:
    """Match a path from a trace to an indexed file by longest common path suffix."""
    raw = raw.replace("\\", "/")
    parts = [p for p in raw.split("/") if p and p != "."]
    best, best_n = None, 0
    for rel in index:
        rparts = rel.split("/")
        n = 0
        while n < min(len(rparts), len(parts)) and rparts[-1 - n] == parts[-1 - n]:
            n += 1
        if n > best_n:
            best, best_n = rel, n
    return best if best_n >= 1 else None


_BLOCK_START = re.compile(
    r"^\s*(Traceback \(most recent call last\)|Caused by:|Exception in thread|goroutine \d+|panic:|thread '.*' panicked)")


def _split_trace_blocks(text: str) -> List[Tuple[bool, List[Tuple[str, int]]]]:
    """Split a trace into blocks (one per Python Traceback / Java 'Caused by' / Go goroutine ...).
    Returns [(python_style, [(path, line), ...]), ...]. python_style=True means innermost frame is LAST
    ('most recent call last'); every other runtime lists the innermost frame FIRST."""
    py_global = "most recent call last" in text
    blocks: List[Tuple[bool, List[Tuple[str, int]]]] = []
    cur: Optional[Tuple[bool, List[Tuple[str, int]]]] = None
    for ln in text.splitlines():
        m_b = _BLOCK_START.match(ln)
        if m_b:
            is_py = m_b.group(1).startswith("Traceback")
            if cur is None or cur[1]:
                cur = (is_py, [])
                blocks.append(cur)
            else:
                cur = (is_py, cur[1])
                blocks[-1] = cur
            continue
        for pat in _TRACE_PATTERNS:
            m = pat.search(ln)
            if m:
                if cur is None:
                    cur = (py_global, [])
                    blocks.append(cur)
                cur[1].append((m.group("f"), int(m.group("l"))))
                break
    return blocks


def trace_frames(
    root_path: Path, index: Dict[str, Dict[str, Any]], text: str,
    max_lines: int = 40, no_doc: bool = True, window: int = 4, full_frames: bool = False,
    caller_window: int = 2,
) -> str:
    """Parse a stack trace; print the enclosing symbol of every in-repo frame (deduplicated),
    failing lines marked '>>'. The crashing (innermost) frame of each trace block is rendered with full
    context; caller frames are rendered compactly (signature + failing line +- caller_window lines).
    Innermost = last frame for Python, first frame for Node/Java/Go/Rust/Ruby/PHP/C. Frames outside the
    repo are listed in one line."""
    blocks = _split_trace_blocks(text)
    n_frames = sum(len(b[1]) for b in blocks)
    err = ""
    for ln in reversed(text.strip().splitlines()):
        if re.match(r"^\s*[\w.]+(Error|Exception|Warning|Exit|Interrupt)\b|^\s*(panic|Uncaught|Caused by|thread .* panicked)", ln):
            err = ln.strip()
            break
    if not n_frames:
        return "No stack frames recognized in input (supported: Python, Node/V8, Java/Kotlin/C#, Go, Rust, C/C++/PHP/Ruby)."
    grouped: Dict[Tuple[str, Tuple[int, int, str]], List[int]] = {}
    order: List[Tuple[str, Tuple[int, int, str]]] = []
    leaf_keys = set()
    loose: List[str] = []
    external: List[str] = []
    for is_py, frames in blocks:
        block_keys: List[Tuple[str, Tuple[int, int, str]]] = []
        for raw, line_no in frames:
            rel = _match_repo_file(index, raw)
            if not rel:
                external.append(f"{Path(raw).name}:{line_no}")
                continue
            sp = _enclosing_symbol(index[rel], line_no)
            if not sp:
                loose.append(f"{rel}:{line_no}")
                continue
            key = (rel, sp)
            block_keys.append(key)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            if line_no not in grouped[key]:
                grouped[key].append(line_no)
        if block_keys:
            leaf_keys.add(block_keys[-1] if is_py else block_keys[0])
    out = [f"# TRACE {n_frames} frame(s): {len(order)} symbol(s) in repo"
           + (f" | error: {err[:160]}" if err else "")]
    for key in order:
        is_leaf = key in leaf_keys or full_frames
        out.append(_render_symbol(
            root_path, index, key[0], key[1], grouped[key],
            max_lines if is_leaf else 2,
            window=window if is_leaf else caller_window, no_doc=no_doc, show_context=is_leaf,
        ))
    if loose:
        out.append("# MODULE-LEVEL frames: " + ", ".join(dict.fromkeys(loose)))
    if external:
        uniq = list(dict.fromkeys(external))
        out.append(f"# OUTSIDE repo (skipped, {len(uniq)}): " + ", ".join(uniq[:8]))
    return "\n\n".join(out)


def symbol_history(
    root_path: Path, index: Dict[str, Dict[str, Any]], target: str, limit: int = 5,
) -> str:
    """Recent git history of ONE symbol's exact line range (git log -L) + who last touched each line.
    Read-only (git log / git blame). Answers 'what changed here recently?'."""
    import subprocess
    root = (root_path if root_path.is_dir() else root_path.parent).resolve()
    if subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                      capture_output=True, text=True).returncode != 0:
        return "Not a git repository: history unavailable."
    q = target.lower()
    found: List[Tuple[str, int, int, str]] = []
    for rel_path, info in sorted(index.items()):
        for s, e, label in _symbol_spans(info):
            if label.lower() == q or label.lower().endswith("." + q):
                found.append((rel_path, s, e, label))
    if not found:
        return f"Symbol {target!r} not found. Try `find` or `search`."
    out: List[str] = []
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    for rel_path, s, e, label in found[:2]:
        abs_f = (root / rel_path) if not root_path.is_file() else root_path
        try:
            git_rel = abs_f.resolve().relative_to(Path(top).resolve()).as_posix()
        except Exception:
            git_rel = rel_path
        log = subprocess.run(
            ["git", "-C", top, "log", f"-{limit}", "-s", "--date=short",
             "--format=%h %ad %an: %s", "-L", f"{s},{e}:{git_rel}"],
            capture_output=True, text=True)
        out.append(f"# HISTORY {rel_path} [{label}] (L{s}-L{e}) last {limit} commit(s) touching these lines")
        commits = [ln for ln in log.stdout.splitlines() if ln.strip()]
        out.append("\n".join(commits) if commits else "(no commits: file untracked or uncommitted)")
        if commits:
            diff = subprocess.run(
                ["git", "-C", top, "log", "-1", "--format=# LAST CHANGE %h %ad %an", "--date=short",
                 "-L", f"{s},{e}:{git_rel}"], capture_output=True, text=True).stdout.splitlines()
            keep = [ln for ln in diff if ln.startswith(("# LAST", "+", "-", "@@")) and not ln.startswith(("+++", "---"))]
            out.append("\n".join(keep[:30]))
    return "\n".join(out)


def _resolve_fuzzy_path(missing_path: Path) -> Optional[Path]:
    """
    If a user or AI passes a slightly wrong/moved file path (e.g.,
    '/repo/scripts/brain3_rag_server.py' when the real file is '/repo/brain3_server.py'),
    walks up to 3 parent levels to find the existing repo root and fuzzy-matches
    the filename by token overlap and extension in < 20ms.
    """
    want_name = missing_path.name.lower()
    want_ext = missing_path.suffix.lower()
    want_tokens = [t for t in re.split(r"[^a-z0-9]+", missing_path.stem.lower()) if t]
    if not want_tokens:
        return None

    parent = missing_path.parent
    for _ in range(3):
        if parent.exists() and parent.is_dir():
            break
        parent = parent.parent
    if not parent.exists() or not parent.is_dir() or parent == Path("/"):
        return None

    best_score = 0
    best_path: Optional[Path] = None
    for dirpath, dirnames, filenames in os.walk(parent):
        dirnames[:] = sorted([d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")])
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            if want_ext and fpath.suffix.lower() != want_ext:
                continue
            fn_low = fname.lower()
            if fn_low == want_name:
                return fpath
            cand_tokens = [t for t in re.split(r"[^a-z0-9]+", fpath.stem.lower()) if t]
            overlap = sum(1 for t in want_tokens if t in cand_tokens or any(len(t) >= 3 and (t in ct or ct in t) for ct in cand_tokens))
            if overlap >= max(1, len(want_tokens) - 1):
                score = overlap * 20 - len(cand_tokens)
                if score > best_score:
                    best_score = score
                    best_path = fpath
    return best_path


# ============================================================================
# 7. CLI ENTRYPOINT (With Autonomous Routing & Fuzzy Path Auto-Resolver)
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="lazy-read: Polyglot CodeMap Skeleton Indexer & Surgical Symbol Slicer"
    )
    sub = parser.add_subparsers(dest="cmd")

    p_map = sub.add_parser("map", help="Generate skeleton index (auto-inlines tiny <=40L single files)")
    p_map.add_argument("path", nargs="?", default=".", help="Target repository or file path")
    p_map.add_argument("--mode", choices=["ultra", "full", "lite"], default="full")
    p_map.add_argument("--no-cache", action="store_true", help="Disable the on-disk skeleton cache")
    p_map.add_argument("--no-imports", action="store_true", help="Omit imp: lists (~40%% smaller on JS repos)")
    p_map.add_argument("--no-calls", action="store_true", help="Omit ->[calls] fingerprints (~12%% smaller)")
    p_map.add_argument("--lean", action="store_true", help="Shortcut for --no-imports --no-calls (auto-enabled on >30 files)")
    p_map.add_argument("--full-detail", action="store_true", help="Force showing imp: and ->[calls] even on repos >30 files")
    p_map.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                       help="Skip dirs/files (repeatable), e.g. --exclude lodash --exclude 'vendor' --exclude '*.test.js'")

    p_inspect = sub.add_parser("inspect", help="1-Shot Autonomous Batch Search + Slice for 1 or more queries")
    p_inspect.add_argument("path", help="Target repository or file path")
    p_inspect.add_argument("queries", nargs="+", help="1 or more symbol names, fuzzy queries, or keywords")
    p_inspect.add_argument("--max-lines", type=int, default=120, help="Fold slices longer than N lines (0 = unlimited)")
    p_inspect.add_argument("--max-per-query", type=int, default=2, help="Max slices returned per query")
    p_inspect.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="Skip dirs/files (repeatable)")

    p_search = sub.add_parser("search", help="Search symbols and body call fingerprints across repository")
    p_search.add_argument("path", help="Target repository path")
    p_search.add_argument("query", help="Symbol or call substring to match")

    p_slice = sub.add_parser("slice", help="Surgically slice exact lines of a symbol or file:start-end")
    p_slice.add_argument("path", help="Target repository or file path")
    p_slice.add_argument("target", help="Symbol name (e.g. myFunc, Class.method) or file:start-end")

    p_find = sub.add_parser("find", help="Text/regex search in source files -> prints the ENCLOSING symbol (hits marked >>)")
    p_find.add_argument("path", help="Target repository or file path")
    p_find.add_argument("text", help="Text (or regex with --regex), e.g. an error message")
    p_find.add_argument("--regex", action="store_true")
    p_find.add_argument("-i", "--ignore-case", action="store_true")
    p_find.add_argument("--max-symbols", type=int, default=6)
    p_find.add_argument("--max-lines", type=int, default=25, help="Window long symbols around hits (0 = unlimited)")
    p_find.add_argument("--no-doc", action="store_true", default=True, help="Drop Python docstrings from output (default in v1.7.0)")
    p_find.add_argument("--with-doc", action="store_true", help="Include Python docstrings in output")
    p_find.add_argument("--full-symbol", action="store_true", help="Render full symbols even when >=3 symbols match")
    p_find.add_argument("--exclude", action="append", default=[], metavar="GLOB")

    p_trace = sub.add_parser("trace", help="Paste a stack trace (stdin or --file): prints every in-repo frame's symbol")
    p_trace.add_argument("path", help="Target repository path")
    p_trace.add_argument("--file", help="Read the trace from this file instead of stdin")
    p_trace.add_argument("--max-lines", type=int, default=40, help="Window leaf symbol longer than N lines around failing line (0 = unlimited)")
    p_trace.add_argument("--window", type=int, default=4, help="Lines of context each side of a failing line in long leaf symbols")
    p_trace.add_argument("--no-doc", action="store_true", default=True, help="Drop Python docstrings (default in v1.7.0)")
    p_trace.add_argument("--with-doc", action="store_true", help="Include Python docstrings in output")
    p_trace.add_argument("--caller-window", type=int, default=2, help="Lines of context each side of the call line in caller (non-crashing) frames")
    p_trace.add_argument("--full-frames", action="store_true", help="Render full window for intermediate caller frames too")
    p_trace.add_argument("--exclude", action="append", default=[], metavar="GLOB")

    p_hist = sub.add_parser("history", help="git history + blame of one symbol's exact lines (what changed recently?)")
    p_hist.add_argument("path", help="Target repository path")
    p_hist.add_argument("symbol", help="Symbol name, e.g. decode or JSONDecoder.decode")
    p_hist.add_argument("-n", "--limit", type=int, default=5)

    # Autonomous CLI routing:
    # - `codemap.py /path` -> `map /path`
    # - `codemap.py /path q1 q2 ...` -> `inspect /path q1 q2 ...`
    known_cmds = {"map", "inspect", "search", "slice", "find", "trace", "history", "-h", "--help"}
    if len(sys.argv) > 1 and sys.argv[1] not in known_cmds:
        non_flag_args = [a for a in sys.argv[1:] if not a.startswith("-")]
        if len(non_flag_args) >= 2:
            sys.argv.insert(1, "inspect")
        else:
            sys.argv.insert(1, "map")

    args = parser.parse_args()
    cmd = args.cmd or "map"
    raw_target = Path(getattr(args, "path", ".")).expanduser()
    target_path = raw_target.resolve()
    if not target_path.exists():
        resolved = _resolve_fuzzy_path(target_path)
        if resolved is not None:
            print(f"# [Auto-Resolved Path] '{raw_target}' -> '{resolved}'")
            target_path = resolved.resolve()
        else:
            print(f"Error: path not found: {target_path}", file=sys.stderr)
            return 1

    use_cache = not getattr(args, "no_cache", False)
    index = scan_repository(target_path, use_cache=use_cache, excludes=getattr(args, "exclude", []))

    if cmd == "map":
        # Smart Short-File Auto-Inline: if mapping a single file <= 40 lines, inline it in 1 shot
        if target_path.is_file() and len(index) == 1:
            only_info = next(iter(index.values()))
            if only_info.get("lines", 999) <= 40:
                print(format_caveman_index(index, mode="full"))
                print(_read_line_slice(target_path, target_path.name, 1, only_info["lines"]))
                return 0
        auto_lean = len(index) > 30 and not getattr(args, "full_detail", False)
        lean = args.lean or auto_lean
        print(format_caveman_index(
            index, mode=args.mode,
            show_imports=not (args.no_imports or lean),
            show_calls=not (args.no_calls or lean),
        ))
    elif cmd == "inspect":
        print(inspect_batch(target_path, index, args.queries,
                            max_lines=args.max_lines, max_per_query=args.max_per_query))
    elif cmd == "search":
        print(search_symbols(index, args.query))
    elif cmd == "slice":
        print(slice_symbol(target_path, index, args.target))
    elif cmd == "find":
        use_no_doc = not getattr(args, "with_doc", False)
        print(find_text(target_path, index, args.text, regex=args.regex, ignore_case=args.ignore_case,
                        max_symbols=args.max_symbols, max_lines=args.max_lines, no_doc=use_no_doc,
                        full_symbol=getattr(args, "full_symbol", False)))
    elif cmd == "trace":
        use_no_doc = not getattr(args, "with_doc", False)
        data = Path(args.file).read_text(encoding="utf-8", errors="replace") if args.file else sys.stdin.read()
        print(trace_frames(target_path, index, data, max_lines=args.max_lines, no_doc=use_no_doc,
                           window=args.window, full_frames=getattr(args, "full_frames", False),
                           caller_window=args.caller_window))
    elif cmd == "history":
        print(symbol_history(target_path, index, args.symbol, limit=args.limit))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
