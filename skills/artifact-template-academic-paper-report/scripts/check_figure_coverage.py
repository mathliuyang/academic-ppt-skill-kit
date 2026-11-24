#!/usr/bin/env python3
"""Compare a paper figure inventory with the slide placements reviewed by the author."""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

KEY_COLUMNS = ("paper", "section", "panel")


def read_rows(path, fields):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(fields).issubset(reader.fieldnames or []):
            raise ValueError(f"{path}: required columns: {', '.join(fields)}")
        for row in reader:
            values = {f: (row.get(f) or "").strip() for f in fields}
            if not all(values.values()):
                raise ValueError(f"{path}:{reader.line_num}: required field is blank")
            if values["section"] not in ("main", "supplement"):
                raise ValueError(f"{path}:{reader.line_num}: section must be main or supplement")
            yield values


def key_for(row):
    return tuple(row[column] for column in KEY_COLUMNS)


def audit(inventory_path, placements_path, max_slide):
    inventory = {}
    for row in read_rows(inventory_path, (*KEY_COLUMNS, "expected")):
        key = key_for(row)
        if key in inventory:
            raise ValueError(f"Duplicate inventory entry: {key}")
        if row["expected"] not in ("yes", "no"):
            raise ValueError(f"{key}: expected must be yes or no")
        inventory[key] = row["expected"] == "yes"
    if not any(inventory.values()):
        raise ValueError("Inventory must contain at least one expected panel")

    placements = defaultdict(set)
    for row in read_rows(placements_path, (*KEY_COLUMNS, "slide", "area")):
        key = key_for(row)
        slide = int(row["slide"])
        if not 1 <= slide <= max_slide:
            raise ValueError(f"{key}: slide {slide} is outside 1–{max_slide}")
        if row["area"] not in ("main", "backup"):
            raise ValueError(f"{key}: area must be main or backup")
        placements[key].add((slide, row["area"]))

    summaries = []
    for paper, section in sorted({key[:2] for key in inventory}):
        expected = sorted(key for key, required in inventory.items() if key[:2] == (paper, section) and required)
        summaries.append({
            "paper": paper,
            "section": section,
            "expected": len(expected),
            "on_main_slides": sum(any(area == "main" for _, area in placements.get(key, ())) for key in expected),
            "backup_only": sum(bool(placements.get(key)) and all(area == "backup" for _, area in placements[key]) for key in expected),
            "missing": [key[2] for key in expected if not placements.get(key)],
        })
    unregistered = sorted(set(placements) - set(inventory))
    return {"ok": not unregistered and all(not group["missing"] for group in summaries),
            "groups": summaries, "unregistered_placements": unregistered}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory_csv", type=Path)
    parser.add_argument("placements_csv", type=Path)
    parser.add_argument("--slide-count", type=int, required=True)
    args = parser.parse_args()
    if args.slide_count < 1:
        parser.error("--slide-count must be positive")
    try:
        result = audit(args.inventory_csv, args.placements_csv, args.slide_count)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
