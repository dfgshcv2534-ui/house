"""조사용: 공공데이터포털 API 상세 페이지에서 요청주소·변수(스웨거)를 뽑아 로그로 남긴다."""
import json
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36", "Accept-Language": "ko-KR"}
PAGES = {"iH 공고문": "https://www.data.go.kr/data/15149725/openapi.do",
         "마이홈 모집공고": "https://www.data.go.kr/data/15108420/openapi.do"}
for name, url in PAGES.items():
    print("\n" + "=" * 80 + f"\n{name} {url}")
    try:
        r = requests.get(url, headers=UA, timeout=30)
    except Exception as e:
        print("실패", e); continue
    t = r.text
    print("HTTP", r.status_code, len(t))
    print("요청주소 후보:", sorted(set(re.findall(r"https?://apis\.data\.go\.kr/[\w/.-]+", t)))[:10])
    m = re.search(r"swaggerJson\s*=\s*`([\s\S]*?)`", t) or re.search(r"swaggerJson\s*=\s*'([\s\S]*?)';", t)
    if m:
        try:
            sj = json.loads(m.group(1))
            print("host", sj.get("host"), "basePath", sj.get("basePath"), "servers", sj.get("servers"))
            for path, ops in (sj.get("paths") or {}).items():
                for verb, op in ops.items():
                    print("PATH", verb.upper(), path, "|", op.get("summary"))
                    for p in op.get("parameters", []):
                        print("   param", p.get("name"), p.get("required"), (p.get("description") or "")[:60])
                    resp = (op.get("responses") or {}).get("200", {})
                    print("   resp", json.dumps(resp)[:600])
        except Exception as e:
            print("스웨거 파싱 실패", e, m.group(1)[:500])
    else:
        for k in ("End Point", "요청주소", "상세기능", "serviceKey"):
            for mm in list(re.finditer(k, t))[:3]:
                print(k, "…", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t[mm.start():mm.start() + 400]))[:300])
