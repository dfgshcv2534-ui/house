"""SH 서울주택도시개발공사 공고 게시판 (www.i-sh.co.kr, 공개 HTML).

공식 API가 없어 게시판 목록을 읽고, 모집공고로 보이는 글만 상세 본문을 열어
접수기간·당첨자 발표·입주 시기를 최대한 뽑아낸다. 본문에 일정이 없으면 공고문 링크만 남긴다.
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

from bs4 import BeautifulSoup

from .common import SPECIAL, SourceError, clean, get, gu_in_text, kst_today, log, special_kind, to_iso

BASE = "https://www.i-sh.co.kr"
PREFIXES = ["/app", "/main"]  # 같은 게시판이 두 경로로 열린다. 앞의 것이 실패하면 뒤의 것으로
LOOKBACK_DAYS = 60
MAX_PAGES = 8  # 게시판은 한 페이지 10건 고정

BOARDS = [
    {"key": "sale", "name": "주택분양", "path": "/lay2/program/S1T294C296/www/brd/m_244", "seq": "1", "cat": "분양"},
    {"key": "rent", "name": "주택임대", "path": "/lay2/program/S1T294C297/www/brd/m_247", "seq": "2", "cat": "임대"},
    {"key": "purchase", "name": "주택매입", "path": "/lay2/program/S1T294C3379/www/brd/m_247", "seq": "512", "cat": "임대"},
]

# 모집공고가 아닌 글 (결과·발표·안내)
EXCLUDE = re.compile(
    r"당첨자|당첨\s*결과|발표|계약\s*결과|결과\s*(?:알림|안내|공고)|서류\s*(?:심사|제출)\s*대상|순번|명단|동\s*·?\s*호|"
    r"추첨\s*결과|합격|선정\s*결과|입주\s*안내|하자|설명회|사전\s*점검|추가\s*서류|개인정보|만족도|채용|입찰|용역|"
    r"(?:접수|청약|신청)\s*(?:현황|결과)|결과\s*$|경쟁률|분양\s*전환\s*(?:신청\s*)?(?:안내|가격|대상|감정)"
)
INCLUDE = re.compile(r"모집|공급|청약|분양|공고")

# (정규식, 유형 이름, 분류) — 위에서부터 먼저 맞는 것
KIND_RULES = [
    (r"사회주택", "사회주택", "임대"),
    (r"행복주택", "행복주택", "임대"),
    (r"미리내집|장기전세", "장기전세(미리내집)", "임대"),
    (r"청년\s*안심주택", "청년안심주택", "임대"),
    (r"신혼희망타운", "신혼희망타운", "분양"),
    (r"국민임대", "국민임대", "임대"),
    (r"영구임대", "영구임대", "임대"),
    (r"재개발\s*임대", "재개발임대", "임대"),
    (r"전세\s*임대", "전세임대", "임대"),
    (r"매입\s*임대|매입형|청년\s*매입|신혼.*매입|다가구|기존주택", "매입임대", "임대"),
    (r"공공\s*임대|임대주택|임대", "공공임대", "임대"),
    (r"공공\s*분양|분양", "공공분양", "분양"),
]

TARGET_RULES = [
    (r"청년", "청년"), (r"대학생", "대학생"), (r"신혼|예비\s*신혼|신생아", "신혼·신생아"),
    (r"고령자|어르신|65세", "고령자"), (r"다자녀", "다자녀"), (r"한부모", "한부모"),
    (r"장애인", "장애인"), (r"예술인|연극인", "예술인"), (r"창업", "창업인"),
]


def classify(title: str, board_cat: str) -> tuple[str, str]:
    if not re.search(r"사회주택", title) and (kind := special_kind(title)):
        return kind, SPECIAL
    for pattern, kind, cat in KIND_RULES:
        if re.search(pattern, title):
            return kind, cat
    return ("공공분양" if board_cat == "분양" else "공공임대"), board_cat


def targets_of(title: str) -> list[str]:
    return [label for pattern, label in TARGET_RULES if re.search(pattern, title)]


def is_recruitment(title: str) -> bool:
    return bool(INCLUDE.search(title)) and not EXCLUDE.search(title)


def parse_list(html: str) -> list[dict]:
    """게시판 목록 HTML → [{seq, title, dept, date}]."""
    soup = BeautifulSoup(html, "html.parser")
    area = soup.select_one("#listTb tbody") or soup.select_one("tbody")
    if area is None:
        return []
    rows = []
    for tr in area.find_all("tr"):
        link = tr.find("a", onclick=re.compile(r"getDetailView"))
        if link is None:
            continue
        seq = re.search(r"getDetailView\(\s*['\"]?(\d+)", link["onclick"])
        tds = tr.find_all("td")
        if not seq or len(tds) < 4:
            continue
        for new in link.select(".icoNew"):
            new.decompose()
        title = clean(re.sub(r"^NEW\s*", "", link.get_text(" ")))
        rows.append({
            "seq": seq.group(1),
            "title": title,
            "dept": clean(tds[2].get_text(" ")),
            "date": to_iso(tds[3].get_text()),
        })
    return rows


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    cont = soup.select_one("td.cont")
    text = clean(cont.get_text(" ")) if cont else ""
    files = []
    for a in soup.select("a.btnAttach"):
        name = clean(a.get_text(" "))
        if name and not re.fullmatch(r"\.\w{2,5}", name) and "existFile" in (a.get("onclick") or ""):
            files.append(name)
    return {"text": text or "", "files": files}


# ---- 본문에서 일정 뽑기 ----------------------------------------------------

_FULL = r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?"
_PART = r"(?:(20\d{2})\s*[.\-/년]\s*)?(?:(\d{1,2})\s*[.\-/월]\s*)?(\d{1,2})\s*일?"
RANGE_RE = re.compile(_FULL + r"\s*\.?\s*[~∼～\-–]\s*" + _PART)
FULL_RE = re.compile(_FULL)
MONTH_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*월?")

APPLY_KEY = re.compile(r"(?:청약|인터넷|온라인|방문)?\s*(?:접수|신청)(?!\s*자격)(?!\s*방법)(?:\s*(?:기간|일정|일시|기한))?")
WINNER_KEY = re.compile(r"당첨자\s*(?:발표|공고)|입주\s*대상자\s*발표|발표\s*일")
MOVEIN_KEY = re.compile(r"입주\s*(?:예정|시기|가능)")


def _simplify(text: str) -> str:
    text = re.sub(r"\(\s*[월화수목금토일]\s*\)", " ", text)
    text = re.sub(r"\d{1,2}\s*:\s*\d{2}", " ", text)
    return re.sub(r"\s+", " ", text)


def _mk(y, m, d) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def _range_after(text: str, pos: int, window: int = 90) -> tuple[date | None, date | None]:
    chunk = text[pos:pos + window]
    rm = RANGE_RE.search(chunk)
    fm = FULL_RE.search(chunk)
    if rm and (not fm or rm.start() <= fm.start()):
        y, m, d, y2, m2, d2 = rm.groups()
        start = _mk(y, m, d)
        end = _mk(y2 or y, m2 or m, d2)
        if start and end and end < start and not m2:  # '10.30 ~ 3' 처럼 달이 넘어간 경우
            end = _mk(int(y) + (int(m) == 12), int(m) % 12 + 1, d2)
        return start, end
    if fm:
        d = _mk(*fm.groups())
        return d, d
    return None, None


def extract_schedule(text: str, notice: str | None) -> dict:
    """본문에서 접수 시작·마감, 당첨자 발표, 입주 시기를 찾는다. 못 찾으면 빈 dict."""
    if not text:
        return {}
    text = _simplify(text)
    base = date.fromisoformat(notice) if notice else None
    out: dict = {}
    for want_range in (True, False):
        for m in APPLY_KEY.finditer(text):
            start, end = _range_after(text, m.end())
            if not start or (want_range and end == start):
                continue
            if base and not (base - timedelta(days=14) <= start <= base + timedelta(days=180)):
                continue
            if end and end < start:
                continue
            out["start"], out["end"] = start.isoformat(), (end or start).isoformat()
            break
        if "start" in out:
            break
    for m in WINNER_KEY.finditer(text):
        fm = FULL_RE.search(text[m.end():m.end() + 60])
        d = _mk(*fm.groups()) if fm else None
        if d and (not out.get("start") or d.isoformat() >= out["start"]):
            out["winner"] = d.isoformat()
            break
    for m in MOVEIN_KEY.finditer(text):
        mm = MONTH_RE.search(text[m.end():m.end() + 40])
        if mm and 1 <= int(mm.group(2)) <= 12:
            out["moveIn"] = f"{mm.group(1)}-{int(mm.group(2)):02d}"
            break
    return out


def units_of(text: str) -> int | None:
    m = re.search(r"(?:총|공급\s*(?:호수|세대수|규모)?|모집\s*(?:호수|세대)?)\s*:?\s*([\d,]{1,6})\s*(?:호|세대|가구)", text or "")
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    return n if 0 < n < 100000 else None


# ---- 수집 -----------------------------------------------------------------

def _board_url(prefix: str, board: dict, page_kind: str) -> str:
    return f"{BASE}{prefix}{board['path']}/{page_kind}.do"


def _fetch_board(session, board: dict, since: str) -> tuple[str, list[dict]]:
    last_error = None
    for prefix in PREFIXES:
        try:
            items: list[dict] = []
            for page in range(1, MAX_PAGES + 1):
                resp = get(session, _board_url(prefix, board, "list"), params={"multi_itm_seq": board["seq"], "page": page})
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                rows = parse_list(resp.text)
                if not rows:
                    if page == 1:
                        raise RuntimeError("목록 표를 찾지 못함 (사이트 구조 변경 또는 차단)")
                    break
                items.extend(rows)
                if all((r["date"] or "9999") < since for r in rows):
                    break
                time.sleep(0.5)
            return prefix, [r for r in items if (r["date"] or "9999") >= since]
        except Exception as e:
            last_error = e
            log.warning("SH %s (%s) 실패: %s", board["name"], prefix, e)
    raise RuntimeError(f"SH {board['name']} 게시판 읽기 실패: {last_error}")


def to_notice(row: dict, board: dict, detail: dict | None, url: str) -> dict:
    title = row["title"]
    kind, cat = classify(title, board["cat"])
    text = (detail or {}).get("text", "")
    sched = extract_schedule(text, row["date"])
    dates = {"notice": row["date"]}
    dates.update({k: v for k, v in sched.items() if k in ("start", "end", "winner")})
    name = re.sub(r"\s*\(\s*(?:\d{4}|\d{2})\s*[.\-]\s*\d{1,2}\s*[.\-]\s*\d{1,2}\s*\.?\s*(?:공고)?\s*\)\s*$", "", title)
    return {
        "id": f"sh:{board['key']}:{row['seq']}",
        "source": "SH",
        "cat": cat,
        "kind": kind,
        "name": name,
        "address": None,
        "gu": gu_in_text(title) or gu_in_text(text[:400]),
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
        "supplier": "SH공사" + (f" {row['dept']}" if row.get("dept") else ""),
        "tel": None,
        "url": url,
        "homepage": None,
        "files": (detail or {}).get("files", []),
    }


def collect(session) -> tuple[list[dict], list[str]]:
    since = (kst_today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    out: list[dict] = []
    failed: list[str] = []
    for board in BOARDS:
        try:
            prefix, rows = _fetch_board(session, board, since)
        except Exception as e:
            log.error("%s", e)
            failed.append(board["key"])
            continue
        picked = [r for r in rows if is_recruitment(r["title"])]
        log.info("SH %s: 최근 %d건 중 모집공고 %d건", board["name"], len(rows), len(picked))
        for row in picked:
            url = f"{_board_url(prefix, board, 'view')}?multi_itm_seq={board['seq']}&seq={row['seq']}"
            detail = None
            try:
                resp = get(session, url)
                if resp.status_code == 200:
                    detail = parse_detail(resp.text)
            except Exception as e:
                log.warning("SH 상세 실패(%s): %s", row["seq"], e)
            out.append(to_notice(row, board, detail, url))
            time.sleep(0.5)
    if len(failed) == len(BOARDS):
        raise SourceError("SH 게시판을 하나도 읽지 못했습니다")
    return drop_reposts(out), failed


def drop_reposts(items: list[dict]) -> list[dict]:
    """같은 제목으로 다시 올린 공고는 가장 최근 글만 남긴다 (게시판은 최신순)."""
    seen: set[str] = set()
    out = []
    for item in sorted(items, key=lambda i: i["dates"].get("notice") or "", reverse=True):
        key = re.sub(r"\W", "", re.sub(r"^\(\s*(?:수정|정정)\s*\)", "", item["name"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
