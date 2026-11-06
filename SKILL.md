---
name: lazy-read
description: "Cut input tokens when exploring or reading large inputs. Code repos: skeleton map + surgical symbol slices. Long documents (md, txt, html, docx, pdf): outline then read one section. Tables (csv, xlsx): schema and aggregates instead of rows. Use before reading any big file."
---

# Lazy-Read (v1.7.0) — Read the Map First, Then Slice

Instead of loading whole files, read a compact index first, then pull only the exact lines, section or rows needed. Three read-only helpers, Python 3 standard library only, no network, nothing is modified:

| Input | Script | Index | Slice |
|---|---|---|---|
| Code (py, js/ts, c/c++, go, rust, java, kotlin, c#, swift, ruby, php, sh, sql) | `scripts/codemap.py` | `map` | `inspect` / `slice` / `search` / `find` / `trace` / `history` |
| Documents (md, txt, html, docx, pdf*) | `scripts/docmap.py` | `outline` | `slice` / `search` |
| Tables (csv, tsv, xlsx) | `scripts/tablemap.py` | `schema` | `agg` / `slice` / `find` |

`SKILL_DIR` = the folder containing this file. *PDF needs `pdftotext` (poppler). If scripts or Python are unavailable, fall back to your normal file tools with line/page/row limits (grep, head, offset/limit). Files under ~40 lines (code) or ~2k tokens (docs/tables): just read them.

---

## A. Code repositories (`codemap.py`)

1. **Unknown large repo → `ultra` first, then scope:**
   `python3 "$SKILL_DIR/scripts/codemap.py" map <repo> --mode ultra`
   Pick the relevant folders. (`node_modules`, `vendor`, `lodash`, `third_party`, `dist` are skipped automatically.)
2. **Map the relevant folder** (auto-lean when >30 files; `--full-detail` restores imports and call lists):
   `codemap.py map <repo>/src/feature --mode full`
3. **Fetch code with one batched `inspect`, not full-file reads:**
   `codemap.py inspect <repo> "res.sendFile" "parseQuery"`
   - Exact/qualified names (`res.sendFile`, `Class.method`) rank first; case-exact matches lock.
   - Slices carry `# CONTEXT imp:... | called_by:...` and verbatim lines, so edits apply first try.
   - Slices over 120 lines fold with a hint (`--max-lines N`, `0` = unlimited).
   - Check the `# SLICE file [symbol] (Lx-Ly)` header before trusting a slice.
4. Extra ranges: `codemap.py slice <repo> <Symbol | file:start-end>`; locate text/calls: `codemap.py search <repo> <text>`.

Flags: `map --mode ultra|full|lite`, `--lean`, `--full-detail`, `--no-cache`; `map`/`inspect --exclude GLOB` (repeatable); `inspect --max-per-query N`, `--max-lines N`. Skeleton cache lives outside the repo (`~/.cache/lazy-read`, override with `LAZYREAD_CACHE_DIR`).

Caveats: JS/TS/C-family/etc. use regex heuristics (Python uses real `ast`); the vendor skip hides directories named `lodash`, `third_party`, `3rdparty`, `externals`, `bower_components` (map that path directly if it is your own code). When writing new code from the skeleton, `inspect` the real functions you will call so signatures are exact.

### Debugging a bug (v1.7.0): error message / stack trace -> function -> what changed

Run the failing command with Bash first; these commands then turn its output into the exact code to read.

- `codemap.py find <repo> "<error text>"` : text/regex search over source files only (skips .pyc, binaries, vendored dirs). Hits are grouped by enclosing function, ranked with executable code hits ahead of docstring/comment mentions, docstrings stripped by default (`--with-doc` to keep), hit lines marked `>>`. Pinpoint searches (`<=2` symbols) show the function window + `# CONTEXT`; broad searches (`>=3` symbols) automatically switch to Compact Hit Mode (~196 tok vs ~600 tok for `grep -rn`, pass `--full-symbol` for full bodies). Flags: `--regex`, `-i`, `--max-symbols N` (default 6), `--max-lines N` (default 25), `--with-doc`, `--full-symbol`.
- `codemap.py trace <repo> --file trace.txt` (or pipe the trace on stdin): maps every in-repo frame (Python, Node, Java/Kotlin/C#, Go, Rust, C/C++/PHP/Ruby) to its enclosing function, failing line marked `>>`; frames outside the repo are listed in one line. Uses Leaf-Frame Focus by default: intermediate caller frames render compactly (`# SYMBOL` + `>>` call line) while the leaf/crashing frame renders full context (~144–154 tok in 1 call vs ~170 tok for reading ±4 lines per frame by hand and ~333 tok in v1.6.0; pass `--full-frames` for full caller frames).
- `codemap.py history <repo> <Symbol> [-n 5]` : last commits that touched that function's exact lines plus the diff of the newest one (`git log -L`, read-only). Answers "what changed here recently?" at ~2% of the cost of `git log -p` (~79–90 tok vs ~3,660 tok).

Then edit with your normal tools and re-run the failing command. `search` finds symbol names only; for message text use `find`.

## B. Long documents (`docmap.py`)

1. `python3 "$SKILL_DIR/scripts/docmap.py" outline <file> --depth 1` — sections with line ranges and rough token sizes (raise `--depth` only where needed; docs under ~400 tokens are inlined whole).
2. `docmap.py search <file> "term" ["term2"]` — hits with their section.
3. `docmap.py slice <file> <#id | "title" | L120-180 | p3-5>` — one section, line range, or PDF pages; folds after 6000 chars with a continue hint (`--max-chars 0` = unlimited).
4. Answer from the slice and cite section ids / lines.

Caveats: identical titles nested parent/child resolve to the outer section; true duplicates return an id list. PDF headings come from font size (no larger-font headings → one section per page). Scanned PDFs have no text layer: not supported (no OCR). Word headings need real Heading styles; headingless text falls back to 40-line chunks.

## C. Tables (`tablemap.py`)

1. `python3 "$SKILL_DIR/scripts/tablemap.py" schema <file> [--sheet NAME]` — rows x cols, per-column type, null %, distinct count, range/mean or top values, sample rows, sheet list.
2. `tablemap.py agg <file> --col amount --by region` — count/sum/mean/min/max per group, computed by the script.
3. `tablemap.py slice <file> --where "qty>18" --cols id,qty --rows 1-50 --limit 30` — operators `= != > < >= <= ~` (`~` = contains); row numbers are data rows (header excluded).
4. `tablemap.py find <file> "text" [--col NAME]`.

Never page thousands of rows into the conversation. Joins, pivots, charts and formulas: run real code (e.g. pandas) after reading the schema. xlsx: cached values only (formulas are not evaluated); date-formatted cells are converted from serials.

