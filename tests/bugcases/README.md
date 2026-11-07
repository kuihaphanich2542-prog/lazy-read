# Bug cases (14)

Small seeded-bug projects used by `run_bench.py`. Each `<case>.trace` was recorded from a real failing run
(paths made relative). The projects are not meant to be run again unless you want to regenerate traces
(needs python3, node, go, java, ruby, php, rustc).

| Case | What it tests |
|---|---|
| PY-1 | 4-frame Python trace in a pure-Python JSON encoder |
| PY-2 | silent wrong output (no trace), found via `find "sorted("` |
| PY-3 | root cause 15 lines above the crash line in a 39-line function |
| PY-4 | root cause on its own line inside a CALLER frame, exception chain |
| JS-1..3 | Node traces: nested calls, lost `this` + node_modules frame, async chain |
| JS-4 | silent pagination bug; `find "slice("` hits 9 symbols |
| GO-1, GO-2 | Go panics; GO-2 root cause is not on the stack |
| JAVA-1 | NPE, innermost frame listed first |
| RB-1, PHP-1, RS-1 | Ruby, PHP, Rust traces |

Run: `python3 tests/bugcases/run_bench.py [path/to/codemap.py]`
