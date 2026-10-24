"""Descriptions for ``sensor_attrs.json`` -- the 77 things ``sensor`` can read.

The *names* come from the enum in ``LAccess.java`` (order and the ``obj`` flag
are taken verbatim).  The one-line descriptions are mine: the game's own docs
are a table of property names with no explanation, and almost every wasted hour
on this project came from guessing what a property means.

Two things this file exists to prevent:

- ``sensor x some-building @heat`` vs ``@shield``: on a force projector ``heat``
  is *not* the reactor heat, it is how much shield the projector has lost.
- ``sensor n cell1 @size`` returns the UTF-16 length when the target is a
  string, so it is not only a building property.

This file is now the **single home of DESC** (name -> short description) and
nothing else: the table itself is generated from the game's own jar by
``tools/sensor_attrs_from_jar.py``, which imports DESC from here.

Do **not** run this file as a script any more.  Its old writer parsed a Java
snapshot and wrote to the *mirror* at
``mindustry-blueprint/tools/sensor_attrs.json`` with a 75-name / v159.3 schema;
running it would silently roll the table back and turn the mirror gate red.

    python tools/sensor_attrs_from_jar.py --check   # verify the real table
    python tools/sensor_attrs_from_jar.py           # regenerate it from the jar
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Mindustry-Source/core/src/mindustry/logic/LAccess.java"
OUT = ROOT / "mindustry-blueprint/tools/sensor_attrs.json"

# name -> (short description, what it is read from)
# "b" = building, "u" = unit, "c" = content, "a" = any object
DESC: dict[str, tuple[str, str]] = {
    "totalItems": ("total number of items held", "b"),
    "firstItem": ("the first item type held (object)", "b"),
    "totalLiquids": ("total liquid amount held", "b"),
    "totalPower": ("stored power", "b"),
    "itemCapacity": ("item capacity", "b"),
    "liquidCapacity": ("liquid capacity", "b"),
    "powerCapacity": ("battery capacity", "b"),
    "powerNetStored": ("power stored in the whole grid", "b"),
    "powerNetCapacity": ("grid battery capacity", "b"),
    "powerNetIn": ("grid power input per tick", "b"),
    "powerNetOut": ("grid power output per tick", "b"),
    "ammo": ("ammo count", "b"),
    "ammoCapacity": ("ammo capacity", "b"),
    "currentAmmoType": ("loaded ammo type (object)", "b"),
    "memoryCapacity": ("number of cells in this memory block", "b"),
    "health": ("current health", "b u"),
    "maxHealth": ("maximum health", "b u"),
    "heat": ("reactor heat 0..1; on a force projector, the shield it has LOST", "b"),
    "shield": ("current shield", "b u"),
    "armor": ("armor value", "u"),
    "efficiency": ("efficiency multiplier 0..1", "b"),
    "progress": ("crafting progress 0..1", "b"),
    "timescale": ("processor speed multiplier", "b"),
    "rotation": ("facing, 0..3", "b"),
    "x": ("tile x", "b u"),
    "y": ("tile y", "b u"),
    "velocityX": ("horizontal speed", "u"),
    "velocityY": ("vertical speed", "u"),
    "shootX": ("x of the current shoot target", "u"),
    "shootY": ("y of the current shoot target", "u"),
    "cameraX": ("camera x (world processors, privileged on some builds)", "a"),
    "cameraY": ("camera y", "a"),
    "cameraWidth": ("camera width in world units", "a"),
    "cameraHeight": ("camera height in world units", "a"),
    "displayWidth": ("canvas width in pixels", "b"),
    "displayHeight": ("canvas height in pixels", "b"),
    "bufferSize": ("entries a message block can hold", "b"),
    "operations": ("instructions executed so far", "b"),
    "size": ("block size in tiles; UTF-16 length when the target is a string", "b c"),
    "solid": ("1 if the block is solid", "b"),
    "dead": ("1 when the unit is dead AND ALSO when it is null -- not an existence test", "u"),
    "range": ("attack range in world units", "b u"),
    "shooting": ("1 while firing", "u"),
    "boosting": ("1 while boosting", "u"),
    "mineX": ("x of the tile being mined", "u"),
    "mineY": ("y of the tile being mined", "u"),
    "mining": ("1 while mining", "u"),
    "buildX": ("x of the tile being built", "u"),
    "buildY": ("y of the tile being built", "u"),
    "pingX": ("x of the player's last map ping (~157.4+)", "a"),
    "pingY": ("y of the player's last map ping (~157.4+)", "a"),
    "pingText": ("text of the player's last map ping (~157.4+)", "a"),
    "building": ("the building the unit is standing on / building (object)", "u"),
    "breaking": ("1 while deconstructing", "u"),
    "speed": ("movement speed", "u"),
    "team": ("team (object)", "b u"),
    "type": ("content type (object) -- compare with @conveyor etc.", "b u c"),
    "flag": ("the value stored by ucontrol flag", "u"),
    "flying": ("1 while airborne", "u"),
    "controlled": ("0 none, 1 processor, 2 player, 3 command", "u"),
    "controller": ("controlling entity (object): the processor, or the unit itself", "u"),
    "name": ("content name as a string", "b u c"),
    "payloadCount": ("number of payloads carried", "u"),
    "payloadType": ("first payload's type (object)", "u"),
    "totalPayload": ("total number of payload blocks in a container", "b"),
    "payloadCapacity": ("payload capacity", "u"),
    "maxUnits": ("unit cap; huge when read from a wave team", "b"),
    "id": ("content id", "b u c"),
    "selectedBlock": ("block selected in the player's build menu (object)", "a"),
    "selectedRotation": ("rotation selected in the build menu", "a"),
    "bulletLifetime": ("lifetime of the unit's last bullet", "u"),
    "bulletTime": ("age of the unit's last bullet", "u"),
    "enabled": ("whether the block is enabled (writable via control)", "b"),
    "shoot": ("issue a shoot at x,y (writable)", "u"),
    "shootp": ("issue a shoot at a unit (writable)", "u"),
    "config": ("block config (object; writable via control config)", "b"),
    "color": ("block colour (writable)", "b"),
}

TARGET = {"b": "building", "u": "unit", "c": "content", "a": "any"}


def _target(key: str) -> str:
    """DESC keys are space separated when a property reads from two kinds."""
    return " / ".join(TARGET[k] for k in key.split())


def _legacy_main() -> int:
    """Dead code, kept for the git history: the old Java-snapshot writer.

    It wrote a 75-name / v159.3 table straight into the *mirror* copy, so any
    run would turn the mirror gate red.  Do not call it.
    """
    src = SRC.read_text(encoding="utf-8")
    body = src[src.index("public enum LAccess{"):src.index("public final String[] params;")]

    entries: list[dict] = []
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("//") or line.startswith("public enum"):
            continue
        m = re.match(r"^([a-zA-Z][\w]*)\((.*)\)$", line)
        if m:
            name, raw = m.group(1), m.group(2)
            obj = raw.lstrip().startswith("true")
            params = re.findall(r'"([^"]*)"', raw)
        else:
            m = re.match(r"^([a-zA-Z][\w]*)$", line)
            if not m:
                continue
            name, obj, params = m.group(1), False, []
        desc, target = DESC.get(name, ("", "a"))
        entries.append({
            "name": name,
            "obj": obj,
            "params": params,
            "target": _target(target),
            "desc": desc,
        })

    dupes = sorted({e["name"] for e in entries if [x["name"] for x in entries].count(e["name"]) > 1})
    missing = [e["name"] for e in entries if not e["desc"]]
    data = {
        "source": "Mindustry v159.3 (git 5811844), core/src/mindustry/logic/LAccess.java",
        "note": ("descriptions are hand-written from the source behaviour; the game "
                 "documents only the names. `params` non-empty = readable AND settable "
                 "through `control`."),
        "access": {e["name"]: e for e in entries},
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(entries)} sensor properties -> {OUT.relative_to(ROOT)}")
    if dupes:
        print("!! parsed twice:", ", ".join(dupes))
    if missing:
        print("!! no description:", ", ".join(missing))
    return 0


def main() -> int:
    """Refuse to write: the real table comes from the jar, not from this file."""
    print("!! tools/sensor_from_source.py no longer writes sensor_attrs.json.",
          file=sys.stderr)
    print("   it now only holds DESC; the table is generated from the jar:",
          file=sys.stderr)
    print("       python tools/sensor_attrs_from_jar.py --check", file=sys.stderr)
    print("       python tools/sensor_attrs_from_jar.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
