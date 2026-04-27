// ── Redirect if already logged in ────────────────────────────────────────
if (localStorage.getItem('ph_token')) {
  window.location.href = '/dashboard';
}

// ── Activate tab from URL param (?tab=register or ?tab=login) ────────────
const tabParam = new URLSearchParams(location.search).get('tab');
if (tabParam === 'register') {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.form-panel').forEach(p => p.classList.remove('active'));
  document.querySelector('[data-tab="register"]').classList.add('active');
  document.getElementById('panel-register').classList.add('active');
}

// ── Tab sliding indicator ─────────────────────────────────────────────────
function moveTabIndicator(btn) {
  const ind = document.querySelector('.tab-indicator');
  if (!ind) return;
  ind.style.left  = btn.offsetLeft + 'px';
  ind.style.width = btn.offsetWidth + 'px';
}

// Init without animation
const activeTab = document.querySelector('.tab-btn.active');
if (activeTab) {
  const ind = document.querySelector('.tab-indicator');
  ind.style.transition = 'none';
  moveTabIndicator(activeTab);
  requestAnimationFrame(() => { ind.style.transition = ''; });
}

// ── Tab switching ─────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.form-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    moveTabIndicator(btn);
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});

// ── Toast helper ──────────────────────────────────────────────────────────
function showToast(msg, type = '') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = 'toast' + (type ? ' ' + type : '');
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function showError(id, msg) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.style.display = 'block';
}
function clearError(id) {
  const el = document.getElementById(id);
  el.style.display = 'none';
  el.textContent = '';
}

// ── Login ─────────────────────────────────────────────────────────────────
document.getElementById('btn-login').addEventListener('click', async () => {
  clearError('login-error');
  const email    = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  if (!email || !password) { showError('login-error', 'Please fill in all fields.'); return; }

  const btn = document.getElementById('btn-login');
  btn.disabled = true;
  btn.textContent = 'Signing in…';

  try {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) { showError('login-error', data.detail || 'Login failed.'); return; }
    localStorage.setItem('ph_token', data.access_token);
    showToast('Signed in!', 'success');
    setTimeout(() => { window.location.href = '/dashboard'; }, 600);
  } catch {
    showError('login-error', 'Network error. Please try again.');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sign In';
  }
});

// ── Register ──────────────────────────────────────────────────────────────
document.getElementById('btn-register').addEventListener('click', async () => {
  clearError('register-error');
  const email    = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  if (!email || !password) { showError('register-error', 'Please fill in all fields.'); return; }
  if (password.length < 8) { showError('register-error', 'Password must be at least 8 characters.'); return; }

  const btn = document.getElementById('btn-register');
  btn.disabled = true;
  btn.textContent = 'Creating account…';

  try {
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) { showError('register-error', data.detail || 'Registration failed.'); return; }
    localStorage.setItem('ph_token', data.access_token);
    showToast('Account created!', 'success');
    setTimeout(() => { window.location.href = '/dashboard'; }, 600);
  } catch {
    showError('register-error', 'Network error. Please try again.');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Account';
  }
});

// Allow submitting with Enter key
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const active = document.querySelector('.form-panel.active');
  if (!active) return;
  active.querySelector('.btn-primary').click();
});

// ── Forgot password ───────────────────────────────────────────────────────
const tabs = document.querySelector('.tabs');
let forgotEmail = '';

function showPanel(id) {
  document.querySelectorAll('.form-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

document.getElementById('btn-forgot-link').addEventListener('click', () => {
  tabs.style.display = 'none';
  document.querySelector('h1').textContent = 'Reset password';
  document.querySelector('.subtitle').textContent = 'We\'ll email you a code to reset your password.';
  showPanel('panel-forgot');
});

function backToLogin() {
  tabs.style.display = '';
  document.querySelector('h1').textContent = 'Welcome back';
  document.querySelector('.subtitle').textContent = 'Track prices and get notified when they drop.';
  showPanel('panel-login');
}

document.getElementById('btn-back-login').addEventListener('click', backToLogin);
document.getElementById('btn-back-forgot').addEventListener('click', () => showPanel('panel-forgot'));

document.getElementById('btn-send-code').addEventListener('click', async () => {
  clearError('forgot-error');
  document.getElementById('forgot-success').style.display = 'none';
  const email = document.getElementById('forgot-email').value.trim();
  if (!email) { showError('forgot-error', 'Please enter your email.'); return; }

  const btn = document.getElementById('btn-send-code');
  btn.disabled = true; btn.textContent = 'Sending…';

  try {
    const res = await fetch('/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!res.ok) {
      const d = await res.json();
      showError('forgot-error', d.detail || 'Something went wrong.');
      return;
    }
    forgotEmail = email;
    const succ = document.getElementById('forgot-success');
    succ.textContent = `Code sent to ${email}`;
    succ.style.display = 'block';
    setTimeout(() => showPanel('panel-verify'), 1000);
  } catch {
    showError('forgot-error', 'Network error. Please try again.');
  } finally {
    btn.disabled = false; btn.textContent = 'Send Code';
  }
});

document.getElementById('btn-reset-password').addEventListener('click', async () => {
  clearError('verify-error');
  const code     = document.getElementById('verify-code').value.trim();
  const password = document.getElementById('verify-password').value;
  if (!code || !password) { showError('verify-error', 'Please fill in all fields.'); return; }
  if (password.length < 8) { showError('verify-error', 'Password must be at least 8 characters.'); return; }

  const btn = document.getElementById('btn-reset-password');
  btn.disabled = true; btn.textContent = 'Resetting…';

  try {
    const res = await fetch('/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: forgotEmail, code, new_password: password }),
    });
    const d = await res.json();
    if (!res.ok) { showError('verify-error', d.detail || 'Invalid or expired code.'); return; }
    showToast('Password reset! Please sign in.', 'success');
    setTimeout(() => backToLogin(), 1200);
  } catch {
    showError('verify-error', 'Network error. Please try again.');
  } finally {
    btn.disabled = false; btn.textContent = 'Reset Password';
  }
});
