"""청약홈 모집공고문 PDF 안에 평면도 페이지가 있는지 살펴보는 일회성 조사 (수동 워크플로에서 실행)."""
import io
import json
import re
from pathlib import Path

import fitz  # pymupdf
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; seoul-house-board/1.0)"}
notices = json.loads(Path("docs/data/notices.json").read_text(encoding="utf-8"))
for n in [n for n in notices if n["source"] == "청약홈" and n.get("files")][:12]:
    url = n["files"][0]["url"]
    try:
        r = requests.get(url, headers=UA, timeout=40)
        doc = fitz.open(stream=io.BytesIO(r.content), filetype="pdf")
    except Exception as e:
        print(f"[{n['name']}] 열기 실패: {e} (HTTP {getattr(r, 'status_code', '?')}, {r.headers.get('content-type') if 'r' in dir() else ''})")
        continue
    hits = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if re.search(r"평\s*면\s*도|단위\s*세대", text):
            hits.append((i + 1, len(page.get_images()), len(page.get_drawings()), text.count("㎡")))
    types = [m.get("type") for m in n.get("models", [])]
    print(f"[{n['kind']}] {n['name']} | {len(r.content)//1024}KB {doc.page_count}쪽 | 타입 {types} | 평면 언급 쪽(쪽,이미지,도형,㎡): {hits[:8]}")
