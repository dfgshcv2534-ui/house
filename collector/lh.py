"""LH 분양임대공고 (공공데이터포털, apis.data.go.kr/B552555). 수도권(서울 11·경기 41·인천 28)만.

공공데이터포털 서비스키 하나로 아래 서비스를 모두 쓴다. 다만 서비스마다 따로 활용신청해야 하고,
신청하지 않은 서비스는 '등록되지 않은 서비스키' 오류가 나서 그 부분만 건너뛴다.

- 분양임대공고문 조회            → 공고 목록 (공고명·유형·게시일·마감일·상세 URL)
- 분양임대공고별 상세정보 조회     → 공고마다 주소·접수/발표/계약 일정·입주 예정·세대수·첨부
- 분양임대공고별 공급정보 조회     → 주택형별 면적·세대수 (공고 전체 세대수는 이 합계)
- 위 두 서비스의 '(사전청약)' 버전 → 사전청약 공고. 요청주소를 아래 PRE_* 에 넣으면 켜진다.
"""
from __future__ import annotations

import re
from datetime import timedelta

from .common import (
    SPECIAL, SourceError, clean, clean_title, drop_reposts, get, gu_in_text, is_correction, is_recruitment_title, REGIONS, region_of, sigungu, place_in_text,
    kst_today, log, redact, special_kind, to_float, to_int, to_iso, to_month,
)

LIST_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
DTL_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"
SPL_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeSplInfo1/getLeaseNoticeSplInfo1"  # 공급정보: 주택형별 세대수·면적

# 사전청약 서비스 자리: 활용신청 승인 후 공공데이터포털 상세 페이지의 '요청주소(End Point)' 뒤에
# 오퍼레이션 이름까지 붙인 전체 주소를 넣는다. 비어 있으면 사전청약은 건너뛴다.
PRE_LIST_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeBfhInfo1/lhLeaseNoticeBfhInfo1"
PRE_DTL_URL = ""  # 사전청약 상세정보 요청주소를 받으면 채운다

LOOKBACK_DAYS = 180
PER_PAGE = 100
REGION_CODES = {"11": "서울", "41": "경기", "28": "인천"}
# 상위 유형: 05 분양주택, 06 임대주택, 39 신혼희망타운, 13 주거복지
TYPES = {"05": "분양", "06": "임대", "39": "분양", "13": "임대"}
DETAIL_PARAMS = ("CCR_CNNT_SYS_DS_CD", "SPL_INF_TP_CD", "UPP_AIS_TP_CD", "AIS_TP_CD")
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_logged_fields: set[str] = set()


def _log_fields_once(what: str, row: dict) -> None:
    """응답 필드 이름을 한 번 남겨 두면 나중에 쓸 만한 항목을 찾기 쉽다 (공개 데이터라 값도 문제없음)."""
    if row and what not in _logged_fields:
        _logged_fields.add(what)
        log.info("%s 필드: %s", what, ", ".join(f"{k}={str(v)[:30]}" for k, v in row.items()))


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
    raw_name = clean(row.get("PAN_NM"))
    name = clean_title(raw_name)
    tags = (["사전청약"] if pre else []) + (["정정공고"] if is_correction(raw_name) else [])
    return {
        "id": f"{'lhp' if pre else 'lh'}:{row.get('PAN_ID')}",
        "source": "LH",
        "sector": "공공",
        "region": region_of(row.get("CNP_CD_NM")) or region_of(name) or "서울",
        "cat": cat,
        "kind": kind,
        "name": name,
        "address": None,
        "gu": place_in_text(name, region_of(row.get("CNP_CD_NM")) or region_of(name)),
        "units": None,  # 목록의 ALL_CNT는 검색 결과 건수라 세대수가 아니다
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
        "tags": tags,
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
    sbds = _ds(body, "dsSbd") or [{}]
    sbd = sbds[0]
    address = " ".join(x for x in (clean(sbd.get("LCT_ARA_ADR")), clean(sbd.get("LCT_ARA_DTL_ADR"))) if x)
    if not address:  # 유형마다 주소 필드 이름이 달라서, 서울 주소가 든 *ADR 필드를 찾는다
        address = next((clean(v) for k, v in sbd.items() if k.endswith("ADR") and region_of(v)), None)
    if address:
        item["address"] = address
        item["gu"] = sigungu(address) or item["gu"]
        item["region"] = region_of(address) or item["region"]
    move_in = to_month(sbd.get("MVIN_XPC_YM"))
    notice = item["dates"].get("notice") or ""
    if move_in and move_in >= notice[:7]:  # 이미 입주한 기존 단지(예비입주자 모집)의 과거 입주월은 숨긴다
        item["moveIn"] = move_in
    # 세대수: 합계 필드가 있으면 그것, 없으면 단지별 HSH_CNT 합 (공급정보 서비스 없이도 채워진다)
    item["units"] = to_int(sbd.get("SUM_TOT_HSH_CNT")) or (sum(to_int(b.get("HSH_CNT")) or 0 for b in sbds) or None) or item["units"]
    heat = clean(sbd.get("HTN_FMLA_DESC"))
    if heat and heat not in item["tags"]:
        item["tags"].append(heat)
    area = clean(sbd.get("DDO_AR") or sbd.get("MIN_MAX_RSDN_DDO_AR"))
    if area:
        lo, _, hi = area.partition("~")
        item["area"] = f"{lo.strip()}㎡" if not hi or lo.strip() == hi.strip() else f"{lo.strip()}~{hi.strip()}㎡"

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

    files = [{"name": clean(a.get("CMN_AHFL_NM")), "url": a.get("AHFL_URL")} for a in _ds(body, "dsAhflInfo")
             if str(a.get("AHFL_URL") or "").startswith("http") and clean(a.get("CMN_AHFL_NM"))]
    if files:
        item["files"] = files

    # 단지 이미지(조감도·배치도·평면도 등). lhImageView 주소는 뷰어 페이지라 나중에 실제 이미지로 바꾼다
    images = []
    for a in _ds(body, "dsSbdAhfl"):
        url, name = str(a.get("AHFL_URL") or ""), clean(a.get("CMN_AHFL_NM")) or ""
        if url.startswith("http") and name.lower().endswith(IMG_EXT):
            label = clean(a.get("SL_PAN_AHFL_DS_CD_NM")) or re.sub(r"\.\w+$", "", name)  # 구분이 없으면 파일 이름('단지배치도')
            images.append({"label": label, "name": name, "url": url})
    if images:
        item["images"] = images[:16]
    _log_fields_once("LH 상세 dsSbd", sbd)


def apply_supply(item: dict, body) -> None:
    """공급정보(주택형별 면적·세대수)로 models 와 전체 세대수를 채운다."""
    models = []
    for r in _ds(body, "dsList01"):
        _log_fields_once("LH 공급정보", r)
        ty = clean(r.get("HTY_NNA"))
        if not ty:
            continue
        m = {
            "type": re.sub(r"^0*(\d+)(?:\.\d+)?", r"\1", ty),
            "area": to_float(r.get("SPL_AR")),
            "excl": to_float(r.get("DDO_AR")) or to_float(re.match(r"0*(\d+(?:\.\d+)?)", ty).group(1) if re.match(r"0*\d", ty) else None),
            "units": to_int(r.get("HSH_CNT")),
        }
        models.append({k: v for k, v in m.items() if v not in (None, "")})
    if models:
        item["models"] = models
        total = sum(m.get("units") or 0 for m in models)
        if total and not item.get("units"):
            item["units"] = total


TYPE_RE = re.compile(r"(\d{2,3})(?:\.\d+)?\s*(?:㎡|m2|형|타입|type)?\s*([A-Za-z])?", re.I)


def attach_plans(item: dict) -> None:
    """'평면'이 붙은 이미지를 파일 이름의 면적·타입(26A, 36 등)으로 주택형과 짝짓는다."""
    plans = [im for im in item.get("images", []) if "평면" in (im["label"] + im["name"])]
    for m in item.get("models", []):
        mt = re.match(r"(\d+)([A-Za-z]?)", m.get("type") or "")
        if not mt:
            continue
        num, letter = mt.group(1), mt.group(2).upper()
        for im in plans:
            for found in TYPE_RE.finditer(im["name"]):
                if found.group(1).lstrip("0") == num.lstrip("0") and (not letter or (found.group(2) or "").upper() == letter):
                    m["plan"] = im["url"]
                    break
            if "plan" in m:
                break


_IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)", re.I)


def resolve_images(session, item: dict) -> None:
    """LH 이미지 뷰어(lhImageView) 주소를 실제 이미지 파일 주소로 바꾼다.

    뷰어 페이지에는 '이미지 없음' 같은 장식 그림도 섞여 있어서 그런 건 건너뛴다.
    실제 그림을 못 찾으면 뷰어 주소를 그대로 둔다 (화면에서는 썸네일 대신 링크로 보여준다).
    """
    from urllib.parse import urljoin
    for im in item.get("images", []):
        if "ImageView" not in im["url"]:
            continue
        try:
            resp = get(session, im["url"], attempts=1, timeout=15)
        except Exception:
            continue
        srcs = [urljoin(im["url"], m) for m in _IMG_SRC.findall(resp.text)]
        real = [u for u in srcs if not re.search(r"noImg|/images/co/|logo|icon|btn|blank", u, re.I)]
        if "viewer" not in _logged_fields:
            _logged_fields.add("viewer")
            log.info("LH 이미지 뷰어 그림 후보: %s", srcs[:8])
        if real:
            im["url"] = real[0]


def _fetch_list(session, key: str, url: str, what: str) -> tuple[list[tuple[dict, str]], list[str]]:
    today = kst_today()
    st = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y.%m.%d")
    ed = (today + timedelta(days=180)).strftime("%Y.%m.%d")
    rows_out: dict[str, tuple[dict, str]] = {}
    failed: list[str] = []
    jobs = [(code, cat, cnp) for code, cat in TYPES.items() for cnp in REGION_CODES]
    for code, cat, cnp in jobs:
        try:
            for page in range(1, 6):
                resp = get(session, url, params={
                    "serviceKey": key, "PG_SZ": PER_PAGE, "PAGE": page,
                    "PAN_NT_ST_DT": st, "CLSG_DT": ed, "UPP_AIS_TP_CD": code, "CNP_CD": cnp,
                })
                rows = _ds(_json(resp, what), "dsList")
                for row in rows:
                    if row.get("CNP_CD_NM") and region_of(row.get("CNP_CD_NM")) not in REGIONS:
                        continue
                    if row.get("PAN_ID"):
                        rows_out[str(row["PAN_ID"])] = (row, cat)
                if len(rows) < PER_PAGE:
                    break
        except SourceError:
            raise
        except Exception as e:
            log.error("%s 유형 %s(%s) 실패: %s", what, code, REGION_CODES[cnp], e)
            failed.append(f"{code}-{cnp}")
    if len(failed) == len(jobs):
        raise SourceError(f"{what}를 하나도 읽지 못했습니다")
    return list(rows_out.values()), failed


def _fetch_pre_list(session, key: str, url: str, what: str) -> tuple[list[tuple[dict, str]], list[str]]:
    """사전청약 목록: 게시일 기간(PAN_ST_DT~PAN_ED_DT, YYYYMMDD)만 받고 지역·유형 조건이 없어 서울은 직접 거른다."""
    today = kst_today()
    params = {"serviceKey": key, "PG_SZ": PER_PAGE,
              "PAN_ST_DT": (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d"), "PAN_ED_DT": today.strftime("%Y%m%d")}
    rows_out: dict[str, tuple[dict, str]] = {}
    total = 0
    for page in range(1, 11):
        rows = _ds(_json(get(session, url, params={**params, "PAGE": page}), what), "dsList")
        total += len(rows)
        for row in rows:
            _log_fields_once(what, row)
            if region_of(row.get("CNP_CD_NM"), row.get("PAN_NM")) not in REGIONS:
                continue
            if row.get("PAN_ID"):
                kind = f"{row.get('UPP_AIS_TP_NM') or ''} {row.get('AIS_TP_CD_NM') or ''}"
                rows_out[str(row["PAN_ID"])] = (row, "분양" if "분양" in kind or "신혼희망" in kind else "임대")
        if len(rows) < PER_PAGE:
            break
    log.info("%s: 최근 %d건 중 수도권 %d건", what, total, len(rows_out))
    return list(rows_out.values()), []


def _collect(session, key: str | None, *, list_url: str, dtl_url: str, spl_url: str, pre: bool) -> tuple[list[dict], list[str]]:
    what = "LH 사전청약" if pre else "LH"
    if not key:
        raise SourceError(f"DATA_GO_KR_KEY 가 없어 {what}를 건너뜁니다")
    if not list_url:
        raise SourceError(f"{what} 요청주소가 아직 비어 있습니다 (collector/lh.py PRE_LIST_URL)")
    fetch = _fetch_pre_list if pre else _fetch_list
    rows, failed = fetch(session, key, list_url, what + " 공고문")
    items = []
    detail_on = bool(dtl_url)
    supply_on = bool(spl_url)
    for row, cat in rows:
        item = normalize(row, cat, pre=pre)
        if not item["name"] or not is_recruitment_title(row.get("PAN_NM")):
            continue
        params = {"serviceKey": key, "PAN_ID": row["PAN_ID"], **{k: row.get(k) for k in DETAIL_PARAMS}}
        if detail_on:
            try:
                apply_detail(item, _json(get(session, dtl_url, params=params), what + " 상세정보"))
                resolve_images(session, item)
            except SourceError as e:  # 상세정보 서비스 미신청: 이번 실행에선 목록만
                log.warning("%s — 목록 정보만 씁니다", e)
                failed.append("상세")
                detail_on = False
            except Exception as e:
                log.warning("%s 상세 실패(%s): %s", what, row.get("PAN_ID"), e)
        if supply_on:
            try:
                apply_supply(item, _json(get(session, spl_url, params=params), what + " 공급정보"))
            except SourceError as e:  # 공급정보 서비스 미신청
                log.info("%s — 주택형별 표 없이 진행합니다 (선택 기능)", e)
                supply_on = False
            except Exception as e:
                log.warning("%s 공급정보 실패(%s): %s", what, row.get("PAN_ID"), e)
        attach_plans(item)
        items.append(item)
    items = drop_reposts(items)
    log.info("%s: 수도권 %d건 (상세정보 %s, 공급정보 %s)", what, len(items),
             "사용" if detail_on else "미사용", "사용" if supply_on else "미사용")
    return items, failed


def collect(session, key: str | None) -> tuple[list[dict], list[str]]:
    return _collect(session, key, list_url=LIST_URL, dtl_url=DTL_URL, spl_url=SPL_URL, pre=False)


def collect_pre(session, key: str | None) -> tuple[list[dict], list[str]]:
    return _collect(session, key, list_url=PRE_LIST_URL, dtl_url=PRE_DTL_URL, spl_url="", pre=True)
