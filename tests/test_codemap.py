#!/usr/bin/env python3
"""
Automated Unit & Integration Test Suite for lazy-read (codemap.py)
Tests polyglot parsing (Python, JS/TS, C/C++, Go, Rust, Java), false-positive immunity,
3 compression modes (ultra, full, lite), symbol search, surgical slicing, and SHA-256 caching.
"""

import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT_PATH = str(pathlib.Path(__file__).resolve().parent.parent / "scripts" / "codemap.py")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import codemap  # noqa: E402


class TestCavemanReadEngine(unittest.TestCase):

    def test_01_python_ast_exact_extraction(self):
        src = '''"""Module docstring summary."""
import os
from typing import List

__all__ = ["AuthEngine", "verify_jwt"]

class AuthEngine:
    """Handles token verification."""
    def login(self, user: str, pwd: str) -> bool:
        return True

async def verify_jwt(token: str) -> dict:
    """Verify JWT signature."""
    return {"ok": True}
'''
        res = codemap.parse_python(src)
        self.assertEqual(res["doc"], "Module docstring summary.")
        self.assertIn("os", res["imports"])
        self.assertIn("typing", res["imports"])
        self.assertEqual(res["exports"], ["AuthEngine", "verify_jwt"])
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "AuthEngine")
        self.assertEqual(res["classes"][0]["line"], 7)
        self.assertEqual(res["classes"][0]["end_line"], 10)
        self.assertEqual(res["classes"][0]["methods"][0]["name"], "login")
        self.assertEqual(res["classes"][0]["methods"][0]["params"], "user,pwd")
        self.assertEqual(len(res["functions"]), 1)
        self.assertEqual(res["functions"][0]["name"], "verify_jwt")
        self.assertTrue(res["functions"][0]["async"])
        self.assertEqual(res["functions"][0]["line"], 12)
        self.assertEqual(res["functions"][0]["end_line"], 14)

    def test_01b_python_module_level_constants_and_slice(self):
        src = '''
SERVER_CONFIG = {
    "host": "0.0.0.0",
    "port": 8080,
}
BROWSER_LOGIN_LOCK: str = "lock"
MAX_CONNECTIONS = 100

def run():
    pass
'''
        res = codemap.parse_python(src)
        const_names = [c["name"] for c in res["constants"]]
        self.assertIn("SERVER_CONFIG", const_names)
        self.assertIn("BROWSER_LOGIN_LOCK", const_names)
        self.assertIn("MAX_CONNECTIONS", const_names)

        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "drill_server.py"
            f.write_text(src)
            idx = codemap.scan_repository(f, use_cache=False)
            full_map = codemap.format_caveman_index(idx, mode="full")
            self.assertIn("const:SERVER_CONFIG,BROWSER_LOGIN_LOCK,MAX_CONNECTIONS", full_map)
            sliced = codemap.slice_symbol(f, idx, "SERVER_CONFIG")
            self.assertIn("SERVER_CONFIG = {", sliced)
            self.assertIn("8080", sliced)
            inspected = codemap.inspect_batch(f, idx, ["BROWSER_LOGIN_LOCK"])
            self.assertIn("BROWSER_LOGIN_LOCK: str = \"lock\"", inspected)

    def test_02_c_pointer_functions_and_zero_false_positives(self):
        src = '''#include <stdio.h>
#include "mypyc_runtime.h"

#define MACRO_CALL(a, b) ((a) + (b))

struct BufferNode {
    int size;
    char *data;
};

/* Fake function in block comment:
   int fake_comment_fn(int x) { return x; }
*/
static inline const struct BufferNode *
alloc_buffer_node(size_t cap, const char **labels) {
    if (cap == 0) {
        return NULL;
    }
    for (int i = 0; i < 10; i++) {
        while (cap > 100) {
            printf("int fake_string_fn(int y) { return 0; }");
            cap--;
        }
    }
    return NULL;
}

char **split_tokens(const char *input, int *out_count) {
    switch (*out_count) {
        case 0: return NULL;
        default: break;
    }
    return NULL;
}
'''
        res = codemap.parse_c_cpp(src)
        cls_names = [c["name"] for c in res["classes"]]
        fn_names = [f["name"] for f in res["functions"]]
        self.assertEqual(cls_names, ["BufferNode"])
        self.assertEqual(fn_names, ["alloc_buffer_node", "split_tokens"])
        # Ensure control keywords and fake comment/string functions are NOT matched
        for forbidden in ("if", "for", "while", "switch", "printf", "fake_comment_fn", "fake_string_fn", "MACRO_CALL"):
            self.assertNotIn(forbidden, fn_names)
        # Verify exact line range for multiline pointer-returning function
        self.assertEqual(res["functions"][0]["line"], 14)
        self.assertEqual(res["functions"][0]["end_line"], 26)

    def test_03_js_ts_regex_quote_immunity_and_arrows(self):
        src = '''import { Client } from '@line/bot-sdk';
const storage = require('./storage');

export class WebhookRouter {
  async handleEvent(req, res) {
    const cleaned = req.text.replace(/"quote_in_regex"/g, '');
    if (cleaned) {
      return true;
    }
    return false;
  }
}

export const verifySignature = async (body, secret = 'default') => {
  return Boolean(body && secret);
};

export function parseCalendar(icsData) {
  return [];
}
'''
        res = codemap.parse_js_ts(src)
        self.assertIn("@line/bot-sdk", res["imports"])
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "WebhookRouter")
        self.assertEqual(res["classes"][0]["line"], 4)
        self.assertEqual(res["classes"][0]["end_line"], 12)
        self.assertEqual(res["classes"][0]["methods"][0]["name"], "handleEvent")
        fn_names = [f["name"] for f in res["functions"]]
        self.assertEqual(fn_names, ["verifySignature", "parseCalendar"])
        self.assertEqual(res["functions"][0]["params"], "body,secret")

    def test_04_go_rust_java_polyglot(self):
        go_src = '''package main
import "net/http"
type Router struct { Port int }
func (r *Router) Serve(addr string) error {
    return nil
}
'''
        go_res = codemap.parse_go_rust(go_src, "go")
        self.assertEqual(go_res["classes"][0]["name"], "Router")
        self.assertEqual(go_res["functions"][0]["name"], "Router.Serve")

        rs_src = '''use std::sync::Arc;
pub struct Vault { id: u64 }
impl Vault {
    pub async fn unlock(&self, pin: &str) -> bool {
        true
    }
}
'''
        rs_res = codemap.parse_go_rust(rs_src, "rust")
        self.assertEqual(rs_res["classes"][0]["name"], "Vault")
        self.assertEqual(rs_res["functions"][0]["name"], "unlock")

        java_src = '''package com.example;
import java.util.List;
public class OrderService {
    public boolean processOrder(String orderId, int qty) {
        if (qty <= 0) { return false; }
        return true;
    }
}
'''
        java_res = codemap.parse_jvm_csharp_swift(java_src)
        self.assertEqual(java_res["classes"][0]["name"], "OrderService")
        self.assertEqual(java_res["classes"][0]["methods"][0]["name"], "processOrder")

    def test_05_cli_map_search_slice_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "auth.py").write_text(
                "class TokenGuard:\n"
                "    def check_token(self, raw_tok: str) -> bool:\n"
                "        return len(raw_tok) > 10\n"
            )
            # 1. Test map (creates .codemap_cache.json)
            out_full = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "map", tmp, "--mode", "full"], text=True
            )
            self.assertIn("TokenGuard:1-3[check_token:2]", out_full)
            # cache must NOT pollute the scanned repo
            self.assertFalse((p / ".codemap_cache.json").exists())

            # 2. Test search
            out_search = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "search", tmp, "check_token"], text=True
            )
            self.assertIn("TokenGuard.check_token(raw_tok)", out_search)

            # 3. Test surgical slice
            out_slice = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "slice", tmp, "TokenGuard.check_token"], text=True
            )
            self.assertIn("# SLICE auth.py [TokenGuard.check_token] (L2-L3 of 3L)", out_slice)
            self.assertIn("def check_token(self, raw_tok: str) -> bool:", out_slice)

    def test_06_obfuscated_function_body_call_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            # Poorly named / obfuscated JS & Python functions whose true behavior is only in body calls
            (p / "mystery.js").write_text(
                "async function xyz_123(a, b) {\n"
                "  const lock = await callKv(['SET', a, '1', 'EX', 43200, 'NX']);\n"
                "  return axios.post('https://api.line.me/v2/bot/message/push', b);\n"
                "}\n"
            )
            (p / "mystery.py").write_text(
                "def do_stuff_99(x):\n"
                "    clean_temp_logs(max_age_hours=0)\n"
                "    return redis_client.setnx(x, 1)\n"
            )
            out_map = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "map", tmp, "--mode", "full", "--no-cache"], text=True
            )
            # Even though functions are named xyz_123 and do_stuff_99, map reveals their true body calls!
            self.assertIn("xyz_123(a,b):1-4->[callKv,axios.post]", out_map)
            self.assertIn("do_stuff_99(x):1-3->[clean_temp_logs,redis_client.setnx]", out_map)

            # And searching by internal API call ('callKv' or 'setnx') finds the obfuscated function!
            out_search = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "search", tmp, "callKv"], text=True
            )
            self.assertIn("xyz_123(a,b) ->[callKv,axios.post]", out_search)

    def test_07_autonomous_batch_inspect_and_short_file_auto_inline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "service.js").write_text(
                "function filterMeetingsByGroup(meetings, groupId) {\n"
                "  if (!groupId) return meetings;\n"
                "\n"
                "  return meetings.filter(m => m.title.includes(groupId));\n"
                "}\n"
                "\n"
                "async function xyz_lock(dateStr) {\n"
                "  const res = await callKv(['SET', dateStr, '1', 'EX', 43200, 'NX']);\n"
                "  return res !== null;\n"
                "}\n"
            )
            # 1. Autonomous shorthand: passing path + multiple queries runs 1-Shot Batch Inspect!
            # Even with fuzzy query 'filterEventsForGroup' and internal call query 'callKv',
            # it returns both exact function slices in 1 round-trip with blank lines collapsed!
            out_inspect = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, tmp, "filterEventsForGroup", "callKv"], text=True
            )
            self.assertIn("# SLICE service.js [fn filterMeetingsByGroup]", out_inspect)
            self.assertIn("return meetings.filter", out_inspect)
            self.assertIn("# SLICE service.js [fn xyz_lock]", out_inspect)
            self.assertIn("callKv(['SET'", out_inspect)

            # 2. Tiny single file (<= 40 lines) auto-inlines on `map` in 1 round-trip
            out_tiny = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "map", str(p / "service.js")], text=True
            )
            self.assertIn("# SLICE service.js (L1-L10 of 10L)", out_tiny)


    def test_08_prop_assignment_functions_and_exact_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "res.js").write_text(
                "var res = {};\n"
                "res.sendFile = function sendFile(path, options) {\n"
                "  return sendfile(this, path);\n"
                "};\n"
                "function sendfile(res, file) {\n"
                "  return file;\n"
                "}\n"
                "Foo.prototype.bar = (a, b) => {\n"
                "  return a + b;\n"
                "};\n"
            )
            info = codemap.parse_js_ts((p / "res.js").read_text())
            names = [f["name"] for f in info["functions"]]
            self.assertIn("res.sendFile", names)
            self.assertIn("sendfile", names)
            self.assertIn("Foo.prototype.bar", names)
            # Even WITHOUT --max-per-query 1, v1.4.0 Auto Case-Exact Lock drops lowercase 'sendfile'!
            out = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "inspect", tmp, "sendFile"], text=True
            )
            self.assertIn("[fn res.sendFile]", out)
            self.assertNotIn("[fn sendfile]", out)

    def test_09_lean_exclude_and_fold(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "app.js").write_text(
                "const fs = require('fs');\n"
                "function run(a) {\n  return helper(a);\n}\n"
            )
            (p / "vendor").mkdir()
            (p / "vendor" / "big.js").write_text("function huge() {\n  return 1;\n}\n")
            out = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "map", tmp, "--lean", "--exclude", "vendor"], text=True
            )
            self.assertIn("run(a)", out)
            self.assertNotIn("imp:", out)
            self.assertNotIn("->[", out)
            self.assertNotIn("vendor", out)
            body = "\n".join(f"  x{i} = {i};" for i in range(200))
            (p / "long.js").write_text("function longOne() {\n" + body + "\n}\n")
            out2 = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "inspect", tmp, "longOne", "--max-lines", "50"], text=True
            )
            self.assertIn("more lines folded", out2)

    def test_10_v140_auto_lean_and_auto_lodash_ignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            # Create 32 files so Auto-Lean (>30 files) triggers automatically without --lean
            for i in range(32):
                (p / f"mod_{i}.py").write_text(
                    "import os\n"
                    f"def fn_{i}(x):\n"
                    "    return helper_call(x)\n"
                )
            # Create a vendored lodash directory that should be ignored automatically without --exclude
            (p / "lodash").mkdir()
            (p / "lodash" / "charsEndIndex.js").write_text("function charsEndIndex() { return 0; }\n")

            out_auto = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "map", tmp], text=True
            )
            self.assertNotIn("charsEndIndex", out_auto)
            self.assertNotIn("imp:", out_auto)
            self.assertNotIn("->[", out_auto)

            # Verify --full-detail restores imp: and ->[calls] when explicitly requested
            out_detail = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "map", tmp, "--full-detail"], text=True
            )
            self.assertIn("imp:os", out_detail)
            self.assertIn("->[helper_call]", out_detail)

            # Verify Fuzzy Path Auto-Resolver when subdir/filename has a typo
            # e.g. asking for '<tmp>/scripts/mod_0_rag.py' auto-resolves to '<tmp>/mod_0.py'
            out_fuzzy_path = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "map", str(p / "scripts" / "mod_0_rag.py")], text=True
            )
            self.assertIn("# [Auto-Resolved Path]", out_fuzzy_path)
            self.assertIn("fn_0(x)", out_fuzzy_path)

    # ---- v1.6.0 debug helpers -------------------------------------------------
    def _mk_repo(self, tmp):
        p = pathlib.Path(tmp)
        (p / "pkg").mkdir()
        (p / "pkg" / "dec.py").write_text(
            'class Dec:\n'
            '    def decode(self, s):\n'
            '        """Doc line."""\n'
            '        end = len(s)\n'
            '        if end != len(s) - 1:\n'
            '            raise ValueError("Extra data")\n'
            '        return s\n'
            '\n'
            'def top(s):\n'
            '    return Dec().decode(s)\n', encoding="utf-8")
        (p / "pkg" / "__pycache__").mkdir()
        (p / "pkg" / "__pycache__" / "dec.cpython-313.pyc").write_bytes(b"Extra data\x00\x01")
        return p

    def test_11_find_text_returns_enclosing_symbol_and_skips_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._mk_repo(tmp)
            out = subprocess.check_output([sys.executable, SCRIPT_PATH, "find", tmp, "Extra data"], text=True)
            self.assertIn("[Dec.decode]", out)
            self.assertIn(">> ", out)               # hit line is marked
            self.assertIn('raise ValueError("Extra data")', out)
            self.assertNotIn(".pyc", out)
            self.assertNotIn("def top", out)        # unrelated symbol not printed
            nodoc = subprocess.check_output([sys.executable, SCRIPT_PATH, "find", tmp, "Extra data", "--no-doc"], text=True)
            self.assertNotIn("Doc line", nodoc)
            none = subprocess.check_output([sys.executable, SCRIPT_PATH, "find", tmp, "zzz-nope"], text=True)
            self.assertIn("No text match", none)
            rx = subprocess.check_output([sys.executable, SCRIPT_PATH, "find", tmp, r"Extra\s+DATA", "--regex", "-i"], text=True)
            self.assertIn("[Dec.decode]", rx)

    def test_12_trace_maps_frames_to_symbols_and_skips_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._mk_repo(tmp)
            trace = (
                'Traceback (most recent call last):\n'
                f'  File "{tmp}/pkg/dec.py", line 10, in top\n'
                '    return Dec().decode(s)\n'
                '  File "/usr/lib/python3/json/other.py", line 5, in x\n'
                f'  File "{tmp}/pkg/dec.py", line 6, in decode\n'
                '    raise ValueError("Extra data")\n'
                'ValueError: Extra data\n')
            out = subprocess.run([sys.executable, SCRIPT_PATH, "trace", tmp], input=trace,
                                 capture_output=True, text=True).stdout
            self.assertIn("[Dec.decode]", out)
            self.assertIn("[top]", out)
            self.assertIn("error: ValueError: Extra data", out)
            self.assertIn("OUTSIDE repo", out)
            self.assertIn("other.py:5", out)
            (pathlib.Path(tmp) / "pkg" / "app.js").write_text(
                "function run(x) {\n  throw new Error('boom');\n}\nmodule.exports = { run };\n", encoding="utf-8")
            node = "Error: boom\n    at run (/srv/app/pkg/app.js:2:9)\n    at Module._compile (node:internal/modules/cjs/loader:1:1)\n"
            out2 = subprocess.run([sys.executable, SCRIPT_PATH, "trace", tmp], input=node,
                                  capture_output=True, text=True).stdout
            self.assertIn("[run]", out2)     # suffix match works for foreign path roots
            empty = subprocess.run([sys.executable, SCRIPT_PATH, "trace", tmp], input="hello",
                                   capture_output=True, text=True).stdout
            self.assertIn("No stack frames", empty)

    def test_13_history_shows_last_change_of_one_symbol(self):
        import shutil
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as tmp:
            p = self._mk_repo(tmp)
            (p / "pkg" / "__pycache__" / "dec.cpython-313.pyc").unlink()
            g = ["git", "-C", tmp, "-c", "user.email=a@b", "-c", "user.name=dev"]
            subprocess.check_call(["git", "-C", tmp, "init", "-q"])
            f = p / "pkg" / "dec.py"
            src = f.read_text(encoding="utf-8")
            f.write_text(src.replace(" - 1", ""), encoding="utf-8")
            subprocess.check_call(g + ["add", "-A"]); subprocess.check_call(g + ["commit", "-qm", "good"])
            f.write_text(src, encoding="utf-8")
            subprocess.check_call(g + ["commit", "-qam", "perf: tighten check"])
            out = subprocess.check_output([sys.executable, SCRIPT_PATH, "history", tmp, "Dec.decode"], text=True)
            self.assertIn("perf: tighten check", out)
            self.assertIn("LAST CHANGE", out)
            self.assertIn("+        if end != len(s) - 1:", out)
            self.assertIn("-        if end != len(s):", out)
            nogit = tempfile.mkdtemp()
            try:
                (pathlib.Path(nogit) / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
                out2 = subprocess.check_output([sys.executable, SCRIPT_PATH, "history", nogit, "f"], text=True)
                self.assertIn("Not a git repository", out2)
            finally:
                shutil.rmtree(nogit)

    def test_14_search_miss_points_to_find(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._mk_repo(tmp)
            out = subprocess.check_output([sys.executable, SCRIPT_PATH, "search", tmp, "Extra data"], text=True)
            self.assertIn("codemap.py find", out)

    def test_15_find_code_priority_and_adaptive_broad_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "mod.py").write_text(
                'def aaa_doc_only(x):\n'
                '    """This docstring mentions raise ValueError but code does not."""\n'
                '    return x + 1\n'
                '\n'
                'def bbb_real_raise_1(x):\n'
                '    """Long docstring line 1.\n'
                '    Long docstring line 2.\n'
                '    """\n'
                '    if x < 0:\n'
                '        raise ValueError("neg 1")\n'
                '    return x\n'
                '\n'
                'def ccc_real_raise_2(x):\n'
                '    if x == 0:\n'
                '        raise ValueError("zero 2")\n'
                '    return x\n',
                encoding="utf-8",
            )
            # 3 symbols match "raise ValueError" (1 in docstring only, 2 in executable code).
            # With --max-symbols 2, the 2 real code-hit symbols must rank BEFORE aaa_doc_only!
            out = subprocess.check_output(
                [sys.executable, SCRIPT_PATH, "find", tmp, "raise ValueError", "--max-symbols", "2"],
                text=True,
            )
            self.assertIn("[bbb_real_raise_1]", out)
            self.assertIn("[ccc_real_raise_2]", out)
            self.assertNotIn("[aaa_doc_only]", out)
            # Docstrings are stripped by default in v1.7.0
            self.assertNotIn("Long docstring line 1", out)

    def test_16_trace_leaf_frame_focus_saves_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            caller_body = "\n".join(f"    step_{i} = {i}" for i in range(25))
            (p / "flow.py").write_text(
                "def caller_entry(val):\n"
                '    """Caller docstring."""\n'
                f"{caller_body}\n"
                "    return leaf_crash(val)\n"
                "\n"
                "def leaf_crash(v):\n"
                '    """Leaf docstring."""\n'
                "    clean = v.strip()\n"
                "    if not clean:\n"
                '        raise RuntimeError("empty value")\n'
                "    return clean\n",
                encoding="utf-8",
            )
            trace = (
                "Traceback (most recent call last):\n"
                f'  File "{tmp}/flow.py", line 28, in caller_entry\n'
                "    return leaf_crash(val)\n"
                f'  File "{tmp}/flow.py", line 35, in leaf_crash\n'
                '    raise RuntimeError("empty value")\n'
                "RuntimeError: empty value\n"
            )
            out_compact = subprocess.run(
                [sys.executable, SCRIPT_PATH, "trace", tmp],
                input=trace, capture_output=True, text=True,
            ).stdout
            out_full = subprocess.run(
                [sys.executable, SCRIPT_PATH, "trace", tmp, "--full-frames", "--with-doc"],
                input=trace, capture_output=True, text=True,
            ).stdout
            # Intermediate caller frame is compact (shows >> call line, omits unrelated step_N lines)
            self.assertIn("[caller_entry]", out_compact)
            self.assertIn(">>     return leaf_crash(val)", out_compact)
            self.assertNotIn("step_20", out_compact)
            # Leaf crash frame keeps full executable context
            self.assertIn("[leaf_crash]", out_compact)
            self.assertIn("clean = v.strip()", out_compact)
            self.assertLess(len(out_compact), len(out_full))


    # ---- v1.7.2: crash-frame detection per runtime, Ruby/PHP spans, caller window ----------
    def _trace(self, root, text, *extra):
        return subprocess.run([sys.executable, SCRIPT_PATH, "trace", str(root), *extra],
                              input=text, capture_output=True, text=True).stdout

    def _write(self, root, rel, body):
        f = pathlib.Path(root) / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")

    def test_17_go_trace_crash_frame_is_first_not_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "batch/batch.go",
                "package batch\n\nfunc Totals(chunks [][]int) []int {\n"
                "\tres := make([]int, len(chunks)-1)\n\tfor i, c := range chunks {\n"
                "\t\tres[i] = len(c)\n\t}\n\treturn res\n}\n")
            self._write(tmp, "main.go",
                "package main\n\nfunc run() {\n\tprintln(1)\n\tprintln(2)\n\tprintln(3)\n\tprintln(4)\n"
                "\tprintln(5)\n\tbatch.Totals(nil)\n}\n\nfunc main() {\n\trun()\n}\n")
            trace = ("panic: runtime error: index out of range [2] with length 2\n\ngoroutine 1 [running]:\n"
                     "demo/batch.Totals(...)\n\t/x/demo/batch/batch.go:6\n"
                     "main.run(...)\n\t/x/demo/main.go:9 +0x1be\n"
                     "main.main()\n\t/x/demo/main.go:14 +0x52\nexit status 2\n")
            out = self._trace(tmp, trace)
            # crashing frame (Totals, listed FIRST by Go) gets full body incl. the root-cause line
            self.assertIn("len(chunks)-1", out)
            self.assertIn("[Totals]", out)
            # outer main() is only a compact caller frame
            self.assertNotIn("println(1)", out)

    def test_18_java_trace_with_caused_by_marks_each_crash_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "com/demo/Svc.java",
                "package com.demo;\n\npublic class Svc {\n    String a(String s) {\n        String t = s.trim();\n"
                "        return t.toUpperCase();\n    }\n}\n")
            self._write(tmp, "com/demo/Main.java",
                "package com.demo;\n\npublic class Main {\n    public static void main(String[] a) {\n"
                "        int x = 1;\n        int y = 2;\n        int z = 3;\n        int w = 4;\n"
                "        new Svc().a(null);\n    }\n}\n")
            trace = ('Exception in thread "main" java.lang.IllegalStateException: boom\n'
                     "\tat com.demo.Svc.a(Svc.java:6)\n\tat com.demo.Main.main(Main.java:9)\n")
            out = self._trace(tmp, trace)
            self.assertIn("return t.toUpperCase();", out)     # innermost frame first in Java
            self.assertNotIn("int x = 1;", out)               # caller main() stays compact

    def test_19_ruby_spans_and_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "main.rb",
                "def shout(t)\n  t.upcase\nend\n\nclass Box\n  def pick(h, k)\n    v = h[k.to_sym]\n"
                "    shout(v)\n  end\nend\n\nBox.new.pick({}, 'a')\n")
            res = codemap.parse_ruby(pathlib.Path(tmp, "main.rb").read_text())
            self.assertEqual(res["functions"][0]["name"], "shout")
            self.assertEqual((res["functions"][0]["line"], res["functions"][0]["end_line"]), (1, 3))
            self.assertEqual(res["classes"][0]["name"], "Box")
            self.assertEqual(res["classes"][0]["methods"][0]["name"], "pick")
            self.assertEqual(res["classes"][0]["methods"][0]["end_line"], 9)
            trace = ("main.rb:2:in 'shout': undefined method 'upcase' for nil (NoMethodError)\n"
                     "\tfrom main.rb:8:in 'pick'\n\tfrom main.rb:12:in '<main>'\n")
            out = self._trace(tmp, trace)
            self.assertIn("[shout]", out)
            self.assertIn("[Box.pick]", out)
            self.assertIn("k.to_sym", out)                    # root cause line one above the call

    def test_20_php_methods_with_modifiers_and_hash_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "Calc.php",
                "<?php\nclass Calc {\n    public function ratio(int $a, int $b): float {\n"
                "        return intdiv($a, $b);\n    }\n}\n")
            self._write(tmp, "main.php",
                "<?php\nfunction run() {\n    $c = new Calc();\n    return $c->ratio(10, 0);\n}\necho run();\n")
            res = codemap.parse_php(pathlib.Path(tmp, "Calc.php").read_text())
            self.assertEqual(res["classes"][0]["methods"][0]["name"], "ratio")
            self.assertEqual(res["classes"][0]["methods"][0]["end_line"], 5)
            trace = ("PHP Fatal error:  Uncaught DivisionByZeroError: Division by zero in /x/Calc.php:4\n"
                     "Stack trace:\n#0 /x/Calc.php(4): intdiv()\n#1 /x/main.php(4): Calc->ratio()\n"
                     "#2 /x/main.php(6): run()\n#3 {main}\n")
            out = self._trace(tmp, trace)
            self.assertIn("[Calc.ratio]", out)
            self.assertIn("[run]", out)

    def test_21_python_exception_chain_shows_both_crash_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a.py", "def parse(x):\n    return int(x)\n")
            self._write(tmp, "b.py",
                "from a import parse\n\n\ndef load(c):\n    try:\n        return parse(c)\n"
                "    except ValueError as e:\n        raise RuntimeError('bad') from e\n")
            self._write(tmp, "main.py", "from b import load\n\nprint(load('12px'))\n")
            trace = ("Traceback (most recent call last):\n  File \"b.py\", line 6, in load\n    return parse(c)\n"
                     "  File \"a.py\", line 2, in parse\n    return int(x)\nValueError: bad literal\n\n"
                     "The above exception was the direct cause of the following exception:\n\n"
                     "Traceback (most recent call last):\n  File \"main.py\", line 3, in <module>\n"
                     "    print(load('12px'))\n  File \"b.py\", line 8, in load\n"
                     "    raise RuntimeError('bad') from e\nRuntimeError: bad\n")
            out = self._trace(tmp, trace)
            self.assertIn("[parse]", out)
            self.assertIn("return int(x)", out)               # original crash site, full context
            self.assertIn("[load]", out)

    def test_22_trace_without_repo_frames_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a.py", "def f():\n    return 1\n")
            trace = 'Traceback (most recent call last):\n  File "/usr/lib/python3/other.py", line 5, in x\nKeyError: 1\n'
            res = subprocess.run([sys.executable, SCRIPT_PATH, "trace", tmp], input=trace, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertIn("OUTSIDE repo", res.stdout)

    def test_23_caller_window_option_controls_caller_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "m.py",
                "def leaf(x):\n    return x.boom\n\n\ndef caller(v):\n    a = 1\n    b = 2\n"
                "    c = v.strip() + 'px'\n    d = 4\n    return leaf(c)\n")
            trace = ('Traceback (most recent call last):\n  File "m.py", line 10, in caller\n'
                     '    return leaf(c)\n  File "m.py", line 2, in leaf\n    return x.boom\nAttributeError: boom\n')
            narrow = self._trace(tmp, trace, "--caller-window", "0")
            wide = self._trace(tmp, trace, "--caller-window", "3")
            self.assertNotIn("+ 'px'", narrow)
            self.assertIn("+ 'px'", wide)


if __name__ == "__main__":
    unittest.main(verbosity=2)
