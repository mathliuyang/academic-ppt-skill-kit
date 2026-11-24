"""Read-only audit of preview design records; declarations do not attest tool calls."""
from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from report_common import normalize

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
KINDS = {"native_text", "native_table", "native_chart", "original_image", "auxiliary_image"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
LIMIT = "Design records and matching local bytes are checked only; JSON declarations do not certify genuine image_gen tool execution, review quality or reconstruction fidelity. The agent must audit actual tool calls and inspect preview/final pairs."


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def screen_text_digest(slide):
    content = {"title": slide["title"], "screen_text": slide["screen_text"]}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def resolve_path(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("file path must be a nonempty string")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def protected_design_paths(record_path, preview_dir=None):
    """Collect known input paths even when record validation failed."""
    result = {record_path.resolve()} if record_path else set()
    if preview_dir and preview_dir.is_dir():
        result.update(p.resolve() for p in preview_dir.rglob("*") if p.is_file())
    if not record_path or not record_path.is_file():
        return result
    try:
        record = json.loads(record_path.read_text(encoding="utf-8-sig"))
        slides = record.get("slides", []) if isinstance(record, dict) else []
        for slide in slides if isinstance(slides, list) else []:
            if not isinstance(slide, dict):
                continue
            generation = slide.get("generation", {})
            generation = generation if isinstance(generation, dict) else {}
            values = [slide.get("selected_preview"), generation.get("artifact_file")]
            references = generation.get("reference_images", [])
            if isinstance(references, list):
                values += references
            reconstruction = slide.get("reconstruction", {})
            reconstruction = reconstruction if isinstance(reconstruction, dict) else {}
            regions = reconstruction.get("regions", [])
            if isinstance(regions, list):
                values += [region.get("asset_path") for region in regions if isinstance(region, dict)]
            for value in values:
                try:
                    result.add(resolve_path(value, record_path.parent))
                except (ValueError, TypeError, OSError):
                    pass
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return result


def pointer_value(data, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("native canonical_source must be a report JSON Pointer")
    value = data
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9]\d*", token):
                raise ValueError("JSON Pointer array index must be nonnegative")
            value = value[int(token)]
        else:
            value = value[token]
    return value


def _part_relations(archive, part):
    rel_part = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    result = {}
    if rel_part not in archive.namelist():
        return result
    for rel in ET.fromstring(archive.read(rel_part)):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "").replace("\\", "/")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        result[rel.get("Id")] = (resolved, rel.get("Type", "").rsplit("/", 1)[-1])
    return result


def _related_root(archive, part, relation_kind):
    related_part = next((target for target, kind in _part_relations(archive, part).values() if kind == relation_kind), None)
    return (related_part, ET.fromstring(archive.read(related_part))) if related_part in archive.namelist() else (None, None)


def _xml_true(value, default=False):
    return default if value is None else str(value).strip().casefold() in {"1", "true"}


def _blip_hashes(archive, part, node):
    rels, hashes = _part_relations(archive, part), set()
    for blip in node.findall(".//a:blip", NS):
        relation = rels.get(blip.get("{%s}embed" % NS["r"]))
        if relation and relation[1] == "image" and relation[0] in archive.namelist():
            hashes.add(hashlib.sha256(archive.read(relation[0])).hexdigest())
    return hashes


def _shape_image_hashes(archive, part, root, inherited=False):
    """Static display flags only; hidden groups suppress their descendants.

    Inherited placeholders are not ordinary inherited graphics. Their realized
    content is resolved on the actual slide and is deliberately not inferred.
    """
    hashes = set()
    tree = root.find("p:cSld/p:spTree", NS)
    if tree is None:
        return hashes

    def visit(shape):
        nonvisual = next((node for node in shape if node.tag in {"{%s}%s" % (NS["p"], name) for name in ("nvPicPr", "nvSpPr", "nvGrpSpPr", "nvGraphicFramePr", "nvCxnSpPr")}), None)
        if nonvisual is not None:
            drawing = nonvisual.find("p:cNvPr", NS)
            if drawing is not None and _xml_true(drawing.get("hidden")):
                return
            if inherited and nonvisual.find("p:nvPr/p:ph", NS) is not None:
                return
        if shape.tag == "{%s}grpSp" % NS["p"]:
            for child in shape:
                visit(child)
        else:
            hashes.update(_blip_hashes(archive, part, shape))

    for shape in tree:
        visit(shape)
    return hashes


def _visible_slide_images(archive, slide_part, slide):
    """Resolve this slide's own and statically displayed inherited image bytes."""
    layout_part, layout = _related_root(archive, slide_part, "slideLayout")
    master_part, master = _related_root(archive, layout_part, "slideMaster") if layout_part else (None, None)
    hashes = _shape_image_hashes(archive, slide_part, slide)
    show_inherited = _xml_true(slide.get("showMasterSp"), default=True)
    if layout is not None and show_inherited:
        hashes.update(_shape_image_hashes(archive, layout_part, layout, inherited=True))
    if master is not None and show_inherited and _xml_true(layout.get("showMasterSp"), default=True):
        hashes.update(_shape_image_hashes(archive, master_part, master, inherited=True))
    # Backgrounds inherit independently of Show Master Shapes. An explicit
    # nearest background (including a solid fill) suppresses more distant ones.
    for part, root in ((slide_part, slide), (layout_part, layout), (master_part, master)):
        if root is not None:
            background = root.find("p:cSld/p:bg", NS)
            if background is not None:
                hashes.update(_blip_hashes(archive, part, background))
                break
    return hashes


def ppt_native_inventory(path):
    """Presentation order, text/object counts and original media hashes."""
    with ZipFile(path) as archive:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        relations = {}
        for rel in ET.fromstring(archive.read("ppt/_rels/presentation.xml.rels")):
            if rel.get("TargetMode") != "External":
                target = rel.get("Target", "").replace("\\", "/")
                relations[rel.get("Id")] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("ppt", target))
        results = []
        for node in presentation.findall("p:sldIdLst/p:sldId", NS):
            root = ET.fromstring(archive.read(relations[node.get("{%s}id" % NS["r"])]))
            counts = Counter()
            text = "".join(n.text or "" for n in root.findall(".//a:t", NS))
            counts["native_text"] = sum(bool("".join(n.text or "" for n in shape.findall(".//a:t", NS)).strip()) for shape in root.findall(".//p:sp", NS))
            counts["native_table"] = len(root.findall(".//a:tbl", NS))
            counts["native_chart"] = len(root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/chart}chart"))
            # Only this actual slide/layout/master chain can satisfy image
            # regions; inherited text never replaces native slide-body objects.
            part = relations[node.get("{%s}id" % NS["r"])]
            results.append({"counts": counts, "text": normalize(text), "image_hashes": _visible_slide_images(archive, part, root)})
    return results


def verify_design(data, canonical_path, record_path, preview_dir=None, pptx_path=None, final_png_dir=None):
    from PIL import Image
    failures, slide_checks = [], []
    result = {"ok": False, "declared_producer": None, "generation_attestation": "not_certified_from_records", "slide_count": 0, "slide_checks": slide_checks, "limits": [LIMIT], "failures": failures}
    if record_path is None:
        failures.append("--design-record is required for design preview validation")
        return result
    try:
        record = json.loads(record_path.read_text(encoding="utf-8-sig"))
        if not isinstance(record, dict):
            raise ValueError("design record must be a JSON object")
    except (OSError, ValueError) as exc:
        failures.append(f"Cannot read design record: {exc}")
        return result
    result["declared_producer"] = record.get("producer")
    if record.get("schema_version") != 1 or isinstance(record.get("schema_version"), bool):
        failures.append("design record schema_version must be integer 1")
    if record.get("producer") != "image_gen.imagegen":
        failures.append("design record producer must be image_gen.imagegen; rendered PPTs are not imagegen previews")
    if record.get("report_json_sha256") != digest(canonical_path):
        failures.append("design record report_json_sha256 does not match exact canonical report file bytes")
    slides = record.get("slides")
    if not isinstance(slides, list):
        failures.append("design record slides must be an array")
        return result
    result["slide_count"] = len(slides)
    if len(slides) != len(data["slides"]):
        failures.append(f"Expected {len(data['slides'])} design entries, found {len(slides)}")
    inventory = None
    if pptx_path is not None:
        try:
            inventory = ppt_native_inventory(pptx_path)
            if len(inventory) != len(data["slides"]):
                failures.append("final PPT slide count does not match design/canonical page count")
        except Exception as exc:
            failures.append(f"Cannot inspect reconstruction in PPT: {exc}")
    # Existing verify_png owns output count and dimensions. Use a numeric
    # filename suffix for optional page hashes, since Slide10 sorts before Slide2.
    final_hashes, numbered_final_pngs = set(), {}
    if final_png_dir is not None and final_png_dir.is_dir():
        for path in final_png_dir.glob("*.png"):
            if not path.is_file():
                continue
            png_hash = digest(path)
            final_hashes.add(png_hash)
            page_suffix = re.search(r"([0-9]+)$", path.stem)
            if page_suffix:
                numbered_final_pngs.setdefault(int(page_suffix[1]), []).append((path, png_hash))
    selected_paths, selected_hashes = set(), set()
    base = record_path.parent
    for index, entry in enumerate(slides, 1):
        label = f"design slide {index}"
        issues = []
        checked = {"slide": index, "ok": False, "failures": issues}
        slide_checks.append(checked)
        try:
            if not isinstance(entry, dict) or type(entry.get("slide")) is not int or entry["slide"] != index:
                raise ValueError("slide must be consecutive integer matching canonical page order")
            if index > len(data["slides"]):
                raise ValueError("entry has no corresponding canonical slide")
            canonical_slide = data["slides"][index - 1]
            if not isinstance(entry.get("purpose"), str) or not entry["purpose"].strip():
                issues.append("purpose must be a nonempty string")
            if "screen_text_sha256" in entry and entry["screen_text_sha256"] != screen_text_digest(canonical_slide):
                issues.append("screen_text_sha256 disagrees with canonical title/screen text")
            selected = resolve_path(entry.get("selected_preview"), base)
            if Path(entry["selected_preview"]).is_absolute():
                issues.append("selected_preview must be relative to design record directory")
            checked["selected_preview"] = str(selected)
            if selected in selected_paths:
                issues.append("selected_preview path duplicates another page")
            selected_paths.add(selected)
            if not selected.is_file():
                raise ValueError(f"selected preview does not exist: {selected}")
            selected_hash = digest(selected)
            if selected_hash in selected_hashes:
                issues.append("selected preview bytes duplicate another page")
            selected_hashes.add(selected_hash)
            if selected_hash in final_hashes:
                issues.append("selected imagegen preview bytes also appear as a final PNG; reconstruction rendering is not evidenced")
            with Image.open(selected) as image:
                width, height = image.size
                image.verify()
            checked["dimensions"] = [width, height]
            if width < 1280 or height < 720 or abs(width / height - 16 / 9) > .015:
                issues.append("selected preview must be a complete 16:9 page, at least 1280×720, not a thumbnail/contact sheet")
            generation = entry.get("generation", {})
            if not isinstance(generation, dict):
                raise ValueError("generation must be an object")
            if generation.get("tool") != "image_gen.imagegen":
                issues.append("generation.tool must be image_gen.imagegen")
            if not isinstance(generation.get("prompt"), str) or not generation["prompt"].strip():
                issues.append("generation.prompt must store the actual nonempty generation prompt")
            if generation.get("sha256") != selected_hash:
                issues.append("generation.sha256 does not match selected preview bytes")
            artifact = resolve_path(generation.get("artifact_file"), base)
            if not artifact.is_file() or digest(artifact) != selected_hash:
                issues.append("actual returned artifact_file must exist and match selected preview bytes")
            try:
                stamp = datetime.fromisoformat(generation.get("generated_at_utc", "").replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
                    raise ValueError("not UTC")
            except (ValueError, TypeError, AttributeError):
                issues.append("generation.generated_at_utc must be an ISO8601 UTC timestamp")
            references = generation.get("reference_images")
            if not isinstance(references, list) or not references:
                issues.append("generation.reference_images must record nonempty original/reference image paths")
            else:
                for reference in references:
                    if not resolve_path(reference, base).is_file():
                        issues.append(f"generation reference image does not exist: {reference}")
            review = entry.get("review", {})
            if not isinstance(review, dict) or review.get("status") != "accepted" or not isinstance(review.get("observations"), str) or not review["observations"].strip():
                issues.append("review must be accepted with nonempty observations")
            reconstruction = entry.get("reconstruction", {})
            if not isinstance(reconstruction, dict):
                raise ValueError("reconstruction must be an object")
            if reconstruction.get("status") != "complete" or type(reconstruction.get("final_slide")) is not int or reconstruction["final_slide"] != index:
                issues.append("reconstruction must be complete and map to this final_slide")
            if final_png_dir is not None and "final_png_sha256" in reconstruction:
                expected_png_hash = reconstruction["final_png_sha256"]
                candidates = numbered_final_pngs.get(index, [])
                if not isinstance(expected_png_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_png_hash):
                    issues.append("reconstruction.final_png_sha256 must be a lowercase SHA-256 hex digest")
                elif len(candidates) != 1:
                    issues.append(f"reconstruction.final_png_sha256 needs exactly one final PNG with filename ending in page number {index}")
                elif expected_png_hash != candidates[0][1]:
                    issues.append(f"reconstruction.final_png_sha256 does not match final PNG {candidates[0][0].name}")
            if not isinstance(reconstruction.get("comparison_observations"), str) or not reconstruction["comparison_observations"].strip():
                issues.append("reconstruction comparison_observations must be nonempty")
            regions = reconstruction.get("regions")
            if not isinstance(regions, list) or not regions:
                raise ValueError("reconstruction regions must be a nonempty array")
            region_ids, native_counts = set(), Counter()
            for region in regions:
                if not isinstance(region, dict):
                    raise ValueError("each region must be an object")
                region_id = region.get("id")
                if not isinstance(region_id, str) or not region_id.strip() or region_id in region_ids:
                    issues.append("region ids must be nonempty and unique within page")
                region_ids.add(region_id)
                kind = region.get("kind")
                if kind not in KINDS:
                    issues.append(f"unknown region kind: {kind}")
                    continue
                bbox = region.get("bbox")
                valid_bbox = isinstance(bbox, list) and len(bbox) == 4 and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in bbox)
                if not valid_bbox or bbox[2] <= 0 or bbox[3] <= 0 or bbox[0] + bbox[2] > 1.000001 or bbox[1] + bbox[3] > 1.000001:
                    issues.append(f"region {region_id}: bbox must be normalized [x,y,width,height] inside the page")
                source = region.get("canonical_source")
                if not isinstance(source, str) or not source.strip():
                    issues.append(f"region {region_id}: canonical_source must be nonempty")
                if kind.startswith("native_"):
                    native_counts[kind] += 1
                    try:
                        value = pointer_value(data, source)
                        if not source.startswith(f"/slides/{index - 1}/"):
                            raise ValueError("source must reference this canonical slide")
                        if kind == "native_text":
                            suffix = source[len(f"/slides/{index - 1}/"):]
                            if suffix != "title" and not (suffix == "screen_text" or suffix.startswith("screen_text/")):
                                raise ValueError("native text must reference title or screen_text, never generated OCR or speech")
                            values = value if isinstance(value, list) else [value]
                            if not values or any(not isinstance(v, str) or not v.strip() for v in values):
                                raise ValueError("native text source must resolve to nonempty canonical strings")
                            if inventory is not None and index <= len(inventory) and any(normalize(v) not in inventory[index - 1]["text"] for v in values):
                                issues.append(f"region {region_id}: canonical text is missing from final slide's native text")
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        issues.append(f"region {region_id}: invalid canonical_source: {exc}")
                else:
                    check_transparency = False
                    if kind == "auxiliary_image" and "transparent_background" in region:
                        check_transparency = region["transparent_background"]
                        if type(check_transparency) is not bool:
                            issues.append(f"region {region_id}: transparent_background must be a boolean")
                    asset = resolve_path(region.get("asset_path"), base)
                    if not asset.is_file() or digest(asset) != region.get("asset_sha256"):
                        issues.append(f"region {region_id}: image asset must exist with matching asset_sha256")
                    elif region["asset_sha256"] == selected_hash:
                        issues.append(f"region {region_id}: a selected full-page design preview cannot be a reconstruction image asset")
                    elif inventory is not None and index <= len(inventory) and region["asset_sha256"] not in inventory[index - 1]["image_hashes"]:
                        issues.append(f"region {region_id}: original asset bytes are not embedded on this final PPT slide")
                    elif check_transparency is True:
                        try:
                            with Image.open(asset) as image:
                                if image.format != "PNG":
                                    issues.append(f"region {region_id}: transparent_background requires a PNG asset")
                                else:
                                    low, high = image.convert("RGBA").getchannel("A").getextrema()
                                    if low != 0 or high == 0:
                                        issues.append(f"region {region_id}: transparent_background requires fully transparent pixels and nontransparent foreground")
                        except (OSError, ValueError, Image.DecompressionBombError) as exc:
                            issues.append(f"region {region_id}: cannot check transparent_background: {exc}")
            if not native_counts["native_text"]:
                issues.append("reconstruction must include canonical native_text; an all-image page is not editable")
            if inventory is not None and index <= len(inventory):
                for kind, count in native_counts.items():
                    if count > inventory[index - 1]["counts"][kind]:
                        issues.append(f"record claims {count} {kind} regions but final PPT has fewer native objects")
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            issues.append(str(exc))
        checked["ok"] = not issues
        failures.extend(f"{label}: {issue}" for issue in issues)
    if preview_dir is not None:
        if not preview_dir.is_dir():
            failures.append(f"Design preview directory does not exist: {preview_dir}")
        else:
            actual = {p.resolve() for p in preview_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS}
            if actual != selected_paths:
                failures.append("Design preview directory must contain exactly the N selected per-slide images, with no extra drafts or contact sheets")
    result["ppt_reconstruction_checked"] = inventory is not None
    result["final_png_substitution_checked"] = final_png_dir is not None and final_png_dir.is_dir()
    result["ok"] = not failures
    return result
