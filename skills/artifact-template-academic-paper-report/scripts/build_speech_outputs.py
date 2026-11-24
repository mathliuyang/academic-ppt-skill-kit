#!/usr/bin/env python3
"""Generate synchronized Word and pure large-print PDF from canonical JSON."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from report_common import ReportError, emphasis_runs, load_report, sha256, timing_summary


def find_fonts(regular: str | None, bold: str | None) -> tuple[Path, Path]:
    if bool(regular) != bool(bold):
        raise ReportError("Supply both --font-regular and --font-bold, or neither")
    base = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    paths = (Path(regular), Path(bold)) if regular else (base / "msyh.ttc", base / "msyhbd.ttc")
    if not all(p.is_file() for p in paths):
        raise ReportError("Default Windows Microsoft YaHei font files unavailable; supply matching --font-regular and --font-bold. On macOS select tested local font files and specify --docx-font-family for Word.")
    if paths[0].resolve() == paths[1].resolve() or sha256(paths[0]) == sha256(paths[1]):
        raise ReportError("Regular and bold fonts must be different font assets; synthetic bold is not accepted")
    return paths


def set_doc_font(font, name="Microsoft YaHei", size=None):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    font.name = name
    font.color.rgb = RGBColor(0, 0, 0)
    if size:
        font.size = Pt(size)
    rpr = font._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn("w:" + attribute), name)
    for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        rfonts.attrib.pop(qn("w:" + attribute), None)


def create_docx(data: dict, path: Path, include_cues: bool, font_family: str = "Microsoft YaHei"):
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = Mm(20)
    section.left_margin = section.right_margin = Mm(22)
    for name, size in (("Normal", 13), ("Title", 19), ("Heading 1", 15)):
        set_doc_font(document.styles[name].font, name=font_family, size=size)
        for border in list(document.styles[name]._element.findall(".//" + qn("w:pBdr"))):
            border.getparent().remove(border)
    for name in ("SpokenText", "StageCue", "SlideTiming"):
        document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        document.styles[name].base_style = document.styles["Normal"]
        set_doc_font(document.styles[name].font, name=font_family, size=13 if name == "SpokenText" else 10)
    spoken = document.styles["SpokenText"].paragraph_format
    spoken.line_spacing = 1.36
    spoken.space_after = Pt(7)
    spoken.widow_control = True
    header = section.header.paragraphs[0]
    header.text = f"{data['report_title']}  逐页讲稿"
    set_doc_font(header.runs[0].font, name=font_family, size=9)
    title = document.add_paragraph(data["report_title"], "Title")
    title.paragraph_format.space_after = Pt(10)
    identity = [f"{label} {data[key].strip()}" for label, key in (("汇报人", "presenter"), ("单位", "institution")) if data[key].strip()]
    if identity:
        document.add_paragraph("　".join(identity))
    document.add_paragraph(f"听众 {data['audience']}　场景 {data['scenario']}")
    timing = timing_summary(data)
    document.add_paragraph(f"本稿按 PPT 页序编排，口述正文与 PPT 备注及纯讲稿 PDF 同步。预计逐页用时 {timing['slides_seconds']:g} 秒，预留 {data['reserved_seconds']:g} 秒，总时长上限 {data['target_seconds']:g} 秒。")
    for slide in data["slides"]:
        heading = document.add_paragraph(f"第 {slide['slide']} 页　{slide['title']}", "Heading 1")
        heading.paragraph_format.keep_with_next = True
        timing_paragraph = document.add_paragraph(f"本页预计用时 {slide['duration_seconds']:g} 秒", "SlideTiming")
        timing_paragraph.paragraph_format.keep_with_next = True
        for paragraph_index, paragraph in enumerate(slide["paragraphs"]):
            p = document.add_paragraph(style="SpokenText")
            if include_cues and slide["cues"] and paragraph_index == len(slide["paragraphs"]) - 1:
                p.paragraph_format.keep_with_next = True
            for text, bold in emphasis_runs(paragraph, slide["emphasis"]):
                run = p.add_run(text)
                run.bold = bold
                set_doc_font(run.font, name=font_family, size=13)
        if include_cues and slide["cues"]:
            for cue_index, cue in enumerate(slide["cues"]):
                cue_paragraph = document.add_paragraph("提示　" + cue, "StageCue")
                cue_paragraph.paragraph_format.keep_with_next = cue_index < len(slide["cues"]) - 1
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    document.core_properties.title = data["report_title"]
    document.core_properties.author = data["presenter"]
    document.save(path)


def _tokens(text: str):
    # Keep ordinary English words, scientific identifiers, decimals and units together.
    # A token wider than the complete line is split only as a last resort.
    pattern = r"[+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?\s*(?:%|(?:mg|kg|ug|µg|μg|g|nm|mm|cm|m|ms|s|K|eV|V|A|Hz|Pa|mol|mL|L)(?:/[A-Za-z0-9^µμ]+)?)(?![A-Za-z])|[A-Za-z0-9]+(?:[._/%+\-][A-Za-z0-9]+)*|\s+|[^A-Za-z0-9\s]"
    raw = re.findall(pattern, text)
    tokens = []
    pending = ""
    for token in raw:
        if token in "（【《“‘":
            pending += token
        elif token in "，。；：、！？）】》”’%" and tokens and not pending:
            tokens[-1] += token
        else:
            tokens.append(pending + token)
            pending = ""
    if pending:
        tokens.append(pending)
    return tokens


def wrap_paragraph(text: str, terms: list[str], font_size: float, width: float):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    characters = []
    for value, bold in emphasis_runs(text, terms):
        characters.extend((c, bold) for c in value)
    flags = [bold for _, bold in characters]
    offset = 0
    lines, line, used = [], [], 0.0
    for token in _tokens(text):
        token_flags = flags[offset:offset + len(token)]
        offset += len(token)
        chunks = []
        start = 0
        for i in range(1, len(token) + 1):
            if i == len(token) or token_flags[i] != token_flags[start]:
                chunks.append((token[start:i], token_flags[start]))
                start = i
        token_width = sum(stringWidth(s, "ReportYaHeiBold" if bold else "ReportYaHei", font_size) for s, bold in chunks)
        if "\n" in token or "\r" in token:
            for char, bold in zip(token, token_flags):
                if char == "\n":
                    lines.append(line)
                    line, used = [], 0.0
                elif char != "\r":
                    char_width = stringWidth(char, "ReportYaHeiBold" if bold else "ReportYaHei", font_size)
                    if line and used + char_width > width:
                        lines.append(line)
                        line, used = [], 0.0
                    line.append((char, bold))
                    used += char_width
            continue
        if line and used + token_width > width:
            lines.append(line)
            line, used = [], 0.0
        if token_width <= width:
            line.extend(chunks)
            used += token_width
        else:
            for char, bold in zip(token, token_flags):
                char_width = stringWidth(char, "ReportYaHeiBold" if bold else "ReportYaHei", font_size)
                if line and used + char_width > width:
                    lines.append(line)
                    line, used = [], 0.0
                line.append((char, bold))
                used += char_width
    if line:
        lines.append(line)
    return lines


def layout_pdf(data, font_size: float):
    from reportlab.lib.pagesizes import A4
    page_width, page_height = A4
    left, right, top, bottom = 56.0, 32.0, 45.0, 44.0
    width = page_width - left - right
    leading = font_size * 1.36
    pages = [[]]
    y = page_height - top - font_size
    active_slide = None
    for slide in data["slides"]:
        for paragraph_index, text in enumerate(slide["paragraphs"]):
            lines = wrap_paragraph(text, slide["emphasis"], font_size, width)
            for line in lines:
                if y < bottom:
                    pages.append([])
                    y = page_height - top - font_size
                    active_slide = None
                marker = slide["slide"] if active_slide != slide["slide"] else None
                pages[-1].append({"y": y, "line": line, "marker": marker, "slide": slide["slide"]})
                active_slide = slide["slide"]
                y -= leading
            y -= 5
        y -= 6
    return pages, left


def create_pdf(data: dict, path: Path, regular: Path, bold: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    pdfmetrics.registerFont(TTFont("ReportYaHei", str(regular), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("ReportYaHeiBold", str(bold), subfontIndex=0))
    pdfmetrics.registerFontFamily("ReportYaHei", normal="ReportYaHei", bold="ReportYaHeiBold")
    missing = set()
    for slide in data["slides"]:
        for paragraph in slide["paragraphs"]:
            for value, is_bold in emphasis_runs(paragraph, slide["emphasis"]):
                mapping = pdfmetrics.getFont("ReportYaHeiBold" if is_bold else "ReportYaHei").face.charToGlyph
                missing.update(character for character in value if not character.isspace() and not mapping.get(ord(character)))
    if missing:
        raise ReportError("PDF font lacks required glyphs: " + ", ".join(f"{character} U+{ord(character):04X}" for character in sorted(missing)))
    size = 21.0
    pages, left = layout_pdf(data, size)
    if len(pages) > 2:
        for candidate in (20.5, 20.0):
            shorter, candidate_left = layout_pdf(data, candidate)
            if len(shorter) <= 2:
                pages, left, size = shorter, candidate_left, candidate
                break
    canvas = Canvas(str(path), pagesize=A4, pageCompression=1)
    canvas.setTitle(data["report_title"])
    canvas.setAuthor(data["presenter"])
    for page_index, lines in enumerate(pages, 1):
        for row in lines:
            if row["marker"] is not None:
                canvas.setFont("ReportYaHei", 10)
                canvas.setFillColorRGB(.25, .25, .25)
                canvas.drawString(17, row["y"] + 3, f"S{row['marker']}")
            x = left
            canvas.setFillColorRGB(0, 0, 0)
            for text, is_bold in row["line"]:
                font = "ReportYaHeiBold" if is_bold else "ReportYaHei"
                canvas.setFont(font, size)
                canvas.drawString(x, row["y"], text)
                x += pdfmetrics.stringWidth(text, font, size)
        canvas.setFont("ReportYaHei", 9)
        canvas.setFillColorRGB(.35, .35, .35)
        canvas.drawCentredString(A4[0] / 2, 22, f"p.{page_index}")
        canvas.showPage()
    canvas.save()
    return {"pages": len(pages), "body_font_pt": size, "line_spacing_factor": 1.36, "regular_font": str(regular.resolve()), "bold_font": str(bold.resolve()), "regular_font_sha256": sha256(regular), "bold_font_sha256": sha256(bold), "spoken_only": True, "margin_markers": {"slide_id_x_max_pt": 48, "footer_y_max_pt": 36}}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_json", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--stem", default="逐页讲稿")
    parser.add_argument("--no-cues", action="store_true")
    parser.add_argument("--font-regular")
    parser.add_argument("--font-bold")
    parser.add_argument("--docx-font-family", default="Microsoft YaHei", help="Installed Word font family name; default preserves the Windows Microsoft YaHei behavior")
    args = parser.parse_args()
    try:
        data = load_report(args.report_json)
        if not args.stem or Path(args.stem).name != args.stem or any(c in args.stem for c in '<>:"/\\|?*') or args.stem.endswith((" ", ".")):
            raise ReportError("--stem must be a filename stem without path separators or reserved characters")
        regular, bold = find_fonts(args.font_regular, args.font_bold)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        docx_path = args.out_dir / f"{args.stem}.docx"
        pdf_path = args.out_dir / f"{args.stem}.pdf"
        if not args.docx_font_family.strip():
            raise ReportError("--docx-font-family must not be empty")
        create_docx(data, docx_path, not args.no_cues, args.docx_font_family.strip())
        pdf_details = create_pdf(data, pdf_path, regular, bold)
        receipt = {"schema_version": 1, "input": str(args.report_json.resolve()), "input_sha256": sha256(args.report_json), "slide_count": len(data["slides"]), "timing": timing_summary(data), "pdf": pdf_details, "outputs": {"docx": {"path": str(docx_path.resolve()), "sha256": sha256(docx_path)}, "pdf": {"path": str(pdf_path.resolve()), "sha256": sha256(pdf_path)}}, "docx_cues_included": not args.no_cues, "docx_font_family": args.docx_font_family.strip(), "verification_limits": "Generation receipt is not visual QA, semantic evidence verification, or playback verification."}
        receipt_path = args.out_dir / f"{args.stem}.receipt.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "docx": str(docx_path.resolve()), "pdf": str(pdf_path.resolve()), "receipt": str(receipt_path.resolve()), "pdf_pages": pdf_details["pages"], "body_font_pt": pdf_details["body_font_pt"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
