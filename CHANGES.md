# Changelog

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
