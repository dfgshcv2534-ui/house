"""조사용: GitHub 서버에서 iH 사이트의 여러 주소로 접속되는지 확인."""
import socket
import time
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"}
for host in ["www.ih.co.kr", "ih.co.kr", "m.ih.co.kr", "land.ih.co.kr", "landmap.ih.co.kr"]:
    try:
        print(host, "DNS", sorted({a[4][0] for a in socket.getaddrinfo(host, 443)}))
    except Exception as e:
        print(host, "DNS 실패", e)
for url in ["https://www.ih.co.kr/main/sale_lease/board/house_notice.jsp", "http://www.ih.co.kr/main/sale_lease/board/house_notice.jsp",
            "https://ih.co.kr/", "http://ih.co.kr/", "https://m.ih.co.kr/", "http://m.ih.co.kr/", "https://land.ih.co.kr/intro.jsp",
            "https://www.ih.co.kr/main/bbs/bbsMsgList.do?cate1=a&bcd=sale_lease&pgno=1"]:
    t = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
        print(f"OK  {url} → {r.status_code} {r.url} {len(r.text)}B {time.time()-t:.1f}s")
    except Exception as e:
        print(f"ERR {url} {type(e).__name__} {time.time()-t:.1f}s")
