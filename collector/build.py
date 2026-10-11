"""모든 출처를 모아 docs/data/notices.json 과 meta.json 을 만든다.

- 한 출처가 실패하면 그 출처의 지난 데이터를 그대로 유지한다 (사이트가 갑자기 비지 않게).
- 처음 보는 공고에는 firstSeen 을 오늘로 찍어 '신규' 표시에 쓴다.
- 청약홈과 SH·LH에 같은 분양 공고가 있으면 청약홈 쪽만 남긴다.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from . import applyhome, lh, sh
from .common import SourceError, api_key, kst_now, kst_today, log, make_session

DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"
KEEP_AFTER_END_DAYS = 14
KEEP_UNDATED_DAYS = 60
ID_PREFIX = {"청약홈": "ah:", "SH": "sh:", "LH": "lh:"}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _norm_name(text: str | None) -> str:
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text or "")
    text = re.sub(r"\d{4}년|제?\d+차|입주자|모집|공고|분양|정정|변경|주택|아파트|\s", "", text)
    return text


def dedupe(items: list[dict]) -> list[dict]:
    """SH·LH 분양 공고 중 청약홈 단지명과 겹치는 것은 청약홈 항목의 '다른 공고 링크'로 합친다."""
    ah = [i for i in items if i["source"] == "청약홈"]
    keys = [(i, _norm_name(i["name"])) for i in ah]
    out = []
    for item in items:
        if item["source"] != "청약홈" and item["cat"] == "분양":
            mine = _norm_name(item["name"])
            match = next((a for a, k in keys if len(k) >= 4 and k in mine), None)
            if match:
                match.setdefault("links", []).append({"label": f"{item['source']} 공고", "url": item.get("url")})
                continue
        out.append(item)
    return out


def keep(item: dict, today: date) -> bool:
    d = item.get("dates", {})
    end = d.get("end") or d.get("winner")
    if end:
        return end >= (today - timedelta(days=KEEP_AFTER_END_DAYS)).isoformat()
    notice = d.get("notice")
    return bool(notice) and notice >= (today - timedelta(days=KEEP_UNDATED_DAYS)).isoformat()


def run_sources(session, key) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    results: dict[str, list[dict]] = {}
    status: dict[str, dict] = {}
    jobs = {
        "청약홈": lambda: applyhome.collect(session, key),
        "SH": lambda: sh.collect(session),
        "LH": lambda: lh.collect(session, key),
    }
    for name, job in jobs.items():
        try:
            items, failed_parts = job()
            results[name] = items
            status[name] = {"ok": not failed_parts, "count": len(items), "failedParts": failed_parts}
        except SourceError as e:
            log.error("%s 건너뜀: %s", name, e)
            status[name] = {"ok": False, "count": 0, "message": str(e)}
        except Exception as e:  # 예상 못 한 오류도 다른 출처는 살린다
            log.exception("%s 수집 중 오류", name)
            status[name] = {"ok": False, "count": 0, "message": f"{type(e).__name__}: {e}"}
    return results, status


def _part_of(item_id: str) -> str:
    parts = item_id.split(":")
    return parts[1] if len(parts) > 2 else parts[-1]


def merge(previous: list[dict], results: dict[str, list[dict]], status: dict[str, dict], today: date) -> list[dict]:
    prev_by_id = {p["id"]: p for p in previous}
    merged: list[dict] = []
    for name, prefix in ID_PREFIX.items():
        fresh = results.get(name)
        old = [p for p in previous if p["id"].startswith(prefix)]
        if fresh is None:  # 출처 전체 실패 → 지난 데이터 유지
            merged.extend(dict(p, stale=True) for p in old)
            continue
        merged.extend(fresh)
        failed_parts = set(status.get(name, {}).get("failedParts") or [])
        fresh_ids = {f["id"] for f in fresh}
        merged.extend(dict(p, stale=True) for p in old if p["id"] not in fresh_ids and _part_of(p["id"]) in failed_parts)
    for item in merged:
        item["firstSeen"] = prev_by_id.get(item["id"], {}).get("firstSeen") or today.isoformat()
    merged = [i for i in dedupe(merged) if keep(i, today)]
    merged.sort(key=lambda i: (i.get("dates", {}).get("notice") or "", i["id"]), reverse=True)
    return merged


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="서울 공공주택 공고 수집")
    parser.add_argument("--out", type=Path, default=DATA_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    today = kst_today()
    notices_path = args.out / "notices.json"
    previous = load_json(notices_path, [])
    results, status = run_sources(make_session(), api_key())

    if not results:
        log.error("모든 출처 수집 실패 — 기존 데이터를 그대로 둡니다")
        for name, st in status.items():
            print(f"::error::{name}: {st.get('message', '실패')}")
        return 1

    notices = merge(previous, results, status, today)
    prev_ids = {p["id"] for p in previous}
    new_count = sum(1 for n in notices if n["id"] not in prev_ids)
    meta = {
        "updatedAt": kst_now().isoformat(timespec="minutes"),
        "baseDate": today.isoformat(),
        "sources": status,
        "total": len(notices),
        "newToday": new_count,
    }
    write_json(notices_path, notices)
    write_json(args.out / "meta.json", meta)

    for name, st in status.items():
        if not st["ok"]:
            print(f"::warning::{name} 수집 문제: {st.get('message') or '일부 실패 ' + str(st.get('failedParts'))}")
    log.info("저장 완료: %d건 (신규 %d) → %s", len(notices), new_count, notices_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
