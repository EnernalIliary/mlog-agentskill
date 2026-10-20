"""Sign / verify AI-generated mlog logic.

    python tools/aigenerated.py sign  Logic/foo.mlog [--author 猪猪鱼] [--force]
    python tools/aigenerated.py verify Logic/foo.mlog
    python tools/aigenerated.py strip  Logic/foo.mlog   # always refused

Why a signature at all
----------------------
AI-generated logic must be distinguishable from hand-written logic, and the
mark must survive copy/paste and blueprint export.  The marker is *hidden* in
the sense that it never prints and never changes behaviour: it is one comment
line plus an unreachable `set` after the program's final `end`/`stop`.  Because
`.msch` schematics store the processor source text, signing the .mlog before
building the blueprint carries the mark into the schematic automatically.

Removal policy
--------------
There is deliberately no `strip` mode: the signature is a licence/attribution
term, not an optional comment.  A determined editor can of course delete text;
what they cannot do is make the result verify.  `verify` re-hashes the body, so
deleting the marker, or editing the logic after signing, both fail.

Hash covers the program body only (header/trailer excluded, line endings
normalised to LF), so re-signing after an intentional edit produces a new id.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

HEADER_RE = re.compile(
    r"^# @aigenerated author=(?P<author>.+?) id=(?P<id>[0-9a-f]{12}) sha256=(?P<hash>[0-9a-f]{64})\s*$")
TAIL_RE = re.compile(r"^# @aigenerated-end id=(?P<id>[0-9a-f]{12})\s*$")
TRAILER_RE = re.compile(r'^set aigenerated\.(?P<id>[0-9a-f]{12}) "?(?P=id)"?\s*$')

DEFAULT_AUTHOR = "猪猪鱼"


class SignError(Exception):
    pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def _write(path: Path, text: str) -> None:
    # keep the repository convention: UTF-8, no BOM, LF
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def split_signed(text: str):
    """Return (header dict|None, body, ok).  Drops an existing signature."""
    lines = text.split("\n")
    header = None
    if lines and (m := HEADER_RE.match(lines[0])):
        header = m.groupdict()
        lines = lines[1:]
    # strip trailer: optional 'end' guard, tail comment, set line
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "":
            continue
        if TRAILER_RE.match(lines[i].strip()):
            del lines[i]
            continue
        if TAIL_RE.match(lines[i].strip()):
            del lines[i]
            continue
        break
    body = "\n".join(lines).strip("\n") + "\n"
    return header, body


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def sign(path: Path, author: str, force: bool) -> str:
    text = _read(path)
    header, body = split_signed(text)
    if header is not None and not force:
        return f"already signed  {path}  id={header['id']}  (use --force to re-sign)"
    digest = _hash(body)
    pid = digest[:12]

    body_lines = body.rstrip("\n").split("\n")
    last = ""
    for ln in reversed(body_lines):
        s = ln.strip()
        if s and not s.startswith("#"):
            last = s
            break
    if last.split()[0] not in ("end", "stop"):
        body_lines.append("end")
        body = "\n".join(body_lines) + "\n"
        digest = _hash(body)
        pid = digest[:12]

    out = (f"# @aigenerated author={author} id={pid} sha256={digest}\n"
           + body
           + f"# @aigenerated-end id={pid}\n"
           + f'set aigenerated.{pid} "{pid}"\n')
    _write(path, out)
    return f"signed  {path}  id={pid}"


def verify(path: Path) -> list[str]:
    text = _read(path)
    header, body = split_signed(text)
    problems = []
    if header is None:
        return [f"{path}: missing @aigenerated header"]
    if _hash(body) != header["hash"]:
        problems.append(f"{path}: body changed after signing (hash mismatch)")
    if header["id"] != header["hash"][:12]:
        problems.append(f"{path}: id does not match hash prefix")
    if f"# @aigenerated-end id={header['id']}" not in text:
        problems.append(f"{path}: missing trailer comment")
    if f'set aigenerated.{header["id"]} "{header["id"]}"' not in text:
        problems.append(f"{path}: missing trailer set line")
    return problems


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="hidden @aigenerated signature for AI-written mlog")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sign", help="add/replace the signature")
    ps.add_argument("files", nargs="+")
    ps.add_argument("--author", default=DEFAULT_AUTHOR)
    ps.add_argument("--force", action="store_true", help="replace an existing signature")

    pv = sub.add_parser("verify", help="check signature and body hash")
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
            print(sign(path, args.author, args.force))
        else:
            problems = verify(path)
            if problems:
                failed += 1
                for p in problems:
                    print("FAIL  " + p, file=sys.stderr)
            else:
                header, _ = split_signed(_read(path))
                print(f"OK    {path}  id={header['id']}  author={header['author']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
