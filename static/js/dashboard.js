const token = localStorage.getItem('ph_token');

// ── Auth guard ─────────────────────────────────────────────────────────────
if (!token) window.location.href = '/login';

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

function formatPrice(amount, productCurrency) {
  if (amount == null) return '—';
  const n    = Number(amount);
  const pCur = productCurrency || 'USD';
  const uCur = _xCurrency      || 'USD';
  if (pCur === uCur) {
    const sym = CURRENCY_SYMBOLS[uCur] || (uCur + ' ');
    return sym + n.toFixed(2);
  }
  const pRate = pCur === 'USD' ? 1 : (_allRates[pCur] || 0);
  const uRate = uCur === 'USD' ? 1 : (_allRates[uCur] || 0);
  if (!pRate || !uRate) return (CURRENCY_SYMBOLS[pCur] || (pCur + ' ')) + n.toFixed(2);
  return '~' + (CURRENCY_SYMBOLS[uCur] || (uCur + ' ')) + ((n / pRate) * uRate).toFixed(2);
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
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('approx-btn')) {
    const rect = e.target.getBoundingClientRect();
    approxPopup.innerHTML =
      `We couldn't find the price directly in <strong>${_xCurrency}</strong>, so it was converted from USD<br>using live exchange rates.<br>Actual price on the retailer's site may differ slightly.<br><a href="https://open.er-api.com" target="_blank" rel="noopener">Rates: open.er-api.com ↗</a>`;
    // Position: above button if near bottom, below otherwise
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow < 140) {
      approxPopup.style.top  = '';
      approxPopup.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
    } else {
      approxPopup.style.bottom = '';
      approxPopup.style.top  = (rect.bottom + 8) + 'px';
    }
    let left = rect.left;
    if (left + 240 > window.innerWidth - 12) left = window.innerWidth - 252;
    approxPopup.style.left   = Math.max(12, left) + 'px';
    approxPopup.style.display = 'block';
    e.stopPropagation();
  } else if (!approxPopup.contains(e.target)) {
    approxPopup.style.display = 'none';
  }
});

// ── Currency dropdown ───────────────────────────────────────────────────────
const CURRENCY_NAMES = {
  USD: 'US Dollar',       EUR: 'Euro',              GBP: 'British Pound',
  CAD: 'Canadian Dollar', AUD: 'Australian Dollar', CHF: 'Swiss Franc',
  JPY: 'Japanese Yen',    CNY: 'Chinese Yuan',      HKD: 'Hong Kong Dollar',
  SGD: 'Singapore Dollar',KRW: 'South Korean Won',  INR: 'Indian Rupee',
  SEK: 'Swedish Krona',   NOK: 'Norwegian Krone',   DKK: 'Danish Krone',
  PLN: 'Polish Zloty',    CZK: 'Czech Koruna',      HUF: 'Hungarian Forint',
  RON: 'Romanian Leu',    BGN: 'Bulgarian Lev',     UAH: 'Ukrainian Hryvnia',
  TRY: 'Turkish Lira',    AED: 'UAE Dirham',        SAR: 'Saudi Riyal',
  ILS: 'Israeli Shekel',  BRL: 'Brazilian Real',    MXN: 'Mexican Peso',
  ZAR: 'South African Rand', NZD: 'New Zealand Dollar', THB: 'Thai Baht',
  MYR: 'Malaysian Ringgit',  IDR: 'Indonesian Rupiah',  PHP: 'Philippine Peso',
};

function buildCurrencyMenu() {
  const menu = document.getElementById('currency-drop-menu');
  menu.innerHTML = Object.keys(CURRENCY_NAMES).map(code => `
    <div class="currency-drop-item${code === _xCurrency ? ' selected' : ''}" data-code="${code}">
      <span class="cur-code">${code}</span>
      <span class="cur-name">${CURRENCY_NAMES[code]}</span>
      <span class="cur-check">✓</span>
    </div>`).join('');
  menu.querySelectorAll('.currency-drop-item').forEach(item => {
    item.addEventListener('click', () => {
      setCurrency(item.dataset.code);
      menu.classList.remove('open');
      document.getElementById('btn-currency').classList.remove('open');
    });
  });
}

function setCurrency(code) {
  _xCurrency = code;
  _xRate     = _allRates[code] || null;
  localStorage.setItem('ph_currency', code);
  localStorage.setItem('ph_currency_changed_at', Date.now());
  document.getElementById('currency-label').textContent = code;
  buildCurrencyMenu();
  filterAndRender();
}

const btnCurrency      = document.getElementById('btn-currency');
const currencyDropMenu = document.getElementById('currency-drop-menu');

btnCurrency.addEventListener('click', (e) => {
  e.stopPropagation();
  const open = currencyDropMenu.classList.toggle('open');
  btnCurrency.classList.toggle('open', open);
  sortDropMenu.classList.remove('open');
  sortDropBtn.classList.remove('open');
});

// close both dropdowns on outside click
document.addEventListener('click', (e) => {
  if (!document.getElementById('currency-nav-wrap').contains(e.target)) {
    currencyDropMenu.classList.remove('open');
    btnCurrency.classList.remove('open');
  }
  if (!document.getElementById('sort-drop').contains(e.target)) {
    sortDropMenu.classList.remove('open');
    sortDropBtn.classList.remove('open');
  }
});

function parseJwt(t) {
  try { return JSON.parse(atob(t.split('.')[1])); } catch { return {}; }
}
const payload = parseJwt(token);
document.getElementById('nav-email').textContent = payload.email || '';

// ── Logout ─────────────────────────────────────────────────────────────────
document.getElementById('btn-logout').addEventListener('click', () => {
  localStorage.removeItem('ph_token');
  window.location.href = '/';
});

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'toast' + (type ? ' ' + type : '');
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function sourceFromUrl(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); }
  catch { return ''; }
}

// ── Track limit check ─────────────────────────────────────────────────────
function checkTrackLimit(e) {
  if (allProducts.length >= 5) {
    e.preventDefault();
    showToast('You\'ve reached the 5-product limit. Remove a product to add a new one.', 'error');
    return false;
  }
  return true;
}

// ── State ──────────────────────────────────────────────────────────────────
let allProducts   = [];
let activeFilter  = 'all';
let editAlertId      = null;
let editCurrentPrice = 0;
let editCurrency     = 'USD';
let pendingDeleteId  = null;

// ── Load dashboard ─────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const res = await fetch('/api/dashboard/', {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    if (res.status === 401) { localStorage.removeItem('ph_token'); window.location.href = '/login'; return; }
    if (!res.ok) throw new Error('API error');
    const data = await res.json();
    renderDashboard(data);
  } catch {
    showToast('Could not load dashboard. Please refresh.', 'error');
    document.getElementById('skeleton-list').style.display = 'none';
  }
}

function renderDashboard(data) {
  document.getElementById('skeleton-list').style.display = 'none';
  document.getElementById('s-total').textContent     = data.total_products;
  document.getElementById('s-active').textContent    = data.active_alerts;
  document.getElementById('s-triggered').textContent = data.alerts_triggered;

  allProducts = data.products || [];

  if (!allProducts.length) {
    document.getElementById('empty-state').style.display   = 'block';
    document.getElementById('btn-track-bottom').style.display = 'block';
    startTour(false);
    return;
  }

  document.getElementById('list-wrapper').style.display = 'block';
  document.getElementById('filter-bar').style.display   = 'flex';
  requestAnimationFrame(() => requestAnimationFrame(initChipIndicator));
  filterAndRender();
  startTour(true);
}

// ── Filter / sort / render ─────────────────────────────────────────────────
function filterAndRender() {
  const query = document.getElementById('search-input').value.trim().toLowerCase();
  const sort  = _currentSort;

  let items = allProducts.filter(p => {
    if (query && !(p.name || '').toLowerCase().includes(query)) return false;
    if (activeFilter === 'active'  && !p.alert_active)              return false;
    if (activeFilter === 'dropped' && !(p.change_24h_pct < 0))      return false;
    return true;
  });

  if (sort === 'price-asc')  items.sort((a, b) => (a.current_price || 0) - (b.current_price || 0));
  if (sort === 'price-desc') items.sort((a, b) => (b.current_price || 0) - (a.current_price || 0));
  if (sort === 'change')     items.sort((a, b) => (a.change_24h_pct || 0) - (b.change_24h_pct || 0));
  if (sort === 'name')       items.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  // 'date' = API order (already sorted by created_at DESC)
  // Always push unavailable/broken products to the bottom regardless of sort
  const _unavail = v => v.availability === 'unavailable' || v.availability === 'url_error';
  items.sort((a, b) => _unavail(a) - _unavail(b));

  const list = document.getElementById('product-list');
  const noRes = document.getElementById('no-results');

  if (!items.length) {
    list.innerHTML = '';
    noRes.style.display = 'block';
  } else {
    noRes.style.display = 'none';
    list.innerHTML = items.map(p => buildCard(p)).join('');
    attachCardListeners();
  }
}

// ── Filter chips ───────────────────────────────────────────────────────────
document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    moveChipIndicator(chip);
    activeFilter = chip.dataset.filter;
    filterAndRender();
  });
});
document.getElementById('search-input').addEventListener('input', filterAndRender);

// ── Sort custom dropdown ────────────────────────────────────────────────────
let _currentSort = 'date';
const _sortLabels = {
  'date': 'Latest first', 'price-asc': 'Price: low → high',
  'price-desc': 'Price: high → low', 'change': 'Biggest drop first', 'name': 'Name A–Z'
};
const sortDropBtn  = document.getElementById('sort-drop-btn');
const sortDropMenu = document.getElementById('sort-drop-menu');

sortDropBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  const open = sortDropMenu.classList.toggle('open');
  sortDropBtn.classList.toggle('open', open);
  document.getElementById('currency-drop-menu').classList.remove('open');
  document.getElementById('btn-currency').classList.remove('open');
});

sortDropMenu.querySelectorAll('.custom-drop-item').forEach(item => {
  item.addEventListener('click', () => {
    _currentSort = item.dataset.value;
    document.getElementById('sort-label').textContent = _sortLabels[_currentSort];
    sortDropMenu.querySelectorAll('.custom-drop-item').forEach(i => i.classList.remove('selected'));
    item.classList.add('selected');
    sortDropMenu.classList.remove('open');
    sortDropBtn.classList.remove('open');
    filterAndRender();
  });
});

function moveChipIndicator(btn) {
  const ind = document.getElementById('chip-indicator');
  if (!ind || !btn) return;
  ind.style.left  = btn.offsetLeft + 'px';
  ind.style.width = btn.offsetWidth + 'px';
}

function initChipIndicator() {
  const active = document.querySelector('.chip.active');
  if (!active) return;
  const ind = document.getElementById('chip-indicator');
  if (!ind) return;
  ind.style.transition = 'none';
  moveChipIndicator(active);
  requestAnimationFrame(() => { ind.style.transition = ''; });
}

// ── Build card HTML ────────────────────────────────────────────────────────
function buildCard(p) {
  const imgHtml = p.image_url
    ? `<div class="dash-img"><img src="${esc(p.image_url)}" alt="${esc(p.name || '')}" onerror="this.parentElement.innerHTML='📦'" /></div>`
    : `<div class="dash-img">📦</div>`;

  const unavail  = p.availability === 'unavailable' || p.availability === 'url_error';
  const source   = p.source || sourceFromUrl(p.url);
  const priceStr = formatPrice(p.current_price, p.currency);

  let changeBadge = '';
  if (!unavail && p.change_24h_pct != null) {
    const pct  = Number(p.change_24h_pct).toFixed(1);
    const cls   = p.change_24h_pct < 0 ? 'down' : p.change_24h_pct > 0 ? 'up' : 'flat';
    const arrow = p.change_24h_pct < 0 ? '↓' : p.change_24h_pct > 0 ? '↑' : '→';
    changeBadge = `<span class="change-badge ${cls}">${arrow} ${Math.abs(pct)}% 24h</span>`;
  }

  const targetStr  = formatPrice(p.target_price, p.currency);
  const alertPill  = p.alert_active
    ? `<span class="alert-pill active">🔔 Alert on</span>`
    : `<span class="alert-pill inactive">Alert off</span>`;
  const unavailPill = unavail
    ? `<span class="unavail-pill">⚠️ ${p.availability === 'url_error' ? 'Link broken' : 'Unavailable'}</span>`
    : '';

  return `
    <div class="dash-card${unavail ? ' unavailable' : ''}" data-id="${p.id}" onclick="if(!event.target.closest('.dash-actions'))location.href='/product?id=${p.id}'">
      ${imgHtml}
      <div class="dash-info">
        <div class="dash-source">${esc(source || 'Unknown')}</div>
        <div class="dash-name">
          <a href="/product?id=${p.id}">${esc(p.name || 'Unknown product')}</a>
        </div>
        <div class="dash-meta">
          <span class="price-tag${unavail ? ' unavailable' : ''}">${unavail ? 'Last: ' : ''}${priceStr}</span>
          ${unavailPill}
          ${changeBadge}
          ${!unavail ? `<span class="target-label">Target: <strong>${targetStr}</strong></span>` : ''}
          ${!unavail ? alertPill : ''}
        </div>
      </div>
      <div class="dash-actions">
        ${p.alert_id ? `<button class="btn-icon"
          data-action="edit"
          data-alert-id="${esc(p.alert_id)}"
          data-target="${esc(p.target_price || '')}"
          data-current-price="${esc(p.current_price || '')}"
          data-currency="${esc(p.currency || 'USD')}">Edit target</button>` : ''}
        <button class="btn-icon danger"
          data-action="delete"
          data-product-id="${p.id}">Delete</button>
      </div>
    </div>`;
}

// ── Card listeners ─────────────────────────────────────────────────────────
function attachCardListeners() {
  document.querySelectorAll('[data-action="delete"]').forEach(btn => {
    btn.addEventListener('click', () => {
      pendingDeleteId = btn.dataset.productId;
      openModal('confirm-modal');
    });
  });

  document.querySelectorAll('[data-action="edit"]').forEach(btn => {
    btn.addEventListener('click', () => {
      editAlertId      = btn.dataset.alertId;
      editCurrentPrice = parseFloat(btn.dataset.currentPrice) || 0;
      editCurrency     = btn.dataset.currency || 'USD';
      const storedTarget = parseFloat(btn.dataset.target) || (editCurrentPrice * 0.9);

      document.getElementById('edit-current-label').textContent =
        editCurrentPrice > 0 ? 'Current price: ' + formatPrice(editCurrentPrice, editCurrency) : 'Current price: unknown';

      const currSym = CURRENCY_SYMBOLS[_xCurrency] || _xCurrency;
      document.getElementById('edit-price-label').textContent = `Target price (${currSym})`;
      const localCurrent = _toLocalAmount(editCurrentPrice, editCurrency);
      document.getElementById('edit-price').max = Math.ceil(localCurrent * 3) || 9999;

      const slider = document.getElementById('edit-slider');
      slider.disabled = (editCurrentPrice <= 0);

      // Alert target stored in product's native currency — convert to display currency
      const targetLocal = _toLocalAmount(storedTarget, editCurrency);
      document.getElementById('edit-price').value = targetLocal.toFixed(2);
      updatePctDisplay(targetLocal);
      if (localCurrent > 0) {
        const pct = Math.round((targetLocal / localCurrent - 1) * 100);
        slider.value = Math.max(-50, Math.min(50, pct));
        updateSliderThumb(slider);
      }
      openModal('edit-modal');
    });
  });
}

// ── Edit modal — slider ↔ input sync ──────────────────────────────────────
const SNAP_POINTS = [-50, -25, -15, -10, 0, 10, 25, 50];

function snapToNearest(val) {
  let best = null, bestDist = 4;
  for (const sp of SNAP_POINTS) {
    const d = Math.abs(val - sp);
    if (d < bestDist) { bestDist = d; best = sp; }
  }
  return best !== null ? best : val;
}

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

function _localEditCurrentPrice() { return _toLocalAmount(editCurrentPrice, editCurrency); }

function updatePctDisplay(targetPrice) {  // targetPrice is in local currency
  const el = document.getElementById('pct-display');
  const localCurrent = _localEditCurrentPrice();
  if (!localCurrent || localCurrent <= 0) { el.textContent = '—'; el.className = 'pct-display zero'; return; }
  const pct = ((targetPrice / localCurrent) - 1) * 100;
  if (Math.abs(pct) < 0.05) {
    el.textContent = 'At current price';
    el.className   = 'pct-display zero';
  } else if (pct < 0) {
    el.textContent = Math.abs(pct).toFixed(1) + '% below current price';
    el.className   = 'pct-display negative';
  } else {
    el.textContent = pct.toFixed(1) + '% above current price';
    el.className   = 'pct-display positive';
  }
}

function updateSliderThumb(slider) {
  const val = parseInt(slider.value);
  slider.classList.remove('sage-thumb', 'rose-thumb');
  if (val < 0)      slider.classList.add('sage-thumb');
  else if (val > 0) slider.classList.add('rose-thumb');
}

// Slider → input (live while dragging)
document.getElementById('edit-slider').addEventListener('input', function() {
  if (!editCurrentPrice) return;
  const localCurrent = _localEditCurrentPrice();
  const price = localCurrent * (1 + parseInt(this.value) / 100);
  document.getElementById('edit-price').value = Math.max(0.01, price).toFixed(2);
  updatePctDisplay(price);
  updateSliderThumb(this);
});

// Slider → snap on release
document.getElementById('edit-slider').addEventListener('change', function() {
  const snapped = snapToNearest(parseInt(this.value));
  this.value = snapped;
  if (editCurrentPrice) {
    const localCurrent = _localEditCurrentPrice();
    const price = localCurrent * (1 + snapped / 100);
    document.getElementById('edit-price').value = Math.max(0.01, price).toFixed(2);
    updatePctDisplay(price);
  }
  updateSliderThumb(this);
});

// Input → slider (manual typing)
document.getElementById('edit-price').addEventListener('input', function() {
  const price = parseFloat(this.value);
  updatePctDisplay(isNaN(price) ? 0 : price);
  if (!editCurrentPrice || isNaN(price)) return;
  const localCurrent = _localEditCurrentPrice();
  const slider = document.getElementById('edit-slider');
  slider.value = Math.max(-50, Math.min(50, Math.round((price / localCurrent - 1) * 100)));
  updateSliderThumb(slider);
});

// ── Modal helpers ──────────────────────────────────────────────────────────
function openModal(id) {
  document.getElementById(id).classList.add('open');
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

// Close on backdrop click
['edit-modal', 'confirm-modal'].forEach(id => {
  document.getElementById(id).addEventListener('click', function(e) {
    if (e.target === this) closeModal(id);
  });
});

// Edit modal — cancel / save
document.getElementById('btn-edit-cancel').addEventListener('click', () => closeModal('edit-modal'));
document.getElementById('btn-edit-save').addEventListener('click', async () => {
  const priceLocal = parseFloat(document.getElementById('edit-price').value);
  if (!priceLocal || priceLocal <= 0) { showToast('Enter a valid target price.', 'error'); return; }
  if (!editAlertId) { showToast('No alert selected.', 'error'); return; }
  // Convert from display currency back to product's native currency for storage
  const price = _fromLocalAmount(priceLocal, editCurrency);
  try {
    const res = await fetch(`/api/alerts/${editAlertId}/target?target_price=${price}`, {
      method: 'PATCH', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (res.ok) {
      showToast('Target price updated!', 'success');
      closeModal('edit-modal');
      await loadDashboard();
    } else {
      showToast('Could not update target.', 'error');
    }
  } catch { showToast('Network error.', 'error'); }
});

// Delete modal — cancel / confirm
document.getElementById('btn-confirm-cancel').addEventListener('click', () => {
  closeModal('confirm-modal'); pendingDeleteId = null;
});
document.getElementById('btn-confirm-ok').addEventListener('click', async () => {
  if (!pendingDeleteId) return;
  closeModal('confirm-modal');
  try {
    const res = await fetch(`/api/products/${pendingDeleteId}`, {
      method: 'DELETE', headers: { 'Authorization': 'Bearer ' + token },
    });
    if (res.ok || res.status === 204) {
      // Remove from allProducts and re-render
      allProducts = allProducts.filter(p => String(p.id) !== String(pendingDeleteId));
      document.getElementById('s-total').textContent = allProducts.length;
      if (!allProducts.length) {
        document.getElementById('list-wrapper').style.display   = 'none';
        document.getElementById('filter-bar').style.display     = 'none';
        document.getElementById('empty-state').style.display    = 'block';
        document.getElementById('btn-track-bottom').style.display = 'block';
      } else {
        filterAndRender();
      }
      showToast('Product removed.', 'success');
    } else {
      showToast('Could not delete product.', 'error');
    }
  } catch { showToast('Network error.', 'error'); }
  pendingDeleteId = null;
});

// ── Onboarding tour ────────────────────────────────────────────────────────
const TOUR_STEPS = [
  {
    selector: '.summary-bar',
    title: 'Your tracking at a glance',
    body: 'See how many products you\'re following, how many alerts are active, and how many have already triggered.',
    place: 'below',
  },
  {
    selector: '.btn-add',
    title: 'Track a new product',
    body: 'Paste any product URL — Amazon, Best Buy, or other stores — and we\'ll start monitoring the price for you.',
    place: 'below',
  },
  {
    selector: '#filter-bar',
    title: 'Filter and search',
    body: 'Quickly find products by name, filter by alert status, or sort by biggest price drop.',
    place: 'below',
  },
  {
    selector: '.dash-actions',
    title: 'Manage your alerts',
    body: 'Set a target price — we\'ll email you the moment it drops that low. Or remove the product if you\'re no longer interested.',
    place: 'left',
  },
];

let tourStep = 0;
let tourSteps = [];

function tourSpotlight() { return document.getElementById('tour-spotlight'); }
function tourTooltip()   { return document.getElementById('tour-tooltip'); }

function positionTour(step) {
  const el = document.querySelector(step.selector);
  if (!el) return false;

  const PAD = 8;
  const rect = el.getBoundingClientRect();
  const spot = tourSpotlight();
  const tip  = tourTooltip();

  spot.style.top    = (rect.top  - PAD) + 'px';
  spot.style.left   = (rect.left - PAD) + 'px';
  spot.style.width  = (rect.width  + PAD * 2) + 'px';
  spot.style.height = (rect.height + PAD * 2) + 'px';

  const TIP_W = 300;
  const TIP_MARGIN = 16;
  let tipTop, tipLeft;

  if (step.place === 'left') {
    tipTop  = rect.top + rect.height / 2 - 80;
    tipLeft = rect.left - TIP_W - TIP_MARGIN;
    if (tipLeft < 12) tipLeft = rect.right + TIP_MARGIN;
  } else {
    // below by default; fall back to above if not enough room
    const belowTop = rect.bottom + PAD + TIP_MARGIN;
    if (belowTop + 160 < window.innerHeight) {
      tipTop = belowTop;
    } else {
      tipTop = rect.top - PAD - TIP_MARGIN - 160;
    }
    tipLeft = rect.left + rect.width / 2 - TIP_W / 2;
    tipLeft = Math.max(12, Math.min(window.innerWidth - TIP_W - 12, tipLeft));
  }

  tip.style.top  = tipTop  + 'px';
  tip.style.left = tipLeft + 'px';
  return true;
}

function showTourStep(idx) {
  const step = tourSteps[idx];
  const spot = tourSpotlight();
  const tip  = tourTooltip();

  if (!positionTour(step)) {
    // target not in DOM — skip this step
    if (idx + 1 < tourSteps.length) showTourStep(idx + 1);
    else endTour();
    return;
  }

  spot.style.display = 'block';
  tip.style.display  = 'block';

  document.getElementById('tour-step-count').textContent =
    'Step ' + (idx + 1) + ' of ' + tourSteps.length;
  document.getElementById('tour-title').textContent = step.title;
  document.getElementById('tour-body').textContent  = step.body;

  const nextBtn = document.getElementById('tour-next');
  nextBtn.textContent = idx + 1 < tourSteps.length ? 'Next →' : 'Done ✓';
  tourStep = idx;
}

function endTour() {
  tourSpotlight().style.display = 'none';
  tourTooltip().style.display   = 'none';
  localStorage.setItem('ph_tour_done', '1');
}

function startTour(hasProducts) {
  if (localStorage.getItem('ph_tour_done')) return;
  tourSteps = hasProducts
    ? TOUR_STEPS
    : TOUR_STEPS.slice(0, 2); // summary + add button only for empty state
  // small delay so layout is settled
  setTimeout(() => showTourStep(0), 500);
}

document.getElementById('tour-next').addEventListener('click', () => {
  if (tourStep + 1 < tourSteps.length) showTourStep(tourStep + 1);
  else endTour();
});
document.getElementById('tour-skip').addEventListener('click', endTour);

// Reposition on resize
window.addEventListener('resize', () => {
  if (tourTooltip().style.display === 'block') positionTour(tourSteps[tourStep]);
});


// ── Init ───────────────────────────────────────────────────────────────────
(async () => {
  await initCurrency();
  document.getElementById('currency-label').textContent = _xCurrency;
  buildCurrencyMenu();
  loadDashboard();
})();
