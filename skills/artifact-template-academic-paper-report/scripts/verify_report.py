#!/usr/bin/env python3
"""Read-only structural and synchronization audit; never certifies visual QA."""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from report_common import ReportError, load_report, normalize, timing_summary
from preview_validation import LIMIT as DESIGN_LIMIT, protected_design_paths, verify_design
from brand_validation import protected_brand_paths, verify_brand

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships", "rel": "http://schemas.openxmlformats.org/package/2006/relationships", "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def relationship_path(part):
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def related(zip_file, part):
    name = relationship_path(part)
    if name not in zip_file.namelist():
        return {}
    result = {}
    for rel in ET.fromstring(zip_file.read(name)):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "").replace("\\", "/")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        result[rel.get("Id")] = (resolved, rel.get("Type", "").rsplit("/", 1)[-1])
    return result


def find_relation(zip_file, part, kind):
    return next((path for path, relation_type in related(zip_file, part).values() if relation_type == kind), None)


def pptx_slides(zip_file):
    presentation = ET.fromstring(zip_file.read("ppt/presentation.xml"))
    rels = related(zip_file, "ppt/presentation.xml")
    return [rels[node.get("{%s}id" % NS["r"])][0] for node in presentation.findall("p:sldIdLst/p:sldId", NS)]


def reference_background_hashes(reference):
    """Identify actual retained full-canvas/background image assets, not all media."""
    hashes = set()
    with ZipFile(reference) as archive:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        size = presentation.find("p:sldSz", NS)
        width, height = int(size.get("cx")), int(size.get("cy"))
        for part in archive.namelist():
            if not re.match(r"ppt/(slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$", part):
                continue
            root = ET.fromstring(archive.read(part))
            relationships = related(archive, part)
            blips = list(root.findall("p:cSld/p:bg//a:blip", NS))
            for picture in root.findall(".//p:pic", NS):
                off = picture.find("p:spPr/a:xfrm/a:off", NS)
                ext = picture.find("p:spPr/a:xfrm/a:ext", NS)
                if off is not None and ext is not None and int(ext.get("cx")) >= width * .98 and int(ext.get("cy")) >= height * .98 and abs(int(off.get("x"))) < width * .02 and abs(int(off.get("y"))) < height * .02:
                    blips.extend(picture.findall("p:blipFill/a:blip", NS))
            for blip in blips:
                relation = relationships.get(blip.get("{%s}embed" % NS["r"]))
                if relation and relation[1] == "image" and relation[0] in archive.namelist():
                    hashes.add(hashlib.sha256(archive.read(relation[0])).hexdigest())
    return hashes


def _text(root):
    return "".join(n.text or "" for n in root.findall(".//a:t", NS))


def _paragraph_text(paragraph):
    return "".join("\n" if node.tag == "{%s}br" % NS["a"] else node.text or "" for node in paragraph.iter() if node.tag in {"{%s}t" % NS["a"], "{%s}br" % NS["a"]})


def spoken_note_paragraphs(notes):
    """Pure body or explicit ordered sections; never guess where speech ends."""
    markers = ["【口述正文】", "【提示】", "【资料来源】"]
    notes = [line for paragraph in notes for line in paragraph.splitlines() if line.strip()]
    marker_positions = [(index, paragraph.strip()) for index, paragraph in enumerate(notes) if paragraph.strip() in markers]
    if not marker_positions:
        if any(marker in paragraph for paragraph in notes for marker in markers):
            raise ReportError("Notes section markers must each occupy a separate paragraph/line")
        return notes
    labels = [marker for _, marker in marker_positions]
    if labels[0] != markers[0] or marker_positions[0][0] != 0 or len(labels) != len(set(labels)) or [markers.index(label) for label in labels] != sorted(markers.index(label) for label in labels):
        raise ReportError("Notes sections must begin with unique 【口述正文】 and follow body→cues→sources order")
    if any(marker in paragraph and paragraph.strip() != marker for paragraph in notes for marker in markers):
        raise ReportError("Notes section markers must each occupy a separate paragraph/line")
    stop = marker_positions[1][0] if len(marker_positions) > 1 else len(notes)
    speech = notes[1:stop]
    if not speech:
        raise ReportError("Notes 【口述正文】 section is empty")
    return speech


def _placeholder(shape):
    ph = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
    return (ph.get("idx", "0"), ph.get("type", "obj")) if ph is not None else None


def _matching_shape(root, placeholder):
    if root is None or placeholder is None:
        return None
    shapes = root.findall(".//p:sp", NS)
    return next((shape for shape in shapes if _placeholder(shape) and _placeholder(shape)[0] == placeholder[0]), None) or next((shape for shape in shapes if _placeholder(shape) and _placeholder(shape)[1] == placeholder[1]), None)


def _font_from_properties(properties, chinese):
    if properties is None:
        return None
    preferred = ("a:ea", "a:latin") if chinese else ("a:latin", "a:ea")
    for tag in preferred:
        font = properties.find(tag, NS)
        if font is not None and font.get("typeface"):
            return font.get("typeface")
    return None


def _theme_font(root, kind, script):
    if root is None:
        return None
    fonts = root.find(f"a:themeElements/a:fontScheme/a:{kind}Font", NS)
    if fonts is None:
        return None
    if script == "ea":
        direct = fonts.find("a:ea", NS)
        if direct is not None and direct.get("typeface"):
            return direct.get("typeface")
        han = next((node.get("typeface") for node in fonts.findall("a:font", NS) if node.get("script") == "Hans"), None)
        if han:
            return han
    latin = fonts.find("a:latin", NS)
    return latin.get("typeface") if latin is not None else None


def effective_fonts(zip_file, slide_part):
    """Resolve explicit, paragraph, placeholder, master and theme font settings."""
    slide = ET.fromstring(zip_file.read(slide_part))
    layout_part = find_relation(zip_file, slide_part, "slideLayout")
    layout = ET.fromstring(zip_file.read(layout_part)) if layout_part else None
    master_part = find_relation(zip_file, layout_part, "slideMaster") if layout_part else None
    master = ET.fromstring(zip_file.read(master_part)) if master_part else None
    theme_part = find_relation(zip_file, master_part, "theme") if master_part else None
    theme = ET.fromstring(zip_file.read(theme_part)) if theme_part else None
    presentation = ET.fromstring(zip_file.read("ppt/presentation.xml"))
    result, processed_runs = [], set()
    for shape in slide.findall(".//p:sp", NS):
        placeholder = _placeholder(shape)
        layout_shape = _matching_shape(layout, placeholder)
        master_shape = _matching_shape(master, placeholder)
        for paragraph in shape.findall("p:txBody/a:p", NS):
            ppr = paragraph.find("a:pPr", NS)
            level = int(ppr.get("lvl", "0")) + 1 if ppr is not None else 1
            for run in list(paragraph.findall("a:r", NS)) + list(paragraph.findall("a:fld", NS)):
                processed_runs.add(id(run))
                text = "".join(node.text or "" for node in run.findall("a:t", NS))
                if not text.strip():
                    continue
                chinese = bool(re.search(r"[\u3400-\u9fff]", text))
                properties = [run.find("a:rPr", NS), ppr.find("a:defRPr", NS) if ppr is not None else None]
                for inherited in (shape, layout_shape, master_shape):
                    if inherited is not None:
                        properties.append(inherited.find(f"p:txBody/a:lstStyle/a:lvl{level}pPr/a:defRPr", NS))
                        properties.append(inherited.find("p:txBody/a:lstStyle/a:defPPr/a:defRPr", NS))
                        if inherited is not shape:
                            properties.append(inherited.find("p:txBody/a:p/a:pPr/a:defRPr", NS))
                font = next((value for value in (_font_from_properties(prop, chinese) for prop in properties) if value), None)
                if not font:
                    reference = shape.find("p:style/a:fontRef", NS)
                    if reference is not None:
                        font = "+mj-ea" if reference.get("idx") == "major" and chinese else "+mj-lt" if reference.get("idx") == "major" else "+mn-ea" if chinese else "+mn-lt"
                if not font and master is not None:
                    style = "titleStyle" if placeholder and placeholder[1] in {"title", "ctrTitle"} else "bodyStyle" if placeholder else "otherStyle"
                    font = _font_from_properties(master.find(f"p:txStyles/p:{style}/a:lvl{level}pPr/a:defRPr", NS), chinese)
                if not font:
                    font = _font_from_properties(presentation.find(f"p:defaultTextStyle/a:lvl{level}pPr/a:defRPr", NS), chinese)
                if font and font.startswith("+"):
                    font = _theme_font(theme, "major" if font.startswith("+mj") else "minor", "ea" if font.endswith("ea") else "latin")
                if not font:
                    font = _theme_font(theme, "minor", "ea" if chinese else "latin")
                result.append({"text": text, "font": font})
    # Native tables and other non-shape text also expose a:r; inspect those too.
    parents = {child: parent for parent in slide.iter() for child in parent}
    for run in slide.findall(".//a:r", NS):
        if id(run) in processed_runs:
            continue
        text = "".join(node.text or "" for node in run.findall("a:t", NS))
        if not text.strip():
            continue
        chinese = bool(re.search(r"[\u3400-\u9fff]", text))
        paragraph = parents.get(run)
        font = _font_from_properties(run.find("a:rPr", NS), chinese)
        if not font and paragraph is not None:
            font = _font_from_properties(paragraph.find("a:pPr/a:defRPr", NS), chinese)
        if not font:
            font = _font_from_properties(presentation.find("p:defaultTextStyle/a:lvl1pPr/a:defRPr", NS), chinese)
        if font and font.startswith("+"):
            font = _theme_font(theme, "major" if font.startswith("+mj") else "minor", "ea" if font.endswith("ea") else "latin")
        if not font:
            font = _theme_font(theme, "minor", "ea" if chinese else "latin")
        result.append({"text": text, "font": font})
    return result


def expected_speech(data):
    return [paragraph for slide in data["slides"] for paragraph in slide["paragraphs"]]


def verify_docx(data, path):
    from docx import Document
    doc = Document(path)
    spoken = [p.text for p in doc.paragraphs if p.style.name == "SpokenText"]
    expected = expected_speech(data)
    failures = []
    if spoken != expected:
        failures.append("Word SpokenText paragraphs differ from canonical JSON (including paragraph boundaries)")
    actual_paragraphs = [p for p in doc.paragraphs if p.style.name == "SpokenText"]
    cursor = 0
    for slide in data["slides"]:
        for text in slide["paragraphs"]:
            paragraph = actual_paragraphs[cursor] if cursor < len(actual_paragraphs) else None
            cursor += 1
            if paragraph is None or paragraph.text != text:
                continue
            flags = [bool(run.bold) for run in paragraph.runs for _ in run.text]
            for term in slide["emphasis"]:
                start = 0
                while True:
                    start = text.find(term, start)
                    if start < 0:
                        break
                    if not all(flags[start:start + len(term)]):
                        failures.append(f"Word emphasis is not fully bold: slide {slide['slide']} paragraph {cursor} {term!r}")
                    start += 1
    return {"ok": not failures, "spoken_paragraph_count": len(spoken), "failures": failures}


def verify_pdf(data, path):
    from pypdf import PdfReader
    reader = PdfReader(path)
    content, bold_flags = [], []
    font_names, font_sizes = set(), []
    for page in reader.pages:
        def visitor(text, cm, tm, font, size):
            # Only the known self-generated slide gutter and page footer are excluded.
            x, y = tm[4] * cm[0] + tm[5] * cm[2] + cm[4], tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            stripped = text.strip()
            if x < 48 and re.fullmatch(r"S\d+", stripped):
                return
            if y <= 36 and re.fullmatch(r"p\.\d+", stripped):
                return
            if stripped:
                content.append(text)
                font_sizes.append(size)
                font_name = str(font.get("/BaseFont", "")) if font else ""
                is_bold = "Bold" in font_name or "BD" in font_name.upper()
                bold_flags.extend([is_bold] * len(normalize(text)))
                if font:
                    font_names.add(font_name)
        page.extract_text(visitor_text=visitor)
    speech = "\n".join(expected_speech(data))
    actual = "".join(content)
    failures = []
    if normalize(actual) != normalize(speech):
        failures.append("PDF spoken text differs from canonical JSON; no title, time or cue text may be added")
    if not font_sizes or min(font_sizes) < 20:
        failures.append("PDF spoken body font is below 20 pt or no body text was found")
    if any(slide["emphasis"] for slide in data["slides"]) and not any("Bold" in name or "BD" in name.upper() for name in font_names):
        failures.append("PDF does not contain a real bold font for emphasis")
    if normalize(actual) == normalize(speech):
        offset = 0
        for slide in data["slides"]:
            for paragraph in slide["paragraphs"]:
                normalized_paragraph = normalize(paragraph)
                for term in slide["emphasis"]:
                    start = 0
                    term = normalize(term)
                    while True:
                        start = normalized_paragraph.find(term, start)
                        if start < 0:
                            break
                        if not all(bold_flags[offset + start:offset + start + len(term)]):
                            failures.append(f"PDF emphasis is not fully bold: slide {slide['slide']} {term!r}")
                        start += 1
                offset += len(normalized_paragraph)
    for page in reader.pages:
        if abs(float(page.mediabox.width) - 595.276) > 1 or abs(float(page.mediabox.height) - 841.89) > 1:
            failures.append("PDF page is not A4 portrait")
            break
    return {"ok": not failures, "page_count": len(reader.pages), "fonts": sorted(font_names), "body_min_font_pt": min(font_sizes) if font_sizes else None, "failures": failures}


def verify_png(data, directory, template_style=False):
    from PIL import Image
    paths = sorted(directory.glob("*.png"))
    failures = []
    if len(paths) != len(data["slides"]):
        failures.append(f"Expected {len(data['slides'])} PNG files, found {len(paths)}; directory must contain only per-slide PNGs")
    dimensions = []
    for path in paths:
        with Image.open(path) as image:
            width, height = image.size
        dimensions.append({"file": path.name, "width": width, "height": height})
        if width < 1280 or height < 720 or (template_style and abs(width / height - 16 / 9) > .01):
            failures.append(f"PNG {path.name} must be at least 1280×720" + (" and 16:9 for this template" if template_style else ""))
    return {"ok": not failures, "count": len(paths), "dimensions": dimensions, "failures": failures}


def verify_pptx(data, path, template=None, brand=None, require_every_slide_brand=False, require_pure_speech_notes=False):
    failures, slide_results = [], []
    brand_result = None
    if require_every_slide_brand and brand is None:
        failures.append("--require-every-slide-brand requires --brand-profile")
    background_hashes = reference_background_hashes(template) if template else set()
    with ZipFile(path) as deck:
        slide_parts = pptx_slides(deck)
        if len(slide_parts) != len(data["slides"]):
            failures.append("PPT slide count differs from canonical JSON")
        presentation = ET.fromstring(deck.read("ppt/presentation.xml"))
        size = presentation.find("p:sldSz", NS)
        width, height = int(size.get("cx")), int(size.get("cy"))
        if template and abs(width / height - 16 / 9) > .001:
            failures.append("PPT canvas is not 16:9")
        deck_text = []
        for index, part in enumerate(slide_parts, 1):
            slide = ET.fromstring(deck.read(part))
            text = _text(slide)
            deck_text.append(text)
            note_part = find_relation(deck, part, "notesSlide")
            notes = []
            extra_note_texts = []
            if note_part:
                note_root = ET.fromstring(deck.read(note_part))
                speech_or_number_nodes = set()
                for shape in note_root.findall(".//p:sp", NS):
                    ph = _placeholder(shape)
                    if ph and ph[1] == "body":
                        notes.extend(_paragraph_text(p) for p in shape.findall("p:txBody/a:p", NS))
                        speech_or_number_nodes.update(shape.findall(".//a:t", NS))
                    elif ph and ph[1] == "sldNum":
                        speech_or_number_nodes.update(shape.findall(".//a:t", NS))
                extra_note_texts = [node.text for node in note_root.findall(".//a:t", NS)
                                    if node not in speech_or_number_nodes and (node.text or "").strip()]
            try:
                if require_pure_speech_notes:
                    # New deliveries contain only canonical oral paragraphs. Do not silently
                    # hide old section labels, cue/source blocks, or extra notes text boxes.
                    notes = [line for paragraph in notes for line in paragraph.splitlines() if line.strip()]
                    if extra_note_texts:
                        failures.append(f"PPT slide {index} has non-speech text outside the notes body")
                else:
                    notes = spoken_note_paragraphs(notes)
            except ReportError as exc:
                failures.append(f"PPT slide {index}: {exc}")
                notes = []
            expected = [line for paragraph in data["slides"][index - 1]["paragraphs"] for line in paragraph.splitlines() if line.strip()] if index <= len(data["slides"]) else []
            if [normalize(p) for p in notes] != [normalize(p) for p in expected]:
                failures.append(f"PPT slide {index} notes paragraphs differ from canonical speech")
            if template and not text.strip():
                failures.append(f"PPT slide {index} has no editable text")
            for picture in slide.findall(".//p:pic", NS):
                off = picture.find("p:spPr/a:xfrm/a:off", NS)
                ext = picture.find("p:spPr/a:xfrm/a:ext", NS)
                if template and off is not None and ext is not None and int(ext.get("cx")) >= width * .98 and int(ext.get("cy")) >= height * .98 and abs(int(off.get("x"))) < width * .02 and abs(int(off.get("y"))) < height * .02:
                    blip = picture.find("p:blipFill/a:blip", NS)
                    relation = related(deck, part).get(blip.get("{%s}embed" % NS["r"])) if blip is not None else None
                    digest = hashlib.sha256(deck.read(relation[0])).hexdigest() if relation and relation[1] == "image" else None
                    if not text.strip() or digest not in background_hashes:
                        failures.append(f"PPT slide {index} contains an unrecognized full-slide image or lacks an editable native body; inspect for a flattened slide")
            fonts = effective_fonts(deck, part)
            font_policy = data.get("font_policy")
            if font_policy is None:
                approved = {"microsoftyahei", "微软雅黑", "microsoftyaheiui"}
                font_label = "Microsoft YaHei (legacy default)"
            else:
                families = font_policy.get("families") if isinstance(font_policy, dict) else None
                if not isinstance(families, list) or not families or any(not isinstance(value, str) or not value.strip() for value in families):
                    raise ReportError("font_policy.families must be a nonempty array of approved font names")
                approved = {normalize(value).casefold() for value in families}
                font_label = ", ".join(families)
            non_approved = [item for item in fonts if item["font"] is None or normalize(item["font"]).casefold() not in approved]
            if template and non_approved:
                failures.append(f"PPT slide {index} has text outside approved font policy [{font_label}]: " + ", ".join(f"{item['text'][:20]!r}:{item['font']}" for item in non_approved[:4]))
            slide_results.append({"slide": index, "part": part, "notes_part": note_part, "notes_paragraph_count": len(notes), "extra_notes_text_count": len(extra_note_texts), "editable_text_characters": len(text), "effective_fonts": sorted(set(item["font"] or "unresolved" for item in fonts))})
        if template:
            with ZipFile(template) as reference:
                def master_signature(archive, part):
                    root = ET.fromstring(archive.read(part))
                    background = root.find("p:cSld/p:bg", NS)
                    bg = ET.tostring(background, encoding="unicode") if background is not None else "inherited"
                    decorations = []
                    for shape in root.findall(".//p:sp", NS):
                        if _placeholder(shape) or _text(shape).strip():
                            continue
                        transform = shape.find("p:spPr/a:xfrm", NS)
                        geometry = shape.find("p:spPr/a:prstGeom", NS)
                        decorations.append((ET.tostring(transform, encoding="unicode") if transform is not None else "", geometry.get("prst", "") if geometry is not None else "custom"))
                    return bg, sorted(decorations)
                master_parts = [p for p in deck.namelist() if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", p)]
                reference_parts = [p for p in reference.namelist() if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", p)]
                retained = [master_signature(deck, p) for p in master_parts]
                expected = [master_signature(reference, p) for p in reference_parts]
                if not all(signature in retained for signature in expected):
                    failures.append("PPT reference master backgrounds or non-text decorative geometry were not retained; review any intended redesign")
                for slide_part in slide_parts:
                    layout_part = find_relation(deck, slide_part, "slideLayout")
                    if not layout_part or not find_relation(deck, layout_part, "slideMaster"):
                        failures.append(f"PPT has a broken slide→layout→master relationship: {slide_part}")
                reference_layouts = {ET.fromstring(reference.read(p)).get("type", "") for p in reference.namelist() if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", p)}
                used_layouts = {ET.fromstring(deck.read(find_relation(deck, p, "slideLayout"))).get("type", "") for p in slide_parts if find_relation(deck, p, "slideLayout")}
                if not used_layouts.issubset(reference_layouts):
                    failures.append("PPT uses a layout type absent from the retained reference")
        if brand:
            brand_result = verify_brand(data, deck, slide_parts, deck_text, brand, require_every_slide_brand)
            failures.extend(brand_result["failures"])
    result = {"ok": not failures, "slide_count": len(slide_parts), "pure_speech_notes_required": require_pure_speech_notes, "slide_checks": slide_results, "failures": failures}
    if brand_result is not None:
        result["brand"] = brand_result
    return result


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("canonical_json", type=Path)
    for argument in ("pptx", "docx", "pdf", "png-dir", "template", "brand-profile", "report-json", "design-record", "design-preview-dir"):
        parser.add_argument("--" + argument, type=Path)
    parser.add_argument("--require-design-previews", action="store_true", help="Require a complete imagegen design record and a selected preview directory; legacy checks remain available without this flag")
    parser.add_argument("--require-every-slide-brand", action="store_true", help="Require visible registered brand assets on every actual PPT page; revision 2 requires exactly one original combined_logo per page")
    parser.add_argument("--require-pure-speech-notes", action="store_true", help="Require only canonical speech paragraphs in each notes body and no extra text boxes; reject legacy cue/source sections")
    args = parser.parse_args()
    report = {"schema_version": 1, "ok": False, "checks": {}, "failures": [], "limits": ["Sources are checked for presence and shape only; scientific truth and exact chart interpretation require human/agent source review.", "Structural checks do not certify visual layout, clipping, readability, animation or actual media playback.", "PPT image dimensions and effective font resolution are heuristic checks; all rendered pages still require visual inspection."]}
    try:
        data = load_report(args.canonical_json, enforce_budget=False)
        timing = timing_summary(data)
        report["checks"]["canonical"] = {"ok": timing["within_budget"], "slide_count": len(data["slides"]), "timing": timing, "source_record_count": sum(len(s["sources"]) for s in data["slides"])}
        if not timing["within_budget"]:
            report["failures"].append("Timing including reserve exceeds target")
        if (args.template or args.brand_profile) and not args.pptx:
            report["failures"].append("--template and --brand-profile require --pptx")
        if args.require_every_slide_brand and (args.pptx is None or args.brand_profile is None):
            report["failures"].append("--require-every-slide-brand requires both --pptx and --brand-profile")
        if args.require_design_previews or args.design_record or args.design_preview_dir:
            if args.require_design_previews and args.design_preview_dir is None:
                report["failures"].append("--require-design-previews requires --design-preview-dir")
            result = verify_design(data, args.canonical_json, args.design_record, args.design_preview_dir, args.pptx, args.png_dir)
            report["checks"]["design"] = result
            report["limits"].append(DESIGN_LIMIT)
            report["failures"].extend("design: " + failure for failure in result["failures"])
        if args.require_pure_speech_notes and args.pptx is None:
            report["failures"].append("--require-pure-speech-notes requires --pptx")
        checks = [("pptx", args.pptx, lambda p: verify_pptx(data, p, args.template, args.brand_profile, args.require_every_slide_brand, args.require_pure_speech_notes)), ("docx", args.docx, lambda p: verify_docx(data, p)), ("pdf", args.pdf, lambda p: verify_pdf(data, p)), ("png", args.png_dir, lambda p: verify_png(data, p, bool(args.template)))]
        for name, path, check in checks:
            if path is None:
                continue
            try:
                if not path.exists():
                    raise ReportError(f"Required artifact does not exist: {path}")
                result = check(path)
                report["checks"][name] = result
                report["failures"].extend(f"{name}: {failure}" for failure in result["failures"])
            except Exception as exc:
                report["checks"][name] = {"ok": False, "error": str(exc)}
                report["failures"].append(f"{name}: {exc}")
        report["ok"] = not report["failures"]
    except Exception as exc:
        report["failures"].append(str(exc))
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report_json:
        try:
            # The artifacts being audited remain read-only; this optional receipt is separate.
            protected = {p.resolve() for p in (args.canonical_json, args.pptx, args.docx, args.pdf, args.template, args.brand_profile) if p}
            protected.update(protected_design_paths(args.design_record, args.design_preview_dir))
            protected.update(protected_brand_paths(args.brand_profile))
            if args.png_dir and args.png_dir.is_dir():
                protected.update(p.resolve() for p in args.png_dir.rglob("*") if p.is_file())
            if args.report_json.resolve() in protected:
                raise ReportError("--report-json must not overwrite an input or audited artifact")
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(output, encoding="utf-8")
        except Exception as exc:
            report["failures"].append(f"Cannot write audit receipt: {exc}")
            report["ok"] = False
            output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
