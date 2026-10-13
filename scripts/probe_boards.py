"""조사용: GH·iH 공고 게시판 목록 행 구조를 짧게 로그로 남긴다."""
import re
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36", "Accept-Language": "ko-KR"}
URLS = [
    "https://www.gh.or.kr/gh/announcement-of-salerental001.do",
    "https://apply.gh.or.kr/sb/sr/sr7150/selectPbancRentHouseList.do",
    "https://www.ih.co.kr/main/sale_lease/notice.jsp",
    "https://www.ih.co.kr/main/sale_lease/board/house_notice.jsp",
]
for url in URLS:
    print("\n" + "=" * 80 + "\n" + url)
    try:
        r = requests.get(url, headers=UA, timeout=25)
    except Exception as e:
        print("실패", e); continue
    print("HTTP", r.status_code, "최종", r.url, "길이", len(r.text))
    soup = BeautifulSoup(r.text, "html.parser")
    rows = [tr for tr in soup.select("tbody tr") if tr.find("a")]
    if not rows:
        rows = [li for li in soup.select("ul li") if li.find("a") and re.search(r"모집|공고", li.get_text())]
    print("목록 행 수", len(rows))
    if rows:
        print("첫 행 HTML:", re.sub(r"\s+", " ", str(rows[0]))[:1200])
    for tr in rows[:8]:
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True))[:50] for td in tr.find_all(["td", "th", "span", "p"], recursive=True)][:8]
        a = tr.find("a")
        print("ROW:", cells, "| href:", (a.get("href") or "")[:150], "| onclick:", (a.get("onclick") or "")[:120])
    pg = soup.select_one(".paging, .pagination, .board_paging, .page")
    if pg:
        print("페이징 HTML:", re.sub(r"\s+", " ", str(pg))[:600])
    print("전체 건수 단서:", re.findall(r"(?:총|전체)\s*<?[^>]{0,30}>?\s*[\d,]+\s*건", r.text)[:3])
