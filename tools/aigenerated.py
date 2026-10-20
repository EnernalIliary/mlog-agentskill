"""Hidden @aigenerated signature for AI-written mlog.

    python tools/aigenerated.py sign   Logic/foo.mlog [--author 猪猪鱼] [--force]
    python tools/aigenerated.py verify Logic/foo.mlog
    python tools/aigenerated.py strip  Logic/foo.mlog   # always refused

The marker is an *extra string argument* on the program's last statement,
e.g. `end "aigenerated:猪猪鱼:1f02465d9e75"`.  mlog parsers fill fields by
position and silently drop tokens past the declared arity, so the program
runs exactly as before; nothing is printed, nothing is branched to, and the
token survives copy/paste and `.msch` export (schematics store the source).

Why not a comment?
------------------
`#` comments are stripped when a blueprint is compiled, and the in-game
editor makes a leading comment obvious.  A surplus argument is part of the
instruction text, so it travels with the code and is easy to miss.

Removal policy
--------------
There is deliberately no `strip` mode: the signature is an attribution term.
Anyone can edit the text, but `verify` re-hashes the body without the token,
so deleting it or changing the logic both fail.  Re-sign after an intentional
edit with `sign --force`; that produces a new id.

The id is the first 12 hex of SHA-256 over the body (line endings normalised
to LF, one trailing newline, signature token removed).
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

DEFAULT_AUTHOR = "猪猪鱼"
SIG_RE = re.compile(r'[ \t]+"aigenerated:([^":]+):([0-9a-f]{12})"[ \t]*$')
# older releases used a comment header + unreachable set; drop those on re-sign
OLD_MARK_RE = re.compile(
    r"^(?:# @aigenerated(?:-end)?\b.*|set aigenerated\.[0-9a-f]{12}\b.*)$", re.M)


class SignError(Exception):
    pass


def _read(path: Path) -> str:
    return (path.read_text(encoding="utf-8-sig")
            .replace("\r\n", "\n").replace("\r", "\n"))


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _body(text: str) -> str:
    """Normalise, drop old-style marks, and remove the hidden signature token."""
    text = SIG_RE.sub("", text)
    lines = [ln for ln in text.split("\n") if not OLD_MARK_RE.match(ln)]
    return "\n".join(lines).rstrip("\n") + "\n"


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _find(text: str):
    hits = []
    for line in text.split("\n"):
        m = SIG_RE.search(line)
        if m:
            hits.append(m)
    return hits


def _last_statement(lines: list[str]) -> int:
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s and not s.startswith("#"):
            return i
    return -1


def sign(path: Path, author: str, force: bool) -> str:
    text = _read(path)
    hits = _find(text)
    body = _body(text)
    digest = _hash(body)
    pid = digest[:12]
    if hits:
        old = hits[0].group(2)
        if old == pid and not force:
            return f"already signed  {path}  id={pid}"
        if old != pid and not force:
            raise SignError(
                f"{path}: body changed since signing (id {old} -> {pid}); "
                f"pass --force to re-sign")

    author = re.sub(r'[:"]', "", author).strip() or DEFAULT_AUTHOR
    lines = body.rstrip("\n").split("\n")
    idx = _last_statement(lines)
    if idx < 0:
        raise SignError(f"{path}: no statement to attach the signature to")
    lines[idx] = lines[idx].rstrip() + f' "aigenerated:{author}:{pid}"'
    _write(path, "\n".join(lines) + "\n")
    return f"signed  {path}  id={pid}  author={author}"


def verify(path: Path) -> list[str]:
    text = _read(path)
    hits = _find(text)
    if not hits:
        return [f"{path}: missing hidden @aigenerated argument "
                f'(expected "aigenerated:<author>:<id>" on the last statement)']
    if len(hits) > 1:
        return [f"{path}: {len(hits)} @aigenerated arguments found, expected 1"]
    want = hits[0].group(2)
    got = _hash(_body(text))[:12]
    if want != got:
        return [f"{path}: body changed after signing (id {want} != {got})"]
    return []


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
