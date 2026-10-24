#!/usr/bin/env python
"""
mlogcheck.py -- static analyser for mlog, focused on the mistakes that have
actually shipped broken logic in this workspace.

It is NOT an emulator. It does flow / usage analysis on one processor's code
and reports things a compiler would not: inverted conditions, variables read
before assignment, jumps that land on statements with side effects, unbounded
loops, and unit-control executed without a live `ubind`.

Usage
-----
  python tools/mlogcheck.py 逻辑.mlog
  python tools/mlogcheck.py --blueprint out/无线超.msch     # check a whole schematic
  python tools/mlogcheck.py --dir logic-corpus/by-blueprint # (md dumps, not for this)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------- #
# instruction tables
# --------------------------------------------------------------------------- #

# statements that WRITE into their first operand (or a named output slot)
# key -> parameter positions that are outputs (-1 = first operand)
OUTPUT_SLOTS: dict[str, list[int]] = {
    "sensor": [0], "getlink": [0], "op": [1], "set": [0], "select": [0],
    "lookup": [1], "read": [0], "packcolor": [0], "unpackcolor": [0, 1, 2, 3],
    "radar": [-1], "uradar": [-1], "ulocate": [-4, -3, -2, -1],
    "sensor_": [0],
}

# statements with a side effect on the world / processor state
SIDE_EFFECT = {
    "ubind", "ucontrol", "uradar", "ulocate", "control", "write", "read",
    "print", "printflush", "draw", "drawflush", "jump", "end", "stop",
    "wait", "setrate", "getlink", "sensor", "op", "set", "select", "lookup",
    "spawn", "setblock", "getblock", "setprop", "setrule", "effect", "status",
    "explosion", "fetch", "sync", "message", "format", "printchar",
}

# unit-control statements that silently do nothing unless @unit is bound
NEEDS_UNIT = {"ucontrol", "uradar", "ulocate"}

# ---- loop progress ------------------------------------------------------- #
# Instructions that can change something a line earlier in the same loop would
# read again. If a loop body contains any of these, the loop can make progress
# and there is nothing to say about it.

# Reads whose value comes from outside this processor (a handshake source).
EXTERNAL_READ = {"sensor", "getlink", "lookup", "read", "radar", "uradar",
                 "getblock"}

# ucontrol sub-actions that refresh the 10s control timer
UNIT_ACTIONS_NO_TIMER = {"uradar"}

OP_UNARY = {"abs", "sign", "log", "log10", "floor", "ceil", "round",
            "sqrt", "rand", "sin", "cos", "tan", "asin", "acos", "atan", "not"}
OP_BINARY = {"add", "sub", "mul", "div", "idiv", "mod", "emod", "pow",
             "equal", "notEqual", "land", "lessThan", "lessThanEq",
             "greaterThan", "greaterThanEq", "strictEqual",
             "shl", "shr", "ushr", "or", "and", "xor",
             "max", "min", "angle", "angleDiff", "len", "noise", "logn"}

# built-in / magic symbols that are always in scope.
# `true` / `false` ARE here: GlobalVars.init() registers them as plain constants
# (`putEntry("false", 0)`, `putEntry("true", 1)` at GlobalVars.java:54-55), and
# `LAssembler.var()` returns that constant before ever reaching putVar(). So
# `jump 34 equal aat true` really is `aat == 1` -- correct code.
BUILTIN = re.compile(
    r"^(@|_|null$|true$|false$|-?\d+(\.\d+)?$|\"[^\"]*\"$|%[0-9a-fA-F]+$)")

# reserved words that appear in operand positions but are NOT variables
KEYWORDS = {
    # jump condition operators
    "equal", "notEqual", "lessThan", "lessThanEq", "greaterThan",
    "greaterThanEq", "strictEqual", "always",
    # ulocate / locate modes and block flags
    "building", "ore", "spawn", "damaged",
    "core", "storage", "generator", "turret", "factory", "repair",
    "battery", "reactor", "drill", "shield",
    # ucontrol actions
    "idle", "stop", "move", "approach", "pathfind", "autoPathfind", "boost",
    "target", "targetp", "itemDrop", "itemTake", "payDrop", "payTake",
    "payEnter", "mine", "flag", "build", "deconstruct", "getBlock", "within",
    "unbind",
    # control actions
    "enabled", "shoot", "shootp", "config", "color",
    # draw/print/etc.
    "clear", "stroke", "line", "rect", "lineRect", "poly", "linePoly",
    "triangle", "image", "print", "translate", "scale", "rotate", "reset",
    # layers / misc
    "block", "floor", "ore_", "building_", "type", "apply", "clear_",
}

# Built-ins GlobalVars registers with privileged=true. A normal processor that
# reads one gets the `null` constant, not the value: GlobalVars.putEntry(name,
# value, true) at :81-90, and get(name, privileged) at :253-256 returns
# `vars.get("null")` when `!privileged && privilegedNames.contains(name)`.
# Nothing throws -- the branch just never takes, which is invisible until the
# logic is run against a real server/client.
PRIVILEGED_VARS = {
    "@server", "@client", "@clientLocale", "@clientUnit", "@clientName",
    "@clientTeam", "@clientMobile", "@clientMusicPlaying",
}

# draw sub-commands: `draw <sub> ...` -- the sub-command is not an operand
DRAW_SUBS = {
    "clear", "color", "col", "stroke", "line", "rect", "lineRect", "poly",
    "linePoly", "triangle", "image", "print", "translate", "scale", "rotate",
    "reset",
}

# keywords that appear in operand positions for other statements
OTHER_KEYWORDS = {
    "player", "unit", "unitCount", "playerCount", "build", "enemy", "ally",
    "any", "attacker", "flying", "boss", "ground", "distance", "health",
    "shield", "armor", "maxHealth", "remove", "pos", "shape", "texture",
    "minimap", "shapeText", "world", "natural", "effect", "source", "target",
    "command", "object", "none", "default", "on", "off", "down", "up",
    "left", "right",
}
KEYWORDS |= DRAW_SUBS | OTHER_KEYWORDS

JMP_RE = re.compile(r"^jump\s+(-?\d+)\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?$")
OP_RE = re.compile(r"^op\s+(\S+)\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?$")


class Finding:
    __slots__ = ("sev", "line", "code", "msg")

    def __init__(self, sev: str, line: int, code: str, msg: str):
        self.sev, self.line, self.code, self.msg = sev, line, code, msg

    def __str__(self):
        return f"  [{self.sev}] L{self.line:<4} {self.code:<44} {self.msg}"


def strip_comment(line: str) -> str:
    # A BOM on the first line would otherwise become part of the mnemonic
    # ("\ufeffset"), and no rule or opcode tally would recognise it.
    line = line.lstrip("\ufeff")
    out, in_str = [], False
    for ch in line:
        if ch == '"':
            in_str = not in_str
        elif ch == "#" and not in_str:
            break
        out.append(ch)
    return "".join(out).strip()


def defs_of(c: str) -> list[str]:
    """Variables this statement WRITES."""
    p = tokenize(c)
    if not p:
        return []
    # Drop surplus tokens: the game fills the statement's fields by index and
    # never looks at the rest, so `control enabled reactor enable 0 by bicker`
    # does not read `by`/`bicker` -- the author appended a signature there.
    limit = ARITY.get(p[0].lower())
    if limit is not None and len(p) > limit + 1:
        p = p[:limit + 1]
    op = p[0]
    # `draw triangle a b c d e f` placed after `end` is a DECLARATION TABLE:
    # LParser calls var() on every argument, creating the variable slots.
    if op == "draw" and len(p) > 1 and p[1] == "triangle":
        return _vars(p[2:8])
    if op == "op" and len(p) >= 3:
        return [p[2]]
    if op == "ulocate" and len(p) >= 9:
        return [x for x in p[5:9] if x not in ("0", "null")]
    if op in ("sensor", "getlink", "set", "read", "packcolor"):
        return [p[1]] if len(p) >= 2 and p[1] != "0" else []
    if op == "select":
        return [p[1]] if len(p) >= 2 and p[1] != "0" else []
    # `lookup unit u i` -- index 0 is the ContentType keyword, the result is
    # index 1 (LStatements.java:875-909). Treating `unit` as the destination
    # made every `ubind u` look like a read of an undeclared variable.
    if op == "lookup":
        return [p[2]] if len(p) >= 3 and p[2] != "0" else []
    if op == "unpackcolor" and len(p) >= 6:
        return [x for x in p[1:5] if x != "0"]
    if op in ("radar", "uradar"):
        return [p[-1]] if p[-1] not in ("0", "null") else []
    if op == "ucontrol" and len(p) >= 3:
        # ucontrol within x y r result -> 4th slot is an output
        if p[1] == "within" and len(p) >= 6:
            return [p[5]]
        # `ucontrol getBlock x y block building floor` writes THREE outputs
        # (LExecutor.java:491-509: p3/p4/p5 get the tile's block, its building,
        # and its floor-or-ore). The statement has no `type` input at all, so
        # `ucontrol getBlock x y scatter f 0` assigns both `scatter` and `f`.
        if p[1] == "getBlock" and len(p) >= 7:
            return [x for x in p[4:7] if x != "0"]
    # Generic fallback: `defs` in the semantics table are ARG-relative indices
    # (0 = first argument after the mnemonic). Any output slot not special-cased
    # above still counts as a definition: `getblock block b ax+ ay` writes `b`,
    # not `block` (layer is the first field, LStatements.java:1359-1398).
    # Without this, `b` looked undeclared and every such program gained a
    # phantom "typo" in the A layer.
    spec = SPECS.get(op.lower())
    if spec:
        got = []
        for idx in spec.get("defs", []):
            j = idx + 1
            if j < len(p) and p[j] not in ("0", "null"):
                got.append(p[j])
        if got:
            return got
    return []


QUOTED = re.compile(r'"[^"]*"')

# Everything LAssembler.var() turns into a constant instead of a variable:
#   parseDouble() handles 0x / 0b (and their +/- forms) and %rrggbb / %[name]
#   colour literals before falling back to Strings.parseDouble, which accepts
#   ordinary float syntax (1e5, .5, +3). A token that parses as a number is
#   never a variable read -- treating it as one produced hard errors on
#   `write 0x00003008 bank1 5` in a real blueprint pack.
_NUMERIC = re.compile(
    r"^(?:"
    r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
    r"|[+-]?0[xX][0-9a-fA-F]+"
    r"|[+-]?0[bB][01]+"
    r"|%[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?"
    r"|%\[[A-Za-z]+\]"
    r")$")


def is_number(t: str) -> bool:
    return bool(_NUMERIC.match(t))


def tokenize(line: str) -> list[str]:
    """Split into tokens, keeping a quoted string as ONE token."""
    out, i, n = [], 0, len(line)
    while i < n:
        ch = line[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j = line.find('"', i + 1)
            if j == -1:
                out.append(line[i:])
                break
            out.append(line[i:j + 1])
            i = j + 1
        else:
            j = i
            while j < n and not line[j].isspace():
                j += 1
            out.append(line[i:j])
            i = j
    return out


def _vars(tokens) -> list[str]:
    """Filter operand tokens down to things that can actually be variables."""
    out = []
    for t in tokens:
        if not t:
            continue
        if is_number(t) or t in KEYWORDS or BUILTIN.match(t):
            continue
        if t.startswith('"'):                     # string literal
            continue
        out.append(t)
    return out


_PUNCT_NAME = re.compile(r"^[^A-Za-z0-9_@\"]*$")


def _load_arity() -> dict[str, int]:
    """Tokens each mnemonic actually consumes (from `instr_semantics.json`).

    Anything past the declared `arity` is parsed and then dropped by the game
    (`LParser` fills the statement's fields by index and never reads the rest),
    which is exactly why `op rand g 255 b` does not read `b` -- and why authors
    can sign a program by appending `by bicker` to a real statement.
    """
    try:
        raw = (Path(__file__).with_name("instr_semantics.json")).read_text("utf-8")
        data = json.loads(raw)
    except Exception:
        return {}
    out: dict[str, int] = {}
    for name, spec in (data.get("instructions") or {}).items():
        n = spec.get("arity")
        if isinstance(n, int) and n >= 0:
            out[name.lower()] = n
    return out


ARITY = _load_arity()


def _load_sensor_props() -> set[str]:
    """The `LAccess` attributes a `sensor` instruction can read.

    `sensor` compiles to `SenseI`, which looks the third operand up in
    `LAccess`; anything else (an item, a block, a typo) reads null. The table
    ships next to this file as `sensor_attrs.json` (`access`, one entry per
    `LAccess` constant -- 77 in v160.7, rebuilt from the shipped jar by
    `tools/sensor_attrs_from_jar.py`).
    """
    try:
        raw = (Path(__file__).with_name("sensor_attrs.json")).read_text("utf-8")
        return set((json.loads(raw).get("access") or {}).keys())
    except Exception:
        return set()


SENSOR_PROPS = _load_sensor_props()


def _load_content_names() -> dict[str, str]:
    """`name -> "item" | "liquid" | "block" | "unit" | "status"`.

    `sensor` resolves its third operand against `LAccess` first; a Content takes
    the OTHER branch of `SenseI.run` (`LExecutor.java:692-693`), and an unknown
    name writes null into the destination (measured on v160.7; the Java checkout
    is older than the shipped jar -- see
    `out/takeover-20261024/15-sensor-link-oracle.md`). The table ships as
    `content_names.json` (generated by `tools/content_names_from_source.py`
    from the v160.7 dump in `data/game/`, verified against the Java literals)
    because this file is also read from copies that ship neither `data/` nor
    `Mindustry-Source/`.
    """
    try:
        raw = (Path(__file__).with_name("content_names.json")).read_text("utf-8")
        data = json.loads(raw)
    except Exception:  # the file is optional: never break analysis over it
        return {}
    out: dict[str, str] = {}
    for key, category in (("items", "item"), ("liquids", "liquid"),
                          ("blocks", "block"), ("units", "unit"),
                          ("statuses", "status")):
        for name in data.get(key) or []:
            out.setdefault(str(name).lower(), category)
    return out


CONTENT_NAMES = _load_content_names()


def _load_specs() -> dict[str, dict]:
    """`defs` / `uses` / `tokens` per mnemonic, from `instr_semantics.json`.

    Needed because a statement's first argument is often an ENUM KEYWORD, not a
    variable: `setmarker rotation mid 45 1 0` names a control kind, and
    `fetch buildCount max team 0 @sorter` names a fetch mode. Without the table
    those keywords were reported as undeclared variables -- 18 of the 310 hard
    errors in the blueprint-pack scan were that bug.
    """
    try:
        raw = (Path(__file__).with_name("instr_semantics.json")).read_text("utf-8")
        data = json.loads(raw)
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for name, spec in (data.get("instructions") or {}).items():
        if isinstance(spec, dict):
            out[name.lower()] = spec
    return out


SPECS = _load_specs()

#: Mnemonic -> the parameter that names a *block link* rather than an ordinary
#: variable. The game resolves these with its link table (`validLink`), so an
#: unbound name is the null object and the instruction silently has no target.
#: Deliberately NOT listed (and why): `jump.dest` is a label, `setblock.block`
#: is a Content name, `ulocate.outBuild`/`getlink.output` are outputs,
#: `ucontrol.p1` may be a unit, and `fetch.index`/`lookup.id` are numbers.
LINK_PARAMS: dict[str, str] = {
    "drawflush": "target", "printflush": "target", "sensor": "from",
    "control": "target", "radar": "building", "setprop": "of",
    "bullet": "from", "read": "cell", "write": "cell",
}


def _load_link_slots(specs: dict[str, dict]) -> dict[str, frozenset[int]]:
    """mnemonic -> parameter indices that name a link (from instr_semantics.json)."""
    out: dict[str, frozenset[int]] = {}
    for mnemonic, param in LINK_PARAMS.items():
        spec = specs.get(mnemonic) or {}
        params = spec.get("params") or []
        if param not in params:
            continue
        idx = params.index(param)
        if idx in (spec.get("defs") or []):
            continue
        # params are the operands after the mnemonic, so param 0 is token 1
        out[mnemonic] = frozenset({idx + 1})
    return out


LINK_SLOTS = _load_link_slots(SPECS)

#: Statement -> the first vanilla build that understands it. Only the ones with a
#: citable release note are listed (see `mindustry-blueprint/BUILDS.md`); everything
#: else is assumed to exist since the v7 baseline (146), which is where most of the
#: player base sat for a year.
#: The reporting baseline: build 146, the first *released* v7 build (7.0 Build
#: 146, 2023-09-04) -- where most of the player base sat for a year. A statement
#: that exists there is part of the baseline and is never reported; only
#: statements added *after* it can make a blueprint un-runnable for someone.
#: Kept as a constant so the rule reads as "newer than the baseline", not as a
#: magic 147.
BASELINE_BUILD = 146

STATUS_NAMES: set[str] = set()
try:
    _status_json = json.loads(
        (Path(__file__).with_name("status_names.json")).read_text(encoding="utf-8"))
    STATUS_NAMES = {str(n).lower() for n in _status_json.get("status", [])}
except Exception:  # the file is optional: never break analysis over it
    STATUS_NAMES = set()


def _load_op_builds() -> dict[str, int]:
    """Operators that arrived after the v7 baseline (`emod`, `ushr` = v150)."""
    try:
        data = json.loads((Path(__file__).with_name("instr_semantics.json"))
                          .read_text(encoding="utf-8"))
        return {k: v["min_build"] for k, v in (data.get("ops") or {}).items()
                if isinstance(v.get("min_build"), int)}
    except Exception:
        return {}


OP_MIN_BUILD: dict[str, int] = _load_op_builds()

MIN_BUILD: dict[str, int] = {
    k: v["min_build"] for k, v in SPECS.items() if isinstance(v.get("min_build"), int)
}


def build_floor(stmts: list[tuple[int, str]]) -> tuple[int, list[str]]:
    """Oldest vanilla build that understands every statement here, plus which ones.

    A schematic has no version field, so this is inferred from the statements it
    uses. Anything at or below BASELINE_BUILD is "always there" and returns
    `(0, [])`, i.e. nothing to say.
    """
    hits: list[tuple[str, int]] = []
    for _, c in stmts:
        words = c.split()
        if not words:
            continue
        mnem = words[0].lower()
        b = MIN_BUILD.get(mnem)
        name = mnem
        # `op` is one statement but 45 operators, and two of them (`emod`,
        # `ushr`) are v150 additions while the rest go back to v6. The gate has
        # to look at the operator, not just the mnemonic.
        if mnem == "op" and len(words) > 1:
            ob = OP_MIN_BUILD.get(words[1])
            if ob and (not b or ob > b):
                b = ob
                name = f"op {words[1]}"
        if b:
            hits.append((name, b))
    if not hits:
        return 0, []
    floor = max(b for _, b in hits)
    if floor <= BASELINE_BUILD:
        return floor, []
    # Only the statements that *decide* the floor and are newer than the
    # baseline. Every instruction now carries a min_build (the v7 baseline is
    # 146), so listing all of them would report `set`/`print`/`end` as the
    # reasons a program "needs build 146".
    users = sorted({n for n, b in hits if b == floor and b > BASELINE_BUILD})
    return floor, sorted(set(users))


def _effective_params(p: list[str]) -> int:
    """How many parameters this instruction actually consumes, for the form in use.

    A statement's syntax can be longer than its useful arguments. `control` has
    six slots but only three are ever meaningful (`type`, `target`, `p1`): the
    building's `control()` receives p2..p4 and ignores them for every type that
    matters here. `ucontrol` is worse -- each sub-command uses a different
    subset. Authors park their signature in those dead slots, so a name found
    there is a hidden byline, not a bug (user-confirmed convention: a name that
    is not a string still shows up in the editor's variable list).
    """
    mnem = p[0].lower()
    if mnem == "control":
        return 3
    spec = SPECS.get(mnem) or {}
    subs = spec.get("subcommands") or {}
    if subs and len(p) > 1:
        sub = subs.get(p[1]) or subs.get(p[1].lower())
        if sub is not None:
            if mnem == "ucontrol" and p[1].lower() == "autopathfind":
                return 3          # 3rd argument is a literal flag, ignored
            # `semantic_uses` is the smaller set that actually changes
            # behaviour: `ucontrol flag <value>` reads one argument even though
            # the statement carries six slots (`LUnitControl.java:20`).
            if "semantic_uses" in sub:
                sem = [int(i) for i in (sub.get("semantic_uses") or [])]
                if sem:
                    return max(sem) + 1
                if not (sub.get("defs") or sub.get("tokens")):
                    return 1          # sub-command takes no argument at all
            idx = ([int(i) for i in (sub.get("uses") or [])]
                   + [int(i) for i in (sub.get("defs") or [])]
                   + [int(k) for k in (sub.get("tokens") or {})])
            if idx:
                return max(idx) + 1
    idx = ([int(i) for i in (spec.get("uses") or [])]
           + [int(i) for i in (spec.get("defs") or [])]
           + [int(k) for k in (spec.get("tokens") or {})])
    if idx:
        return max(idx) + 1
    arity = spec.get("arity")
    return arity if isinstance(arity, int) else max(len(p) - 1, 0)


def _surplus_names(c: str) -> set[str]:
    """Names sitting in parameter slots the instruction never actually uses."""
    p = tokenize(c)
    if len(p) < 3:
        return set()
    return {t for t in p[1 + _effective_params(p):]
            if not is_number(t) and not QUOTED.match(t) and t not in ("0", "null")}


# Parameters the game reads as a BOOLEAN (`p1.bool()`). An unset name there is
# 0, i.e. always false -- a constant, not a missing value. `ucontrol payTake`
# is the classic case: it only ever takes "pick up units?" as a boolean, so
# `ucontrol payTake upt ...` with `upt` never assigned just means "always
# buildings". Values are indices into the tokenised statement.
_BOOL_PARAM: dict[tuple[str, str], int] = {
    ("ucontrol", "paytake"): 2,
    ("ucontrol", "boost"): 2,
    ("control", "enabled"): 3,
    ("status", ""): 1,
    ("setflag", ""): 2,
    ("spawnwave", ""): 3,
}


def _bool_slot(p: list[str]) -> int | None:
    """Index of this statement's boolean parameter, if it has one."""
    if not p:
        return None
    mnem = p[0].lower()
    if mnem == "ulocate":
        # `ulocate building <group> <enemy> <ore> ...` -- the enemy flag is the
        # 3rd argument. `ore`/`spawn`/`damaged` forms have no boolean.
        return 3 if len(p) > 1 and p[1].lower() == "building" else None
    sub = p[1].lower() if len(p) > 1 else ""
    for key in ((mnem, sub), (mnem, "")):
        if key in _BOOL_PARAM:
            return _BOOL_PARAM[key]
    return None


def _comment_stmt(c: str) -> bool:
    """True for `set <punctuation-name> <prose>` -- mlog's de-facto comment.

    The game only treats `#` as a comment, so authors who want a visible note
    write `set // 装载电池组` and let the right-hand side read as null. The
    destination name being pure punctuation is the tell; it also shows up in
    the editor's variable list, which is the point.
    """
    p = tokenize(c)
    return len(p) >= 2 and p[0] == "set" and bool(_PUNCT_NAME.match(p[1]))


def uses_of(c: str) -> list[str]:
    """Variables this statement READS (operators/keywords filtered out)."""
    p = tokenize(c)
    if not p:
        return []
    # See defs_of: tokens past the declared arity are inert filler.
    limit = ARITY.get(p[0].lower())
    if limit is not None and len(p) > limit + 1:
        p = p[:limit + 1]
    if not p:
        return []
    op = p[0]
    if op == "jump":
        # jump <target> <op> <value> <compare>
        # `always` takes NO operands -- the trailing "x false" is filler
        if len(p) >= 3 and p[2] == "always":
            return []
        return _vars(p[3:5])
    if op == "op":
        # arity depends on the operator name: the game parses every token on
        # the line and then hands UnaryOp only `a`, so `op rand flag 1000 b`
        # never reads `b`. Counting it as a read made a clean program fail with
        # "`b` is read here but is never assigned anywhere".
        if len(p) > 1 and p[1] in OP_UNARY:
            return _vars(p[3:4])
        return _vars(p[3:5])
    if op == "ulocate":
        return _vars([p[3], p[4]])
    if op == "set":
        return _vars(p[2:3])
    if op == "sensor":
        return _vars([p[2]])
    if op == "getlink":
        return _vars([p[2]])
    if op in ("select", "lookup"):
        return _vars(p[3:6])
    if op == "read":
        return _vars([p[3]])
    if op == "write":
        return _vars([p[1], p[3]])
    if op == "radar":
        return _vars([p[5]])
    if op == "uradar":
        return []
    if op == "ucontrol":
        if len(p) > 1 and p[1] == "within":
            return _vars(p[2:5])
        if len(p) > 1 and p[1] == "getBlock":
            return _vars(p[2:4])
        return _vars(p[2:7])
    if op == "control":
        return _vars(p[2:7])
    if op == "draw":
        # `draw triangle <names...>` is a declaration table, not a read.
        # Every other draw sub-command takes numbers/colours/content names, so
        # there is nothing meaningful to read -- skip the whole statement.
        return []
    if op == "fetch" and len(p) >= 6:
        # fetch <type> <result> <team> <index> <extra>.  For the counting types
        # FetchI.run only ever touches `extra` (the UnitType/Block filter) and
        # `result`/`team`; `index` is never read, so a name sitting there is an
        # inert parameter, not an undeclared read.  The maintainer caught this on
        # `fetch unitCount 信标数量 1 A @oct` ("A 是无效参数，不影响").
        if p[1].lower().endswith("count"):
            return _vars([p[2], p[3], p[5]])
        return _vars([p[2], p[3], p[4], p[5]])
    if op in ("print", "printflush", "drawflush", "format", "localeprint",
              "printchar", "playsound", "playmusic", "setmarker", "makemarker",
              "effect", "explosion", "status", "spawn", "bullet", "setprop",
              "setrule", "fetch", "sync", "message", "cutscene", "spawnwave",
              "weatherset", "weathersense", "getflag", "setflag", "setrate",
              "query", "clientdata", "getblock", "setblock", "localeprint"):
        # Prefer the semantics table here: the first N arguments are often enum
        # keywords (`setmarker rotation`, `fetch ... max`), and reporting those
        # as undeclared variables is a false positive. Fall back to "everything
        # after the mnemonic is a read" only when the table knows nothing.
        spec = SPECS.get(op)
        if spec is not None and "uses" in spec:
            idx = [i for i in (spec.get("uses") or []) if 1 + i < len(p)]
            return _vars([p[1 + i] for i in idx])
        return _vars(p[1:9])
    return _vars(p[1:6])


_CMP_OPS = {"lessthan", "lessthaneq", "greaterthan", "greaterthaneq",
            "equal", "notequal", "strictequal"}
_REACTOR_LINK = re.compile(r"^(?:nuclear-)?reactor\d*$", re.I)


def _num_or_none(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _guard_threshold(stmts: list[tuple[int, str]], var: str) -> float | None:
    """The constant this program compares a sensed value against."""
    for _, code in stmts:
        q = code.split()
        if len(q) < 5:
            continue
        m = q[0].lower()
        if m == "jump":
            op, a, b = q[2].lower(), q[3], q[4]
        elif m == "op":
            op, a, b = q[1].lower(), q[3], q[4]
        else:
            continue
        if op not in _CMP_OPS:
            continue
        for x, y in ((a, b), (b, a)):
            if x == var:
                n = _num_or_none(y)
                if n is not None:
                    return n
    return None


def analyse(lines: list[str], links: list[str] | None = None, ipt: int = 2) -> list[Finding]:
    # Labels are resolved by prepare(), the only place that knows a label is not
    # a statement. Resolving them again here used to map a label to its LINE
    # index while prepare() used the STATEMENT index, so every `jump idle` on a
    # program with blank lines turned into an out-of-range jump to a line number.
    stmts = prepare(lines)
    out: list[Finding] = []
    n = len(stmts)

    # `jump <label>` with no such label: LParser resolves a missing label to -1
    # (LParser.java:195-198 `jumpLocations.get(location, -1)`) and JumpI.run()
    # guards `if(address != -1)`, so the jump does nothing at all and execution
    # falls through. Almost always a renamed or mistyped label.
    for _idx, (_i, _c) in enumerate(stmts):
        _t = _c.split()
        if len(_t) < 2 or _t[0].lower() != "jump":
            continue
        try:
            int(_t[1])
        except ValueError:
            out.append(Finding(
                "WARN", _i + 1, "no-target-jump",
                f"`{_t[1]}` is not a label in this program, so the game turns this "
                f"into a jump to -1, which does nothing; execution just falls through"))

    # ---- 病毒逻辑 / virus logic: `ucontrol build ... @this` ---------------
    # The last argument of `ucontrol build` is the config copied onto the new
    # block, so passing `@this` builds a processor configured with THIS
    # program -- one processor that builds processors that build processors.
    # It is not an error (self-replicating factories are a real design) but it
    # is the one line worth seeing before importing somebody else's map, and
    # the community has a name for it, so it gets its own check instead of
    # hiding inside the generic `ucontrol build` warnings.  `@this` reaches the
    # config through a variable just as often as directly, so track both.
    _this_vars = {"@this"}
    for _i, _c in stmts:
        if "@this" in _c:
            _this_vars |= set(defs_of(_c))
    for _idx, (_i, _c) in enumerate(stmts):
        _t = _c.split()
        if len(_t) < 5 or _t[0].lower() != "ucontrol" or _t[1].lower() != "build":
            continue
        if _t[-1] in _this_vars:
            out.append(Finding(
                "INFO", _i + 1, "virus-logic",
                f"`{_t[-1]}` is this processor's own program, so the `{_t[4]}` it builds "
                f"runs the same code and builds more -- 病毒逻辑 (virus logic), "
                f"i.e. self-replication; check the rest of the program before importing "
                f"the map"))

    # Link names are bound by the processor itself, not by an assignment, so
    # they are live from the very first statement. We also auto-detect them by
    # the game's naming rule (internal-name tail + index, e.g. message1, arc1).
    link_vars = set(links or [])
    LINK_RE = re.compile(r"^[A-Za-z_][\w\-]*\d+$")

    def def_of(i: int) -> set[str]:
        return set(defs_of(stmts[i][1]))

    # ---- predecessors (successors are i+1 and, for jump, the target) ------
    preds: list[set[int]] = [set() for _ in range(n)]
    for i, (_, c) in enumerate(stmts):
        m = JMP_RE.match(c)
        succ = []
        if m:
            tgt = int(m.group(1))
            if 0 <= tgt < n:
                succ.append(tgt)
            if m.group(2) != "always":
                succ.append(i + 1)                # fall-through when not taken
        else:
            succ.append(i + 1)
        for s in succ:
            if 0 <= s < n:
                preds[s].add(i)

    # ---- reaching definitions -------------------------------------------
    # REACH[i][v] = set of statement indices that define v and may reach i
    REACH: list[dict[str, set[int]]] = [dict() for _ in range(n)]
    changed = True
    rounds = 0
    while changed and rounds < 200:
        changed = False
        rounds += 1
        for i in range(n):
            acc: dict[str, set[int]] = {}
            for p in preds[i]:
                for v, ds in REACH[p].items():
                    acc.setdefault(v, set()).update(ds)
            # a definition is killed by any other definition of the same var
            for v in {x for p in preds[i] for x in def_of(p)}:
                acc[v] = {p for p in preds[i] if v in def_of(p)}
            if acc != REACH[i]:
                REACH[i] = acc
                changed = True

    # ---- report: read of a variable that is NEVER defined anywhere --------
    # Deliberately weak: full reaching-definition analysis produces far too many
    # false positives on real mlog, which relies on `@counter` relative jumps,
    # loop-carried initialisation, and jump tables. Only flag a variable that no
    # statement in the program ever writes -- that is a guaranteed mistake.
    ever_defined: set[str] = set()
    for _, c in stmts:
        ever_defined |= set(defs_of(c))
    ever_defined |= link_vars

    # Declaration does not require `set`: the assembler's readVar() creates a
    # variable on its first mention anywhere (`vars.get(name, true)`), which is
    # why `draw triangle a b c d e f` works as a compact six-slot table. So the
    # only truly undeclared name is one no statement mentions at all.
    mentioned: set[str] = set(ever_defined)
    for _, c in stmts:
        mentioned |= set(uses_of(c))

    # ---- a name containing '-' can never be a link variable ---------------
    # LogicBlock.getLinkName() builds the link name from the block name's LAST
    # '-'-separated segment (plus its index): `silicon-arc-furnace` -> `furnace1`.
    # So `silicon-arc-furnace1` never binds; the statement silently does nothing.
    _HYPHEN_NAME = re.compile(r"^[A-Za-z_][\w.]*(?:-[\w.]+)+$")
    for _ln, _code in stmts:
        # Strip string literals first: `print "Power Gauge v0-B.2"` tokenises to
        # `v0-B.2`, which is not a link name at all.
        _bare_code = re.sub(r'"[^"]*"', '""', _code)
        for _tok in re.findall(r"\S+", _bare_code):
            if _tok.startswith('"') or _tok.startswith("@"):
                continue
            # A hyphenated name that the program itself assigns is a legal
            # variable (`set needed-icon ""`), not a unbound link.
            if _tok in ever_defined:
                continue
            if _HYPHEN_NAME.match(_tok):
                out.append(Finding(
                    "ERR", _ln + 1, "link-name-hyphen",
                    f"`{_tok}` contains '-': the game derives a link's name from the "
                    f"block name's last hyphenated segment plus its index "
                    f"(`silicon-arc-furnace` -> `furnace1`), so this name never binds "
                    f"and the statement is a silent no-op"))

    # ---- a name used as a link that nothing ever binds ---------------------
    # A link name is not assigned by the program: findLinkName()
    # (`LogicBlock.java:331-360`) / getLinkName() (`:123-135`) build it from the
    # linked block's internal name -- its last '-' segment -- plus a 1-based
    # index, hence `message1`, `arc1`. A name that does not end in a digit can
    # therefore NEVER bind: it is an ordinary variable, value null, and the
    # instruction it feeds has no target. Measured on v160.7
    # (`out/takeover-20261024/15-sensor-link-oracle.md`): an unbound target makes
    # the instruction read null, and every comparison against it is false.
    # This pass is token-based on purpose: uses_of() drops words drawn from
    # KEYWORDS (block flags such as `core`, `storage`, `reactor`), yet in a link
    # slot exactly such a bare word is the dead target.
    for _ln, _code in stmts:
        _p = tokenize(_code)
        if not _p:
            continue
        _link_slots = LINK_SLOTS.get(_p[0].lower())
        if not _link_slots:
            continue
        for _slot in sorted(_link_slots):
            if _slot >= len(_p):
                continue
            _tok = _p[_slot]
            if (is_number(_tok) or _tok == "null" or _tok.startswith("@")
                    or _tok.startswith('"') or _PUNCT_NAME.match(_tok)
                    or _tok in ever_defined or LINK_RE.match(_tok)
                    or _HYPHEN_NAME.match(_tok)):
                continue
            out.append(Finding(
                "WARN", _ln + 1, "link-name-unbindable",
                f"`{_tok}` is the link this `{_p[0].lower()}` acts on, but nothing "
                f"binds it: the program never assigns it, it is not one of this "
                f"processor's links, and it is not shaped like a link name -- the "
                f"game builds those as the block's internal name's last segment "
                f"plus a 1-based index (`vault1`), so a name not ending in a digit "
                f"never binds. Measured on v160.7: the instruction then reads null "
                f"and every comparison against it is false"))

    # ---- `sensor result target @name`: which branch does the game take? -----
    # Measured on v160.7 with the real jar
    # (`out/takeover-20261024/15-sensor-link-oracle.md`,
    # `scenes/sensor_oracle3.py`):
    #   LAccess           -> a real property read (`sensor vault1 @health` -> 495):
    #                        nothing to say;
    #   item / liquid     -> legal and common: `sensor n vault1 @copper` -> 100, a
    #                        vault holding none -> 0: never reported
    #                        (rules/sensor-item-read-is-fine);
    #   block/unit/status -> INFO: a Content, not an LAccess attribute; a
    #                        building with a payload container yields the
    #                        payload count, one without yields null;
    #   unknown name      -> WARN: the destination is written null -- it does
    #                        NOT keep its old value (`set d 77` then a bad sensor
    #                        leaves d null), so every comparison against it is
    #                        false, including `equal x 0` (null counts as 0).
    if SENSOR_PROPS:
        for _ln, _code in stmts:
            _q = _code.split()
            if len(_q) < 4 or _q[0].lower() != "sensor":
                continue
            _prop = _q[3]
            if not _prop.startswith("@"):
                continue
            _name = _prop[1:]
            if _name in SENSOR_PROPS:
                continue
            _cat = CONTENT_NAMES.get(_name.lower())
            if _cat in ("item", "liquid"):
                continue
            if _cat is not None:
                out.append(Finding(
                    "INFO", _ln + 1, "sensor-content-not-a-property",
                    f"`{_prop}` is a {_cat} name -- a Content, not one of the "
                    f"{len(SENSOR_PROPS)} `LAccess` attributes `sensor` reads. On "
                    f"v160.7 a building with a payload container returns the payload "
                    f"count and one without returns null (`sensor x vault1 "
                    f"@hyper-processor` -> null; "
                    f"out/takeover-20261024/15-sensor-link-oracle.md). If a property "
                    f"was meant, this is the wrong spelling"))
                continue
            out.append(Finding(
                "WARN", _ln + 1, "sensor-not-a-property",
                f"`{_prop}` is not a sensor property: `sensor` resolves the third "
                f"operand against `LAccess` (the {len(SENSOR_PROPS)} names like "
                f"`@x`, `@health`, `@totalItems`), and this is neither one of them "
                f"nor any item/liquid/block/unit name. Measured on v160.7: the "
                f"destination is then written null, so every comparison against it "
                f"is false -- `jump ... equal x 0` matches too, because null's "
                f"numeric value is 0 "
                f"(out/takeover-20261024/15-sensor-link-oracle.md)"))

    # ---- read/write @this "name": a string addresses a processor variable ----
    # `LogicBlock.read` looks the name up in `executor.optionalVar(name)`, then
    # falls back to `optionalLink(name)`; `LogicBlock.write` returns silently
    # when the name is not a variable (LogicBlock.java:607-650). Neither path
    # shows up in defs_of(), because the name is a string, not a variable token.
    _SELF_READ = re.compile(r'^read\s+\S+\s+@this\s+"([^"]+)"\s*$')
    _SELF_WRITE = re.compile(r'^write\s+\S+\s+@this\s+"([^"]+)"\s*$')
    for _ln, _code in stmts:
        m = _SELF_READ.match(_code)
        if m:
            name = m.group(1)
            if name not in mentioned and not LINK_RE.match(name):
                out.append(Finding(
                    "INFO", _ln + 1, "self-read-undefined",
                    f'`read ... @this "{name}"` names a variable no statement in '
                    f'this program mentions (a mention anywhere would declare it), '
                    f'so the game returns null (a name ending in a digit would '
                    f'resolve as a link instead)'))
        m = _SELF_WRITE.match(_code)
        if m:
            name = m.group(1)
            if name not in mentioned:
                out.append(Finding(
                    "INFO", _ln + 1, "self-write-noop",
                    f'`write ... @this "{name}"` names a variable this program '
                    f'never mentions; LogicBlock.write returns silently when the '
                    f'name is not a variable, so this statement does nothing'))

    # How is each name USED? A name that only ever appears in `print` is not a
    # mistake: the in-game editor shows every variable of a program in its
    # variable list, so signing a blueprint by printing an unassigned name is a
    # real convention (the print itself outputs "null" -- the point is the list).
    # Likewise names that only appear as `jump ... equal X null`: legal, but the
    # comparison is constant. Everything else (arithmetic, control, sensor...)
    # silently reads 0, which is a genuine mistake.
    use_kinds: dict[str, set[str]] = {}
    for _, c in stmts:
        p = tokenize(c)
        if not p:
            continue
        kind = p[0]
        if kind == "jump" and len(p) >= 3 and p[2] == "always":
            kind = "jump-always"
        for v in uses_of(c):
            use_kinds.setdefault(v, set()).add(kind)

    def _null_guard_only(name: str) -> bool:
        """True if every read of `name` is a jump comparing it against null."""
        for _, c in stmts:
            if name not in uses_of(c):
                continue
            p = tokenize(c)
            if not p or p[0] != "jump" or len(p) < 5:
                return False
            if p[2] not in ("equal", "notEqual"):
                return False
            if "null" not in (p[4], p[5] if len(p) > 5 else ""):
                return False
        return True

    ever_read: set[str] = set()
    for _, c in stmts:
        ever_read |= set(uses_of(c))

    def _constant_guard(c: str) -> bool:
        """A `jump` whose comparison cannot vary: both operands are constants,
        builtins, or names nothing ever assigns. `jump 21 equal colour ender`
        is how one author signs a blueprint AND jumps unconditionally at once.
        """
        p = tokenize(c)
        if not p or p[0] != "jump" or len(p) < 5 or p[2] == "always":
            return False
        if p[2] not in (COND_OPS | {"equal", "notEqual", "strictEqual"}):
            return False
        for tok in (p[3], p[4]):
            if is_number(tok) or tok == "null" or tok.startswith("@"):
                continue
            if LINK_RE.match(tok) or tok in ever_defined:
                return False
        return True

    for i, (orig, c) in enumerate(stmts):
        # `set // read anything` is the de-facto comment idiom: the author names
        # the destination with punctuation so it stands out in the variable
        # list, and the "value" is prose. mlog has no line comments (only `#`),
        # so the right operand is a variable read that outputs null -- harmless
        # and certainly not an undefined-variable error.
        if _comment_stmt(c):
            continue
        # `noop` is literally `LStatements.InvalidStatement` (LStatements.java:48)
        # -- the statement the game substitutes for a line it cannot parse, whose
        # own `build(LAssembler)` returns `NoopI` (an empty `run`). It is usually
        # NOT intentional: it is what is left when logic written for a newer
        # version is opened in an older one and a statement the old parser does
        # not know gets dropped. The program still loads and still runs, so the
        # hole is silent -- worth flagging, never auto-removing.
        if c.split(None, 1)[0].lower() == "noop":
            out.append(Finding(
                "ERR", orig + 1, c,
                "`noop` is the game's InvalidStatement -- the placeholder for a "
                "line it could not parse. Nearly always a statement lost when "
                "logic written for a newer version is opened in an older one, "
                "and such a program is usually dead because the missing line "
                "was doing the work. Open and fix it on the version it was "
                "written for"))
            continue
        surplus = _surplus_names(c)
        p = tokenize(c)
        # `set Madeby mineqwwe` -- the destination is never read anywhere, so
        # the whole statement is a name tag written in the variable list.
        tag = (len(p) >= 3 and p[0] == "set" and p[1] not in ever_read)
        for v in uses_of(c):
            if v in ever_defined:
                continue
            # A name made only of punctuation (`/`, `///`, `//`) is never data;
            # it is a comment marker the author parks in a real argument slot
            # (`control config sorter1 / 0 0 0` clears the sorter). Reporting it
            # as an undeclared variable is noise.
            if _PUNCT_NAME.match(v):
                continue
            # Auto-detect link names by the game's `name + index` convention so
            # plain .mlog files (which carry no link table) don't false-positive.
            # With a blueprint we DO have the table, and a link-shaped name that
            # is not in it is a real dead reference: `control shootp scatter1`
            # in a processor whose only link is `conveyor1` silently does
            # nothing (`LExecutor` requires `exec.build.validLink(b)`).
            if LINK_RE.match(v):
                if links is not None and v not in link_vars:
                    out.append(Finding(
                        "WARN", orig + 1, c,
                        f"`{v}` is shaped like a block link but this processor "
                        f"has no such link (it has: {', '.join(sorted(link_vars)) or 'none'})"))
                continue
            kinds = use_kinds.get(v, set())
            bslot = _bool_slot(p)
            if bslot is not None and len(p) > bslot and p[bslot] == v:
                out.append(Finding(
                    "WARN", orig + 1, c,
                    f"`{v}` is never assigned, and this parameter is read as a "
                    f"boolean -- so it is constantly 0 (false). Harmless if "
                    f"that is the intent; a typo of `true`/`false` lands here"))
                continue
            if v in surplus:
                out.append(Finding(
                    "WARN", orig + 1, c,
                    f"`{v}` sits in a parameter slot this instruction never "
                    f"reads -- ignored at runtime (often a hidden signature)"))
                continue
            if tag:
                out.append(Finding(
                    "INFO", orig + 1, c,
                    f"`{v}` is never assigned, but the destination `{p[1]}` is "
                    f"never read either -- a signature written into the "
                    f"editor's variable list"))
                continue
            if kinds == {"print"}:
                out.append(Finding(
                    "INFO", orig + 1, c,
                    f"`{v}` is never assigned -- signature only (it shows up in "
                    f"the editor's variable list; print outputs `null`)"))
                continue
            if kinds and kinds <= {"print", "printflush"}:
                out.append(Finding(
                    "INFO", orig + 1, c,
                    f"`{v}` is never assigned, so this `printflush` has no valid "
                    f"message block -- and that is NOT a no-op: PrintFlushI clears "
                    f"the print buffer unconditionally (LExecutor.java:1178), so "
                    f"everything queued by `print` is DISCARDED here. A deliberate "
                    f"way to empty the buffer; it also parks the name in the "
                    f"editor's variable list"))
                continue
            if _null_guard_only(v) or _constant_guard(c):
                out.append(Finding(
                    "WARN", orig + 1, c,
                    f"`{v}` is never assigned, so this comparison is constant: an "
                    f"unset variable is 0 and `null` reads as 0, so only `===` "
                    f"tells null from 0 (a constant branch is often a signature)"))
                continue
            if v.lower() in STATUS_NAMES:
                # `status false unmoving @unit 0.1`: the name is a real status
                # effect (StatusEffects.java declares it) but a content constant
                # needs the @ prefix, so a bare name is an ordinary unset
                # variable -- null.  Reported as INFO because the author clearly
                # meant the effect and the line still runs; what is wrong is the
                # spelling, and some builds spell it `@status_<name>`.
                out.append(Finding(
                    "INFO", orig + 1, c,
                    f"`{v}` is the name of a status effect, not a variable: a "
                    f"content constant needs the @ prefix (`@{v}`, and some "
                    f"builds expose it as `@status_{v}` -- check the variable "
                    f"list in the editor), so as written this reads null and "
                    f"the instruction does nothing"))
                continue
            out.append(Finding(
                "ERR", orig + 1, c,
                f"`{v}` is mentioned (so it is declared, with the initial value "
                f"null) but is never assigned anywhere in this program; reading "
                f"it here yields null (and it is not a link or built-in)"))

    # ---- privileged built-ins --------------------------------------------
    # INFO, not WARN: a world processor legitimately reads these, and a .mlog
    # file does not say which block will run it. What is worth saying is that
    # in micro/logic/hyper the value is a null constant -- no error, no warning,
    # the branch simply never runs.
    for i, (orig, c) in enumerate(stmts):
        # A quoted string is data, not a variable read: `print "@clientUnit"`
        # must not be flagged. Only bare @tokens count.
        bare = re.sub(r'"[^"]*"', '""', c)
        hits = sorted({t for t in re.findall(r"@\w+", bare) if t in PRIVILEGED_VARS})
        if hits:
            names = ", ".join(f"`{h}`" for h in hits)
            out.append(Finding(
                "INFO", orig + 1, c,
                f"{names} privileged: only a world processor sees a real value; "
                f"in a micro/logic/hyper processor this reads the null constant "
                f"(GlobalVars.java:81-90) -- fine if this program is meant for a "
                f"world processor"))

    # ---- jump diagnostics (only structural problems) ---------------------
    for i, (orig, c) in enumerate(stmts):
        m = JMP_RE.match(c)
        if not m:
            continue
        tgt = int(m.group(1))
        if tgt == -1:
            continue
        if not (0 <= tgt < n):
            out.append(Finding("ERR", orig + 1, c,
                               f"jump target {tgt} out of range (0..{n-1})"))
            continue
        # Only UNCONDITIONAL into UNCONDITIONAL is a chain: then the second hop
        # is guaranteed and one instruction is spent for nothing. A conditional
        # jump landing on a jump is an ordinary dispatch triangle -- when the
        # condition is false you fall through and never touch the target.
        _hop = stmts[tgt][1].split()
        if (m.group(2) == "always" and _hop[0].lower() == "jump"
                and len(_hop) > 2 and _hop[2] == "always"):
            out.append(Finding("INFO", orig + 1, c,
                               f"this jump is unconditional and lands on another "
                               f"unconditional jump (L{tgt}), so that hop is "
                               f"executed for nothing"))

    # ---- op arity ---------------------------------------------------------
    for i, (orig, c) in enumerate(stmts):
        mo = OP_RE.match(c)
        if not mo:
            continue
        op, a, b = mo.group(1), mo.group(3), mo.group(4)
        want = 2 if op in OP_UNARY else (3 if op in OP_BINARY else None)
        given = 1 + sum(1 for x in (a, b) if x is not None)
        if want is None:
            out.append(Finding("ERR", orig + 1, c, f"unknown op `{op}`"))
        # `given > want` is deliberately silent.  The maintainer audited 29 of
        # these and judged every single one "not worth reporting": an extra
        # operand is what you get when someone edits an operator in place and
        # leaves the old tokens behind, and the game parses the line then hands
        # the operator only the operands it takes.  The rule JSON keeps this as
        # a negative record (`unary-op-extra-operand`) so nobody re-adds it.
        elif given < want:
            out.append(Finding("WARN", orig + 1, c,
                               f"`op {op}` given {given} args, expects {want}"))

    # ---- @dead polarity: NOT reported ------------------------------------
    # Every row of this rule was judged bad by the author (m15434): "这个逻辑使用
    # notequal没问题呀，反向了而已". Both polarities are normal code -- `jump rebind
    # notEqual d 0` jumps when the unit died, `jump act equal d 0` falls through
    # when it did not -- and which one is meant depends on what the target *does*
    # (rebind vs act), not on the operator. Nothing local can tell them apart, so
    # the check is gone rather than downgraded. `rules/dead-polarity.json` keeps
    # the reasoning so it is not re-invented.

    # ---- ulocate hygiene --------------------------------------------------
    for i, (orig, c) in enumerate(stmts):
        mu = re.match(r"^ulocate\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
                      r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", c)
        if not mu:
            continue
        if mu.group(2) in ("0", "null"):
            out.append(Finding("ERR", orig + 1, c,
                               "ulocate arg2 (flag) must be a valid BlockFlag; "
                               "`0` makes the whole instruction invalid"))
        # only complain about discarded coords if the code actually moves to them
        outx, outy = mu.group(5), mu.group(6)
        if outx in ("0", "null") or outy in ("0", "null"):
            uses_move = any(
                re.match(rf"^ucontrol\s+(move|approach)\s+({re.escape(outx)}|{re.escape(outy)})\b",
                         stmts[j][1])
                for j in range(n))
            if uses_move:
                out.append(Finding("ERR", orig + 1, c,
                                   "outX/outY discarded but later used by move/approach"))
        if mu.group(8) in ("0", "null") and mu.group(1) in ("building", "damaged"):
            # find whether an itemDrop/itemTake later uses a link-ish name
            out.append(Finding("INFO", orig + 1, c,
                               "outBuild discarded -- if you need to itemTake/itemDrop "
                               "this building, capture the reference instead"))

    # ---- unit control without any ubind ----------------------------------
    if not any(c.startswith("ubind") for _, c in stmts):
        for i, (orig, c) in enumerate(stmts):
            if c.split()[0] in NEEDS_UNIT:
                out.append(Finding("ERR", orig + 1, c,
                                   f"`{c.split()[0]}` used but there is no `ubind` -> "
                                   f"@unit is null, this silently does nothing"))
                break

    # ---- a back-edge that can never come out --------------------------------
    # `@this` in a jump guard asks "is the bound unit mine". `la.controller` is
    # written in exactly one place -- `UnitControlI.checkLogicAI`
    # (LExecutor.java:322-340, `la.controller = exec.thisv.building()`) -- which
    # is called by `ubind` *and* by every `ucontrol` command. So either one can
    # hand the unit to this processor.
    #
    # Two things decide whether that locks the loop shut:
    #   * polarity. Under `equal`/`strictEqual ... @this` a claimed unit makes
    #     the guard permanently true. Under `notEqual` the same body is the
    #     ordinary "do not steal a unit somebody else drives" idiom: the guard
    #     goes false on the first pass and the loop ends. 9 corpus files are
    #     exactly that shape and all are correct, so `notEqual` stays silent.
    #   * order. The claim only matters if the compared variable is re-read
    #     *after* it. `sensor c @unit @controller` placed before the claim keeps
    #     the pre-claim value, the guard is false and the loop leaves -- safe.
    # So: deadlock iff a claimer sits at j and the compared variable is assigned
    # again at k with j < k <= jump. A nest reports only its outermost loop.
    _POS = {"equal", "strictequal"}
    _READS_CONTROLLER = {"sensor", "read", "set", "op", "select", "lookup",
                         "getlink", "getblock", "radar", "uradar", "ulocate"}
    _NOT_CLAIMING = {"unbind", "within"}     # no longer touch control state >=159.8

    def _claims(words: list[str]) -> bool:
        if not words:
            return False
        m = words[0].lower()
        if m == "ubind":
            return len(words) > 1 and words[1].lower() != "null"
        if m == "ucontrol":
            return not (len(words) > 1 and words[1].lower() in _NOT_CLAIMING)
        return False

    _spin = []
    for i, (orig, c) in enumerate(stmts):
        mj = JMP_RE.match(c)
        if not mj:
            continue
        try:
            tgt = int(mj.group(1))
        except (TypeError, ValueError):
            continue
        if not (0 <= tgt < i):
            continue                       # not a backward branch
        head = c.split()
        if len(head) < 3 or head[2].lower() not in _POS:
            continue                       # only a positive guard can lock in
        if "@this" not in c:
            continue
        watched = [w for w in head[3:5] if w != "@this"]
        claims_at = [k for k in range(tgt, i) if _claims(stmts[k][1].split())]
        if not claims_at:
            continue                       # nothing in the body takes the unit
        if watched:
            senses = [k for k in range(tgt, i)
                      if (w := stmts[k][1].split())
                      and w[0].lower() in _READS_CONTROLLER
                      and watched[0] in w[1:4]]
            if not senses:
                continue                   # value comes from outside: never updates
            last_sense = max(senses)
            if not any(j < last_sense for j in claims_at):
                continue                   # unit is claimed only after the read
        _spin.append((tgt, i, orig, c))
    for tgt, i, orig, c in _spin:
        if any(o[0] <= tgt and i <= o[1] and (o[0], o[1]) != (tgt, i)
               for o in _spin):
            continue                       # inside a wider loop of the same shape
        out.append(Finding(
            "ERR", orig + 1, c,
            f"this loop can never leave: `ubind` or a `ucontrol` command hands "
            f"the bound unit to this processor (UnitControlI.checkLogicAI sets "
            f"the controller), so `@controller` equals `@this` from the first "
            f"pass on and the guard is true forever -- it jumps back to "
            f"L{tgt} instead of falling through, so nothing after "
            f"this line ever runs"))

    # ---- version gate -----------------------------------------------------
    floor, users = build_floor(stmts)
    if floor > BASELINE_BUILD:
        who = ", ".join(sorted(set(users)))
        # Point at the line that needs the build, never at line 0.  A finding the
        # reader has to hunt for is a finding they will skip: both of the ones the
        # maintainer audited were filed at L0 and he answered "shouldn't this
        # point at `format`?".  `users` holds a mnemonic ("format"), an operator
        # ("op emod") or a keyword, so match the mnemonic and, for `op`, the
        # operator name as well.
        want = {u.lower() for u in users}
        at = 0
        for orig, c in stmts:
            t = c.split()
            if not t:
                continue
            head = t[0].lower()
            if head in want or (head == "op" and len(t) > 1
                                and f"op {t[1].lower()}" in want):
                at = orig
                break
        out.append(Finding(
            "INFO", at + 1, stmts[at][1] if at < len(stmts) else "",
            f"version gate: uses {who} -- needs build >= {floor}; on anything "
            f"older the line is replaced by noop and silently does nothing"))

    noop_lines = [orig + 1 for orig, c in stmts
                  if c.strip() and c.split()[0].lower() == "noop"]
    if noop_lines:
        if floor > BASELINE_BUILD:
            # The generic noop ERR already fired; replace it instead of stacking a
            # second finding on the same line -- the point is one conclusion, not
            # two overlapping ones.
            out = [f for f in out if not (f.code.strip().lower() == "noop")]
            out.append(Finding(
                "ERR", noop_lines[0], "noop",
                f"{len(noop_lines)} noop line(s) plus statements that need build "
                f">= {floor} -- this is version drift, not a typo: a line written "
                f"for a newer build was replaced by InvalidStatement when opened on "
                f"an older one, so it now runs as nothing and whatever it did is "
                f"gone. Open the schematic on build >= {floor} to get it back"))
        else:
            out.append(Finding(
                "WARN", noop_lines[0], "noop",
                f"{len(noop_lines)} noop line(s) = InvalidStatement "
                f"(LParser.java:143-147). Three causes: a statement from a NEWER "
                f"build, a privileged world-processor statement sitting in a normal "
                f"processor (LParser.java:150-152), or a mod statement whose mod is "
                f"not loaded"))

    # ---- reactor guard latency: can the check keep up with the heating?
    # NuclearReactor.updateTile() (Mindustry-Source/core/src/mindustry/world/
    # blocks/power/NuclearReactor.java:95-125) heats at `fullness * 0.01` per
    # tick and dies at heat >= 0.999, so a full reactor has ~100 ticks between
    # "cool" and "boom". One `sensor ... @heat` per loop pass means the check
    # interval is (loop body / ipt) ticks; if that exceeds the remaining window
    # the guard is decorative.
    for i, (orig, code) in enumerate(stmts):
        q = code.split()
        if len(q) < 4 or q[0].lower() != "sensor" or q[3].lower() != "@heat":
            continue
        if not _REACTOR_LINK.match(q[2]):
            continue
        acts = any(
            r and r[0].lower() == "control" and len(r) > 2
            and r[1].lower() == "enabled" and r[2] == q[2]
            for r in (c.split() for _, c in stmts)
        )
        if not acts:
            continue
        thresh = _guard_threshold(stmts, q[1])
        if thresh is None:
            continue
        window = int(round((0.999 - thresh) / 0.01))
        if window <= 0:
            continue
        # innermost loop containing the sensor = smallest span among the
        # back-edges that jump over it (find_loop_bounds() returns trip counts,
        # not spans, so the span is measured here)
        body = len(stmts)
        for j, (_, c) in enumerate(stmts):
            m = _BACKJUMP.match(c)
            if not m:
                continue
            tgt = int(m.group(1))
            if 0 <= tgt <= i <= j:
                body = min(body, j - tgt + 1)
        interval = max(1, -(-body // max(1, ipt)))
        if interval <= window:
            continue
        # `reactor1` may be a thorium reactor OR an impact reactor, and the two
        # mean completely different things by `@heat`:
        #   thorium -- a temperature. Uncooled it climbs 0.01/tick and
        #              `kill()`s at 0.999 (NuclearReactor.java:95-125).
        #   impact  -- its warmup, i.e. the power ramp: `sense(LAccess.heat)`
        #              returns `warmup`, and `productionEfficiency = warmup^5`
        #              (ImpactReactor.java:117-120). It never explodes from
        #              heat; max warmup is max output.
        # So the arithmetic below is a promise only when the program proves the
        # type -- and a cutoff on an impact reactor is the opposite mistake: it
        # protects nothing, it just holds the reactor down its ramp.
        proven = any("@thorium-reactor" in c for _, c in stmts)
        impact = any("@impact-reactor" in c for _, c in stmts)
        if impact and not proven:
            cut = re.search(r"control\s+enabled\s+" + re.escape(q[2]) + r"\s+0\b",
                            "\n".join(c for _, c in stmts))
            cap = thresh ** 5
            if cut and cap < 0.95:
                out.append(Finding(
                    "WARN", orig, "",
                    f"capping an impact reactor does not protect it: `{q[2]}` is "
                    f"cut at heat {thresh:g}, but on an impact reactor `@heat` is "
                    f"its warmup and productionEfficiency = warmup^5 "
                    f"(ImpactReactor.java:117-120), so this holds it at "
                    f"{cap * 100:.1f}% output. An impact reactor never explodes "
                    f"from heat; only a thorium reactor does (heat >= 0.999)"))
            continue
        if proven:
            out.append(Finding(
                "WARN", orig, "",
                f"reactor guard is too slow: `{q[2]}` is checked once every "
                f"~{interval} ticks ({body} statements per pass / ipt {ipt}), but "
                f"a full reactor goes from heat {thresh:g} to 0.999 in {window} "
                f"ticks (0.01 per tick, NuclearReactor.java:95-125) -- it can "
                f"explode between two checks. Either move the guard into its own "
                f"short loop or lower the fuel"))
        else:
            out.append(Finding(
                "INFO", orig, "",
                f"`{q[2]}` is checked once every ~{interval} ticks ({body} "
                f"statements per pass / ipt {ipt}); IF that link is a thorium "
                f"reactor, heat {thresh:g} to 0.999 takes only {window} ticks, so "
                f"it could explode between two checks. Nothing here proves the "
                f"type -- on an impact reactor `@heat` is its warmup, a power "
                f"ramp that never explodes -- so this is a question, not a "
                f"verdict"))

    # dedupe, keep order
    # Every finding above was created against the RAW line index (orig + 1),
    # because that is what someone counting in a text editor expects. But `jump
    # N` counts STATEMENTS: labels and blank lines are not statements, so on any
    # program with a label our number and the jump target disagree by the number
    # of label lines before the row -- and a reader checking "is line 13 really a
    # jump?" lands on the wrong line. Report the statement index instead: it is
    # the only number that agrees with the code itself.
    _raw_to_idx = {ln + 1: k for k, (ln, _c) in enumerate(stmts)}
    out = [Finding(f.sev, _raw_to_idx.get(f.line, f.line), f.code, f.msg)
           for f in out]

    seen, uniq = set(), []
    for f in out:
        k = (f.sev, f.line, f.msg)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    order = {"ERR": 0, "SUSPECT": 1, "WARN": 2, "INFO": 3}
    uniq.sort(key=lambda f: (order.get(f.sev, 9), f.line))
    return uniq


_INT = re.compile(r"^-?\d+$")
_SET_COUNTER = re.compile(r"^set\s+@counter\s+(\S+)")
_OP_COUNTER = re.compile(r"^op\s+(\w+)\s+@counter\s+(\S+)\s+(\S+)")


def _counter_target(i: int, c: str, n: int) -> list[int] | None:
    """Successors of a computed `@counter` write, or None if it is not one.

    The executor increments @counter *before* running the instruction, so
    inside statement `i` the register reads `i + 1`.  That makes
    `op add @counter @counter 3` land on `i + 4`, and `set @counter 7` land
    on 7 (absolute).  Anything we cannot resolve to a literal is treated as
    an unknown branch: every statement stays reachable, which is the only
    honest answer for a dispatch table.
    """
    m = _SET_COUNTER.match(c)
    if m and m.group(1) != "@counter":
        arg = m.group(1)
        if _INT.match(arg):
            tgt = int(arg)
            return [tgt] if 0 <= tgt < n else []
        return list(range(n))

    m = _OP_COUNTER.match(c)
    if not m:
        return None
    opname, a, b = m.group(1), m.group(2), m.group(3)
    base = i + 1
    la = int(a) if _INT.match(a) else None
    lb = int(b) if _INT.match(b) else None
    tgt = None
    if opname == "add":
        if a == "@counter" and lb is not None:
            tgt = base + lb
        elif b == "@counter" and la is not None:
            tgt = base + la
        elif la is not None and lb is not None:
            tgt = la + lb
    elif opname == "sub":
        if a == "@counter" and lb is not None:
            tgt = base - lb
        elif la is not None and lb is not None:
            tgt = la - lb
    elif la is not None and lb is not None:
        tgt = {"mul": la * lb, "div": la // lb if lb else None,
               "mod": la % lb if lb else None}.get(opname)
    if tgt is None:
        return list(range(n))
    return [tgt] if 0 <= tgt < n else []


def _cfg(stmts: list[tuple[int, str]]) -> list[list[int]]:
    """Control-flow successors for each statement index.

    Semantics that matter here:
      * `end` sets @counter to the program length, so it behaves as a LOOP BACK
        to statement 0 -- it is NOT a terminator. (A sink would wrongly make
        every loop look like dead code.)
      * `stop` really does halt, so it IS a sink.
      * `jump -1` never branches (it is the decorative no-op form), so it just
        falls through.
      * writing `@counter` is a computed jump; `_counter_target` resolves the
        literal forms and conservatively keeps everything reachable otherwise.
    """
    n = len(stmts)
    succ: list[list[int]] = []
    for i, (_, c) in enumerate(stmts):
        op = c.split()[0] if c else ""
        if op == "stop":
            succ.append([])
            continue
        if op == "end":
            succ.append([0] if n else [])
            continue
        m = JMP_RE.match(c)
        if m:
            tgt, cond = int(m.group(1)), m.group(2)
            out = []
            if tgt >= 0 and tgt < n:
                out.append(tgt)
            if cond != "always":
                if i + 1 < n:
                    out.append(i + 1)
            succ.append(out)
            continue
        counter = _counter_target(i, c, n)
        if counter is not None:
            succ.append(counter)
            continue
        succ.append([i + 1] if i + 1 < n else [0])
    return succ


def reachable_set(stmts: list[tuple[int, str]]) -> set[int]:
    """Statement indices reachable from entry 0."""
    succ = _cfg(stmts)
    seen: set[int] = set()
    stack = [0] if stmts else []
    while stack:
        i = stack.pop()
        if i in seen or not (0 <= i < len(stmts)):
            continue
        seen.add(i)
        stack.extend(succ[i])
    return seen


# a loop-guard comparison, in either of the two forms mlog uses:
#   op   lessThan idx CONST
#   jump <target> lessThan idx CONST
_GUARD_OP = re.compile(r"^op\s+(lessThan|lessThanEq|greaterThan|greaterThanEq)"
                       r"\s+(\S+)\s+(\S+)\s+(\S+)$")
_GUARD_JMP = re.compile(r"^jump\s+-?\d+\s+(lessThan|lessThanEq|greaterThan|greaterThanEq)"
                        r"\s+(\S+)\s+(\S+)$")
_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_BACKJUMP = re.compile(r"^jump\s+(-?\d+)\s+(\S+)")

COND_OPS = {"lessThan", "lessThanEq", "greaterThan", "greaterThanEq"}


def _bound_from_guard(a: str, b: str) -> int | None:
    """If one operand is a literal > 1, that literal is the trip-count hint."""
    const = None
    if _NUM.match(b):
        const = float(b)
    elif _NUM.match(a):
        const = float(a)
    if const is None:
        return None
    cand = int(abs(const))
    return cand if cand > 1 else None


def find_loop_bounds(stmts: list[tuple[int, str]]) -> dict[int, int]:
    """Best-effort loop trip counts.

    mlog has no declared loop bound, so we infer it the way blueprint authors
    actually write it: a counter compared against a CONSTANT, with a conditional
    jump back above that comparison. Loops bounded by something invisible (an
    idiv, a sensor count) are simply left out.
    """
    bounds: dict[int, int] = {}
    n = len(stmts)
    for j in range(n):
        m = _BACKJUMP.match(stmts[j][1])
        if not m:
            continue
        target = int(m.group(1))
        if not (0 <= target < j):
            continue                      # not a backward branch
        best = None
        # The back edge's OWN condition is the loop's trip counter, so it wins
        # over anything found in the body. Scanning the body and taking the max
        # let an inner loop's constant leak outward: `jump inner lessThan j 10`
        # inside an `i < 3` loop reported the outer loop as x10.
        own = _GUARD_JMP.match(stmts[j][1])
        if own and own.group(1) in COND_OPS:
            best = _bound_from_guard(own.group(2), own.group(3))
        for k in range(target, j + 1):
            if best is not None:
                break                     # own condition already answered it
            c = stmts[k][1]
            # each pattern: group(1)=comparison, then the two operands
            g = _GUARD_OP.match(c)
            if g and g.group(1) in COND_OPS:
                cand = _bound_from_guard(g.group(2), g.group(3))
            else:
                g2 = _GUARD_JMP.match(c)
                cand = (_bound_from_guard(g2.group(2), g2.group(3))
                        if g2 and g2.group(1) in COND_OPS else None)
            if cand:
                best = cand if best is None else max(best, cand)

        if best:
            bounds[target] = max(bounds.get(target, 0), best)
    return bounds


def prepare(lines: list[str]) -> list[tuple[int, str]]:
    """Statements for analysis: comments stripped, labels dropped, jumps resolved.

    A label line is NOT a statement. LParser.java:117-125 records it against the
    count of statements parsed so far (`jumpLocations.put(label, line)`), so it
    names the *next* statement and consumes no instruction slot. Keeping label
    lines in the list shifted every index after them, which is why `--cost` used
    to print `L0(?)` -- "no visible constant bound" -- for every loop written
    with `main:` style labels.

    Line numbers stay 0-based, like the rest of this file's output.
    """
    stmts: list[tuple[int, str]] = []
    labels: dict[str, int] = {}
    for ln, raw in enumerate(lines):
        code = strip_comment(raw)
        if not code:
            continue
        toks = code.split()
        if len(toks) == 1 and len(toks[0]) > 1 and toks[0].endswith(":"):
            labels.setdefault(toks[0][:-1], len(stmts))
            continue
        stmts.append((ln, code))
    if not labels:
        return stmts
    out: list[tuple[int, str]] = []
    for ln, code in stmts:
        toks = code.split()
        if len(toks) >= 2 and toks[0] == "jump" and toks[1] in labels:
            toks[1] = str(labels[toks[1]])
            code = " ".join(toks)
        out.append((ln, code))
    return out


def wait_ticks(stmts: list[tuple[int, str]],
               bounds: dict[int, int],
               loops: list[tuple[int, int, int]]) -> list[tuple[int, int | None]]:
    """Ticks each `wait` blocks, multiplied by every loop that contains it.

    `wait` never shows up in the instruction count: WaitI decrements the counter
    and yields every tick (LExecutor.java:1227-1232), so it consumes no ipt --
    it *is* the reason no further instruction runs. Its argument is in SECONDS,
    accumulated as `Time.delta / 60f` per tick, i.e. 60 ticks to the second.

    `wait 0` (or negative) only yields without counting up (LExecutor.java:1220),
    so it blocks nothing. A non-literal argument cannot be bounded: reported as
    None so the caller can say "unknown" instead of inventing a number.
    """
    out: list[tuple[int, int | None]] = []
    for i, (ln, code) in enumerate(stmts):
        toks = code.split()
        if not toks or toks[0] != "wait" or len(toks) < 2:
            continue
        try:
            sec = float(toks[1])
        except ValueError:
            out.append((ln, None))        # variable wait: cannot be priced
            continue
        if sec <= 0:
            continue                      # pure yield, blocks no time
        mult = 1
        for head, latch, bound in loops:
            if head <= i <= latch:        # this wait sits inside that loop
                mult *= max(bound, 1)
        out.append((ln, int(round(sec * 60)) * mult))
    return out


def cost_report(stmts: list[tuple[int, str]],
                links: list[str] | None = None) -> str:
    """Human-readable size / reachability / worst-case-cost summary."""
    n = len(stmts)
    if n == 0:
        return "  (empty program)"

    lines: list[str] = []
    lines.append(f"  statements      : {n}")

    # ---- reachability -----------------------------------------------------
    live = reachable_set(stmts)
    dead = [i for i in range(n) if i not in live]
    if dead:
        lines.append(f"  UNREACHABLE     : {len(dead)} statement(s) can never run:")
        for i in dead:
            lines.append(f"      L{stmts[i][0]}: {stmts[i][1][:70]}")
    else:
        lines.append("  reachability    : all statements reachable")

    # ---- opcode histogram -------------------------------------------------
    ops = collections.Counter(c.split()[0] for _, c in stmts if c)
    top = ", ".join(f"{o}×{c}" for o, c in ops.most_common(6))
    lines.append(f"  opcodes         : {top}")

    # ---- loops ------------------------------------------------------------
    succ = _cfg(stmts)
    back = [(i, t) for i, ss in enumerate(succ) for t in ss if t <= i]
    bounds = find_loop_bounds(stmts)
    if back:
        uniq = sorted({t for _, t in back})
        det = ", ".join(f"L{stmts[t][0]}(×{bounds[t]})" if t in bounds
                        else f"L{stmts[t][0]}(?)" for t in uniq)
        lines.append(f"  loop heads      : {det}")
        unknown = [t for t in uniq if t not in bounds]
        if unknown:
            lines.append(f"  ⚠ {len(unknown)} loop(s) have no visible constant bound; "
                         f"worst-case cost below assumes ONE pass for those")

    # ---- instruction thresholds ------------------------------------------
    if n > 1000:
        lines.append(f"  ⚠ ERR: {n} statements exceeds LExecutor.maxInstructions "
                     f"(1000) -- the tail is SILENTLY TRUNCATED on import")

    # ---- worst-case path -------------------------------------------------
    # Longest path from entry 0, with each loop's body charged `bound` times.
    #
    # Traps this implementation had to work around (all found by testing):
    #   1. Plain longest-path DP is undefined on the cycle head->body->latch->head.
    #   2. Adding the bound only at the back edge never grows: head depends on
    #      latch and latch on head, so the body was counted ONCE (reported a
    #      nonsense "78 instructions" for a program whose real cost is ~2494).
    #   3. A global relaxation DOUBLE-CHARGES nested loop bodies -- the inner
    #      loop inflates every statement after it, and the outer loop then
    #      multiplies that again (reported 643686 for the same program).
    #   4. `float('inf')` as the "unreached" sentinel breaks the comparison, so
    #      nothing ever relaxed and every program reported cost 1.
    #   5. A back edge to statement 0 is the MAIN LOOP (mlog re-runs the whole
    #      program each tick) and must cost ONE pass, not `bound`.
    #
    # The fix is a forward-only recursive interval DP. `path(a, b)` = worst cost
    # to get from `a` to the end of the interval `[a, b)`, only following edges
    # that stay inside it:
    #   * if a loop head h with latch l satisfies h <= i <= l, jump to h and
    #     re-enter with `limit = l + 1` (so the loop is entered and exited once);
    #   * at the latch, multiply by the trip count -- once for this loop only;
    #   * otherwise take 1 + max over forward successors.
    # Every recursive call raises `limit`, so recursion terminates.
    #
    # Still conservative: mutually exclusive branches are not pruned, so this is
    # an upper bound on a single tick's work, not a prediction of typical cost.
    MAX_INSTR_PER_TICK = 1000
    CAP = 10_000_000

    # Iterative forward-only propagation, inner loops resolved first.
    #
    # `f[i]` = worst instruction count from entry 0 to the point just after
    # statement i finishes. Backward edges are never followed during the sweep;
    # instead a loop is priced once, when its own head comes up:
    #
    #     loop_cost(h) = bound(h) * (worst forward path inside [h, latch])
    #
    # Because loops are handled by descending head index, an inner loop is
    # already priced when the outer loop that contains it is measured -- so the
    # inner cost is added exactly once, from f[inner_head] + loop_cost, and the
    # outer multiplication applies to a body that already includes it.
    #
    # Exiting a loop: the latch's forward edges leave it, and their cost is
    # `loop_cost + 1` (run the loop `bound` times, then take one step out).

    loops: list[tuple[int, int, int]] = []
    for head in sorted(bounds, reverse=True):
        latch = None
        for i in range(n - 1, head, -1):
            if head in succ[i]:
                latch = i
                break
        if latch is None or head == 0:
            continue                      # no latch found, or the main loop
        loops.append((head, latch, bounds[head]))

    f = [0] * n
    f[0] = 1                              # entry: statement 0 always executes
    loop_cost: dict[int, int] = {}

    for head, latch, bound in loops:
        f[head] = max(f[head], 1)
        cnt = [0] * n
        cnt[head] = 1
        best = 1
        for i in range(head, latch + 1):
            if cnt[i] == 0:
                continue
            for s in succ[i]:
                if s <= i:
                    continue              # backward edge: priced by loop_cost
                if i == latch and s > latch:
                    # `body` must be measured BEFORE this exit candidate is
                    # merged into cnt: feeding the candidate back into `best`
                    # multiplied the loop by its own exit path (a 4-iteration
                    # loop of 3 statements was billed as 4 x 14 = 56).
                    body = max(cnt[head:latch + 1])
                    cand = max(f[head], cnt[head]) + bound * body + 1
                elif s <= latch:
                    # Stepping INTO an inner loop head costs that whole loop.
                    # Inner loops were priced first (heads descend), so their
                    # cost is already known; without this the outer loop was
                    # billed for a single pass of the inner one.
                    cand = cnt[i] + loop_cost.get(s, 1)
                else:
                    continue              # forward exit taken from inside
                if s < n:
                    if cand > cnt[s]:
                        cnt[s] = cand
                    if cnt[s] > best:
                        best = cnt[s]
                    if i == latch and cand > f[s]:
                        f[s] = cand
        lc = min(bound * max(cnt[head:latch + 1]), MAX_INSTR_PER_TICK)
        loop_cost[head] = lc
        for i in range(head, latch + 1):
            if cnt[i]:
                f[i] = max(f[i], f[head] + cnt[i] - 1)
        if f[head] + lc > f[latch]:
            f[latch] = f[head] + lc

    for i in range(n):
        if f[i] == 0:
            continue
        for s in succ[i]:
            if s < i:
                # Backward edges were already priced: a statement inside a
                # counted loop has its whole loop included in f[], so walking
                # the back edge again billed the loop a second time (_wait1
                # came out at 25 instead of ~16). Loops without a constant
                # bound get the documented "one pass" treatment.
                continue
            cand = f[i] + 1
            if s < n and cand > f[s]:
                f[s] = cand

    worst_n = max(f)

    # `wait` burns no ipt (it yields and re-enters itself), so it is invisible in
    # `worst_n` -- yet it is often what dominates the real cycle time. Priced
    # separately and then added to the per-processor tick counts below.
    waits = wait_ticks(stmts, bounds, loops)
    blocked = sum(t for _, t in waits if t is not None)
    unpriced = sum(1 for _, t in waits if t is None)

    # A loop whose body alone blows the per-tick budget is priced as exactly
    # MAX_INSTR_PER_TICK, so `worst_n` saturates there instead of growing. Report
    # that as a lower bound (`>=`) -- printing "~1000" would read as a measurement.
    capped = worst_n >= MAX_INSTR_PER_TICK
    marks = ">=" if capped else "~"
    lines.append(f"  worst-case path : {marks}{worst_n} instructions per full cycle "
                 f"(approximate)")
    if capped:
        lines.append(f"      ! a loop body alone fills {MAX_INSTR_PER_TICK} "
                     f"instructions, so this is a lower bound, not the total")
    if worst_n > MAX_INSTR_PER_TICK:
        lines.append(f"      ⚠ over LExecutor.maxInstructions "
                     f"({MAX_INSTR_PER_TICK}/tick): one cycle needs "
                     f"{marks}{worst_n / MAX_INSTR_PER_TICK:.1f} ticks of pure work, "
                     f"so the unit reacts with that much latency")
    for ipt, name in ((2, "micro-processor"), (8, "logic-processor"),
                      (25, "hyper-processor")):
        ticks = worst_n / ipt + blocked
        lines.append(f"      {name:<16} @ipt={ipt:<3} {ticks:8.0f} ticks "
                     f"({ticks/60:7.1f} s) per cycle")

    if waits:
        if unpriced:
            head = f"{len(waits)} wait statement(s)"
            tail = f"{unpriced} of them take a variable argument, so blocking is UNBOUNDED"
        else:
            head = f"{len(waits)} wait statement(s)"
            tail = f"~{blocked} ticks ({blocked/60:.1f} s) blocked per cycle, added above"
        lines.append(f"  ⏸ blocking      : {head}, {tail}")
        for ln, t in waits[:6]:
            shown = "?" if t is None else f"~{t} ticks"
            lines.append(f"      L{ln}: wait -> {shown}")
        if len(waits) > 6:
            lines.append(f"      ... and {len(waits) - 6} more")

    if links:
        lines.append(f"  links           : {len(links)} "
                     f"({', '.join(links[:6])}{'...' if len(links) > 6 else ''})")
    return "\n".join(lines)


def show(path: str, findings: list[Finding]) -> int:
    errs = [f for f in findings if f.sev in ("ERR", "SUSPECT")]
    warns = [f for f in findings if f.sev == "WARN"]
    infos = [f for f in findings if f.sev == "INFO"]
    print(f"=== {path}")
    for f in errs + warns + infos:
        print(f)
    if not findings:
        print("  no issues found")
    print(f"  -> {len(errs)} error/ suspect, {len(warns)} warning, {len(infos)} info")
    return 1 if errs else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help=".mlog files")
    ap.add_argument("--blueprint", action="append", default=[],
                    help=".msch file; checks every logic block inside")
    ap.add_argument("--cost", action="store_true",
                    help="also report statement count, unreachable code, loop "
                         "bounds and worst-case instruction cost per cycle")
    args = ap.parse_args()

    def do(path: str, lines: list[str], links: list[str] | None = None) -> int:
        rc = show(path, analyse(lines, links))
        if args.cost:
            print(cost_report(prepare(lines), links))
            print()
        return rc

    rc = 0
    for p in args.files:
        with open(p, encoding="utf-8") as fh:
            rc |= do(p, fh.read().split("\n"))

    if args.blueprint:
        import msch
        for p in args.blueprint:
            sch = msch.parse_file(p)
            for t in sch.logic_tiles():
                assert t.logic is not None
                rc |= do(f"{p} [{t.block} @{t.x},{t.y}]",
                         t.logic.code.split("\n"),
                         [l.name for l in t.logic.links])
    return rc


_CP_RE = re.compile(r'^(read|write)\s+(\S+)\s+(\S+)\s+"([^"]*)"')


def cross_processor(tiles) -> list[Finding]:
    """Check `read`/`write` string addressing between logic processors.

    `read r processor1 "name"` / `write v processor1 "name"` reaches INTO
    another processor's variable BY NAME, and that slot has to exist there
    already -- the game does not create it on demand (confirmed by the author of
    the blueprint library this was tested against: "跨逻辑读写必须提前声明").
    So a name the target never mentions is a silent no-op.

    Resolution is exact, not a guess: a link stores its offset relative to the
    processor, so the target tile is `(t.x + link.x, t.y + link.y)`. A name
    counts as declared when it appears as ANY token of ANY statement in the
    target, because the parser calls var() on every argument -- that is what
    actually creates the slot.
    """
    tiles = [t for t in tiles if getattr(t, "logic", None) is not None]
    if not tiles:
        return []
    by_pos = {(t.x, t.y): t for t in tiles}
    declared: dict[int, set[str]] = {}
    for t in tiles:
        names: set[str] = set()
        for c in t.logic.code.split("\n"):
            names.update(tokenize(c)[1:])
        declared[id(t)] = names

    out: list[Finding] = []
    for t in tiles:
        by_name = {}
        for ln in t.logic.links:
            by_name[ln.name] = by_pos.get((t.x + ln.x, t.y + ln.y))
        for i, c in enumerate(t.logic.code.split("\n")):
            m = _CP_RE.match(c.strip())
            if not m:
                continue
            kind, _dst, target, name = m.groups()
            dst = by_name.get(target)
            if dst is None or dst is t:
                continue                      # not a logic block, or itself
            if name in declared[id(dst)]:
                continue
            out.append(Finding(
                "WARN", i + 1, c,
                f"cross-processor {kind}: `{name}` is never mentioned in "
                f"{dst.block} @({dst.x},{dst.y}) -- the slot must be declared "
                f"there first (the game does not create it on demand), so this "
                f"{kind} does nothing"))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
