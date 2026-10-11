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
    return None
