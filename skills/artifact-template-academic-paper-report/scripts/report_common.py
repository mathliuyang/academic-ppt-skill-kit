"""Canonical report data validation shared by authoring and read-only checks."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path


class ReportError(ValueError):
    pass


def normalize(text: str) -> str:
    """Ignore layout whitespace only; keep punctuation, case and all content."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value, label: str, minimum: float, inclusive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReportError(f"{label} must be a finite number")
    if value < minimum or (not inclusive and value == minimum):
        raise ReportError(f"{label} must be {'at least' if inclusive else 'greater than'} {minimum}")
    return float(value)


def _strings(value, label: str, required: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(t, str) or not t.strip() for t in value):
        raise ReportError(f"{label} must be an array of nonempty strings")
    if required and not value:
        raise ReportError(f"{label} must not be empty")
    return value


def load_report(path: Path, enforce_budget: bool = True) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"Cannot read report JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ReportError("Report must be an object with schema_version: 1")
    for field in ("report_title", "audience", "scenario"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ReportError(f"{field} must be a nonempty string")
    for field in ("presenter", "institution"):
        data.setdefault(field, "")
        if not isinstance(data[field], str):
            raise ReportError(f"{field} must be a string; leave it empty if unknown")
    if "brand_profile_id" in data and (not isinstance(data["brand_profile_id"], str) or not data["brand_profile_id"].strip()):
        raise ReportError("brand_profile_id must be a nonempty string when supplied")
    if "brand_asset_revision" in data and (type(data["brand_asset_revision"]) is not int or data["brand_asset_revision"] < 1):
        raise ReportError("brand_asset_revision must be a positive integer when supplied")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise ReportError("metadata must be an object")
    data["target_seconds"] = _number(data.get("target_seconds"), "target_seconds", 0, False)
    data["reserved_seconds"] = _number(data.get("reserved_seconds", 10), "reserved_seconds", 0)
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ReportError("slides must be a nonempty array")
    for index, slide in enumerate(slides, 1):
        if not isinstance(slide, dict) or isinstance(slide.get("slide"), bool) or slide.get("slide") != index:
            raise ReportError(f"slides[{index - 1}].slide must be consecutive integer {index}")
        if not isinstance(slide["slide"], int):
            raise ReportError(f"slide {index}: slide must be an integer")
        if not isinstance(slide.get("title"), str) or not slide["title"].strip():
            raise ReportError(f"slide {index}: title must be a nonempty string")
        slide["screen_text"] = _strings(slide.get("screen_text"), f"slide {index} screen_text")
        slide["paragraphs"] = _strings(slide.get("paragraphs"), f"slide {index} paragraphs", True)
        slide["duration_seconds"] = _number(slide.get("duration_seconds"), f"slide {index} duration_seconds", 0, False)
        for field in ("cues", "emphasis"):
            slide[field] = _strings(slide.get(field, []), f"slide {index} {field}")
        speech = "\n".join(slide["paragraphs"])
        for term in slide["emphasis"]:
            if term not in speech:
                raise ReportError(f"slide {index}: emphasis {term!r} does not occur in spoken paragraphs")
        sources = slide.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ReportError(f"slide {index}: sources must contain evidence or an explicit non-scientific source record")
        for source in sources:
            if isinstance(source, str) and source.strip():
                continue
            if not isinstance(source, dict) or not any(isinstance(v, str) and v.strip() for k, v in source.items() if k in {"path", "file", "url", "doi", "source", "description", "title"}):
                raise ReportError(f"slide {index}: source needs a nonempty path/file/url/doi/source/description/title")
            if "page" in source and (isinstance(source["page"], bool) or not isinstance(source["page"], int) or source["page"] < 1):
                raise ReportError(f"slide {index}: source page must be a one-based integer")
            if "crop" in source:
                crop = source["crop"]
                if not isinstance(crop, list) or len(crop) != 4:
                    raise ReportError(f"slide {index}: crop must be [x0,y0,x1,y1]")
                crop = [_number(v, f"slide {index} crop", 0) for v in crop]
                if crop[0] >= crop[2] or crop[1] >= crop[3]:
                    raise ReportError(f"slide {index}: crop must have positive width and height")
    timing = timing_summary(data)
    if enforce_budget and timing["total_with_reserve_seconds"] > data["target_seconds"] + 1e-8:
        raise ReportError(f"Timing exceeds target: {timing['total_with_reserve_seconds']:g}s including reserve > {data['target_seconds']:g}s")
    return data


def timing_summary(data: dict) -> dict:
    duration = sum(s["duration_seconds"] for s in data["slides"])
    total = duration + data["reserved_seconds"]
    return {"slides_seconds": duration, "reserved_seconds": data["reserved_seconds"], "total_with_reserve_seconds": total, "target_seconds": data["target_seconds"], "within_budget": total <= data["target_seconds"] + 1e-8, "meaning": "Planned timing only, not measured rehearsal. Slide duration already includes media playback; reserve is added once."}


def emphasis_runs(text: str, terms: list[str]) -> list[tuple[str, bool]]:
    """Use union of matches so overlapping emphasis never duplicates speech."""
    flags = [False] * len(text)
    for term in terms:
        start = 0
        while True:
            start = text.find(term, start)
            if start < 0:
                break
            flags[start:start + len(term)] = [True] * len(term)
            start += 1
    if not text:
        return []
    runs = []
    start = 0
    for index in range(1, len(text) + 1):
        if index == len(text) or flags[index] != flags[start]:
            runs.append((text[start:index], flags[start]))
            start = index
    return runs
