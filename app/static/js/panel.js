// static/js/app_panel.js
console.log('[app_panel] loaded');

document.addEventListener('click', function (e) {
  const root = document.querySelector('.panel-wrap');
  if (!root || !root.contains(e.target)) return;

  // + / −
  const incBtn = e.target.closest('[data-inc]');
  const decBtn = e.target.closest('[data-dec]');
  if (incBtn || decBtn) {
    e.preventDefault();
    const btn = incBtn || decBtn;
    const delta = incBtn ? +1 : -1;
    const target = btn.getAttribute('data-target');
    if (!target) return;

    const input = root.querySelector('#' + CSS.escape(target));
    if (!input) return;
    const cur = parseInt(input.value || '0', 10) || 0;
    input.value = Math.max(0, cur + delta);
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return;
  }

  // Akordeon
  const head = e.target.closest('[data-acc-head]');
  if (head) {
    const id = head.getAttribute('data-target');
    const body = root.querySelector('#' + CSS.escape(id));
    if (body) {
      const open = body.style.display !== 'none';
      body.style.display = open ? 'none' : 'block';
      const icon = head.querySelector('[data-acc-icon]');
      if (icon) icon.textContent = open ? '▸' : '▾';
    }
    return;
  }

  // Sıfırla
  if (e.target.id === 'hepsiniSifirla') {
    root.querySelectorAll('input.qty').forEach(i => (i.value = 0));
    root.querySelectorAll('input.note').forEach(i => (i.value = ''));
    return;
  }
});

document.addEventListener('input', function (e) {
  const root = document.querySelector('.panel-wrap');
  if (!root || !root.contains(e.target)) return;

  if (e.target.id === 'urunAra') {
    const val = (e.target.value || '').toLowerCase().trim();
    root.querySelectorAll('[data-prod]').forEach(el => {
      const name = (el.getAttribute('data-name') || '').toLowerCase();
      el.style.display = val === '' || name.includes(val) ? '' : 'none';
    });
  }
});

(function(){
  // Tema toggle
  const root = document.documentElement;
  const key = 'nexa-theme';
  const btn = document.getElementById('modeToggle');
  try {
    const saved = localStorage.getItem(key);
    if (saved === 'dark') {
      root.setAttribute('data-theme','dark');
      if (btn) btn.textContent = '☀️';
    }
  } catch(_) {}
  if (btn){
    btn.addEventListener('click', ()=>{
      const cur = root.getAttribute('data-theme') || 'light';
      const next = cur === 'light' ? 'dark' : 'light';
      root.setAttribute('data-theme', next);
      btn.textContent = next === 'dark' ? '☀️' : '🌙';
      try { localStorage.setItem(key, next); } catch(_) {}
    });
  }

  // Burger: mobil nav aç/kapa
  const burger = document.getElementById('nxBurger');
  const nav = document.getElementById('nxNav');
  if (burger && nav) {
    burger.addEventListener('click', ()=> nav.classList.toggle('open'));
  }
})();

