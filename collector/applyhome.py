"""한국부동산원 청약홈 분양정보 조회 서비스 (공공데이터포털 15098547, api.odcloud.kr).

APT·무순위·오피스텔/도시형·공공지원민간임대·임의공급 공고를 받아 서울 것만 남긴다.
공고 목록(Detail)에는 가격이 없어서, 서울 공고마다 주택형(Mdl)을 한 번씩 더 조회한다.
"""
from __future__ import annotations

import re
import time
from datetime import timedelta

from .common import (
    SPECIAL, SourceError, clean, first, get, redact, is_seoul, kst_today, log, sector_of, seoul_gu, special_kind, to_float, to_int, to_iso, to_month,
)

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
PER_PAGE = 500
MAX_PAGES = 20
LOOKBACK_DAYS = 180

# kind: 화면에 보이는 유형 이름, cat: 분양/임대
SOURCES = [
    {"key": "apt", "detail": "getAPTLttotPblancDetail", "model": "getAPTLttotPblancMdl", "kind": "아파트", "cat": "분양"},
    {"key": "remndr", "detail": "getRemndrLttotPblancDetail", "model": "getRemndrLttotPblancMdl", "kind": "무순위·잔여세대", "cat": "분양"},
    {"key": "opt", "detail": "getOptLttotPblancDetail", "model": "getOptLttotPblancMdl", "kind": "임의공급", "cat": "분양"},
    {"key": "urbty", "detail": "getUrbtyOfctlLttotPblancDetail", "model": "getUrbtyOfctlLttotPblancMdl", "kind": "오피스텔·도시형", "cat": "분양"},
    {"key": "pvtrent", "detail": "getPblPvtRentLttotPblancDetail", "model": "getPblPvtRentLttotPblancMdl", "kind": "공공지원민간임대", "cat": "임대"},
]

FLAG_TAGS = [
    ("PARCPRC_ULS_AT", "분양가상한제"),
    ("SPECLT_RDN_EARTH_AT", "투기과열지구"),
    ("MDAT_TRGET_AREA_SECD", "조정대상지역"),
    ("PUBLIC_HOUSE_EARTH_AT", "공공주택지구"),
    ("LRSCL_BLDLND_AT", "대규모택지"),
    ("IMPRMN_BSNS_AT", "정비사업"),
    ("PUBLIC_HOUSE_SPCLW_APPLC_AT", "공공주택특별법"),
]


def _call(session, op: str, key: str, params: dict) -> dict:
    resp = get(session, f"{BASE}/{op}", params={"serviceKey": key, **params})
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError(redact(f"{op}: JSON 아님 (HTTP {resp.status_code}) {resp.text[:200]}"))
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(code, int) and code < 0:
        # -4 미등록 키, -401 권한 없음 등: 키 문제는 다른 오퍼레이션도 똑같이 실패한다
        raise SourceError(f"청약홈 API 오류 {code}: {body.get('msg', '')} (서비스키·활용신청 확인)")
    if resp.status_code >= 400 or not isinstance(body.get("data"), list):
        raise RuntimeError(redact(f"{op}: HTTP {resp.status_code} {str(body)[:200]}"))
    return body


def _fetch_details(session, op: str, key: str, since: str) -> list[dict]:
    """모집공고일 since 이후 공고. 조건 검색이 거절되면 전체를 최신순으로 넘기며 since에서 멈춘다."""
    rows: list[dict] = []
    use_cond = True
    page = 1
    while page <= MAX_PAGES:
        params = {"page": page, "perPage": PER_PAGE}
        if use_cond:
            params["cond[RCRIT_PBLANC_DE::GTE]"] = since
        try:
            body = _call(session, op, key, params)
        except RuntimeError:
            if use_cond and page == 1:
                log.warning("%s: 날짜 조건 검색 실패, 전체 목록으로 다시 시도", op)
                use_cond = False
                continue
            raise
        data = body["data"]
        rows.extend(data)
        total = body.get("matchCount") or body.get("totalCount") or 0
        if not data or len(rows) >= total:
            break
        if not use_cond and all((to_iso(r.get("RCRIT_PBLANC_DE")) or "9999") < since for r in data):
            break
        page += 1
    return [r for r in rows if (to_iso(r.get("RCRIT_PBLANC_DE")) or "9999") >= since]


def _fetch_models(session, op: str, key: str, manage_no: str) -> list[dict]:
    body = _call(session, op, key, {"page": 1, "perPage": 100, "cond[HOUSE_MANAGE_NO::EQ]": manage_no})
    # 조건이 무시되면 다른 단지 행이 섞이므로 관리번호로 다시 거른다
    return [r for r in body["data"] if str(r.get("HOUSE_MANAGE_NO")) == str(manage_no)]


def house_type_label(value) -> str | None:
    """'084.9800A' → '84A', '059.9600' → '59'."""
    text = clean(value)
    if not text:
        return None
    m = re.match(r"0*(\d+)(?:\.\d+)?\s*([A-Za-z가-힣0-9]*)$", text)
    return f"{m.group(1)}{m.group(2)}" if m else text


def normalize_model(row: dict) -> dict:
    model = {
        "type": house_type_label(first(row, "HOUSE_TY", "TP")),
        "area": to_float(first(row, "SUPLY_AR")),            # 공급면적(㎡)
        "excl": to_float(first(row, "EXCLUSE_AR")),          # 전용면적(㎡), 오피스텔 등
        "units": to_int(first(row, "SUPLY_HSHLDCO")),
        "special": to_int(first(row, "SPSPLY_HSHLDCO")),
        "price": to_int(first(row, "LTTOT_TOP_AMOUNT", "SUPLY_AMOUNT")),  # 만원
    }
    if model["excl"] is None and model["type"]:
        m = re.match(r"(\d+)", model["type"])
        model["excl"] = float(m.group(1)) if m else None
    return {k: v for k, v in model.items() if v not in (None, "")}


def normalize(row: dict, src: dict, models: list[dict]) -> dict:
    address = clean(row.get("HSSPLY_ADRES"))
    dates = {
        "notice": to_iso(row.get("RCRIT_PBLANC_DE")),
        "start": to_iso(first(row, "RCEPT_BGNDE", "SUBSCRPT_RCEPT_BGNDE", "SPSPLY_RCEPT_BGNDE", "GNRL_RCEPT_BGNDE")),
        "end": to_iso(first(row, "RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE", "GNRL_RCEPT_ENDDE")),
        "special_start": to_iso(row.get("SPSPLY_RCEPT_BGNDE")),
        "special_end": to_iso(row.get("SPSPLY_RCEPT_ENDDE")),
        "rank1_start": to_iso(first(row, "GNRL_RNK1_CRSPAREA_RCPTDE", "GNRL_RNK1_CRSPAREA_RCEPT_BGNDE", "GNRL_RCEPT_BGNDE")),
        "rank1_end": to_iso(first(row, "GNRL_RNK1_CRSPAREA_ENDDE", "GNRL_RNK1_ETC_AREA_ENDDE", "GNRL_RCEPT_ENDDE")),
        "rank2_start": to_iso(row.get("GNRL_RNK2_CRSPAREA_RCPTDE")),
        "rank2_end": to_iso(first(row, "GNRL_RNK2_CRSPAREA_ENDDE", "GNRL_RNK2_ETC_AREA_ENDDE")),
        "winner": to_iso(row.get("PRZWNER_PRESNATN_DE")),
        "contract_start": to_iso(row.get("CNTRCT_CNCLS_BGNDE")),
        "contract_end": to_iso(row.get("CNTRCT_CNCLS_ENDDE")),
    }
    kind = src["kind"]
    if src["key"] == "urbty":
        kind = clean(first(row, "HOUSE_DTL_SECD_NM", "HOUSE_SECD_NM")) or kind
    cat = src["cat"]
    rent_nm = clean(row.get("RENT_SECD_NM")) or ""
    if "임대" in rent_nm or "임대" in kind:
        cat = "임대"
    special = special_kind(rent_nm, clean(row.get("HOUSE_NM")))
    if special:
        kind, cat = special, SPECIAL
    tags = [label for field, label in FLAG_TAGS if str(row.get(field) or "").upper() == "Y"]
    detail_kind = clean(row.get("HOUSE_DTL_SECD_NM"))
    if rent_nm and rent_nm != "분양주택":
        tags.append(rent_nm)

    prices = [m["price"] for m in models if m.get("price")]
    manage_no = clean(row.get("HOUSE_MANAGE_NO")) or clean(row.get("PBLANC_NO"))
    return {
        "id": f"ah:{src['key']}:{manage_no}:{clean(row.get('PBLANC_NO')) or ''}",
        "source": "청약홈",
        "sector": sector_of(detail_kind, clean(row.get("BSNS_MBY_NM"))),
        "cat": cat,
        "kind": kind,
        "name": clean(row.get("HOUSE_NM")),
        "address": address,
        "gu": seoul_gu(address),
        "units": to_int(row.get("TOT_SUPLY_HSHLDCO")) or (sum(m.get("units", 0) + m.get("special", 0) for m in models) or None),
        "dates": {k: v for k, v in dates.items() if v},
        "dateBasis": "api",
        "moveIn": to_month(row.get("MVN_PREARNGE_YM")),
        "models": models,
        "priceMin": min(prices) if prices else None,
        "priceMax": max(prices) if prices else None,
        "tags": tags,
        "targets": [],
        "builder": clean(first(row, "CNSTRCT_ENTRPS_NM")),
        "supplier": clean(first(row, "BSNS_MBY_NM")),
        "tel": clean(first(row, "MDHS_TELNO")),
        "url": clean(row.get("PBLANC_URL")),
        "homepage": clean(row.get("HMPG_ADRES")),
    }


def collect(session, key: str | None) -> tuple[list[dict], list[str]]:
    """(서울 공고 목록, 실패한 하위 출처 키 목록)."""
    if not key:
        raise SourceError("DATA_GO_KR_KEY 가 없어 청약홈을 건너뜁니다")
    since = (kst_today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    out: list[dict] = []
    failed: list[str] = []
    for src in SOURCES:
        try:
            rows = _fetch_details(session, src["detail"], key, since)
        except SourceError:
            raise
        except Exception as e:  # 한 종류가 실패해도 나머지는 계속
            log.error("청약홈 %s 실패: %s", src["kind"], e)
            failed.append(src["key"])
            continue
        seoul = [r for r in rows if is_seoul(r.get("SUBSCRPT_AREA_CODE_NM"), r.get("HSSPLY_ADRES"))]
        log.info("청약홈 %s: 최근 %d건 중 서울 %d건", src["kind"], len(rows), len(seoul))
        for row in seoul:
            models: list[dict] = []
            manage_no = row.get("HOUSE_MANAGE_NO")
            if manage_no:
                try:
                    models = [normalize_model(m) for m in _fetch_models(session, src["model"], key, manage_no)]
                except Exception as e:
                    log.warning("청약홈 %s 주택형 조회 실패(%s): %s", src["kind"], manage_no, e)
                time.sleep(0.2)
            item = normalize(row, src, models)
            if item["name"]:
                out.append(item)
    if len(failed) == len(SOURCES):
        raise SourceError("청약홈 API를 하나도 읽지 못했습니다")
    return out, failed
