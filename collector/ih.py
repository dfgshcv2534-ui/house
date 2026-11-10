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
    redact, sigungu, special_kind, to_iso,
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
    if kind == "장기전세(미리내집)" and "미리내집" not in title:
        kind = "장기전세"  # 미리내집은 서울(SH) 브랜드
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


API_URL = "https://apis.data.go.kr/B552831/ih/slls-posts"  # 인천도시공사_분양임대 관련 공고문 조회 서비스 (공공데이터포털)


def _api_body(resp) -> dict:
    """JSON({response:{header,body}} 또는 {header,body}) / XML 둘 다 받아서 body 를 돌려준다."""
    try:
        data = resp.json()
    except ValueError:
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            raise SourceError(redact(f"iH API 응답을 읽지 못함 (HTTP {resp.status_code}): {resp.text[:150]}"))
        code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
        if code and code not in ("00", "0", "200"):
            raise SourceError(redact(f"iH API 오류 {code}: {root.findtext('.//resultMsg') or root.findtext('.//returnAuthMsg')}"))
        posts = [{c.tag: c.text for c in el} for el in root.iter() if el.find("sj") is not None]
        return {"posts": posts, "totalCount": root.findtext(".//totalCount")}
    data = data.get("response", data)
    header = data.get("header") or {}
    if header.get("resultCode") not in (None, "00", "0", "200", 0, 200):
        raise SourceError(redact(f"iH API 오류 {header.get('resultCode')}: {header.get('resultMsg')}"))
    return data.get("body") or {}


def api_rows(posts: list[dict]) -> dict[str, list[dict]]:
    """API 공고 → 게시판과 같은 모양의 행. 링크의 msg_seq 를 써서 게시판에서 받던 공고와 같은 id 가 되게 한다."""
    out = {"sale": [], "rent": []}
    for p in posts:
        title, link = clean(p.get("sj")), clean(p.get("link")) or ""
        date = to_iso(p.get("crtYmd"))
        if not title or not date:
            continue
        m = re.search(r"msg_seq=(\d+)", link)
        seq = m.group(1) if m else f"api{abs(hash((title, date))) % 10**8}"
        key = "sale" if "분양" in (p.get("seNm") or "") else "rent"
        out[key].append({"seq": seq, "title": title, "date": date, "href": urljoin(BASE, link) if link else BASE})
    return out


def _collect_api(session, key: str | None, since: str) -> dict[str, list[dict]]:
    if not key:
        raise SourceError("DATA_GO_KR_KEY 가 없어 iH API를 쓸 수 없습니다")
    posts = []
    for page in range(1, 6):
        resp = get(session, API_URL, params={"serviceKey": key, "pageNo": page, "numOfRows": 50, "type": "json"},
                   attempts=3, timeout=60)
        body = _api_body(resp)
        page_posts = body.get("posts") or body.get("items") or []
        if isinstance(page_posts, dict):
            page_posts = page_posts.get("item") or []
        posts.extend(page_posts)
        if not posts:  # 미신청 키 등은 오류 형식이 제각각이라, 공고가 하나도 없으면 실패로 본다
            raise SourceError(redact(f"iH API에서 공고를 받지 못했습니다 (활용신청 확인). 응답 앞부분: {resp.text[:200]}"))
        if len(page_posts) < 50 or all((to_iso(p.get("crtYmd")) or "9999") < since for p in page_posts):
            break
    return api_rows(posts)


def _board_reachable(session) -> bool:
    try:
        return get(session, LIST, params={**BOARDS[0]["params"], "pgno": 1}, attempts=1, timeout=15).status_code == 200
    except Exception:
        return False


def collect(session, key: str | None = None) -> tuple[list[dict], list[str]]:
    """게시판이 열리면 게시판(상세 본문 포함), 막혀 있으면 공공데이터포털 iH API 목록으로 받는다."""
    since = (kst_today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    if not _board_reachable(session):
        log.warning("iH 홈페이지에 접속되지 않아 공공데이터포털 iH API로 목록을 받습니다")
        by_board = _collect_api(session, key, since)
        out = []
        for board in BOARDS:
            recent = [r for r in by_board[board["key"]] if r["date"] >= since]
            picked = [r for r in recent if is_recruitment_title(r["title"]) and not EXCLUDE.search(r["title"])]
            log.info("iH(API) %s: 최근 %d건 중 모집공고 %d건", board["name"], len(recent), len(picked))
            out.extend(to_notice(r, board, None) for r in picked)
        return drop_reposts(out), []
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
