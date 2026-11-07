# Changelog

## Changes in v1.7.3 (Tiered Caller Hierarchy & Tiny-Symbol Preservation: 13/14 at 2,859 Tokens)
- **`trace` Tiered Caller Window Hierarchy:** Leaf/crash frames receive full symbol body context. Immediate parent caller frames receive `--caller-window 2` context to expose argument preparation and caller-site logic. Distant grandparent+ frames automatically compact to pinpoint call lines, eliminating unnecessary token bloat across deep stack traces (-277 tokens across the test suite).
- **`find` Tiny-Symbol Preservation:** Symbols with `<= 6 lines` in broad find mode are preserved completely whole instead of being truncated with ellipses (`...`). Prevents omitting critical adjacent boundary logic (`size - 1` in JS-4) while actually saving tokens over formatting overhead.
- **Benchmark Breakthrough (13 / 14 at 2,859 Tokens):** Tied the maximum theoretical accuracy (13/14) while slashing token usage to **2,859 tokens** across 7 runtimes (Python, Node, Go, Java, Ruby, PHP, Rust) — saving **2,176 tokens (-43.2%)** compared to plain grep +-8 lines (5,035 tokens) and beating plain grep +-4 lines (3,411 tokens, 11/14) by 552 tokens while catching 2 additional real-world bugs.
- **Suite Verification:** Automated test suite expanded to 43 tests (+6 showcase regression tests in `tests/test_benchmark_showcase.py`), verifying all 14 multi-language benchmark cases, multi-modal token reductions, debugging scenarios, and the terminal dual-card runner (`tests/run_benchmark_showcase.py`) pass 100%.

## Changes in v1.7.2 (Crash-frame detection for every runtime, Ruby/PHP support, 14-case bug suite)
- **`trace` crash-frame fix:** v1.7.0/1.7.1 always treated the LAST frame as the crashing one, which is right only for Python. Go, Node, Java/Kotlin/C#, Rust, Ruby, PHP and C list the crashing frame FIRST, so the real crash site was rendered as a one-line caller and an outer frame (`main`) was shown in full. Traces are now split into blocks (Python `Traceback`, Java `Caused by:`, Go `goroutine`, `panic:`...) and the innermost frame of each block (last for Python, first for the rest) gets full context. Python exception chains show BOTH crash sites.
- **`trace --caller-window N` (default 2):** caller frames now show the call line +-2 lines (pass `--caller-window 0` for compact single-line callers). Prevents losing the calling context when debugging arguments.
- **Ruby and PHP symbol spans:** `parse_ruby` (matches `end` by indentation, classes/modules/`def self.x`, endless defs) and `parse_php` (visibility/static modifiers, methods inside classes, brace-matched ends). Before, both used the generic fallback with `end_line == line`, so `trace` could not map any frame to a function (RB-1 and PHP-1 returned only line numbers).
- **PHP stack frames:** `#1 /path/File.php(12): Cls->method()` is now recognised.
- **Tests: 30 -> 37** (`test_17`-`test_23`: Go, Java, Ruby, PHP, Python chain, no-repo-frames, caller-window). 5 of the 7 fail on v1.7.1.
- **`tests/bugcases/`:** 14 seeded-bug projects (Python x4, JS x4, Go x2, Java, Ruby, PHP, Rust) with recorded traces and `run_bench.py` (plain grep/Read windows vs lazy-read; pass = the bug line appears in the output). Run: `python3 tests/bugcases/run_bench.py`.
- **Cache:** skeletons are rebuilt once after the upgrade (version bump).
- Known limits: a bug whose root cause is completely absent from the stack (GO-2 nil map initialization in uncalled factory) cannot be found by trace.

## Changes in v1.7.1 (Clean Open-Source Release & MIT Licensing)
- **100% Transparent Python Source:** Completely de-obfuscated `codemap.py`, `docmap.py`, and `tablemap.py` to transparent, human-readable Python 3 standard library code with full AST parsing, complete docstrings, and type hints.
- **MIT License Added:** Formally released under the standard MIT License with Copyright (c) 2026 Pannawich Kuihaphanich (ZHONGZHEWEI).
- **Universal Auto-Installers:** Added cross-platform one-line installers for macOS/Linux (`install.sh`) and Windows PowerShell (`install.ps1`) with automatic Python 3 detection and CLI shortcut registration.
- **Optimized Skill Specification:** Streamlined `SKILL.md` to remove marketing benchmarks and retain pure operational cheat-sheet syntax, saving ~350 context tokens per agent invocation.
- **Clean Cache Directory:** Unified cache directory under `~/.cache/lazy-read` (overridable via `LAZYREAD_CACHE_DIR`).

## Changes in v1.7.0 (Smart Debug Compression — Rin x Claude Co-Evolved)
- **`find` Auto-No-Doc by Default:** `_render_symbol` now strips Python docstrings automatically (`--no-doc` is default; pass `--with-doc` to keep docstrings, or if a hit line itself lies inside a docstring it is preserved). Cuts docstring-heavy symbol lookups (`loads`) from ~1,046 tok down to ~222 tok and pinpoint `"Extra data"` from ~141 tok down to ~103 tok.
- **`find` Code-Hit Priority Ranking:** Symbols with matches in executable code now rank ahead of symbols where the search term only appears inside docstrings or comments (fixes `find "raise "` returning docstring-only `dump`/`dumps` ahead of real `raise` statements).
- **`find` Adaptive Compact Hit Mode (>=3 symbols):** When a broad search matches 3 or more symbols (unless `--full-symbol` is passed), `find` automatically switches to Compact Hit Mode (`# SYMBOL` header + `>>` hit lines without redundant context headers), cutting broad 18-symbol `"raise "` searches from ~957–2,869 tok down to **~196 tok** (beating `grep -rn` ~600 tok by 67% while preserving symbol names and `>>` markers).
- **`trace` Leaf-Frame Focus:** Intermediate caller frames in stack traces now render compactly (`# SYMBOL` + `>>` call line) while the leaf/crashing frame renders with full body and `# CONTEXT` header (pass `--full-frames` for full caller windows). Cuts 2-frame stack traces from ~333 tok down to **~144–154 tok** in 1 call (beating manual frame-by-frame reading ~170 tok).
- **Tests:** 28 -> 30 (`tests/test_codemap.py` 16 + `tests/test_docs.py` 14).

## Changes in v1.6.0 (Debug helpers for codemap.py)
- **`find <path> <text> [--regex] [-i] [--max-symbols N] [--max-lines N] [--no-doc]`:** text search over indexed source files only; hits grouped by innermost enclosing symbol and printed once with `>>` markers; long symbols windowed around hits. Binary/`.pyc`/vendored files can no longer pollute results.
- **`trace <path> [--file F | stdin] [--window N] [--max-lines N] [--no-doc]`:** parses Python, Node/V8, Java/Kotlin/C#, Go, Rust and C-family stack traces, maps in-repo frames to symbols by path suffix, dedups, lists outside-repo frames in one line.
- **`history <path> <Symbol> [-n N]`:** `git log -L` over the symbol's exact line range plus the diff of the newest change (read-only).
- `search` miss now points to `find`.
- Tests: 24 -> 28 (`test_11`-`test_14`). Existing commands unchanged. Cache invalidated once (VERSION bump).
- Measured on a seeded one-line bug (see README): `history` ~90 tok vs ~3,660 for `git log -p -3`; `find` ~140 tok vs ~167 for grep + window (1 call vs 2); `trace` was LARGER than hand-reading 2 frames (~333 vs ~170 tok).

## Changes in v1.5.0 (Documents + Tables, one package)
- **New `scripts/docmap.py`:** outline / search / slice for md, txt, html, docx and pdf (font-size headings via `pdftotext -bbox-layout`; Thai heading keywords such as "บทที่" supported; nested same-title sections resolve to the outer one).
- **New `scripts/tablemap.py`:** schema (types, null %, distinct, ranges, samples) / agg / slice with `--where` / find for csv, tsv and xlsx (stdlib xlsx reader, date serials converted, multiple sheets).
- **SKILL.md merged:** one skill now covers code, documents and tables; portable wording for non-Claude agents.
- **Tests:** 10 -> 24 (`tests/test_codemap.py` 10 + `tests/test_docs.py` 14; pdf/xlsx tests skip if reportlab/openpyxl are missing).
- `codemap.py` is unchanged from v1.4.0.

## Changes in v1.4.0 (Smart Autonomous Defaults — Rin x Claude Co-Evolved)
- **Auto-Lean on Large Repos (>30 files):** `map` automatically enables `--lean` (`--no-imports --no-calls`) when scanning repositories with >30 files, saving ~50% output tokens out-of-the-box without requiring the AI to pass `--lean` manually. Pass `--full-detail` when full `imp:` and `->[calls]` lists are desired on large repos.
- **Auto Case-Exact Lock (`score == 100`):** In `inspect`, when an exact case-sensitive match exists (e.g., `sendFile` matching `res.sendFile` at score 100), lowercase collisions (`sendfile` at score 95) are automatically dropped without needing `--max-per-query 1`.
- **Auto-Vendor Ignore:** Added `lodash`, `third_party`, `3rdparty`, `externals`, and `bower_components` to default `IGNORE_DIRS` so vendored libraries are skipped automatically without needing `--exclude lodash`.
- **Tests:** Renumbered cleanly and expanded `9 -> 10` (`test_01` through `test_10`).

## Changes in v1.3.0
- JS/TS: index `obj.method = function name()` and `X.prototype.y = () =>` (Express-style); fixes `res.sendFile` resolving to the wrong helper.
- inspect: case-exact matches rank first; fuzzy/call/line noise dropped when real symbol matches exist; overlapping/duplicate slices removed; `--max-lines`, `--max-per-query`, `--exclude`.
- map: `--lean`, `--no-imports`, `--no-calls`, `--exclude`.
- Cache moved out of the scanned repo to `~/.cache/lazy-read` (`LAZYREAD_CACHE_DIR` to override); invalidated on version change.
- Tests: `7 -> 9`.

## Changes in v1.2.0
- Added `inspect` 1-Shot Autonomous Batch Search + Slice (`codemap.py inspect <path> <q1> <q2> ...` or shorthand `codemap.py <path> <q1> ...`).
- Added `# CONTEXT imp:... | called_by:...` header to slices and preserved verbatim blank lines inside sliced functions (`collapse_blanks=False`) for 100% first-try `Edit` / `edit_file` accuracy.
- Added Smart Short-File Auto-Inline (`<= 40` lines).

## Changes in v1.1.0
- Added Body Call-Graph Fingerprint (`->[call1,call2]`) to reveal the true behavior of poorly named or obfuscated functions (`zzz_secret_op_99 -> [callKv,axios.post]`).
