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
    assert sh.classify("마곡 토지임대부 분양주택 입주자 모집", "분양") == ("토지임대부 분양", "특수형")
    assert sh.classify("청년 매입임대주택 모집", "임대")[0] == "매입임대"
    assert sh.targets_of("청년·신혼부부 매입임대") == ["청년", "신혼·신생아"]


def test_sh_detail_schedule():
    detail = sh.parse_detail(SH_DETAIL)
    assert detail["files"] == [{"name": "2026년 2차 행복주택 공고문.pdf"}]
    with_preview = sh.parse_detail(SH_DETAIL.replace("</td></tr>\n<tr><td colspan=\"2\" class=\"cont\">",
        '<a href="/app/com/util/htmlConverter.do?brd_id=GS0401&amp;seq=1&amp;file_seq=1">미리보기</a></td></tr>\n<tr><td colspan="2" class="cont">', 1))
    assert with_preview["files"] == [{"name": "2026년 2차 행복주택 공고문.pdf",
                                      "url": "https://www.i-sh.co.kr/app/com/util/htmlConverter.do?brd_id=GS0401&seq=1&file_seq=1"}]
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
    assert n["tags"] == ["분양가상한제"] and n["sector"] == "공공"
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
    from collector.common import drop_reposts
    assert drop_reposts([a, b, c]) == [b]


def test_keep_uses_latest_schedule_date():
    item = {"dates": {"end": "2026-09-01", "contract_end": "2026-10-20"}}
    assert build.keep(item, date(2026, 10, 11))


def test_special_kinds():
    from collector.common import special_kind
    assert special_kind("마곡 토지임대부 분양주택") == "토지임대부 분양"
    assert special_kind("[토지임대부 사회주택] 옥류서원") is None
    assert special_kind("서울형 지분적립형 분양주택 입주자 모집") == "지분적립형 분양"
    assert special_kind("뉴홈 나눔형 사전청약") == "나눔형(이익공유)"
    assert special_kind("분양전환 가능임대") == "분양전환 임대"
    assert special_kind("10년 공공임대주택 입주자 모집") == "분양전환 임대"
    assert special_kind("공공임대(10년)") == "분양전환 임대"
    assert special_kind("분양전환 불가임대") is None
    assert special_kind("행복주택 입주자 모집") is None
    assert sh.classify("[토지임대부 사회주택] 옥류서원 입주자 모집 공고문", "분양") == ("사회주택", "임대")
    assert sh.classify("10년 공공임대주택 입주자 모집공고", "임대") == ("분양전환 임대", "특수형")
    assert not sh.is_recruitment("○○단지 분양전환 가격 안내")


def test_applyhome_conversion_rental_is_special():
    row = dict(APT_ROW, RENT_SECD_NM="분양전환 가능임대", HOUSE_DTL_SECD_NM="국민")
    n = applyhome.normalize(row, applyhome.SOURCES[0], [])
    assert (n["cat"], n["kind"]) == ("특수형", "분양전환 임대")
    row = dict(APT_ROW, RENT_SECD_NM="분양전환 불가임대")
    assert applyhome.normalize(row, applyhome.SOURCES[0], [])["cat"] == "임대"


def test_lh_detail_fills_schedule_and_address():
    from collector import lh
    item = lh.normalize({"PAN_ID": "2026000123", "PAN_NM": "서울강남 행복주택 입주자 모집", "AIS_TP_CD_NM": "행복주택",
                         "PAN_NT_ST_DT": "2026.10.01", "CLSG_DT": "2026.10.17", "PAN_SS": "공고중", "DTL_URL": "https://apply.lh.or.kr/x"}, "임대")
    assert (item["cat"], item["kind"], item["gu"]) == ("임대", "행복주택", "강남구")
    body = [
        {"resHeader": [{"SS_CODE": "Y"}]},
        {"dsSbd": [{"LCT_ARA_ADR": "서울특별시 강남구 세곡동 100", "LCT_ARA_DTL_ADR": "A1블록", "MVIN_XPC_YM": "202803", "SUM_TOT_HSH_CNT": "350"}]},
        {"dsSplScdl": [
            {"HS_SBSC_ACP_TRG_CD_NM": "청년", "ACP_DTTM": "2026.10.14 10:00 ~ 2026.10.16 17:00", "PZWR_ANC_DT": "20261224", "CTRT_ST_DT": "20270210", "CTRT_ED_DT": "20270212"},
            {"HS_SBSC_ACP_TRG_CD_NM": "고령자", "ACP_DTTM": "2026.10.15 10:00 ~ 2026.10.17 17:00", "PZWR_ANC_DT": "20261224"},
        ]},
        {"dsAhflInfo": [{"CMN_AHFL_NM": "공고문.pdf", "AHFL_URL": "https://apply.lh.or.kr/f"}, {"CMN_AHFL_NM": "다운로드", "AHFL_URL": "x"}]},
    ]
    lh.apply_detail(item, body)
    assert item["address"] == "서울특별시 강남구 세곡동 100 A1블록" and item["gu"] == "강남구"
    assert item["dates"] == {"notice": "2026-10-01", "start": "2026-10-14", "end": "2026-10-17", "winner": "2026-12-24",
                             "contract_start": "2027-02-10", "contract_end": "2027-02-12"}
    assert item["moveIn"] == "2028-03" and item["units"] == 350
    assert item["files"] == [{"name": "공고문.pdf", "url": "https://apply.lh.or.kr/f"}]
    assert "statusHint" not in item


def test_lh_preorder_slot_is_skipped_until_configured():
    import pytest
    from collector import lh
    from collector.common import SourceError
    with pytest.raises(SourceError, match="요청주소"):
        lh._collect(None, "key", list_url="", dtl_url="", spl_url="", pre=True)


def test_lh_preorder_list_filters_capital_region():
    from collector import lh

    class Resp:
        status_code = 200
        def __init__(self, body): self._b = body
        def json(self): return self._b

    class Session:
        def __init__(self): self.params = []
        def get(self, url, params=None, timeout=None):
            self.params.append(params)
            return Resp([{"resHeader": [{"SS_CODE": "Y"}]}, {"dsList": [
                {"PAN_ID": "A1", "PAN_NM": "서울대방 신혼희망타운 사전청약", "CNP_CD_NM": "서울특별시", "UPP_AIS_TP_NM": "신혼희망타운", "PAN_NT_ST_DT": "2026.09.01"},
                {"PAN_ID": "A2", "PAN_NM": "남양주왕숙 공공분양 사전청약", "CNP_CD_NM": "경기도", "UPP_AIS_TP_NM": "분양주택"},
                {"PAN_ID": "A3", "PAN_NM": "부산에코델타 공공분양 사전청약", "CNP_CD_NM": "부산광역시", "UPP_AIS_TP_NM": "분양주택"},
            ]}])

    sess = Session()
    items, failed = lh._collect(sess, "key", list_url="u", dtl_url="", spl_url="", pre=True)
    assert [(i["id"], i["cat"], i["tags"], i["region"]) for i in items] == [
        ("lhp:A1", "분양", ["사전청약"], "서울"), ("lhp:A2", "분양", ["사전청약"], "경기")]
    assert items[1]["gu"] == "남양주시"
    assert set(sess.params[0]) == {"serviceKey", "PG_SZ", "PAGE", "PAN_ST_DT", "PAN_ED_DT"}
    assert len(sess.params[0]["PAN_ST_DT"]) == 8


def test_lh_real_world_cleanup():
    from collector import lh
    from collector.common import drop_reposts, gu_in_text, special_kind
    a = lh.normalize({"PAN_ID": "1", "PAN_NM": "강서염창 통합공공임대주택 최초 입주자 모집공고", "AIS_TP_CD_NM": "통합공공임대",
                      "PAN_NT_ST_DT": "2026.09.17", "ALL_CNT": "4"}, "임대")
    b = lh.normalize({"PAN_ID": "2", "PAN_NM": "[정정공고][정정공고] 강서염창 통합공공임대주택 최초 입주자 모집공고", "AIS_TP_CD_NM": "통합공공임대",
                      "PAN_NT_ST_DT": "2026.09.21", "ALL_CNT": "4"}, "임대")
    assert a["units"] is None and a["gu"] == "강서구"
    assert b["name"] == a["name"] and b["tags"] == ["정정공고"]
    assert [i["id"] for i in drop_reposts([a, b])] == ["lh:2"]
    c = lh.normalize({"PAN_ID": "3", "PAN_NM": "[서울지역본부] 26년 2차 비분양전환형 든든전세주택 입주자 모집공고", "AIS_TP_CD_NM": "매입임대",
                      "PAN_NT_ST_DT": "2026.10.01"}, "임대")
    assert c["name"] == "26년 2차 비분양전환형 든든전세주택 입주자 모집공고" and c["cat"] == "임대"
    assert special_kind("비분양전환형 든든전세주택 공공임대") is None
    assert gu_in_text("서울번동3 행복주택") is None
    assert gu_in_text("서울강남 행복주택") == "강남구"
    assert gu_in_text("입구로 이동") is None


def test_lh_detail_hides_past_move_in():
    from collector import lh
    item = lh.normalize({"PAN_ID": "9", "PAN_NM": "서울번동3 행복주택 예비입주자 모집", "AIS_TP_CD_NM": "행복주택", "PAN_NT_ST_DT": "2026.08.19"}, "임대")
    lh.apply_detail(item, [{"dsSbd": [{"LGDN_ADR": "서울특별시 강북구 번동 1", "MVIN_XPC_YM": "202304"}]}])
    assert item["moveIn"] is None and item["gu"] == "강북구"


def test_sector():
    from collector.common import sector_of
    assert sector_of("국민", None) == "공공"
    assert sector_of("민영", "서울주택도시공사") == "민간"
    assert sector_of(None, "서울주택도시개발공사") == "공공"
    assert sector_of(None, "(주)○○개발") == "민간"


def test_lh_supply_and_floor_plans():
    from collector import lh
    item = lh.normalize({"PAN_ID": "5", "PAN_NM": "강서염창 통합공공임대주택 모집", "AIS_TP_CD_NM": "통합공공임대", "PAN_NT_ST_DT": "2026.09.17"}, "임대")
    lh.apply_detail(item, [{"dsSbdAhfl": [
        {"SL_PAN_AHFL_DS_CD_NM": "평면도", "CMN_AHFL_NM": "26A형 평면도.jpg", "AHFL_URL": "https://apply.lh.or.kr/p26a"},
        {"SL_PAN_AHFL_DS_CD_NM": "평면도", "CMN_AHFL_NM": "36㎡.png", "AHFL_URL": "https://apply.lh.or.kr/p36"},
        {"SL_PAN_AHFL_DS_CD_NM": "조감도", "CMN_AHFL_NM": "조감도.jpg", "AHFL_URL": "https://apply.lh.or.kr/bird"},
        {"SL_PAN_AHFL_DS_CD_NM": "기타", "CMN_AHFL_NM": "다운로드", "AHFL_URL": "x"},
    ]}])
    lh.apply_supply(item, [{"dsList01": [
        {"HTY_NNA": "26A", "SPL_AR": "45.1", "HSH_CNT": "120"},
        {"HTY_NNA": "36", "SPL_AR": "60.2", "HSH_CNT": "80"},
        {"HTY_NNA": "46B", "SPL_AR": "70.0", "HSH_CNT": "10"},
    ]}])
    lh.attach_plans(item)
    assert item["units"] == 210
    assert [im["label"] for im in item["images"]] == ["평면도", "평면도", "조감도"]
    plans = {m["type"]: m.get("plan") for m in item["models"]}
    assert plans == {"26A": "https://apply.lh.or.kr/p26a", "36": "https://apply.lh.or.kr/p36", "46B": None}


def test_geocoder_queries_and_fallback(tmp_path, monkeypatch):
    from collector.geo import Geocoder, queries_for

    assert queries_for("서울특별시 강남구 세곡동 100 A1블록") == [
        ("서울특별시 강남구 세곡동 100 A1블록", "주소"), ("서울특별시 강남구 세곡동 100", "주소"), ("서울특별시 강남구 세곡동", "동")]

    class Resp:
        def __init__(self, rows): self.status_code, self._rows = 200, rows
        def json(self): return self._rows

    class Session:
        def __init__(self): self.calls = []
        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append(params["q"])
            return Resp([{"lat": "37.47", "lon": "127.10"}] if params["q"].endswith("세곡동") else [])

    import collector.geo as geo
    monkeypatch.setattr(geo.time, "sleep", lambda s: None)
    g = Geocoder(Session(), tmp_path / "geo.json")
    a = {"address": "서울특별시 강남구 세곡동 100 A1블록", "gu": "강남구"}
    g.locate(a)
    assert a["geo"] == {"lat": 37.47, "lng": 127.1, "precision": "동"}
    b = {"address": None, "gu": "중랑구"}
    g.locate(b)
    assert b["geo"]["precision"] == "구"
    g.save()
    g2 = Geocoder(Session(), tmp_path / "geo.json")   # 캐시가 있으면 다시 묻지 않는다
    c = {"address": "서울특별시 강남구 세곡동 100 A1블록", "gu": "강남구"}
    g2.locate(c)
    assert g2.session.calls == [] and c["geo"]["precision"] == "동"


def test_lh_detail_units_from_complex_rows():
    from collector import lh
    item = lh.normalize({"PAN_ID": "7", "PAN_NM": "강서염창 통합공공임대주택 모집", "AIS_TP_CD_NM": "통합공공임대", "PAN_NT_ST_DT": "2026.09.17"}, "임대")
    lh.apply_detail(item, [{"dsSbd": [{"LGDN_ADR": "서울특별시 강서구 공항대로81길 14(염창동)", "HSH_CNT": "14",
                                        "HTN_FMLA_DESC": "개별난방", "DDO_AR": "59.95~59.95", "MVIN_XPC_YM": "2027.02"}]}])
    assert item["units"] == 14 and item["area"] == "59.95㎡" and "개별난방" in item["tags"]
    assert item["address"].startswith("서울특별시 강서구") and item["gu"] == "강서구" and item["moveIn"] == "2027-02"


def test_sh_single_address():
    assert sh.single_address("소재지: 서울특별시 관악구 신림동 1422-5 (에어스페이스)") == "서울특별시 관악구 신림동 1422-5"
    assert sh.single_address("서울특별시 강동구 고덕동 1 / 서울특별시 송파구 거여동 2") is None
    assert sh.single_address("공급 위치는 첨부 참조") is None


def test_applyhome_notice_files():
    html = """<a href="https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=1&amp;pblancNo=1&amp;atchmnflSeqNo=9&amp;atchmnflSn=4"
      class="btn">모집공고문 보기</a> <a href="/x">기타</a>"""
    assert applyhome.notice_files(html) == [{"name": "모집공고문 보기 (PDF)",
        "url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=1&pblancNo=1&atchmnflSeqNo=9&atchmnflSn=4"}]


def test_lh_image_resolver_skips_placeholder():
    from collector import lh

    class Resp:
        status_code = 200
        text = '<img src="/images/co/na/noImg.gif"><img src="/lhFile/2026/plan_26A.png">'
    class Session:
        def get(self, url, params=None, timeout=None):
            return Resp()
    item = {"images": [{"label": "단지배치도", "name": "단지배치도.png", "url": "https://apply.lh.or.kr/lhImageView2.do?id=1"}]}
    lh.resolve_images(Session(), item)
    assert item["images"][0]["url"] == "https://apply.lh.or.kr/lhFile/2026/plan_26A.png"

    class OnlyPlaceholder:
        def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                text = '<img src="/images/co/na/noImg.gif">'
            return R()
    item = {"images": [{"label": "위치도", "name": "위치도.jpg", "url": "https://apply.lh.or.kr/lhImageView2.do?id=2"}]}
    lh.resolve_images(OnlyPlaceholder(), item)
    assert item["images"][0]["url"] == "https://apply.lh.or.kr/lhImageView2.do?id=2"


def test_pdf_plan_page_detection(tmp_path):
    import pymupdf
    from collector import pdfplans
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Floor plan: see model house")      # 안내문뿐인 페이지
    p2 = doc.new_page()
    p2.insert_text((50, 50), "84A")
    for k in range(900):                                        # 선이 아주 많은 페이지 = 평면도
        p2.draw_line((10 + k % 30, 100), (10 + k % 30, 300))
    p3 = doc.new_page()
    p3.insert_text((50, 50), "59")
    # 한글 키워드는 기본 글꼴로 넣기 어려워 판별 정규식을 잠시 바꿔 시험한다
    old = pdfplans.PLAN_WORD
    pdfplans.PLAN_WORD = __import__("re").compile(r"Floor plan|84A|59")
    try:
        assert pdfplans.candidate_pages(doc) == [1]
    finally:
        pdfplans.PLAN_WORD = old
    models = [{"type": "84A"}, {"type": "84B"}, {"type": "59"}]
    assert pdfplans.types_on_page("주택형 084.9800A 평면도", models) == ["84A"]
    assert pdfplans.types_on_page("59㎡ 타입", models) == ["59"]
    assert pdfplans.types_on_page("2059년", models) == []


def test_homepage_plan_helpers():
    from collector import homeplans as hp
    assert hp.type_from_url("https://cheonggye-elitz.com/assets/plan-81a.webp?v=bc7e754d") == "81A"
    assert hp.type_from_url("http://x.com/images/type-38-plan.png") == "38"
    assert hp.type_from_url("http://x.com/unit_084B.jpg") == "84B"
    assert hp.type_from_url("http://x.com/img/community_01_240528.jpg") is None
    assert hp.is_plan_image("https://cheonggye-elitz.com/assets/plan-81a.webp?v=1")
    assert not hp.is_plan_image("https://cheonggye-elitz.com/assets/siteplan-low.webp?v=1")
    assert not hp.is_plan_image("https://x.com/img/community_KV_240527.jpg")
    assert hp.match_type("81A", "81A") and hp.match_type("38", "38") and hp.match_type("84", "84B")
    assert not hp.match_type("81B", "81A") and not hp.match_type("59", "84A")


def test_homepage_plans_attach_from_cache(tmp_path):
    import json as _json
    from collector import homeplans as hp
    (tmp_path / "plans").mkdir()
    today = hp.kst_today().isoformat()
    (tmp_path / "plans" / "homepages.json").write_text(_json.dumps({"http://cheonggye-elitz.com": {"checked": today, "plans": [
        {"url": "https://cheonggye-elitz.com/assets/plan-81a.webp", "type": "81A", "kind": "평면"},
        {"url": "https://cheonggye-elitz.com/assets/plan-76.webp", "type": "76", "kind": "평면"}]}}), encoding="utf-8")
    n = {"source": "청약홈", "homepage": "cheonggye-elitz.com", "dates": {"end": today},
         "models": [{"type": "81A"}, {"type": "81B"}, {"type": "76"}]}
    hp.attach([n], tmp_path)
    assert [m.get("plan") for m in n["models"]] == ["https://cheonggye-elitz.com/assets/plan-81a.webp", None,
                                                    "https://cheonggye-elitz.com/assets/plan-76.webp"]
    assert len(n["homePlans"]) == 2


def test_only_recruitment_notices():
    keep = [
        "2026년 2차 행복주택 입주자 모집공고",
        "2026년 2차 청년안심주택(공공임대) 입주자 모집공고(정정)",
        "(수정) 2026년 2차 장기미임대 매입임대주택 입주자모집공고",
        "26년 3차 청년 매입임대주택 예비입주자 모집공고",
        "서울번동3 행복주택 예비입주자 모집",
        "2026년 재개발임대주택 일반모집 공고",
        "[토지임대부 사회주택] 옥류서원 입주자 모집 공고문",
    ]
    drop = [
        "2026년 재개발임대주택 입주자 모집 일정 연기 안내",
        "2026년 빈집활용 건설약정방식 매입임대주택 사전공고(수정)",
        "2026년 1차 일반주택형 미리내집(신혼신생아매입임대주택Ⅱ) 입주자 모집공고(2026.08.14.) 주택정보 추가",
        "행복주택 입주자 모집 접수 기간 변경 안내",
        "2026년 국민임대 입주자 모집 취소 공고",
        "행복주택 예비당첨자 게시",
    ]
    assert [t for t in keep if not sh.is_recruitment(t)] == []
    assert [t for t in drop if sh.is_recruitment(t)] == []


def test_capital_region_helpers():
    from collector.common import place_in_text, region_of, sigungu
    assert region_of("경기") == "경기" and region_of(None, "인천광역시 연수구") == "인천" and region_of("부산") is None
    assert sigungu("경기도 성남시 분당구 정자동 1") == "성남시" and sigungu("인천광역시 연수구 송도동") == "연수구"
    assert place_in_text("남양주왕숙 A-1블록 신혼희망타운", "경기") == "남양주시"
    assert place_in_text("하남교산 A2 행복주택", "경기") == "하남시"
    assert place_in_text("인천 미추홀구 매입임대", "인천") == "미추홀구"
    assert place_in_text("광주 송정 행복주택", "경기") is None   # '광주'는 광주광역시와 헷갈려서 줄임말로 안 찾음


def test_applyhome_keeps_capital_region():
    row = dict(APT_ROW, SUBSCRPT_AREA_CODE_NM="경기", HSSPLY_ADRES="경기도 하남시 교산동 1")
    n = applyhome.normalize(row, applyhome.SOURCES[0], [])
    assert (n["region"], n["gu"]) == ("경기", "하남시")


GH_LIST = """<table><tbody>
<tr> <td>1</td> <td> 행복주택 </td> <td> <a class="text_cut" data-biztynm="행복주택" data-pbanckndcd="01" data-pbancno="811" href="#a"> 연천BIX 경기행복주택 기업체 기숙사 추가모집 공고 </a> </td> <td> 연천군 <td> <img alt="pdf파일" src="/images/sub/pdf.png"/> </td> <td> 2026-10-01 </td> <td> 2026-10-20 <td> 접수중 <td> <button class="btn_normal" data-biztycd="01" data-pbancno="811" type="button">확인</button> </td> <td>22606</td></td></td></td></tr>
<tr> <td>2</td> <td> 장기전세 </td> <td> <a class="text_cut" data-pbancno="790" href="#a"> 경기리츠1호 다산진건데시앙 장기전세주택 예비입주자 모집공고 </a> </td> <td> 남양주시 <td></td> <td> 2026-08-13 </td> <td> 2026-08-24 <td> 접수마감 <td></td> <td>73390</td></td></td></td></tr>
<tr> <td>3</td> <td> 국민임대 </td> <td> <a data-pbancno="780" href="#a"> 다산센트럴파크6단지 국민임대 당첨자 발표 </a> </td> <td> 남양주시 <td></td> <td> 2026-08-01 </td> <td> - <td> - <td></td> <td>1</td></td></td></td></tr>
</tbody></table>"""


def test_gh_list_and_notice():
    from collector import gh
    rows = gh.parse_list(GH_LIST)
    assert [(r["no"], r["kind"], r["place"], r["notice"], r["end"], r["state"]) for r in rows[:2]] == [
        ("811", "행복주택", "연천군", "2026-10-01", "2026-10-20", "접수중"),
        ("790", "장기전세", "남양주시", "2026-08-13", "2026-08-24", "접수마감")]
    n = gh.to_notice(rows[0], gh.BOARDS[0])
    assert (n["region"], n["gu"], n["cat"], n["kind"], n["source"]) == ("경기", "연천군", "임대", "행복주택", "GH")
    assert n["dates"] == {"notice": "2026-10-01", "end": "2026-10-20"} and n["statusHint"] == "접수중"
    assert not sh.is_recruitment(rows[2]["title"])


IH_LIST = """<ul class="nav"><li><a href="/main/bbs/bbsMsgDetail.do?msg_seq=72&bcd=com_regul">안전보건관리규정</a></li></ul>
<ul class="board_list">
<li><a href="/main/bbs/bbsMsgDetail.do?msg_seq=177&cate1=a&bcd=sale_lease&pgno=1">검암역 푸르지오 프라베뉴(검암B-1BL) 입주자모집공고[정정공고]</a> <span>2026.08.25</span> <span>마케팅처</span></li>
<li><a href="/main/bbs/bbsMsgDetail.do?msg_seq=176&cate1=a&bcd=sale_lease&pgno=1">e편한세상 검단 웰카운티(검단AA10-1BL) 소유권이전등기 안내</a> <span>2026.08.24</span></li>
</ul>"""

IH_DETAIL = """<div class="board_view"><p>■ 공급위치 : 인천광역시 서구 검암동 100-1 일원</p>
<p>■ 청약접수 : 2026.09.01 ~ 09.03</p><p>■ 당첨자 발표 : 2026.09.10</p>
<a href="/main/bbs/bbsMsgFileDown.do?bcd=sale_lease&msg_seq=177&fileno=1">입주자모집공고문.pdf [1,024KByte]</a> <a href="/x">미리보기</a></div>"""


def test_ih_list_detail_notice():
    from collector import ih
    rows = ih.parse_list(IH_LIST, "sale_lease")
    assert [(r["seq"], r["date"]) for r in rows] == [("177", "2026-08-25"), ("176", "2026-08-24")]
    assert sh.is_recruitment(rows[0]["title"]) and not sh.is_recruitment(rows[1]["title"])
    d = ih.parse_detail(IH_DETAIL)
    assert d["files"] == [{"name": "입주자모집공고문.pdf", "url": "https://www.ih.co.kr/main/bbs/bbsMsgFileDown.do?bcd=sale_lease&msg_seq=177&fileno=1"}]
    n = ih.to_notice(rows[0], ih.BOARDS[0], d)
    assert (n["region"], n["gu"], n["cat"], n["address"]) == ("인천", "서구", "분양", "인천광역시 서구 검암동 100-1")
    assert n["dates"] == {"notice": "2026-08-25", "start": "2026-09-01", "end": "2026-09-03", "winner": "2026-09-10"}
    assert "정정공고" in n["tags"]


def test_still_relevant_and_lh_sale_supply():
    from collector import lh
    from collector.common import kst_today, still_relevant
    from datetime import timedelta
    today = kst_today()
    assert still_relevant({"notice": "2020-01-01"})                                   # 끝나는 날 모르면 살림
    assert not still_relevant({"end": (today - timedelta(days=30)).isoformat()})
    assert still_relevant({"end": (today - timedelta(days=30)).isoformat(), "contract_end": today.isoformat()})
    item = lh.normalize({"PAN_ID": "61183", "PAN_NM": "양주회천 A26 공공분양 입주자 모집공고", "AIS_TP_CD_NM": "공공분양",
                         "CNP_CD_NM": "경기도", "PAN_NT_ST_DT": "2026.10.01"}, "분양")
    lh.apply_supply(item, [{"dsList01": [
        {"HTY_NM": "59.7400A", "RSDN_DDO_AR": "59.74", "SPL_AR": "82.6719", "TOT_HSH_CNT": "262", "SIL_AMT": "353694000"},
        {"HTY_NM": "84.8600A", "RSDN_DDO_AR": "84.86", "SPL_AR": "114.1", "TOT_HSH_CNT": "530", "SIL_AMT": "462100000"}]}])
    assert [(m["type"], m["excl"], m["units"], m["price"]) for m in item["models"]] == [("59A", 59.74, 262, 35369), ("84A", 84.86, 530, 46210)]
    assert (item["units"], item["priceMin"], item["priceMax"], item["region"], item["gu"]) == (792, 35369, 46210, "경기", "양주시")


def test_capital_landmarks_and_exclusions():
    from collector import gh, ih
    from collector.common import place_in_text
    assert place_in_text("장기전세주택 예비입주자 모집공고 (청학아파트)", "인천") == "연수구"
    assert place_in_text("더샵부평센트럴시티 10년 분양전환 공공임대", "인천") == "부평구"
    assert place_in_text("동탄2 A-12블록 행복주택", "경기") == "화성시"
    assert place_in_text("고덕강일 3단지", "서울") is None
    assert not sh.is_recruitment("2026년 임대아파트 단지 내 상가 입점자 모집 공고(청학)")
    row = {"seq": "1", "title": "장기전세주택 예비입주자 모집공고 (청학아파트)", "date": "2026-07-23", "href": "u"}
    n = ih.to_notice(row, ih.BOARDS[1], None)
    assert (n["kind"], n["gu"]) == ("장기전세", "연수구")
