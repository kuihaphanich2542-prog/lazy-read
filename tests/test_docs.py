import csv, os, pathlib, subprocess, sys, tempfile, unittest, zipfile

HERE = pathlib.Path(__file__).resolve().parent.parent / "scripts"
DOC = str(HERE / "docmap.py")
TAB = str(HERE / "tablemap.py")


def run(script, *args):
    return subprocess.check_output([sys.executable, "-I", script, *args], text=True)


LONG_MD = "# Guide\n\nIntro paragraph that is long enough to count as a snippet here.\n\n" + "".join(
    f"## Section {i}\n\n" + ("Body sentence number %d about topic %d. " % (i, i)) * 40 + "\n\n" for i in range(1, 9)
) + "## Deep\n\n### Sub A\n\nalpha text " * 1 + "\n" + "needle-in-sub " * 60 + "\n"


class TestDocmap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown_outline_slice_search(self):
        f = self.p / "a.md"
        f.write_text(LONG_MD)
        out = run(DOC, "outline", str(f))
        self.assertIn("Section 3", out)
        self.assertIn("[#", out)
        sl = run(DOC, "slice", str(f), "Section 3")
        self.assertIn("topic 3", sl)
        self.assertNotIn("topic 4", sl)
        self.assertIn("needle", run(DOC, "search", str(f), "needle-in-sub", "--limit", "1"))

    def test_fenced_code_hash_is_not_heading(self):
        f = self.p / "b.md"
        f.write_text("# Real\n\n```\n# not a heading\n```\n\n" + "text. " * 400 + "\n")
        out = run(DOC, "outline", str(f))
        self.assertIn("Real", out)
        self.assertNotIn("not a heading", out)

    def test_tiny_doc_is_inlined(self):
        f = self.p / "t.md"
        f.write_text("# Hi\n\nshort\n")
        self.assertIn("full text inlined", run(DOC, "outline", str(f)))

    def test_txt_numbered_and_thai_headings(self):
        f = self.p / "c.txt"
        body = "รายละเอียดของหัวข้อนี้ " * 80
        f.write_text(f"1. Introduction\n\n{body}\n\n2. Methods\n\n{body}\n\nบทที่ 3 สรุป\n\n{body}\n")
        out = run(DOC, "outline", str(f), "--depth", "2")
        for k in ("Introduction", "Methods", "บทที่ 3"):
            self.assertIn(k, out)

    def test_html_headings_skip_scripts(self):
        f = self.p / "d.html"
        f.write_text("<html><script>var secret=1;</script><h1>Top</h1><p>" + "word " * 500 + "</p><h2>Sub</h2><p>" + "more " * 300 + "</p></html>")
        out = run(DOC, "outline", str(f))
        self.assertIn("Top", out)
        self.assertIn("Sub", out)
        self.assertNotIn("secret", run(DOC, "slice", str(f), "Top"))

    def test_docx_styles_and_tables(self):
        W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

        def para(t, style=None):
            st = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
            return f"<w:p>{st}<w:r><w:t>{t}</w:t></w:r></w:p>"
        body = para("Annual Report", "Heading1") + para("filler " * 400) + para("Revenue", "Heading2") + para("rev " * 300)
        body += "<w:tbl><w:tr><w:tc>%s</w:tc><w:tc>%s</w:tc></w:tr></w:tbl>" % (para("Q1"), para("42"))
        doc = f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'
        styles = f'<?xml version="1.0"?><w:styles {W}><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style><w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style></w:styles>'
        f = self.p / "e.docx"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("word/styles.xml", styles)
        out = run(DOC, "outline", str(f))
        self.assertIn("Annual Report", out)
        self.assertIn("Revenue", out)
        self.assertIn("Q1 | 42", run(DOC, "slice", str(f), "Revenue"))

    def test_pdf_font_size_headings(self):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest("reportlab missing")
        if subprocess.call(["which", "pdftotext"], stdout=subprocess.DEVNULL):
            self.skipTest("pdftotext missing")
        f = self.p / "f.pdf"
        c = canvas.Canvas(str(f), pagesize=A4)
        y = 800
        for title in ("Alpha Chapter", "Beta Chapter"):
            c.setFont("Helvetica-Bold", 20)
            c.drawString(50, y, title)
            y -= 30
            c.setFont("Helvetica", 10)
            for i in range(25):
                c.drawString(50, y, f"Body line {i} of {title} with ordinary words here.")
                y -= 14
            c.showPage()
            y = 800
        c.save()
        out = run(DOC, "outline", str(f), "--depth", "1")
        self.assertIn("Alpha Chapter", out)
        self.assertIn("Beta Chapter", out)
        self.assertIn("Body line 3 of Beta", run(DOC, "slice", str(f), "p2"))

    def test_same_title_parent_child_resolves_to_outer(self):
        f = self.p / "g.md"
        f.write_text("# pkg\n\n## pkg\n\n" + "x " * 600 + "\n\n# other\n\n" + "y " * 600 + "\n")
        out = run(DOC, "slice", str(f), "pkg")
        self.assertIn("L1-", out)
        f2 = self.p / "h.md"
        f2.write_text("## pkg\n\n" + "x " * 300 + "\n\n## pkg\n\n" + "y " * 300 + "\n")
        r = subprocess.run([sys.executable, "-I", DOC, "slice", str(f2), "pkg"], capture_output=True, text=True)
        self.assertIn("ambiguous", r.stderr)  # true siblings must still be reported

    def test_errors(self):
        f = self.p / "x.xyz"
        f.write_text("x")
        r = subprocess.run([sys.executable, "-I", DOC, "outline", str(f)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsupported", r.stderr)


class TestTablemap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = pathlib.Path(self.tmp.name)
        self.csv = self.p / "s.csv"
        with open(self.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "region", "amount", "day"])
            for i in range(1, 101):
                w.writerow([i, "N" if i % 2 else "S", "" if i % 10 == 0 else i * 1.5, f"2024-01-{(i % 28) + 1:02d}"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_types_nulls_and_header(self):
        out = run(TAB, "schema", str(self.csv))
        self.assertIn("100 rows x 4 cols", out)
        self.assertIn("id | int", out)
        self.assertIn("amount | float | 10", out)
        self.assertIn("day | date", out)
        self.assertIn("region | text", out)

    def test_slice_where_cols_and_find(self):
        out = run(TAB, "slice", str(self.csv), "--where", "id>=98", "--cols", "id,region")
        self.assertIn("3 matched", out)
        self.assertIn("98 | 98 | S", out)
        fnd = run(TAB, "find", str(self.csv), "2024-01-02", "--col", "day", "--limit", "1")
        self.assertIn("rows", fnd)
        self.assertIn("2024-01-02", fnd)
        self.assertIn("id | region", out)

    def test_agg_matches_manual_math(self):
        out = run(TAB, "agg", str(self.csv), "--col", "amount", "--by", "region")
        s = sum(i * 1.5 for i in range(1, 101) if i % 10 != 0)
        rows = [l.split(" | ") for l in out.splitlines()[2:]]
        self.assertEqual(sum(int(r[1]) for r in rows), 90)
        self.assertIn("skipped: 10", out)
        self.assertAlmostEqual(sum(float(r[2]) for r in rows), s, places=4)

    def test_xlsx_sheets_and_dates(self):
        try:
            import openpyxl, datetime as dt
        except ImportError:
            self.skipTest("openpyxl missing")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Data"
        ws.append(["when", "v"])
        ws.append([dt.date(2024, 5, 17), 1.1 + 2.2])
        ws.append([dt.date(2024, 6, 1), 7])
        wb.create_sheet("Other").append(["k"])
        f = self.p / "w.xlsx"
        wb.save(f)
        out = run(TAB, "schema", str(f))
        self.assertIn("2 rows x 2 cols", out)
        self.assertIn("sheets: Data, Other", out)
        self.assertIn("2024-05-17", out)
        self.assertIn("3.3", out)
        self.assertNotIn("3.3000000000000003", out)

    def test_bad_column_errors(self):
        r = subprocess.run([sys.executable, "-I", TAB, "slice", str(self.csv), "--where", "nope=1"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown column", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
