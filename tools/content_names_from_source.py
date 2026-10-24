#!/usr/bin/env python
"""content_names.json -- every content name a sensor operand can resolve to.

Why this file exists: mlogcheck.py has to tell three cases apart when it looks
at "sensor result target @name":

  * @name is a LAccess attribute (tools/sensor_attrs.json) -> a property read;
  * @name is a Content (item/liquid/block/unit/status) -> the game takes the
    OTHER branch of SenseI.run (LExecutor.java:692-693): an item/liquid reads
    the building stock ("sensor n vault1 @copper" is legal and common), a
    block/unit asks for the payload count, and a building with no such
    container reads NaN (BuildingComp.java:2144-2153);
  * @name is unknown -> the destination is written null. The source snapshot
    (SenseI.run, LExecutor.java:680-719) shows neither branch taken, i.e. no
    assignment at all, but v160.7 was MEASURED to overwrite it (`set d 77` then
    `sensor d vault1 @nosuchthing` leaves d null) -- trust the measurement;
    see out/takeover-20261024/15-sensor-link-oracle.md.

The names come from the v160.7 game dump that already ships in data/game/
(made by out/_dump_game.py) and are then verified against the Java literals in
Mindustry-Source -- a name that is not a quoted literal in its content file is
reported under "unverified" rather than trusted blindly. Status effects come
from tools/status_names.json (StatusEffects.java).

The output must be self-contained: mlogcheck.py runs from copies that ship
neither data/ nor Mindustry-Source.

Usage:
  python tools/content_names_from_source.py          # write tools/content_names.json
  python tools/content_names_from_source.py --check  # exit 1 if the file is stale
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
OUT = TOOLS / "content_names.json"
DATA = ROOT / "data" / "game"
SRC = ROOT / "Mindustry-Source" / "core" / "src" / "mindustry" / "content"

#: category -> (data/game file, Java file the names should appear in as literals)
SOURCES = (
    ("item", "items.json", "Items.java"),
    ("liquid", "liquids.json", "Liquids.java"),
    ("block", "blocks.json", "Blocks.java"),
    ("unit", "units.json", "UnitTypes.java"),
)


def _quoted(name: str) -> str:
    return '"' + name + '"'


def _names(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("blocks") or data.get("items") or list(data.values())
    return [str(rec["name"]).lower() for rec in data
            if isinstance(rec, dict) and "name" in rec]


def build() -> dict:
    names: dict[str, list[str]] = {}
    sources: dict[str, str] = {}
    unverified: dict[str, list[str]] = {}
    for category, data_file, java_file in SOURCES:
        data_path = DATA / data_file
        if not data_path.exists():
            print("!! missing " + data_path.relative_to(ROOT).as_posix())
            names[category] = []
            continue
        java_path = SRC / java_file
        literals = java_path.read_text(encoding="utf-8") if java_path.exists() else ""
        every = _names(data_path)
        # Every dumped name counts as a Content -- a real name the game knows must
        # never be reported as unknown. The ones the Java split does not show as a
        # literal are kept AND listed under "unverified"; they are usually
        # generated names (build1, ore-copper) or placeholders (dummy).
        bad = [n for n in every if _quoted(n) not in literals]
        names[category] = every
        label = data_path.relative_to(ROOT).as_posix() + " (v160.7 dump)"
        if java_path.exists():
            label += " + " + java_path.relative_to(ROOT).as_posix()
        sources[category] = label
        if bad:
            unverified[category] = bad

    statuses: list[str] = []
    sn = TOOLS / "status_names.json"
    if sn.exists():
        data = json.loads(sn.read_text(encoding="utf-8"))
        statuses = sorted({str(n).lower() for n in (data.get("status") or [])})
        sources["status"] = "tools/status_names.json (StatusEffects.java)"
    else:
        print("!! missing tools/status_names.json -- statuses left empty")

    version = ""
    meta_path = DATA / "meta.json"
    if meta_path.exists():
        version = str(json.loads(meta_path.read_text(encoding="utf-8")).get("version") or "")

    doc = {
        "_source": "derived by tools/content_names_from_source.py",
        "_why": ("sensor resolves its third operand against LAccess first; a Content takes the "
                 "other branch of SenseI.run, and an unknown name leaves the destination "
                 "written null (measured on v160.7: it overwrites the old value)"),
        "version": version,
        "sources": sources,
        "counts": {},
        "items": names.get("item", []),
        "liquids": names.get("liquid", []),
        "blocks": names.get("block", []),
        "units": names.get("unit", []),
        "statuses": statuses,
    }
    doc["counts"] = {
        "item": len(doc["items"]),
        "liquid": len(doc["liquids"]),
        "block": len(doc["blocks"]),
        "unit": len(doc["units"]),
        "status": len(doc["statuses"]),
    }
    if unverified:
        doc["unverified"] = unverified
    return doc


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=1) + chr(10)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the file would change")
    args = ap.parse_args(argv)
    text = render()
    rel = OUT.relative_to(ROOT).as_posix()
    if args.check:
        if not OUT.exists():
            print("!! " + rel + " is missing")
            return 1
        if OUT.read_text(encoding="utf-8") != text:
            print("!! " + rel + " is stale -- rerun without --check")
            return 1
        print("ok " + rel + " is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    doc = json.loads(text)
    print("wrote " + rel + ": " + ", ".join(k + " " + str(v) for k, v in doc["counts"].items()))
    for cat, bad in (doc.get("unverified") or {}).items():
        shown = ", ".join(bad[:12]) + (" ..." if len(bad) > 12 else "")
        print("  ~ " + str(len(bad)) + " " + cat + " name(s) not a literal in source: " + shown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
