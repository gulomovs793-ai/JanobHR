(() => {
  const tg = window.Telegram?.WebApp || null;
  const $ = (id) => document.getElementById(id);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const initData = tg?.initData || '';
  let currentPromo = '';
  let promoType = 'percent';
  let promoCaps = {
    all: {percent: 25, amount: 99000},
    start: {percent: 33, amount: 99000},
    growth: {percent: 33, amount: 199000},
    business: {percent: 25, amount: 299000},
  };

  if (tg) {
    tg.ready(); tg.expand();
    try { tg.setHeaderColor('#f5f5f7'); tg.setBackgroundColor('#f5f5f7'); } catch (_) {}
  }
  const haptic = (kind='light') => { try { tg?.HapticFeedback?.impactOccurred(kind); } catch (_) {} };
  const text = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const formatUzs = (value) => `${Number(value || 0).toLocaleString('uz-UZ')} UZS`;
  const dateLabel = (value, options={day:'2-digit', month:'short'}) => {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('uz-UZ', options);
  };
  const promoPlanLabel = {all:'barcha tariflar', start:'faqat START', growth:'faqat GROWTH', business:'faqat BUSINESS'};
  const getPromoCap = (planCode, type) => Number(promoCaps[planCode]?.[type] ?? promoCaps.all[type] ?? 0);
  function updatePromoLimit() {
    const type = promoType === 'amount' ? 'amount' : 'percent';
    const planCode = $('promoPlan')?.value || 'all';
    const cap = getPromoCap(planCode, type);
    const input = $('discountValue');
    if (input) {
      input.max = String(cap);
      input.min = type === 'amount' ? '1' : '0';
      input.placeholder = type === 'amount' ? 'Masalan, 30000' : 'Masalan, 10';
    }
    text('discountSuffix', type === 'amount' ? 'UZS' : '%');
    text('promoLimit', `Maksimum: ${cap.toLocaleString('uz-UZ')}${type === 'amount' ? ' UZS' : '%'} — ${promoPlanLabel[planCode] || 'tarif'}.`);
  }
  function renderActivity(items) {
    const root = $('activity'); if (!root) return;
    if (!items?.length) { root.innerHTML = '<p class="empty">Faoliyat hali yo‘q.</p>'; return; }
    root.innerHTML = items.map(item => {
      const date = dateLabel(item.created_at);
      const detail = item.type === 'sale' && item.plan_code ? ` · ${String(item.plan_code).toUpperCase()}` : ' · Referral kanali';
      const commission = item.type === 'sale' ? `<strong>${Number(item.commission || 0).toLocaleString('uz-UZ')} UZS</strong>` : '';
      return `<div class="activity-row"><span class="activity-icon">${esc(item.icon || '•')}</span><div><b>${esc(item.label || 'Faoliyat')}</b><small>${esc(detail)}${date ? ` · ${esc(date)}` : ''}</small></div>${commission}</div>`;
    }).join('');
  }
  function renderLeads(items, id='leads') {
    const root = $(id); if (!root) return;
    if (!items?.length) { root.innerHTML = '<p class="empty">Leadlar hali yo‘q.</p>'; return; }
    root.innerHTML = items.map(item => {
      const date = dateLabel(item.created_at);
      const source = item.source === 'promo_code' ? 'Promo orqali' : 'Referral orqali';
      const plan = item.plan_code ? String(item.plan_code).toUpperCase() : '';
      const commission = Number(item.commission_amount || 0);
      const earning = plan && commission > 0 ? `<small><b>${esc(plan)}</b> → sizga <b>${commission.toLocaleString('uz-UZ')} UZS</b></small>` : '';
      return `<div class="lead-row"><div><b>${esc(item.company_name || 'Noma’lum kompaniya')}</b><small>${esc(source)}${date ? ` · ${esc(date)}` : ''}</small>${earning}</div><span class="lead-status">${esc(item.status_label || '🆕 Yangi')}</span></div>`;
    }).join('');
  }
  function renderPayout(balance) {
    const active = balance?.active_request;
    const status = $('payoutStatus');
    const form = $('payoutForm');
    if (!status || !form) return;
    if (active) {
      status.classList.remove('hidden'); form.classList.add('hidden');
      text('payoutStatusTitle', `#${active.id} — ko‘rib chiqilmoqda`);
      const delay = Number(active.delay_days || 0);
      text('payoutStatusText', `Asosiy summa: ${formatUzs(active.requested_amount)}\nKechikish bonusi: ${formatUzs(active.bonus_amount)}${delay ? ` (${delay} kun)` : ''}\nAniq o‘tkazma: ${formatUzs(active.total_amount)}\nTo‘lov kuni: ${active.payout_due_date || '—'}\n\nSana o‘tsa, summa har yangilanganda qayta hisoblanadi.`);
    } else {
      status.classList.add('hidden'); form.classList.remove('hidden');
    }
  }
  function show(name) {
    $$('.view').forEach(v => v.classList.toggle('active', v.id === name));
    $$('.bottom-nav [data-go]').forEach(b => b.classList.toggle('active', b.dataset.go === name));
    window.scrollTo({top:0, behavior:'smooth'}); haptic();
  }
  $$('[data-go]').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.go)));
  function fail(message) { text('errorMessage', message || 'Mini Appni Hamkor bot ichidan qayta oching.'); show('error'); }
  async function api(path, options={}) {
    const headers = Object.assign({'X-Telegram-Init-Data': initData}, options.headers || {});
    return fetch(path, Object.assign({cache:'no-store'}, options, {headers}));
  }
  async function load() {
    if (!initData) return fail('Telegram tasdiqlashi topilmadi. Panelni Hamkor bot ichidagi ko‘k tugmadan oching.');
    $('refresh')?.classList.add('loading');
    try {
      const res = await api('/api/partner-miniapp/stats'); const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        if (res.status === 403) return fail('Bu panel faqat tasdiqlangan hamkorlar uchun.');
        if (res.status === 401) return fail('Telegram sessiyasi tasdiqlanmadi. Mini Appni bot ichidan qayta oching.');
        return fail('Ma’lumotlarni yuklab bo‘lmadi. Qayta urinib ko‘ring.');
      }
      const s = data.stats || {}; const earned = s.earned_label || '0 UZS';
      if (data.promo_caps && typeof data.promo_caps === 'object') promoCaps = Object.assign(promoCaps, data.promo_caps);
      text('partnerName', data.partner?.full_name || 'Hamkor paneli');
      text('clicks', s.clicks ?? 0); text('trials', s.trials ?? 0); text('sales', s.sales ?? 0); text('promo_sales', s.promo_sales ?? 0);
      text('earned', earned); text('earnedLarge', earned);
      const balance = data.balance || {};
      text('totalEarned', balance.earned_label || earned); text('totalEarnedLarge', balance.earned_label || earned);
      text('paidAmount', balance.paid_label || '0 UZS'); text('paidAmountLarge', balance.paid_label || '0 UZS');
      text('reservedAmount', balance.reserved_label || '0 UZS'); text('earned', balance.available_label || earned); text('earnedLarge', balance.available_label || earned);
      const due = balance.next_payout_date || balance.active_request?.payout_due_date || '—'; text('nextPayout', due);
      const delay = Number(balance.active_request?.delay_days || 0);
      text('balanceNote', delay ? `Faol ariza · ${delay} kun kechikish` : 'Tasdiqlangan sotuvlardan.');
      text('earningsNote', delay ? `Kechikish bonusi: ${Number(balance.active_request?.bonus_amount || 0).toLocaleString('uz-UZ')} UZS` : 'Tasdiqlangan sotuvlardan.');
      text('openPayout', balance.active_request ? 'Arizani ko‘rish' : 'Pul yechish arizasini yuborish');
      renderPayout(balance);
      if ($('payoutFullName') && !$('payoutFullName').value) $('payoutFullName').value = data.partner?.full_name || '';
      if ($('payoutUsername') && !$('payoutUsername').value && data.partner?.username) $('payoutUsername').value = data.partner.username.startsWith('@') ? data.partner.username : `@${data.partner.username}`;
      renderActivity(data.activity || []); renderLeads(data.leads || [], 'leads'); renderLeads(data.leads || [], 'leadsFull');
      text('referral_link', data.referral_link || 'Referral link topilmadi');
      if (data.promo?.code) {
        currentPromo = data.promo.code; text('promoCode', data.promo.code);
        const value = data.promo.discount_type === 'amount' ? `${Number(data.promo.discount_value || 0).toLocaleString('uz-UZ')} UZS` : `${data.promo.discount_value || data.promo.discount_percent}%`;
        const expires = dateLabel(data.promo.expires_at, {year:'numeric', month:'2-digit', day:'2-digit'}) || '—';
        text('promoText', `${value} chegirma faol. Amal qilish muddati: ${expires}.`); $('promoResult')?.classList.remove('hidden');
        promoType = data.promo.discount_type || 'percent';
        $$('[data-promo-type]').forEach(b => b.classList.toggle('selected', b.dataset.promoType === promoType));
        if ($('discountValue')) $('discountValue').value = data.promo.discount_value || data.promo.discount_percent || '';
        if ($('promoPlan')) $('promoPlan').value = data.promo.plan_code || 'all';
      }
      updatePromoLimit();
    } catch (_) { fail('Server bilan aloqa bo‘lmadi. Qayta urinib ko‘ring.'); }
    finally { $('refresh')?.classList.remove('loading'); }
  }
  async function copyValue(value, label) {
    if (!value) return; let copied = false;
    try { await navigator.clipboard.writeText(value); copied = true; } catch (_) {}
    haptic('medium');
    if (tg?.showPopup) tg.showPopup({title: copied ? 'Nusxalandi' : label, message: copied ? `${label} nusxalandi.` : value, buttons:[{type:'ok'}]});
    else alert(copied ? `${label} nusxalandi.` : value);
  }
  $('copyReferral')?.addEventListener('click', () => copyValue($('referral_link')?.textContent?.trim(), 'Referral link'));
  $('copyPromo')?.addEventListener('click', () => copyValue(currentPromo, 'Promo kod'));
  $('refresh')?.addEventListener('click', load); $('retry')?.addEventListener('click', () => { show('home'); load(); });
  $$('[data-promo-type]').forEach(btn => btn.addEventListener('click', () => {
    promoType = btn.dataset.promoType; $$('[data-promo-type]').forEach(b => b.classList.toggle('selected', b.dataset.promoType === promoType));
    updatePromoLimit();
  }));
  $('promoPlan')?.addEventListener('change', updatePromoLimit);
  $('createPromo')?.addEventListener('click', async () => {
    const discount = Number($('discountValue')?.value || 0); const duration = Number($('durationDays')?.value || 0); const planCode = $('promoPlan')?.value || 'all';
    if (!initData) return fail('Telegram sessiyasi topilmadi.');
    const cap = getPromoCap(planCode, promoType);
    if (discount < 0 || (promoType === 'amount' && discount === 0) || duration < 1 || duration > 365 || discount > cap) { if (tg?.showAlert) tg.showAlert(`Chegirma miqdori noto‘g‘ri. Maksimum: ${cap.toLocaleString('uz-UZ')}${promoType === 'amount' ? ' UZS' : '%'}.`); return; }
    haptic('medium'); const btn = $('createPromo'); btn.disabled = true;
    try {
      const res = await api('/api/partner-miniapp/promo', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({discount_type:promoType, discount_value:discount, duration_days:duration, plan_code:planCode})});
      const data = await res.json().catch(() => ({})); if (!res.ok || !data.ok) throw new Error(data.error || 'promo_failed');
      currentPromo = data.promo.code; text('promoCode', currentPromo);
      const label = promoType === 'amount' ? `${discount.toLocaleString('uz-UZ')} UZS` : `${discount}%`; const expires = dateLabel(data.promo.expires_at, {year:'numeric', month:'2-digit', day:'2-digit'}) || '—';
      const planLabel = promoPlanLabel[planCode] || promoPlanLabel.all;
      const payoutText = planCode === 'all'
        ? `START: ${data.payouts.start}, GROWTH: ${data.payouts.growth}, BUSINESS: ${data.payouts.business}`
        : `${planCode.toUpperCase()}: ${data.payouts[planCode]}`;
      text('promoText', `${label} chegirma · ${planLabel}. Amal qilish muddati: ${expires}. ${payoutText} komissiya qoladi.`); $('promoResult')?.classList.remove('hidden');
    } catch (_) { if (tg?.showAlert) tg.showAlert(`Promo kodni yaratib bo‘lmadi. Maksimum: ${cap.toLocaleString('uz-UZ')}${promoType === 'amount' ? ' UZS' : '%'}.`); else alert('Promo kodni yaratib bo‘lmadi.'); }
    finally { btn.disabled = false; }
  });
  $('submitPayout')?.addEventListener('click', async () => {
    const fullName = $('payoutFullName')?.value?.trim() || '';
    const cardNumber = $('payoutCard')?.value?.trim() || '';
    const receiptUsername = $('payoutUsername')?.value?.trim() || '';
    if (!fullName || !cardNumber || !receiptUsername) {
      const message = "Ism-familiya, karta raqami va Telegram username'ni to‘liq kiriting.";
      text('payoutMessage', message); if (tg?.showAlert) tg.showAlert(message); return;
    }
    const btn = $('submitPayout'); btn.disabled = true; text('payoutMessage', 'Ariza yuborilmoqda…'); haptic('medium');
    try {
      const res = await api('/api/partner-miniapp/payout', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({full_name:fullName, card_number:cardNumber, receipt_username:receiptUsername})});
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || 'Payout arizasi yaratilmadi.');
      const payout = data.payout || {};
      const notice = data.founder_notified ? 'Founder Botga notification yuborildi.' : 'Founder Bot notificationi recovery orqali qayta yuboriladi.';
      const message = `Ariza #${payout.id || '—'} yuborildi. Aniq summa: ${formatUzs(payout.total_amount)}. ${notice}`;
      text('payoutMessage', message);
      if (tg?.showPopup) tg.showPopup({title:'Ariza yuborildi', message, buttons:[{type:'ok'}]});
      await load(); show('payout');
    } catch (error) {
      const message = error?.message || 'Payout arizasini yuborib bo‘lmadi. Qayta urinib ko‘ring.';
      text('payoutMessage', message); if (tg?.showAlert) tg.showAlert(message);
    } finally { btn.disabled = false; }
  });
  updatePromoLimit();
  load(); window.setInterval(() => { if (!document.hidden) load(); }, 15000);
})();
