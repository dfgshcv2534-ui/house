"""조사용: 청약홈 공고의 분양 홈페이지를 실제 브라우저로 열어 평면도·팜플렛 단서를 찾는다."""
import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

KEY = re.compile(r"평면|타입|TYPE|unit|floor|plan|세대\s*안내|세대안내|카탈로그|catalog|e-?book|팜플렛|팸플릿|브로슈|brochure|리플렛", re.I)
notices = json.loads(Path("docs/data/notices.json").read_text(encoding="utf-8"))
targets = [n for n in notices if n["source"] == "청약홈" and n.get("homepage")]


async def scan(page, url):
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(1500)
    imgs = await page.eval_on_selector_all("img", "els => els.map(e => [e.currentSrc || e.src, e.alt || ''])")
    links = await page.eval_on_selector_all("a", "els => els.map(e => [(e.innerText||'').trim().slice(0,30), e.href])")
    return imgs, links


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(ignore_https_errors=True, locale="ko-KR")
        for n in targets:
            url = n["homepage"] if n["homepage"].startswith("http") else "http://" + n["homepage"]
            page = await ctx.new_page()
            print(f"\n=== {n['kind']} {n['name']} {url}")
            try:
                imgs, links = await scan(page, url)
            except Exception as e:
                print("  열기 실패:", str(e)[:120]); await page.close(); continue
            print("  이미지", len(imgs), "링크", len(links))
            print("  단서 이미지:", [i for i in imgs if KEY.search(" ".join(i))][:8])
            cand = [l for l in links if KEY.search(" ".join(l))]
            print("  단서 링크:", cand[:10])
            for text, href in cand[:2]:
                if not href.startswith("http") or href.lower().endswith(".pdf"):
                    continue
                try:
                    imgs2, _ = await scan(page, href)
                    print(f"  └ [{text}] {href} 이미지 {len(imgs2)}:", [i[0] for i in imgs2 if KEY.search(' '.join(i))][:8])
                except Exception as e:
                    print("  └ 실패", href, str(e)[:80])
            await page.close()
        await b.close()

asyncio.run(main())
