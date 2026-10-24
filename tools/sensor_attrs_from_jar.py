# -*- coding: utf-8 -*-
"""Build tools/sensor_attrs.json from the real v160.7 jar -- the 77 LAccess names.

The table used to be built from Mindustry-Source/core/src/mindustry/logic/LAccess.java
(a git checkout), which lagged the shipped game: it had 75 names and missed enabled and
color, so every "sensor x some-block @enabled" in the wild was flagged as
"sensor-not-a-property". This script takes the NAME SET from the jar the emulator
actually runs (out/_server160.jar -> mindustry/logic/LAccess.class) and only the
metadata (obj / params / description) from the Java source, then cross-checks the two.

Why the jar wins: GlobalVars.java:146-148 puts "@" + sensor.name() for every LAccess
constant, so the spellings a program can use are exactly the enum constant names in the
class file -- nothing more, nothing less, no aliases.

Requires the jar (gitignored, see README):  python tools/sensor_attrs_from_jar.py
Check without writing:                      python tools/sensor_attrs_from_jar.py --check
"""
from __future__ import annotations

import json
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "out/_server160.jar"
JAVA = ROOT / "Mindustry-Source/core/src/mindustry/logic/LAccess.java"
OUT = ROOT / "tools/sensor_attrs.json"
CLS = "mindustry/logic/LAccess.class"

# Names the v159.3 Java checkout lacked (so the old 75-entry table lacked them).
# Pinned rather than derived, so a rebuild produces the same provenance markers.
LEGACY_ADDED = ("enabled", "color")

import sensor_from_source as SFS  # noqa: E402  DESC / TARGET live here (one home)

TARGET = SFS.TARGET


def _skip_constant_pool(data: bytes) -> int:
    """Return the offset just past the constant pool."""
    cnt = struct.unpack(">H", data[8:10])[0]
    pos, k = 10, 1
    while k < cnt:
        tag = data[pos]
        if tag == 1:
            pos += 3 + struct.unpack(">H", data[pos + 1:pos + 3])[0]
        elif tag in (7, 8, 16, 19, 20):
            pos += 3
        elif tag == 15:
            pos += 4
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            pos += 5
        elif tag in (5, 6):
            pos += 9
            k += 1
        else:
            raise SystemExit("bad constant-pool tag %d at %d" % (tag, pos))
        k += 1
    return pos


def _utf8_at(data: bytes, cp_start: int, index: int) -> str:
    """Resolve one CONSTANT_Utf8 entry by its 1-based constant-pool index."""
    cnt = struct.unpack(">H", data[8:10])[0]
    pos, k = cp_start, 1
    while k < cnt:
        tag = data[pos]
        if tag == 1:
            ln = struct.unpack(">H", data[pos + 1:pos + 3])[0]
            if k == index:
                return data[pos + 3:pos + 3 + ln].decode("utf-8", "replace")
            pos += 3 + ln
        elif tag in (7, 8, 16, 19, 20):
            pos += 3
        elif tag == 15:
            pos += 4
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            pos += 5
        elif tag in (5, 6):
            pos += 9
            k += 1
        else:
            raise SystemExit("bad constant-pool tag %d at %d" % (tag, pos))
        k += 1
    raise KeyError(index)


def _enum_fields(data: bytes) -> list[str]:
    """Field names of the class that carry ACC_ENUM, in declaration order."""
    cp_start = 10
    pos = _skip_constant_pool(data)
    pos += 6                                   # access_flags, this_class, super_class
    n_if = struct.unpack(">H", data[pos:pos + 2])[0]
    pos += 2 + 2 * n_if
    n_fields = struct.unpack(">H", data[pos:pos + 2])[0]
    pos += 2
    names = []
    for _ in range(n_fields):
        flags, name_i = struct.unpack(">HH", data[pos:pos + 4])
        na = struct.unpack(">H", data[pos + 6:pos + 8])[0]
        pos += 8
        for _ in range(na):
            pos += 2
            ln = struct.unpack(">I", data[pos:pos + 4])[0]
            pos += 4 + ln
        if flags & 0x4000:                     # ACC_ENUM
            names.append(_utf8_at(data, cp_start, name_i))
    return names


def jar_names() -> list[str]:
    if not JAR.exists():
        raise SystemExit("jar not found: %s\n  it is gitignored; copy the v160.7 server jar to out/_server160.jar" % JAR)
    with zipfile.ZipFile(JAR) as z:
        return _enum_fields(z.read(CLS))


def java_meta() -> dict[str, dict]:
    src = JAVA.read_text(encoding="utf-8")
    head = "public enum LAccess{"
    body = src[src.index(head) + len(head):src.index("public final String[] params;")]
    meta: dict[str, dict] = {}
    for line in body.splitlines():
        line = line.split("//")[0].strip().rstrip(",;").strip()
        if not line:
            continue
        m = re.match(r"^([a-zA-Z][\w]*)\((.*)\)$", line)
        if m:
            name, raw = m.group(1), m.group(2)
            meta[name] = {"obj": raw.lstrip().startswith("true"),
                          "params": re.findall(r'"([^"]*)"', raw)}
        elif re.match(r"^[a-zA-Z][\w]*$", line):
            meta[line] = {"obj": False, "params": []}
    return meta


def build() -> dict:
    names = jar_names()
    meta = java_meta()
    old = {}
    if OUT.exists():
        old = (json.loads(OUT.read_text(encoding="utf-8")).get("access") or {})
    access: dict[str, dict] = {}
    jar_only, missing_desc = [], []
    for idx, name in enumerate(names):
        m = meta.get(name)
        if m is None:
            jar_only.append(name)
            m = {"obj": False, "params": []}
        desc, target = SFS.DESC.get(name, ("", "a"))
        if not desc:
            missing_desc.append(name)
        entry = {
            "name": name,
            "obj": bool(m["obj"]),
            "params": list(m["params"]),
            "target": " / ".join(TARGET[x] for x in target.split()),
            "desc": desc,
        }
        if name in LEGACY_ADDED:
            entry["source"] = ("%s!%s (ACC_ENUM field %d/%d, v160.7) + Mindustry-Source/"
                               "core/src/mindustry/logic/LAccess.java (obj/params)"
                               % (JAR.name, CLS, idx + 1, len(names)))
        access[name] = entry
    dropped = [n for n in old if n not in access]
    added = [n for n in access if n not in old] if old else list(LEGACY_ADDED)
    if jar_only:
        print("!! in the jar but not the Java checkout:", ", ".join(jar_only))
    if dropped:
        print("!! dropped (in the old table, absent from the jar):", ", ".join(dropped))
    if missing_desc:
        print("!! no description:", ", ".join(missing_desc))
    return {
        "source": "Mindustry v160.7 (%s -> %s, %d ACC_ENUM constants)" % (JAR.name, CLS, len(names)),
        "legacy_source": ("Mindustry v159.3 (git 5811844), core/src/mindustry/logic/LAccess.java"
                          " -- the original 75-entry table; descriptions were written against it"),
        "version": "v160.7",
        "note": ("descriptions are hand-written from the source behaviour; the game documents only the names. "
                 "params non-empty = readable AND settable through control. Names come from the shipped jar: "
                 "GlobalVars.java:146-148 registers exactly @ + LAccess.name(), so there are no aliases."),
        "added_2026_10_25": list(LEGACY_ADDED),
        "note_added": ("enabled/color are in the v160.7 jar but were missing from the v159.3 checkout the"
                       " old table was built from; they caused 253 false sensor-not-a-property WARNs."),
        "access": access,
    }


def main() -> int:
    check = "--check" in sys.argv[1:]
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    old_names = []
    if OUT.exists():
        old_names = list((json.loads(OUT.read_text(encoding="utf-8")).get("access") or {}))
    new_names = list(data["access"])
    added = [n for n in new_names if n not in old_names] or ([] if len(old_names) == len(new_names) else [])
    removed = [n for n in old_names if n not in new_names]
    print("%d LAccess names from the jar; old table had %d" % (len(new_names), len(old_names)))
    if added:
        print("added:", ", ".join(added))
    if removed:
        print("removed:", ", ".join(removed))
    if check:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if cur == text:
            print("ok %s is up to date" % OUT.relative_to(ROOT))
            return 0
        print("STALE %s differs from the jar; run without --check" % OUT.relative_to(ROOT))
        return 1
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s (%d bytes)" % (OUT.relative_to(ROOT), len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
