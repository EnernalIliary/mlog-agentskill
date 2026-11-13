#!/usr/bin/env python3
"""Docs signatures must agree with the instruction semantics table.

Docs drift from the game silently.  On 2026-10-28 the maintainer asked why a
tower-defense program "detected only one unit" -- the answer was that
蓝图逻辑模式库.md described `radar <target> <relation> <sort> <direction> <building> <count> <output>`
with a COUNT, and taught "at most 10, it is really the Nth one".  The engine has
no count: LStatements.java:485-547 -> RadarI, the sixth operand is the sort
DIRECTION (LExecutor.java:753 `sortOrder.bool() ? 1 : -1`) and the statement has
exactly ONE output (LExecutor.java:802).  Every reader of that page was taught a
parameter that does not exist, and the error was copied into four PATTERNS.md
mirrors.  A human re-reading 12k lines of docs did not catch it for months, so
this file makes the docs checkable by machine.

Authority: tools/instr_semantics.json (params = mlog text order, which is the
Java field declaration order of the LStatement subclass: LogicIO.write()
serialises the fields reflectively and the parser fills them back in the same
order.  The order the statement's build(LAssembler) passes them to the
instruction constructor is irrelevant -- probe `read r c0 5` and the jar reports
ReadI{output=r, target=c0, position=5}, i.e. fields, not constructor args.
See the table's _notes).  Four checks:

  signature  A line of the shape `mnemonic <a> <b> ...` -- outside a fence or
             inside one, since docs put signatures in ```mlog` blocks -- must
             have exactly len(params) placeholders.  Generic forms containing
             ... or 参数 are skipped (they describe a family, not a statement).
  example    Inside a fenced block, a statement starting with a STRICT mnemonic
             must not supply FEWER operands than the engine reads.  Extra
             trailing tokens are legal -- LParser reads the fields it knows and
             ignores the rest (measured: `radar ... u 0 0` keeps output u) -- but a
             missing operand shifts everything after it: `uradar enemy any any
             distance 1 target` puts `target` in the order slot and writes the
             result to the default `result`.  That silent shift is the bug class.
  table      A field table that follows a signature line and names params must
             name them in params order (skipping some is fine: the dead uradar
             slot is legitimately omitted).  Catches a reordered field list.
  slot       A placeholder that carries a param NAME must sit at that param's
             index: `getblock <result> <x> <y> <layer>` was 4 placeholders for 4
             params, so the count check passed, but the engine reads
             layer,result,x,y and the output silently became the layer token.
             This is the check the count check cannot do; it needs the doc to
             spell the operand names, which is why check 3 and this one work
             together.  Measured on v160.7: getblock/setblock/weathersense had
             the right count and the wrong order, all fixed 2026-10-28 along
             with spawnwave (doc order reversed, table already right).

  operand    A token that SELECTS an enum value must exist: the subcommand of
             ucontrol/draw/ulocate, the first operand of status, the status
             effect name, and a sensor property written @name.  None of these
             slots can hold a variable (the semantics table records them as
             LUnitControl / LDrawType / LLocate / boolean / LAccess), so a name
             outside the table is always wrong -- unlike an ordinary operand,
             which may be a variable.  Measured on v160.7: `ulocate locate ...`
             compiles to a NoopI (the statement silently does nothing),
             `sensor d b @damage` leaves SenseI.type null (there is no @damage;
             velocity is @velocityX/@velocityY), and status' first operand is a
             BOOLEAN literal -- `status clear ...` parses clear=false, i.e. it
             APPLIES the effect instead of clearing it.

Known blind spot: an invented Chinese field name (the original radar 数量 row)
is not detectable by check 3 -- it does not look like a param at all, so the
row contributes no hit -- and the original line had 7 placeholders for 7
params, so check 1 passed it too.  That class (right arity, wrong meaning,
unmatched name) has no mechanical detector here; a player caught it, and it is
now pinned by a runtime probe (tests/probes, radar-* cases) plus the rewritten
param table.

`--self-test` proves the harness is not vacuous: it feeds one synthetic doc
with one planted defect per check and requires at least one finding per
check (the slot check fires once per misplaced operand, so the counts differ).
Without it, a regex that stopped matching would exit 0 forever (the failure
mode tests/shapes/run_shapes.py exists to prevent for the checkers).

Run:  python tests/docsig/run_docsig.py [-v] [--self-test] [--root DIR]
Exit: 0 clean, 1 mismatch found, 3 could not run (no semantics table).
"""

import io
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]

# Docs written by hand.  Deliberately NOT scanned here:
#   Logic/                 original read-only copies (never edited)
#   out/, dist/            drafts and build output
#   */PATTERNS.md, */BLUEPRINT-ANALYSIS.md
#                          DERIVED, not written: they are 蓝图逻辑模式库.md and
#                          蓝图层逐类精讲.md copied to a deeper directory by
#                          tools/fix_skill_links.py (which rewrites the leading
#                          ../ of every link and renames the file).  Scanning
#                          them here would report the same defect once per copy;
#                          derived() below asserts they are content-identical
#                          instead, which is the real invariant.
DOCS = [
    "蓝图逻辑模式库.md",
    "Logic-Docs-v1.1.0.md",
    "蓝图层逐类精讲.md",
    "mlog工作笔记.md",
    "docs/速查卡.md",
]

# Mnemonics whose operand count is fixed and whose docs carry runnable examples.
# draw/op/ucontrol/ulocate are excluded: their arity depends on a subcommand, so
# a token count says nothing on its own.
STRICT = {
    "set", "sensor", "getlink", "print", "printflush", "drawflush", "format",
    "wait", "ubind", "setrate", "printchar", "radar", "uradar", "noop", "end",
    "read", "write", "status",
}

# hand-written source -> derived copies, discovered by walking the tree (a new
# mirror must not be able to escape this check by not being listed).
DERIVED_SOURCES = ["蓝图逻辑模式库.md", "蓝图层逐类精讲.md"]
DERIVED_SKIP = ("out", "dist", "Logic", ".git", "logic-corpus", "saves")

PLACE = re.compile(r"^<[^<>]{1,40}>$")
FENCE = re.compile(r"^\s*```\s*([A-Za-z0-9_+-]*)")
BULLET = "-*+>| \t"

def load_semantics(root=ROOT):
    p = Path(root) / "tools" / "instr_semantics.json"
    if not p.is_file():
        print("SKIP no semantics table at " + str(p))
        return None
    sem = json.loads(io.open(p, encoding="utf-8").read())
    out = {}
    for name, spec in (sem.get("instructions") or {}).items():
        out[name] = list(spec.get("params") or [])
    return out

def load_vocab(root=ROOT):
    """Names that a subcommand / enum / property slot is allowed to hold.

    Returns None when a table is missing (the caller then skips the operand
    check rather than reporting every name as wrong).
    """
    root = Path(root)
    need = {"sem": "tools/instr_semantics.json",
            "status": "tools/status_names.json",
            "sensor": "tools/sensor_attrs.json",
            "content": "tools/content_names.json"}
    for k, rel in need.items():
        if not (root / rel).is_file():
            print("SKIP no " + rel)
            return None
    sem = json.loads((root / need["sem"]).read_text("utf-8"))["instructions"]
    vocab = {}
    for name in ("ucontrol", "draw", "ulocate"):
        vocab[name] = set((sem.get(name) or {}).get("subcommands") or ())
    vocab["status"] = set(json.loads((root / need["status"]).read_text("utf-8"))["status"])
    vocab["access"] = set(json.loads((root / need["sensor"]).read_text("utf-8"))["access"])
    cn = json.loads((root / need["content"]).read_text("utf-8"))
    content = set()
    for k in ("items", "liquids", "blocks", "units", "statuses"):
        content |= set(cn.get(k) or ())
    vocab["content"] = content
    return vocab

def operand(rel, lineno, toks, vocab, stats, problems):
    """Check the token that selects a subcommand / names an enum value.

    True when this line had such a slot (so the caller knows it was looked at).
    """
    if not vocab or len(toks) < 2:
        return False
    head = toks[0].lower()
    arg = toks[1]
    if PLACE.match(arg):
        return False                    # generic signature: <动作>, <type>
    if head in ("ucontrol", "draw", "ulocate"):
        known = vocab.get(head) or set()
        stats["operand"] += 1
        if arg not in known:
            problems.append(
                "%s:%d %s subcommand %s does not exist -- the parser keeps the "
                "line but turns it into a noop (measured: ulocate locate -> "
                "NoopI); known: %s"
                % (rel, lineno, head, arg, ", ".join(sorted(known))))
        return True
    if head == "status":
        stats["operand"] += 1
        if arg not in ("true", "false"):
            problems.append(
                "%s:%d status takes a BOOLEAN literal first (true/false), not %s: "
                "the field is `clear`, and any other token parses as an "
                "undefined variable = false, so `status clear ...` APPLIES the "
                "effect instead of clearing it (measured on v160.7: clear=false)"
                % (rel, lineno, arg))
        elif len(toks) >= 3 and toks[2].startswith("@"):
            name = toks[2][1:]
            if name.startswith("status-"):
                name = name[len("status-"):]
            known = vocab.get("status") or set()
            if name not in known:
                problems.append(
                    "%s:%d status effect @%s is not in StatusEffects; known: %s"
                    % (rel, lineno, name, ", ".join(sorted(known))))
        return True
    if head == "sensor":
        if len(toks) < 4 or not toks[3].startswith("@"):
            return False
        stats["operand"] += 1
        name = toks[3][1:]
        if name not in (vocab.get("access") or set()) and            name not in (vocab.get("content") or set()):
            problems.append(
                "%s:%d sensor property @%s is neither an LAccess nor a Content "
                "name; the engine stores a null type and the statement reads "
                "nothing (LAccess has %d entries on v160.7)"
                % (rel, lineno, name, len(vocab.get("access") or ())))
        return True
    return False

def strip_comment(line):
    """Drop a trailing # comment, respecting double quotes."""
    inq = False
    for i, ch in enumerate(line):
        if ch == '"':
            inq = not inq
        elif ch == "#" and not inq:
            return line[:i]
    return line

def doc_lines(path):
    try:
        text = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    return text.splitlines()

def _subsequence(seq, full):
    it = iter(full)
    return all(any(x == y for y in it) for x in seq)

def tokenize(line):
    """Tokens of one doc line, with markdown decoration removed."""
    toks = line.replace("`", "").split()
    while toks and not toks[0].strip(BULLET).strip("*:,"):
        toks.pop(0)                      # bullet / pipe / emphasis prefix
    if not toks:
        return []
    toks[0] = toks[0].strip("*:,")
    return toks

def signature(rel, lineno, toks, sem, stats, problems):
    """Check a signature-shaped line.  True when the line was one."""
    if len(toks) < 3:
        return False
    head = toks[0].lower()
    if head not in sem:
        return False
    rest = toks[1:]
    if not all(PLACE.match(t) for t in rest):
        return False
    params = sem[head]
    if any(("..." in t) or ("…" in t) or ("参数" in t) for t in rest):
        return True                      # generic family form: nothing to count
    stats["signature"] += 1
    if len(rest) != len(params):
        problems.append(
            "%s:%d signature %s has %d placeholder(s), the engine reads %d: %s"
            % (rel, lineno, head, len(rest), len(params), ", ".join(params)))
        return True
    for idx, tok in enumerate(rest):
        name = tok[1:-1].strip()
        if name in params and params.index(name) != idx:
            problems.append(
                "%s:%d signature %s slot %d is <%s>, the engine reads %s at "
                "that position (mlog text order = field declaration order): %s"
                % (rel, lineno, head, idx, name, params.index(name),
                   ", ".join(params)))
    return True

def scan_lines(rel, lines, sem, stats, problems, vocab=None):
    """Check one document.  Appends to stats/problems, returns nothing."""
    in_fence = False
    lang = ""
    sig_at = None              # mnemonic of the most recent signature line
    table = []                 # (line no, param) collected since sig_at
    table_sig = None
    table_first = None
    table_header = None        # lowercased header row of the current table

    def flush():
        nonlocal table, table_sig, table_first, table_header
        if len(table) >= 2 and table_sig:
            params = sem.get(table_sig) or []
            seq = [p for _, p in table]
            stats["table"] += 1
            if params and not _subsequence(seq, params):
                problems.append(
                    "%s:%d table for %s names %s but the engine reads %s (in this order)"
                    % (rel, table_first, table_sig, ", ".join(seq), ", ".join(params)))
        table = []
        table_sig = None
        table_first = None
        table_header = None

    for i, raw in enumerate(lines, 1):
        m = FENCE.match(raw)
        if m:
            flush()
            in_fence = not in_fence
            lang = (m.group(1) or "").lower()
            continue

        s = raw.strip()
        if not s:
            flush()
            continue

        if in_fence:
            if lang not in ("", "mlog", "text", "txt"):
                continue
            body = strip_comment(raw).strip()
            if not body:
                continue
            for part in body.split(";"):
                toks = part.split()
                if len(toks) < 2:
                    continue
                if signature(rel, i, toks, sem, stats, problems):
                    sig_at = toks[0].lower()
                    continue
                head = toks[0].lower()
                operand(rel, i, toks, vocab, stats, problems)
                if head in STRICT and head in sem:
                    need = len(sem[head]) + 1
                    stats["example"] += 1
                    if len(toks) < need:
                        problems.append(
                            "%s:%d example %s needs %d operand(s), has %d -- a "
                            "missing operand shifts the rest (LParser pads the tail)"
                            % (rel, i, head, need - 1, len(toks) - 1))
            continue

        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 2 or set("".join(cells)) <= set("-: "):
                continue
            if table_sig != sig_at:
                flush()
                table_sig = sig_at
            if table_header is None:
                table_header = " ".join(cells).lower()
                continue
            # Only tables that declare a param column claim to document the
            # engine's operand list.  Logic-Docs writes 参数/类型 tables that put
            # the output first for readability -- a presentation choice, not a
            # contradiction, so those are deliberately not checked.
            if "param" not in table_header or sig_at is None:
                continue
            params = sem.get(sig_at) or []
            if not params:
                continue
            first_two = " ".join(cells[:2])
            hits = [p for p in params
                    if re.search(r"(?<![\w-])" + re.escape(p) + r"(?![\w-])", first_two)]
            if not hits:
                continue
            if table_first is None:
                table_first = i
            for h in hits:
                table.append((i, h))
            continue

        flush()
        toks = tokenize(s)
        if toks and signature(rel, i, toks, sem, stats, problems):
            sig_at = toks[0].lower()
    flush()

def _norm_link_depth(line):
    """Collapse ../ runs inside markdown link targets.

    A derived copy sits one directory deeper (or three), so fix_skill_links.py
    rewrites (../.../Mindustry-Source/x) to (../../../../Mindustry-Source/x).
    Only the depth differs -- the target is the same file.
    """
    return re.sub(r"\((?:(\.\.)/)+", "(", line)

def derived(root=ROOT, verbose=False):
    """Compare every *derived* copy with its hand-written source.

    Returns (checked, problems).  A copy that drifted is how the radar "count"
    myth reached four mirrors: the source was fixed and the copies were not, and
    nothing looked at them.
    """
    root = Path(root)
    checked, problems = 0, []
    copies = []
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirnames[:] = [d for d in dirnames if d not in DERIVED_SKIP]
        rel_dir = Path(dirpath).relative_to(root)
        for fn in filenames:
            if fn in ("PATTERNS.md", "BLUEPRINT-ANALYSIS.md"):
                copies.append(rel_dir / fn)
    src_of = {"PATTERNS.md": "蓝图逻辑模式库.md",
              "BLUEPRINT-ANALYSIS.md": "蓝图层逐类精讲.md"}
    for copy in sorted(copies):
        src = root / src_of[copy.name]
        if not src.is_file():
            problems.append(f"{copy.as_posix()}: source {src.name} is gone")
            continue
        checked += 1
        a = src.read_text("utf-8").splitlines()
        b = (root / copy).read_text("utf-8").splitlines()
        if len(a) != len(b):
            problems.append(f"{copy.as_posix()}: {len(b)} line(s) vs {len(a)} in "
                            f"{src.name} -- regenerate with "
                            f"python tools/fix_skill_links.py <skill dir>")
            continue
        out = []
        for i, (la, lb) in enumerate(zip(a, b), 1):
            want = _norm_link_depth(la).replace(src.name, copy.name)
            got = _norm_link_depth(lb)
            if want != got:
                out.append((i, la, lb))
        if out:
            problems.append(f"{copy.as_posix()}: {len(out)} line(s) differ from "
                            f"{src.name} (first at line {out[0][0]})")
            if verbose:
                for ln, la, lb in out[:5]:
                    print(f"    {copy.name}:{ln} source: {la[:90]}")
                    print(f"    {copy.name}:{ln} copy  : {lb[:90]}")
    return checked, problems

QUICK = "docs/速查卡.md"
ASSERT = "docs/断言表.md"
AID = re.compile(r"\bL\d-\d\d\b")

def refs(root=ROOT):
    """Every assertion id cited by the cheat card must exist in the table.

    The card is meant to be printable and quotable, so its value is exactly the
    strength of the ids behind it: a citation to a deleted assertion (or a typo)
    turns a one-page summary into folklore.  Sections are checked too -- a
    section without a single id is an opinion, not a fact.
    """
    problems = []
    qp, ap = Path(root) / QUICK, Path(root) / ASSERT
    if not qp.is_file():
        return problems, 0
    if not ap.is_file():
        problems.append("%s: cannot find %s to verify citations" % (QUICK, ASSERT))
        return problems, 0
    known = set(AID.findall(io.open(ap, encoding="utf-8").read()))
    if not known:
        problems.append("%s: no assertion ids found in %s" % (QUICK, ASSERT))
        return problems, 0
    seen, section, per = set(), None, {}
    for lineno, line in enumerate(io.open(qp, encoding="utf-8").read().splitlines(), 1):
        if line.startswith("## "):
            section = line[3:].strip()
            per.setdefault(section, 0)
        ids = AID.findall(line)
        for aid in ids:
            seen.add(aid)
            if aid not in known:
                problems.append("%s:%d: cites %s, which is not in %s"
                                % (QUICK, lineno, aid, ASSERT))
        if section:
            per[section] += len(ids)
    for section, n in per.items():
        if n == 0:
            problems.append("%s: section %r cites no assertion id" % (QUICK, section))
    return problems, len(seen)

def check(sem, verbose=False, root=ROOT):
    problems = []
    stats = {"signature": 0, "example": 0, "table": 0, "operand": 0, "files": 0}
    vocab = load_vocab(root)
    for rel in DOCS:
        path = Path(root) / rel
        if not path.is_file():
            continue
        stats["files"] += 1
        scan_lines(rel, doc_lines(path), sem, stats, problems, vocab)
    return problems, stats

def selftest(sem, vocab=None):
    """One planted defect per check must be reported; clean lines must not."""
    fake = [
        "- `getblock <result> <x> <y> <layer>`",                 # bad: slot order
        "- `uradar <a> <b> <c> <d> <e> <f>`",            # bad: 6 vs 7
        "- `radar <target1> <target2> <target3> <sort> <building> <order> <output>`",  # ok
        "```mlog",
        "uradar enemy any any distance 1 target",                   # bad: 6 operands vs 7
        "```",
        "```mlog",
        "status clear @burning myUnit 5",                # bad: boolean literal
        "sensor _dmg _bullet @damage",                   # bad: no such LAccess
        "ulocate locate core true @copper x y f b",      # bad: no such subcommand
        "```",
        "| field | param | value |",
        "|---|---|---|",
        "| a | sort | x |",                                        # table order: sort
        "| b | target1 | y |",                                     # bad: then target1
        "",
    ]
    stats = {"signature": 0, "example": 0, "table": 0, "operand": 0, "files": 1}
    problems = []
    scan_lines("<selftest>", fake, sem, stats, problems, vocab)
    want = ("signature", "example", "table", "slot", "operand")
    seen = {w for w in want for p in problems if w in p}
    if seen != set(want):
        print("SELFTEST FAIL: expected at least one finding per check (%s), got %d:"
              % (", ".join(want), len(problems)))
        for p in problems:
            print("  " + p)
        return 1
    print("SELFTEST OK: %d findings, all five checks fired" % len(problems))
    return 0

def main(argv):
    verbose = "-v" in argv or "--verbose" in argv
    root = ROOT
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    sem = load_semantics(root)
    if sem is None:
        return 3
    if "--self-test" in argv:
        return selftest(sem, load_vocab(root))
    problems, stats = check(sem, verbose, root)
    n_derived, der_problems = derived(root, verbose)
    ref_problems, n_refs = refs(root)
    problems += der_problems + ref_problems
    print("docs: %d file(s), %d signature line(s), %d example line(s), "
          "%d table(s), %d operand line(s), %d cited assertion id(s), "
          "%d derived copy/copies"
          % (stats["files"], stats["signature"], stats["example"],
             stats["table"], stats["operand"], n_refs, n_derived))
    for p in problems:
        print("MISMATCH " + p)
    if problems:
        print("%d mismatch(es)" % len(problems))
        return 1
    print("OK signatures agree with tools/instr_semantics.json")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))