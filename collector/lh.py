"""LH 분양임대공고문 조회 서비스 (공공데이터포털, apis.data.go.kr/B552555). 서울(지역코드 11)만.

같은 서비스키를 쓰지만 공공데이터포털에서 이 서비스도 따로 활용신청해야 한다.
신청하지 않았으면 오류 로그만 남기고 건너뛴다.
"""
from __future__ import annotations

from datetime import timedelta

from .common import SPECIAL, SourceError, clean, get, redact, gu_in_text, is_seoul, kst_today, log, special_kind, to_int, to_iso

URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
LOOKBACK_DAYS = 90
PER_PAGE = 100
# 상위 유형: 05 분양주택, 06 임대주택, 39 신혼희망타운, 13 주거복지
TYPES = {"05": "분양", "06": "임대", "39": "분양", "13": "임대"}


def _ds(body, key: str) -> list[dict]:
    for block in body if isinstance(body, list) else []:
        if isinstance(block, dict) and key in block:
            return block[key] or []
    return []


def _check(body) -> None:
    if isinstance(body, dict):  # 키 오류는 공공데이터포털 공통 형식으로 온다
        raise SourceError(redact(f"LH API 오류: {str(body)[:200]}"))
    for hdr in _ds(body, "resHeader"):
        if hdr.get("SS_CODE") and hdr.get("SS_CODE") != "Y":
            raise RuntimeError(f"LH API 오류 {hdr.get('SS_CODE')}: {hdr.get('SS_MSG', '')}")


def normalize(row: dict, cat: str) -> dict:
    kind = clean(row.get("AIS_TP_CD_NM")) or clean(row.get("UPP_AIS_TP_NM")) or "LH"
    if "신혼희망" in kind or "분양" in kind:
        cat = "분양"
    special = special_kind(kind, clean(row.get("PAN_NM")))
    if special:
        kind, cat = special, SPECIAL
    status = clean(row.get("PAN_SS"))
    name = clean(row.get("PAN_NM"))
    return {
        "id": f"lh:{row.get('PAN_ID')}",
        "source": "LH",
        "cat": cat,
        "kind": kind,
        "name": name,
        "address": None,
        "gu": gu_in_text(name),
        "units": to_int(row.get("ALL_CNT")) or None,
        "dates": {k: v for k, v in {
            "notice": to_iso(row.get("PAN_NT_ST_DT")),
            "end": to_iso(row.get("CLSG_DT")),
        }.items() if v},
        "dateBasis": "api",
        "statusHint": status,
        "moveIn": None,
        "models": [],
        "priceMin": None,
        "priceMax": None,
        "tags": [],
        "targets": [],
        "builder": None,
        "supplier": "LH",
        "tel": None,
        "url": clean(row.get("DTL_URL")),
        "homepage": None,
    }


def collect(session, key: str | None) -> tuple[list[dict], list[str]]:
    if not key:
        raise SourceError("DATA_GO_KR_KEY 가 없어 LH를 건너뜁니다")
    today = kst_today()
    st = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y.%m.%d")
    ed = (today + timedelta(days=180)).strftime("%Y.%m.%d")
    out: dict[str, dict] = {}
    failed: list[str] = []
    for code, cat in TYPES.items():
        try:
            for page in range(1, 6):
                resp = get(session, URL, params={
                    "serviceKey": key, "PG_SZ": PER_PAGE, "PAGE": page,
                    "PAN_NT_ST_DT": st, "CLSG_DT": ed, "UPP_AIS_TP_CD": code, "CNP_CD": "11",
                })
                try:
                    body = resp.json()
                except ValueError:
                    raise SourceError(redact(f"LH API 응답이 JSON이 아님 (HTTP {resp.status_code}): {resp.text[:150]}"))
                _check(body)
                rows = _ds(body, "dsList")
                for row in rows:
                    if row.get("CNP_CD_NM") and not is_seoul(row.get("CNP_CD_NM")):
                        continue
                    item = normalize(row, cat)
                    if item["name"]:
                        out[item["id"]] = item
                if len(rows) < PER_PAGE:
                    break
        except SourceError:
            raise
        except Exception as e:
            log.error("LH 유형 %s 실패: %s", code, e)
            failed.append(code)
    if len(failed) == len(TYPES):
        raise SourceError("LH API를 하나도 읽지 못했습니다")
    log.info("LH: 서울 %d건", len(out))
    return list(out.values()), failed
