"""수집기 공통 도구: HTTP 세션, 날짜 처리, 서울 주소 판별."""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

import requests

log = logging.getLogger("collector")

KST = timezone(timedelta(hours=9))
USER_AGENT = "Mozilla/5.0 (compatible; seoul-house-board/1.0; +https://github.com)"


class SourceError(Exception):
    """한 출처 전체를 포기해야 하는 오류 (인증 실패, 차단 등)."""


def kst_now() -> datetime:
    return datetime.now(KST)


def kst_today() -> date:
    return kst_now().date()


def api_key() -> str | None:
    """공공데이터포털 서비스키. 인코딩 키를 넣어도 동작하도록 한 번 디코딩한다."""
    key = (os.environ.get("DATA_GO_KR_KEY") or "").strip()
    if not key:
        return None
    return unquote(key) if "%" in key else key


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
    return s


def redact(text) -> str:
    """로그에 서비스키가 찍히지 않도록 가린다 (공개 레포의 Actions 로그는 누구나 볼 수 있다)."""
    return re.sub(r"(serviceKey=)[^&\s'\")]+", r"\1***", str(text))


def get(session: requests.Session, url: str, *, params=None, attempts: int = 3, timeout: int = 30) -> requests.Response:
    """일시 오류(네트워크, 5xx)는 재시도하고 4xx는 바로 돌려준다."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code < 500:
                return resp
            last = RuntimeError(f"HTTP {resp.status_code}")
        except requests.RequestException as e:
            last = e
        if i < attempts - 1:
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url} 요청 실패: {redact(last)}")


def to_iso(value) -> str | None:
    """'2026-10-01', '20261001', '2026.10.01' → '2026-10-01'. 날짜가 아니면 None."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:
        return None


def to_month(value) -> str | None:
    """'202812' 또는 '2028.12' → '2028-12'."""
    if value is None:
        return None
    m = re.search(r"(20\d{2})\D*(\d{1,2})", str(value))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def to_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = re.sub(r"[,\s]", "", str(value))
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None
    return int(float(text))


def to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def clean(value) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def first(row: dict, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", " "):
            return v
    return None


def is_seoul(*texts) -> bool:
    for t in texts:
        if t and re.match(r"\s*서울", str(t)):
            return True
    return False


def seoul_gu(address: str | None) -> str | None:
    """'서울특별시 강동구 고덕동 …' → '강동구'."""
    if not address:
        return None
    m = re.search(r"서울\S*\s+(\S+?구)(?:\s|$|,)", address)
    return m.group(1) if m else None


SEOUL_GU = [
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구", "노원구",
    "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구", "성북구", "송파구",
    "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
]


def gu_in_text(text: str | None) -> str | None:
    """공고 제목처럼 주소가 아닌 글에서 자치구 이름을 찾는다 ('강동구 고덕' → '강동구')."""
    if not text:
        return None
    for gu in sorted(SEOUL_GU, key=len, reverse=True):
        if gu == "중구":
            if re.search(r"(?<![가-힣])중구", text):
                return gu
        elif gu in text:
            return gu
    # '강서염창', '서울강남'처럼 '구'를 뺀 이름이 단어 앞에 붙은 경우 ('중구'는 '중'이 흔해서 제외)
    for gu in sorted(SEOUL_GU, key=len, reverse=True):
        short = gu[:-1]
        if len(short) >= 2 and re.search(rf"(?:^|[^가-힣]|서울){short}", text):
            return gu
    return None


_REPOST_MARK = re.compile(r"[\[(]\s*(?:정정\s*공고|정정|수정|재공고)\s*[\])]")


def clean_title(title: str | None) -> str | None:
    """'[서울지역본부]', '[정정공고]' 같은 머리말을 뗀 제목."""
    if not title:
        return title
    text = _REPOST_MARK.sub(" ", title)
    text = re.sub(r"^\s*\[[^\]]*(?:지역본부|본부|센터)\]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_correction(title: str | None) -> bool:
    return bool(title and _REPOST_MARK.search(title))


def drop_reposts(items: list[dict]) -> list[dict]:
    """같은 공고를 정정·재게시한 경우 가장 최근 글 하나만 남긴다."""
    seen: set[str] = set()
    out = []
    for item in sorted(items, key=lambda i: i["dates"].get("notice") or "", reverse=True):
        key = re.sub(r"\W", "", clean_title(item["name"]) or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


SPECIAL = "특수형"
# 분양과 임대 사이에 있는 방식: 소유 구조나 전환 조건이 달라 따로 본다. (정규식, 유형 이름)
SPECIAL_RULES = [
    (r"토지\s*임대부(?!\s*사회주택)", "토지임대부 분양"),
    (r"지분\s*적립형", "지분적립형 분양"),
    (r"나눔형|이익\s*공유형", "나눔형(이익공유)"),
    (r"분양\s*전환\s*(?:가능|형)?\s*(?:공공)?\s*임대|분납\s*임대|(?:5|10)\s*년\s*(?:공공)?\s*임대|공공\s*임대\s*\(\s*(?:5|10)\s*년|분양\s*전환\s*가능", "분양전환 임대"),
]


def special_kind(*texts) -> str | None:
    """토지임대부·지분적립형·나눔형·분양전환 임대면 그 유형 이름, 아니면 None."""
    text = " ".join(t for t in texts if t)
    text = re.sub(r"비\s*분양\s*전환\S*|분양\s*전환\s*불가\S*", "", text)
    for pattern, kind in SPECIAL_RULES:
        if re.search(pattern, text):
            return kind
    return None


PUBLIC_SUPPLIER = re.compile(r"주택도시공사|토지주택공사|도시개발공사|도시공사|개발공사|공단|LH|SH|서울특별시|구청")


def sector_of(detail_kind: str | None, supplier: str | None) -> str:
    """공공/민간. 청약홈의 국민/민영 구분을 먼저 보고, 없으면 사업주체 이름으로 판단한다."""
    if detail_kind == "국민":
        return "공공"
    if detail_kind == "민영":
        return "민간"
    return "공공" if supplier and PUBLIC_SUPPLIER.search(supplier) else "민간"


# 입주자 모집공고만 남기기: '모집' 공고여야 하고, 연기·변경 안내·취소·사전공고·보충 글은 뺀다 ([정정]·(수정) 공고는 남김)
RECRUIT = re.compile(r"모집|공급\s*공고|분양\s*공고|청약\s*공고|사전\s*청약")
NOT_RECRUIT = re.compile(
    r"연기|일정\s*(?:변경|조정|안내)|변경\s*(?:안내|알림|공지)|취소|중단|철회|보류|사전\s*공고|사전\s*안내|"
    r"(?:정보|서류|내용)\s*추가|추가\s*(?:안내|공지)|안내\s*$|안내문|알림\s*$|공지\s*$|Q\s*&\s*A|FAQ|질의|응답"
)


def is_recruitment_title(title: str | None) -> bool:
    return bool(title) and bool(RECRUIT.search(title)) and not NOT_RECRUIT.search(title)


# ---- 수도권(서울·경기·인천) 지역·시군구 -----------------------------------------

REGIONS = ("서울", "경기", "인천")
REGION_FULL = {"서울": "서울특별시", "경기": "경기도", "인천": "인천광역시"}
GYEONGGI = [
    "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시", "평택시", "동두천시", "안산시", "고양시", "과천시",
    "구리시", "남양주시", "오산시", "시흥시", "군포시", "의왕시", "하남시", "용인시", "파주시", "이천시", "안성시",
    "김포시", "화성시", "광주시", "양주시", "포천시", "여주시", "연천군", "가평군", "양평군",
]
INCHEON = ["중구", "동구", "미추홀구", "연수구", "남동구", "부평구", "계양구", "서구", "강화군", "옹진군"]


def region_of(*texts) -> str | None:
    """'서울특별시 …', '경기', '인천광역시' 같은 글에서 수도권 지역 이름. 수도권이 아니면 None."""
    for t in texts:
        if not t:
            continue
        m = re.match(r"\s*(서울|경기|인천)", str(t))
        if m:
            return m.group(1)
    return None


def sigungu(address: str | None) -> str | None:
    """주소의 시·군·구: 서울·인천은 '강동구'·'연수구', 경기는 '성남시'·'가평군'."""
    if not address:
        return None
    m = re.search(r"(?:서울|경기|인천)\S*\s+(\S+?[시군구])(?:\s|$|,|\()", address)
    return m.group(1) if m else None


def place_in_text(text: str | None, region: str | None) -> str | None:
    """공고 제목 같은 글에서 시·군·구 찾기 ('남양주왕숙' → '남양주시', '고덕강일' 없음)."""
    if not text:
        return None
    if region in (None, "서울"):
        found = gu_in_text(text)
        if found or region == "서울":
            return found
    names = GYEONGGI if region == "경기" else INCHEON if region == "인천" else GYEONGGI + INCHEON
    for name in sorted(names, key=len, reverse=True):
        if len(name) > 2 and name in text:
            return name
    for name in sorted(names, key=len, reverse=True):
        short = name[:-1]
        if len(short) >= 2 and short != "광주" and re.search(rf"(?:^|[^가-힣]|경기|인천){short}", text):
            return name
    return None
