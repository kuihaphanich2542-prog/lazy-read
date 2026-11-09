#!/usr/bin/env python3
"""docmap: outline / slice / search for LONG DOCUMENTS so an agent reads a table of
contents first and only the sections it needs.

Formats: .md .markdown .txt .rst .html .htm .docx .pdf (pdf needs `pdftotext`, poppler).
Pure Python 3 standard library. No network. Read-only (never modifies the document).

  docmap.py outline <file> [--depth N] [--no-snippet] [--max-sections N]
  docmap.py slice   <file> <#N | "title text" | L10-80 | p3-5> [--max-chars N]
  docmap.py search  <file> <text> [<text> ...] [--limit N]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET

VERSION = "1.7.4"
TOK = 4  # approx chars per token (same convention as lazy-read)

Head = Tuple[int, str, int]  # (level, title, 1-based line index)


# --------------------------------------------------------------------------
# Plain-text heading heuristics (txt / pdf)
# --------------------------------------------------------------------------
_RE_NUM = re.compile(r"^(\d+(?:\.\d+){0,3})[.)]?\s+\S")
_RE_KEY = re.compile(r"^(chapter|section|part|appendix|article|บทที่|ส่วนที่|หมวด|ภาคผนวก|ข้อ)(?=\s|\d|$)", re.I)


def _plain_heading(line: str, prev_blank: bool, next_nonblank: bool) -> Optional[int]:
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ",", ";", ":")) or s.startswith(("[page ", "---")):
        return None
    m = _RE_NUM.match(s)
    if m and prev_blank and len(s.split()) <= 14:
        return min(m.group(1).count(".") + 1, 4)
    if _RE_KEY.match(s) and prev_blank:
        return 1
    letters = [c for c in s if c.isalpha()]
    if prev_blank and next_nonblank and len(letters) >= 4 and s.isupper() and len(s.split()) <= 10:
        return 1
    return None


def _plain_headings(lines: List[str]) -> List[Head]:
    heads: List[Head] = []
    for i, ln in enumerate(lines):
        prev_blank = i == 0 or not lines[i - 1].strip()
        nxt = any(l.strip() for l in lines[i + 1:i + 3])
        lvl = _plain_heading(ln, prev_blank, nxt)
        if lvl:
            heads.append((lvl, ln.strip(), i + 1))
    return heads


# --------------------------------------------------------------------------
# Extractors -> (lines, headings)
# --------------------------------------------------------------------------
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("cp874", errors="replace")


def extract_markdown(path: Path):
    lines = _read_text(path).splitlines()
    heads: List[Head] = []
    in_fence = False
    for i, ln in enumerate(lines):
        if re.match(r"^\s*(```|~~~)", ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", ln)
        if m:
            heads.append((len(m.group(1)), m.group(2), i + 1))
        elif i + 1 < len(lines) and ln.strip() and re.match(r"^(=+|-+)\s*$", lines[i + 1]) and len(lines[i + 1].strip()) >= 3:
            heads.append((1 if lines[i + 1].startswith("=") else 2, ln.strip(), i + 1))
    return lines, heads


def extract_text(path: Path):
    lines = _read_text(path).splitlines()
    return lines, _plain_headings(lines)


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "table", "ul", "ol", "pre", "blockquote", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: List[str] = [""]
        self.heads: List[Head] = []
        self._skip = 0
        self._in_script = False
        self._h: Optional[int] = None
        self._hbuf: List[str] = []

    def _nl(self):
        if self.lines[-1] != "":
            self.lines.append("")

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "noscript", "svg"):
            self._skip += 1
        elif tag == "script":
            self._in_script = True
            self._nl()
        elif re.fullmatch(r"h[1-6]", tag):
            self._nl()
            self._h = int(tag[1])
            self._hbuf = []
        elif tag in self.BLOCK:
            self._nl()
        elif tag in ("td", "th"):
            self.lines[-1] += " | "

    def handle_endtag(self, tag):
        if tag in ("style", "noscript", "svg"):
            self._skip = max(0, self._skip - 1)
        elif tag == "script":
            self._in_script = False
            self._nl()
        elif re.fullmatch(r"h[1-6]", tag) and self._h:
            title = " ".join("".join(self._hbuf).split())
            if title:
                self.heads.append((self._h, title, len(self.lines)))
            self._h = None
            self._nl()
        elif tag in self.BLOCK:
            self._nl()

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_script:
            for sl in data.splitlines():
                st = sl.strip()
                if st:
                    self._nl()
                    self.lines[-1] = st
            return
        t = " ".join(data.split())
        if not t:
            return
        if self._h:
            self._hbuf.append(t + " ")
        if self.lines[-1] and not self.lines[-1].endswith(" "):
            self.lines[-1] += " "
        self.lines[-1] += t


def extract_html(path: Path):
    p = _HTMLText()
    p.feed(_read_text(path))
    lines = [l.rstrip() for l in p.lines]
    # a heading's line index must point at the (non-empty) heading text line
    heads = []
    for lvl, title, idx in p.heads:
        j = min(idx, len(lines))
        while j > 1 and title not in lines[j - 1]:
            j -= 1
        heads.append((lvl, title, max(1, j)))
    return lines, heads


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _para_text(p) -> str:
    out = []
    for el in p.iter():
        if el.tag == _W + "t" and el.text:
            out.append(el.text)
        elif el.tag == _W + "tab":
            out.append("\t")
        elif el.tag in (_W + "br", _W + "cr"):
            out.append("\n")
    return "".join(out)


def extract_docx(path: Path):
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("word/document.xml"))
        names = {}
        if "word/styles.xml" in z.namelist():
            for st in ET.fromstring(z.read("word/styles.xml")).iter(_W + "style"):
                sid = st.get(_W + "styleId")
                nm = st.find(_W + "name")
                if sid and nm is not None:
                    names[sid] = (nm.get(_W + "val") or "").lower()
    body = doc.find(_W + "body")
    lines: List[str] = []
    heads: List[Head] = []
    for child in (list(body) if body is not None else []):
        if child.tag == _W + "p":
            text = _para_text(child).replace("\n", " ").strip()
            ppr = child.find(_W + "pPr")
            sid = None
            if ppr is not None:
                ps = ppr.find(_W + "pStyle")
                if ps is not None:
                    sid = ps.get(_W + "val")
            sname = names.get(sid or "", (sid or "")).lower()
            lvl = None
            m = re.search(r"heading\s*(\d)", sname)
            if m:
                lvl = int(m.group(1))
            elif sname in ("title", "หัวเรื่อง"):
                lvl = 1
            lines.append(text)
            if lvl and text:
                heads.append((lvl, text, len(lines)))
        elif child.tag == _W + "tbl":
            for tr in child.iter(_W + "tr"):
                cells = []
                for tc in tr.findall(_W + "tc"):
                    cells.append(" ".join(_para_text(p).strip() for p in tc.iter(_W + "p")).strip())
                lines.append(" | ".join(cells))
            lines.append("")
    return lines, heads


def _pdf_bbox(path: Path):
    """Return list of pages; each page a list of (text, line_height) in reading order."""
    try:
        res = subprocess.run(["pdftotext", "-bbox-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=180)
    except FileNotFoundError:
        raise SystemExit("error: pdftotext (poppler-utils) is required for .pdf files")
    if res.returncode != 0:
        raise SystemExit("error: pdftotext failed: " + res.stderr.decode("utf-8", "replace")[:200])
    xml = res.stdout.decode("utf-8", errors="replace")
    xml = re.sub(r"<!DOCTYPE[^>]*>", "", xml)
    root = ET.fromstring(xml.encode("utf-8"))
    pages = []
    for pg in root.iter():
        if pg.tag.split("}")[-1] != "page":
            continue
        items = []
        for ln in pg.iter():
            if ln.tag.split("}")[-1] != "line":
                continue
            words = [w.text or "" for w in ln if w.tag.split("}")[-1] == "word"]
            h = float(ln.get("yMax", 0)) - float(ln.get("yMin", 0))
            items.append((" ".join(words).strip(), h))
        pages.append(items)
    return pages


def extract_pdf(path: Path):
    pages = _pdf_bbox(path)
    from collections import Counter
    hs = Counter()
    for pg in pages:
        for t, h in pg:
            if t:
                hs[round(h, 1)] += len(t)
    body = hs.most_common(1)[0][0] if hs else 0
    big = sorted({round(h, 1) for pg in pages for t, h in pg if t and h >= body * 1.18}, reverse=True)
    lvl_of = {h: min(i + 1, 4) for i, h in enumerate(big[:4])}
    lines: List[str] = []
    heads: List[Head] = []
    for n, pg in enumerate(pages, 1):
        lines.append(f"[page {n}]")
        for t, h in pg:
            lines.append(t)
            hr = round(h, 1)
            if hr in lvl_of and 2 <= len(t) <= 90 and not t.endswith((".", ",", ";")):
                if heads and heads[-1][2] == len(lines) - 1 and heads[-1][0] == lvl_of[hr]:
                    # merge wrapped multi-line heading
                    lv, ttl, ix = heads.pop()
                    heads.append((lv, (ttl + " " + t)[:90], ix))
                else:
                    heads.append((lvl_of[hr], t, len(lines)))
    if len(heads) < 2:
        heads = _plain_headings(lines)
    if len(heads) < 2:  # still nothing -> one pseudo-section per page
        heads = []
        for i, ln in enumerate(lines):
            if ln.startswith("[page "):
                first = next((l.strip() for l in lines[i + 1:i + 8] if l.strip()), "")
                heads.append((1, f"{ln} {first[:50]}".strip(), i + 1))
    return lines, heads


EXTRACTORS = {
    ".md": extract_markdown, ".markdown": extract_markdown,
    ".txt": extract_text, ".rst": extract_text, ".text": extract_text,
    ".html": extract_html, ".htm": extract_html,
    ".docx": extract_docx, ".pdf": extract_pdf,
}


def load(path: Path):
    ext = path.suffix.lower()
    fn = EXTRACTORS.get(ext)
    if not fn:
        raise SystemExit(f"error: unsupported format '{ext}'. Supported: {', '.join(sorted(EXTRACTORS))}")
    lines, heads = fn(path)
    heads = sorted(set(heads), key=lambda h: h[2])
    return lines, heads


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
class Section:
    __slots__ = ("sid", "level", "title", "start", "end", "chars")

    def __init__(self, sid, level, title, start, end, chars):
        self.sid, self.level, self.title, self.start, self.end, self.chars = sid, level, title, start, end, chars


def build_sections(lines: List[str], heads: List[Head]) -> List[Section]:
    n = len(lines)
    secs: List[Section] = []
    if not heads:  # fallback: fixed chunks so very long headingless text is still navigable
        step = 40
        for k, s in enumerate(range(1, n + 1, step), 1):
            e = min(n, s + step - 1)
            first = next((l.strip() for l in lines[s - 1:e] if l.strip()), "")
            secs.append(Section(k, 1, f"(chunk) {first[:50]}", s, e, sum(len(l) + 1 for l in lines[s - 1:e])))
        return secs
    if heads[0][2] > 1 and any(l.strip() for l in lines[:heads[0][2] - 1]):
        e = heads[0][2] - 1
        secs.append(Section(0, 1, "(preamble)", 1, e, sum(len(l) + 1 for l in lines[:e])))
    for i, (lvl, title, ln) in enumerate(heads):
        end = n
        for lvl2, _t, ln2 in heads[i + 1:]:
            if lvl2 <= lvl:
                end = ln2 - 1
                break
        secs.append(Section(i + 1, lvl, title, ln, end, sum(len(l) + 1 for l in lines[ln - 1:end])))
    return secs


def _snippet(lines: List[str], s: Section, width: int = 70) -> str:
    for l in lines[s.start:min(s.end, s.start + 12)]:
        t = " ".join(l.split())
        if len(t) >= 12 and not t.startswith(("#", "[page ", "[![", "![", "<", "|--", "```", "http")) and sum(c.isalpha() for c in t) >= 0.5 * len(t):
            return (t[:width] + "…") if len(t) > width else t
    return ""


def _tok(chars: int) -> str:
    t = max(1, chars // TOK)
    return f"{t / 1000:.1f}k" if t >= 1000 else str(t)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_outline(path: Path, depth: int, snippet: bool, max_sections: int) -> str:
    lines, heads = load(path)
    total = sum(len(l) + 1 for l in lines)
    if total // TOK <= 400:  # tiny doc: just give it all, one round trip
        return f"# DOCMAP {path.name} | tiny (~{total // TOK} tok) — full text inlined\n" + "\n".join(lines)
    secs = build_sections(lines, heads)
    shown = [s for s in secs if s.level <= depth]
    out = [f"# DOCMAP {path.name} | {len(lines)} lines | ~{_tok(total)} tok | {len(secs)} sections (depth<={depth}: {len(shown)})"]
    base = min((s.level for s in shown), default=1)
    for s in shown[:max_sections]:
        ind = "  " * max(0, s.level - base)
        row = f"{ind}[#{s.sid}] {s.title[:80]} L{s.start}-{s.end} ~{_tok(s.chars)}t"
        if snippet:
            sn = _snippet(lines, s)
            if sn:
                row += f" — {sn}"
        out.append(row)
    if len(shown) > max_sections:
        out.append(f"... +{len(shown) - max_sections} more sections (raise --max-sections or lower --depth)")
    if len(shown) < len(secs):
        out.append(f"# {len(secs) - len(shown)} deeper sections hidden; use --depth {depth + 1}")
    return "\n".join(out)


def _resolve_target(lines, secs, target: str):
    t = target.strip()
    m = re.fullmatch(r"#(\d+)", t)
    if m:
        sid = int(m.group(1))
        for s in secs:
            if s.sid == sid:
                return s.start, s.end, f"#{s.sid} {s.title[:60]}"
        raise SystemExit(f"error: no section #{sid}")
    m = re.fullmatch(r"[Ll](\d+)-[Ll]?(\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return max(1, a), min(len(lines), b), f"L{a}-{b}"
    m = re.fullmatch(r"[Pp](\d+)(?:-[Pp]?(\d+))?", t)
    if m:
        p1, p2 = int(m.group(1)), int(m.group(2) or m.group(1))
        idx = {int(re.match(r"\[page (\d+)\]", l).group(1)): i + 1 for i, l in enumerate(lines) if re.match(r"\[page \d+\]", l)}
        if p1 not in idx:
            raise SystemExit(f"error: page {p1} not found (page slicing is for PDFs)")
        end = idx.get(p2 + 1, len(lines)) - 1
        return idx[p1], end, f"pages {p1}-{p2}"
    low = t.lower()
    hits = [s for s in secs if low in s.title.lower()]
    exact = [s for s in hits if s.title.lower() == low]
    hits = exact or hits
    if not hits:
        raise SystemExit(f"error: no section title contains '{t}'. Run `outline` first.")
    if len(hits) > 1:
        # same title repeated as parent/child (e.g. "# cookie" then "## cookie"): take the outermost
        outer = hits[0]
        if all(h.title.lower() == outer.title.lower() and outer.start <= h.start and h.end <= outer.end for h in hits):
            hits = [outer]
    if len(hits) > 1:
        raise SystemExit("error: ambiguous title, use an id:\n" + "\n".join(f"  [#{s.sid}] {s.title[:70]} L{s.start}-{s.end}" for s in hits[:12]))
    s = hits[0]
    return s.start, s.end, f"#{s.sid} {s.title[:60]}"


def cmd_slice(path: Path, target: str, max_chars: int) -> str:
    lines, heads = load(path)
    secs = build_sections(lines, heads)
    a, b, label = _resolve_target(lines, secs, target)
    body = lines[a - 1:b]
    chars = sum(len(l) + 1 for l in body)
    out = [f"# SLICE {path.name} [{label}] L{a}-L{b} of {len(lines)}L (~{_tok(chars)} tok)"]
    used = 0
    cut = None
    for i, l in enumerate(body):
        if max_chars and used + len(l) + 1 > max_chars and i > 0:
            cut = a + i
            break
        out.append(f"{a + i} | {l}")
        used += len(l) + 1
    if cut:
        out.append(f"... [folded L{cut}-L{b}; continue with: slice {path.name} L{cut}-{b}] ...")
    return "\n".join(out)


def cmd_search(path: Path, queries: List[str], limit: int) -> str:
    lines, heads = load(path)
    secs = build_sections(lines, heads)
    out = []
    for q in queries:
        ql = q.lower()
        hits = [(i + 1, l) for i, l in enumerate(lines) if ql in l.lower()]
        out.append(f"# search '{q}' ({len(hits)} hits)")
        for ln, l in hits[:limit]:
            sec = next((s for s in reversed(secs) if s.start <= ln <= s.end and s.sid != 0), None)
            where = f"[#{sec.sid} {sec.title[:40]}]" if sec else ""
            k = l.lower().find(ql)
            frag = " ".join(l[max(0, k - 50):k + len(q) + 70].split())
            out.append(f"L{ln} {where} …{frag}…")
        if len(hits) > limit:
            out.append(f"... +{len(hits) - limit} more (raise --limit)")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="docmap: outline/slice/search long documents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("outline")
    o.add_argument("path")
    o.add_argument("--depth", type=int, default=3)
    o.add_argument("--no-snippet", action="store_true")
    o.add_argument("--max-sections", type=int, default=150)
    s = sub.add_parser("slice")
    s.add_argument("path")
    s.add_argument("target", help="#N | title text | L10-80 | p3-5")
    s.add_argument("--max-chars", type=int, default=6000, help="fold output after N chars (0 = unlimited)")
    q = sub.add_parser("search")
    q.add_argument("path")
    q.add_argument("queries", nargs="+")
    q.add_argument("--limit", type=int, default=30)
    a = ap.parse_args()
    p = Path(a.path)
    if not p.is_file():
        print(f"error: file not found: {p}", file=sys.stderr)
        return 1
    if a.cmd == "outline":
        print(cmd_outline(p, a.depth, not a.no_snippet, a.max_sections))
    elif a.cmd == "slice":
        print(cmd_slice(p, a.target, a.max_chars))
    else:
        print(cmd_search(p, a.queries, a.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
