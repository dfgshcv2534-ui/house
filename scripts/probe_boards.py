"""조사용: GH·iH 공고 게시판의 HTML 구조를 로그로 남긴다."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36", "Accept-Language": "ko-KR"}
URLS = [
    "https://www.gh.or.kr/gh/announcement-of-salerental001.do",
    "https://apply.gh.or.kr/sb/sr/sr7150/selectPbancRentHouseList.do",
    "https://apply.gh.or.kr/sb/sr/sr7155/selectPbancRentHouseList.do",
    "https://www.ih.co.kr/main/sale_lease/notice.jsp",
    "https://www.ih.co.kr/main/sale_lease/board/arrival_notice.jsp",
    "https://www.ih.co.kr/main/",
]
for url in URLS:
    print("\n" + "=" * 100 + "\n" + url)
    try:
        r = requests.get(url, headers=UA, timeout=25)
    except Exception as e:
        print("실패", e); continue
    r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
    print("HTTP", r.status_code, "최종", r.url, "길이", len(r.text), "인코딩", r.encoding)
    soup = BeautifulSoup(r.text, "html.parser")
    print("제목", soup.title.get_text(strip=True) if soup.title else "")
    for f in soup.find_all("form")[:3]:
        print("FORM", f.get("action"), f.get("method"), [(i.get("name"), i.get("value")) for i in f.find_all("input")][:12])
    rows = soup.select("tbody tr") or soup.select("ul li")
    print("행 수", len(rows))
    for tr in rows[:6]:
        print("ROW:", re.sub(r"\s+", " ", tr.get_text(" ", strip=True))[:160])
        for a in tr.find_all("a")[:2]:
            print("   A href=", (a.get("href") or "")[:140], "onclick=", (a.get("onclick") or "")[:140])
    for a in soup.find_all("a"):
        t = a.get_text(" ", strip=True)
        if re.search(r"분양|임대|모집|공고", t) and len(t) < 30:
            print("MENU", t, "|", (a.get("href") or "")[:120])
    print("페이지 단서", re.findall(r"(?:pageIndex|page|pageNo|cpage|curPage)=\d+", r.text)[:5], re.findall(r"fn_\w+|goPage\w*|linkPage\w*", r.text)[:8])
