(() => {
  'use strict';
  const tg = window.Telegram?.WebApp;
  const tenant = document.body.dataset.tenant;
  let initData = tg?.initData || '';
  const previewMode = location.protocol === 'file:' || ['localhost', '127.0.0.1'].includes(location.hostname);
  let selectedCandidateId = null;
  let detailEnhancing = false;

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const fmt = value => new Intl.NumberFormat('uz-UZ').format(Number(value || 0));

  async function api(path, options = {}) {
    if (previewMode) {
      if (path === '/analytics/funnel') return {period_days:30,funnel:{applications:67,passed_filter:43,strong:18,interview:14,hired:5,no_show:2,rates:{filter_pass:64,strong:42,interview:33,hire:36}}};
      if (path === '/onboarding/status') return {completed:false,can_quick_setup:true,profile:{}};
      if (path.startsWith('/intelligence/compare')) return {vacancy:{key:'sales',title:'Sotuv menejeri'},comparison:{eligible:9,recommendation:{text:'Ali Otajonov hozircha eng yuqori moslikka ega. Oldingi ishida rejaning 118%ini bajargan.'},items:[
        {rank:1,id:1,full_name:'Ali Otajonov',score:88,metrics:{natijadorlik:92,masuliyat:84,aniqlik:87},strength:{summary:'Oldingi ishida rejaning 118%ini bajargan.',evidence:'Bir oyda rejaning 118 foizini bajarganman.'},salary:{amount:8000000,currency:'UZS'},risks:[]},
        {rank:2,id:2,full_name:'Dilnoza Karimova',score:81,metrics:{natijadorlik:80,masuliyat:85,aniqlik:79},strength:{summary:'Mijoz bilan ishlash jarayonini aniq tushuntirgan.',evidence:'CRMda har bir lead uchun keyingi qadamni belgilardim.'},salary:{amount:7000000,currency:'UZS'},risks:[]},
        {rank:3,id:3,full_name:'Javohir Akramov',score:72,metrics:{natijadorlik:68,masuliyat:76,aniqlik:72},strength:{summary:'Kommunikatsiya bo‘yicha yaxshi misol keltirgan.',evidence:'Mijoz e’tirozini savol bilan aniqlab olardim.'},salary:{amount:6000000,currency:'UZS'},risks:[{label:'Javobda aniq misol yoki o‘lchov yetishmaydi'}]}
      ]}};
      if (path.startsWith('/candidates/')) return {id:1,ai_scores:{achievement:{score:88,izoh:'Natija aniq raqam bilan tasdiqlangan.',evidence:'Bir oyda rejaning 118 foizini bajarganman.',red_flags:[]},plan:{score:79,izoh:'Reja tushunarli.',evidence:'Birinchi haftada vazifalarni o‘rganib, reja tuzaman.',red_flags:['natija_isbotsiz']}},risk_signals:[{label:'Da’vo aniq dalil yoki raqam bilan tasdiqlanmagan',severity:'medium'}]};
      if (path === '/vacancies') return {items:[{key:'sales',title:'Sotuv menejeri'},{key:'smm',title:'SMM mutaxassisi'}]};
      if (path === '/onboarding/quick-setup' && options.method === 'POST') return {ok:true,vacancy_key:'sales'};
      return {};
    }
    if(window.JanobHRAuth?.ensure) initData = await window.JanobHRAuth.ensure();
    const headers = window.JanobHRAuth?.headers
      ? window.JanobHRAuth.headers(options.headers||{})
      : {'Content-Type':'application/json', ...(initData?{'X-Telegram-Init-Data':initData,'Authorization':`tma ${initData}`}:{ }), ...options.headers};
    const response = await fetch(`/api/miniapp/${tenant}${path}`, {
      ...options,
      headers
    });
    if (!response.ok) throw new Error((await response.text()) || 'Server xatosi');
    return response.json();
  }

  function ensureUI() {
    const dashboard = document.querySelector('#dashboard');
    if (dashboard && !document.querySelector('#jh2-funnel-card')) {
      const plan = dashboard.querySelector('.plan-card');
      const wrap = document.createElement('div');
      wrap.innerHTML = `
        <article id="jh2-onboarding-card" class="jh2-card" hidden>
          <div class="jh2-card-head"><div><small>5 DAQIQALIK SOZLASH</small><h3>Botni biznesingizga moslang</h3><p>Lavozim, ideal xodim, savollar va suhbat vaqtlarini bitta oqimda tayyorlang.</p></div><button id="jh2-open-onboarding" class="jh2-primary">Boshlash</button></div>
        </article>
        <article id="jh2-funnel-card" class="jh2-card">
          <div class="jh2-card-head"><div><small>OXIRGI 30 KUN</small><h3>Hiring funnel</h3><p>Qayerda nomzodlar kamayib ketayotganini bir qarashda ko‘ring.</p></div></div>
          <div id="jh2-funnel" class="jh2-funnel"><div class="jh2-loading">Yuklanmoqda…</div></div>
        </article>`;
      if (plan) dashboard.insertBefore(wrap, plan); else dashboard.appendChild(wrap);
    }

    const candidates = document.querySelector('#candidates');
    if (candidates && !document.querySelector('#jh2-compare-tools')) {
      const filters = candidates.querySelector('#candidate-filters');
      const tools = document.createElement('div');
      tools.id = 'jh2-compare-tools';
      tools.className = 'jh2-compare-tools';
      tools.innerHTML = '<select id="jh2-compare-vacancy" aria-label="Taqqoslash uchun vakansiya"><option value="">Vakansiyani tanlang</option></select><button id="jh2-compare-top" type="button">Top 3 ni taqqoslash</button>';
      filters?.insertAdjacentElement('afterend', tools);
    }

    if (!document.querySelector('#jh2-overlay')) {
      const overlay = document.createElement('div');
      overlay.id = 'jh2-overlay';
      overlay.className = 'jh2-overlay';
      overlay.hidden = true;
      overlay.innerHTML = '<div class="jh2-sheet"><div class="jh2-sheet-top"><h2 id="jh2-sheet-title">Janob HR</h2><button class="jh2-close" id="jh2-close" aria-label="Yopish">×</button></div><div id="jh2-sheet-body"></div></div>';
      document.body.appendChild(overlay);
    }
  }

  function openSheet(title, html) {
    document.querySelector('#jh2-sheet-title').textContent = title;
    document.querySelector('#jh2-sheet-body').innerHTML = html;
    document.querySelector('#jh2-overlay').hidden = false;
  }
  function closeSheet() { document.querySelector('#jh2-overlay').hidden = true; }

  async function loadFunnel() {
    const target = document.querySelector('#jh2-funnel');
    if (!target) return;
    try {
      const data = await api('/analytics/funnel');
      const f = data.funnel;
      const steps = [
        ['Ariza',f.applications],['Filtrdan o‘tdi',f.passed_filter],['Kuchli',f.strong],['Suhbat',f.interview],['Ishga olindi',f.hired]
      ];
      target.innerHTML = steps.map(([label,value]) => `<div class="jh2-funnel-step"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join('');
    } catch (e) { target.innerHTML = `<div class="jh2-loading">${esc(e.message)}</div>`; }
  }

  async function loadOnboardingStatus() {
    const card = document.querySelector('#jh2-onboarding-card');
    if (!card) return;
    try {
      const data = await api('/onboarding/status');
      card.hidden = Boolean(data.completed) || !data.can_quick_setup;
    } catch { card.hidden = true; }
  }

  async function loadVacancyOptions() {
    const select = document.querySelector('#jh2-compare-vacancy');
    if (!select || select.dataset.loaded) return;
    try {
      const data = await api('/vacancies');
      select.innerHTML = '<option value="">Vakansiyani tanlang</option>' + (data.items || []).filter(v=>v.active!==false).map(v=>`<option value="${esc(v.key)}">${esc(v.title)}</option>`).join('');
      select.dataset.loaded = '1';
    } catch {}
  }

  function renderComparison(data) {
    const comparison = data.comparison || {};
    const cards = (comparison.items || []).map(item => {
      const metrics = item.metrics || {};
      const risks = (item.risks || []).map(r=>`<span class="jh2-risk">${esc(r.label)}</span>`).join('');
      const salary = item.salary ? `${fmt(item.salary.amount)} ${esc(item.salary.currency)}` : 'Ko‘rsatilmagan';
      return `<article class="jh2-candidate-card" data-candidate="${item.id}">
        <span class="jh2-rank">${item.rank}-o‘rin</span><h3>${esc(item.full_name)}</h3><div class="jh2-big-score">${item.score==null?'—':esc(item.score)+'/100'}</div>
        <div class="jh2-metrics"><span><b>${metrics.natijadorlik??'—'}</b>Natija</span><span><b>${metrics.masuliyat??'—'}</b>Mas’uliyat</span><span><b>${metrics.aniqlik??'—'}</b>Aniqlik</span></div>
        <p class="jh2-strength"><b>Kuchli tomoni:</b> ${esc(item.strength?.summary||'—')}</p><p class="jh2-strength"><b>Kutilayotgan maosh:</b> ${salary}</p>${risks}
      </article>`;
    }).join('');
    const recommend = comparison.recommendation?.text ? `<div class="jh2-recommend"><b>Janob HR tavsiyasi:</b><br>${esc(comparison.recommendation.text)}</div>` : '';
    openSheet(`${data.vacancy?.title || 'Nomzodlar'} · Top 3`, `${recommend}<div class="jh2-compare-grid">${cards || '<div class="jh2-loading">Taqqoslash uchun yetarli nomzod yo‘q.</div>'}</div>`);
  }

  async function compareTop() {
    const select = document.querySelector('#jh2-compare-vacancy');
    const key = select?.value;
    if (!key) { tg?.showAlert?.('Avval vakansiyani tanlang.'); return; }
    openSheet('Top nomzodlar', '<div class="jh2-loading">Taqqoslanmoqda…</div>');
    try { renderComparison(await api(`/intelligence/compare?vacancy_key=${encodeURIComponent(key)}&limit=3`)); }
    catch (e) { document.querySelector('#jh2-sheet-body').innerHTML = `<div class="jh2-loading">${esc(e.message)}</div>`; }
  }

  function onboardingForm() {
    openSheet('5 daqiqalik sozlash', `<form id="jh2-onboarding-form" class="jh2-form">
      <label>Biznes sohasi<input id="jh2-industry" maxlength="100" required placeholder="Masalan: mebel savdosi"></label>
      <label>Qaysi xodim kerak?<input id="jh2-role" maxlength="100" required placeholder="Masalan: Sotuv menejeri"></label>
      <label>Yaxshi xodim siz uchun qanday?<textarea id="jh2-ideal" rows="4" maxlength="700" required placeholder="Masalan: telefon savdosida kuchli, CRM biladi, reja bilan ishlaydi…"></textarea></label>
      <label>Kutilayotgan maksimal oylik (so‘m, ixtiyoriy)<input id="jh2-salary" type="number" min="0" step="100000" placeholder="8000000"></label>
      <label>Savollar soni<select id="jh2-question-count"><option>7</option><option selected>9</option><option>10</option><option>12</option></select></label>
      <label>Suhbat vaqtlari<textarea id="jh2-slots" rows="3" placeholder="2026-09-05T10:00\n2026-09-05T14:00"></textarea><span class="jh2-form-note">Har bir vaqtni yangi qatordan yozing. Bo‘sh qoldirsangiz keyin qo‘shasiz.</span></label>
      <label>Suhbat manzili<input id="jh2-location" maxlength="240" placeholder="Toshkent, Chilonzor…"></label>
      <button class="jh2-primary" type="submit">Tizimni tayyorlash</button>
      <div class="jh2-form-note">Janob HR vakansiya savollari, scorecard va red-flag tekshiruvlarini avtomatik tayyorlaydi.</div>
    </form>`);
  }

  function parseSlots(raw) {
    return String(raw||'').split(/\n+/).map(x=>x.trim()).filter(Boolean).slice(0,10).map(value=>{
      const date = new Date(value);
      return {label:value.replace('T',' '),starts_at:Number.isNaN(date.getTime())?null:date.toISOString(),capacity:1};
    });
  }

  async function submitOnboarding(event) {
    event.preventDefault();
    const button = event.target.querySelector('button[type="submit"]');
    button.disabled = true; button.textContent = 'Tayyorlanmoqda…';
    const body = {
      industry: document.querySelector('#jh2-industry').value.trim(),
      role_title: document.querySelector('#jh2-role').value.trim(),
      ideal_candidate: document.querySelector('#jh2-ideal').value.trim(),
      salary_budget_max: Number(document.querySelector('#jh2-salary').value || 0) || null,
      question_count: Number(document.querySelector('#jh2-question-count').value || 9),
      interview_slots: parseSlots(document.querySelector('#jh2-slots').value),
      location_text: document.querySelector('#jh2-location').value.trim()
    };
    try {
      await api('/onboarding/quick-setup',{method:'POST',body:JSON.stringify(body)});
      tg?.HapticFeedback?.notificationOccurred('success');
      document.querySelector('#jh2-sheet-body').innerHTML = '<div class="jh2-recommend"><b>Tayyor ✅</b><br>Vakansiya, savollar va suhbat sozlamalari yaratildi.</div><button class="jh2-primary" id="jh2-reload">Panelni yangilash</button>';
    } catch (e) {
      button.disabled = false; button.textContent = 'Tizimni tayyorlash';
      tg?.showAlert?.(e.message);
    }
  }

  async function enhanceCandidateDetail(id) {
    if (!id || detailEnhancing) return;
    const root = document.querySelector('#candidate-detail');
    if (!root || root.querySelector('.jh2-insights')) return;
    detailEnhancing = true;
    try {
      const c = await api(`/candidates/${id}`);
      const evidence = Object.values(c.ai_scores || {}).filter(x=>x && (x.evidence || x.dalil)).map(x=>`<div class="jh2-evidence"><b>AI bahosining dalili</b><p>${esc(x.evidence||x.dalil)}</p><small>${esc(x.izoh||'')} ${x.score!=null?'· '+esc(x.score)+'/100':''}</small></div>`).join('');
      const risks = (c.risk_signals || []).map(r=>`<span class="jh2-risk">${esc(r.label)}</span>`).join('');
      if (evidence || risks) root.querySelector('.detail-card')?.insertAdjacentHTML('beforeend', `<section class="jh2-insights"><h3>Nega bunday baholandi?</h3>${evidence}${risks?`<div>${risks}</div>`:''}</section>`);
    } catch {} finally { detailEnhancing = false; }
  }

  function refreshForView(name) {
    if (name === 'dashboard') { loadFunnel(); loadOnboardingStatus(); }
    if (name === 'candidates') loadVacancyOptions();
  }

  ensureUI();
  loadFunnel(); loadOnboardingStatus(); loadVacancyOptions();

  document.addEventListener('click', event => {
    const candidate = event.target.closest('[data-candidate]');
    if (candidate) { selectedCandidateId = candidate.dataset.candidate; setTimeout(()=>enhanceCandidateDetail(selectedCandidateId), 260); }
    const go = event.target.closest('[data-go]'); if (go) setTimeout(()=>refreshForView(go.dataset.go), 80);
    if (event.target.closest('#jh2-open-onboarding')) onboardingForm();
    if (event.target.closest('#jh2-close') || event.target === document.querySelector('#jh2-overlay')) closeSheet();
    if (event.target.closest('#jh2-compare-top')) compareTop();
    if (event.target.closest('#jh2-reload')) location.reload();
  });
  document.addEventListener('submit', event => { if (event.target.id === 'jh2-onboarding-form') submitOnboarding(event); });

  const detail = document.querySelector('#candidate-detail');
  if (detail) new MutationObserver(()=>{ if(selectedCandidateId) setTimeout(()=>enhanceCandidateDetail(selectedCandidateId),80); }).observe(detail,{childList:true,subtree:true});
})();
