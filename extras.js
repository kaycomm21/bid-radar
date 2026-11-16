/* BID RADAR extras — 과거 연도 불러오기 · 전체 순위/점수 · 행사 이력 탭 · 심층분석(AI) 탭  (ⓒ 2026-11-17)
   index.html 의 window.BR(데이터·상태·도우미)을 받아 쓴다. 큰 데이터(history.js, ranks.js)는 필요할 때만 내려받는다. */
(() => {
  'use strict';
  const BR = window.BR;
  if (!BR || !BR.DATA) return;
  const { esc, fmtWon, state } = BR;
  const DATA = BR.DATA;
  const $ = (id) => document.getElementById(id);

  // ── 공통 ────────────────────────────────────────────────────────────
  const loaded = {};
  function loadScript(src) {
    if (!loaded[src]) {
      loaded[src] = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => resolve(true);
        s.onerror = () => { delete loaded[src]; reject(new Error(src + ' 를 불러오지 못했습니다')); };
        document.head.appendChild(s);
      });
    }
    return loaded[src];
  }
  const LEGAL_RE = /주식회사|\(주\)|㈜|유한회사|\(유\)|사단법인|\(사\)|재단법인|\(재\)|협동조합|합자회사|\(합\)|합명회사|영농조합법인|사회적협동조합/g;
  const normKey = (n) => String(n || '').replace(LEGAL_RE, '').replace(/\s+/g, '');
  const dispMap = new Map();
  function registerNames(rows) {
    rows.forEach((r) => { const k = normKey(r.corp_norm || r.corp); if (k && !dispMap.has(k)) dispMap.set(k, r.corp_norm || r.corp); });
  }
  registerNames(DATA.won_rows);
  const disp = (name) => dispMap.get(normKey(name)) || name;
  const eok1 = (v) => (v / 1e8).toFixed(1);
  const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

  // ── 과거 연도 (history.js) ──────────────────────────────────────────
  const H = { rows: null, merged: false };
  const bandOf = (v) => { const e = v / 1e8; return e < 1 ? '1억 미만' : e < 3 ? '1~3억' : e < 6 ? '3~6억' : e < 11 ? '6~11억' : '11억 이상'; };
  const bandUi = (v) => { const e = v / 1e8; return e >= 1 && e < 3 ? '1~2억' : e >= 3 && e < 6 ? '3~5억' : e >= 6 && e < 11 ? '6~10억' : '그 외'; };
  async function ensureHistory() {
    if (H.rows) return H.rows;
    await loadScript('./history.js');
    const raw = window.__BID_HIST__;
    if (!raw) throw new Error('history.js 형식 오류');
    const keys = raw.keys;
    H.rows = raw.rows.map((arr) => {
      const r = {};
      keys.forEach((k, i) => { r[k] = arr[i]; });
      const m = (r.posted || '').slice(0, 7);
      const mm = Number(m.slice(5, 7));
      r.month = m; r.year = m.slice(0, 4);
      r.half = `${r.year}-H${mm <= 6 ? 1 : 2}`; r.quarter = `${r.year}-Q${Math.floor((mm - 1) / 3) + 1}`;
      r.budget = r.value; r.band = bandOf(r.value); r.band_ui = bandUi(r.value);
      r.scope = '판정불가'; r.source_db = 'G2B 과거 이력'; r.is_notion_v2 = false; r._hist = true; r._noise = false; r.ranks = [];
      return r;
    });
    registerNames(H.rows);
    return H.rows;
  }
  async function mergeHistory() {
    const btn = $('btnLoadHistory');
    if (H.merged) return;
    try {
      if (btn) { btn.disabled = true; btn.textContent = '⏳ 과거 연도 내려받는 중…'; }
      const rows = await ensureHistory();
      const have = new Set(DATA.won_rows.map((r) => r.no));
      const add = rows.filter((r) => !have.has(r.no));
      add.forEach((r) => DATA.won_rows.push(r));
      DATA.won_rows.sort((a, b) => (b.posted || '').localeCompare(a.posted || ''));
      const m = DATA.meta;
      const uniq = (k) => [...new Set(DATA.won_rows.map((r) => r[k]).filter((x) => x && x !== '미상'))].sort();
      m.all_years = uniq('year'); m.all_halves = uniq('half'); m.all_quarters = uniq('quarter'); m.all_months = uniq('month');
      H.merged = true;
      applyRanks(DATA.won_rows);
      BR.buildPeriodControls(); BR.syncFilterChips(); BR.renderAll();
      if (btn) { btn.textContent = `✅ 과거 연도 포함됨 (+${add.length.toLocaleString('ko-KR')}건, ${m.all_years[0]}~)`; btn.classList.add('active'); }
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = '⚠️ 불러오기 실패 — 다시 누르세요'; }
    }
  }
  $('btnLoadHistory')?.addEventListener('click', mergeHistory);

  // ── 전체 순위·점수 (ranks.js) ──────────────────────────────────────
  let RK = null;
  async function ensureRanks() {
    if (RK) return RK;
    try { await loadScript('./ranks.js'); RK = window.__BID_RANKS__ || {}; } catch (_) { RK = {}; }
    return RK;
  }
  function applyRanks(rows) {
    if (!RK) return 0;
    let n = 0;
    rows.forEach((r) => {
      const v = RK[r.no];
      if (!v) return;
      r._rkTotal = v[0];
      r.ranks = v[1].map((x) => ({ rank: x[0], corp: x[1], corp_norm: disp(x[1]), amt: x[2], tech: x[3], price: x[4], total_score: x[5], note: x[6] }));
      r.rank_detail_raw = r.ranks.slice(0, 5).map((p) => `${p.rank || '-'}위 ${p.corp_norm}${p.total_score != null ? ' ' + p.total_score : ''}`).join(' · ');
      n += 1;
    });
    return n;
  }
  let ranksApplied = false;
  async function activateRanks() {
    if (ranksApplied) return;
    ranksApplied = true;
    await ensureRanks();
    applyRanks(DATA.won_rows);
    DATA.meta.rank_detail_count = DATA.won_rows.filter((r) => r.ranks && r.ranks.length).length;
    BR.renderAll();
  }
  // 차점·행사이력·심층분석 탭을 열 때만 순위 데이터를 내려받는다(첫 화면 속도 유지)
  document.querySelectorAll('[data-tab="runners"],[data-tab="history"],[data-tab="ai"]').forEach((b) => b.addEventListener('click', activateRanks));
  if (/^#\/?(runners|history|ai)/.test(location.hash)) activateRanks();
  // 행사 이력·심층분석은 위쪽 전역 필터를 거의 쓰지 않으므로, 탭을 열면 탭 줄이 화면 맨 위로 오게 한다
  const toTabs = () => setTimeout(() => document.querySelector('nav.tabs')?.scrollIntoView({ block: 'start' }), 30);
  document.querySelectorAll('[data-tab="history"],[data-tab="ai"]').forEach((b) => b.addEventListener('click', toTabs));
  if (/^#\/?(history|ai)/.test(location.hash)) toTabs();

  // ── 행사 이력 탭 ───────────────────────────────────────────────────
  const EXAMPLES = ['탈춤', '찻사발', '신라문화제', '수성못', '100대 피아노', '치맥', '도민체육대회', '풍기인삼'];
  $('histChips').innerHTML = '<span class="filter-label">예시</span>' + EXAMPLES.map((x) => `<button type="button" class="chip" data-hq="${esc(x)}">${esc(x)}</button>`).join('');
  $('histChips').addEventListener('click', (e) => { const b = e.target.closest('[data-hq]'); if (b) { $('histQuery').value = b.dataset.hq; histSearch(); } });
  $('btnHistSearch').addEventListener('click', histSearch);
  $('histQuery').addEventListener('keydown', (e) => { if (e.key === 'Enter') histSearch(); });

  async function findEventRows(q) {
    const tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!tokens.length) return [];
    let hist = [];
    try { hist = await ensureHistory(); } catch (_) { /* 과거 연도 없이 2026년만 */ }
    await ensureRanks();
    const seen = new Set();
    const pool = [];
    DATA.won_rows.concat(H.merged ? [] : hist).forEach((r) => { if (!seen.has(r.no)) { seen.add(r.no); pool.push(r); } });
    const out = pool.filter((r) => { const hay = `${r.title} ${r.org}`.toLowerCase(); return tokens.every((t) => hay.includes(t)); });
    applyRanks(out);
    return out.sort((a, b) => (b.posted || '').localeCompare(a.posted || ''));
  }
  const cname = (r) => r.corp_norm || r.corp;
  const fmtScore = (x) => (x == null ? '-' : Number(x).toFixed(2));

  function rankTable(r) {
    if (!r.ranks || !r.ranks.length) return '<div class="muted" style="padding:6px 0;">이 공고는 순위가 아직 수집되지 않았습니다(단독응찰이거나 수집 대기).</div>';
    const more = r._rkTotal > r.ranks.length ? `<div class="muted" style="font-size:11.5px;">참가 ${r._rkTotal}곳 중 상위 ${r.ranks.length}곳만 표시</div>` : '';
    return `<table style="min-width:520px;margin:6px 0;"><thead><tr><th class="num">개찰순위</th><th>업체</th><th class="num">투찰금액</th><th class="num">기술</th><th class="num">가격</th><th class="num">종합</th><th>비고</th></tr></thead><tbody>` +
      r.ranks.map((p) => `<tr${p.corp_norm === cname(r) ? ' style="background:var(--acc-dim);"' : ''}><td class="num">${p.rank || '-'}</td><td><span class="corp-link" data-corp="${esc(p.corp_norm)}">${esc(p.corp_norm)}</span>${p.corp_norm === cname(r) ? ' <span class="badge badge-acc">최종 낙찰</span>' : ''}</td><td class="num">${p.amt ? fmtWon(p.amt) : '-'}</td><td class="num">${fmtScore(p.tech)}</td><td class="num">${fmtScore(p.price)}</td><td class="num"><b>${fmtScore(p.total_score)}</b></td><td class="muted">${esc(p.note || '')}</td></tr>`).join('') +
      `</tbody></table>${more}`;
  }

  let lastHist = { q: '', rows: [] };
  async function histSearch() {
    const q = $('histQuery').value.trim();
    const box = $('histResult');
    if (!q) { box.innerHTML = '<div class="empty-msg">행사명을 넣고 「찾기」를 누르세요.</div>'; return; }
    box.innerHTML = '<div class="empty-msg">찾는 중… (처음 한 번은 과거 연도·순위 데이터를 내려받습니다)</div>';
    const rows = await findEventRows(q);
    lastHist = { q, rows };
    $('histStatus').textContent = `과거 연도 ${H.rows ? H.rows.length.toLocaleString('ko-KR') + '건' : '없음'} · 순위 ${RK ? Object.keys(RK).length.toLocaleString('ko-KR') + '건' : '없음'}`;
    if (!rows.length) { box.innerHTML = `<div class="empty-msg">"${esc(q)}"에 해당하는 낙찰 공고가 없습니다. 단어를 줄이거나 다른 표기로 찾아보세요. (나라장터에 낙찰 기록이 없는 수의·자체 발주는 나오지 않습니다)</div>`; return; }

    const years = [...new Set(rows.map((r) => r.year))].sort();
    const total = rows.reduce((s, r) => s + (r.value || 0), 0);
    const winCnt = new Map();
    rows.forEach((r) => winCnt.set(cname(r), (winCnt.get(cname(r)) || 0) + 1));
    const topWin = [...winCnt.entries()].sort((a, b) => b[1] - a[1])[0];
    const ns = rows.map((r) => r.n).filter((x) => x > 0);
    const ranked = rows.filter((r) => r.ranks && r.ranks.length);

    // 연도별
    const byYear = years.map((y) => {
      const rs = rows.filter((r) => r.year === y);
      const yn = rs.map((r) => r.n).filter((x) => x > 0);
      return { y, n: rs.length, v: rs.reduce((s, r) => s + r.value, 0), avgN: avg(yn), wins: [...rs].sort((a, b) => b.value - a.value).slice(0, 3) };
    });
    // 참가 업체(순위 수집분)
    const part = new Map();
    ranked.forEach((r) => r.ranks.forEach((p) => {
      if (!part.has(p.corp_norm)) part.set(p.corp_norm, { name: p.corp_norm, n: 0, first: 0, won: 0, ranks: [], tech: [], total: [], last: '' });
      const o = part.get(p.corp_norm);
      o.n += 1; if (p.rank === 1) o.first += 1; if (p.corp_norm === cname(r)) o.won += 1;
      if (p.rank) o.ranks.push(p.rank); if (p.tech != null) o.tech.push(p.tech); if (p.total_score != null) o.total.push(p.total_score);
      if ((r.year || '') > o.last) o.last = r.year;
    }));
    const partList = [...part.values()].sort((a, b) => b.n - a.n || b.won - a.won).slice(0, 30);

    box.innerHTML = `
      <div class="callout" style="margin-bottom:12px;">
        <b>"${esc(q)}"</b> — 낙찰 공고 <b>${rows.length}건</b> · ${years[0]}~${years[years.length - 1]}년 · 수주사 <b>${winCnt.size}곳</b> · 총 ${fmtWon(total)}
        · 평균 참가 <b>${ns.length ? avg(ns).toFixed(1) : '-'}개사</b> · 최다 수주 <b>${esc(topWin[0])}</b> (${topWin[1]}회)
        · 순위·점수 수집 ${ranked.length}건
        <button type="button" class="btn btn-acc" id="btnHistToAi" style="padding:2px 8px;margin-left:8px;font-size:11.5px;">🧠 이 행사 AI 분석</button>
      </div>
      <h4 style="margin:10px 0 6px;">연도별 수주사</h4>
      <div class="table-scroll-wrap" style="margin-bottom:14px;"><table style="min-width:640px;"><thead><tr><th>연도</th><th class="num">공고</th><th class="num">총액</th><th class="num">평균 참가</th><th>수주사 (금액 큰 순 3건)</th></tr></thead><tbody>
        ${byYear.map((x) => `<tr><td><b>${x.y}</b></td><td class="num">${x.n}건</td><td class="num">${fmtWon(x.v)}</td><td class="num">${x.avgN ? x.avgN.toFixed(1) : '-'}</td><td>${x.wins.map((r) => `<span class="corp-link" data-corp="${esc(cname(r))}">${esc(cname(r))}</span> <span class="muted">${fmtWon(r.value)}</span>`).join(' · ')}</td></tr>`).join('')}
      </tbody></table></div>
      ${partList.length ? `<h4 style="margin:10px 0 6px;">참가 업체 분석 <span class="muted" style="font-weight:400;font-size:12px;">(순위가 수집된 ${ranked.length}건 기준 · 개찰 1위와 최종 낙찰은 협상 결과에 따라 다를 수 있음)</span></h4>
      <div class="table-scroll-wrap" style="margin-bottom:14px;"><table style="min-width:680px;"><thead><tr><th>업체</th><th class="num">참가</th><th class="num">최종 낙찰</th><th class="num">개찰 1위</th><th class="num">평균 순위</th><th class="num">평균 기술</th><th class="num">평균 종합</th><th class="num">최근</th></tr></thead><tbody>
        ${partList.map((o) => `<tr><td><span class="corp-link" data-corp="${esc(o.name)}">${esc(o.name)}</span></td><td class="num"><b>${o.n}회</b></td><td class="num">${o.won}회</td><td class="num">${o.first}회</td><td class="num">${o.ranks.length ? avg(o.ranks).toFixed(1) : '-'}</td><td class="num">${fmtScore(avg(o.tech))}</td><td class="num">${fmtScore(avg(o.total))}</td><td class="num">${esc(o.last)}</td></tr>`).join('')}
      </tbody></table></div>` : ''}
      <h4 style="margin:10px 0 6px;">공고 목록 <span class="muted" style="font-weight:400;font-size:12px;">(「순위」를 누르면 참가 업체 점수가 펼쳐집니다${rows.length > 200 ? ' · 최근 200건만 표시' : ''})</span></h4>
      <div class="table-scroll-wrap"><table style="min-width:820px;"><thead><tr><th>개찰일</th><th>공고명</th><th>발주처</th><th>수주사</th><th class="num">금액</th><th class="num">참가</th><th class="num">낙찰률</th><th>순위</th></tr></thead><tbody>
        ${rows.slice(0, 200).map((r, i) => `<tr>
          <td style="white-space:nowrap;">${esc(r.posted || '')}</td>
          <td class="title-cell">${r.link ? `<a href="${esc(r.link)}" target="_blank" rel="noopener noreferrer">${esc(r.title)} ↗</a>` : esc(r.title)}</td>
          <td class="org-cell">${esc(r.org)}</td>
          <td><span class="corp-link" data-corp="${esc(cname(r))}">${esc(cname(r))}</span></td>
          <td class="num"><b>${fmtWon(r.value)}</b></td><td class="num">${r.n ? r.n + '개사' : '-'}</td><td class="num">${r.rate ? r.rate.toFixed(1) + '%' : '-'}</td>
          <td>${r.ranks && r.ranks.length ? `<button type="button" class="btn" data-rk="${i}" style="padding:2px 8px;font-size:11.5px;">순위 ▾</button>` : '<span class="muted">-</span>'}</td>
        </tr><tr id="rk-${i}" style="display:none;"><td colspan="8">${rankTable(r)}</td></tr>`).join('')}
      </tbody></table></div>`;
    box.querySelectorAll('[data-rk]').forEach((b) => b.addEventListener('click', () => {
      const tr = $('rk-' + b.dataset.rk); const open = tr.style.display === 'none';
      tr.style.display = open ? '' : 'none'; b.textContent = open ? '순위 ▴' : '순위 ▾';
    }));
    $('btnHistToAi')?.addEventListener('click', () => {
      document.querySelector('.tab-btn[data-tab="ai"]')?.click();
      $('aiType').value = 'event'; $('aiTarget').value = q; aiSyncForm(); aiBuild();
    });
  }

  // ── 심층분석(AI) 탭 ────────────────────────────────────────────────
  const AI_KEY = 'ag_bid_radar_ai_v1';
  let aiCfg = { provider: 'claude', model: '', key: '', save: false };
  try { const s = JSON.parse(localStorage.getItem(AI_KEY) || 'null'); if (s) aiCfg = { ...aiCfg, ...s }; } catch (_) { /* 저장값 없음 */ }
  const inputCss = 'background:var(--card-2,var(--card));border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px 10px;font-size:13px;font-family:inherit;';
  $('aiRoot').innerHTML = `
    <div class="filter-group" style="margin-bottom:10px;">
      <span class="filter-label">① 무엇을</span>
      <select id="aiType">
        <option value="company">특정 회사 분석</option>
        <option value="market">시장 분석 (지금 걸어 둔 필터 기준)</option>
        <option value="event">연속 행사 분석 (매년 열리는 행사)</option>
      </select>
      <input type="text" id="aiTarget" class="search-input" style="flex:1;min-width:200px;" placeholder="회사명 (예: 주식회사 렛츠)" />
      <label class="filter-label" style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;"><input type="checkbox" id="aiHist" checked /> 과거 연도(2020~) 포함</label>
      <button type="button" class="btn btn-acc" id="btnAiBuild">프롬프트 만들기</button>
    </div>
    <div id="aiInfo" class="muted" style="font-size:12px;margin-bottom:6px;">대상을 고르고 「프롬프트 만들기」를 누르세요.</div>
    <textarea id="aiPrompt" spellcheck="false" style="${inputCss}width:100%;min-height:220px;font-family:var(--mono);font-size:12px;line-height:1.5;" placeholder="여기에 데이터와 질문이 만들어집니다. 직접 고쳐 써도 됩니다."></textarea>
    <div class="filter-group" style="margin:8px 0 14px;">
      <span class="filter-label">② 구독 앱에 붙여넣기 (추가 비용 없음)</span>
      <button type="button" class="btn btn-acc" id="btnAiCopy">📋 복사</button>
      <a class="btn" href="https://claude.ai/new" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">Claude 열기 ↗</a>
      <a class="btn" href="https://gemini.google.com/app" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">Gemini 열기 ↗</a>
      <span id="aiCopyMsg" class="muted" style="font-size:12px;"></span>
    </div>
    <div class="callout" style="margin:0 0 10px;">
      <b>③ 이 화면에서 바로 분석 (API 키 필요 · 쓴 만큼 과금)</b>
      <div class="muted" style="font-size:12px;margin:4px 0 8px;">Claude·Gemini <u>구독 요금제의 사용량은 여기서 쓸 수 없습니다</u>(구독은 각 앱 안에서만 적용). 키는 이 브라우저에서 해당 AI 회사 서버로만 보내며, 「키 저장」을 체크한 경우에만 이 브라우저에 남습니다. 공용 PC에서는 저장하지 마세요.</div>
      <div class="filter-group">
        <select id="aiProvider"><option value="claude">Claude (Anthropic)</option><option value="gemini">Gemini (Google)</option></select>
        <input type="password" id="aiKey" autocomplete="off" style="${inputCss}flex:1;min-width:200px;" placeholder="API 키" />
        <select id="aiModel" style="min-width:180px;"><option value="">모델 (키 입력 후 불러오기)</option></select>
        <button type="button" class="btn" id="btnAiModels">모델 목록 불러오기</button>
        <label class="filter-label" style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;"><input type="checkbox" id="aiSave" /> 키 저장</label>
        <button type="button" class="btn btn-acc" id="btnAiRun">▶ 분석 실행</button>
      </div>
    </div>
    <div id="aiOut" style="display:none;border:1px solid var(--line);border-radius:10px;padding:14px;line-height:1.65;font-size:13.5px;overflow-x:auto;"></div>`;

  const PH = { company: '회사명 (예: 주식회사 렛츠)', market: '입력 불필요 — 위쪽 필터(지역·기간·유형)를 먼저 맞추세요', event: '행사명 (예: 100대 피아노, 탈춤)' };
  function aiSyncForm() { const t = $('aiType').value; $('aiTarget').placeholder = PH[t]; $('aiTarget').disabled = t === 'market'; }
  $('aiType').addEventListener('change', aiSyncForm);
  $('aiProvider').value = aiCfg.provider; $('aiKey').value = aiCfg.key || ''; $('aiSave').checked = !!aiCfg.save;
  if (aiCfg.model) $('aiModel').innerHTML = `<option value="${esc(aiCfg.model)}">${esc(aiCfg.model)}</option>`;

  const man = (v) => Math.round((v || 0) / 1e4).toLocaleString('ko-KR');
  const HEAD = '당신은 한국 공공 행사·축제 입찰 시장을 분석하는 전략 컨설턴트입니다. 아래 나라장터 낙찰 데이터만 근거로 분석하세요. 데이터에 없는 내용은 반드시 "추정"이라고 밝히고, 지어내지 마세요. 결론을 먼저 쓰고, 근거는 표로 정리하며, 마지막에 바로 실행할 행동 3가지를 제시하세요. 한국어로 답하세요.';
  const bidLine = (r) => [r.posted, r.title, r.org, cname(r), man(r.value), r.n || '', r.rate ? r.rate.toFixed(1) : '', r.cat || ''].join('\t');
  const BID_COLS = '개찰일\t공고명\t발주처\t수주사\t금액(만원)\t참가수\t낙찰률(%)\t유형';

  async function aiPool() {
    await ensureRanks();
    let rows = BR.getBaseWonRows();
    if ($('aiHist').checked && !H.merged) { try { rows = rows.concat(await ensureHistory()); } catch (_) { /* 2026년만 */ } }
    applyRanks(rows);
    return rows;
  }
  async function aiBuild() {
    const t = $('aiType').value; const target = $('aiTarget').value.trim(); const info = $('aiInfo');
    info.textContent = '데이터 모으는 중…';
    let text = '';
    if (t === 'company') {
      if (!target) { info.textContent = '회사명을 넣어 주세요.'; return; }
      const pool = await aiPool();
      const k = normKey(target).toLowerCase();
      let names = [...new Set(pool.map(cname).filter((n) => normKey(n).toLowerCase().includes(k)))];
      const exact = names.filter((n) => normKey(n).toLowerCase() === k);
      if (exact.length) names = exact;
      if (!names.length) { info.textContent = `"${target}"와 일치하는 수주 업체가 없습니다.`; return; }
      if (names.length > 1) { info.innerHTML = `"${esc(target)}"가 ${names.length}곳에 걸립니다. 정확한 이름을 넣어 주세요: ${names.slice(0, 8).map(esc).join(', ')}`; return; }
      const name = names[0];
      const wins = pool.filter((r) => cname(r) === name).sort((a, b) => (b.posted || '').localeCompare(a.posted || ''));
      const lost = pool.filter((r) => cname(r) !== name && (r.ranks || []).some((p) => p.corp_norm === name));
      const scoreLines = pool.filter((r) => (r.ranks || []).some((p) => p.corp_norm === name)).slice(0, 120).map((r) => {
        const p = r.ranks.find((x) => x.corp_norm === name);
        return [r.posted, r.title, `${p.rank || '-'}/${r._rkTotal || r.ranks.length}`, p.tech ?? '', p.price ?? '', p.total_score ?? '', cname(r)].join('\t');
      });
      text = `${HEAD}\n\n# 분석 대상: ${name}\n` +
        `수주 ${wins.length}건 · 총 ${fmtWon(wins.reduce((s, r) => s + r.value, 0))} · 참가했으나 탈락한 공고(순위 수집분) ${lost.length}건\n\n` +
        `## 수주 이력 (${Math.min(wins.length, 200)}건${wins.length > 200 ? ' — 최근 200건만' : ''})\n${BID_COLS}\n${wins.slice(0, 200).map(bidLine).join('\n')}\n\n` +
        (scoreLines.length ? `## 참가 공고별 순위·점수 (개찰 순위/참가 수, 기술, 가격, 종합, 최종 수주사)\n개찰일\t공고명\t순위\t기술\t가격\t종합\t최종수주사\n${scoreLines.join('\n')}\n\n` : '') +
        `## 질문\n1. 이 회사의 주력 행사 유형·금액대·단골 발주처는 무엇이며, 지역 범위는 어디까지인가?\n2. 연도별 수주 추세와 최근 1년의 변화는?\n3. 기술점수와 가격점수 중 어디에서 이기고 어디에서 지는가? 투찰 가격 성향(낙찰률)은?\n4. 이 회사와 경쟁할 때의 공략 지점, 협력(공동수급·연출 참여)을 제안할 때의 접근 포인트는?\n5. 이 회사의 약점 또는 비어 있는 영역은?`;
    } else if (t === 'market') {
      const rows = BR.getFilteredWonRows(false);
      if (!rows.length) { info.textContent = '현재 필터에 해당하는 공고가 없습니다.'; return; }
      const cm = new Map();
      rows.forEach((r) => { const n = cname(r); if (!cm.has(n)) cm.set(n, { n: 0, v: 0, hq: r.corp_hq || r.corp_sido || '' }); const o = cm.get(n); o.n += 1; o.v += BR.valueOf(r); });
      const top = [...cm.entries()].sort((a, b) => b[1].v - a[1].v).slice(0, 40);
      const cat = new Map(); rows.forEach((r) => { const o = cat.get(r.cat) || { n: 0, v: 0 }; o.n += 1; o.v += BR.valueOf(r); cat.set(r.cat, o); });
      const per = new Map(); rows.forEach((r) => { const o = per.get(r.quarter) || { n: 0, v: 0 }; o.n += 1; o.v += BR.valueOf(r); per.set(r.quarter, o); });
      const big = [...rows].sort((a, b) => BR.valueOf(b) - BR.valueOf(a)).slice(0, 80);
      text = `${HEAD}\n\n# 분석 대상: 시장 — ${BR.periodLabelText()} / 입찰 범위 ${state.region} / ${BR.zoneLabelText()}${state.cat !== 'ALL' ? ' / ' + state.cat : ''}${state.search ? ' / 검색어 "' + state.search + '"' : ''}\n` +
        `낙찰 ${rows.length}건 · 총 ${fmtWon(rows.reduce((s, r) => s + BR.valueOf(r), 0))} · 수주사 ${cm.size}곳\n\n` +
        `## 수주 상위 ${top.length}개사\n업체\t본사\t건수\t수주액(만원)\n${top.map(([n, o]) => [n, o.hq, o.n, man(o.v)].join('\t')).join('\n')}\n\n` +
        `## 행사 유형별\n유형\t건수\t총액(만원)\n${[...cat.entries()].sort((a, b) => b[1].v - a[1].v).map(([c, o]) => [c, o.n, man(o.v)].join('\t')).join('\n')}\n\n` +
        `## 분기별\n분기\t건수\t총액(만원)\n${[...per.entries()].sort().map(([c, o]) => [c, o.n, man(o.v)].join('\t')).join('\n')}\n\n` +
        `## 금액 상위 ${big.length}건\n${BID_COLS}\n${big.map(bidLine).join('\n')}\n\n` +
        `## 질문\n1. 이 시장의 구조(상위 집중도, 강자와 중견의 구분)는?\n2. 어떤 유형·금액대에 물량이 몰려 있고, 경쟁이 덜한 틈새는 어디인가?\n3. 지역 업체와 외지 업체의 구도는?\n4. 신규로 들어가거나 협력으로 참여하려는 기획·연출자에게 가장 승산 있는 영역 3가지는?\n5. 향후 6개월에 주목할 발주처와 행사 유형은?`;
    } else {
      if (!target) { info.textContent = '행사명을 넣어 주세요.'; return; }
      const rows = await findEventRows(target);
      if (!rows.length) { info.textContent = `"${target}"에 해당하는 낙찰 공고가 없습니다.`; return; }
      const use = rows.slice(0, 60);
      text = `${HEAD}\n\n# 분석 대상: 연속 행사 — "${target}" (낙찰 공고 ${rows.length}건${rows.length > 60 ? ', 최근 60건만 수록' : ''})\n\n` +
        use.map((r) => `## ${r.posted} | ${r.title}\n발주처: ${r.org} / 최종 수주: ${cname(r)} / 금액 ${man(r.value)}만원 / 참가 ${r.n || '?'}곳${r.rate ? ' / 낙찰률 ' + r.rate.toFixed(1) + '%' : ''}\n` +
          ((r.ranks && r.ranks.length) ? '개찰순위\t업체\t투찰금액(만원)\t기술\t가격\t종합\n' + r.ranks.map((p) => [p.rank || '-', p.corp_norm, p.amt ? man(p.amt) : '', p.tech ?? '', p.price ?? '', p.total_score ?? ''].join('\t')).join('\n') : '(순위·점수 미수집)')).join('\n\n') +
        `\n\n## 질문\n1. 이 행사는 기존 수행사가 굳어진 사업인가, 매번 바뀌는 사업인가? 근거는?\n2. 해마다 참가 업체 수와 얼굴은 어떻게 바뀌었나? 꾸준히 들어오는 업체는?\n3. 당락은 기술점수와 가격점수 중 무엇이 갈랐나? 1·2위 점수 차는 어느 정도인가?\n4. 다음 회차에 예상되는 경쟁사와 각자의 강점은?\n5. 새로 도전한다면 권장 투찰가 범위(예산 대비 %)와 제안서에서 벌려야 할 기술점수 차이는?\n6. 단독 참여와 협력 참여 중 무엇이 유리한가?`;
    }
    $('aiPrompt').value = text;
    info.textContent = `프롬프트 ${text.length.toLocaleString('ko-KR')}자 (대략 ${Math.round(text.length / 1.6).toLocaleString('ko-KR')} 토큰 안팎 — 추정). 고쳐 쓴 뒤 복사하거나 실행하세요.`;
  }
  $('btnAiBuild').addEventListener('click', aiBuild);
  $('btnAiCopy').addEventListener('click', async () => {
    const t = $('aiPrompt').value; if (!t) return;
    try { await navigator.clipboard.writeText(t); } catch (_) { $('aiPrompt').select(); document.execCommand('copy'); }
    $('aiCopyMsg').textContent = '복사됨 — Claude나 Gemini 대화창에 붙여넣으세요.';
  });

  function aiPersist() {
    aiCfg = { provider: $('aiProvider').value, model: $('aiModel').value, key: $('aiSave').checked ? $('aiKey').value.trim() : '', save: $('aiSave').checked };
    try { localStorage.setItem(AI_KEY, JSON.stringify(aiCfg)); } catch (_) { /* 저장 불가 환경 */ }
  }
  ['aiProvider', 'aiModel', 'aiSave'].forEach((id) => $(id).addEventListener('change', aiPersist));
  $('aiProvider').addEventListener('change', () => { $('aiModel').innerHTML = '<option value="">모델 (키 입력 후 불러오기)</option>'; });

  const CLAUDE_HEADERS = (key) => ({ 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true', 'content-type': 'application/json' });
  const out = (html) => { const o = $('aiOut'); o.style.display = 'block'; o.innerHTML = html; };
  async function aiModels() {
    const key = $('aiKey').value.trim(); const p = $('aiProvider').value;
    if (!key) { out('API 키를 먼저 넣어 주세요.'); return; }
    try {
      let ids = [];
      if (p === 'claude') {
        const r = await fetch('https://api.anthropic.com/v1/models?limit=100', { headers: CLAUDE_HEADERS(key) });
        const j = await r.json(); if (!r.ok) throw new Error(j?.error?.message || r.status);
        ids = (j.data || []).map((m) => m.id);
        const pref = ids.indexOf('claude-opus-5-5'); if (pref > 0) ids.unshift(ids.splice(pref, 1)[0]);
      } else {
        const r = await fetch('https://generativelanguage.googleapis.com/v1beta/models?pageSize=200', { headers: { 'x-goog-api-key': key } });
        const j = await r.json(); if (!r.ok) throw new Error(j?.error?.message || r.status);
        ids = (j.models || []).filter((m) => (m.supportedGenerationMethods || []).includes('generateContent')).map((m) => m.name);
      }
      if (!ids.length) throw new Error('사용 가능한 모델이 없습니다');
      $('aiModel').innerHTML = ids.map((id) => `<option value="${esc(id)}">${esc(id.replace(/^models\//, ''))}</option>`).join('');
      if (aiCfg.model && ids.includes(aiCfg.model)) $('aiModel').value = aiCfg.model;
      aiPersist(); out(`모델 ${ids.length}개를 불러왔습니다. 모델을 고르고 「분석 실행」을 누르세요.`);
    } catch (e) { out(`⚠️ 모델 목록을 불러오지 못했습니다: ${esc(String(e.message || e))}`); }
  }
  $('btnAiModels').addEventListener('click', aiModels);

  // 아주 작은 마크다운 표시기(제목·굵게·표·목록) — 외부 라이브러리 없이
  function md(text) {
    const lines = esc(text).split('\n'); let html = ''; let tbl = [];
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
    const flush = () => {
      if (!tbl.length) return;
      const rows = tbl.filter((l) => !/^[\s:|-]+$/.test(l));   // |---|---| 구분선 제외
      html += '<div class="table-scroll-wrap"><table style="min-width:420px;margin:8px 0;">' + rows.map((l, i) => '<tr>' + l.replace(/^\||\|$/g, '').split('|').map((c) => `<${i ? 'td' : 'th'}>${inline(c.trim())}</${i ? 'td' : 'th'}>`).join('') + '</tr>').join('') + '</table></div>';
      tbl = [];
    };
    lines.forEach((l) => {
      if (/^\s*\|.*\|\s*$/.test(l)) { tbl.push(l.trim()); return; }
      flush();
      const h = l.match(/^(#{1,4})\s+(.*)$/);
      if (h) html += `<h${h[1].length + 2} style="margin:14px 0 6px;">${inline(h[2])}</h${h[1].length + 2}>`;
      else if (/^\s*([-*]|\d+\.)\s+/.test(l)) html += `<div style="padding-left:14px;text-indent:-10px;">• ${inline(l.replace(/^\s*([-*]|\d+\.)\s+/, ''))}</div>`;
      else if (l.trim()) html += `<p style="margin:6px 0;">${inline(l)}</p>`;
    });
    flush();
    return html;
  }

  async function aiRun() {
    const key = $('aiKey').value.trim(); const p = $('aiProvider').value; const model = $('aiModel').value; const prompt = $('aiPrompt').value.trim();
    if (!prompt) { out('먼저 「프롬프트 만들기」를 눌러 주세요.'); return; }
    if (!key) { out('API 키를 넣어 주세요. 키가 없으면 ② 복사 → 구독 앱 붙여넣기를 쓰면 됩니다.'); return; }
    if (!model) { out('「모델 목록 불러오기」를 눌러 모델을 골라 주세요.'); return; }
    aiPersist();
    const btn = $('btnAiRun'); btn.disabled = true; out('⏳ 분석 중… 데이터가 많으면 1~3분 걸릴 수 있습니다.');
    let acc = '';
    try {
      if (p === 'claude') {
        // 긴 응답이 끊기지 않도록 스트리밍으로 받는다
        const r = await fetch('https://api.anthropic.com/v1/messages', { method: 'POST', headers: CLAUDE_HEADERS(key),
          body: JSON.stringify({ model, max_tokens: 32000, stream: true, messages: [{ role: 'user', content: prompt }] }) });
        if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j?.error?.message || `HTTP ${r.status}`); }
        const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = ''; let stop = '';
        for (;;) {
          const { done, value } = await reader.read(); if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split('\n'); buf = parts.pop();
          for (const line of parts) {
            if (!line.startsWith('data:')) continue;
            let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch (_) { continue; }
            if (ev.type === 'content_block_delta' && ev.delta?.type === 'text_delta') { acc += ev.delta.text; out(md(acc)); }
            else if (ev.type === 'message_delta' && ev.delta?.stop_reason) stop = ev.delta.stop_reason;
            else if (ev.type === 'error') throw new Error(ev.error?.message || '스트림 오류');
          }
        }
        if (stop === 'refusal') acc += '\n\n⚠️ 모델이 이 요청의 답변을 거절했습니다.';
        if (stop === 'max_tokens') acc += '\n\n⚠️ 응답이 길이 한도에서 잘렸습니다.';
      } else {
        const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/${model}:generateContent`, { method: 'POST',
          headers: { 'x-goog-api-key': key, 'content-type': 'application/json' }, body: JSON.stringify({ contents: [{ role: 'user', parts: [{ text: prompt }] }] }) });
        const j = await r.json(); if (!r.ok) throw new Error(j?.error?.message || `HTTP ${r.status}`);
        acc = (j.candidates?.[0]?.content?.parts || []).map((x) => x.text || '').join('') || '(빈 응답)';
      }
      out(md(acc) + `<div style="margin-top:10px;"><button type="button" class="btn" id="btnAiOutCopy">📋 결과 복사</button></div>`);
      $('btnAiOutCopy')?.addEventListener('click', () => navigator.clipboard?.writeText(acc));
    } catch (e) {
      out((acc ? md(acc) : '') + `<p>⚠️ 분석 실패: ${esc(String(e.message || e))}</p><p class="muted">키·모델·잔액을 확인하세요. 계속 안 되면 ② 복사 → 구독 앱 붙여넣기를 쓰면 됩니다.</p>`);
    } finally { btn.disabled = false; }
  }
  $('btnAiRun').addEventListener('click', aiRun);
  aiSyncForm();

  window.BRX = { ensureHistory, ensureRanks, mergeHistory, findEventRows, aiBuild, md };   // 검증·디버깅용
})();
