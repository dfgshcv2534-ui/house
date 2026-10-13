"""iH 인천도시공사 (www.ih.co.kr) 분양·임대 입주자모집공고 게시판.

API가 없어 공개 게시판을 읽는다. 모집공고로 보이는 글만 상세를 열어 본문에서 일정·주소를 뽑는다(SH와 같은 방식).
"""
from __future__ import annotations

import re
import time
from datetime import timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import (
    INCHEON, SPECIAL, SourceError, clean, drop_reposts, get, is_recruitment_title, kst_today, log, place_in_text,
    sigungu, special_kind, to_iso,
)
from .sh import EXCLUDE, classify, extract_schedule, targets_of, units_of

BASE = "https://www.ih.co.kr"
LIST = f"{BASE}/main/bbs/bbsMsgList.do"
BOARDS = [
    {"key": "sale", "name": "주택분양", "params": {"cate1": "a", "bcd": "sale_lease"}, "cat": "분양", "bcd": "sale_lease"},
    {"key": "rent", "name": "임대", "params": {"cate1": "general", "bcd": "notice", "pgdiv": "general"}, "cat": "임대", "bcd": "notice"},
]
LOOKBACK_DAYS = 120
MAX_PAGES = 8
DATE_RE = re.compile(r"20\d{2}\.\d{1,2}\.\d{1,2}")
ADDRESS_RE = re.compile(r"인천(?:광역시|시)?\s+(\S+[구군])\s+\S+?(?:동|로|길|읍|면)(?:\s*\d+(?:-\d+)?)?")


def parse_list(html: str, bcd: str) -> list[dict]:
    """게시판 목록 → [{seq, title, date, href}]. 메뉴 링크와 섞이지 않게 해당 게시판(bcd)의 글 링크만 본다."""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(rf"bbsMsgDetail\.do\?.*bcd={bcd}")):
        m = re.search(r"msg_seq=(\d+)", a["href"])
        if not m or m.group(1) in seen:
            continue
        row = a.find_parent(["tr", "li"]) or a.parent
        date = DATE_RE.search(row.get_text(" ") if row else "")
        title = clean(a.get_text(" "))
        if not title or not date:
            continue
        seen.add(m.group(1))
        out.append({"seq": m.group(1), "title": title, "date": to_iso(date.group(0)), "href": urljoin(BASE, a["href"])})
    return out


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    view = soup.select_one(".board_view") or soup
    text = clean(view.get_text(" ")) or ""
    files = []
    for a in view.find_all("a", href=re.compile(r"FileDown", re.I)):
        name = clean(a.get_text(" "))
        if name and not re.fullmatch(r"(?:다운로드|미리보기|첨부파일)", name):
            files.append({"name": re.sub(r"\s*\[[\d.,]+\s*[KMG]?Byte\]\s*$", "", name), "url": urljoin(BASE, a["href"])})
    return {"text": text, "files": files}


def single_address(text: str) -> str | None:
    found = list(ADDRESS_RE.finditer(text or ""))
    if not found or len({m.group(1) for m in found}) != 1:
        return None
    return re.sub(r"\s+", " ", found[0].group(0)).strip()


def to_notice(row: dict, board: dict, detail: dict | None) -> dict:
    title = row["title"]
    kind, cat = classify(title, board["cat"])
    special = special_kind(title)
    if special:
        kind, cat = special, SPECIAL
    elif board["cat"] == "분양" and cat == "분양" and kind == "공공분양" and not re.search(r"공공", title):
        kind = "분양"  # iH 분양 게시판에는 민간 참여 단지(푸르지오 등)도 올라온다
    text = (detail or {}).get("text", "")
    sched = extract_schedule(text, row["date"])
    address = single_address(text)
    dates = {"notice": row["date"], **{k: v for k, v in sched.items() if k in ("start", "end", "winner")}}
    gu = sigungu(address) if address else None
    gu = gu if gu in INCHEON else place_in_text(title, "인천")
    return {
        "id": f"ih:{board['key']}:{row['seq']}",
        "source": "iH",
        "sector": "공공",
        "region": "인천",
        "cat": cat,
        "kind": kind,
        "name": title,
        "address": address,
        "gu": gu,
        "units": units_of(title) or units_of(text[:1500]),
        "dates": {k: v for k, v in dates.items() if v},
        "dateBasis": "본문" if sched.get("start") else "없음",
        "moveIn": sched.get("moveIn"),
        "models": [],
        "priceMin": None,
        "priceMax": None,
        "tags": ["정정공고"] if re.search(r"정정|변경", title) else [],
        "targets": targets_of(title),
        "builder": None,
        "supplier": "iH",
        "tel": None,
        "url": row["href"],
        "homepage": None,
        "files": (detail or {}).get("files", []),
    }


def collect(session) -> tuple[list[dict], list[str]]:
    since = (kst_today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    out, failed = [], []
    for board in BOARDS:
        try:
            rows = []
            for page in range(1, MAX_PAGES + 1):
                resp = get(session, LIST, params={**board["params"], "pgno": page})
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                page_rows = parse_list(resp.text, board["bcd"])
                if not page_rows:
                    if page == 1:
                        raise RuntimeError("목록을 찾지 못함 (사이트 구조 변경 또는 차단)")
                    break
                new = [r for r in page_rows if r["seq"] not in {x["seq"] for x in rows}]
                rows.extend(new)
                if not new or all(r["date"] < since for r in page_rows):
                    break
                time.sleep(0.5)
        except Exception as e:
            log.error("iH %s 실패: %s", board["name"], e)
            failed.append(board["key"])
            continue
        recent = [r for r in rows if r["date"] >= since]
        picked = [r for r in recent if is_recruitment_title(r["title"]) and not EXCLUDE.search(r["title"])]
        log.info("iH %s: 최근 %d건 중 모집공고 %d건", board["name"], len(recent), len(picked))
        for row in picked:
            detail = None
            try:
                resp = get(session, row["href"])
                if resp.status_code == 200:
                    detail = parse_detail(resp.text)
            except Exception as e:
                log.warning("iH 상세 실패(%s): %s", row["seq"], e)
            out.append(to_notice(row, board, detail))
            time.sleep(0.5)
    if len(failed) == len(BOARDS):
        raise SourceError("iH 게시판을 하나도 읽지 못했습니다")
    return drop_reposts(out), failed
