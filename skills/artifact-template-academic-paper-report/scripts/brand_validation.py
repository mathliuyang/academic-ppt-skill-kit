"""Read-only brand asset revision selection and visible original-logo audit."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from preview_validation import NS, _part_relations, _related_root, _visible_slide_images, _xml_true
from report_common import ReportError, normalize

LIMIT = "Brand checks establish original source bytes and statically displayed slide/layout/master uses with supported native effects only. They do not certify visual color contrast, cropping, logo clarity or actual rendering; inspect every rendered page."
USE_LOCAL_DPI_NS = "http://schemas.microsoft.com/office/drawing/2010/main"
USE_LOCAL_DPI_URI = "{28A0092B-C50C-407E-A947-70E740481C1C}"


def _read_profile(path):
    try:
        profile = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"Cannot read brand profile {path}: {exc}") from exc
    if not isinstance(profile, dict):
        raise ReportError("Brand profile must be a JSON object")
    return profile


def select_brand_profile(data, path):
    """Absent revision keeps historical reports on the retained revision 1."""
    profile = _read_profile(path)
    current = profile.get("asset_revision", 1)
    requested = data.get("brand_asset_revision", 1)
    for value, label in ((current, "Brand profile asset_revision"), (requested, "brand_asset_revision")):
        if type(value) is not int or value < 1:
            raise ReportError(f"{label} must be a positive integer")
    if current not in {1, 2}:
        raise ReportError(f"Unsupported brand profile asset_revision: {current}")
    if requested not in {1, 2} or requested > current:
        raise ReportError(f"Unsupported brand_asset_revision {requested} for selected profile (available current revision {current})")
    selected_path = path
    if current == 2 and requested == 1:
        legacy = profile.get("legacy_profile")
        if not isinstance(legacy, str) or not legacy.strip() or Path(legacy).is_absolute():
            raise ReportError("Revision-2 brand profile requires a relative legacy_profile for revision 1")
        selected_path = (path.parent / legacy).resolve()
        selected = _read_profile(selected_path)
        legacy_revision = selected.get("asset_revision", 1)
        if type(legacy_revision) is not int or legacy_revision != 1:
            raise ReportError("legacy_profile must contain brand asset revision 1")
        if selected.get("id") != profile.get("id"):
            raise ReportError("legacy_profile identity differs from current brand profile")
        profile = selected
    return profile, selected_path, requested


def protected_brand_paths(path):
    """Keep optional audit receipts from overwriting profile or logo inputs."""
    result = set()
    if path is None:
        return result
    result.add(path.resolve())
    try:
        current = _read_profile(path)
        paths = [path]
        legacy = current.get("legacy_profile")
        if isinstance(legacy, str) and legacy.strip():
            paths.append((path.parent / legacy).resolve())
        for profile_path in paths:
            result.add(profile_path.resolve())
            profile = _read_profile(profile_path)
            assets = profile.get("assets", {})
            for asset in assets.values() if isinstance(assets, dict) else []:
                if isinstance(asset, dict) and isinstance(asset.get("path"), str) and asset["path"].strip():
                    result.add((profile_path.parent / asset["path"]).resolve())
    except (OSError, ValueError, TypeError):
        pass
    return result


def _neutral_blip_extension(extension_list):
    """Allow only the documented Office compression flag, never opaque effects.

    MS-ODRAWXML 2.3.1.13 and 2.3.3.42 define this namespace, extension URI
    and optional xsd:boolean val (default true); the element has no children.
    """
    extensions = list(extension_list)
    if extension_list.attrib or len(extensions) != 1:
        raise ReportError("unsupported logo blip extension list; only one recognized useLocalDpi metadata extension is allowed")
    extension = extensions[0]
    if extension.tag != "{%s}ext" % NS["a"] or set(extension.attrib) != {"uri"} or extension.get("uri", "").upper() != USE_LOCAL_DPI_URI or len(extension) != 1:
        raise ReportError("unsupported logo blip extension; expected the known useLocalDpi URI and element only")
    metadata = extension[0]
    if metadata.tag != "{%s}useLocalDpi" % USE_LOCAL_DPI_NS or set(metadata.attrib) - {"val"} or len(metadata):
        raise ReportError("unsupported logo blip extension content or alpha/color effects inside useLocalDpi metadata")
    if any((node.text or "").strip() or (node.tail or "").strip() for node in extension_list.iter()):
        raise ReportError("unsupported text inside logo blip metadata extension")
    value = metadata.get("val", "true").strip()
    if value not in {"0", "1", "true", "false"}:
        raise ReportError("logo useLocalDpi metadata val must be a legal xsd:boolean")
    return {"kind": "useLocalDpi", "value": value in {"1", "true"}}


def _native_effect(blip, owners):
    """Only source white or exact white-to-target native duotone is supported."""
    for owner in owners:
        for tag in ("p:spPr", "p:grpSpPr", "p:bgPr"):
            properties = owner.find(tag, NS)
            if properties is not None:
                for name in ("a:effectLst", "a:effectDag"):
                    effects = properties.find(name, NS)
                    if effects is not None and len(effects):
                        raise ReportError("unsupported logo shape/group effects or alpha overrides")
    extension_lists = [child for child in blip if child.tag == "{%s}extLst" % NS["a"]]
    if len(extension_lists) > 1:
        raise ReportError("unsupported duplicate logo blip extension lists")
    metadata = [_neutral_blip_extension(node) for node in extension_lists]
    children = [child for child in blip if child.tag != "{%s}extLst" % NS["a"]]
    if not children:
        result = {"kind": "none", "target_color": "FFFFFF"}
    else:
        if len(children) != 1 or children[0].tag != "{%s}duotone" % NS["a"]:
            raise ReportError("unsupported logo blip color effects or alpha overrides; use no effect or native duotone")
        colors = list(children[0])
        if len(colors) != 2 or any(color.tag != "{%s}srgbClr" % NS["a"] or not re.fullmatch(r"[0-9A-Fa-f]{6}", color.get("val", "")) or len(color) for color in colors):
            raise ReportError("logo duotone must contain exactly two plain a:srgbClr colors with six-digit hex values")
        first, target = [color.get("val").upper() for color in colors]
        if first != "FFFFFF":
            raise ReportError("logo duotone first color must be FFFFFF")
        result = {"kind": "duotone", "first_color": first, "target_color": target}
    if metadata:
        result["neutral_metadata"] = metadata
    return result


def _visible_logo_uses(archive, slide_number, slide_part, slide, expected_hash):
    """Mirror preview display rules and retain the actual matching blip effects."""
    if expected_hash not in _visible_slide_images(archive, slide_part, slide):
        return []
    layout_part, layout = _related_root(archive, slide_part, "slideLayout")
    master_part, master = _related_root(archive, layout_part, "slideMaster") if layout_part else (None, None)
    uses = []

    def inspect_blips(part, node, owners, inherited, background=False):
        rels = _part_relations(archive, part)
        for blip in node.findall(".//a:blip", NS):
            relation_id = blip.get("{%s}embed" % NS["r"])
            relation = rels.get(relation_id)
            if not relation or relation[1] != "image" or relation[0] not in archive.namelist():
                continue
            if hashlib.sha256(archive.read(relation[0])).hexdigest() != expected_hash:
                continue
            drawing = next((child for owner in reversed(owners) for child in owner.findall(".//p:cNvPr", NS)), None)
            use = {"slide": slide_number, "part": part, "media_part": relation[0], "relationship_id": relation_id, "inherited": inherited, "background": background, "source_sha256": expected_hash}
            if drawing is not None:
                use.update({"shape_id": drawing.get("id"), "shape_name": drawing.get("name", "")})
            try:
                use["effect"] = _native_effect(blip, owners)
            except ReportError as exc:
                use["effect"] = {"kind": "unsupported"}
                use["failure"] = str(exc)
            uses.append(use)

    def shapes(part, root, inherited=False):
        tree = root.find("p:cSld/p:spTree", NS)
        if tree is None:
            return

        def visit(shape, parents):
            nonvisual = next((node for node in shape if node.tag in {"{%s}%s" % (NS["p"], name) for name in ("nvPicPr", "nvSpPr", "nvGrpSpPr", "nvGraphicFramePr", "nvCxnSpPr")}), None)
            if nonvisual is not None:
                drawing = nonvisual.find("p:cNvPr", NS)
                if drawing is not None and _xml_true(drawing.get("hidden")):
                    return
                if inherited and nonvisual.find("p:nvPr/p:ph", NS) is not None:
                    return
            owners = parents + [shape]
            if shape.tag == "{%s}grpSp" % NS["p"]:
                for child in shape:
                    visit(child, owners)
            else:
                inspect_blips(part, shape, owners, inherited)

        for shape in tree:
            visit(shape, [])

    shapes(slide_part, slide)
    show_inherited = _xml_true(slide.get("showMasterSp"), default=True)
    if layout is not None and show_inherited:
        shapes(layout_part, layout, True)
    if master is not None and show_inherited and _xml_true(layout.get("showMasterSp"), default=True):
        shapes(master_part, master, True)
    for part, root in ((slide_part, slide), (layout_part, layout), (master_part, master)):
        if root is not None:
            background = root.find("p:cSld/p:bg", NS)
            if background is not None:
                inspect_blips(part, background, [background], part != slide_part, True)
                break
    return uses


def verify_brand(data, archive, slide_parts, deck_text, profile_path, require_every_slide=False):
    failures, assets, uses = [], [], []
    result = {"ok": False, "asset_revision": None, "profile_path": None, "assets": assets, "observed_uses": uses, "every_slide_brand_required": require_every_slide, "every_slide_brand_coverage_checked": False, "limits": [LIMIT], "failures": failures}
    try:
        profile, selected_path, revision = select_brand_profile(data, profile_path)
        result.update({"asset_revision": revision, "profile_path": str(selected_path), "brand_profile_id": profile.get("id")})
        all_text = normalize("".join(deck_text))
        for field in ("presenter", "institution", "motto"):
            expected = profile.get(field)
            if not isinstance(expected, str) or normalize(expected) not in all_text:
                failures.append(f"PPT expected brand text is missing: {field}")
        for field in ("presenter", "institution"):
            if normalize(str(data.get(field, ""))) != normalize(str(profile.get(field, ""))):
                failures.append(f"Canonical {field} disagrees with brand profile")
        if data.get("brand_profile_id") and data["brand_profile_id"] != profile.get("id"):
            failures.append("Canonical brand_profile_id disagrees with selected profile")
        profile_assets = profile.get("assets", {})
        if not isinstance(profile_assets, dict):
            raise ReportError("Brand profile assets must be an object")
        if revision == 2 and "combined_logo" not in profile_assets:
            raise ReportError("Revision-2 brand profile requires assets.combined_logo")
        media_hashes = {hashlib.sha256(archive.read(part)).hexdigest() for part in archive.namelist() if part.startswith("ppt/media/")} if revision == 1 else set()
        # Revision 2 requires the original combined source, not baked color variants.
        selected_assets = profile_assets.items() if revision == 1 else [("combined_logo", profile_assets["combined_logo"])]
        for name, asset in selected_assets:
            if not isinstance(asset, dict) or not isinstance(asset.get("path"), str) or not asset["path"].strip():
                raise ReportError(f"Brand asset {name} requires a nonempty path")
            asset_path = (selected_path.parent / asset["path"]).resolve()
            source = asset_path.read_bytes()
            actual_hash = hashlib.sha256(source).hexdigest()
            checked = {"name": name, "path": str(asset_path), "sha256": actual_hash}
            assets.append(checked)
            expected_hash = asset.get("sha256")
            if actual_hash != expected_hash:
                failures.append(f"Brand asset {name} does not match profile sha256")
            if revision == 1:
                if actual_hash not in media_hashes:
                    failures.append(f"Brand asset {name} is not present as original image bytes in PPT")
                continue
            from PIL import Image
            with Image.open(asset_path) as image:
                image.load()
                transparent = image.mode == "RGBA" and image.getchannel("A").getextrema()[0] == 0
                checked.update({"image_mode": image.mode, "transparent_pixels": transparent})
                if not transparent:
                    failures.append("Revision-2 combined_logo source must be RGBA with transparent pixels")
            for number, part in enumerate(slide_parts, 1):
                slide = ET.fromstring(archive.read(part))
                uses.extend(_visible_logo_uses(archive, number, part, slide, expected_hash))
            if not uses:
                failures.append("Revision-2 combined_logo original source bytes are not visibly used in any actual slide/layout/master chain")
            for use in uses:
                if "failure" in use:
                    failures.append(f"Brand logo slide {use['slide']} ({use['part']}): {use['failure']}")
        if require_every_slide:
            slide_checks = []
            result["slide_brand_checks"] = slide_checks
            for number, part in enumerate(slide_parts, 1):
                issues = []
                if revision == 2:
                    count = sum(use["slide"] == number for use in uses)
                    check = {"slide": number, "part": part, "visible_original_logo_count": count, "required_original_logo_count": 1, "failures": issues}
                    if count != 1:
                        issues.append(f"Brand coverage slide {number}: expected exactly one visible original combined_logo, found {count}")
                else:
                    slide = ET.fromstring(archive.read(part))
                    visible_hashes = _visible_slide_images(archive, part, slide)
                    visible_names = [asset["name"] for asset in assets if asset["sha256"] in visible_hashes]
                    check = {"slide": number, "part": part, "visible_registered_asset_count": len(visible_names), "visible_registered_assets": visible_names, "minimum_registered_asset_count": 1, "failures": issues}
                    if not visible_names:
                        issues.append(f"Brand coverage slide {number}: expected at least one visible registered brand asset, found 0")
                check["ok"] = not issues
                slide_checks.append(check)
                failures.extend(issues)
            result["every_slide_brand_coverage_checked"] = True
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        failures.append(str(exc))
    result["ok"] = not failures
    return result
