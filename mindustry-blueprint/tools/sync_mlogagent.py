#!/usr/bin/env python3
"""Vendor the mlog toolchain into the standalone `mlogagent` skill.

The `mlogagent` skill is meant to be self-contained: copy
`.dsh/skills/mlog-agentskill` somewhere else and it still runs, without the rest of
this repo.  That means the skill carries its own copy of every module and data
file, and this script is the one place that produces that copy -- so "which
version is in the skill" never becomes a guess.

Only the *tools* are synced.  `mlogagent/SKILL.md` is authored in place: it
belongs to that skill alone, while `mindustry-blueprint/SKILL.md` is a different
document.  (Copying it here once clobbered the playbook and silently removed the
skill from the catalog -- hence the explicit exclusion below.)

    python tools/sync_mlogagent.py            # copy + rewrite MANIFEST.sha256
    python tools/sync_mlogagent.py --check    # compare only, exit 1 if stale
    python tools/sync_mlogagent.py --global   # also install into DSH's user-level
                                              # skills dir, so the skill is in
                                              # scope for EVERY project

Run it after touching any module listed in `mlogagent._MODULES`, then
`python .dsh/skills/mlog-agentskill/tools/mlogagent.py info --verify` to confirm.

`--global` writes outside this repo (`$DSH_HOME/skills/...`, usually
`C:/Users/<you>/.dsh/skills`, which is a junction into `.dsh-pack/skills/default`).
That is what makes the skill visible in every project instead of only this one --
DSH has no per-skill scope switch, so scope *is* the directory it lives in.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _repo_root(start: Path) -> Path:
    """Find the checkout root by looking for `.dsh/skills`.

    This script lives in two places at *different depths*
    (`mindustry-blueprint/tools/` and, after the sync, `tools/`), so a fixed
    `parents[N]` resolves correctly in one and silently lands one level too high
    in the other (symptom: "skill directory not found").  Walking up until the
    marker appears keeps both copies honest.
    """
    for p in [start, *start.parents]:
        if (p / ".dsh" / "skills").is_dir():
            return p
    return start.parent


ROOT = _repo_root(HERE)
SKILL = ROOT / ".dsh" / "skills" / "mlog-agentskill"
DEST = SKILL / "tools"

#: DSH's user-level ("every project") skills directory.  `~/.dsh/skills` is a
#: junction into `.dsh-pack/skills/default` on this machine, so writing here is
#: the same as installing a built-in skill.
GLOBAL_SKILL = (Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
                / "skills" / "mlog-agentskill")
GLOBAL_DEST = GLOBAL_SKILL / "tools"

sys.path.insert(0, str(HERE))
import mlogagent  # noqa: E402  (needs the sys.path line above)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def payload() -> list[str]:
    """Modules + data files, in a stable order.  Never SKILL.md."""
    return list(mlogagent._MODULES) + list(mlogagent._DATA)


def install_global(check_only: bool = False) -> int:
    """Copy the vendored skill into DSH's user-level skills directory.

    Verified file-by-file afterwards, because the whole point of this copy is
    that it is the one DSH actually loads -- a half-finished copy would look
    installed while still running the previous version.
    """
    if not GLOBAL_SKILL.parent.is_dir():
        print(f"!! no global skills directory: {GLOBAL_SKILL.parent}")
        print("   (DSH_HOME unset and ~/.dsh/skills missing?)")
        return 2

    rels = ["SKILL.md", *[f"tools/{n}" for n in payload()], "tools/MANIFEST.sha256"]

    if check_only:
        bad = []
        for rel in rels:
            a, b = SKILL / rel, GLOBAL_SKILL / rel
            if not b.exists():
                bad.append(f"{rel}: missing")
            elif sha256(a) != sha256(b):
                bad.append(f"{rel}: differs")
        if bad:
            print(f"STALE  {len(bad)} file(s) differ in {GLOBAL_SKILL}:")
            for x in bad:
                print(f"  {x}")
            print("run: python tools/sync_mlogagent.py --global")
            return 1
        print(f"global : in sync with {GLOBAL_SKILL}")
        return 0

    GLOBAL_DEST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL / "SKILL.md", GLOBAL_SKILL / "SKILL.md")
    for n in payload():
        shutil.copy2(DEST / n, GLOBAL_DEST / n)
    shutil.copy2(DEST / "MANIFEST.sha256", GLOBAL_DEST / "MANIFEST.sha256")

    bad = [rel for rel in rels if sha256(SKILL / rel) != sha256(GLOBAL_SKILL / rel)]
    if bad:
        print(f"!! {len(bad)} file(s) did not copy cleanly: {bad}")
        return 1
    print(f"global : installed {len(rels)} file(s) into {GLOBAL_SKILL}")
    print("         available in every DSH project "
          "(reload the session if the catalog does not refresh)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="do not write; report what differs from the skill copy")
    ap.add_argument("--global", dest="install_global", action="store_true",
                    help="also install into $DSH_HOME/skills, so the skill is in "
                         "scope for every project (combine with --check to verify)")
    args = ap.parse_args(argv)

    if not SKILL.is_dir():
        print(f"!! skill directory not found: {SKILL}")
        return 2

    names = payload()
    stale: list[str] = []

    if args.check:
        for n in names:
            dst = DEST / n
            if not dst.exists():
                stale.append(f"{n}: missing from the skill")
            elif sha256(HERE / n) != sha256(dst):
                stale.append(f"{n}: differs")
    else:
        DEST.mkdir(parents=True, exist_ok=True)
        for n in names:
            shutil.copy2(HERE / n, DEST / n)
        lines = [f"{sha256(DEST / n)}  {n}" for n in names]
        (DEST / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", "utf-8")

    if stale:
        print(f"STALE  {len(stale)} file(s) differ from {HERE}:")
        for s in stale:
            print(f"  {s}")
        print("run: python tools/sync_mlogagent.py")
        return 1

    print(f"ok     {len(names)} tool file(s) vendored into {DEST}")
    print(f"       manifest: {DEST / 'MANIFEST.sha256'}")
    if not args.check:
        print("verify : python .dsh/skills/mlog-agentskill/tools/mlogagent.py info --verify")
    if args.install_global:
        return install_global(check_only=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
