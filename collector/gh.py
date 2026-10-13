"""GH 경기주택도시공사 주택청약·임대센터 (apply.gh.or.kr) 임대 공고 목록.

API가 없어 공개 목록 페이지를 읽는다. 목록 표에 유형·시군·공고일·접수 마감일·상태가 다 있어서
상세 페이지는 열지 않는다. (분양은 청약홈으로 접수해서 청약홈 쪽에서 들어온다)
"""
from __future__ import annotations

import re
import time
from datetime import timedelta

from bs4 import BeautifulSoup

from .common import (
    GYEONGGI, SPECIAL, SourceError, clean, drop_reposts, get, is_recruitment_title, kst_today, log, special_kind, to_iso,
)
from .sh import EXCLUDE, classify, targets_of

BASE = "https://apply.gh.or.kr"
BOARDS = [
    {"key": "rent", "name": "임대주택", "path": "/sb/sr/sr7150"},
    {"key": "buy", "name": "매입임대", "path": "/sb/sr/sr7155"},
]
LOOKBACK_DAYS = 120
MAX_PAGES = 6


def parse_list(html: str) -> list[dict]:
    """목록 표 → [{no, kind, title, place, notice, end, state}]. 셀: 번호·유형·제목·지역·첨부·공고일·마감일·상태…"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("tbody tr"):
        a = tr.find("a", attrs={"data-pbancno": True})
        if a is None:
            continue
        tds = [clean(td.get_text(" ")) or "" for td in tr.find_all("td", recursive=False)]
        texts = [clean(t) for t in tr.stripped_strings]
        dates = [d for d in (to_iso(t) for t in texts) if d]
        state = next((t for t in texts if re.search(r"접수\s*(?:중|마감|예정)|공고중|모집중|마감", t or "")), None)
        out.append({
            "no": a["data-pbancno"],
            "kind": clean(tds[1]) if len(tds) > 1 else None,
            "title": clean(a.get_text(" ")),
            "place": next((t for t in texts if t in GYEONGGI or t == "경기도"), None),
            "notice": dates[0] if dates else None,
            "end": dates[1] if len(dates) > 1 else None,
            "state": state,
        })
    return out


def to_notice(row: dict, board: dict) -> dict:
    title = row["title"]
    kind = row.get("kind") or ""
    cat = "임대"
    special = special_kind(kind, title)
    if special:
        kind, cat = special, SPECIAL
    elif not kind:
        kind, cat = classify(title, "임대")
    dates = {k: v for k, v in {"notice": row.get("notice"), "end": row.get("end")}.items() if v}
    if kind == "장기전세(미리내집)" and "미리내집" not in title:
        kind = "장기전세"  # 미리내집은 서울(SH) 브랜드
    return {
        "id": f"gh:{board['key']}:{row['no']}",
        "source": "GH",
        "sector": "공공",
        "region": "경기",
        "cat": cat,
        "kind": kind,
        "name": title,
        "address": None,
        "gu": row["place"] if row.get("place") in GYEONGGI else None,
        "units": None,
        "dates": dates,
        "dateBasis": "api",
        "statusHint": row.get("state"),
        "moveIn": None,
        "models": [],
        "priceMin": None,
        "priceMax": None,
        "tags": ["정정공고"] if re.search(r"정정|변경", title) else [],
        "targets": targets_of(title),
        "builder": None,
        "supplier": "GH",
        "tel": None,
        "url": f"{BASE}{board['path']}/selectPbancDetailView.do?pbancNo={row['no']}",
        "homepage": None,
    }


def collect(session) -> tuple[list[dict], list[str]]:
    since = (kst_today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    out, failed = [], []
    for board in BOARDS:
        try:
            rows = []
            for page in range(1, MAX_PAGES + 1):
                resp = get(session, f"{BASE}{board['path']}/selectPbancRentHouseList.do", params={"pageIndex": page})
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                page_rows = parse_list(resp.text)
                if not page_rows:
                    if page == 1:
                        raise RuntimeError("목록 표를 찾지 못함 (사이트 구조 변경 또는 차단)")
                    break
                new = [r for r in page_rows if r["no"] not in {x["no"] for x in rows}]
                rows.extend(new)
                if not new or all((r["notice"] or "9999") < since for r in page_rows):
                    break
                time.sleep(0.5)
        except Exception as e:
            log.error("GH %s 실패: %s", board["name"], e)
            failed.append(board["key"])
            continue
        recent = [r for r in rows if (r["notice"] or "9999") >= since]
        picked = [r for r in recent if is_recruitment_title(r["title"]) and not EXCLUDE.search(r["title"])]
        log.info("GH %s: 최근 %d건 중 모집공고 %d건", board["name"], len(recent), len(picked))
        out.extend(to_notice(r, board) for r in picked)
    if len(failed) == len(BOARDS):
        raise SourceError("GH 게시판을 하나도 읽지 못했습니다")
    return drop_reposts(out), failed
