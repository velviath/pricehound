const params    = new URLSearchParams(location.search);
const productId = parseInt(params.get('id'));
const token     = localStorage.getItem('ph_token');

const DEMO_PRODUCT_URLS = new Set([
  'https://www.amazon.com/dp/B09XS7JWHH',
  'https://www.amazon.com/dp/B0BDHWDR12',
  'https://www.amazon.com/dp/B09TMF6741',
]);

const DEMO_WATCHER_COUNTS = {
  'https://www.amazon.com/dp/B09XS7JWHH': 47,
  'https://www.amazon.com/dp/B0BDHWDR12': 128,
  'https://www.amazon.com/dp/B09TMF6741': 92,
};

let priceChart        = null;
let productData       = null;
let rawHistory        = [];
let chartMode         = 'all';
let currentPeriod     = 'week';
let userStatus        = null;
let alertMode         = 'set';
let alertCurrentPrice = 0;

// ── Currency conversion ─────────────────────────────────────────────────────
const CURRENCY_SYMBOLS = {
  USD: '$',    EUR: '€',    GBP: '£',    CAD: 'CA$', AUD: 'A$',
  CHF: 'Fr ',  JPY: '¥',   CNY: '¥',    HKD: 'HK$', SGD: 'S$',
  KRW: '₩',   INR: '₹',   SEK: 'kr ',  NOK: 'kr ', DKK: 'kr ',
  PLN: 'zł ', CZK: 'Kč ', HUF: 'Ft ', RON: 'lei ',BGN: 'лв ',
  UAH: '₴',   TRY: '₺',   AED: 'د.إ ',SAR: '﷼ ', ILS: '₪',
  BRL: 'R$',  MXN: 'MX$', ZAR: 'R ',  NZD: 'NZ$',THB: '฿',
  MYR: 'RM ', IDR: 'Rp ', PHP: '₱',
};
let _allRates  = {};
let _xRate     = null;
let _xCurrency = 'USD';

async function initCurrency() {
  _xCurrency = localStorage.getItem('ph_currency') || 'USD';
  try {
    const r = await fetch('https://open.er-api.com/v6/latest/USD');
    const d = await r.json();
    if (d.result === 'success' && d.rates) {
      _allRates = d.rates;
      _xRate    = d.rates[_xCurrency] || null;
    }
  } catch {}
}

// productCurrency: the currency the price is stored in (from DB)
function formatPrice(amount, productCurrency) {
  if (amount == null) return '—';
  const n    = Number(amount);
  const pCur = productCurrency || 'USD';
  const uCur = _xCurrency      || 'USD';
  // Same currency — display directly, no conversion needed
  if (pCur === uCur) {
    const sym = CURRENCY_SYMBOLS[uCur] || (uCur + ' ');
    return sym + n.toFixed(2);
  }
  // Cross-rate: pCur → USD → uCur
  const pRate = pCur === 'USD' ? 1 : (_allRates[pCur] || 0);
  const uRate = uCur === 'USD' ? 1 : (_allRates[uCur] || 0);
  if (!pRate || !uRate) {
    // Rates not loaded — fall back to product's own currency
    const sym = CURRENCY_SYMBOLS[pCur] || (pCur + ' ');
    return sym + n.toFixed(2);
  }
  const converted = (n / pRate) * uRate;
  const sym = CURRENCY_SYMBOLS[uCur] || (uCur + ' ');
  return '~' + sym + converted.toFixed(2);
}

function isApprox(productCurrency) {
  const pCur = productCurrency || 'USD';
  const uCur = _xCurrency      || 'USD';
  if (pCur === uCur) return false;
  const pRate = pCur === 'USD' ? 1 : (_allRates[pCur] || 0);
  const uRate = uCur === 'USD' ? 1 : (_allRates[uCur] || 0);
  return !!(pRate && uRate);
}

// ── Approx popup ────────────────────────────────────────────────────────────
const approxPopup = document.getElementById('approx-popup');
document.getElementById('p-approx-btn').addEventListener('click', (e) => {
  const rect = e.currentTarget.getBoundingClientRect();
  const pCur = productData?.currency || 'USD';
  const _REGIONAL = { GBP:'.co.uk', EUR:'.de / .fr', CAD:'.ca', AUD:'.com.au', JPY:'.co.jp' };
  const _regionalTip = _REGIONAL[_xCurrency] ? `<br>For exact prices, use <strong>${_REGIONAL[_xCurrency]}</strong> links.` : '';
  const origPrice = productData?.current_price != null
    ? (CURRENCY_SYMBOLS[pCur] || (pCur + ' ')) + Number(productData.current_price).toFixed(2)
    : null;
  const origLine = origPrice ? `Original price: <strong>${origPrice}</strong><br>` : '';
  approxPopup.innerHTML =
    `${origLine}Priced in <strong>${pCur}</strong>, shown as <strong>${_xCurrency}</strong>.${_regionalTip}<br><a href="https://www.exchangerate-api.com" target="_blank" rel="noopener">Live rates source ↗</a>`;
  const spaceBelow = window.innerHeight - rect.bottom;
  if (spaceBelow < 140) {
    approxPopup.style.top    = '';
    approxPopup.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
  } else {
    approxPopup.style.bottom = '';
    approxPopup.style.top    = (rect.bottom + 8) + 'px';
  }
  let left = rect.left;
  if (left + 240 > window.innerWidth - 12) left = window.innerWidth - 252;
  approxPopup.style.left    = Math.max(12, left) + 'px';
  approxPopup.style.display = 'block';
  e.stopPropagation();
});
document.addEventListener('click', (e) => {
  if (!approxPopup.contains(e.target)) approxPopup.style.display = 'none';
});

// ── Navbar ─────────────────────────────────────────────────────────────────
if (token) {
  document.getElementById('nav-right').innerHTML =
    `<a class="btn-nav btn-nav-outline" href="/dashboard">Dashboard</a>`;
}

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'toast' + (type ? ' ' + type : '');
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function timeAgo(isoStr) {
  if (!isoStr) return null;
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Load product ───────────────────────────────────────────────────────────
async function loadProduct(period = 'week') {
  if (!productId) { showError(); return; }
  try {
    const cur = _xCurrency || 'USD';
    const res = await fetch(`/api/products/${productId}?period=${period}&display_currency=${cur}`);
    if (res.status === 404) { showError(); return; }
    if (!res.ok) throw new Error();
    productData = await res.json();
    rawHistory  = productData.price_history || [];
    renderProduct(productData);
    renderChart(filterHistory(rawHistory));
  } catch { showError(); }
}

async function loadHistoryOnly(period) {
  if (!productId) return;
  try {
    const res = await fetch(`/api/products/${productId}/history?period=${period}`);
    if (!res.ok) return;
    rawHistory = await res.json();
    renderChart(filterHistory(rawHistory));
  } catch {}
}

function showError() {
  document.getElementById('skeleton-view').style.display = 'none';
  document.getElementById('product-view').style.display  = 'none';
  document.getElementById('error-view').style.display    = 'block';
  const footer = document.querySelector('footer');
  if (footer) footer.style.display = 'none';
}

function renderProduct(p) {
  document.getElementById('skeleton-view').style.display = 'none';
  document.getElementById('product-view').style.display  = 'block';
  requestAnimationFrame(() => requestAnimationFrame(initIndicators));

  const imgWrap = document.getElementById('img-wrap');
  if (p.image_url) {
    imgWrap.innerHTML = `<img class="product-img" src="${esc(p.image_url)}" alt="${esc(p.name || '')}"
      onerror="this.parentElement.innerHTML='<div class=product-img-placeholder>📦</div>'" />`;
  } else {
    imgWrap.innerHTML = '<div class="product-img-placeholder">📦</div>';
  }

  document.getElementById('p-source').textContent = p.source || '';
  document.getElementById('p-name').textContent   = p.name || 'Unknown product';
  document.title = (p.name || 'Product') + ' — PriceHound';
  document.getElementById('btn-source').href = p.url;

  document.getElementById('p-price').textContent =
    p.current_price != null ? formatPrice(p.current_price, p.currency) : '—';
  document.getElementById('p-approx-btn').style.display =
    (p.current_price != null && isApprox(p.currency)) ? '' : 'none';

  if (p.price_history && p.price_history.length > 1) {
    const first = p.price_history[0].price;
    const cur   = p.current_price;
    const pct   = ((cur - first) / first * 100).toFixed(1);
    const cls   = pct < 0 ? 'down' : pct > 0 ? 'up' : 'neutral';
    const arrow = pct < 0 ? '↓' : pct > 0 ? '↑' : '→';
    document.getElementById('p-change-badge').innerHTML =
      `<span class="price-badge ${cls}">${arrow} ${Math.abs(pct)}% since tracking began</span>`;
    const oldEl = document.getElementById('p-price-old');
    if (first !== cur) { oldEl.textContent = formatPrice(first, p.currency); oldEl.style.display = ''; }
  }

  updateAvailability(p.availability || 'available');
  updateLastChecked(p.last_checked);
  document.getElementById('price-meta-row').style.display = 'flex';
  document.getElementById('btn-refresh').style.display    = token ? '' : 'none';

  const wc = DEMO_WATCHER_COUNTS[p.url] ?? p.watcher_count ?? 0;
  document.getElementById('p-watchers').innerHTML =
    `👁 <strong>${wc}</strong> ${wc === 1 ? 'person' : 'people'} tracking this`;

  if (p.ai_insight) {
    document.getElementById('insight-text').textContent   = p.ai_insight;
    document.getElementById('insight-card').style.display = 'flex';
    const noteEl = document.getElementById('insight-currency-note');
    const pCur = p.currency || 'USD';
    noteEl.textContent = (pCur !== (_xCurrency || 'USD')) ? `· prices in ${pCur}` : '';
  }

  const note = document.getElementById('chart-demo-note');
  if (note) note.style.display = (DEMO_PRODUCT_URLS.has(p.url)) ? 'block' : 'none';
}

function updateAvailability(availability) {
  const banner   = document.getElementById('unavail-banner');
  const text     = document.getElementById('unavail-text');
  const label    = document.getElementById('price-last-label');
  const priceEl  = document.getElementById('p-price');
  const unavail  = availability === 'unavailable' || availability === 'url_error';
  banner.style.display = unavail ? 'flex' : 'none';
  label.style.display  = unavail ? 'block' : 'none';
  if (unavail) {
    text.textContent = availability === 'url_error'
      ? 'This product page no longer exists. Try re-adding with a fresh link.'
      : 'This listing is no longer available.';
    priceEl.classList.add('muted');
  } else {
    priceEl.classList.remove('muted');
  }
}

function updateLastChecked(isoStr) {
  const el = document.getElementById('p-last-checked');
  if (el) el.textContent = 'Checked ' + (timeAgo(isoStr) || 'just now');
  if (productData && isoStr) productData.last_checked = isoStr;
}

// ── Chart ──────────────────────────────────────────────────────────────────
function filterHistory(history) {
  if (chartMode === 'all' || history.length <= 1) return history;
  return history.filter((h, i) =>
    i === 0 || Math.abs(h.price - history[i - 1].price) > 0.001
  );
}

function niceStep(range, maxTicks) {
  if (range <= 0) return 5;
  const raw = range / maxTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  let s;
  if (norm < 1.5) s = 1;
  else if (norm < 3.5) s = 2;
  else if (norm < 7.5) s = 5;
  else s = 10;
  // Always round up to nearest multiple of 5
  return Math.max(5, Math.ceil((s * mag) / 5) * 5);
}

function renderChart(history) {
  const noDataEl = document.getElementById('chart-no-data');
  const noData = history.length === 0 || (chartMode === 'changes' && history.length < 2);
  if (noData) {
    if (priceChart) { priceChart.destroy(); priceChart = null; }
    document.getElementById('price-chart').style.display = 'none';
    noDataEl.style.display = 'flex';
    return;
  }
  document.getElementById('price-chart').style.display = '';
  noDataEl.style.display = 'none';

  const MAX_POINTS = 100;
  let displayHistory = history;
  if (history.length > MAX_POINTS) {
    const s = Math.ceil(history.length / MAX_POINTS);
    displayHistory = history.filter((_, i) => i % s === 0 || i === history.length - 1);
  }
  const labels = displayHistory.map(h =>
    new Date(h.checked_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  );

  // Pre-convert all prices to user display currency so y-axis ticks are clean multiples of 5
  const pCur   = productData?.currency || 'USD';
  const uCur   = _xCurrency || 'USD';
  const pRate  = pCur === 'USD' ? 1 : (_allRates[pCur] || 0);
  const uRate  = uCur === 'USD' ? 1 : (_allRates[uCur] || 0);
  const needsConv = pCur !== uCur && pRate && uRate;
  const toDisp    = n => needsConv ? (n / pRate) * uRate : n;
  const dispSym   = CURRENCY_SYMBOLS[uCur] || CURRENCY_SYMBOLS[pCur] || (pCur + ' ');
  const prefix    = (needsConv ? '~' : '') + dispSym;

  const data = displayHistory.map(h => toDisp(Number(h.price)));
  const pointRadius = displayHistory.length > 30 ? 0 : 4;
  const pointHoverRadius = displayHistory.length > 30 ? 4 : 6;

  const minP = data.length ? Math.min(...data) : 0;
  const maxP = data.length ? Math.max(...data) : 100;
  const range = maxP - minP;
  const step  = niceStep(range || maxP * 0.1, 5);
  const yMin  = Math.max(0, Math.floor(minP / step) * step - step);  // one extra tick below min
  const yMax  = Math.ceil(maxP  / step) * step + step;               // one extra tick above max

  if (priceChart) priceChart.destroy();
  const ctx = document.getElementById('price-chart').getContext('2d');
  priceChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: 'Price', data, borderColor: '#5C7A5C', backgroundColor: 'rgba(92,122,92,0.08)', borderWidth: 2.5, pointRadius, pointBackgroundColor: '#5C7A5C', pointHoverRadius, fill: true, tension: 0.35 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: '#2D3748', padding: 12, cornerRadius: 10, callbacks: {
          title: ctx => {
            const d = new Date(displayHistory[ctx[0].dataIndex].checked_at);
            const date = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
            return date + ' (' + time + ')';
          },
          label: c => ' ' + prefix + Number(c.parsed.y).toFixed(2)
        } }
      },
      scales: {
        x: { grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { font: { family: 'Plus Jakarta Sans', size: 12 }, color: '#4A5568', maxTicksLimit: 8, maxRotation: 0 } },
        y: { min: yMin, max: yMax, grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { stepSize: step, font: { family: 'Plus Jakarta Sans', size: 12 }, color: '#4A5568',
          callback: v => prefix + Math.round(Number(v))
        } }
      }
    }
  });
}

function movePeriodIndicator(btn) {
  const ind = document.querySelector('.period-indicator');
  if (!ind) return;
  ind.style.left  = btn.offsetLeft + 'px';
  ind.style.width = btn.offsetWidth + 'px';
}

function moveModeIndicator(btn) {
  const ind = document.querySelector('.mode-indicator');
  if (!ind) return;
  ind.style.left  = btn.offsetLeft + 'px';
  ind.style.width = btn.offsetWidth + 'px';
}

function initIndicators() {
  const activePeriod = document.querySelector('.period-btn.active');
  if (activePeriod) { const ind = document.querySelector('.period-indicator'); ind.style.transition = 'none'; movePeriodIndicator(activePeriod); requestAnimationFrame(() => { ind.style.transition = ''; }); }
  const activeMode = document.querySelector('.mode-btn.active');
  if (activeMode) { const ind = document.querySelector('.mode-indicator'); ind.style.transition = 'none'; moveModeIndicator(activeMode); requestAnimationFrame(() => { ind.style.transition = ''; }); }
}

document.querySelectorAll('.period-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    movePeriodIndicator(btn);
    currentPeriod = btn.dataset.period;
    await loadHistoryOnly(currentPeriod);
  });
});

document.querySelectorAll('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    moveModeIndicator(btn);
    chartMode = btn.dataset.mode;
    renderChart(filterHistory(rawHistory));
  });
});

// ── Live polling (30s) ─────────────────────────────────────────────────────
setInterval(async () => {
  if (productData && productData.last_checked) updateLastChecked(productData.last_checked);
  try {
    const res = await fetch(`/api/products/${productId}/status`);
    if (!res.ok) return;
    const s = await res.json();
    if (s.last_checked) updateLastChecked(s.last_checked);

    if (s.current_price != null && productData) {
      const priceChanged = Math.abs(s.current_price - (productData.current_price || 0)) > 0.001;
      if (priceChanged) {
        productData.current_price = s.current_price;
        const priceEl = document.getElementById('p-price');
        if (priceEl) priceEl.textContent = formatPrice(s.current_price, productData?.currency);
        showToast('Price updated!', 'success');
        // Refresh chart for the active period
        await loadHistoryOnly(currentPeriod);
        // Refresh AI insight only when price changed
        reloadAiInsight();
      }
    }
  } catch {}
}, 30000);

async function reloadAiInsight() {
  try {
    const res = await fetch(`/api/products/${productId}?period=all`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.ai_insight) {
      document.getElementById('insight-text').textContent = data.ai_insight;
      document.getElementById('insight-card').style.display = 'flex';
    }
  } catch {}
}

// ── User status + action buttons ───────────────────────────────────────────
async function loadUserStatus() {
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  try {
    const res = await fetch(`/api/products/${productId}/user-status`, { headers });
    userStatus = res.ok ? await res.json() : { tracking: false, alert: null, pause_reason: null };
  } catch { userStatus = { tracking: false, alert: null, pause_reason: null }; }
  renderActions();
  const pauseEl = document.getElementById('tracking-paused-notice');
  if (pauseEl && userStatus.tracking) {
    if (userStatus.pause_reason === 'inactive') {
      pauseEl.textContent = '⏸    Price tracking is paused — you haven\'t visited in a while. Refresh the price manually to resume.';
      pauseEl.style.display = 'block';
    }
  }
}

function renderActions() {
  const row = document.getElementById('action-row');
  if (!token) {
    row.innerHTML = `
      <button class="btn-add-primary" id="btn-add">Add to Track</button>
      <button class="btn-secondary-action" id="btn-setalert">Set Alert</button>`;
    row.querySelector('#btn-add').onclick     = goToLogin;
    row.querySelector('#btn-setalert').onclick = goToLogin;
    return;
  }
  if (!userStatus || !userStatus.tracking) {
    row.innerHTML = `
      <button class="btn-add-primary" id="btn-add">Add to Track</button>
      <button class="btn-secondary-action" id="btn-setalert">Set Alert</button>`;
    row.querySelector('#btn-add').onclick     = handleAdd;
    row.querySelector('#btn-setalert').onclick = () => openAlertModal('set');
    return;
  }
  const alertBtn = userStatus.alert
    ? `<button class="btn-secondary-action" id="btn-editalert">Edit target</button>`
    : `<button class="btn-secondary-action" id="btn-setalert">Set Alert</button>`;
  row.innerHTML = `
    <button class="btn-delete" id="btn-delete">Delete</button>
    ${alertBtn}`;
  row.querySelector('#btn-delete').onclick = openConfirmModal;
  if (userStatus.alert) {
    row.querySelector('#btn-editalert').onclick = () => openAlertModal('edit');
  } else {
    row.querySelector('#btn-setalert').onclick = () => openAlertModal('set');
  }
}

function goToLogin() {
  showToast('Sign in to track prices and set alerts.');
  setTimeout(() => { window.location.href = '/login'; }, 1200);
}

async function handleAdd() {
  const btn = document.getElementById('btn-add');
  btn.disabled = true; btn.textContent = 'Adding…';
  try {
    const res = await fetch(`/api/products/${productId}/add`, {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (res.ok || res.status === 201) {
      userStatus = { tracking: true, alert: null };
      renderActions(); bumpWatchers(+1);
      showToast('Added to your tracking list!', 'success');
    } else {
      const d = await res.json().catch(() => ({}));
      showToast(d.detail || 'Could not add product.', 'error');
      btn.disabled = false; btn.textContent = 'Add to Track';
    }
  } catch { showToast('Network error.', 'error'); btn.disabled = false; btn.textContent = 'Add to Track'; }
}

// ── Delete / confirm modal ─────────────────────────────────────────────────
function openConfirmModal() {
  document.getElementById('confirm-modal').classList.add('open');
}
function closeConfirmModal() {
  document.getElementById('confirm-modal').classList.remove('open');
}

document.getElementById('btn-confirm-cancel').addEventListener('click', closeConfirmModal);
document.getElementById('confirm-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('confirm-modal')) closeConfirmModal();
});

document.getElementById('btn-confirm-ok').addEventListener('click', async () => {
  closeConfirmModal();
  try {
    const res = await fetch(`/api/products/${productId}/add`, {
      method: 'DELETE', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (res.ok || res.status === 204) {
      userStatus = { tracking: false, alert: null };
      renderActions(); bumpWatchers(-1);
      showToast('Removed from your tracking list.');
    } else { showToast('Could not remove product.', 'error'); }
  } catch { showToast('Network error.', 'error'); }
});

function bumpWatchers(delta) {
  const el = document.getElementById('p-watchers');
  if (!el) return;
  const next = Math.max(0, (parseInt(el.querySelector('strong').textContent) || 0) + delta);
  el.innerHTML = `👁 <strong>${next}</strong> ${next === 1 ? 'person' : 'people'} tracking this`;
}

// ── Refresh button ─────────────────────────────────────────────────────────
document.getElementById('btn-refresh').addEventListener('click', async () => {
  const btn = document.getElementById('btn-refresh');
  btn.disabled = true; btn.innerHTML = '<span class="loading-dots"><span></span><span></span><span></span></span>';
  try {
    const res = await fetch(`/api/products/${productId}/refresh`, {
      method: 'POST', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.currency) productData.currency = data.currency;
      if (data.availability) productData.availability = data.availability;
      if (data.current_price != null) {
        document.getElementById('p-price').textContent = formatPrice(data.current_price, productData?.currency);
      }
      updateAvailability(data.availability || 'available');
      updateLastChecked(data.last_checked);
      if (data.availability === 'unavailable') {
        showToast('This listing is no longer available.', 'error');
      } else if (data.availability === 'url_error') {
        showToast('This product page no longer exists.', 'error');
      } else {
        showToast('Price updated!', 'success');
      }
    } else { const d = await res.json().catch(() => ({})); showToast(d.detail || 'Could not refresh price.', 'error'); }
  } catch { showToast('Network error.', 'error'); }
  finally  { btn.disabled = false; btn.textContent = 'Refresh price'; }
});

// ── Market analysis ────────────────────────────────────────────────────────
async function loadMarketAnalysis() {
  const card = document.getElementById('market-card');
  card.style.display = 'flex';
  try {
    const res = await fetch(`/api/products/${productId}/ai-analysis`);
    if (res.ok) {
      const data = await res.json();
      document.getElementById('market-body').innerHTML = data.analysis
        ? `<p class="market-text">${esc(data.analysis)}</p>`
        : '';
      if (!data.analysis) card.style.display = 'none';
    } else { card.style.display = 'none'; }
  } catch { card.style.display = 'none'; }
}

// ── Alert modal (slider — identical to dashboard) ──────────────────────────
const SNAP_POINTS = [-50, -25, -15, -10, 0, 10, 25, 50];

function snapToNearest(val) {
  let best = null, bestDist = 4;
  for (const sp of SNAP_POINTS) { const d = Math.abs(val - sp); if (d < bestDist) { bestDist = d; best = sp; } }
  return best !== null ? best : val;
}

// Convert amount from a given currency into the user's display currency
function _toLocalAmount(amount, fromCurrency) {
  if (!amount) return 0;
  const pCur = fromCurrency || 'USD';
  const uCur = _xCurrency   || 'USD';
  if (pCur === uCur) return amount;
  const pRate = pCur === 'USD' ? 1 : (_allRates[pCur] || 0);
  const uRate = uCur === 'USD' ? 1 : (_allRates[uCur] || 0);
  if (!pRate || !uRate) return amount;
  return (amount / pRate) * uRate;
}

// Convert amount from the user's display currency back into a given currency
function _fromLocalAmount(amount, toCurrency) {
  if (!amount) return 0;
  const pCur = toCurrency || 'USD';
  const uCur = _xCurrency  || 'USD';
  if (pCur === uCur) return amount;
  const pRate = pCur === 'USD' ? 1 : (_allRates[pCur] || 0);
  const uRate = uCur === 'USD' ? 1 : (_allRates[uCur] || 0);
  if (!pRate || !uRate) return amount;
  return (amount / uRate) * pRate;
}

function _localCurrentPrice() {
  return _toLocalAmount(alertCurrentPrice, productData?.currency);
}

function updatePctDisplay(targetPrice) {
  const el = document.getElementById('pct-display');
  const localCurrent = _localCurrentPrice();
  if (!localCurrent || localCurrent <= 0) { el.textContent = '—'; el.className = 'pct-display zero'; return; }
  const pct = ((targetPrice / localCurrent) - 1) * 100;
  if (Math.abs(pct) < 0.05) { el.textContent = 'At current price'; el.className = 'pct-display zero'; }
  else if (pct < 0) { el.textContent = Math.abs(pct).toFixed(1) + '% below current price'; el.className = 'pct-display negative'; }
  else              { el.textContent = pct.toFixed(1) + '% above current price';           el.className = 'pct-display positive'; }
}

function updateSliderThumb(slider) {
  const val = parseInt(slider.value);
  slider.classList.remove('sage-thumb', 'rose-thumb');
  if (val < 0) slider.classList.add('sage-thumb'); else if (val > 0) slider.classList.add('rose-thumb');
}

document.getElementById('alert-slider').addEventListener('input', function() {
  if (!alertCurrentPrice) return;
  const localCurrent = _localCurrentPrice();
  const price = localCurrent * (1 + parseInt(this.value) / 100);
  document.getElementById('alert-price').value = Math.max(0.01, price).toFixed(2);
  updatePctDisplay(price); updateSliderThumb(this);
});

document.getElementById('alert-slider').addEventListener('change', function() {
  const snapped = snapToNearest(parseInt(this.value));
  this.value = snapped;
  if (alertCurrentPrice) {
    const localCurrent = _localCurrentPrice();
    const price = localCurrent * (1 + snapped / 100);
    document.getElementById('alert-price').value = Math.max(0.01, price).toFixed(2);
    updatePctDisplay(price);
  }
  updateSliderThumb(this);
});

document.getElementById('alert-price').addEventListener('input', function() {
  const price = parseFloat(this.value);
  updatePctDisplay(isNaN(price) ? 0 : price);
  if (!alertCurrentPrice || isNaN(price)) return;
  const localCurrent = _localCurrentPrice();
  const slider = document.getElementById('alert-slider');
  slider.value = Math.max(-50, Math.min(50, Math.round((price / localCurrent - 1) * 100)));
  updateSliderThumb(slider);
});

function openAlertModal(mode) {
  alertMode = mode;
  alertCurrentPrice = productData ? (productData.current_price || 0) : 0;
  document.getElementById('modal-subtitle').textContent =
    alertCurrentPrice > 0 ? 'Current price: ' + formatPrice(alertCurrentPrice, productData?.currency) : 'Current price: unknown';
  document.getElementById('modal-error').style.display = 'none';

  const isEdit = (mode === 'edit' && userStatus && userStatus.alert);
  document.getElementById('modal-title').textContent    = isEdit ? 'Edit target price' : 'Set target price';
  document.getElementById('btn-alert-save').textContent = isEdit ? 'Save' : 'Set Alert';

  // Update label and input max to reflect current currency
  const currSym = CURRENCY_SYMBOLS[_xCurrency] || _xCurrency;
  document.getElementById('alert-price-label').textContent = `Target price (${currSym})`;
  const localCurrent = _localCurrentPrice();
  document.getElementById('alert-price').max = Math.ceil(localCurrent * 3) || 9999;

  const slider = document.getElementById('alert-slider');
  slider.disabled = (alertCurrentPrice <= 0);
  // Alert target is stored in product's native currency — convert to display currency
  const targetLocal = isEdit
    ? _toLocalAmount(userStatus.alert.target_price, productData?.currency)
    : (localCurrent > 0 ? localCurrent * 0.9 : 0);
  document.getElementById('alert-price').value = targetLocal > 0 ? targetLocal.toFixed(2) : '';
  if (localCurrent > 0 && targetLocal > 0) {
    slider.value = Math.max(-50, Math.min(50, Math.round((targetLocal / localCurrent - 1) * 100)));
    updateSliderThumb(slider);
  }
  updatePctDisplay(targetLocal);
  document.getElementById('alert-modal').classList.add('open');
}

function closeAlertModal() { document.getElementById('alert-modal').classList.remove('open'); }

document.getElementById('btn-alert-cancel').addEventListener('click', closeAlertModal);
document.getElementById('alert-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('alert-modal')) closeAlertModal();
});

document.getElementById('btn-alert-save').addEventListener('click', async () => {
  const errEl   = document.getElementById('modal-error');
  const saveBtn = document.getElementById('btn-alert-save');
  errEl.style.display = 'none';

  const targetPriceLocal = parseFloat(document.getElementById('alert-price').value);
  if (!targetPriceLocal || targetPriceLocal <= 0) {
    errEl.textContent = 'Please enter a valid target price.'; errEl.style.display = 'block'; return;
  }
  // Convert from display currency to product's native currency for backend comparison
  const targetPrice = _fromLocalAmount(targetPriceLocal, productData?.currency);

  saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
  try {
    let res;
    const isEdit = (alertMode === 'edit' && userStatus && userStatus.alert);
    if (isEdit) {
      res = await fetch(`/api/alerts/${userStatus.alert.id}/target?target_price=${targetPrice}`, {
        method: 'PATCH', headers: { 'Authorization': 'Bearer ' + token },
      });
    } else {
      res = await fetch('/api/alerts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ product_id: productId, target_price: targetPrice }),
      });
    }
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || 'Could not save alert.'; errEl.style.display = 'block'; return; }

    userStatus = { tracking: true, alert: { id: data.id, target_price: data.target_price, is_active: data.is_active } };
    if (!isEdit) bumpWatchers(+1);
    renderActions(); closeAlertModal();
    showToast(isEdit ? 'Alert updated!' : "Alert set! We'll notify you when the price drops.", 'success');
  } catch {
    errEl.textContent = 'Network error. Please try again.'; errEl.style.display = 'block';
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = (alertMode === 'edit' && userStatus && userStatus.alert) ? 'Save' : 'Set Alert';
  }
});

// ── Init ───────────────────────────────────────────────────────────────────
(async () => {
  await initCurrency();
  await loadProduct('week');
  await loadUserStatus();
  loadMarketAnalysis();
  // Auto-refresh once if currency changed after last price check and product is in a different currency
  if (token && productData && productData.currency && productData.currency !== _xCurrency) {
    const changedAt  = parseInt(localStorage.getItem('ph_currency_changed_at') || '0', 10);
    const lastChecked = productData.last_checked ? new Date(productData.last_checked).getTime() : 0;
    if (changedAt > lastChecked) {
      document.getElementById('btn-refresh').click();
    }
  }
})();
