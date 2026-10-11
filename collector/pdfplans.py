"""청약홈 모집공고문 PDF 안의 평면도 페이지를 이미지로 잘라 보여주기.

대부분의 공고문에는 평면도가 없고 '평면도는 견본주택 참조' 같은 문장만 있다.
그래서 '평면'이라는 말이 있으면서 실제 그림(이미지 또는 아주 많은 선)이 있는 페이지만 고른다.
같은 PDF는 한 번만 확인하도록 docs/plans/index.json 에 결과를 남긴다.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from .common import get, kst_today, log

PLAN_WORD = re.compile(r"평\s*면\s*도|단위\s*세대|평면\s*형태|세대\s*평면")
MIN_DRAWINGS = 800      # 벡터로 그린 평면도는 선·면이 수천 개
MAX_TEXT = 2500         # 글자가 너무 많은 페이지는 안내문
MAX_PAGES = 6           # 공고 하나에서 자를 최대 페이지 수
DPI = 110


def _safe(id_: str) -> str:
    return re.sub(r"[^\w-]", "_", id_)


def candidate_pages(doc) -> list[int]:
    """평면도로 보이는 페이지 번호(0부터)."""
    out = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if not PLAN_WORD.search(text) or len(text) > MAX_TEXT:
            continue
        if page.get_images() or len(page.get_drawings()) >= MIN_DRAWINGS:
            out.append(i)
    return out[:MAX_PAGES]


def types_on_page(text: str, models: list[dict]) -> list[str]:
    """페이지 글자에 나오는 주택형(84A, 59 등)."""
    found = []
    for m in models:
        t = m.get("type") or ""
        mt = re.match(r"(\d+)([A-Za-z]?)", t)
        if not mt:
            continue
        num, letter = mt.group(1), mt.group(2)
        pat = rf"(?<!\d)0*{num}(?:\.\d+)?\s*{letter}(?![A-Za-z])" if letter else rf"(?<!\d)0*{num}(?:\.\d+)?\s*(?:㎡|m2|형|타입|TYPE)"
        if re.search(pat, text, re.I):
            found.append(t)
    return found


def _pdf_url(item: dict) -> str | None:
    for f in item.get("files") or []:
        if isinstance(f, dict) and str(f.get("url", "")).startswith("http"):
            return f["url"]
    return None


def attach(session, notices: list[dict], docs_dir: Path) -> None:
    try:
        import pymupdf
    except ImportError:
        log.warning("pymupdf 가 없어 공고문 평면도 자르기를 건너뜁니다")
        return
    plans_dir = docs_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    index_path = plans_dir / "index.json"
    try:
        index: dict = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}

    recent = (kst_today() - timedelta(days=30)).isoformat()
    keep_ids = set()
    for item in notices:
        url = _pdf_url(item)
        if item.get("source") != "청약홈" or not url:
            continue
        keep_ids.add(item["id"])
        entry = index.get(item["id"])
        if (not entry or entry.get("pdf") != url) and max(item.get("dates", {}).values(), default="") >= recent:
            entry = _scan(session, pymupdf, url, item, plans_dir)
            if entry is None:
                continue
            index[item["id"]] = entry
        if not entry or not entry.get("pages"):
            continue
        item["planPages"] = entry["pages"]
        for m in item.get("models", []):
            page = next((p for p in entry["pages"] if m.get("type") in p.get("types", [])), None)
            if page:
                m["plan"] = page["url"]

    # 목록에서 사라진 공고의 이미지는 지운다 (레포가 계속 커지지 않게)
    for id_ in [k for k in index if k not in keep_ids]:
        for p in index.pop(id_).get("pages", []):
            (docs_dir / p["url"]).unlink(missing_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def _scan(session, pymupdf, url: str, item: dict, plans_dir: Path) -> dict | None:
    try:
        resp = get(session, url, attempts=2, timeout=40)
        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            return {"pdf": url, "pages": []}
        doc = pymupdf.open(stream=resp.content, filetype="pdf")
    except Exception as e:
        log.warning("공고문 PDF 열기 실패(%s): %s", item.get("name"), e)
        return None
    pages = []
    for i in candidate_pages(doc):
        page = doc[i]
        name = f"{_safe(item['id'])}-p{i + 1}.jpg"
        page.get_pixmap(dpi=DPI).save(str(plans_dir / name), jpg_quality=72)
        pages.append({"page": i + 1, "url": f"plans/{name}", "types": types_on_page(page.get_text(), item.get("models", []))})
    log.info("공고문 평면도: %s → %d쪽 %s", item.get("name"), len(pages), [p["page"] for p in pages])
    return {"pdf": url, "pages": pages}
