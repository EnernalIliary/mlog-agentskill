"""Hidden @aigenerated signature for AI-written mlog.

    python tools/aigenerated.py sign   Logic/foo.mlog [--author 猪猪鱼] [--force]
    python tools/aigenerated.py verify Logic/foo.mlog
    python tools/aigenerated.py strip  Logic/foo.mlog   # always refused

Where the mark lives
--------------------
The last `end` of the program is replaced by

    jump 0 always 0 "aigenerated:猪猪鱼:1f02465d9e75"

`end` means "next instruction reads 0"; `jump 0 always` does the same thing, so
the program behaves identically.  The token sits in `JumpStatement`'s declared
p4 operand — the one `always` never looks at — so the game's own
`LAssembler.read` / `LAssembler.write` round-trip re-emits it verbatim.  A
surplus token after `end` is *not* used: `LogicIO.write` drops everything past
the declared arity, and statements after an `end` are lost too (measured on
v160.7, see mlog工作笔记).

Why not a comment?
-----------------
`#` comments are stripped when a blueprint is compiled, and the in-game editor
makes a leading comment obvious.

Removal policy
--------------
There is deliberately no `strip` mode: the signature is an attribution term.
Anyone can edit the text, but `verify` re-hashes the body without the token,
so deleting it or changing the logic both fail.  Re-sign after an intentional
edit with `sign --force`; that produces a new id.

The id is the first 12 hex of SHA-256 over `author + "\\n" + body`, with the
body normalised to LF, the signature line removed, and a trailing `end`
guaranteed (so signing is idempotent even for programs that omitted it).
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

DEFAULT_AUTHOR = "猪猪鱼"
SIG_LINE = 'jump 0 always 0 "aigenerated:{author}:{pid}"'
SIG_RE = re.compile(
    r'^jump\s+0\s+always\s+0\s+"aigenerated:([^":]+):([0-9a-f]{12})"\s*$')
# older releases used a comment header + unreachable set; drop those on re-sign
OLD_MARK_RE = re.compile(
    r"^(?:# @aigenerated(?:-end)?\b.*|set aigenerated\.[0-9a-f]{12}\b.*)$")
# release 0.9 put the token after `end`; normalise that back to a plain `end`
OLD_TAIL_RE = re.compile(r'^end\s+"aigenerated:[^"]*"\s*$')


class SignError(Exception):
    pass


def _read(path: Path) -> str:
    return (path.read_text(encoding="utf-8-sig")
            .replace("\r\n", "\n").replace("\r", "\n"))


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _clean(text: str) -> list[str]:
    """Normalise newlines and drop every existing signature / legacy mark."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in text.split("\n"):
        if SIG_RE.match(line.strip()) or OLD_MARK_RE.match(line):
            continue
        if OLD_TAIL_RE.match(line.strip()):
            out.append("end")
            continue
        out.append(line)
    return out


def _canonical(lines: list[str]) -> str:
    """Signature-free body, guaranteed to end with a single `end`."""
    lines = list(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    last = -1
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s and not s.startswith("#"):
            last = i
            break
    if last < 0:
        return ""
    if lines[last].strip() != "end":
        lines.insert(last + 1, "end")
    return "\n".join(lines) + "\n"


def _body(text: str) -> str:
    return _canonical(_clean(text))


def _hash(author: str, body: str) -> str:
    return hashlib.sha256((author + "\n" + body).encode("utf-8")).hexdigest()


def _find(text: str):
    text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return [m for m in (SIG_RE.match(ln.strip()) for ln in text.split("\n")) if m]


def sign_text(text: str, author: str = DEFAULT_AUTHOR, force: bool = False):
    """Return (signed_text, id).  Raises SignError if it would change an id."""
    hits = _find(text)
    body = _body(text)
    if not body:
        raise SignError("no statement to attach the signature to")
    author = re.sub(r'[:"]', "", author).strip() or DEFAULT_AUTHOR
    pid = _hash(author, body)[:12]
    if hits:
        old_id, old_author = hits[0].group(2), hits[0].group(1)
        if old_id == pid and old_author == author and not force:
            return text, pid
        if (old_id != pid or old_author != author) and not force:
            raise SignError(
                f"body changed since signing (id {old_id} -> {pid}); "
                f"pass --force to re-sign")
    lines = body.rstrip("\n").split("\n")
    lines[-1] = SIG_LINE.format(author=author, pid=pid)
    return "\n".join(lines) + "\n", pid


def verify_text(text: str) -> list[str]:
    hits = _find(text)
    if not hits:
        return ['missing hidden @aigenerated argument '
                '(expected `jump 0 always 0 "aigenerated:<author>:<id>"`)']
    if len(hits) > 1:
        return [f"{len(hits)} @aigenerated arguments found, expected 1"]
    author, want = hits[0].group(1), hits[0].group(2)
    got = _hash(author, _body(text))[:12]
    if want != got:
        return [f"body changed after signing (id {want} != {got})"]
    return []


def sign(path: Path, author: str, force: bool) -> str:
    text = _read(path)
    hits = _find(text)
    body = _body(text)
    if not body:
        raise SignError(f"{path}: no statement to attach the signature to")
    pid = _hash(author, body)[:12]
    if hits:
        old_id, old_author = hits[0].group(2), hits[0].group(1)
        if old_id == pid and old_author == author and not force:
            return f"already signed  {path}  id={pid}"
        if (old_id != pid or old_author != author) and not force:
            raise SignError(
                f"{path}: body changed since signing "
                f"(id {old_id} -> {pid}); pass --force to re-sign")

    signed, pid = sign_text(text, author, force=True)
    _write(path, signed)
    return f"signed  {path}  id={pid}  author={author}"


def verify(path: Path) -> list[str]:
    return [f"{path}: {p}" for p in verify_text(_read(path))]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="hidden @aigenerated signature for AI-written mlog")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sign", help="add/replace the hidden argument")
    ps.add_argument("files", nargs="+")
    ps.add_argument("--author", default=DEFAULT_AUTHOR)
    ps.add_argument("--force", action="store_true", help="re-sign after an intentional edit")

    pv = sub.add_parser("verify", help="check the hidden argument and body hash")
    pv.add_argument("files", nargs="+")

    pt = sub.add_parser("strip", help="refused by policy")
    pt.add_argument("files", nargs="+")

    args = ap.parse_args(argv)
    if args.cmd == "strip":
        print("refused: the @aigenerated signature is an attribution term and cannot be stripped;\n"
              "edit the logic and re-sign with `sign --force` instead", file=sys.stderr)
        return 2

    failed = 0
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f"missing file: {path}", file=sys.stderr)
            failed += 1
            continue
        if args.cmd == "sign":
            try:
                print(sign(path, args.author, args.force))
            except SignError as e:
                print(f"FAIL  {e}", file=sys.stderr)
                failed += 1
        else:
            problems = verify(path)
            if problems:
                failed += 1
                for p in problems:
                    print("FAIL  " + p, file=sys.stderr)
            else:
                m = _find(_read(path))[0]
                print(f"OK    {path}  id={m.group(2)}  author={m.group(1)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
