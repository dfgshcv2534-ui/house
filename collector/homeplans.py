"""민간 분양 홈페이지의 타입별 평면도 이미지 찾기 (청약홈 공고).

분양 홈페이지는 화면을 스크립트로 그리기 때문에 실제 브라우저(Playwright)로 연다.
첫 화면과 '세대안내/평면안내/타입안내' 같은 메뉴 페이지에서 평면도로 보이는 이미지를 모으고,
파일 이름의 타입(plan-81a → 81A)으로 주택형과 짝짓는다. 이미지는 복사하지 않고 원본 주소를 쓴다.
같은 홈페이지는 일주일에 한 번만 다시 연다 (docs/plans/homepages.json).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .common import kst_today, log

MENU_WORD = re.compile(r"평면|타입|세대\s*안내|주택형|unit|plan(?!ning)|plane|floor|type", re.I)
IMG_WORD = re.compile(r"plan|type|unit|floor|평면|타입", re.I)
IMG_SKIP = re.compile(r"site_?plan|siteplan|배치|logo|icon|btn|bg[_-]|kv|banner|map|location|community|thumb_?nav|arrow|sns", re.I)
RECHECK_DAYS = 7
MAX_MENU_PAGES = 3
MAX_SITES = 15  # 한 번 실행에서 새로 여는 홈페이지 수


def type_from_url(url: str) -> str | None:
    """'.../plan-81a.webp?v=1' → '81A', 'type-38-plan.png' → '38', 'unit_084B.jpg' → '84B'."""
    name = urlparse(url).path.rsplit("/", 1)[-1]
    name = re.sub(r"\.\w+$", "", name)
    for m in re.finditer(r"(?<!\d)0*(\d{2,3})(?:\.\d+)?([A-Za-z])?(?![\dA-Za-z])", name):
        num = int(m.group(1))
        if 10 <= num <= 300:
            return f"{num}{(m.group(2) or '').upper()}"
    return None


def is_plan_image(url: str, alt: str = "") -> bool:
    text = f"{url} {alt}"
    return bool(IMG_WORD.search(text)) and not IMG_SKIP.search(text) and bool(re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.I))


def match_type(img_type: str | None, model_type: str | None) -> bool:
    if not img_type or not model_type:
        return False
    a, b = re.match(r"(\d+)([A-Z]?)", img_type), re.match(r"(\d+)([A-Za-z]?)", model_type)
    if not a or not b or a.group(1) != b.group(1).lstrip("0"):
        return False
    return not a.group(2) or not b.group(2) or a.group(2) == b.group(2).upper()


def _menu_links(page) -> list[str]:
    links = page.eval_on_selector_all("a[href]", "els => els.map(e => [(e.innerText||'').trim().slice(0,40), e.href])")
    out = []
    for text, href in links:
        if not href.startswith("http") or re.search(r"\.(pdf|hwp|zip)(\?|$)", href, re.I):
            continue
        if MENU_WORD.search(text) or MENU_WORD.search(urlparse(href).path):
            if href not in out:
                out.append(href)
    return out[:MAX_MENU_PAGES]


def _images(page) -> list[tuple[str, str]]:
    return page.eval_on_selector_all("img", "els => els.map(e => [e.currentSrc || e.src, e.alt || ''])")


def crawl(browser, homepage: str) -> list[dict]:
    ctx = browser.new_context(ignore_https_errors=True, locale="ko-KR")
    page = ctx.new_page()
    found: dict[str, dict] = {}
    try:
        page.goto(homepage, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2500)
        pages = [homepage] + _menu_links(page)
        for i, url in enumerate(pages):
            if i:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2500)
            for src, alt in _images(page):
                if src and is_plan_image(src, alt) and src not in found:
                    kind = "입체" if re.search(r"iso|3d", src, re.I) else "평면"
                    found[src] = {"url": src, "type": type_from_url(src), "kind": kind, "alt": alt[:40]}
    except Exception as e:
        log.info("분양 홈페이지 평면도 찾기 실패(%s): %s", homepage, str(e)[:120])
    finally:
        ctx.close()
    return list(found.values())[:24]


def attach(notices: list[dict], docs_dir: Path) -> None:
    targets = [n for n in notices if n.get("source") == "청약홈" and n.get("homepage")]
    if not targets:
        return
    index_path = docs_dir / "plans" / "homepages.json"
    try:
        index: dict = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    today = kst_today()
    recent = (today - timedelta(days=30)).isoformat()

    def url_of(n):
        h = n["homepage"].strip()
        return h if h.startswith("http") else "http://" + h

    todo = []
    for n in targets:
        entry = index.get(url_of(n))
        stale = not entry or date.fromisoformat(entry["checked"]) < today - timedelta(days=RECHECK_DAYS)
        if stale and max(n.get("dates", {}).values(), default="") >= recent:
            todo.append(url_of(n))
    todo = list(dict.fromkeys(todo))[:MAX_SITES]

    if todo:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.warning("playwright 가 없어 분양 홈페이지 평면도 찾기를 건너뜁니다")
            todo = []
        if todo:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                for url in todo:
                    plans = crawl(browser, url)
                    index[url] = {"checked": today.isoformat(), "plans": plans}
                    log.info("분양 홈페이지 평면도: %s → %d장", url, len(plans))
                browser.close()

    live = {url_of(n) for n in targets}
    for url in [u for u in index if u not in live]:
        index.pop(url)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    for n in targets:
        plans = (index.get(url_of(n)) or {}).get("plans") or []
        if not plans:
            continue
        n["homePlans"] = plans
        for m in n.get("models", []):
            if m.get("plan"):
                continue
            hit = next((p for p in plans if p["kind"] == "평면" and match_type(p["type"], m.get("type"))), None)
            if hit:
                m["plan"] = hit["url"]
