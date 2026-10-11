"""청약홈 공고 상세 페이지·분양 홈페이지에 평면도가 있는지 살펴보는 일회성 조사 스크립트.

GitHub Actions 의 '평면도 조사' 워크플로에서 수동으로 실행한다. 결과는 로그로만 남긴다.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (compatible; seoul-house-board/1.0)"}
notices = json.loads(Path("docs/data/notices.json").read_text(encoding="utf-8"))
targets = [n for n in notices if n["source"] == "청약홈" and n.get("url")][:3]


def probe(label, url):
    print(f"\n=== {label}: {url}")
    try:
        r = requests.get(url, headers=UA, timeout=20)
    except Exception as e:
        print("  요청 실패:", e)
        return None
    print("  HTTP", r.status_code, "길이", len(r.text), "최종주소", r.url)
    soup = BeautifulSoup(r.text, "html.parser")
    print("  제목:", (soup.title.get_text(strip=True) if soup.title else "")[:80])
    imgs = [urljoin(r.url, i.get("src") or "") for i in soup.find_all("img")]
    print("  이미지", len(imgs), "개; 평면/plan 관련:", [i for i in imgs if re.search(r"평면|plan|floor|unit|type", i, re.I)][:10])
    links = [(a.get_text(" ", strip=True)[:30], urljoin(r.url, a.get("href") or "")) for a in soup.find_all("a")]
    print("  평면 관련 링크:", [l for l in links if re.search(r"평면|plan|floor|타입|주택형", l[0] + l[1], re.I)][:10])
    print("  PDF/첨부 링크:", [l for l in links if re.search(r"\.pdf|download|fileDown|atch", l[1], re.I)][:10])
    onclicks = [a.get("onclick") for a in soup.find_all(onclick=True)]
    print("  onclick 샘플:", [o for o in onclicks if re.search(r"평면|plan|pdf|down|file", o or "", re.I)][:10])
    text = soup.get_text(" ", strip=True)
    for m in list(re.finditer(r"평면", text))[:5]:
        print("  …", text[max(0, m.start() - 60): m.end() + 60])
    return r


for n in targets:
    probe(f"청약홈 상세 [{n['name']}]", n["url"])
    if n.get("homepage"):
        probe(f"분양 홈페이지 [{n['name']}]", n["homepage"] if n["homepage"].startswith("http") else "http://" + n["homepage"])
sys.exit(0)
