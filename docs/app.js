"use strict";

const DAY = 86400000;
const NEW_DAYS = 3;
const SOON_DAYS = 7;
const TARGETS = ["청년", "대학생", "신혼·신생아", "고령자", "다자녀", "한부모", "장애인", "예술인", "창업인"];
const SCHEDULE_STEPS = [
  ["notice", "모집공고"],
  ["special_start", "특별공급 접수", "special_end"],
  ["rank1_start", "1순위 접수", "rank1_end"],
  ["rank2_start", "2순위 접수", "rank2_end"],
  ["start", "청약 접수", "end"],
  ["winner", "당첨자 발표"],
  ["contract_start", "계약", "contract_end"],
];

const TABS = ["분양", "임대", "특수형", "전체"];
const CAT_CLASS = { "분양": "sale", "임대": "rent", "특수형": "special" };
// 특수형 유형별 특징: [카드에 보이는 한 줄, 상세 화면 설명]
const KIND_NOTES = {
  "토지임대부 분양": ["건물만 분양 · 땅은 임대료 별도",
    "건물만 소유하고 토지는 공공에 임대료를 내며 사용해요. 분양가가 크게 낮은 대신 매달 토지 임대료가 있고, 전매 제한·거주 의무·되팔 때 공공 환매 조건을 꼭 확인하세요."],
  "분양전환 임대": ["임대로 살다가 분양 전환",
    "정해진 기간(보통 5년·10년) 임대로 거주한 뒤 우선 분양받을 수 있어요. 전환 시점의 분양가 산정 방식(감정가 기준 등)과 임대 기간 중 보증금·임대료를 함께 비교하세요."],
  "지분적립형 분양": ["지분 일부만 사고 나중에 늘려가요",
    "처음에는 집 지분의 일부(예: 10~25%)만 사고, 20~30년에 걸쳐 나머지 지분을 나눠 사요. 남은 공공 지분에는 임대료를 내요."],
  "나눔형(이익공유)": ["싸게 사고, 팔 때 차익을 나눠요",
    "시세보다 낮은 가격에 분양받는 대신, 의무 거주 후 공공에 되팔 때 시세 차익의 일부를 공공과 나눠요."],
};
const kindClass = (n) => CAT_CLASS[n.cat] || "rent";

const state = {
  tab: "분양", q: "", kind: "", gu: "", sort: "deadline",
  statuses: new Set(["open", "upcoming", "check"]), fav: false, targets: new Set(),
  view: "list", stat: "",
};
let notices = [];
let meta = {};
let favs = loadFavs();
const $ = (s) => document.querySelector(s);

/* ---------- 날짜 ---------- */
function kstToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());
}
const TODAY = kstToday();
function diffDays(a, b) { return Math.round((Date.parse(a) - Date.parse(b)) / DAY); }
function addDays(iso, n) { return new Date(Date.parse(iso) + n * DAY).toISOString().slice(0, 10); }
function fmtDate(iso, withDow = true) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  const yy = iso.slice(0, 4) !== TODAY.slice(0, 4) ? `${iso.slice(2, 4)}.` : "";
  const s = `${yy}${d.getMonth() + 1}.${d.getDate()}`;
  return withDow ? `${s}(${"일월화수목금토"[d.getDay()]})` : s;
}
function fmtRange(a, b) {
  if (!a) return b ? `~ ${fmtDate(b)}` : "";
  if (!b || a === b) return fmtDate(a);
  return `${fmtDate(a)} ~ ${fmtDate(b)}`;
}
function fmtMonth(ym) { if (!ym) return ""; const [y, m] = ym.split("-"); return `${y}년 ${Number(m)}월`; }

/* ---------- 상태 ---------- */
function statusOf(n) {
  const d = n.dates || {};
  const s = d.start, e = d.end;
  if (s && TODAY < s) {
    const dd = diffDays(s, TODAY);
    return { key: "upcoming", label: dd === 1 ? "내일 접수 시작" : `접수 D-${dd}`, sortKey: s };
  }
  if (e && TODAY <= e) {
    if (!s && n.statusHint && /공고중|접수예정/.test(n.statusHint)) {
      return { key: "upcoming", label: n.statusHint, sortKey: e };
    }
    const dd = diffDays(e, TODAY);
    return { key: "open", label: dd === 0 ? "오늘 마감" : `마감 D-${dd}`, sortKey: e };
  }
  if (e && TODAY > e) {
    if (d.winner && TODAY <= d.winner) return { key: "closed", label: `발표 ${fmtDate(d.winner, false)}`, sortKey: "9" + d.winner };
    return { key: "closed", label: "마감", sortKey: "99" + e };
  }
  return { key: "check", label: "일정 확인", sortKey: "5" + (d.notice || "") };
}
const isNew = (n) => n.firstSeen && diffDays(TODAY, n.firstSeen) < NEW_DAYS;

/* ---------- 표시 형식 ---------- */
function money(man) {
  if (man == null) return "";
  if (man >= 10000) {
    const eok = Math.floor(man / 10000), rest = man % 10000;
    return rest ? `${eok}억 ${rest.toLocaleString()}만` : `${eok}억`;
  }
  return `${man.toLocaleString()}만`;
}
function moneyShort(man) {
  if (man == null) return "";
  return man >= 10000 ? `${(man / 10000).toFixed(man % 10000 ? 1 : 0).replace(/\.0$/, "")}억` : `${man.toLocaleString()}만`;
}
function perPyeong(m) {
  if (!m.price || !m.area) return null;
  return Math.round(m.price / (m.area / 3.3058));
}
function avgPerPyeong(n) {
  const v = (n.models || []).map(perPyeong).filter(Boolean);
  return v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length) : null;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function safeUrl(u) { return /^https?:\/\//.test(u || "") ? u : null; }

/* ---------- 관심 공고 (이 브라우저에만 저장) ---------- */
function loadFavs() {
  try { return new Set(JSON.parse(localStorage.getItem("favs") || "[]")); } catch { return new Set(); }
}
function toggleFav(id) {
  favs.has(id) ? favs.delete(id) : favs.add(id);
  try { localStorage.setItem("favs", JSON.stringify([...favs])); } catch { /* 저장 불가해도 화면은 동작 */ }
}

/* ---------- 필터 ---------- */
function inTab(n) { return state.tab === "전체" || n.cat === state.tab; }
function matches(n, { ignoreStatus = false } = {}) {
  if (!inTab(n)) return false;
  if (state.kind && n.kind !== state.kind) return false;
  if (state.gu && n.gu !== state.gu) return false;
  if (state.fav && !favs.has(n.id)) return false;
  if (state.targets.size && !(n.targets || []).some((t) => state.targets.has(t))) return false;
  if (state.q) {
    const hay = [n.name, n.address, n.gu, n.kind, n.supplier, n.builder].join(" ").toLowerCase();
    if (!state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  if (!ignoreStatus) {
    const st = statusOf(n);
    if (state.stat === "soon") return st.key === "open" && diffDays(n.dates.end, TODAY) <= SOON_DAYS;
    if (state.stat === "new") return isNew(n);
    if (state.stat) return st.key === state.stat;
    if (!state.statuses.has(st.key)) return false;
  }
  return true;
}
function sorted(list) {
  const by = {
    deadline: (a, b) => statusOf(a).sortKey.localeCompare(statusOf(b).sortKey),
    recent: (a, b) => (b.dates?.notice || "").localeCompare(a.dates?.notice || ""),
    price: (a, b) => (a.priceMin ?? 1e12) - (b.priceMin ?? 1e12),
  }[state.sort];
  const rank = { open: 0, upcoming: 1, check: 2, closed: 3 };
  return [...list].sort((a, b) => state.sort === "deadline"
    ? rank[statusOf(a).key] - rank[statusOf(b).key] || by(a, b)
    : by(a, b));
}

/* ---------- 렌더링 ---------- */
function renderHeader() {
  $("#updated").textContent = meta.updatedAt
    ? `${meta.updatedAt.slice(5, 10).replace("-", ".")} ${meta.updatedAt.slice(11, 16)} 업데이트 · 매일 오전 6시`
    : "첫 업데이트를 기다리는 중";
  // 오늘 실패해서 실제로 지난 데이터를 보여주는 출처만 안내 (한 번도 연결된 적 없는 출처는 조용히)
  const bad = Object.entries(meta.sources || {}).filter(([k, s]) => !s.ok && notices.some((n) => n.source === k && n.stale));
  const alert = $("#sourceAlert");
  if (bad.length) {
    alert.hidden = false;
    alert.textContent = `${bad.map(([k]) => k).join(", ")} 정보를 오늘 새로 받지 못해 지난 데이터를 보여주고 있어요.`;
  } else alert.hidden = true;
  for (const el of document.querySelectorAll("[data-count]")) {
    const t = el.dataset.count;
    const c = notices.filter((n) => (t === "전체" || n.cat === t) && statusOf(n).key !== "closed").length;
    el.textContent = c || "";
  }
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === state.tab);
  $("#tabNote").hidden = state.tab !== "특수형";
}

function renderStats() {
  const base = notices.filter((n) => matches(n, { ignoreStatus: true }));
  const items = [
    ["open", "접수중", base.filter((n) => statusOf(n).key === "open").length],
    ["soon", `${SOON_DAYS}일 안에 마감`, base.filter((n) => statusOf(n).key === "open" && diffDays(n.dates.end, TODAY) <= SOON_DAYS).length],
    ["upcoming", "접수 예정", base.filter((n) => statusOf(n).key === "upcoming").length],
    ["new", `새 공고 (${NEW_DAYS}일)`, base.filter(isNew).length],
  ];
  $("#stats").innerHTML = items.map(([k, label, c]) =>
    `<button class="stat${state.stat === k ? " on" : ""}" data-k="${k}" aria-pressed="${state.stat === k}"><b>${c}</b><span>${label}</span></button>`).join("");
}

function renderFilterOptions() {
  const inT = notices.filter(inTab);
  const kinds = [...new Set(inT.map((n) => n.kind).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  if (state.kind && !kinds.includes(state.kind)) state.kind = "";
  $("#kind").innerHTML = `<option value="">모든 유형</option>` + kinds.map((k) => `<option${k === state.kind ? " selected" : ""}>${esc(k)}</option>`).join("");
  const gus = [...new Set(notices.map((n) => n.gu).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  $("#gu").innerHTML = `<option value="">서울 전체</option>` + gus.map((g) => `<option${g === state.gu ? " selected" : ""}>${esc(g)}</option>`).join("");
  $("#sort").value = state.sort;
  const targets = TARGETS.filter((t) => inT.some((n) => (n.targets || []).includes(t)));
  $("#targetChips").innerHTML = targets.length
    ? targets.map((t) => `<button data-target="${esc(t)}" aria-pressed="${state.targets.has(t)}">${esc(t)}</button>`).join("")
    : "";
  for (const b of document.querySelectorAll("#statusChips [data-status]")) b.setAttribute("aria-pressed", state.statuses.has(b.dataset.status));
  $("#statusChips [data-fav]").setAttribute("aria-pressed", state.fav);
  for (const b of document.querySelectorAll(".seg button")) b.setAttribute("aria-selected", b.dataset.view === state.view);
}

function cardHTML(n) {
  const st = statusOf(n);
  const d = n.dates || {};
  const facts = [];
  if (d.start || d.end) facts.push(["접수", fmtRange(d.start, d.end)]);
  else if (d.notice) facts.push(["공고", fmtDate(d.notice)]);
  if (d.winner) facts.push(["발표", fmtDate(d.winner)]);
  if (n.units) facts.push(["공급", `${n.units.toLocaleString()}세대`]);
  if (n.moveIn) facts.push(["입주", fmtMonth(n.moveIn)]);
  let price = "";
  if (n.priceMin) {
    const pp = avgPerPyeong(n);
    price = `<p class="price">${moneyShort(n.priceMin)}${n.priceMax !== n.priceMin ? ` ~ ${moneyShort(n.priceMax)}` : ""}${pp ? `<small>평당 약 ${money(pp)}</small>` : ""}</p>`;
  }
  const tags = [...(n.targets || []), ...(n.tags || []).slice(0, 3)];
  const where = [n.gu, n.address ? n.address.replace(/^서울\S*\s*/, "").replace(n.gu || "", "").trim() : ""].filter(Boolean).join(" · ");
  return `<article class="card ${st.key}" data-id="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.name)} 자세히 보기">
    <div class="card-top">
      <span class="badge ${st.key}">${esc(st.label)}</span>
      <span class="kind ${kindClass(n)}">${esc(n.kind)}</span>
      ${isNew(n) ? `<span class="newtag">NEW</span>` : ""}
      <span class="src">${esc(n.source)}</span>
    </div>
    <button class="star" data-star="${esc(n.id)}" aria-pressed="${favs.has(n.id)}" aria-label="관심 공고">${favs.has(n.id) ? "★" : "☆"}</button>
    <h3>${esc(n.name)}</h3>
    ${where ? `<p class="where">${esc(where)}</p>` : ""}
    ${KIND_NOTES[n.kind] ? `<p class="kind-note">${KIND_NOTES[n.kind][0]}</p>` : ""}
    ${price}
    <dl class="facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
    ${tags.length ? `<div class="mini-tags">${tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
  </article>`;
}

function renderList(list) {
  const el = $("#list");
  if (!notices.length) {
    el.innerHTML = `<div class="empty"><b>아직 모은 공고가 없어요</b>매일 오전 6시에 자동으로 업데이트돼요.</div>`;
    return;
  }
  el.innerHTML = list.length
    ? list.map(cardHTML).join("")
    : state.tab === "특수형" && !notices.some((n) => n.cat === "특수형")
      ? `<div class="empty"><b>지금 서울에 나온 특수형 공고가 없어요</b>새 공고가 올라오면 매일 아침 여기에 모아 드려요.</div>`
      : `<div class="empty"><b>조건에 맞는 공고가 없어요</b>필터를 줄이거나 ‘마감’도 포함해 보세요.</div>`;
}

function agendaEvents(list) {
  const evs = [];
  for (const n of list) {
    const d = n.dates || {};
    const push = (date, type, label) => { if (date && date >= TODAY) evs.push({ date, type, label, n }); };
    if (d.special_start) push(d.special_start, "start", "특공 접수");
    if (d.rank1_start) push(d.rank1_start, "start", "1순위");
    if (!d.special_start && !d.rank1_start) push(d.start, "start", "접수 시작");
    push(d.end, "end", "접수 마감");
    push(d.winner, "winner", "당첨 발표");
    push(d.contract_start, "contract", "계약");
  }
  return evs.sort((a, b) => a.date.localeCompare(b.date));
}

function renderAgenda(list) {
  const evs = agendaEvents(list).filter((e) => e.date <= addDays(TODAY, 90));
  const el = $("#agenda");
  if (!evs.length) {
    el.innerHTML = `<div class="empty"><b>앞으로 90일 안에 잡힌 일정이 없어요</b>SH 공고 중 일부는 일정이 공고문에만 있어요.</div>`;
    return;
  }
  const byDay = new Map();
  for (const e of evs) (byDay.get(e.date) || byDay.set(e.date, []).get(e.date)).push(e);
  el.innerHTML = [...byDay].map(([date, items]) => {
    const dd = diffDays(date, TODAY);
    return `<div class="day${dd === 0 ? " today" : ""}">
      <div class="day-date">${fmtDate(date)}<small>${dd === 0 ? "오늘" : `D-${dd}`}</small></div>
      <div>${items.map((e) => `<button class="ev" data-id="${esc(e.n.id)}"><span class="ev-type ${e.type}">${e.label}</span><span class="ev-name">${esc(e.n.name)}</span></button>`).join("")}</div>
    </div>`;
  }).join("");
}

function render() {
  renderHeader();
  renderFilterOptions();
  renderStats();
  const list = sorted(notices.filter((n) => matches(n)));
  $("#result").textContent = notices.length ? `${list.length}건` : "";
  $("#list").hidden = state.view !== "list";
  $("#agenda").hidden = state.view !== "agenda";
  if (state.view === "list") renderList(list);
  else renderAgenda(sorted(notices.filter((n) => matches(n, { ignoreStatus: true }))));
  writeHash();
}

/* ---------- 상세 ---------- */
function timelineHTML(n) {
  const d = n.dates || {};
  const steps = [];
  for (const [k, label, kEnd] of SCHEDULE_STEPS) {
    if (!d[k]) continue;
    if (k === "start" && (d.special_start || d.rank1_start)) continue; // 특공·순위 일정이 있으면 합계 기간은 생략
    steps.push({ label, a: d[k], b: kEnd ? d[kEnd] : null });
  }
  if (n.moveIn) steps.push({ label: "입주 예정", a: n.moveIn + "-01", text: fmtMonth(n.moveIn) });
  if (!steps.length) return "";
  steps.sort((x, y) => x.a.localeCompare(y.a));
  const nowIdx = steps.findIndex((s) => (s.b || s.a) >= TODAY);
  return `<ol class="timeline">${steps.map((s, i) => `<li class="${i < nowIdx || nowIdx < 0 ? "past" : i === nowIdx ? "now" : ""}">
      <span>${s.label}</span><time>${esc(s.text || fmtRange(s.a, s.b))}</time></li>`).join("")}</ol>`;
}

function modelsHTML(n) {
  const ms = n.models || [];
  if (!ms.length) return "";
  const hasSpecial = ms.some((m) => m.special);
  return `<div class="table-scroll"><table class="models">
    <thead><tr><th>타입</th><th>전용</th>${hasSpecial ? "<th>특공</th>" : ""}<th>일반</th><th>최고가</th><th>평당</th></tr></thead>
    <tbody>${ms.map((m) => `<tr>
      <td>${esc(m.type || "-")}</td>
      <td>${m.excl ? `${m.excl}㎡` : "-"}</td>
      ${hasSpecial ? `<td>${m.special ?? "-"}</td>` : ""}
      <td>${m.units ?? "-"}</td>
      <td>${m.price ? money(m.price) : "-"}</td>
      <td>${perPyeong(m) ? moneyShort(perPyeong(m)) : "-"}</td></tr>`).join("")}</tbody>
  </table></div><p class="note">최고가 기준이에요. 평당가는 공급면적(3.3㎡)으로 나눈 추정치예요.</p>`;
}

function openDetail(id, { push = true } = {}) {
  const n = notices.find((x) => x.id === id);
  if (!n) return;
  const st = statusOf(n);
  const kv = [];
  if (n.units) kv.push(["공급 세대", `${n.units.toLocaleString()}세대`]);
  if (n.priceMin) kv.push(["분양가", n.priceMin === n.priceMax ? money(n.priceMin) : `${moneyShort(n.priceMin)} ~ ${moneyShort(n.priceMax)}`]);
  if (n.moveIn) kv.push(["입주 예정", fmtMonth(n.moveIn)]);
  if (n.builder) kv.push(["시공사", n.builder]);
  if (n.supplier) kv.push(["공급 주체", n.supplier]);
  if (n.tel) kv.push(["문의", n.tel]);
  const links = [];
  if (safeUrl(n.url)) links.push(`<a class="btn primary" href="${esc(n.url)}" target="_blank" rel="noopener">공고 원문 보기 ↗</a>`);
  if (safeUrl(n.homepage)) links.push(`<a class="btn" href="${esc(n.homepage)}" target="_blank" rel="noopener">분양 홈페이지 ↗</a>`);
  for (const l of n.links || []) if (safeUrl(l.url)) links.push(`<a class="btn" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`);
  const tags = [...(n.targets || []), ...(n.tags || [])];
  const timeline = timelineHTML(n);

  $("#detailBody").innerHTML = `
    <div class="sheet-head">
      <div>
        <div class="card-top">
          <span class="badge ${st.key}">${esc(st.label)}</span>
          <span class="kind ${kindClass(n)}">${esc(n.kind)}</span>
          <span class="src" style="margin-left:0">${esc(n.source)}</span>
        </div>
        <h2 id="dTitle">${esc(n.name)}</h2>
        <p class="where">${esc(n.address || n.gu || "서울")}</p>
      </div>
      <button class="close" data-close aria-label="닫기">×</button>
    </div>
    ${kv.length ? `<div class="section"><dl class="kv">${kv.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></div>` : ""}
    ${KIND_NOTES[n.kind] ? `<div class="section"><h4>${esc(n.kind)}란?</h4><p class="kind-detail">${KIND_NOTES[n.kind][1]}</p></div>` : ""}
    <div class="section"><h4>일정</h4>${timeline || `<p class="note">일정이 공고 본문에 없어요. 공고문 원문에서 확인해 주세요.</p>`}
      ${n.dateBasis === "본문" ? `<p class="note">SH 공고 본문에서 자동으로 읽은 일정이에요. 원문과 꼭 대조해 주세요.</p>` : ""}
      ${n.stale ? `<p class="note">오늘 이 출처를 새로 확인하지 못해 지난 정보를 보여주고 있어요.</p>` : ""}</div>
    ${n.models?.length ? `<div class="section"><h4>주택형별 공급</h4>${modelsHTML(n)}</div>` : ""}
    ${tags.length ? `<div class="section"><h4>대상·특징</h4><div class="tags-row">${tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div></div>` : ""}
    ${n.files?.length ? `<div class="section"><h4>첨부 공고문</h4><p class="note" style="margin:0">${n.files.map(esc).join("<br>")}</p></div>` : ""}
    <div class="actions">
      ${links.join("")}
      <button class="btn" data-ics="${esc(n.id)}">📅 캘린더에 추가</button>
      <button class="btn" data-share="${esc(n.id)}">🔗 링크 공유</button>
      <button class="btn" data-star="${esc(n.id)}" aria-pressed="${favs.has(n.id)}">${favs.has(n.id) ? "★ 관심 해제" : "☆ 관심 공고"}</button>
    </div>`;
  const dlg = $("#detail");
  if (!dlg.open) dlg.showModal();
  dlg.scrollTop = 0;
  state.open = id;
  if (push) writeHash();
}

function closeDetail() {
  const dlg = $("#detail");
  if (dlg.open) dlg.close();
}

/* ---------- 캘린더 파일(.ics) ---------- */
function icsFor(n) {
  const d = n.dates || {};
  const ymd = (iso) => iso.replace(/-/g, "");
  const ev = [];
  const add = (a, b, title) => {
    if (!a) return;
    ev.push(["BEGIN:VEVENT", `UID:${n.id}-${title}@seoul-house`, `DTSTAMP:${ymd(TODAY)}T000000Z`,
      `DTSTART;VALUE=DATE:${ymd(a)}`, `DTEND;VALUE=DATE:${ymd(addDays(b || a, 1))}`,
      `SUMMARY:[${title}] ${n.name}`.replace(/[,;]/g, "\\$&"),
      safeUrl(n.url) ? `URL:${n.url}` : "", "END:VEVENT"].filter(Boolean).join("\r\n"));
  };
  add(d.special_start, d.special_end, "특별공급");
  add(d.rank1_start, d.rank1_end, "1순위");
  if (!d.special_start && !d.rank1_start) add(d.start, d.end, "청약 접수");
  add(d.winner, null, "당첨 발표");
  add(d.contract_start, d.contract_end, "계약");
  if (!ev.length) return null;
  return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//seoul-house//KO", "CALSCALE:GREGORIAN", ...ev, "END:VCALENDAR"].join("\r\n");
}
function downloadIcs(id) {
  const n = notices.find((x) => x.id === id);
  const text = n && icsFor(n);
  if (!text) return toast("캘린더에 넣을 일정이 없어요");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/calendar" }));
  a.download = `${n.name.slice(0, 30)}.ics`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function share(id) {
  const n = notices.find((x) => x.id === id);
  const url = `${location.origin}${location.pathname}#n=${encodeURIComponent(id)}`;
  const st = statusOf(n);
  if (navigator.share) {
    try { await navigator.share({ title: n.name, text: `${n.name} (${st.label})`, url }); return; } catch { /* 취소 */ return; }
  }
  try { await navigator.clipboard.writeText(url); toast("링크를 복사했어요"); } catch { prompt("이 링크를 복사하세요", url); }
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 1800);
}

/* ---------- 주소창(#)에 필터 저장 → 링크로 공유 가능 ---------- */
function writeHash() {
  const p = new URLSearchParams();
  if (state.tab !== "분양") p.set("tab", state.tab);
  if (state.q) p.set("q", state.q);
  if (state.kind) p.set("kind", state.kind);
  if (state.gu) p.set("gu", state.gu);
  if (state.view !== "list") p.set("view", state.view);
  if ($("#detail").open && state.open) p.set("n", state.open);
  const h = p.toString();
  history.replaceState(null, "", h ? `#${h}` : location.pathname + location.search);
}
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (TABS.includes(p.get("tab"))) state.tab = p.get("tab");
  state.q = p.get("q") || "";
  state.kind = p.get("kind") || "";
  state.gu = p.get("gu") || "";
  if (p.get("view") === "agenda") state.view = "agenda";
  return p.get("n");
}

/* ---------- 이벤트 ---------- */
function bind() {
  document.querySelector(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]"); if (!b) return;
    state.tab = b.dataset.tab; state.kind = ""; state.stat = ""; render();
  });
  $("#q").addEventListener("input", (e) => { state.q = e.target.value.trim(); render(); });
  $("#kind").addEventListener("change", (e) => { state.kind = e.target.value; render(); });
  $("#gu").addEventListener("change", (e) => { state.gu = e.target.value; render(); });
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; render(); });
  $("#stats").addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]"); if (!b) return;
    state.stat = state.stat === b.dataset.k ? "" : b.dataset.k; render();
  });
  $("#statusChips").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.fav) state.fav = !state.fav;
    else { const s = b.dataset.status; state.statuses.has(s) ? state.statuses.delete(s) : state.statuses.add(s); }
    state.stat = ""; render();
  });
  $("#targetChips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-target]"); if (!b) return;
    const t = b.dataset.target; state.targets.has(t) ? state.targets.delete(t) : state.targets.add(t); render();
  });
  document.querySelector(".seg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]"); if (!b) return;
    state.view = b.dataset.view; render();
  });
  document.addEventListener("click", (e) => {
    const star = e.target.closest("[data-star]");
    if (star) {
      e.stopPropagation(); toggleFav(star.dataset.star);
      const dlgOpen = $("#detail").open;
      render(); if (dlgOpen) openDetail(star.dataset.star, { push: false });
      return;
    }
    const ics = e.target.closest("[data-ics]"); if (ics) return downloadIcs(ics.dataset.ics);
    const sh = e.target.closest("[data-share]"); if (sh) return share(sh.dataset.share);
    if (e.target.closest("[data-close]")) return closeDetail();
    const card = e.target.closest(".card, .ev");
    if (card) openDetail(card.dataset.id);
  });
  $("#list").addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches(".card")) { e.preventDefault(); openDetail(e.target.dataset.id); }
  });
  const dlg = $("#detail");
  dlg.addEventListener("click", (e) => { if (e.target === dlg) closeDetail(); });
  dlg.addEventListener("close", () => { state.open = null; writeHash(); });
}

async function load() {
  const bust = `?v=${TODAY}-${new Date().getHours()}`;
  try {
    const [a, b] = await Promise.all([fetch(`data/notices.json${bust}`), fetch(`data/meta.json${bust}`)]);
    notices = a.ok ? await a.json() : [];
    meta = b.ok ? await b.json() : {};
  } catch {
    notices = []; meta = {};
    $("#updated").textContent = "데이터를 불러오지 못했어요";
  }
}

(async function init() {
  const openId = readHash();
  $("#q").value = state.q;
  bind();
  await load();
  render();
  if (openId) openDetail(openId, { push: false });
})();
