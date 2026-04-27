// ── Navbar: swap Sign Up → Dashboard if logged in ──────────────────────────
if (localStorage.getItem('ph_token')) {
  document.getElementById('nav-login').style.display = 'none';
  const btn = document.getElementById('nav-signup');
  btn.textContent = 'Dashboard';
  btn.href = '/dashboard';
}


// ── Currency detection ─────────────────────────────────────────────────────
(async function detectCurrency() {
  if (localStorage.getItem('ph_currency')) return;
  try {
    const ctrl  = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    const res   = await fetch('https://ipapi.co/json/', { signal: ctrl.signal });
    clearTimeout(timer);
    const data  = await res.json();
    const currency = data.currency;
    const country  = data.country_name;
    if (!currency || currency === 'USD') return;
    document.getElementById('currency-country').textContent = country || 'your region';
    document.getElementById('currency-code').textContent    = currency;
    document.getElementById('currency-label').textContent   = currency;
    document.getElementById('btn-currency-yes').onclick     = () => dismissCurrency(currency);
    setTimeout(() => document.getElementById('currency-banner').classList.add('visible'), 1800);
  } catch {}
})();

function dismissCurrency(code) {
  localStorage.setItem('ph_currency', code || 'USD');
  document.getElementById('currency-banner').classList.remove('visible');
}

// ── Demo chart (floating card) — fetches real Sony history from API ──────────
(async function() {
  let labels = ['Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar'];
  let prices = [349.99, 329.99, 299.99, 309.99, 289.99, 279.99];

  try {
    const demos = await fetch('/api/products/demo').then(r => r.ok ? r.json() : null);
    if (demos && demos[0]?.id) {
      const hist = await fetch(`/api/products/${demos[0].id}/history?period=6m`).then(r => r.ok ? r.json() : null);
      if (hist && hist.length >= 2) {
        // Sample up to 30 evenly-spaced points
        const step = Math.max(1, Math.ceil(hist.length / 30));
        const sampled = hist.filter((_, i) => i % step === 0 || i === hist.length - 1);
        labels = sampled.map(h => new Date(h.checked_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
        prices = sampled.map(h => Number(h.price));
      }
    }
  } catch {}

  const minP = Math.min(...prices), maxP = Math.max(...prices);
  new Chart(document.getElementById('demo-chart').getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: prices,
        borderColor: '#5C7A5C',
        backgroundColor: 'rgba(92,122,92,0.08)',
        borderWidth: 2,
        pointRadius: prices.length > 20 ? 0 : 5,
        pointHoverRadius: 7,
        hitRadius: 16,
        pointBackgroundColor: '#5C7A5C',
        fill: true,
        tension: 0.4,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          caretSize: 0,
          caretPadding: 12,
          backgroundColor: '#2D3748',
          titleColor: 'rgba(255,255,255,0.6)',
          bodyColor: '#fff',
          bodyFont:  { size: 13, weight: '700', family: 'Plus Jakarta Sans' },
          titleFont: { size: 11, family: 'Plus Jakarta Sans' },
          padding: 10,
          cornerRadius: 8,
          displayColors: false,
          callbacks: {
            title: (items) => items[0].label,
            label: (ctx)   => '$' + ctx.parsed.y.toFixed(2),
          }
        }
      },
      scales: {
        x: { display: false },
        y: { display: false, min: minP - (maxP - minP) * 0.15, max: maxP + (maxP - minP) * 0.15 },
      },
    }
  });
})();

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

// ── timeAgo helper ─────────────────────────────────────────────────────────
function timeAgo(isoStr) {
  if (!isoStr) return null;
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Load demo product IDs and update card links ────────────────────────────
const _DEMO_WATCHER_COUNTS = [47, 128, 92];

(async function initDemoCards() {
  await initCurrency();
  try {
    const res   = await fetch('/api/products/demo');
    if (!res.ok) return;
    const demos = await res.json();
    demos.forEach((d, i) => {
      const card = document.getElementById('demo-card-' + i);
      if (card && d.id) card.href = '/product?id=' + d.id;

      const priceEl = document.getElementById('demo-price-' + i);
      if (priceEl && d.current_price != null)
        priceEl.textContent = formatPrice(d.current_price, d.currency || 'USD');

      if (i === 0) {
        const heroEl = document.getElementById('demo-price-hero');
        if (heroEl && d.current_price != null) heroEl.textContent = formatPrice(d.current_price, d.currency || 'USD');
      }

      // Use realistic hardcoded watcher counts — real DB count is 0 (no users track demo products)
      const metaEl = document.getElementById('demo-meta-' + i);
      if (metaEl)
        metaEl.textContent = '👁 ' + _DEMO_WATCHER_COUNTS[i] + ' tracking';

      const timeEl = document.getElementById('demo-time-' + i);
      if (timeEl && d.last_checked)
        timeEl.textContent = 'Updated ' + (timeAgo(d.last_checked) || 'recently');
    });
  } catch {}
})();

// ── Toast helper ───────────────────────────────────────────────────────────
function showToast(msg, type = '') {
  const el       = document.createElement('div');
  el.className   = 'toast' + (type ? ' ' + type : '');
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── Track a product ────────────────────────────────────────────────────────
document.getElementById('btn-track').addEventListener('click', trackProduct);
document.getElementById('track-url').addEventListener('keydown', e => {
  if (e.key === 'Enter') trackProduct();
});

async function trackProduct() {
  const input = document.getElementById('track-url');
  const hint  = document.getElementById('track-hint');
  const btn   = document.getElementById('btn-track');
  const url   = input.value.trim();

  hint.className   = 'track-hint';
  hint.textContent = '';

  if (!url) {
    hint.textContent = 'Please paste a product URL first.';
    hint.classList.add('visible', 'error');
    return;
  }

  const token = localStorage.getItem('ph_token');
  if (token) {
    try {
      const r = await fetch('/api/dashboard/', { headers: { Authorization: 'Bearer ' + token } });
      if (r.ok) {
        const dash = await r.json();
        if ((dash.products || []).length >= 5) {
          hint.textContent = 'You\'ve reached the 5-product limit. Remove a product to add a new one.';
          hint.classList.add('visible', 'error');
          return;
        }
      }
    } catch { /* ignore, let backend enforce */ }
  }

  btn.disabled  = true;
  btn.innerHTML = 'Tracking <span class="loading-dots"><span></span><span></span><span></span></span>';
  hint.textContent = 'Fetching product info…';
  hint.classList.add('visible');

  try {
    const res  = await fetch('/api/products/track', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!res.ok) {
      hint.textContent = data.detail || 'Could not track this product.';
      hint.classList.add('error');
      return;
    }

    showToast('Product found! Redirecting…', 'success');
    setTimeout(() => { window.location.href = '/product?id=' + data.id; }, 800);
  } catch {
    hint.textContent = 'Network error. Please check your connection and try again.';
    hint.classList.add('error');
  } finally {
    btn.disabled  = false;
    btn.innerHTML = 'Track';
  }
}

function toggleSupported(e) {
  e.stopPropagation();
  document.getElementById('supported-popup').classList.toggle('open');
}
document.addEventListener('click', () => {
  document.getElementById('supported-popup').classList.remove('open');
});
