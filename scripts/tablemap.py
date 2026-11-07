#!/usr/bin/env python3
"""tablemap: schema / slice / find / agg for TABULAR FILES so an agent looks at the
structure first and never has to page thousands of rows through the conversation.

Formats: .csv .tsv .txt(delimited) .xlsx .xlsm. Pure Python 3 standard library. Read-only.

  tablemap.py schema <file> [--sheet NAME] [--sample N]
  tablemap.py slice  <file> [--sheet NAME] [--rows 1-20] [--cols a,b] [--where "col>5"] [--limit N]
  tablemap.py find   <file> <text> [--col NAME] [--sheet NAME] [--limit N]
  tablemap.py agg    <file> --col NAME [--by NAME] [--sheet NAME]

Row numbers are 1-based DATA rows (the header row is not counted), identical across commands.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple
from xml.etree import ElementTree as ET

VERSION = "1.7.3"
TOK = 4
UNIQ_CAP = 2000  # per-column distinct-value tracking cap

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("cp874", errors="replace")


def _csv_rows(path: Path) -> Iterator[List[str]]:
    text = _decode(path.read_bytes())
    ext = path.suffix.lower()
    delim = "\t" if ext == ".tsv" else ","
    if ext not in (".csv", ".tsv"):
        try:
            delim = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
        except csv.Error:
            pass
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        yield row


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_DATE_BUILTIN = set(range(14, 23)) | {45, 46, 47}


def _col_idx(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _is_date_fmt(code: str) -> bool:
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code.lower())
    return bool(re.search(r"[ymdhs]", code)) and not re.search(r"[#0?]", code.replace("0.", ""))


def _xlsx_sheets(path: Path) -> List[str]:
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
    return [s.get("name") for s in wb.iter(_NS + "sheet")]


def _xlsx_rows(path: Path, sheet: Optional[str]) -> Tuple[str, Iterator[List[str]]]:
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels}
    sheets = [(s.get("name"), rmap.get(s.get(_RNS + "id"))) for s in wb.iter(_NS + "sheet")]
    if not sheets:
        raise SystemExit("error: workbook has no sheets")
    pick = next((s for s in sheets if s[0] == sheet), None) if sheet else sheets[0]
    if pick is None:
        raise SystemExit(f"error: sheet '{sheet}' not found. Sheets: {', '.join(n for n, _ in sheets)}")
    name, target = pick
    target = target.lstrip("/")
    member = target if target.startswith("xl/") else "xl/" + target

    shared: List[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for _ev, el in ET.iterparse(z.open("xl/sharedStrings.xml")):
            if el.tag == _NS + "si":
                shared.append("".join(t.text or "" for t in el.iter(_NS + "t") if True))
                el.clear()
    # which cell style ids are dates
    date_xf: set = set()
    if "xl/styles.xml" in z.namelist():
        st = ET.fromstring(z.read("xl/styles.xml"))
        custom = {int(n.get("numFmtId")): n.get("formatCode", "") for n in st.iter(_NS + "numFmt")}
        cx = st.find(_NS + "cellXfs")
        if cx is not None:
            for i, xf in enumerate(cx.findall(_NS + "xf")):
                fid = int(xf.get("numFmtId", "0"))
                if fid in _DATE_BUILTIN or (fid in custom and _is_date_fmt(custom[fid])):
                    date_xf.add(i)

    def gen() -> Iterator[List[str]]:
        epoch = dt.datetime(1899, 12, 30)
        for _ev, row in ET.iterparse(z.open(member)):
            if row.tag != _NS + "row":
                continue
            cells: Dict[int, str] = {}
            for c in row.findall(_NS + "c"):
                ref, t, s = c.get("r"), c.get("t"), c.get("s")
                v = c.find(_NS + "v")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(_NS + "t"))
                elif v is None or v.text is None:
                    continue
                elif t == "s":
                    val = shared[int(v.text)]
                elif t == "b":
                    val = "TRUE" if v.text == "1" else "FALSE"
                elif t in ("str", "e"):
                    val = v.text
                else:
                    val = v.text
                    if s is not None and int(s) in date_xf:
                        try:
                            d = epoch + dt.timedelta(days=float(val))
                            val = d.date().isoformat() if d.time() == dt.time(0) else d.isoformat(sep=" ")
                        except (ValueError, OverflowError):
                            pass
                    else:
                        try:
                            f = float(val)
                            val = str(int(f)) if f == int(f) and abs(f) < 1e15 else f"{f:.15g}"
                        except ValueError:
                            pass
                cells[_col_idx(ref)] = val
            row.clear()
            if not cells:
                yield []
                continue
            width = max(cells) + 1
            yield [cells.get(i, "") for i in range(width)]
    return name, gen()


def open_table(path: Path, sheet: Optional[str]) -> Tuple[str, List[str], Iterator[List[str]]]:
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        name, rows = _xlsx_rows(path, sheet)
    elif ext in (".csv", ".tsv", ".txt"):
        name, rows = "", _csv_rows(path)
    else:
        raise SystemExit(f"error: unsupported format '{ext}'. Supported: .csv .tsv .xlsx .xlsm")
    header: List[str] = []
    for r in rows:
        if any(c.strip() for c in r):
            header = [c.strip() or f"col{i + 1}" for i, c in enumerate(r)]
            break
    # de-duplicate header names
    seen: Counter = Counter()
    uniq = []
    for h in header:
        seen[h] += 1
        uniq.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
    return name, uniq, rows


def data_rows(header: List[str], rows: Iterator[List[str]]) -> Iterator[Tuple[int, List[str]]]:
    n = len(header)
    i = 0
    for r in rows:
        if not any(c.strip() for c in r):
            continue
        i += 1
        r = (r + [""] * n)[:n] if len(r) != n else r
        yield i, r


# --------------------------------------------------------------------------
# Type inference
# --------------------------------------------------------------------------
_RE_INT = re.compile(r"^-?\d{1,18}$")
_RE_FLOAT = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
_RE_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?|\d{1,2}/\d{1,2}/\d{2,4})$")


def _kind(v: str) -> str:
    if _RE_INT.match(v):
        return "int"
    if _RE_FLOAT.match(v.replace(",", "")) and any(ch.isdigit() for ch in v):
        return "float"
    if v.lower() in ("true", "false"):
        return "bool"
    if _RE_DATE.match(v):
        return "date"
    return "text"


def _num(v: str) -> Optional[float]:
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


class ColStat:
    def __init__(self):
        self.n = 0
        self.nulls = 0
        self.kinds: Counter = Counter()
        self.vals: Counter = Counter()
        self.capped = False
        self.nmin = self.nmax = None
        self.nsum = 0.0
        self.ncnt = 0
        self.smin = self.smax = None

    def add(self, v: str):
        self.n += 1
        v = v.strip()
        if v == "":
            self.nulls += 1
            return
        k = _kind(v)
        self.kinds[k] += 1
        if k in ("int", "float"):
            x = _num(v)
            if x is not None:
                self.nmin = x if self.nmin is None else min(self.nmin, x)
                self.nmax = x if self.nmax is None else max(self.nmax, x)
                self.nsum += x
                self.ncnt += 1
        elif k == "date":
            self.smin = v if self.smin is None or v < self.smin else self.smin
            self.smax = v if self.smax is None or v > self.smax else self.smax
        if v in self.vals or len(self.vals) < UNIQ_CAP:
            self.vals[v] += 1
        else:
            self.capped = True

    def type(self) -> str:
        tot = sum(self.kinds.values())
        if not tot:
            return "empty"
        k, c = self.kinds.most_common(1)[0]
        if c / tot >= 0.9:
            return k
        if set(self.kinds) <= {"int", "float"}:
            return "float"
        return "mixed"


def _fmt(x: float) -> str:
    return str(int(x)) if x == int(x) and abs(x) < 1e15 else f"{x:.10g}"


def _cut(s: str, n: int = 28) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_schema(path: Path, sheet: Optional[str], sample: int) -> str:
    name, header, rows = open_table(path, sheet)
    stats = [ColStat() for _ in header]
    first: List[List[str]] = []
    last: List[List[str]] = []
    total_chars = 0
    nrows = 0
    for i, r in data_rows(header, rows):
        nrows = i
        total_chars += sum(len(c) + 1 for c in r)
        for s, v in zip(stats, r):
            s.add(v)
        if i <= sample:
            first.append(r)
        else:
            last.append(r)
            if len(last) > 1:
                last.pop(0)
    full_tok = (total_chars + sum(len(h) + 1 for h in header)) // TOK
    other = ""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        names = _xlsx_sheets(path)
        if len(names) > 1:
            other = " | sheets: " + ", ".join(names)
    out = [f"# TABLEMAP {path.name}{(' / ' + name) if name else ''} | {nrows:,} rows x {len(header)} cols | ~{full_tok:,} tok if read in full{other}"]
    out.append("# col | type | null% | uniq | range / top values")
    for i, (h, s) in enumerate(zip(header, stats), 1):
        t = s.type()
        nonnull = s.n - s.nulls
        uniq = f">{UNIQ_CAP}" if s.capped else str(len(s.vals))
        pct = f"{100 * s.nulls / s.n:.0f}" if s.n else "0"
        if t in ("int", "float") and s.ncnt:
            info = f"{_fmt(s.nmin)}..{_fmt(s.nmax)} mean {_fmt(s.nsum / s.ncnt)}"
        elif t == "date":
            info = f"{s.smin} .. {s.smax}"
        elif t in ("empty",):
            info = ""
        else:
            top = s.vals.most_common(4)
            if not s.capped and len(s.vals) <= 12:
                info = "; ".join(f"{_cut(v, 18)}({100 * c / nonnull:.0f}%)" for v, c in top)
            else:
                info = "top: " + "; ".join(f"{_cut(v, 18)}({c})" for v, c in top[:3])
        out.append(f"{i}. {h} | {t} | {pct} | {uniq} | {info}")
    shown = first + last
    if shown:
        out.append(f"# sample rows ({len(first)} first + {len(last)} last):")
        for r in first:
            out.append("  " + " | ".join(_cut(c) for c in r))
        if last:
            out.append("  ...")
            for r in last:
                out.append("  " + " | ".join(_cut(c) for c in r))
    return "\n".join(out)


_RE_WHERE = re.compile(r"^\s*(.+?)\s*(>=|<=|!=|=|>|<|~)\s*(.*?)\s*$")


def _make_filter(header: List[str], expr: str):
    m = _RE_WHERE.match(expr)
    if not m:
        raise SystemExit(f"error: bad --where '{expr}'. Use: col=value | col>5 | col~text (contains)")
    col, op, val = m.groups()
    if col not in header:
        raise SystemExit(f"error: unknown column '{col}'. Columns: {', '.join(header)}")
    ci = header.index(col)
    fv = _num(val)

    def f(r: List[str]) -> bool:
        x = r[ci].strip()
        if op == "~":
            return val.lower() in x.lower()
        if op in ("=", "!="):
            eq = x == val or (fv is not None and _num(x) == fv)
            return eq if op == "=" else not eq
        a = _num(x)
        if a is None or fv is None:
            return False
        return {">": a > fv, "<": a < fv, ">=": a >= fv, "<=": a <= fv}[op]
    return f


def _pick_cols(header: List[str], cols: Optional[str]) -> List[int]:
    if not cols:
        return list(range(len(header)))
    idx = []
    for c in cols.split(","):
        c = c.strip()
        if c.isdigit() and 1 <= int(c) <= len(header) and c not in header:
            idx.append(int(c) - 1)
        elif c in header:
            idx.append(header.index(c))
        else:
            raise SystemExit(f"error: unknown column '{c}'. Columns: {', '.join(header)}")
    return idx


def cmd_slice(path: Path, sheet, rows_spec: Optional[str], cols: Optional[str], where: Optional[str], limit: int) -> str:
    name, header, rows = open_table(path, sheet)
    ci = _pick_cols(header, cols)
    a, b = 1, 10**12
    if rows_spec:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", rows_spec.strip())
        if not m:
            raise SystemExit("error: --rows must be N or A-B")
        a = int(m.group(1))
        b = int(m.group(2) or m.group(1))
    flt = _make_filter(header, where) if where else None
    out_rows = []
    matched = 0
    for i, r in data_rows(header, rows):
        if i < a:
            continue
        if i > b and not flt:
            break
        if i > b:
            break
        if flt and not flt(r):
            continue
        matched += 1
        if len(out_rows) < limit:
            out_rows.append((i, r))
    out = [f"# SLICE {path.name}{(' / ' + name) if name else ''} rows {a}-{b if b < 10**12 else 'end'}"
           + (f" where {where}" if where else "") + f" | {matched} matched, showing {len(out_rows)}"]
    out.append("row | " + " | ".join(header[i] for i in ci))
    for i, r in out_rows:
        out.append(f"{i} | " + " | ".join(_cut(r[j], 60) for j in ci))
    if matched > len(out_rows):
        out.append(f"... +{matched - len(out_rows)} more (raise --limit or narrow --rows/--where)")
    return "\n".join(out)


def cmd_find(path: Path, sheet, text: str, col: Optional[str], limit: int) -> str:
    name, header, rows = open_table(path, sheet)
    ci = _pick_cols(header, col) if col else list(range(len(header)))
    q = text.lower()
    hits = []
    count = 0
    for i, r in data_rows(header, rows):
        if any(q in r[j].lower() for j in ci):
            count += 1
            if len(hits) < limit:
                hits.append((i, r))
    out = [f"# find '{text}' in {path.name}: {count} rows", "row | " + " | ".join(header)]
    for i, r in hits:
        out.append(f"{i} | " + " | ".join(_cut(c, 40) for c in r))
    if count > len(hits):
        out.append(f"... +{count - len(hits)} more")
    return "\n".join(out)


def cmd_agg(path: Path, sheet, col: str, by: Optional[str]) -> str:
    name, header, rows = open_table(path, sheet)
    if col not in header:
        raise SystemExit(f"error: unknown column '{col}'. Columns: {', '.join(header)}")
    ci = header.index(col)
    bi = header.index(by) if by else None
    if by and by not in header:
        raise SystemExit(f"error: unknown column '{by}'")
    groups: Dict[str, List[float]] = {}
    nonnum = 0
    for _i, r in data_rows(header, rows):
        x = _num(r[ci])
        if x is None:
            nonnum += 1
            continue
        groups.setdefault(r[bi].strip() if bi is not None else "ALL", []).append(x)
    out = [f"# AGG {col}{(' by ' + by) if by else ''} | non-numeric/empty skipped: {nonnum}", "group | n | sum | mean | min | max"]
    items = sorted(groups.items(), key=lambda kv: -sum(kv[1]))
    for g, v in items[:30]:
        out.append(f"{_cut(g, 30)} | {len(v)} | {_fmt(sum(v))} | {_fmt(sum(v) / len(v))} | {_fmt(min(v))} | {_fmt(max(v))}")
    if len(items) > 30:
        out.append(f"... +{len(items) - 30} more groups")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="tablemap: schema/slice/find/agg for csv & xlsx")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("path")
    s.add_argument("--sheet")
    s.add_argument("--sample", type=int, default=3)
    sl = sub.add_parser("slice")
    sl.add_argument("path")
    sl.add_argument("--sheet")
    sl.add_argument("--rows")
    sl.add_argument("--cols")
    sl.add_argument("--where")
    sl.add_argument("--limit", type=int, default=30)
    f = sub.add_parser("find")
    f.add_argument("path")
    f.add_argument("text")
    f.add_argument("--sheet")
    f.add_argument("--col")
    f.add_argument("--limit", type=int, default=20)
    g = sub.add_parser("agg")
    g.add_argument("path")
    g.add_argument("--col", required=True)
    g.add_argument("--by")
    g.add_argument("--sheet")
    a = ap.parse_args()
    p = Path(a.path)
    if not p.is_file():
        print(f"error: file not found: {p}", file=sys.stderr)
        return 1
    if a.cmd == "schema":
        print(cmd_schema(p, a.sheet, a.sample))
    elif a.cmd == "slice":
        print(cmd_slice(p, a.sheet, a.rows, a.cols, a.where, a.limit))
    elif a.cmd == "find":
        print(cmd_find(p, a.sheet, a.text, a.col, a.limit))
    else:
        print(cmd_agg(p, a.sheet, a.col, a.by))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
