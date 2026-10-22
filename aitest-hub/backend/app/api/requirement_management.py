"""UI requirement management: flat module, /api/requirements endpoints."""

import io
import json
import os
import re
import unicodedata
import zipfile
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    get_db,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    db_execute,
    db_commit,
)
from app.core.deps import get_current_user
from app.services import ai as ai_service

router = APIRouter(tags=["ui-requirements"])

# 鉴权契约（与 UI 对齐）：
# - 读接口（GET 列表/详情）与纯 AI 分析接口（ai-parse / ai-test）不鉴权，演示可读
# - 数据变更写操作（create / parse / derive / archive）保持 get_current_user

# statuses (unicode escapes to keep this file pure-ASCII for tooling safety)
S_PARSE = "\u5f85\u89e3\u6790"  # pending parse
S_PARSED = "\u5df2\u89e3\u6790"  # parsed
S_DERIVED = "\u5df2\u6d3e\u751f"  # derived
S_ARCHIVED = "\u5df2\u5f52\u6863"  # archived


class ReqCreate(BaseModel):
    id: str = ""
    title: str
    pri: str = "P1"
    src: str = ""
    desc: str = ""


class DeriveReq(BaseModel):
    type: str = "case"


class AiParseReq(BaseModel):
    docs: List[str] = []
    model: str = ""


_SEED = json.loads(
    """[{"id": "REQ-2026-0125", "title": "\u8ba2\u5355\u9000\u6b3e\u529f\u80fd", "pri": "P0", "status": "\u5df2\u6d3e\u751f", "src": "\u4ea7\u54c1 PRD", "items": 5, "cases": 10, "perf": 1, "sec": 3, "defects": 2, "desc": "\u7528\u6237\u53ef\u5728\u8ba2\u5355\u8be6\u60c5\u53d1\u8d77\u9000\u6b3e\uff0c\u9009\u62e9\u9000\u6b3e\u539f\u56e0\u4e0e\u8bf4\u660e\uff0c\u63d0\u4ea4\u540e\u8fdb\u5165\u5ba1\u6838\u6d41\u7a0b\uff0c\u5ba1\u6838\u901a\u8fc7\u540e\u539f\u8def\u9000\u56de\u3002"}, {"id": "REQ-2026-0121", "title": "\u5927\u4fc3\u79d2\u6740\u6d3b\u52a8", "pri": "P0", "status": "\u5df2\u6d3e\u751f", "src": "\u4ea7\u54c1 PRD", "items": 7, "cases": 14, "perf": 2, "sec": 2, "defects": 1, "desc": "\u6574\u70b9\u5f00\u62a2\u79d2\u6740\u5546\u54c1\uff0c\u5e93\u5b58\u9884\u70ed\u3001\u9650\u6d41\u9632\u8d85\u5356\u3001\u5355\u4eba\u9650\u8d2d 2 \u4ef6\u3002"}, {"id": "REQ-2026-0118", "title": "\u7528\u6237\u4e2d\u5fc3\u6539\u7248", "pri": "P1", "status": "\u5df2\u89e3\u6790", "src": "\u84dd\u6e56\u539f\u578b", "items": 6, "cases": 0, "perf": 0, "sec": 0, "defects": 0, "desc": "\u4e2a\u4eba\u4e2d\u5fc3\u4fe1\u606f\u67b6\u6784\u8c03\u6574\uff0c\u65b0\u589e\u6d88\u606f\u4e2d\u5fc3\u4e0e\u5e38\u7528\u529f\u80fd\u805a\u5408\u9875\u3002"}, {"id": "REQ-2026-0112", "title": "\u652f\u4ed8\u6e20\u9053\u6269\u5c55-\u6570\u5b57\u4eba\u6c11\u5e01", "pri": "P1", "status": "\u5f85\u89e3\u6790", "src": "\u4ea7\u54c1 PRD", "items": 0, "cases": 0, "perf": 0, "sec": 0, "defects": 0, "desc": "\u63a5\u5165\u6570\u5b57\u4eba\u6c11\u5e01\u652f\u4ed8\u6e20\u9053\uff0c\u652f\u6301\u94b1\u5305\u4f59\u989d\u4e0e\u94f6\u884c\u5361\u3002"}, {"id": "REQ-2026-0105", "title": "\u65e7\u7248\u9000\u6b3e\u9875\u4e0b\u7ebf", "pri": "P2", "status": "\u5df2\u5f52\u6863", "src": "\u7ebf\u4e0a\u7f3a\u9677\u53cd\u63a8", "items": 2, "cases": 1, "perf": 0, "sec": 0, "defects": 0, "desc": "\u4e0b\u7ebf\u65e7\u7248\u9000\u6b3e\u9875\u9762\uff0c\u9700\u517c\u5bb9\u5386\u53f2\u94fe\u63a5\u8df3\u8f6c\u3002"}]"""
)

_PARSE_SEED = json.loads(
    """[{"no": "FR-01", "text": "\u7528\u6237\u5728\u8ba2\u5355\u8be6\u60c5\u9875\u70b9\u51fb\u300c\u7533\u8bf7\u9000\u6b3e\u300d\u8fdb\u5165\u7533\u8bf7\u9875\uff0c\u9000\u6b3e\u539f\u56e0\u5fc5\u586b\uff087 \u9879\u679a\u4e3e\uff09", "dim": "\u4e1a\u52a1\u9700\u6c42"}, {"no": "FR-02", "text": "\u9000\u6b3e\u8bf4\u660e\u9009\u586b\uff0c\u6700\u591a 200 \u5b57\uff0c\u8d85\u51fa\u7981\u6b62\u8f93\u5165", "dim": "\u8fb9\u754c\u6761\u4ef6"}, {"no": "FR-03", "text": "\u63d0\u4ea4\u540e\u751f\u6210\u9000\u6b3e\u5355\uff08\u5f85\u5ba1\u6838\uff09\uff0c\u53ef\u64a4\u9500\uff1b\u5ba1\u6838\u901a\u8fc7\u540e 1-3 \u4e2a\u5de5\u4f5c\u65e5\u539f\u8def\u9000\u56de", "dim": "\u4e1a\u52a1\u9700\u6c42"}, {"no": "FR-04", "text": "\u5ba1\u6838\u62d2\u7edd\u540e\u7528\u6237\u53ef\u91cd\u65b0\u7533\u8bf7\uff0c\u5386\u53f2\u8bb0\u5f55\u4fdd\u7559", "dim": "\u5f02\u5e38\u6d41"}, {"no": "NFR-01", "text": "\u9000\u6b3e\u63a5\u53e3\u5cf0\u503c QPS \u76ee\u6807 500\uff0cP99 \u54cd\u5e94\u65f6\u95f4 \u2264 300ms", "dim": "\u6027\u80fd\u6307\u6807"}, {"no": "SEC-01", "text": "\u9000\u6b3e\u91d1\u989d\u7531\u670d\u52a1\u7aef\u6309\u8ba2\u5355\u5b9e\u4ed8\u8ba1\u7b97\uff0c\u7981\u6b62\u5ba2\u6237\u7aef\u4f20\u5165\uff0c\u9632\u7be1\u6539", "dim": "\u5b89\u5168\u8981\u6c42"}]"""
)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def _ensure_schema(db: SyncDB):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS rm_requirements (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, pri TEXT, status TEXT, src TEXT,
        items INTEGER DEFAULT 0, cases INTEGER DEFAULT 0, perf INTEGER DEFAULT 0,
        sec INTEGER DEFAULT 0, defects INTEGER DEFAULT 0, descr TEXT, created_at TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB):
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM rm_requirements", [])
    if row and row["c"]:
        return
    for r in _SEED:
        await db_insert(
            db,
            "rm_requirements",
            {
                "id": r["id"],
                "title": r["title"],
                "pri": r["pri"],
                "status": r["status"],
                "src": r["src"],
                "items": r["items"],
                "cases": r["cases"],
                "perf": r["perf"],
                "sec": r["sec"],
                "defects": r["defects"],
                "descr": r.get("desc", ""),
                "created_at": _now(),
            },
        )
    await db_commit(db)


def _row(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r.get("title", ""),
        "pri": r.get("pri", "P2"),
        "status": r.get("status", S_PARSE),
        "src": r.get("src", ""),
        "items": r.get("items", 0) or 0,
        "cases": r.get("cases", 0) or 0,
        "perf": r.get("perf", 0) or 0,
        "sec": r.get("sec", 0) or 0,
        "defects": r.get("defects", 0) or 0,
        "desc": r.get("descr", ""),
    }


async def _load(db: SyncDB, rid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM rm_requirements WHERE id=?", [rid])
    if not row:
        raise HTTPException(status_code=404, detail="requirement not found")
    return row


async def _next_id(db: SyncDB) -> str:
    rows = await db_fetch_all(
        db, "SELECT id FROM rm_requirements WHERE id LIKE 'REQ-2026-%'", []
    )
    best = 125
    for r in rows:
        try:
            best = max(best, int(r["id"].split("-")[-1]))
        except Exception:
            pass
    return "REQ-2026-%04d" % (best + 1)


# ---------------------------------------------------------------------------
# 统一 AI（app.services.ai）：无 API Key / 调用失败时自动降级为演示数据
# ---------------------------------------------------------------------------

_DIM_KNOWN = ("业务需求", "边界条件", "异常流", "性能指标", "安全要求")
_DIM_ALIAS = {
    "功能": "业务需求",
    "功能需求": "业务需求",
    "业务": "业务需求",
    "需求": "业务需求",
    "边界": "边界条件",
    "边界值": "边界条件",
    "异常": "异常流",
    "异常场景": "异常流",
    "性能": "性能指标",
    "安全": "安全要求",
}


def _norm_dim(v) -> str:
    s = str(v or "").strip()
    if s in _DIM_KNOWN:
        return s
    return _DIM_ALIAS.get(s, s or "业务需求")


def _norm_items(data) -> Optional[list]:
    """把 AI 返回归一为 UI ParseItem: {no, text, dim}。"""
    raw = (
        data.get("items")
        if isinstance(data, dict)
        else (data if isinstance(data, list) else None)
    )
    if not isinstance(raw, list):
        return None
    out = []
    for it in raw[:20]:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or it.get("content") or it.get("desc") or "").strip()
        if not text:
            continue
        no = str(it.get("no") or it.get("id") or "").strip() or (
            "FR-%02d" % (len(out) + 1)
        )
        out.append(
            {"no": no, "text": text, "dim": _norm_dim(it.get("dim") or it.get("type"))}
        )
    return out or None


"""Uploaded requirement document text extraction (txt/md/csv/json/... + docx + xlsx)."""

_TEXT_EXT = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".log",
    ".yml",
    ".yaml",
    ".xml",
    ".html",
    ".htm",
    ".sql",
    ".py",
    ".js",
    ".ts",
    ".vue",
    ".java",
    ".properties",
    ".ini",
    ".conf",
    ".text",
    ".rtf",
}


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_docx(raw: bytes) -> str:
    """docx = zip(word/document.xml); strip tags to plain text, no extra deps."""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p\s*>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _extract_xlsx(raw: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    lines: List[str] = []
    try:
        for ws in wb.worksheets:
            lines.append("## sheet: " + str(ws.title))
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PDF 中文修复：Identity-H 字体子集（ToUnicode 损坏）的 GID → Unicode 还原
#
# 现象：WPS / 预览 导出的中文 PDF 常用 PingFangSC 等系统字体子集，
# ToUnicode CMap 缺失或损坏时，pypdf/pymupdf 只能按 CID 输出乱码
# （如「学生管理系统需求」变成「਍ኞilikቘᔮᕹ」）。
# 关键点：此类子集的 CID 就是原字体的 GID，而 macOS 自带同名字体，
# 因此可用系统字体的 glyphOrder + cmap 反查出真实 Unicode。
# ---------------------------------------------------------------------------

_CJK_FONT_HINTS = (
    "pingfang",
    "songti",
    "stheiti",
    "heit",
    "hiragino",
    "yuanti",
    "lantinghei",
    "stfangsong",
    "stxihei",
    "stkaiti",
    "stliti",
    "stsong",
    "kaiti",
    "fangsong",
)
_GID_MAP_CACHE: Dict[str, Dict[int, str]] = {}


def _is_cjk_font(font_name: str) -> bool:
    low = (font_name or "").lower()
    return any(h in low for h in _CJK_FONT_HINTS)


def _iter_system_ttc() -> List[str]:
    """收集 macOS 系统里可能包含中文字体的 .ttc 候选路径。"""
    import glob as _glob

    patterns = [
        "/System/Library/AssetsV2/com_apple_MobileAsset_Font*/**/*.ttc",
        "/System/Library/Fonts/**/*.ttc",
        "/Library/Fonts/**/*.ttc",
        os.path.expanduser("~/Library/Fonts/**/*.ttc"),
    ]
    seen: List[str] = []
    for pat in patterns:
        for p in _glob.glob(pat, recursive=True):
            if p not in seen:
                seen.append(p)
    return seen


def _face_name_matches(face: str, want: str) -> bool:
    """判断 TTC 中某个 face 名是否匹配 PDF 里出现的字体名。"""
    a = re.sub(r"[^a-z0-9]", "", (face or "").lower())
    b = re.sub(r"[^a-z0-9]", "", (want or "").lower())
    if not a or not b:
        return False
    # 「PingFang SC Regular」 vs 「PingFangSC-Regular」
    if a == b:
        return True
    return a.startswith(b) or b.startswith(a) or a in b or b in a


def _load_gid_map(pdf_font_name: str) -> Dict[int, str]:
    """从系统字体建立 GID → 字符 映射（进程内缓存）。"""
    cached_key = None
    for k in _GID_MAP_CACHE:
        if _face_name_matches(k, pdf_font_name):
            cached_key = k
            break
    if cached_key:
        return _GID_MAP_CACHE[cached_key]

    try:
        from fontTools.ttLib import TTCollection
    except ImportError:
        return {}

    for ttc in _iter_system_ttc():
        try:
            coll = TTCollection(ttc, lazy=True)
        except Exception:  # noqa: BLE001 - 非字体/损坏文件直接跳过
            continue
        try:
            for face in coll.fonts:
                try:
                    name = face["name"].getDebugName(4) or ""
                except Exception:  # noqa: BLE001
                    continue
                if not _face_name_matches(name, pdf_font_name):
                    continue
                order = face.getGlyphOrder()
                # getBestCmap 返回 {unicode: glyphName}，需先换算成 GID
                gid_of = {gname: idx for idx, gname in enumerate(order)}
                cmap = face.getBestCmap() or {}
                reverse = {
                    gid_of[gname]: cp for cp, gname in cmap.items() if gname in gid_of
                }
                mapping: Dict[int, str] = {}
                for gid, name_g in enumerate(order):
                    cp = reverse.get(gid)
                    if cp is None:
                        # 子集字形名多为 cidNNNN / uniXXXX
                        m = re.match(r"uni([0-9A-Fa-f]{4,6})$", name_g)
                        if m:
                            cp = int(m.group(1), 16)
                    if cp is None:
                        continue
                    ch = unicodedata.normalize("NFKC", chr(cp))
                    if ch:
                        mapping[gid] = ch
                if mapping:
                    _GID_MAP_CACHE[name] = mapping
                    return mapping
        except Exception:  # noqa: BLE001
            continue
        finally:
            try:
                coll.close()
            except Exception:  # noqa: BLE001
                pass
    return {}


def _looks_garbled(text: str) -> bool:
    """中文 PDF 提取结果是否为 CID 乱码。"""
    if not text:
        return False
    cjk = 0
    weird = 0
    total_non_ascii = 0
    for ch in text:
        o = ord(ch)
        if o < 0x80:
            continue
        total_non_ascii += 1
        if (
            0x4E00 <= o <= 0x9FFF
            or 0x3000 <= o <= 0x303F
            or 0xFF00 <= o <= 0xFFEF
            or 0xF900 <= o <= 0xFAFF
            or o in (0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x00B7)
        ):
            cjk += 1
        else:
            weird += 1
    if total_non_ascii < 8:
        return False
    return weird / float(total_non_ascii) > 0.25


def _decode_pdf_with_cid_repair(raw: bytes) -> Optional[str]:
    """用 pymupdf 逐字符提取，对中文字体 span 做 GID→Unicode 还原。"""
    try:
        import pymupdf  # noqa: PLC0415 - 懒加载
    except ImportError:
        return None

    doc = pymupdf.open(stream=raw, filetype="pdf")
    try:
        out_pages: List[str] = []
        repaired = 0
        for page in doc:
            page_lines: List[str] = []
            data = page.get_text("rawdict")
            for block in data.get("blocks", []):
                block_lines: List[str] = []
                for line in block.get("lines", []):
                    buf: List[str] = []
                    for span in line.get("spans", []):
                        font = str(span.get("font") or "")
                        gid_map = _load_gid_map(font) if _is_cjk_font(font) else None
                        for item in span.get("chars", []):
                            ch = str(item.get("c") or "")
                            if gid_map and ch:
                                mapped = gid_map.get(ord(ch))
                                if mapped:
                                    if mapped != ch:
                                        repaired += 1
                                    ch = mapped
                            buf.append(ch)
                    block_lines.append("".join(buf))
                if block_lines:
                    page_lines.append("\n".join(block_lines))
            out_pages.append("\n\n".join(page_lines))
        text = "\n".join(out_pages).strip()
        if repaired and not _looks_garbled(text):
            return text
        return None
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass


def _extract_pdf(raw: bytes) -> str:
    """Extract text from PDF.

    优先用 pymupdf + 系统字体 GID 还原（修复 Identity-H 中文子集乱码），
    失败再回退 pypdf。
    """
    text = ""
    repaired = _decode_pdf_with_cid_repair(raw)
    if repaired:
        text = repaired
    if not text:
        try:
            from pypdf import PdfReader
        except ImportError:  # 未安装 pypdf 时的友好提示
            raise HTTPException(
                status_code=400,
                detail="暂不支持 PDF（服务端未安装 pymupdf/pypdf），请先导出为 .txt/.md/.docx",
            )
        reader = PdfReader(io.BytesIO(raw))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        text = "\n".join(pages).strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail="PDF 未提取到文本（可能为扫描件/图片型 PDF），请先导出为 .txt/.md",
        )
    return text


def _extract_doc(raw: bytes) -> str:
    """Extract text from legacy binary .doc.

    Preferred: macOS `textutil` (ships with macOS, converts .doc->txt reliably).
    Fallback: olefile WordDocument stream best-effort decode.
    """
    # 1) macOS textutil（可靠）—— 写入临时 .doc，textutil 转 txt
    tmp_dir = None
    try:
        import tempfile, os, subprocess

        tmp_dir = tempfile.mkdtemp(prefix="aitest_doc_")
        src = os.path.join(tmp_dir, "input.doc")
        with open(src, "wb") as fh:
            fh.write(raw)
        res = subprocess.run(
            [
                "textutil",
                "-convert",
                "txt",
                "-output",
                os.path.join(tmp_dir, "out.txt"),
                src,
            ],
            capture_output=True,
            timeout=30,
        )
        if res.returncode == 0:
            with open(
                os.path.join(tmp_dir, "out.txt"),
                "r",
                encoding="utf-8",
                errors="replace",
            ) as fh:
                text = fh.read()
            if text.strip():
                return text.strip()
    except Exception:  # noqa: BLE001 - textutil 不可用/失败则回退
        pass
    finally:
        if tmp_dir:
            import shutil

            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
    # 2) 回退：olefile 尽力提取
    try:
        import olefile
    except ImportError:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail="暂不支持 .doc，请另存为 .docx / .txt 后上传"
        )
    ole = olefile.OleFileIO(io.BytesIO(raw))
    try:
        if not ole.exists("WordDocument"):
            raise HTTPException(
                status_code=400, detail="无效的 .doc 文件（缺少 WordDocument 流）"
            )
        stream = None
        try:
            if ole.exists("1Table"):
                stream = ole.openstream("1Table")
            elif ole.exists("0Table"):
                stream = ole.openstream("0Table")
        except Exception:  # noqa: BLE001
            stream = None
        text = ""
        if stream is not None:
            text = stream.read().decode("utf-16-le", errors="replace")
        if not text.strip():
            wd = ole.openstream("WordDocument").read()
            text = "".join(chr(b) for b in wd if 32 <= b < 127 or b in (9, 10, 13))
        return re.sub(r"\s+", " ", text).strip() or "（.doc 未能提取到文本）"
    finally:
        ole.close()


def _extract_doc_text(filename: str, raw: bytes) -> str:
    """Extract readable text from an uploaded file; 400 when unsupported."""
    name = (filename or "").strip().lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if not raw:
        raise HTTPException(status_code=400, detail="空文件: %s" % (filename or ""))
    if ext in _TEXT_EXT:
        return _decode_bytes(raw)
    if ext == ".docx":
        try:
            return _extract_docx(raw)
        except Exception as exc:  # noqa: BLE001 - surface parse failure to caller
            raise HTTPException(
                status_code=400, detail="docx 解析失败: %s (%s)" % (filename, exc)
            )
    if ext in (".xlsx", ".xlsm"):
        try:
            return _extract_xlsx(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400, detail="xlsx 解析失败: %s (%s)" % (filename, exc)
            )
    if ext == ".pdf":
        try:
            return _extract_pdf(raw)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - surface parse failure to caller
            raise HTTPException(
                status_code=400, detail="pdf 解析失败: %s (%s)" % (filename, exc)
            )
    if ext == ".doc":
        try:
            return _extract_doc(raw)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400, detail="doc 解析失败: %s (%s)" % (filename, exc)
            )
    raise HTTPException(
        status_code=400,
        detail="不支持的文件类型: %s（支持 txt/md/csv/json/docx/xlsx 等）"
        % (filename or "未知"),
    )


def _parse_messages(docs: List[str], model: str) -> list:
    body = "\n---\n".join((d or "")[:2000] for d in (docs or [])[:5])
    system = (
        "你是资深测试需求分析师。根据需求文档片段提取需求条目，"
        "只输出一个 JSON 对象（不要 Markdown）："
        '{"items": [{"no": "FR-01", "text": "一句话需求描述", '
        '"dim": "业务需求|边界条件|异常流|性能指标|安全要求"}]}，'
        "no 顺序编号，dim 只能取上述五个值，输出 4~12 条。"
    )
    user = "选用模型：%s\n\n需求文档：\n%s" % (model or "默认", body or "（空）")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _ai_parse_items(db: SyncDB, docs: List[str], model: str) -> Optional[list]:
    """走统一 AI 服务解析条目；无 Key/失败/非结构化输出返回 None（调用方降级 seed）。"""
    try:
        data = await ai_service.chat_json(
            db, _parse_messages(docs, model), module="需求解析", model=model or None
        )
        return _norm_items(data)
    except Exception:
        return None


@router.get("/requirements")
async def list_requirements(db: SyncDB = Depends(get_db)):
    await _ensure_schema(db)
    await _seed_if_empty(db)
    rows = await db_fetch_all(db, "SELECT * FROM rm_requirements ORDER BY id DESC", [])
    return [_row(r) for r in rows]


@router.get("/requirements/{rid}")
async def get_requirement(rid: str, db: SyncDB = Depends(get_db)):
    await _ensure_schema(db)
    await _seed_if_empty(db)
    return _row(await _load(db, rid))


@router.post("/requirements")
async def create_requirement(
    body: ReqCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    await _seed_if_empty(db)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="title required")
    rid = body.id.strip() or await _next_id(db)
    if await db_fetch_one(db, "SELECT id FROM rm_requirements WHERE id=?", [rid]):
        raise HTTPException(status_code=409, detail="requirement id exists")
    await db_insert(
        db,
        "rm_requirements",
        {
            "id": rid,
            "title": body.title.strip(),
            "pri": body.pri,
            "status": S_PARSE,
            "src": body.src,
            "items": 0,
            "cases": 0,
            "perf": 0,
            "sec": 0,
            "defects": 0,
            "descr": body.desc,
            "created_at": _now(),
        },
    )
    return _row(await _load(db, rid))


@router.post("/requirements/ai-parse")
async def ai_parse(body: AiParseReq, db: SyncDB = Depends(get_db)):
    """AI 解析需求文档 → 条目化（统一 AI 服务；无 Key/失败降级演示条目）。"""
    await _ensure_schema(db)
    if not body.docs:
        raise HTTPException(status_code=400, detail="docs required")
    items = await _ai_parse_items(db, body.docs, body.model)
    if not items:
        items = [dict(it) for it in _PARSE_SEED]
    return {"items": items, "model": body.model or "default"}


@router.post("/doc-extract")
async def extract_doc_texts(files: List[UploadFile] = File(...)):
    """通用文档正文提取（供各模块「上传附件/资源」复用）。

    Returns {docs: [{name, text}], errors: [{name, error}]}.
    Unextractable types (e.g. image/pdf) are reported in errors instead of
    failing the whole batch, so callers can still send file names as context.
    """
    uploads = [f for f in (files or []) if f is not None]
    if not uploads:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")
    if len(uploads) > 5:
        raise HTTPException(status_code=400, detail="最多上传 5 个文件")
    docs: List[dict] = []
    errors: List[dict] = []
    for f in uploads:
        name = f.filename or "未命名"
        raw = await f.read()
        if len(raw) > 5 * 1024 * 1024:
            errors.append({"name": name, "error": "文件超过 5MB 限制"})
            continue
        if not raw:
            errors.append({"name": name, "error": "文件为空"})
            continue
        try:
            text = _extract_doc_text(name, raw).strip()
        except HTTPException as exc:
            errors.append({"name": name, "error": str(exc.detail)})
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append({"name": name, "error": "解析失败: %s" % exc})
            continue
        if not text:
            errors.append({"name": name, "error": "文件内容为空"})
            continue
        docs.append({"name": name, "text": text[:6000]})
    return {"docs": docs, "errors": errors}


@router.post("/requirements/ai-parse-file")
async def ai_parse_files(
    files: List[UploadFile] = File(...),
    model: str = Form(""),
    db: SyncDB = Depends(get_db),
):
    """真正上传需求文档（multipart）→ 服务端提取正文 → AI 解析条目化。

    Supports: txt/md/csv/json/log/yml/html/sql/py/... , docx (zip+xml), xlsx (openpyxl).
    Files content is extracted server-side and fed to the AI prompt.
    """
    await _ensure_schema(db)
    uploads = [f for f in (files or []) if f is not None]
    if not uploads:
        raise HTTPException(status_code=400, detail="请至少上传一个文档文件")
    if len(uploads) > 5:
        raise HTTPException(status_code=400, detail="最多上传 5 个文档")
    docs: List[str] = []
    parsed: List[str] = []
    for f in uploads:
        raw = await f.read()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="文件超过 5MB 限制: %s" % (f.filename or ""),
            )
        text = _extract_doc_text(f.filename or "", raw).strip()
        if not text:
            raise HTTPException(
                status_code=400, detail="文件内容为空: %s" % (f.filename or "")
            )
        docs.append("【文件: %s】\n%s" % (f.filename or "未命名", text))
        parsed.append(f.filename or "未命名")
    items = await _ai_parse_items(db, docs, model)
    if not items:
        items = [dict(it) for it in _PARSE_SEED]
    return {"items": items, "model": model or "default", "files": parsed}


@router.post("/requirements/ai-test")
async def ai_test(body: AiParseReq, db: SyncDB = Depends(get_db)):
    """模型连通性测试（统一 AI 服务；无 Key 时返回 mock 文本仍 ok=True）。"""
    await _ensure_schema(db)
    model = (body.model or "").strip()
    try:
        reply = await ai_service.simple(
            db,
            "请用一句简短中文确认模型 %s 连通正常，回复「连接正常」即可。"
            % (model or "默认"),
            module="需求解析",
            model=model or None,
        )
        ok = True
    except Exception as exc:
        reply, ok = str(exc), False
    return {"ok": ok, "model": model or "default", "reply": str(reply)[:300]}


@router.post("/requirements/{rid}/parse")
async def parse_requirement(
    rid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    row = await _load(db, rid)
    if row["status"] == S_ARCHIVED:
        raise HTTPException(status_code=400, detail="archived")
    items = None
    try:
        data = await ai_service.chat_json(
            db,
            [
                {
                    "role": "system",
                    "content": '你是需求分析师。只输出 JSON：{"count": 需求条目数（整数）, "summary": "一句话摘要"}',
                },
                {
                    "role": "user",
                    "content": "需求标题：%s\n描述：%s\n请给出解析出的需求条目数。"
                    % (row.get("title", ""), (row.get("descr") or "")[:1500]),
                },
            ],
            module="需求解析",
        )
        if isinstance(data, dict):
            try:
                c = int(str(data.get("count")))
            except (TypeError, ValueError):
                c = 0
            if 1 <= c <= 30:
                items = c
    except Exception:
        items = None
    if not items:
        # 降级：沿用原有演示公式
        items = 4 + (len(row.get("title", "")) % 4)
    await db_update(
        db, "rm_requirements", {"status": S_PARSED, "items": items}, "id=?", [rid]
    )
    return _row(await _load(db, rid))


@router.post("/requirements/{rid}/archive")
async def archive_requirement(
    rid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    await _load(db, rid)
    await db_update(db, "rm_requirements", {"status": S_ARCHIVED}, "id=?", [rid])
    return _row(await _load(db, rid))


@router.post("/requirements/{rid}/derive")
async def derive_requirement(
    rid: str,
    body: DeriveReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    row = await _load(db, rid)
    defaults = {"case": ("cases", 6), "perf": ("perf", 1), "sec": ("sec", 2)}
    if body.type not in defaults:
        raise HTTPException(status_code=400, detail="bad type")
    col, default_add = defaults[body.type]
    labels = {"case": "测试用例", "perf": "压测场景", "sec": "安全测试项"}
    add = None
    try:
        data = await ai_service.chat_json(
            db,
            [
                {
                    "role": "system",
                    "content": '你是测试设计专家。只输出 JSON：{"count": 建议派生数量（1~20 的整数）}',
                },
                {
                    "role": "user",
                    "content": "需求：%s\n描述：%s\n请给出本次应派生的%s数量。"
                    % (
                        row.get("title", ""),
                        (row.get("descr") or "")[:1200],
                        labels[body.type],
                    ),
                },
            ],
            module="需求解析",
        )
        if isinstance(data, dict):
            try:
                c = int(str(data.get("count")))
            except (TypeError, ValueError):
                c = 0
            if 1 <= c <= 20:
                add = c
    except Exception:
        add = None
    if add is None:
        add = default_add  # 降级：沿用原演示派生数量
    data = {col: (row.get(col) or 0) + add}
    st = row.get("status", S_PARSE)
    if st == S_PARSE:
        data["status"] = S_PARSED
    elif st == S_PARSED:
        data["status"] = S_DERIVED
    await db_update(db, "rm_requirements", data, "id=?", [rid])
    return _row(await _load(db, rid))
