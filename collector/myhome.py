"""국토교통부 마이홈포털 공공주택 모집공고 조회 서비스 (공공데이터포털, apis.data.go.kr/1613000/HWSPR02).

여러 공급기관의 공공임대·공공분양 모집공고를 한곳에서 준다. 공고 사이트가 해외 접속을 막아도
공공데이터포털 API 는 열려 있어서 GH·iH 의 예비 경로로 쓰고, 그 밖의 지방 도시공사 공고도 함께 받는다.
LH·SH 는 각자의 수집기가 더 자세하게 받으므로 여기서는 뺀다.
"""
from __future__ import annotations

import re
from datetime import timedelta

from .common import (
    REGIONS, SPECIAL, SourceError, clean, get, is_recruitment_title, kst_today, log, region_of, redact,
    special_kind, still_relevant, to_int, to_iso,
)

BASE = "https://apis.data.go.kr/1613000/HWSPR02"
ENDPOINTS = [("rent", "/rsdtRcritNtcList", "임대"), ("sale", "/ltRsdtRcritNtcList", "분양")]
REGION_CODES = {"11": "서울", "41": "경기", "28": "인천"}
LOOKBACK_DAYS = 120
PER_PAGE = 100
SKIP_SUPPLIER = re.compile(r"^LH$|한국토지주택|토지주택공사|^SH|서울주택도시")
SUPPLIER_SHORT = {"경기주택도시공사": "GH", "인천도시공사": "iH"}


def _body(resp) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise SourceError(redact(f"마이홈 API 응답이 JSON이 아님 (HTTP {resp.status_code}): {resp.text[:150]}"))
    if isinstance(data, dict) and "OpenAPI_ServiceResponse" in str(data)[:200]:
        raise SourceError(redact(f"마이홈 API 오류: {str(data)[:200]}"))
    data = data.get("response", data)
    code = str((data.get("header") or {}).get("resultCode") or "00")
    if code == "03":  # 데이터 없음
        return {"item": []}
    if code not in ("00", "0"):
        raise RuntimeError(f"마이홈 API 오류 {code}: {(data.get('header') or {}).get('resultMsg')}")
    return data.get("body") or {}


def _items(body: dict) -> list[dict]:
    items = body.get("item") or body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or [items]
    return items if isinstance(items, list) else []


def _sigungu(name: str | None) -> str | None:
    """'수원시 권선구' → '수원시', '연수구' → '연수구'."""
    if not name:
        return None
    m = re.match(r"(\S+?[시군구])(?:\s|$)", name.strip())
    return m.group(1) if m else None


def group_notices(rows: list[dict], cat: str) -> list[dict]:
    """마이홈은 한 공고에 단지(houseSn)가 여러 개면 여러 줄로 준다 → 공고 하나로 묶는다."""
    by_id: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("pblancId"):
            by_id.setdefault(str(r["pblancId"]), []).append(r)
    out = []
    for pid, group in by_id.items():
        r = group[0]
        supplier = clean(r.get("suplyInsttNm")) or ""
        if SKIP_SUPPLIER.search(supplier):
            continue
        name = clean(r.get("pblancNm"))
        if not name or not is_recruitment_title(name):
            continue
        region = region_of(r.get("brtcNm"), r.get("fullAdres"))
        if region not in REGIONS:
            continue
        kind = clean(r.get("suplyTyNm")) or clean(r.get("houseTyNm")) or ("공공임대" if cat == "임대" else "공공분양")
        item_cat = cat
        special = special_kind(kind, name)
        if special:
            kind, item_cat = special, SPECIAL
        deposits = [to_int(g.get("rentGtn")) for g in group if to_int(g.get("rentGtn"))]
        monthly = [to_int(g.get("mtRntchrg")) for g in group if to_int(g.get("mtRntchrg"))]
        units = sum(to_int(g.get("sumSuplyCo")) or to_int(g.get("suplyHoCo")) or 0 for g in group) or None
        dates = {
            "notice": to_iso(r.get("rcritPblancDe")),
            "start": min(filter(None, (to_iso(g.get("beginDe")) for g in group)), default=None),
            "end": max(filter(None, (to_iso(g.get("endDe")) for g in group)), default=None),
            "winner": to_iso(r.get("przwnerPresnatnDe")),
        }
        complexes = [c for c in dict.fromkeys(clean(g.get("hsmpNm")) for g in group) if c]
        item = {
            "id": f"mh:{pid}",
            "source": SUPPLIER_SHORT.get(supplier, supplier or "마이홈"),
            "sector": "공공",
            "region": region,
            "cat": item_cat,
            "kind": kind,
            "name": name,
            "address": clean(r.get("fullAdres")),
            "gu": _sigungu(r.get("signguNm")),
            "units": units,
            "dates": {k: v for k, v in dates.items() if v},
            "dateBasis": "api",
            "statusHint": clean(r.get("sttusNm")),
            "moveIn": None,
            "models": [],
            "priceMin": None,
            "priceMax": None,
            "tags": [t for t in [clean(r.get("heatMthdNm"))] if t],
            "targets": [],
            "builder": None,
            "supplier": supplier or None,
            "tel": clean(r.get("refrnc")),
            "url": clean(r.get("url")) or clean(r.get("pcUrl")),
            "homepage": None,
            "via": "마이홈",
        }
        if deposits or monthly:
            item["rent"] = {"deposit": round(min(deposits) / 10000) if deposits else None,  # 만원
                            "monthly": min(monthly) if monthly else None}                  # 원
        if len(complexes) > 1:
            item["complexes"] = complexes
        out.append(item)
    return out


def collect(session, key: str | None) -> tuple[list[dict], list[str]]:
    if not key:
        raise SourceError("DATA_GO_KR_KEY 가 없어 마이홈을 건너뜁니다")
    since = (kst_today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    out, failed = [], []
    for part, path, cat in ENDPOINTS:
        for code, region in REGION_CODES.items():
            try:
                rows = []
                for page in range(1, 6):
                    body = _body(get(session, BASE + path, params={
                        "serviceKey": key, "brtcCode": code, "numOfRows": PER_PAGE, "pageNo": page}, attempts=2, timeout=20))
                    items = _items(body)
                    rows.extend(items)
                    if len(items) < PER_PAGE or all((to_iso(i.get("rcritPblancDe")) or "9999") < since for i in items):
                        break
            except SourceError:
                raise
            except Exception as e:
                log.error("마이홈 %s(%s) 실패: %s", cat, region, e)
                failed.append(f"{part}-{code}")
                continue
            recent = [r for r in rows if (to_iso(r.get("rcritPblancDe")) or "9999") >= since]
            from collections import Counter
            log.info("마이홈 %s(%s) 공급기관: %s", cat, region,
                     dict(Counter(clean(r.get("suplyInsttNm")) for r in recent)))
            items = [i for i in group_notices(recent, cat) if still_relevant(i["dates"])]
            log.info("마이홈 %s(%s): 최근 %d줄 → LH·SH 제외 공고 %d건", cat, region, len(recent), len(items))
            out.extend(items)
    if len(failed) == len(ENDPOINTS) * len(REGION_CODES):
        raise SourceError("마이홈 API를 하나도 읽지 못했습니다")
    return out, failed
