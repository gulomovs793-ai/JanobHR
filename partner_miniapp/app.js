(() => {
  const tg = window.Telegram?.WebApp || null;
  const $ = (id) => document.getElementById(id);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const initData = tg?.initData || '';
  let currentPromo = '';

  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor('#f5f5f7'); tg.setBackgroundColor('#f5f5f7'); } catch (_) {}
  }

  const haptic = (kind='light') => { try { tg?.HapticFeedback?.impactOccurred(kind); } catch (_) {} };
  const text = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  function renderActivity(items) {
    const root = $('activity'); if (!root) return;
    if (!items?.length) { root.innerHTML = '<p class="empty">Faoliyat hali yo‘q.</p>'; return; }
    root.innerHTML = items.map(item => {
      const date = item.created_at ? new Date(item.created_at).toLocaleDateString('uz-UZ', {day:'2-digit', month:'short'}) : '';
      const detail = item.type === 'sale' && item.plan_code ? ` · ${item.plan_code.toUpperCase()}` : ' · Referral kanali';
      const commission = item.type === 'sale' ? `<strong>${Number(item.commission || 0).toLocaleString('uz-UZ')} UZS</strong>` : '';
      return `<div class="activity-row"><span class="activity-icon">${item.icon || '•'}</span><div><b>${item.label || 'Faoliyat'}</b><small>${detail}${date ? ` · ${date}` : ''}</small></div>${commission}</div>`;
    }).join('');
  }

  function show(name) {
    $$('.view').forEach(v => v.classList.toggle('active', v.id === name));
    $$('.bottom-nav [data-go]').forEach(b => b.classList.toggle('active', b.dataset.go === name));
    window.scrollTo({top:0, behavior:'smooth'});
    haptic();
  }

  $$('[data-go]').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.go)));

  function fail(message) {
    text('errorMessage', message || 'Mini Appni Hamkor bot ichidan qayta oching.');
    show('error');
  }

  async function api(path, options={}) {
    const headers = Object.assign({'X-Telegram-Init-Data': initData}, options.headers || {});
    return fetch(path, Object.assign({cache:'no-store'}, options, {headers}));
  }

  async function load() {
    if (!initData) return fail('Telegram tasdiqlashi topilmadi. Panelni Hamkor bot ichidagi ko‘k tugmadan oching.');
    $('refresh')?.classList.add('loading');
    try {
      const res = await api('/api/partner-miniapp/stats');
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        if (res.status === 403) return fail('Bu panel faqat tasdiqlangan hamkorlar uchun.');
        if (res.status === 401) return fail('Telegram sessiyasi tasdiqlanmadi. Mini Appni bot ichidan qayta oching.');
        return fail('Ma’lumotlarni yuklab bo‘lmadi. Qayta urinib ko‘ring.');
      }
      const s = data.stats || {};
      const earned = s.earned_label || '0 UZS';
      text('partnerName', data.partner?.full_name || 'Hamkor paneli');
      text('clicks', s.clicks ?? 0); text('trials', s.trials ?? 0); text('sales', s.sales ?? 0); text('promo_sales', s.promo_sales ?? 0);
      text('earned', earned); text('earnedLarge', earned);
      renderActivity(data.activity || []);
      text('referral_link', data.referral_link || 'Referral link topilmadi');
      if (data.promo?.code) {
        currentPromo = data.promo.code;
        text('promoCode', data.promo.code);
        text('promoText', `${data.promo.discount_percent}% chegirma faol.`);
        $('promoResult')?.classList.remove('hidden');
        $$('[data-discount]').forEach(b => b.classList.toggle('selected', Number(b.dataset.discount) === Number(data.promo.discount_percent)));
      }
    } catch (_) { fail('Server bilan aloqa bo‘lmadi. Qayta urinib ko‘ring.'); }
    finally { $('refresh')?.classList.remove('loading'); }
  }

  async function copyValue(value, label) {
    if (!value) return;
    let copied = false;
    try { await navigator.clipboard.writeText(value); copied = true; } catch (_) {}
    haptic('medium');
    if (tg?.showPopup) tg.showPopup({title: copied ? 'Nusxalandi' : label, message: copied ? `${label} nusxalandi.` : value, buttons:[{type:'ok'}]});
    else alert(copied ? `${label} nusxalandi.` : value);
  }

  $('copyReferral')?.addEventListener('click', () => copyValue($('referral_link')?.textContent?.trim(), 'Referral link'));
  $('copyPromo')?.addEventListener('click', () => copyValue(currentPromo, 'Promo kod'));
  $('refresh')?.addEventListener('click', load);
  $('retry')?.addEventListener('click', () => { show('home'); load(); });

  $$('[data-discount]').forEach(btn => btn.addEventListener('click', async () => {
    const discount = Number(btn.dataset.discount);
    if (!initData) return fail('Telegram sessiyasi topilmadi.');
    haptic('medium');
    btn.disabled = true;
    try {
      const res = await api('/api/partner-miniapp/promo', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({discount_percent:discount})});
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || 'promo_failed');
      currentPromo = data.promo.code;
      text('promoCode', currentPromo);
      text('promoText', `${data.promo.discount_percent}% chegirma. START: ${data.payouts.start}, GROWTH: ${data.payouts.growth}, BUSINESS: ${data.payouts.business} komissiya qoladi.`);
      $('promoResult')?.classList.remove('hidden');
      $$('[data-discount]').forEach(b => b.classList.toggle('selected', Number(b.dataset.discount) === discount));
    } catch (_) {
      if (tg?.showAlert) tg.showAlert('Promo kodni yaratib bo‘lmadi. Qayta urinib ko‘ring.');
      else alert('Promo kodni yaratib bo‘lmadi.');
    } finally { btn.disabled = false; }
  }));

  $('closeToPayout')?.addEventListener('click', () => {
    haptic('medium');
    if (tg?.showPopup) tg.showPopup({title:'Pul yechish', message:'Mini App yopilgach botdagi “💸 Pul yechish” tugmasini bosing.', buttons:[{type:'ok'}]}, () => tg.close());
    else tg?.close();
  });

  load();
})();
