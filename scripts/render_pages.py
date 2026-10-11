"""조사용: 지정한 공고문 PDF 페이지를 이미지로 뽑아 probe/ 에 저장."""
import json
from pathlib import Path

import pymupdf
import requests

TARGETS = {"ah:remndr:2026910251:2026910251": [4, 7], "ah:remndr:2026930040:2026930040": [5, 10]}
notices = {n["id"]: n for n in json.loads(Path("docs/data/notices.json").read_text(encoding="utf-8"))}
out = Path("probe"); out.mkdir(exist_ok=True)
for id_, pages in TARGETS.items():
    n = notices[id_]
    data = requests.get(n["files"][0]["url"], timeout=40, headers={"User-Agent": "Mozilla/5.0"}).content
    doc = pymupdf.open(stream=data, filetype="pdf")
    for p in pages:
        page = doc[p - 1]
        text = page.get_text()
        print(n["name"], p, "글자", len(text), "선", len(page.get_drawings()), "이미지", len(page.get_images()), "|", text[:150].replace("\n", " "))
        page.get_pixmap(dpi=80).save(str(out / f"{id_.split(':')[2]}-p{p}.jpg"), jpg_quality=70)
