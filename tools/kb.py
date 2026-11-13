#!/usr/bin/env python3
"""Build and query a local knowledge base over this repository's docs and tools.

Retrieval is hybrid: dense embeddings (bge-small-zh-v1.5, ONNX) + SQLite FTS5
trigram BM25, fused with reciprocal-rank fusion, and optionally reranked with a
cross-encoder (bge-reranker-base; off by default — it is weak on short
Chinese keyword queries). Everything runs locally through
``fastembed``/onnxruntime; no network is needed after the models are cached.

    python tools/kb.py build                 # index docs + tool sources
    python tools/kb.py search "jump 标签" -k 6
    python tools/kb.py search "read @this" --kind doc
    python tools/kb.py serve                 # MCP server on stdio
    python tools/kb.py stats

Corpus = 旧的固定文档清单 + docs/游戏速查 + tools/*.py + **knowledge/ 全库**
（knowledge/**/*.md 文章、00-data/*.json 的 schema 摘要、KB.md/CONVENTIONS.md/
VERSION.md 契约文档）。knowledge 根可用 KB_KNOWLEDGE 覆盖（默认 <repo>/knowledge）。

Models and libraries are looked up in ``out/_kblibs`` and ``out/_kbmodels``;
override with ``KB_LIBS`` / ``KB_MODELS``. On first build set
``HF_ENDPOINT=https://hf-mirror.com`` if huggingface.co is unreachable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("KB_ROOT", HERE.parent))
KB_DIR = Path(os.environ.get("KB_DIR", ROOT / "out" / "_kb"))
DB_PATH = KB_DIR / "kb.sqlite3"
_LIBS_DEFAULT = ROOT / "out" / ("_kblibs311" if sys.version_info < (3, 12) else "_kblibs")
LIBS = Path(os.environ.get("KB_LIBS", _LIBS_DEFAULT))
MODELS = Path(os.environ.get("KB_MODELS", ROOT / "out" / "_kbmodels"))
EMB_MODEL = os.environ.get("KB_EMB_MODEL", "BAAI/bge-small-zh-v1.5")
RERANK_MODEL = os.environ.get("KB_RERANK_MODEL", "BAAI/bge-reranker-base")
# knowledge/ 全库（文章 + 00-data）。KB_KNOWLEDGE 便于在别处试跑而不动仓库。
KNOWLEDGE_DIR = Path(os.environ.get("KB_KNOWLEDGE", ROOT / "knowledge"))
DATA_DIR = KNOWLEDGE_DIR / "00-data"
KNOWLEDGE_TOOLS_DIR = KNOWLEDGE_DIR / "tools"

DOC_FILES = [
    "README.md",
    "Logic/逻辑代码规范.md",
    "mindustry-blueprint/SKILL.md",
    "mindustry-blueprint/REFERENCE.md",
    "mindustry-blueprint/EMULATOR-CROSSCHECK.md",
    "tools/README.md",
    "dsh-preset-mlog/README.md",
    "rules/README.md",
    # Truth-source docs: what was actually run and what got refuted. Without
    # these, "is L2-07 still ✅?" is unanswerable from the KB (found 2026-10-24
    # when a rebuilt snapshot could not find 「已推翻」 anywhere).
    "docs/断言表.md",
    "docs/验证记录.md",
    # knowledge/ 的入口与契约（文章正文由 KNOWLEDGE_DIR 递归扫描，见 _corpus）
    "knowledge/KB.md",
    "knowledge/CONVENTIONS.md",
    "knowledge/VERSION.md",
]
CODE_GLOBS = ["tools/*.py", "tests/run_tests.py"]
DOC_GLOBS = ["docs/游戏速查/*.md"]
EXCLUDE_DIRS = {"__pycache__", "out", ".git", "assetsraw", "Mindustry-Source", "Arc-Source"}
# 语料权重（20 题确定性样本对照实验，见 knowledge/_report/bench20_*.md）：
# knowledge 文章是权威答案；tools/*.py 是原始实现，mlog 题上常抢 top1。
# knowledge ×1.25 + tools ×0.8 ⇒ A@1 9→14/20、A@3 12→15/20、top1 落在 knowledge 外 10→1。
KNOWLEDGE_BOOST = float(os.environ.get("KB_KNOWLEDGE_BOOST", "1.25"))
CODE_PENALTY = float(os.environ.get("KB_CODE_PENALTY", "0.8"))

def _path_weight(path: str) -> float:
    if path.startswith("knowledge/"):
        return KNOWLEDGE_BOOST
    if path.startswith("tools/") or path.startswith("tests/"):
        return CODE_PENALTY
    return 1.0

# ---------------------------------------------------------------- 检索策略 A/B/C
# 依据 08-evidence/bench/README.md §10.5（冻结快照 300 题，k=6，candidates=40）：
#   基线 67.5% → +A 73.5% → +A+B 78.2% → +A+B+C 85.6%（hit@6），库外槽位 18.5% → 0%。
# 三项默认全开，各自可用环境变量置 0 回退（便于对照实验，不影响 CLI/MCP 签名）。
#   A KB_ONLY_KNOWLEDGE=0  只检索 knowledge/（00-data 摘要仍保留）；显式 kind= 时放行全库
#   B KB_DEDUPE_FILE=0     结果按文件去重（k 数文档，同文件 top3 块合并、正文裁 1200 字）
#   C KB_ASCII_BOOST=0     FTS 标识符加权（×2）+ dense 权重下调（0.7）
def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off", "")

ONLY_KNOWLEDGE = _flag("KB_ONLY_KNOWLEDGE")
DEDUPE_FILE = _flag("KB_DEDUPE_FILE")
ASCII_BOOST = _flag("KB_ASCII_BOOST")
ASCII_DENSE_WEIGHT = float(os.environ.get("KB_ASCII_DENSE_WEIGHT", "0.7"))
CANDIDATES = int(os.environ.get("KB_CANDIDATES", "40"))

_EMB = None
_RR = None

def _ensure_libs() -> None:
    if LIBS.is_dir() and str(LIBS) not in sys.path:
        sys.path.insert(0, str(LIBS))

def _embedder():
    global _EMB
    if _EMB is None:
        _ensure_libs()
        from fastembed import TextEmbedding
        _EMB = TextEmbedding(model_name=EMB_MODEL, cache_dir=str(MODELS))
    return _EMB

def _reranker():
    global _RR
    if _RR is None:
        _ensure_libs()
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _RR = TextCrossEncoder(model_name=RERANK_MODEL, cache_dir=str(MODELS))
    return _RR

# ---------------------------------------------------------------- chunking
def _section_chunks(text: str, path: str, kind: str) -> list[dict]:
    """Split markdown by headings, code by top-level def/class blocks."""
    out: list[dict] = []
    if kind == "code":
        lines = text.splitlines()
        starts = [i for i, l in enumerate(lines, 1)
                  if re.match(r"^(?:def |class |@)", l)]
        if not starts or starts[0] != 1:
            starts = [1] + starts
        bounds = list(zip(starts, starts[1:] + [len(lines) + 1]))
        for s, e in bounds:
            body = "\n".join(lines[s - 1:e - 1])
            for piece, ps, pe in _split_long(body, s, 120):
                out.append({"path": path, "start": ps, "end": pe, "kind": kind,
                            "heading": "", "text": piece})
        return out

    lines = text.splitlines()
    heading = ""
    cur: list[str] = []
    cur_start = 1

    def flush(end_line: int):
        nonlocal cur, cur_start
        body = "\n".join(cur).strip()
        if body:
            lines = body.splitlines()
            # 标题行本身已经在 body 里了，别再加一次前缀（之前每个块标题都出现两遍）
            if lines and re.match(r"^#{1,4} ", lines[0]):
                body = "\n".join(lines[1:]).strip()
            prefix = f"# {heading}\n" if heading else ""
            if body:
                for piece, ps, pe in _split_long(prefix + body, cur_start, 1400):
                    out.append({"path": path, "start": ps, "end": pe, "kind": kind,
                                "heading": heading, "text": piece})
        cur = []

    for i, line in enumerate(lines, 1):
        if re.match(r"^#{1,4} ", line):
            flush(i)
            heading = line.lstrip("# ").strip()
            cur_start = i
        cur.append(line)
    flush(len(lines) + 1)
    return out

def _split_long(body: str, start: int, limit: int) -> list[tuple[str, int, int]]:
    """Split oversized text on paragraph boundaries; returns (text, start, end)."""
    if len(body) <= limit:
        return [(body, start, start + body.count("\n"))]
    chunks, cur, cur_start = [], [], start
    for line in body.splitlines():
        cur.append(line)
        if sum(len(x) + 1 for x in cur) >= limit:
            chunks.append(("\n".join(cur), cur_start, cur_start + len(cur) - 1))
            cur_start += len(cur)
            cur = []
    if cur:
        chunks.append(("\n".join(cur), cur_start, cur_start + len(cur) - 1))
    return chunks

def _rel(p: Path) -> str:
    """path 列统一成仓库相对路径；knowledge 根不在 ROOT 下时补 knowledge/ 前缀。"""
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return "knowledge/" + p.relative_to(KNOWLEDGE_DIR).as_posix()
        except ValueError:
            return p.name

def _knowledge_files() -> list[Path]:
    """knowledge/ 下的文章（md），排除 tools/ 与 00-data/（后者走 schema 摘要）。

    _report/、_kb/、_raw/ 等工作产物目录一律不进口语料：它们本身是检索报告，
    一旦入库会自我引用（实测 knowledge/_report/smoke_demo_new.md 抢到
    「conveyor 每秒运几件」的 top1），对回答没有价值。
    """
    if not KNOWLEDGE_DIR.is_dir():
        return []
    out = []
    for p in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        if not p.is_file():
            continue
        try:
            parts = p.relative_to(KNOWLEDGE_DIR).parts
        except ValueError:
            parts = (p.name,)
        if any(part.startswith("_") for part in parts) or any(part in EXCLUDE_DIRS for part in parts):
            continue
        if KNOWLEDGE_TOOLS_DIR in p.parents or DATA_DIR in p.parents:
            continue
        out.append(p)
    return out

def _fmt_val(v) -> str:
    if isinstance(v, dict):
        if "v" in v:
            u = v.get("unit") or ""
            return f"{v.get('v')}{u}"
        return json.dumps(v, ensure_ascii=False)[:60]
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)[:60]

def _data_summaries() -> list[tuple[str, str]]:
    """把 00-data/*.json 压成可按关键词检索的条目摘要（一条记录一行）。"""
    out: list[tuple[str, str]] = []
    if not DATA_DIR.is_dir():
        return out
    for p in sorted(DATA_DIR.glob("*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue
        recs = []
        if isinstance(obj, dict):
            for k in ("records", "items", "entries", "rows", "data"):
                if isinstance(obj.get(k), list):
                    recs = obj[k]
                    break
            if not recs:
                recs = [dict(v, id=k) for k, v in obj.items() if isinstance(v, dict)]
        elif isinstance(obj, list):
            recs = obj
        lines = [f"## 00-data/{p.name}（{len(recs)} 条）"]
        if isinstance(obj, dict) and isinstance(obj.get("meta"), dict):
            lines.append("- meta: " + ", ".join(
                f"{k}={_fmt_val(v)}" for k, v in list(obj["meta"].items())[:12]))
        for r in recs[:400]:
            if not isinstance(r, dict):
                continue
            rid = r.get("id") or r.get("name") or "?"
            name = r.get("name") or ""
            kv = [f"{k}={_fmt_val(v)}" for k, v in r.items()
                  if k not in ("id", "name", "src", "ver", "tags", "notes", "meta")]
            line = f"- {rid} {name}: " + ", ".join(kv[:8])
            if r.get("src"):
                line += f" [src: {r.get('src')}]"
            if r.get("ver"):
                line += f" ver={r.get('ver')}"
            lines.append(line)
        if len(recs) > 400:
            lines.append(f"- … 其余 {len(recs) - 400} 条略")
        out.append(("00-data/" + p.name, "\n".join(lines)))
    return out

def _corpus() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for rel in DOC_FILES:
        p = ROOT / rel
        if p.is_file():
            files.append((p, "doc"))
    for pattern in CODE_GLOBS:
        for p in sorted(ROOT.glob(pattern)):
            if p.is_file() and not any(part in EXCLUDE_DIRS for part in p.parts):
                files.append((p, "code"))
    for pattern in DOC_GLOBS:
        for p in sorted(ROOT.glob(pattern)):
            if p.is_file() and not any(part in EXCLUDE_DIRS for part in p.parts):
                files.append((p, "doc"))
    for p in _knowledge_files():
        files.append((p, "doc"))
    return files

# ---------------------------------------------------------------- index
def build(quiet: bool = False) -> dict:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """CREATE TABLE chunks(
               id INTEGER PRIMARY KEY, path TEXT, start INTEGER, end INTEGER,
               kind TEXT, heading TEXT, text TEXT, vec BLOB);
           CREATE VIRTUAL TABLE fts USING fts5(
               text, heading, path, content='chunks', content_rowid='id',
               tokenize='trigram');"""
    )
    rows: list[tuple] = []
    seen: set[str] = set()
    data_summaries = _data_summaries()
    for path, kind in _corpus():
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        rel = _rel(path)
        for ch in _section_chunks(text, rel, kind):
            norm = re.sub(r"\s+", "", ch["text"])
            if len(norm) < 24 or norm in seen:
                continue  # 同一段文字在 SKILL/README 等文档里重复出现时只留第一份
            seen.add(norm)
            rows.append((ch["path"], ch["start"], ch["end"], ch["kind"],
                         ch["heading"], ch["text"]))
    for rel, text in data_summaries:  # 00-data 摘要按 data 类型入库，便于精确查数值
        for ch in _section_chunks(text, rel, "data"):
            norm = re.sub(r"\s+", "", ch["text"])
            if len(norm) < 24 or norm in seen:
                continue
            seen.add(norm)
            rows.append((ch["path"], ch["start"], ch["end"], "data",
                         ch["heading"], ch["text"]))
    if not rows:
        raise SystemExit("no corpus files found")

    model = _embedder()
    vecs = []
    B = 32
    for i in range(0, len(rows), B):
        batch = [r[5] for r in rows[i:i + B]]
        vecs.extend(model.embed(batch))
    import numpy as np
    conn.executemany(
        "INSERT INTO chunks(path,start,end,kind,heading,text,vec) VALUES (?,?,?,?,?,?,?)",
        [(r[0], r[1], r[2], r[3], r[4], r[5],
          np.asarray(v, dtype="float32").tobytes()) for r, v in zip(rows, vecs)])
    conn.execute("INSERT INTO fts(rowid,text,heading,path) SELECT id,text,heading,path FROM chunks")
    conn.commit()
    n = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    conn.close()
    stats = {"chunks": n, "files": len({r[0] for r in rows}),
             "data_tables": len(data_summaries)}
    if not quiet:
        print(json.dumps(stats, ensure_ascii=False))
    return stats

def _open() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit("no index yet: python tools/kb.py build")
    return sqlite3.connect(DB_PATH)

def _fts_query(q: str) -> str:
    q = q.strip()
    if len(q) < 3:
        return ""
    return '"' + q.replace('"', '""') + '"'

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*(?::\d+(?:-\d+)?)?")

def _ident_terms(q: str) -> list[str]:
    """题面里的 ASCII 标识符（LExecutor.java / ConsumePower.java:10 / powerProduction）。

    trigram FTS 能精确匹配这些 token，dense 向量会把它们稀释 —— C 开关就是给它们加权。
    """
    out = []
    for m in _IDENT.finditer(q):
        t = m.group(0)
        if len(t) < 3 or not (t[0].isalpha() or t[0] == "_"):
            continue
        if ("." in t) or (":" in t) or ("_" in t) or re.search(r"[a-z][A-Z]", t) or t[0].isupper():
            out.append(t)
    seen, res = set(), []
    for t in out:
        if t.lower() not in seen:
            seen.add(t.lower())
            res.append(t)
    return res[:6]

def _scope_clause(kind: str | None) -> tuple[str, tuple]:
    """A：默认只检索 knowledge/（含 00-data 摘要表）；显式指定 kind 时放行全库。"""
    conds, args = [], []
    if kind:
        conds.append("kind = ?")
        args.append(kind)
    elif ONLY_KNOWLEDGE:
        conds.append("(path LIKE 'knowledge/%' OR path LIKE '00-data/%')")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return where, tuple(args)

def _sparse(conn, query: str, candidates: int) -> list[tuple[int, float]]:
    got: dict[int, tuple[float, float]] = {}
    fq = _fts_query(query)
    if fq:
        try:
            for rid, s in conn.execute(
                    "SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
                    (fq, candidates)):
                got[rid] = (1.0, float(s))
        except sqlite3.OperationalError:
            pass
    if ASCII_BOOST:  # C：标识符单独再查一次，权重 ×2（加权 bm25 取更负者）
        ids = _ident_terms(query)
        if ids:
            sub = " OR ".join('"' + t.replace('"', '""') + '"' for t in ids)
            try:
                for rid, s in conn.execute(
                        "SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
                        (sub, candidates)):
                    if rid in got:
                        got[rid] = (2.0, min(got[rid][1], float(s)))
                    else:
                        got[rid] = (2.0, float(s))
            except sqlite3.OperationalError:
                pass
    best: dict[int, float] = {}
    weight: dict[int, float] = {}
    for rid, (w, s) in got.items():
        sc = w * s
        if rid not in best or sc < best[rid]:
            best[rid] = sc
            weight[rid] = w
    ordered = sorted(best, key=lambda r: best[r])[:candidates]
    return [(rid, weight[rid]) for rid in ordered]

def search(query: str, k: int = 6, kind: str | None = None,
           rerank: bool = False, candidates: int | None = None) -> list[dict]:
    """A/B/C 三开关默认全开（KB_ONLY_KNOWLEDGE / KB_DEDUPE_FILE / KB_ASCII_BOOST 置 0 回退）。"""
    import numpy as np
    if candidates is None:
        candidates = CANDIDATES
    conn = _open()
    where, args = _scope_clause(kind)
    rows = conn.execute(f"SELECT id,path,start,end,kind,heading,text,vec FROM chunks{where}",
                        args).fetchall()
    if not rows:
        conn.close()
        return []
    by_id = {r[0]: r for r in rows}
    qv = np.asarray(next(iter(_embedder().embed([query]))), dtype="float32")
    mat = np.frombuffer(b"".join(r[7] for r in rows), dtype="float32").reshape(len(rows), -1)
    sims = mat @ qv / (np.linalg.norm(mat, axis=1) * np.linalg.norm(qv) + 1e-9)
    dense = list(np.argsort(-sims)[:candidates])
    sparse = _sparse(conn, query, candidates)
    conn.close()

    wd = ASCII_DENSE_WEIGHT if ASCII_BOOST else 1.0
    fused: dict[int, float] = {}
    for rank, i in enumerate(dense):
        cid = rows[i][0]
        fused[cid] = fused.get(cid, 0.0) + wd / (60 + rank)
    for rank, (cid, w) in enumerate(sparse):
        if cid in by_id:
            fused[cid] = fused.get(cid, 0.0) + w / (60 + rank)

    def _score(cid: int) -> float:
        return fused[cid] * _path_weight(by_id[cid][1])

    scores = {cid: _score(cid) for cid in fused}
    if rerank and fused:
        try:
            rr = _reranker()
            ids = sorted(fused, key=lambda c: -scores[c])[:candidates]
            vals = list(rr.rerank(query, [by_id[c][6] for c in ids]))
            for cid, v in zip(ids, vals):
                scores[cid] = float(v) * _path_weight(by_id[cid][1])
        except Exception as exc:  # rerank is optional
            print(f"rerank skipped: {exc}", file=sys.stderr)

    if not DEDUPE_FILE:
        ordered = sorted(fused, key=lambda c: -scores[c])[:k]
        out = []
        for cid in ordered:
            r = by_id[cid]
            out.append({"path": r[1], "start": r[2], "end": r[3], "kind": r[4],
                        "heading": r[5], "text": r[6], "score": round(scores[cid], 4)})
        return out

    # B：k 数文档而不是 chunk —— 同一 .md 的连号块合并成一条，正文裁到 1200 字符。
    per_file: dict[str, list[tuple[float, int]]] = {}
    for cid in fused:
        per_file.setdefault(by_id[cid][1], []).append((scores[cid], cid))
    ranked = []
    for path, lst in per_file.items():
        lst.sort(key=lambda x: -x[0])
        ranked.append((lst[0][0], path, lst))
    ranked.sort(key=lambda x: -x[0])
    out = []
    for sc, path, lst in ranked[:k]:
        parts, starts, ends = [], [], []
        for _s, cid in lst[:3]:
            r = by_id[cid]
            parts.append(r[6].strip())
            starts.append(r[2])
            ends.append(r[3])
        text = "\n\n".join(parts)
        if len(text) > 1200:
            text = text[:1200] + "…"
        top = by_id[lst[0][1]]
        out.append({"path": path, "start": min(starts), "end": max(ends),
                    "kind": top[4], "heading": top[5] or "", "text": text,
                    "score": round(sc, 4), "n_chunks": len(parts)})
    return out

def _format(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        snippet = " ".join(r["text"].split())
        if len(snippet) > 420:
            snippet = snippet[:420] + "…"
        head = f" — {r['heading']}" if r["heading"] else ""
        lines.append(f"[{i}] {r['path']}:{r['start']}-{r['end']}{head}  score={r['score']}")
        lines.append(f"    {snippet}")
    return "\n".join(lines) if lines else "(no results)"

# ---------------------------------------------------------------- MCP
def serve() -> None:
    """Minimal MCP stdio server exposing the kb_search tool."""
    _embedder()  # warm up before answering
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            method = msg.get("method")
            mid = msg.get("id")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mlog-kb", "version": "0.1.0"}}
            elif method == "tools/list":
                result = {"tools": [{
                    "name": "kb_search",
                    "description": "Search this repo's mlog docs and tool sources (hybrid dense+BM25; optional cross-encoder rerank).",
                    "inputSchema": {"type": "object", "properties": {
                        "query": {"type": "string"},
                        "k": {"type": "integer", "default": 6},
                        "kind": {"type": "string", "enum": ["doc", "data", "code"]}},
                        "required": ["query"]}}]}
            elif method == "tools/call":
                params = msg.get("params", {})
                if params.get("name") != "kb_search":
                    raise ValueError(f"unknown tool: {params.get('name')}")
                args = params.get("arguments", {})
                res = search(str(args.get("query", "")), int(args.get("k", 6)),
                             args.get("kind"), rerank=bool(args.get("rerank", False)))
                result = {"content": [{"type": "text", "text": _format(res)}],
                          "isError": False}
            elif method in ("notifications/initialized", "notifications/cancelled"):
                continue
            else:
                result = {}
            if mid is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result},
                                 ensure_ascii=False), flush=True)
        except Exception as exc:
            msg = str(exc)
            if os.environ.get("KB_DEBUG"):
                import traceback
                msg = traceback.format_exc()
            print(json.dumps({"jsonrpc": "2.0", "id": locals().get("mid"),
                              "error": {"code": -32000, "message": msg}},
                             ensure_ascii=False), flush=True)

# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=6)
    sp.add_argument("--kind", choices=["doc", "data", "code"])
    sp.add_argument("--rerank", action="store_true",
                    help="cross-encoder rerank (off by default: bge-reranker-base is weak on short Chinese queries)")
    sub.add_parser("serve")
    sub.add_parser("stats")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        build()
        return 0
    if args.cmd == "serve":
        serve()
        return 0
    if args.cmd == "stats":
        if not DB_PATH.exists():
            print("no index yet: run `python tools/kb.py build` first")
            return 1
        with sqlite3.connect(DB_PATH) as cx:
            n = cx.execute("select count(*) from chunks").fetchone()[0]
            files = cx.execute("select count(distinct path) from chunks").fetchone()[0]
            kinds = dict(cx.execute("select kind, count(*) from chunks group by kind").fetchall())
            files_by_kind = {k: cx.execute("select count(distinct path) from chunks where kind=?",
                                           (k,)).fetchone()[0] for k in kinds}
        print(json.dumps({"chunks": n, "files": files, "kinds": kinds,
                          "files_by_kind": files_by_kind,
                          "data_tables": files_by_kind.get("data", 0)}, ensure_ascii=False))
        return 0
    res = search(args.query, args.k, args.kind, rerank=args.rerank)
    print(_format(res))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
