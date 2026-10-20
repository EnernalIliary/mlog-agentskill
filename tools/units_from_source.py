"""Extract unit stats from `UnitTypes.java` into `unit_attrs.json`.

Why this exists: writing logic starts with *picking a unit*. `ubind @flare` vs
`ubind @mace` is a decision about speed, health, payload and whether the thing
flies -- and before this table the only source was my memory of the game.

Only fields that the source actually sets are recorded; anything absent is the
engine default, which is printed from `UnitType.java` so "absent" is
interpretable instead of ambiguous.

Beyond the raw numbers this also records what a unit *does*: its abilities
(repair field, unit spawn, shield...) and its status-effect immunities. Those are
the two things logic most often needs and least often gets right -- "can I set
@mace on fire" is an immunities lookup, not a guess.

Run:  python tools/units_from_source.py [--check]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "Mindustry-Source/core/src/mindustry"
UNITS = SRC / "content/UnitTypes.java"
TYPE = SRC / "type/UnitType.java"
OUT = pathlib.Path(__file__).resolve().parent / "unit_attrs.json"

# fields worth knowing before you write logic for a unit
FIELDS = ("speed", "health", "armor", "hitSize", "itemCapacity", "flying",
          "mineSpeed", "mineTier", "buildSpeed", "accel", "drag",
          "boostMultiplier", "payloadCapacity", "range",
          "rotateSpeed", "omniMovement", "canBoost", "lowAltitude")

_START = re.compile(r'^(\s*)(\w+) = new UnitType\("([a-z0-9-]+)"\)\{\{')
_NUM = r"(-?\d+(?:\.\d+)?)f?"


def defaults() -> dict[str, str]:
    """Engine defaults, parsed from the field declarations in UnitType.java.

    Declarations are grouped (`float speed = 1.1f, boostMultiplier = 1f;`), so
    each group is split before matching -- a naive per-field regex otherwise
    picks up the *next* field's value, which is how the first attempt reported
    `health -> 1f`.
    """
    t = TYPE.read_text("utf-8", errors="replace")
    out: dict[str, str] = {}
    for m in re.finditer(r"^\s*(?:public|protected)?\s*(?:float|int|boolean)\s+([^;]+);",
                         t, re.M):
        decl = m.group(1)
        if "(" in decl or "{" in decl:
            continue
        for part in decl.split(","):
            q = re.match(r"\s*(\w+)\s*=\s*([^,]+)$", part.strip())
            if not q:
                continue
            name, value = q.group(1), q.group(2).strip()
            out.setdefault(name, value.rstrip("f"))
    return out


def unit_blocks(text: str) -> list[tuple[str, str, list[str]]]:
    """Slice `x = new UnitType("x"){{ ... }};` bodies.

    The closing brace is `}};` (double-brace initializer), and its indent must be
    matched against the *opening* line's indent rather than hard-coded -- the
    first version assumed `};` at 8 spaces and silently extracted zero units.
    """
    lines = text.split("\n")
    blocks: list[tuple[str, str, list[str]]] = []
    cur: tuple[str, str, list[str]] | None = None
    indent = 0
    for line in lines:
        if cur is None:
            m = _START.match(line)
            if m:
                indent = len(m.group(1))
                cur = (m.group(2), m.group(3), [])
            continue
        if line.strip() in ("}};", "};") and len(line) - len(line.lstrip()) <= indent:
            blocks.append(cur)
            cur = None
            continue
        cur[2].append(line)
    return blocks


def scalar(body: list[str], field: str) -> str | None:
    pat = re.compile(r"^\s*" + field + r"\s*=\s*" + _NUM + r"\s*;")
    for line in body:
        m = pat.match(line)
        if m:
            return m.group(1)
    if re.search(r"^\s*" + field + r"\s*=\s*true\s*;", "\n".join(body), re.M):
        return "true"
    return None


def _clean(v: str) -> str:
    """`55f` / `55.0f` -> `55` -- the trailing f is Java, not a number the reader wants."""
    v = v.rstrip("f")
    if v.endswith(".0"):
        v = v[:-2]
    return v


def weapons(body: list[str]) -> dict:
    """One entry per ``new Weapon()`` in the unit body.

    A unit can carry several weapons, and the numbers that matter are often *not*
    constructor arguments: `quad` writes `bullet = new BasicBulletType()` and then
    sets `damage` / `speed` inside the bullet's own `{{ }}` block.  Reading only
    the constructor arguments is why this table said "1 weapon, reload 55t" and
    nothing else for a long time.
    """
    text = "\n".join(body)
    # `new Weapon("name"){{` is the v7 form; splitting on the literal
    # "new Weapon()" only caught the 5 nameless ones and made the table say
    # "5 armed units" out of 39.
    chunks = re.split(r"new Weapon\s*\(", text)[1:]
    out: dict = {"count": len(chunks), "list": []}
    for ch in chunks:
        w: dict = {}
        m = re.search(r"^\s*reload\s*=\s*" + _NUM, ch, re.M)
        if m:
            w["reload"] = _clean(m.group(1))
        m = re.search(r"bullet\s*=\s*new\s+(\w+)\s*\(([^)]*)\)", ch)
        tail = ch
        if m:
            w["bullet"] = m.group(1)
            args = [_clean(a.strip()) for a in m.group(2).split(",") if a.strip()]
            pos = [a for a in args if re.fullmatch(r"-?\d+(\.\d+)?", a)]
            if len(pos) >= 2:
                w["speed"], w["damage"] = pos[0], pos[1]
            tail = ch[m.end():]
        for key in ("damage", "speed", "lifetime", "pierce", "shots",
                    "inaccuracy", "ammoMultiplier", "hitSize"):
            if key in w:
                continue
            mm = re.search(r"\b" + key + r"\s*=\s*" + _NUM, tail)
            if mm:
                w[key] = _clean(mm.group(1))
        m = re.search(r"\bshots\s*=\s*(\d+)", ch)
        if m:
            w["shots"] = m.group(1)
        if w:
            out["list"].append(w)
    if out["list"]:
        first = out["list"][0]
        out["reload"] = first.get("reload")
        out["bullet"] = first.get("bullet")
        out["bullet_speed"] = first.get("speed")
        out["bullet_damage"] = first.get("damage")
    return out


def abilities(body: list[str]) -> list[dict]:
    """`new RepairFieldAbility(50f, 60f*8f, 60f)` -> {ability, args}.

    Arguments stay as raw source text: they mix plain numbers, arithmetic like
    `60f*8f` and booleans, and inventing one numeric value for `60f*8f` would be
    a number the game never computes at runtime.
    """
    text = "\n".join(body)
    out: list[dict] = []
    for m in re.finditer(r"new\s+(\w+)Ability\s*\(([^;)]*)\)", text):
        name = m.group(1)
        args = [a.strip() for a in m.group(2).split(",") if a.strip()]
        rec: dict = {"ability": name}
        if args:
            rec["args"] = args
        out.append(rec)
    return out


def immunities(body: list[str]) -> list[str]:
    """`immunities(StatusEffects.wet, StatusEffects.burning)` -> ['wet', 'burning']."""
    text = "\n".join(body)
    out: list[str] = []
    for m in re.finditer(r"immunities\(([^)]*)\)", text):
        for name in re.findall(r"StatusEffects\.(\w+)", m.group(1)):
            if name not in out:
                out.append(name)
    return out


def build() -> dict:
    text = UNITS.read_text("utf-8", errors="replace")
    dflt = defaults()
    units: dict[str, dict] = {}
    for field, name, body in unit_blocks(text):
        rec: dict = {}
        for f in FIELDS:
            v = scalar(body, f)
            if v is not None:
                rec[f] = v
        w = weapons(body)
        if w.get("count"):
            rec["weapons"] = w
        ab = abilities(body)
        if ab:
            rec["abilities"] = ab
        im = immunities(body)
        if im:
            rec["immune_to"] = im
        units[name] = rec
    return {
        "_source": "Mindustry-Source/core/src/mindustry/content/UnitTypes.java",
        "_note": ("only fields the source sets are listed; absent ones are the "
                  "engine default in `defaults`. `abilities.args` is raw source "
                  "text (they contain arithmetic like `60f*8f`)."),
        "count": len(units),
        "defaults": {k: v for k, v in dflt.items()
                     if k in FIELDS or k in ("speed", "health")},
        "units": units,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="compare against the committed JSON instead of writing")
    args = ap.parse_args()
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if args.check:
        cur = OUT.read_text("utf-8") if OUT.exists() else ""
        same = cur == text
        print(("ok      " if same else "STALE   ") + f"{OUT.name}: {data['count']} units")
        return 0 if same else 1
    OUT.write_text(text, "utf-8")
    print(f"wrote {OUT.name}: {data['count']} units, "
          f"{sum(1 for u in data['units'].values() if 'weapons' in u)} armed, "
          f"{sum(1 for u in data['units'].values() if 'abilities' in u)} with abilities, "
          f"{sum(1 for u in data['units'].values() if 'immune_to' in u)} with immunities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
