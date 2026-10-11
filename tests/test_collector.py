from datetime import date

from collector import applyhome, build, sh
from collector.common import gu_in_text, is_seoul, seoul_gu, to_iso, to_month

SH_LIST = """<html><body>
<div class="topTxt"><p>총 <strong>95</strong> 건</p></div>
<div id="listTb" class="listTable"><table><tbody>
<tr><td>95</td><td class="txtL"><a href="#" onclick="javascript:getDetailView('304371');return false;"><span class="icoNew">NEW</span> 2026년 2차 행복주택 입주자 모집공고(2026.10.02.)</a></td><td>공공주택공급부</td><td class="num">2026-10-02</td><td class="num">872</td></tr>
<tr><td>94</td><td class="txtL"><a href="#" onclick="javascript:getDetailView('304346');return false;">행복주택 예비당첨자 게시</a></td><td>공공주택공급부</td><td class="num">2026-09-30</td><td class="num">1,210</td></tr>
<tr><td>93</td><td class="txtL"><a href="#" onclick="javascript:getDetailView('304300');return false;">강동구 고덕강일 청년 매입임대주택 입주자 모집 공고</a></td><td>매입임대부</td><td class="num">2026-09-28</td><td class="num">300</td></tr>
</tbody></table></div></body></html>"""

SH_DETAIL = """<html><body><div class="detailTable firgs0401Table"><table><tbody>
<tr><th scope="row">첨부</th><td>
<a href="#" class="btnAttach v1" onclick="existFile('0'); return false;">2026년 2차 행복주택 공고문.pdf</a>
</td></tr>
<tr><td colspan="2" class="cont">
<p>■ 공급규모 : 총 1,234호</p>
<p>■ 신청자격 : 공고일(2026.10.02) 현재 무주택세대구성원</p>
<p>■ 청약접수 기간 : 2026.10.14.(화) 10:00 ~ 10.16.(목) 17:00</p>
<p>■ 서류심사대상자 발표 : 2026.10.24.(금)</p>
<p>■ 당첨자 발표 : 2027. 2. 6.(금)</p>
<p>■ 입주예정 : 2027년 5월</p>
</td></tr></tbody></table></div></body></html>"""


def test_dates_and_addresses():
    assert to_iso("2026-10-01") == to_iso("20261001") == to_iso("2026.10.01") == "2026-10-01"
    assert to_iso("공고문 참조") is None
    assert to_month("202812") == "2028-12"
    assert is_seoul("서울", None) and is_seoul(None, "서울특별시 강동구") and not is_seoul("경기", "경기도 하남시")
    assert seoul_gu("서울특별시 강동구 고덕동 123") == "강동구"
    assert gu_in_text("중구 신당동 행복주택") == "중구"
    assert gu_in_text("강서구 마곡") == "강서구"
    assert gu_in_text("중랑구 면목동") == "중랑구"


def test_sh_list_and_filter():
    rows = sh.parse_list(SH_LIST)
    assert [r["seq"] for r in rows] == ["304371", "304346", "304300"]
    assert rows[0]["title"].startswith("2026년 2차 행복주택")
    assert rows[0]["date"] == "2026-10-02"
    picked = [r for r in rows if sh.is_recruitment(r["title"])]
    assert [r["seq"] for r in picked] == ["304371", "304300"]


def test_sh_classify():
    assert sh.classify("2026년 2차 행복주택 입주자 모집공고", "임대") == ("행복주택", "임대")
    assert sh.classify("장기전세주택(미리내집) 입주자 모집", "임대")[0] == "장기전세(미리내집)"
    assert sh.classify("마곡 토지임대부 분양주택 입주자 모집", "분양") == ("토지임대부 분양", "분양")
    assert sh.classify("청년 매입임대주택 모집", "임대")[0] == "매입임대"
    assert sh.targets_of("청년·신혼부부 매입임대") == ["청년", "신혼·신생아"]


def test_sh_detail_schedule():
    detail = sh.parse_detail(SH_DETAIL)
    assert detail["files"] == ["2026년 2차 행복주택 공고문.pdf"]
    sched = sh.extract_schedule(detail["text"], "2026-10-02")
    assert sched == {"start": "2026-10-14", "end": "2026-10-16", "winner": "2027-02-06", "moveIn": "2027-05"}
    assert sh.units_of(detail["text"]) == 1234


def test_sh_schedule_month_rollover_and_missing():
    assert sh.extract_schedule("신청기간: 2026.10.30 ~ 11.2", "2026-10-20") == {"start": "2026-10-30", "end": "2026-11-02"}
    assert sh.extract_schedule("세부 일정은 첨부 공고문을 확인하세요", "2026-10-20") == {}


def test_sh_to_notice():
    row = sh.parse_list(SH_LIST)[0]
    board = sh.BOARDS[1]
    n = sh.to_notice(row, board, sh.parse_detail(SH_DETAIL), "https://example/view")
    assert n["id"] == "sh:rent:304371"
    assert n["kind"] == "행복주택" and n["cat"] == "임대"
    assert n["name"] == "2026년 2차 행복주택 입주자 모집공고"
    assert n["dates"] == {"notice": "2026-10-02", "start": "2026-10-14", "end": "2026-10-16", "winner": "2027-02-06"}
    assert n["dateBasis"] == "본문"


APT_ROW = {
    "HOUSE_MANAGE_NO": "2026000512", "PBLANC_NO": "2026000512", "HOUSE_NM": "고덕강일 3단지",
    "HOUSE_DTL_SECD_NM": "국민", "RENT_SECD_NM": "분양주택", "SUBSCRPT_AREA_CODE_NM": "서울",
    "HSSPLY_ADRES": "서울특별시 강동구 강일동 123", "TOT_SUPLY_HSHLDCO": 590,
    "RCRIT_PBLANC_DE": "2026-10-02", "RCEPT_BGNDE": "2026-10-13", "RCEPT_ENDDE": "2026-10-16",
    "SPSPLY_RCEPT_BGNDE": "2026-10-13", "SPSPLY_RCEPT_ENDDE": "2026-10-13",
    "GNRL_RNK1_CRSPAREA_RCPTDE": "2026-10-14", "GNRL_RNK1_CRSPAREA_ENDDE": "2026-10-14",
    "PRZWNER_PRESNATN_DE": "2026-10-22", "MVN_PREARNGE_YM": "202812",
    "PARCPRC_ULS_AT": "Y", "SPECLT_RDN_EARTH_AT": "N", "PBLANC_URL": "https://www.applyhome.co.kr/x",
}
MODEL_ROWS = [
    {"HOUSE_MANAGE_NO": "2026000512", "HOUSE_TY": "059.9700A", "SUPLY_AR": "84.12", "SUPLY_HSHLDCO": "100", "SPSPLY_HSHLDCO": "150", "LTTOT_TOP_AMOUNT": "52,300"},
    {"HOUSE_MANAGE_NO": "2026000512", "HOUSE_TY": "084.9800", "SUPLY_AR": "112.5", "SUPLY_HSHLDCO": "140", "SPSPLY_HSHLDCO": "200", "LTTOT_TOP_AMOUNT": "71000"},
]


def test_applyhome_normalize():
    models = [applyhome.normalize_model(m) for m in MODEL_ROWS]
    assert models[0] == {"type": "59A", "area": 84.12, "excl": 59.0, "units": 100, "special": 150, "price": 52300}
    n = applyhome.normalize(APT_ROW, applyhome.SOURCES[0], models)
    assert n["cat"] == "분양" and n["kind"] == "아파트" and n["gu"] == "강동구"
    assert n["tags"] == ["공공분양", "분양가상한제"]
    assert n["priceMin"] == 52300 and n["priceMax"] == 71000
    assert n["dates"]["start"] == "2026-10-13" and n["dates"]["rank1_start"] == "2026-10-14"
    assert n["moveIn"] == "2028-12"


def test_merge_keeps_failed_source_and_first_seen():
    today = date(2026, 10, 11)
    previous = [
        {"id": "sh:rent:1", "source": "SH", "cat": "임대", "name": "a", "dates": {"notice": "2026-10-01"}, "firstSeen": "2026-10-01"},
        {"id": "ah:apt:9:9", "source": "청약홈", "cat": "분양", "name": "b", "dates": {"end": "2026-10-20"}, "firstSeen": "2026-10-05"},
    ]
    fresh_ah = [{"id": "ah:apt:9:9", "source": "청약홈", "cat": "분양", "name": "b", "dates": {"end": "2026-10-20"}},
                {"id": "ah:apt:8:8", "source": "청약홈", "cat": "분양", "name": "c", "dates": {"end": "2026-10-25"}}]
    results = {"청약홈": fresh_ah, "LH": []}
    status = {"청약홈": {"ok": True}, "SH": {"ok": False}, "LH": {"ok": True}}
    out = {n["id"]: n for n in build.merge(previous, results, status, today)}
    assert out["sh:rent:1"]["stale"] is True             # SH 실패 → 지난 데이터 유지
    assert out["ah:apt:9:9"]["firstSeen"] == "2026-10-05"  # 이미 본 공고
    assert out["ah:apt:8:8"]["firstSeen"] == "2026-10-11"  # 신규


def test_merge_drops_old_and_dedupes():
    today = date(2026, 10, 11)
    results = {
        "청약홈": [{"id": "ah:apt:1:1", "source": "청약홈", "cat": "분양", "name": "고덕강일 3단지", "dates": {"end": "2026-10-16"}}],
        "SH": [
            {"id": "sh:sale:5", "source": "SH", "cat": "분양", "name": "2026년 고덕강일 3단지 입주자 모집공고", "url": "u", "dates": {"notice": "2026-10-02"}},
            {"id": "sh:rent:6", "source": "SH", "cat": "임대", "name": "옛 공고", "dates": {"notice": "2026-01-02", "end": "2026-01-10"}},
        ],
        "LH": [],
    }
    status = {k: {"ok": True} for k in results}
    out = build.merge([], results, status, today)
    assert [n["id"] for n in out] == ["ah:apt:1:1"]
    assert out[0]["links"] == [{"label": "SH 공고", "url": "u"}]


def test_redact_hides_service_key():
    from collector.common import redact
    msg = "url: /x?serviceKey=abc%2Bdef%3D%3D&PG_SZ=100 (Caused by ProxyError('x'))"
    assert redact(msg) == "url: /x?serviceKey=***&PG_SZ=100 (Caused by ProxyError('x'))"


def test_sh_real_world_titles():
    assert sh.classify("[토지임대부 사회주택] 옥류서원 입주자 모집 공고문", "분양") == ("사회주택", "임대")
    assert not sh.is_recruitment("제51차 장기전세주택(2026.08.31.공고) 최종 청약접수 결과")
    assert not sh.is_recruitment("행복주택 청약접수 현황")
    row = {"seq": "1", "title": "2026년 신정도시마을 잔여세대 입주자모집공고(26. 9. 23.)", "date": "2026-10-08"}
    assert sh.to_notice(row, sh.BOARDS[1], None, "u")["name"] == "2026년 신정도시마을 잔여세대 입주자모집공고"


def test_sh_prefers_range_over_single_date():
    text = "신청자격: 공고일 현재 무주택 / 신청일 2026.09.30 기준 소득 / 청약 신청기간: 2026.10.13 ~ 10.15"
    assert sh.extract_schedule(text, "2026-09-30") == {"start": "2026-10-13", "end": "2026-10-15"}


def test_sh_drop_reposts_keeps_latest():
    a = {"name": "옥류서원 입주자 모집 공고문", "dates": {"notice": "2026-09-22"}}
    b = {"name": "옥류서원 입주자 모집 공고문", "dates": {"notice": "2026-10-07"}}
    c = {"name": "(수정) 옥류서원 입주자 모집 공고문", "dates": {"notice": "2026-10-01"}}
    assert sh.drop_reposts([a, b, c]) == [b]


def test_keep_uses_latest_schedule_date():
    item = {"dates": {"end": "2026-09-01", "contract_end": "2026-10-20"}}
    assert build.keep(item, date(2026, 10, 11))
