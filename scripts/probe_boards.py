"""조사용: GH 상세 이동 방식과 iH bbsMsgList 행 구조."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36", "Accept-Language": "ko-KR"}
# GH: 목록 페이지의 스크립트에서 상세 이동 함수와 페이지 이동 파라미터 찾기
for url in ["https://apply.gh.or.kr/sb/sr/sr7150/selectPbancRentHouseList.do", "https://apply.gh.or.kr/sb/sr/sr7155/selectPbancRentHouseList.do"]:
    r = requests.get(url, headers=UA, timeout=25)
    print("\n=== GH", url, r.status_code, len(r.text))
    for m in re.finditer(r".{0,200}(?:pbancNo|pbancno|Detail|pageIndex|currPage|pageNo).{0,200}", r.text):
        s = re.sub(r"\s+", " ", m.group(0))
        if "data-pbancno=" in s and "<a" in s:
            continue
        print("JS:", s[:400])
    soup = BeautifulSoup(r.text, "html.parser")
    for f in soup.find_all("form"):
        print("FORM", f.get("id"), f.get("action"), [(i.get("name"), i.get("value")) for i in f.find_all("input")][:15])
    rows = soup.select("tbody tr")
    print("행", len(rows), [re.sub(r"\s+", " ", rows[-1].get_text(" ", strip=True))[:120]] if rows else "")
# iH: 목록 본문
for url in ["https://www.ih.co.kr/main/bbs/bbsMsgList.do?cate1=a&bcd=sale_lease&pgno=1",
            "https://www.ih.co.kr/main/bbs/bbsMsgList.do?cate1=general&bcd=notice&pgdiv=general&pgno=1"]:
    r = requests.get(url, headers=UA, timeout=25)
    print("\n=== iH", url, r.status_code, len(r.text))
    soup = BeautifulSoup(r.text, "html.parser")
    rows = [tr for tr in soup.select("tbody tr") if tr.find("a")]
    if not rows:
        rows = [li for li in soup.select("li") if li.find("a", href=re.compile("bbsMsgDetail"))]
    print("행 수", len(rows))
    if rows:
        print("첫 행 HTML:", re.sub(r"\s+", " ", str(rows[0]))[:1000])
    for tr in rows[:10]:
        a = tr.find("a", href=re.compile("bbsMsgDetail")) or tr.find("a")
        print("ROW:", re.sub(r"\s+", " ", tr.get_text(" | ", strip=True))[:170], "| href:", (a.get("href") or "")[:130])
    # 상세 하나 열어 본문·첨부 구조
    if rows:
        a = rows[0].find("a", href=re.compile("bbsMsgDetail"))
        if a:
            d = requests.get("https://www.ih.co.kr" + a["href"] if a["href"].startswith("/") else a["href"], headers=UA, timeout=25)
            ds = BeautifulSoup(d.text, "html.parser")
            body = ds.select_one(".board_view, .view_cont, .bbs_view, .view, #contents")
            print("상세", d.status_code, "본문 클래스 후보", [c.get("class") for c in ds.select("div[class*=view]")][:6])
            print("상세 본문 앞부분:", re.sub(r"\s+", " ", (body or ds).get_text(" ", strip=True))[:500])
            print("첨부:", [(x.get_text(strip=True)[:40], (x.get("href") or "")[:100]) for x in ds.find_all("a", href=re.compile("FileDown|download|fileDown", re.I))][:6])
