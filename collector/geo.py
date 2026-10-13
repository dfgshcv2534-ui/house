"""공고 위치를 지도에 찍기 위한 좌표 찾기.

주소가 있으면 OpenStreetMap Nominatim 으로 찾고(무료, 초당 1회 제한), 못 찾으면 동 → 자치구 중심으로 낮춘다.
한 번 찾은 결과는 docs/data/geocode.json 에 저장해서 다음 날에는 다시 묻지 않는다.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .common import REGION_FULL, log

NOMINATIM = "https://nominatim.openstreetmap.org/search"
CONTACT_UA = "seoul-house-board/1.0 (+https://github.com/dfgshcv2534-ui/house)"
MAX_LOOKUPS = 120  # 한 번 실행에서 새로 물어보는 최대 횟수

# 자치구 중심(구청 부근) 좌표: 주소를 못 찾을 때 대략적인 위치로 쓴다
GU_CENTER = {
    "강남구": (37.5172, 127.0473), "강동구": (37.5301, 127.1238), "강북구": (37.6396, 127.0257),
    "강서구": (37.5509, 126.8495), "관악구": (37.4784, 126.9516), "광진구": (37.5385, 127.0823),
    "구로구": (37.4955, 126.8875), "금천구": (37.4569, 126.8955), "노원구": (37.6542, 127.0568),
    "도봉구": (37.6688, 127.0471), "동대문구": (37.5744, 127.0396), "동작구": (37.5124, 126.9393),
    "마포구": (37.5663, 126.9019), "서대문구": (37.5791, 126.9368), "서초구": (37.4837, 127.0324),
    "성동구": (37.5633, 127.0371), "성북구": (37.5894, 127.0167), "송파구": (37.5145, 127.1059),
    "양천구": (37.5169, 126.8664), "영등포구": (37.5264, 126.8962), "용산구": (37.5324, 126.9900),
    "은평구": (37.6027, 126.9291), "종로구": (37.5735, 126.9790), "중구": (37.5641, 126.9979),
    "중랑구": (37.6063, 127.0927),
}


def queries_for(address: str) -> list[tuple[str, str]]:
    """(검색어, 정밀도) 후보. 번지·블록을 떼어 가며 점점 넓게 찾는다."""
    address = re.sub(r"\s+", " ", address).strip()
    out = [(address, "주소")]
    no_block = re.sub(r"\s*[\w-]*블록.*$|\s*\(.*?\)|\s*외\s*\d+.*$|,.*$", "", address).strip()
    if no_block and no_block != address:
        out.append((no_block, "주소"))
    # 동·읍·면·도로명까지만 남긴 넓은 검색어 (서울 강동구 고덕동 / 경기도 성남시 분당구 정자동)
    tokens = (no_block or address).split()
    for i, t in enumerate(tokens):
        if i >= 2 and re.search(r"[동읍면로길가리]$", t) and not re.search(r"\d", t):
            q = " ".join(tokens[:i + 1])
            if q not in (x for x, _ in out):
                out.append((q, "동"))
            break
    return out


class Geocoder:
    def __init__(self, session, cache_path: Path):
        self.session = session
        self.cache_path = cache_path
        try:
            self.cache: dict = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}
        self.lookups = 0

    def _lookup(self, q: str):
        if q in self.cache:
            return self.cache[q]
        if self.lookups >= MAX_LOOKUPS:
            return None  # 오늘 몫을 다 써서 내일 다시 (캐시에 안 남김)
        self.lookups += 1
        time.sleep(1.1)  # Nominatim 이용 정책: 초당 1회
        try:
            resp = self.session.get(NOMINATIM, params={"q": q, "format": "json", "limit": 1, "countrycodes": "kr"},
                                    headers={"User-Agent": CONTACT_UA}, timeout=20)
            rows = resp.json() if resp.status_code == 200 else None
        except Exception as e:
            log.warning("좌표 찾기 실패(%s): %s", q, e)
            return None
        if rows is None:
            return None
        hit = [round(float(rows[0]["lat"]), 5), round(float(rows[0]["lon"]), 5)] if rows else False
        self.cache[q] = hit
        return hit

    def locate(self, item: dict) -> None:
        if item.get("geo"):
            return
        if item.get("address"):
            for q, precision in queries_for(item["address"]):
                hit = self._lookup(q)
                if hit:
                    item["geo"] = {"lat": hit[0], "lng": hit[1], "precision": precision}
                    return
        gu, region = item.get("gu"), item.get("region") or "서울"
        center = GU_CENTER.get(gu or "") if region == "서울" else None
        if center:
            item["geo"] = {"lat": center[0], "lng": center[1], "precision": "구"}
            return
        if gu:  # 경기·인천은 시·군·구 중심을 지도 검색으로 찾는다 (캐시되므로 한 번만)
            hit = self._lookup(f"{REGION_FULL.get(region, region)} {gu}")
            if hit:
                item["geo"] = {"lat": hit[0], "lng": hit[1], "precision": "구"}

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0), encoding="utf-8")
        log.info("좌표: 새로 찾은 %d건 (캐시 %d건)", self.lookups, len(self.cache))
