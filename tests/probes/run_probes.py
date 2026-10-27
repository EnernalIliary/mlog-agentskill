#!/usr/bin/env python3
"""Runtime probes: assert what the real executor DOES, not what a lint says.

Why this exists
---------------
Every semantic claim in docs/断言表.md used to be checked by hand: boot the v160.7
jar, place a processor, read a number off the scene, write it down. That is how the
status-effect slot kept its claim backwards for a whole release -- the static check
and the report agreed with each other and neither had run.

Each probe in manifest.json is a program plus the numbers the real executor must
produce. Adding a semantic claim means adding a probe, and a wrong claim now fails
a gate instead of surviving until someone re-reads a class file.

What a probe may assert
-----------------------
    expect {effect: duration}   status effect duration in ticks
    expect_has {effect: bool}   hasEffect bit
    expect_vars {name: value}   value: number (|got-want| <= 1e-6) or string (exact),
                                or {"approx": 60, "tol": 1e-3}
    expect_classes [names]      compiled instruction classes, exact list
    expect_classes_has [names]  classes that must be present
    expect_text "..."           text buffer, exact (newlines appear as \\n)
    expect_text_contains [...]  substrings that must appear in the text buffer
    expect_text_empty true      text buffer must be empty
    processor "world"|"auto"    block to place ("auto" sniffs PRIVILEGED_RE)
    rules {field: value}        Vars.state.rules overrides applied before compiling
                                (e.g. allowLogicData, which gates clientdata)

Usage
-----
    python tests/probes/run_probes.py              # all probes (concurrent by default)
    python tests/probes/run_probes.py status-v160  # ids containing this
    python tests/probes/run_probes.py --jobs 1     # serial (easier to read a traceback)

Exit: 0 every probe passed, 1 a probe failed, 3 nothing could run (no JRE, or the
versioned jars are absent -- they live in out/ and are not in git, so a fresh clone
SKIPs this rather than failing it).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

JAR_ATTR = {'160': 'V160_JAR', '159': 'V159_JAR'}

#: runs inside the game: report duration and the applied bit for the named effects
JS = r'''
var G = Packages.mindustry.gen.Groups.unit;
var U = null;
for(var i = 0; i < G.size(); i++){
    var u = G.index(i);
    if(u.team == Packages.mindustry.game.Team.sharded){ U = u; break; }
}
if(U === null){ print('NOUNIT'); } else {
    var SE = Packages.mindustry.Vars.content.statusEffects();
    var want = %s;
    for(var j = 0; j < SE.size; j++){
        var e = SE.get(j);
        if(!want[e.name]) continue;
        print('E\t' + e.name + '\t' + Math.round(U.getDuration(e)) + '\t' + U.hasEffect(e));
    }
}
void 0
'''

#: reads the class of every compiled instruction: a privileged statement placed in
#: a micro processor vanishes without a trace, so the class list *is* the evidence
CLASSES_JS = r'''
var b = Vars.world.build(%d, %d);
if(b === null || b.executor === null){ print('NOPROC'); } else {
    var a = [];
    var ins = b.executor.instructions;
    for(var i = 0; i < ins.length; i++){
        a.push(String(ins[i].getClass().getSimpleName()));
    }
    print('CLS\t' + a.join(','));
}
void 0
'''


def as_lines(out):
    """srv.js() returns a list of lines on some paths and a string on others."""
    if out is None:
        return []
    if isinstance(out, str):
        return out.splitlines()
    return [str(x) for x in out]


def probe_js(names):
    return JS % json.dumps({n: 1 for n in names})


def read_effects(lines):
    got = {}
    for line in lines:
        if not line.startswith('E\t'):
            continue
        _, name, dur, has = line.split('\t')[:4]
        got[name] = (int(float(dur)), has == 'true')
    return got


def read_classes(srv):
    for line in as_lines(srv.js(CLASSES_JS % srv.base)):
        if line.startswith('CLS\t'):
            return [x for x in line.split('\t', 1)[1].split(',') if x]
    return []


def num_close(got, want):
    try:
        return abs(float(got) - float(want)) <= 1e-6
    except (TypeError, ValueError):
        return str(got) == str(want)


def check(p, rec, effects, classes):
    """Return the list of failed assertions; empty means the probe passed."""
    bad = []
    for name, want in (p.get('expect') or {}).items():
        dur, has = effects.get(name, (None, None))
        if dur != want:
            bad.append('%s duration want %s got %s' % (name, want, dur))
    for name, want in (p.get('expect_has') or {}).items():
        dur, has = effects.get(name, (None, None))
        if has != want:
            bad.append('%s hasEffect want %s got %s' % (name, want, has))

    vars_ = (rec or {}).get('vars') or {}
    for name, want in (p.get('expect_vars') or {}).items():
        got = vars_.get(name)
        if got is None:
            bad.append('%s missing (vars: %s)' % (name, sorted(vars_)))
        elif isinstance(want, dict):
            if not num_close(got, want.get('approx')):
                bad.append('%s want ~%s got %s' % (name, want.get('approx'), got))
            elif 'tol' in want and abs(float(got) - float(want['approx'])) > float(want['tol']):
                bad.append('%s want %s+-%s got %s' % (name, want['approx'], want['tol'], got))
        elif isinstance(want, (int, float)):
            if not num_close(got, want):
                bad.append('%s want %s got %s' % (name, want, got))
        elif str(got) != str(want):
            bad.append('%s want %r got %r' % (name, want, got))

    if 'expect_classes' in p:
        if list(classes) != list(p['expect_classes']):
            bad.append('classes want %s got %s' % (p['expect_classes'], classes))
    for name in (p.get('expect_classes_has') or []):
        if name not in classes:
            bad.append('class %s missing (got %s)' % (name, classes))

    text = (rec or {}).get('text')
    if text is None:
        text = ''
    if 'expect_text' in p and text != p['expect_text']:
        bad.append('text want %r got %r' % (p['expect_text'], text))
    for part in (p.get('expect_text_contains') or []):
        if part not in text:
            bad.append('text missing %r (got %r)' % (part, text))
    if p.get('expect_text_empty') and text != '':
        bad.append('text want empty got %r' % (text,))
    return bad


def run_one(p, java, M):
    """One probe, one server, one verdict: ("pass"|"fail"|"skip", id, why).

    Every probe boots its own JVM (~3 s each -- the dominant cost of this file),
    so main() runs them concurrently: they share nothing but the jars on disk.
    """
    jar = getattr(M, JAR_ATTR[p['jar']], None)
    if not jar or not pathlib.Path(jar).is_file():
        return ('skip', p['id'], 'missing jar ' + str(jar))
    names = list(p.get('expect') or {})
    proc = p.get('processor', 'auto')
    srv = None
    try:
        srv = M.Server(java, jar)
        srv._core_spec = 'copper:100'
        srv._unit_spec = [['flare', 1]]
        srv.prepare()
        for field, value in (p.get('rules') or {}).items():
            # Server.js() ends a console command by waiting for the line
            # "undefined" (Rhino prints the value of the last expression).  A bare
            # assignment evaluates to true/false and never prints it, so end the
            # script with an explicit void 0.
            srv.js('Vars.state.rules.%s = %s; void 0' % (
                field, 'true' if value is True else
                'false' if value is False else json.dumps(value)))
        rec = M.run_mlog(srv, 'p', p['code'], steps=int(p.get('steps', 20)),
                         processor=proc)
        effects = read_effects(as_lines(srv.js(probe_js(names))))
        classes = read_classes(srv)
    except Exception as exc:
        return ('fail', p['id'], '%s: %s' % (type(exc).__name__, str(exc)[:120]))
    finally:
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass
    bad = check(p, rec, effects, classes)
    if bad:
        return ('fail', p['id'], '; '.join(bad))
    return ('pass', p['id'], '')


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    jobs = min(8, os.cpu_count() or 4)
    filters = []
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == '--jobs' and rest:
            jobs = max(1, int(rest.pop(0)))
        elif a.startswith('--jobs='):
            jobs = max(1, int(a.split('=', 1)[1]))
        else:
            filters.append(a)

    manifest = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))
    probes = manifest['probes']
    if filters:
        probes = [p for p in probes if any(a.lower() in p['id'].lower() for a in filters)]
    try:
        import mlogsim as M
    except Exception as exc:
        print('SKIP cannot import tools/mlogsim.py: %s' % exc)
        return 3
    java = M._default_java()
    if not java:
        print('SKIP no java found (set MLOGSIM_JAVA)')
        return 3

    if jobs > 1 and len(probes) > 1:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            rows = list(pool.map(lambda pr: run_one(pr, java, M), probes))
    else:
        rows = [run_one(pr, java, M) for pr in probes]

    passed, failed, skipped = [], [], []
    for kind, pid, why in rows:
        if kind == 'pass':
            passed.append(pid)
        elif kind == 'skip':
            skipped.append((pid, why))
        else:
            failed.append((pid, why))

    for pid in passed:
        print('PASS ' + pid)
    for pid, why in skipped:
        print('SKIP ' + pid + ' -- ' + why)
    for pid, why in failed:
        print('FAIL ' + pid + ' -- ' + why)
    ran = len(passed) + len(failed)
    print('%d/%d probe(s) passed, %d skipped' % (len(passed), ran, len(skipped)))
    if failed:
        return 1
    return 0 if passed else 3


if __name__ == '__main__':
    raise SystemExit(main())
