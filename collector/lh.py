"""LH 분양임대공고 (공공데이터포털, apis.data.go.kr/B552555). 서울(지역코드 11)만.

공공데이터포털 서비스키 하나로 아래 서비스를 모두 쓴다. 다만 서비스마다 따로 활용신청해야 하고,
신청하지 않은 서비스는 '등록되지 않은 서비스키' 오류가 나서 그 부분만 건너뛴다.

- 분양임대공고문 조회            → 공고 목록 (공고명·유형·게시일·마감일·상세 URL)
- 분양임대공고별 상세정보 조회     → 공고마다 주소·접수/발표/계약 일정·입주 예정·세대수·첨부
- 위 두 서비스의 '(사전청약)' 버전 → 사전청약 공고. 요청주소를 아래 PRE_* 에 넣으면 켜진다.
"""
from __future__ import annotations

import re
from datetime import timedelta

from .common import (
    SPECIAL, SourceError, clean, get, gu_in_text, is_seoul, kst_today, log, redact, seoul_gu,
    special_kind, to_int, to_iso, to_month,
)

LIST_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
DTL_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"

# 사전청약 서비스 자리: 활용신청 승인 후 공공데이터포털 상세 페이지의 '요청주소(End Point)' 뒤에
# 오퍼레이션 이름까지 붙인 전체 주소를 넣는다. 비어 있으면 사전청약은 건너뛴다.
PRE_LIST_URL = ""
PRE_DTL_URL = ""

LOOKBACK_DAYS = 90
PER_PAGE = 100
# 상위 유형: 05 분양주택, 06 임대주택, 39 신혼희망타운, 13 주거복지
TYPES = {"05": "분양", "06": "임대", "39": "분양", "13": "임대"}
DETAIL_PARAMS = ("CCR_CNNT_SYS_DS_CD", "SPL_INF_TP_CD", "UPP_AIS_TP_CD", "AIS_TP_CD")
DATE_RE = re.compile(r"20\d{2}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}|20\d{6}")


def _ds(body, key: str) -> list[dict]:
    for block in body if isinstance(body, list) else []:
        if isinstance(block, dict) and key in block:
            return block[key] or []
    return []


def _json(resp, what: str):
    try:
        body = resp.json()
    except ValueError:
        raise SourceError(redact(f"{what} 응답이 JSON이 아님 (HTTP {resp.status_code}): {resp.text[:150]}"))
    if isinstance(body, dict):  # 키 미등록 등은 공공데이터포털 공통 오류 형식(dict)으로 온다
        raise SourceError(redact(f"{what} 오류: {str(body)[:200]}"))
    for hdr in _ds(body, "resHeader"):
        if hdr.get("SS_CODE") and hdr.get("SS_CODE") != "Y":
            raise RuntimeError(f"{what} 오류 {hdr.get('SS_CODE')}: {hdr.get('SS_MSG', '')}")
    return body


def normalize(row: dict, cat: str, *, pre: bool = False) -> dict:
    kind = clean(row.get("AIS_TP_CD_NM")) or clean(row.get("UPP_AIS_TP_NM")) or "LH"
    if "신혼희망" in kind or "분양" in kind:
        cat = "분양"
    special = special_kind(kind, clean(row.get("PAN_NM")))
    if special:
        kind, cat = special, SPECIAL
    name = clean(row.get("PAN_NM"))
    return {
        "id": f"{'lhp' if pre else 'lh'}:{row.get('PAN_ID')}",
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
        "statusHint": clean(row.get("PAN_SS")),
        "moveIn": None,
        "models": [],
        "priceMin": None,
        "priceMax": None,
        "tags": ["사전청약"] if pre else [],
        "targets": [],
        "builder": None,
        "supplier": "LH",
        "tel": None,
        "url": clean(row.get("DTL_URL")),
        "homepage": None,
    }


def _dates_in(text) -> list[str]:
    return [d for d in (to_iso(m) for m in DATE_RE.findall(str(text or ""))) if d]


def apply_detail(item: dict, body) -> None:
    """상세정보 응답으로 주소·일정·입주 예정·세대수·첨부를 채운다."""
    sbd = (_ds(body, "dsSbd") or [{}])[0]
    address = " ".join(x for x in (clean(sbd.get("LCT_ARA_ADR")), clean(sbd.get("LCT_ARA_DTL_ADR"))) if x)
    if address:
        item["address"] = address
        item["gu"] = seoul_gu(address) or item["gu"]
    item["moveIn"] = to_month(sbd.get("MVIN_XPC_YM")) or item["moveIn"]
    item["units"] = to_int(sbd.get("SUM_TOT_HSH_CNT")) or item["units"]

    starts, ends, winners, c_starts, c_ends = [], [], [], [], []
    for r in _ds(body, "dsSplScdl"):
        acp = _dates_in(r.get("ACP_DTTM"))
        if acp:
            starts.append(acp[0])
            ends.append(acp[-1])
        winners += _dates_in(r.get("PZWR_ANC_DT"))
        c_starts += _dates_in(r.get("CTRT_ST_DT"))
        c_ends += _dates_in(r.get("CTRT_ED_DT"))
    d = item["dates"]
    if starts:
        d["start"] = min(starts)
        d["end"] = max(ends)
        item.pop("statusHint", None)  # 실제 접수기간을 알았으니 목록의 상태 문구는 필요 없다
    if winners:
        d["winner"] = min(winners)
    if c_starts:
        d["contract_start"] = min(c_starts)
        d["contract_end"] = max(c_ends or c_starts)

    files = [clean(a.get("CMN_AHFL_NM")) for a in _ds(body, "dsAhflInfo")
             if str(a.get("AHFL_URL") or "").startswith("http") and clean(a.get("CMN_AHFL_NM"))]
    if files:
        item["files"] = files


def _fetch_list(session, key: str, url: str, what: str) -> tuple[list[tuple[dict, str]], list[str]]:
    today = kst_today()
    st = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y.%m.%d")
    ed = (today + timedelta(days=180)).strftime("%Y.%m.%d")
    rows_out: dict[str, tuple[dict, str]] = {}
    failed: list[str] = []
    for code, cat in TYPES.items():
        try:
            for page in range(1, 6):
                resp = get(session, url, params={
                    "serviceKey": key, "PG_SZ": PER_PAGE, "PAGE": page,
                    "PAN_NT_ST_DT": st, "CLSG_DT": ed, "UPP_AIS_TP_CD": code, "CNP_CD": "11",
                })
                rows = _ds(_json(resp, what), "dsList")
                for row in rows:
                    if row.get("CNP_CD_NM") and not is_seoul(row.get("CNP_CD_NM")):
                        continue
                    if row.get("PAN_ID"):
                        rows_out[str(row["PAN_ID"])] = (row, cat)
                if len(rows) < PER_PAGE:
                    break
        except SourceError:
            raise
        except Exception as e:
            log.error("%s 유형 %s 실패: %s", what, code, e)
            failed.append(code)
    if len(failed) == len(TYPES):
        raise SourceError(f"{what}를 하나도 읽지 못했습니다")
    return list(rows_out.values()), failed


def _collect(session, key: str | None, *, list_url: str, dtl_url: str, pre: bool) -> tuple[list[dict], list[str]]:
    what = "LH 사전청약" if pre else "LH"
    if not key:
        raise SourceError(f"DATA_GO_KR_KEY 가 없어 {what}를 건너뜁니다")
    if not list_url:
        raise SourceError(f"{what} 요청주소가 아직 비어 있습니다 (collector/lh.py PRE_LIST_URL)")
    rows, failed = _fetch_list(session, key, list_url, what + " 공고문")
    items = []
    detail_on = bool(dtl_url)
    for row, cat in rows:
        item = normalize(row, cat, pre=pre)
        if not item["name"]:
            continue
        if detail_on:
            try:
                params = {"serviceKey": key, "PAN_ID": row["PAN_ID"], **{k: row.get(k) for k in DETAIL_PARAMS}}
                apply_detail(item, _json(get(session, dtl_url, params=params), what + " 상세정보"))
            except SourceError as e:  # 상세정보 서비스 미신청: 이번 실행에선 목록만
                log.warning("%s — 목록 정보만 씁니다", e)
                failed.append("상세")
                detail_on = False
            except Exception as e:
                log.warning("%s 상세 실패(%s): %s", what, row.get("PAN_ID"), e)
        items.append(item)
    log.info("%s: 서울 %d건 (상세정보 %s)", what, len(items), "사용" if detail_on else "미사용")
    return items, failed


def collect(session, key: str | None) -> tuple[list[dict], list[str]]:
    return _collect(session, key, list_url=LIST_URL, dtl_url=DTL_URL, pre=False)


def collect_pre(session, key: str | None) -> tuple[list[dict], list[str]]:
    return _collect(session, key, list_url=PRE_LIST_URL, dtl_url=PRE_DTL_URL, pre=True)
