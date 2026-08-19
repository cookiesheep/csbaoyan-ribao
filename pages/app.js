/* =====================================================================
   保研日报 · 活字印刷 Living Press —— app.js
   marked 渲染 → DOMParser 后处理 → 报纸版面确定性映射
   ===================================================================== */

const SCISSORS_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><line x1="20" y1="4" x2="8.12" y2="15.88"></line><line x1="14.47" y1="14.48" x2="20" y2="20"></line><line x1="8.12" y1="8.12" x2="12" y2="12"></line></svg>';

const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

/* 栏目角色映射 */
const SECTION_ROLE = {
  '今日概览': 'standfirst',
  '重要信息': 'lead',
  '经验': 'commentary',
  '观点': 'commentary',
  '有趣讨论': 'briefs',
  '讨论': 'briefs',
  '花絮': 'briefs',
  '风险': 'advisory',
  '待核实': 'advisory',
  '勘误': 'advisory',
};
const LABELS = {
  lead:      { no: '01', name: '重要信息' },
  commentary:{ no: '02', name: '经验 · 观点' },
  briefs:    { no: '03', name: '花絮 · 讨论' },
  advisory:  { no: '04', name: '风险 · 待核实' },
};

const state = {
  manifest: [],
  activeDate: null,
  activeIndex: 0,
  abortController: null,
  reportsCache: {},
  isSearching: false,
  dateSwitcherOpen: false,
  viewMode: 'full',
  tocObserver: null,
};

const elements = {};

function $(id) { return document.getElementById(id); }

function cacheElements() {
  const ids = [
    'home-link', 'home-view', 'reader-view', 'read-latest-btn', 'home-search-btn',
    'latest-report-date', 'home-report-count', 'recent-reports-list',
    'date-switcher', 'prev-date-btn', 'next-date-btn', 'current-date-btn',
    'date-switcher-current', 'dc-issue', 'date-switcher-popover', 'date-switcher-list',
    'report-count', 'search-meta', 'loading-state', 'report-content',
    'theme-toggle', 'view-toggle', 'toc', 'toc-list',
    'search-btn', 'search-modal', 'search-backdrop', 'search-input',
    'close-search-btn', 'search-results', 'ink-roller', 'toast',
    'pressroom-view', 'pressroom-back-btn', 'home-sift-count',
  ];
  for (const id of ids) {
    const key = id.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    elements[key] = $(id);
  }
}

/* ---------- 主题 ---------- */
function updateThemeIcon(setting) {
  const t = elements.themeToggle;
  if (!t) return;
  t.querySelector('.icon-sun').style.display = setting === 'light' ? 'block' : 'none';
  t.querySelector('.icon-moon').style.display = setting === 'dark' ? 'block' : 'none';
  t.querySelector('.icon-system').style.display = setting === 'system' ? 'block' : 'none';
}
function applyTheme(setting) {
  const isDark = setting === 'dark' || (setting === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
}
function initTheme() {
  let setting = localStorage.getItem('theme') || 'system';
  applyTheme(setting);
  updateThemeIcon(setting);
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((localStorage.getItem('theme') || 'system') === 'system') applyTheme('system');
  });
  elements.themeToggle?.addEventListener('click', () => {
    const cur = localStorage.getItem('theme') || 'system';
    const next = cur === 'system' ? 'light' : cur === 'light' ? 'dark' : 'system';
    localStorage.setItem('theme', next);
    applyTheme(next);
    updateThemeIcon(next);
  });
}

/* ---------- 工具 ---------- */
const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function getHashDate() { return window.location.hash.replace(/^#/, '').trim(); }
function setHashDate(date) {
  const next = `#${date}`;
  if (window.location.hash !== next) window.location.hash = next;
}
function pad3(n) { return String(n).padStart(3, '0'); }
function toRoman(num) {
  const map = [['M',1000],['CM',900],['D',500],['CD',400],['C',100],['XC',90],['L',50],['XL',40],['X',10],['IX',9],['V',5],['IV',4],['I',1]];
  let r = '';
  for (const [s, v] of map) { while (num >= v) { r += s; num -= v; } }
  return r;
}
function formatDate(date) { if (!date) return ''; const [y, m, d] = date.split('-'); return `${y}.${m}.${d}`; }
function formatHomeDate(date) { const [, m, d] = date.split('-'); return `${Number(m)}月${Number(d)}日`; }
function weekdayOf(date) {
  const d = new Date(`${date}T00:00:00`);
  return WEEK[d.getDay()] || '';
}
function issueNumberOf(index) { return state.manifest.length - index; }
function escapeHtml(t) {
  return t.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
}

/* ---------- markdown 渲染 ---------- */
function renderMarkdown(md) {
  if (!window.marked || !window.DOMPurify) throw new Error('Markdown renderer is unavailable');
  const raw = window.marked.parse(md, { breaks: false, gfm: true });
  return window.DOMPurify.sanitize(raw);
}

/* =====================================================================
   报纸版面构建 —— 确定性映射
   ===================================================================== */
function classifySection(text) {
  for (const key in SECTION_ROLE) if (text.includes(key)) return SECTION_ROLE[key];
  return 'generic';
}

/* 把 marked 输出拆成 {meta, blocks} */
function buildBlocks(html) {
  const host = new DOMParser().parseFromString(`<div id="r">${html}</div>`, 'text/html').getElementById('r');
  const meta = { title: '', colophon: '' };
  const blocks = [];
  let cur = null;
  for (const node of Array.from(host.childNodes)) {
    if (node.nodeType === 3) {
      if (node.textContent.trim() && cur) cur.nodes.push(node.cloneNode(true));
      continue;
    }
    if (node.nodeType !== 1) continue;
    const tag = node.tagName;
    if (tag === 'H1') { meta.title = node.textContent.trim(); continue; }
    if (tag === 'BLOCKQUOTE') { meta.colophon = node.textContent.trim(); continue; }
    if (tag === 'H2' || tag === 'H3') {
      const t = node.textContent.trim();
      cur = { role: classifySection(t), title: t, nodes: [] };
      blocks.push(cur);
      continue;
    }
    if (cur) cur.nodes.push(node.cloneNode(true));
  }
  return { meta, blocks };
}

function blockByRole(blocks, role) { return blocks.find(b => b.role === role); }

/* 抽取跨栏引文 —— 每节最长句 */
function extractPullQuote(blocks) {
  const lead = blockByRole(blocks, 'lead');
  const commentary = blockByRole(blocks, 'commentary');
  const pool = (lead ? lead.nodes.map(n => n.textContent).join('') : '') +
              (commentary ? commentary.nodes.map(n => n.textContent).join('') : '');
  const sentences = pool.split(/[。；！？\n]/).map(s => s.trim()).filter(s => s.length >= 14);
  if (!sentences.length) return '';
  sentences.sort((a, b) => b.length - a.length);
  let best = sentences[0];
  if (best.length > 46) {
    const cut = best.slice(0, 46);
    const last = Math.max(cut.lastIndexOf('，'), cut.lastIndexOf('、'), cut.lastIndexOf('；'));
    best = (last > 14 ? cut.slice(0, last) : cut);
  }
  return best;
}

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}

function makeSectionLabel(role, delay) {
  const label = LABELS[role] || { no: '·', name: role };
  const node = el('div', 'section-label ink-reveal');
  node.style.setProperty('--ink-delay', `${delay}s`);
  node.style.setProperty('--rule-delay', `${delay}s`);
  node.innerHTML = `<span class="sl-no">№ ${label.no}</span><span class="sl-name">${escapeHtml(label.name)}</span>`;
  return node;
}

function makeBody(role, block, delay) {
  const body = el('div', `${role}-body ink-reveal`);
  body.style.setProperty('--ink-delay', `${delay + 0.08}s`);
  for (const n of block.nodes) body.appendChild(n);
  /* 花絮：首加粗段当小标题 */
  if (role === 'briefs') {
    body.querySelectorAll('li').forEach(li => {
      const strong = li.querySelector(':scope > strong');
      if (strong) strong.classList.add('brief-kicker');
    });
  }
  return body;
}

function buildNewspaper(html, ctx) {
  const { meta, blocks } = buildBlocks(html);
  const newspaper = el('article', 'newspaper');
  const standfirstBlock = blockByRole(blocks, 'standfirst');
  const pullQuote = extractPullQuote(blocks);

  /* ---- Masthead ---- */
  const mast = el('header', 'masthead');
  const rail = el('div', 'masthead-rail');
  rail.innerHTML =
    `<span class="mr-left">第 NO.${pad3(ctx.issueNo)} 期 · ${ctx.issueRoman}</span>` +
    `<span class="mr-right">${formatDate(ctx.date)} · ${ctx.weekday}</span>`;
  mast.appendChild(rail);

  const titleblock = el('div', 'masthead-titleblock');
  const title = el('h1', 'masthead-title', '保研日报<span class="vert-mark">活字印刷</span>');
  const stamp = el('div', 'stamp');
  stamp.innerHTML = `<div class="stamp-inner">审 阅<span class="stamp-no">NO.${pad3(ctx.issueNo)}</span></div>`;
  titleblock.appendChild(title);
  titleblock.appendChild(stamp);
  const sub = el('div', 'masthead-sub', escapeHtml(meta.title || 'CS 保研信息日报'));
  titleblock.appendChild(sub);
  mast.appendChild(titleblock);
  mast.appendChild(el('div', 'masthead-rule'));

  /* Ticker */
  if (ctx.phrases.length) {
    const ticker = el('div', 'ticker');
    ticker.innerHTML = `<span class="ticker-tag">号外</span>` +
      `<div class="ticker-track"><div class="ticker-move">${
        ctx.phrases.map(p => `<span>${escapeHtml(p)}</span>`).join('<span class="tk-sep">◆</span>')
      }</div></div>`;
    mast.appendChild(ticker);
  }
  newspaper.appendChild(mast);

  /* ---- 付印工单 docket（有 stats 才渲染）---- */
  if (ctx.stats) {
    const docket = makePrintDocket(ctx.stats, 0.14);
    if (docket) newspaper.appendChild(docket);
  }

  /* ---- 免责声明 colophon ---- */
  if (meta.colophon) {
    newspaper.appendChild(el('p', 'colophon ink-reveal', escapeHtml(meta.colophon)));
    const last = newspaper.lastChild;
    last.style.setProperty('--ink-delay', '0.1s');
  }

  /* ---- 导语 standfirst ---- */
  if (standfirstBlock) {
    const sf = el('p', 'standfirst ink-reveal');
    sf.style.setProperty('--ink-delay', '0.18s');
    sf.textContent = standfirstBlock.nodes.map(n => n.textContent).join(' ').replace(/\s+/g, ' ').trim();
    newspaper.appendChild(sf);
  }

  /* ---- 各栏目（按 lead → commentary → briefs → advisory → generic 顺序）---- */
  const order = ['lead', 'commentary', 'briefs', 'advisory'];
  let delay = 0.3;
  order.forEach(role => {
    const block = blockByRole(blocks, role);
    if (!block) return;
    const sec = el('section', `section section-${role}`);
    sec.id = `sec-${role}`;
    sec.appendChild(makeSectionLabel(role, delay));
    const body = makeBody(role, block, delay);
    /* 头版头条插入跨栏引文 */
    if (role === 'lead' && pullQuote) {
      const pq = el('blockquote', 'pullquote ink-reveal', escapeHtml(pullQuote));
      pq.style.setProperty('--ink-delay', `${delay + 0.12}s`);
      body.insertBefore(pq, body.firstChild);
    }
    sec.appendChild(body);
    newspaper.appendChild(sec);
    delay += 0.18;
  });

  /* ---- 未知栏目（保底，不丢内容）---- */
  blocks.filter(b => b.role === 'generic').forEach(block => {
    const sec = el('section', `section section-generic`);
    sec.appendChild(makeSectionLabel(block.title, delay));
    const body = el('div', 'commentary-body ink-reveal');
    body.style.setProperty('--ink-delay', `${delay + 0.08}s`);
    for (const n of block.nodes) body.appendChild(n);
    sec.appendChild(body);
    newspaper.appendChild(sec);
    delay += 0.12;
  });

  /* ---- 报尾 ---- */
  const foot = el('footer', 'colophon-foot ink-reveal',
    `${escapeHtml(meta.title || 'CS 保研信息日报')} · 第 ${pad3(ctx.issueNo)} 期 · ${formatDate(ctx.date)} ${ctx.weekday}` +
    `<span class="cf-end">— 完 —</span>`);
  foot.style.setProperty('--ink-delay', `${delay}s`);
  newspaper.appendChild(foot);

  /* ---- 剪报按钮 ---- */
  attachClippable(newspaper);

  return { newspaper, sections: ['lead', 'commentary', 'briefs', 'advisory'].filter(r => blockByRole(blocks, r)) };
}

function attachClippable(root) {
  root.querySelectorAll('.lead-body li, .commentary-body li, .briefs-body li, .advisory-body li').forEach(li => {
    li.classList.add('clippable');
    const btn = el('button', 'clip-btn', SCISSORS_SVG);
    btn.type = 'button';
    btn.setAttribute('aria-label', '剪报：复制本段');
    li.appendChild(btn);
  });
}

/* =====================================================================
   付印工单 Docket —— 把这期报纸的加工过程印在报头下
   ===================================================================== */
async function fetchStats(date) {
  try {
    const res = await fetch(`./data/stats/${date}.json`, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

function makeDocketDetailLine(label, value, cls) {
  return `<span class="dk-cell"><span class="dk-k">${label}</span> <b class="${cls || ''}">${value}</b></span>`;
}

function makePrintDocket(stats, delay) {
  if (!stats) return null;
  const raw = Number(stats.raw_messages) || 0;
  const kept = Number(stats.kept_messages) || 0;
  const dropped = Number(stats.dropped_total) || 0;
  const speakers = Number(stats.speakers) || 0;
  const items = Number(stats.items) || 0;
  const quotes = Number(stats.quotes) || 0;

  const box = el('div', 'print-docket ink-reveal');
  box.style.setProperty('--ink-delay', `${delay}s`);
  box.style.setProperty('--rule-delay', `${delay}s`);

  const head = el('button', 'docket-head');
  head.type = 'button';
  head.setAttribute('aria-expanded', 'false');
  head.innerHTML =
    `<span class="docket-title">付印工单</span>` +
    `<span class="docket-flow">` +
    `<span class="dk-step">原始 <b>${raw}</b> 条</span>` +
    (dropped ? `<span class="dk-arrow">→</span><span class="dk-step">去噪 <b class="neg">−${dropped}</b></span>` : ``) +
    `<span class="dk-arrow">→</span><span class="dk-step">有效 <b>${kept}</b> 条</span>` +
    `<span class="dk-dot">·</span><span class="dk-step"><b>${speakers}</b> 位发言者</span>` +
    `<span class="dk-arrow">→</span><span class="dk-step">要点 <b>${items}</b></span>` +
    `<span class="dk-dot">·</span><span class="dk-step">原话 <b>${quotes}</b></span>` +
    `<span class="dk-arrow dk-final">付印</span>` +
    `</span>` +
    `<span class="docket-caret" aria-hidden="true">▾</span>`;
  box.appendChild(head);

  const detail = el('div', 'docket-detail');
  detail.hidden = true;
  const cells = [
    makeDocketDetailLine('非文本', Number(stats.dropped_non_text) || 0, 'neg'),
    makeDocketDetailLine('纯 emoji', Number(stats.dropped_emoji_only) || 0),
    makeDocketDetailLine('应答语气词', Number(stats.dropped_noise_token) || 0),
    makeDocketDetailLine('同人刷屏', Number(stats.dropped_flood) || 0),
    makeDocketDetailLine('分块', Number(stats.chunks) || 0),
    makeDocketDetailLine('抽取模式', stats.structured ? '引用式结构化' : '自由摘要'),
  ];
  if (stats.model) cells.push(makeDocketDetailLine('模型', escapeHtml(String(stats.model))));
  const ev = stats.eval;
  if (ev && typeof ev.faithfulness === 'number') {
    cells.push(
      `<span class="dk-cell dk-eval">忠实度 <b>${ev.faithfulness}/5</b> · 召回 <b>${ev.recall}/5</b></span>`
    );
  }
  detail.innerHTML = cells.join('<span class="dk-sep">／</span>');
  box.appendChild(detail);

  head.addEventListener('click', () => {
    const open = detail.hidden;
    detail.hidden = !open;
    head.setAttribute('aria-expanded', String(open));
    box.classList.toggle('open', open);
  });
  return box;
}

/* =====================================================================
   原话引用排版 —— “……”／「……」（User_N @ t）标成可辨识的原话
   ===================================================================== */
const QUOTE_PAIR_RE = /[“][^“”]{2,120}[”]|「[^「」]{2,120}」(?:（[^（）]{2,40}）)?/g;

function decorateSourceQuotes(root) {
  const skip = 'script, style, .src-quote, .clip-btn, .print-docket, .pullquote';
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (
      (n.parentElement && n.parentElement.closest(skip)) || !/[“「]/.test(n.nodeValue)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT
    ),
  });
  const targets = [];
  while (walker.nextNode()) targets.push(walker.currentNode);
  for (const node of targets) {
    const text = node.nodeValue;
    QUOTE_PAIR_RE.lastIndex = 0;
    let m;
    let last = 0;
    let matched = false;
    const frag = document.createDocumentFragment();
    while ((m = QUOTE_PAIR_RE.exec(text))) {
      matched = true;
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      const span = document.createElement('span');
      span.className = 'src-quote';
      span.textContent = m[0];
      frag.appendChild(span);
      last = m.index + m[0].length;
    }
    if (!matched) continue;
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag, node);
  }
}

/* =====================================================================
   TOC 目录 + scroll-spy
   ===================================================================== */
function buildToc(roles) {
  const list = elements.tocList;
  if (!list) return;
  list.innerHTML = '';
  const links = [];
  roles.forEach(role => {
    const label = LABELS[role];
    if (!label) return;
    const sec = document.getElementById(`sec-${role}`);
    if (!sec) return;
    const a = el('a', null, `<span class="toc-no">${label.no}</span>${label.name}`);
    a.href = `#sec-${role}`;
    a.addEventListener('click', e => { e.preventDefault(); sec.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    list.appendChild(a);
    links.push({ a, sec });
  });
  elements.toc.hidden = links.length === 0;
  state.tocObserver?.disconnect();
  if (!links.length) return;
  const obs = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (!en.isIntersecting) return;
      const hit = links.find(l => l.sec === en.target);
      if (hit) links.forEach(l => l.a.classList.toggle('active', l === hit));
    });
  }, { rootMargin: '-25% 0px -65% 0px', threshold: 0 });
  links.forEach(l => obs.observe(l.sec));
  state.tocObserver = obs;
}

/* =====================================================================
   动效触发
   ===================================================================== */
function fireInkRoller() {
  const r = elements.inkRoller;
  if (!r || prefersReducedMotion()) return;
  r.classList.remove('rolling');
  void r.offsetWidth;
  r.classList.add('rolling');
}

function showToast(msg) {
  const t = elements.toast;
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => t.classList.remove('show'), 1800);
}

/* =====================================================================
   加载与渲染
   ===================================================================== */
function showLoading(isLoading) {
  if (elements.loadingState) elements.loadingState.classList.toggle('hidden', !!(!isLoading));
  elements.loadingState.style.display = isLoading ? '' : 'none';
  if (isLoading) {
    const news = elements.reportContent.querySelector('.newspaper');
    if (news) news.classList.remove('ready');
  }
}
function showMessage(cls, msg) {
  elements.reportContent.innerHTML = `<div class="${cls}">${escapeHtml(msg)}</div>`;
}

function showHomeView() {
  closeDateSwitcher();
  elements.homeView.hidden = false;
  elements.readerView.hidden = true;
  if (elements.pressroomView) elements.pressroomView.hidden = true;
  document.title = '保研日报 · CS 保研信息日报';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function showReaderView() {
  elements.homeView.hidden = true;
  elements.readerView.hidden = false;
  if (elements.pressroomView) elements.pressroomView.hidden = true;
}
function showPressroomView() {
  closeDateSwitcher();
  elements.homeView.hidden = true;
  elements.readerView.hidden = true;
  if (elements.pressroomView) elements.pressroomView.hidden = false;
  document.title = '印房 · 保研日报';
  window.scrollTo({ top: 0, behavior: 'smooth' });
  loadPressTotals();
}

async function loadPressTotals() {
  const fields = [
    ['pt-raw', 'total_raw_messages'],
    ['pt-dropped', 'total_dropped_total'],
    ['pt-quotes', 'total_quotes'],
    ['pt-editions', 'editions'],
  ];
  try {
    const res = await fetch('./data/stats/summary.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const s = await res.json();
    for (const [id, key] of fields) {
      const node = document.getElementById(id);
      if (node) node.textContent = Number(s[key] || 0).toLocaleString();
    }
    if (elements.homeSiftCount) {
      elements.homeSiftCount.textContent = `${Number(s.total_dropped_total || 0).toLocaleString()} 条`;
    }
  } catch (e) {
    console.error(e);
    if (elements.homeSiftCount) elements.homeSiftCount.textContent = '— 条';
  }
}

function setReportCount(n) {
  const span = elements.reportCount?.querySelector('.chip-num');
  if (span) span.textContent = String(n);
  if (elements.searchMeta) elements.searchMeta.textContent = `资料室 · 共 ${n} 卷`;
}

async function loadReport(date) {
  const index = state.manifest.findIndex(item => item.date === date);
  const item = index >= 0 ? state.manifest[index] : state.manifest[0];
  if (!item) {
    showReaderView();
    elements.loadingState.style.display = 'none';
    showMessage('empty-state', '暂无可展示的日报。');
    return;
  }

  showReaderView();
  state.activeDate = item.date;
  state.activeIndex = index >= 0 ? index : 0;
  const issueNo = issueNumberOf(state.activeIndex);
  renderDateSwitcher();
  closeDateSwitcher();
  showLoading(true);

  if (state.abortController) state.abortController.abort();
  state.abortController = new AbortController();
  const signal = state.abortController.signal;

  try {
    if (!item.md_path) throw new Error('Missing report path');
    const [response, stats] = await Promise.all([
      fetch(`./data/${item.md_path}`, { cache: 'no-store', signal }),
      fetchStats(item.date),
    ]);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const markdown = await response.text();
    const safeHtml = renderMarkdown(markdown);

    const ctx = {
      date: item.date,
      issueNo,
      issueRoman: toRoman(issueNo),
      weekday: weekdayOf(item.date),
      phrases: buildTickerPhrases(markdown),
      stats,
    };
    const { newspaper, sections } = buildNewspaper(safeHtml, ctx);
    decorateSourceQuotes(newspaper);

    elements.reportContent.replaceChildren(newspaper);
    elements.loadingState.style.display = 'none';
    document.title = `${formatDate(item.date)} · 第 ${issueNo} 期 · 保研日报`;

    buildToc(sections);
    applyViewMode();

    requestAnimationFrame(() => {
      newspaper.classList.add('ready');
      newspaper.classList.add('is-flipping');
      setTimeout(() => newspaper.classList.remove('is-flipping'), 700);
      fireInkRoller();
    });
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error(err);
    elements.loadingState.style.display = 'none';
    showMessage('error-state', '日报内容加载失败，请稍后刷新重试。');
  }
}

function buildTickerPhrases(markdown) {
  const m = markdown.match(/##\s*今日概览\s*\n+([\s\S]*?)(?=\n##\s|$)/);
  if (!m) return [];
  const overview = m[1].replace(/[#*`_>]/g, '').replace(/\s+/g, ' ').trim();
  return overview.split(/[，,；;。]/).map(s => s.trim()).filter(s => s.length >= 3 && s.length <= 22).slice(0, 10);
}

/* =====================================================================
   主页
   ===================================================================== */
function renderHomeView() {
  if (!elements.latestReportDate || !elements.homeReportCount || !elements.recentReportsList) return;
  elements.homeReportCount.textContent = `${state.manifest.length} 期`;
  if (!state.manifest.length) {
    elements.latestReportDate.textContent = '暂无';
    elements.recentReportsList.innerHTML = '<div class="archive-empty">暂无可展示的日报。</div>';
    return;
  }
  const [latest] = state.manifest;
  elements.latestReportDate.textContent = formatHomeDate(latest.date);
  elements.recentReportsList.innerHTML = state.manifest.slice(0, 8).map((item, i) => {
    const tag = i === 0 ? '<span class="tag">最新</span>' : '';
    const issue = issueNumberOf(i);
    return `
      <a class="archive-item" href="#${item.date}" data-date="${item.date}">
        <span class="archive-item-date">${formatHomeDate(item.date)} ${tag}<br><span style="font-size:.66rem;opacity:.7">NO.${pad3(issue)}</span></span>
        <span class="archive-item-summary">正在排印…</span>
        <span class="archive-item-arrow">阅读 →</span>
      </a>`;
  }).join('');
  loadRecentReportSummaries();
}

async function loadRecentReportSummaries() {
  if (!elements.recentReportsList || !state.manifest.length) return;
  const items = state.manifest.slice(0, 8);
  await Promise.all(items.map(async (item) => {
    const link = elements.recentReportsList.querySelector(`[data-date="${item.date}"]`);
    const sum = link?.querySelector('.archive-item-summary');
    if (!sum) return;
    try {
      if (!item.md_path) throw new Error('Missing path');
      const res = await fetch(`./data/${item.md_path}`, { cache: 'force-cache' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const md = await res.text();
      sum.textContent = extractOverview(md);
    } catch (e) {
      console.error(e);
      sum.textContent = '概览加载失败，点击查看正文。';
    }
  }));
}

function extractOverview(md) {
  const m = md.match(/##\s*今日概览\s*\n+([\s\S]*?)(?=\n##\s|$)/);
  if (!m) return '本期概览暂不可用，点击查看日报正文。';
  const line = m[1].split(/\n+/).map(s => s.trim()).find(s => s && !s.startsWith('>'));
  if (!line) return '本期概览暂不可用，点击查看日报正文。';
  return line.replace(/^([-+*]|\d+[.)])\s+/, '').replace(/[#*`_>]/g, '').trim();
}

/* =====================================================================
   日期切换器
   ===================================================================== */
function setDateSwitcherOpen(isOpen) {
  state.dateSwitcherOpen = isOpen;
  if (elements.dateSwitcherPopover) elements.dateSwitcherPopover.hidden = !isOpen;
  elements.currentDateBtn?.setAttribute('aria-expanded', String(isOpen));
}
function closeDateSwitcher() { if (state.dateSwitcherOpen) setDateSwitcherOpen(false); }
function toggleDateSwitcher() { setDateSwitcherOpen(!state.dateSwitcherOpen); }
function navigateDate(offset) {
  const next = state.manifest[state.activeIndex + offset];
  if (next) setHashDate(next.date);
}

function renderDateSwitcher() {
  if (!elements.dateSwitcherList || !elements.dateSwitcherCurrent) return;
  if (!state.manifest.length) {
    elements.dateSwitcherCurrent.textContent = '暂无';
    elements.dateSwitcherList.innerHTML = '<div class="archive-empty">暂无日报。</div>';
    [elements.prevDateBtn, elements.nextDateBtn, elements.currentDateBtn].forEach(b => b && (b.disabled = true));
    return;
  }
  const issueNo = issueNumberOf(state.activeIndex);
  const displayDate = state.activeDate || (state.manifest[0] && state.manifest[0].date);
  if (elements.dcIssue) elements.dcIssue.textContent = `ISSUE NO.${pad3(issueNo)} · ${toRoman(issueNo)}`;
  elements.dateSwitcherCurrent.textContent = formatDate(displayDate);
  elements.prevDateBtn.disabled = state.activeIndex >= state.manifest.length - 1;
  elements.nextDateBtn.disabled = state.activeIndex <= 0;
  elements.currentDateBtn.disabled = false;
  elements.dateSwitcherList.innerHTML = state.manifest.map((item, i) => {
    const active = item.date === state.activeDate;
    return `<button class="date-item${active ? ' active' : ''}" data-date="${item.date}" aria-pressed="${active}">${formatDate(item.date)}</button>`;
  }).join('');
}

/* =====================================================================
   视图切换 头版 / 全文
   ===================================================================== */
function applyViewMode() {
  const news = elements.reportContent.querySelector('.newspaper');
  if (news) news.classList.toggle('mode-front', state.viewMode === 'front');
  elements.viewToggle?.querySelectorAll('button').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === state.viewMode);
  });
}
function initViewToggle() {
  elements.viewToggle?.addEventListener('click', e => {
    const b = e.target.closest('button[data-mode]');
    if (!b) return;
    state.viewMode = b.dataset.mode;
    applyViewMode();
  });
}

/* =====================================================================
   剪报（事件委托）
   ===================================================================== */
function initClipping() {
  elements.reportContent?.addEventListener('click', e => {
    const btn = e.target.closest('.clip-btn');
    if (!btn) return;
    const host = btn.closest('.clippable');
    if (!host) return;
    const text = (host.textContent || '').replace(/\s+\n/g, '\n').trim();
    const payload = `【保研日报 · 第 ${issueNumberOf(state.activeIndex)} 期 · ${state.activeDate}】\n${text}`;
    const done = () => {
      btn.classList.add('copied');
      showToast('已剪报 · 已复制到剪贴板');
      setTimeout(() => btn.classList.remove('copied'), 1400);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(payload).then(done).catch(() => fallbackCopy(payload, done));
    } else fallbackCopy(payload, done);
  });
}
function fallbackCopy(text, done) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    done();
  } catch {
    showToast('剪报失败，请手动复制');
  }
}

/* =====================================================================
   搜索 · 资料室检索卡
   ===================================================================== */
let searchDebounce = null;
function openSearch() {
  closeDateSwitcher();
  elements.searchModal.hidden = false;
  elements.searchModal.setAttribute('aria-hidden', 'false');
  elements.searchInput.focus();
  prefetchAllReports();
}
function closeSearch() {
  elements.searchModal.hidden = true;
  elements.searchModal.setAttribute('aria-hidden', 'true');
  elements.searchInput.value = '';
  elements.searchResults.innerHTML = '<div class="search-placeholder">输入关键词，开始在全部日报中检索…</div>';
}
async function prefetchAllReports() {
  if (state.isSearching || Object.keys(state.reportsCache).length >= state.manifest.length) return;
  state.isSearching = true;
  try {
    await Promise.all(state.manifest.map(async (item) => {
      if (state.reportsCache[item.date]) return;
      const res = await fetch(`./data/${item.md_path}`, { cache: 'force-cache' });
      if (res.ok) state.reportsCache[item.date] = await res.text();
    }));
    if (elements.searchInput.value.trim()) performSearch(elements.searchInput.value);
  } catch (e) { console.error(e); }
  finally { state.isSearching = false; }
}
function performSearch(query) {
  if (!query.trim()) {
    elements.searchResults.innerHTML = '<div class="search-placeholder">输入关键词，开始在全部日报中检索…</div>';
    return;
  }
  const kws = query.trim().toLowerCase().split(/\s+/);
  const results = [];
  for (const item of state.manifest) {
    const text = state.reportsCache[item.date];
    if (!text) continue;
    const low = text.toLowerCase();
    if (!kws.every(k => low.includes(k))) continue;
    const idx = low.indexOf(kws[0]);
    const start = Math.max(0, idx - 40);
    const end = Math.min(text.length, idx + 120);
    let snip = text.substring(start, end).replace(/[\r\n]+/g, ' ').replace(/[#*`_>]/g, '');
    snip = escapeHtml(snip);
    if (start > 0) snip = '…' + snip;
    if (end < text.length) snip += '…';
    kws.forEach(k => {
      const ek = escapeHtml(k);
      snip = snip.replace(new RegExp(`(${ek.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>');
    });
    results.push({ date: item.date, snip });
  }
  if (!results.length) {
    elements.searchResults.innerHTML = '<div class="search-placeholder">资料室里没有找到这条线索。</div>';
    return;
  }
  elements.searchResults.innerHTML = results.map(r => `
    <a href="#${r.date}" class="search-result-item" data-date="${r.date}">
      <h3 class="search-result-title">${formatDate(r.date)}</h3>
      <div class="search-result-snippet">${r.snip}</div>
    </a>`).join('');
  elements.searchResults.querySelectorAll('.search-result-item').forEach(it => {
    it.addEventListener('click', e => { e.preventDefault(); setHashDate(it.dataset.date); closeSearch(); });
  });
}
function initSearch() {
  if (!elements.searchBtn) return;
  elements.searchBtn.addEventListener('click', openSearch);
  elements.closeSearchBtn.addEventListener('click', closeSearch);
  elements.searchBackdrop.addEventListener('click', closeSearch);
  elements.searchInput.addEventListener('input', e => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => performSearch(e.target.value), 220);
  });
}

/* =====================================================================
   路由 / 主流程
   ===================================================================== */
function goHome() {
  if (window.location.hash) history.pushState('', '', window.location.pathname + window.location.search);
  showHomeView();
}

function initDateSwitcher() {
  elements.prevDateBtn?.addEventListener('click', () => navigateDate(1));
  elements.nextDateBtn?.addEventListener('click', () => navigateDate(-1));
  elements.currentDateBtn?.addEventListener('click', toggleDateSwitcher);
  elements.dateSwitcherList?.addEventListener('click', e => {
    const b = e.target.closest('.date-item');
    if (!b) return;
    setHashDate(b.dataset.date);
    closeDateSwitcher();
  });
  document.addEventListener('click', e => {
    if (!state.dateSwitcherOpen || !elements.dateSwitcher) return;
    if (!elements.dateSwitcher.contains(e.target)) closeDateSwitcher();
  });
}

function initHome() {
  elements.homeLink?.addEventListener('click', e => { e.preventDefault(); goHome(); });
  elements.readLatestBtn?.addEventListener('click', () => {
    const latest = state.manifest[0];
    if (latest) setHashDate(latest.date);
  });
  elements.homeSearchBtn?.addEventListener('click', openSearch);
  elements.pressroomBackBtn?.addEventListener('click', goHome);
}

function initKeyboard() {
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || '');
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearch(); return; }
    if (e.key === 'Escape') {
      if (!elements.searchModal.hidden) { closeSearch(); return; }
      if (state.dateSwitcherOpen) { closeDateSwitcher(); return; }
    }
    if (typing || elements.readerView.hidden) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); navigateDate(1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); navigateDate(-1); }
  });
}

async function loadManifest() {
  showLoading(true);
  try {
    const res = await fetch('./data/reports.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.manifest = await res.json();
    if (!Array.isArray(state.manifest) || !state.manifest.length) {
      state.manifest = [];
      setReportCount(0);
      renderHomeView();
      renderDateSwitcher();
      elements.loadingState.style.display = 'none';
      showMessage('empty-state', '还没有可展示的日报，等下一次印好后这里会自动更新。');
      showHomeView();
      return;
    }
    renderHomeView();
    setReportCount(state.manifest.length);
    loadPressTotals();
    const target = getHashDate();
    if (!target) {
      elements.loadingState.style.display = 'none';
      renderDateSwitcher();
      showHomeView();
      return;
    }
    if (target === 'pressroom') {
      elements.loadingState.style.display = 'none';
      showPressroomView();
      return;
    }
    if (!state.manifest.some(i => i.date === target)) { setHashDate(state.manifest[0].date); return; }
    await loadReport(target);
  } catch (err) {
    console.error(err);
    showReaderView();
    setReportCount(0);
    elements.reportCount && (elements.reportCount.textContent = '读取失败');
    elements.loadingState.style.display = 'none';
    showMessage('error-state', '日报索引加载失败，请确认 pages/data 已成功生成。');
  }
}

window.addEventListener('hashchange', () => {
  if (!state.manifest.length) return;
  const h = getHashDate();
  if (!h) { showHomeView(); return; }
  if (h === 'pressroom') { showPressroomView(); return; }
  if (!state.manifest.some(i => i.date === h)) { setHashDate(state.manifest[0].date); return; }
  loadReport(h);
});

/* ---------- 启动 ---------- */
cacheElements();
initTheme();
initDateSwitcher();
initSearch();
initHome();
initViewToggle();
initClipping();
initKeyboard();
loadManifest();
