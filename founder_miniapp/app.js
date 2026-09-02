(()=>{
  const tg=window.Telegram?.WebApp;
  const initData=tg?.initData||'';
  const preview=new URLSearchParams(location.search).has('preview');
  let data=null,customerFilter='all',paymentFilter='all',timer=null;
  const $=s=>document.querySelector(s);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=value=>new Intl.NumberFormat('uz-UZ').format(Number(value||0));
  const money=value=>num(value);
  const date=value=>value?new Intl.DateTimeFormat('uz-UZ',{day:'2-digit',month:'short',year:'numeric'}).format(new Date(value)):'—';
  const planNames={trial:'SINOV',start:'START',growth:'GROWTH',business:'BUSINESS',legacy:'MAXSUS'};
  const statusNames={active:'Faol',pending:'Yangi',inactive:"To'xtagan",awaiting_payment:"Kutilmoqda",needs_review:'Tekshirish kerak',approved:"To'langan",cancelled:'Bekor qilingan'};
  function text(id,value){const el=$(id);if(el)el.textContent=value;}
  function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),1800)}
  async function load(silent=false){
    if(!silent)$('#refresh').classList.add('loading');
    try{
      const response=await fetch('/api/founder/dashboard',{headers:{'X-Telegram-Init-Data':initData}});
      if(!response.ok)throw new Error((await response.text())||'Ma\'lumot ochilmadi');
      data=await response.json();render();
      if(!silent)tg?.HapticFeedback?.impactOccurred('light');
    }catch(error){if(!data)showError(error.message);else toast('Yangilab bo\'lmadi');}
    finally{$('#refresh').classList.remove('loading')}
  }
  function render(){
    text('#updated',`Yangilandi: ${new Date(data.generated_at).toLocaleTimeString('uz-UZ',{hour:'2-digit',minute:'2-digit'})}`);
    text('#revenue-month',money(data.revenue.month));text('#revenue-today',money(data.revenue.today));text('#active-count',num(data.tenants.active));text('#total-count',`Jami ${num(data.tenants.total)} biznes`);
    text('#renewal-count',num(data.renewals.length));text('#review-count',num(data.payments.needs_review));text('#revenue-week',money(data.revenue.week));text('#revenue-30',money(data.revenue.month));text('#revenue-all',money(data.revenue.all));
    text('#apps-today',num(data.applications.today));text('#apps-month',num(data.applications.month));text('#new-leads',num(data.leads.new));text('#waiting-payments',num(data.payments.awaiting_payment));
    const paid=data.plans.filter(p=>!['trial','legacy'].includes(p.plan_code)).reduce((s,p)=>s+p.count,0);text('#paid-total',`${paid} mijoz`);
    $('#plan-list').innerHTML=data.plans.length?data.plans.map(p=>`<div class="plan-row"><span class="plan-mark">${esc((planNames[p.plan_code]||p.plan_code).slice(0,2))}</span><div><b>${esc(planNames[p.plan_code]||p.plan_code)}</b><span>Faol obunalar</span></div><span class="plan-count">${num(p.count)}</span></div>`).join(''):'<div class="empty">Hali faol tarif yo‘q</div>';
    badge('#renewal-badge',data.renewals.length);badge('#payment-badge',data.payments.needs_review);
    renderRenewals();renderCustomers();renderPayments();
  }
  function badge(selector,count){const el=$(selector);el.hidden=!count;el.textContent=count>99?'99+':count}
  function contactLine(item){return [item.contact_name,item.contact_phone].filter(Boolean).map(esc).join(' · ')||'Kontakt yo‘q'}
  function renderRenewals(){
    $('#renewal-list').innerHTML=data.renewals.length?data.renewals.map(c=>`<article class="item"><div class="item-head"><div><h3>${esc(c.company_name)}</h3><p>${contactLine(c)}</p></div><span class="days ${c.days_left<0?'expired':''}">${c.days_left<0?`${Math.abs(c.days_left)} kun o‘tgan`:c.days_left===0?'Bugun tugaydi':`${c.days_left} kun qoldi`}</span></div><div class="item-meta"><span class="tag">${esc(planNames[c.plan_code]||c.plan_code)}</span><span class="tag">${date(c.subscription_expires_at)}</span><span class="tag">${num(c.applications)} ariza</span></div></article>`).join(''):'<div class="empty">Yaqin 7 kunda uzaytiriladigan tarif yo‘q</div>';
  }
  function renderCustomers(){
    const query=$('#customer-search').value.trim().toLowerCase();
    const items=data.customers.filter(c=>(customerFilter==='all'||c.status===customerFilter)&&(!query||`${c.company_name} ${c.contact_phone||''} ${c.contact_name||''}`.toLowerCase().includes(query)));
    $('#customer-list').innerHTML=items.length?items.map(c=>`<article class="item"><div class="item-head"><div><h3>${esc(c.company_name)}</h3><p>${contactLine(c)}</p></div><span class="tag ${esc(c.status)}">${esc(statusNames[c.status]||c.status)}</span></div><div class="item-meta"><span class="tag">${esc(planNames[c.plan_code]||c.plan_code)}</span><span class="tag">${num(c.applications)} ariza</span><span class="tag">${num(c.active_vacancies)} faol vakansiya</span>${c.subscription_expires_at?`<span class="tag">${date(c.subscription_expires_at)} gacha</span>`:''}</div></article>`).join(''):'<div class="empty">Mos biznes topilmadi</div>';
  }
  function renderPayments(){
    const items=data.recent_payments.filter(p=>paymentFilter==='all'||p.status===paymentFilter);
    $('#payment-list').innerHTML=items.length?items.map(p=>`<article class="item"><div class="item-head"><div><h3>${esc(p.company_name)}</h3><p>${esc(p.order_code)} · ${date(p.created_at)}</p></div><span class="tag ${esc(p.status)}">${esc(statusNames[p.status]||p.status)}</span></div><div class="item-meta"><span class="amount">${money(p.amount)} so‘m</span><span class="tag">${esc(planNames[p.plan_code]||p.plan_code)}</span>${p.contact_phone?`<span class="tag">${esc(p.contact_phone)}</span>`:''}</div></article>`).join(''):'<div class="empty">Bu holatda to‘lov topilmadi</div>';
  }
  function show(id){document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===id));document.querySelectorAll('nav [data-go]').forEach(b=>b.classList.toggle('active',b.dataset.go===id));scrollTo({top:0,behavior:'smooth'});if(id==='overview'&&data)render()}
  function showError(message){text('#error-text',message);show('error')}
  document.addEventListener('click',event=>{const go=event.target.closest('[data-go]');if(go)show(go.dataset.go)});
  $('#refresh').addEventListener('click',()=>load());$('#retry').addEventListener('click',()=>load());$('#customer-search').addEventListener('input',renderCustomers);
  $('#customer-filters').addEventListener('click',event=>{const b=event.target.closest('[data-filter]');if(!b)return;customerFilter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));renderCustomers()});
  $('#payment-filters').addEventListener('click',event=>{const b=event.target.closest('[data-payment-filter]');if(!b)return;paymentFilter=b.dataset.paymentFilter;document.querySelectorAll('[data-payment-filter]').forEach(x=>x.classList.toggle('active',x===b));renderPayments()});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load(true)});
  tg?.ready();tg?.expand();tg?.setHeaderColor?.('#f4f5f7');tg?.setBackgroundColor?.('#f4f5f7');
  if(!initData&&!preview)showError('Mini Appni Founder bot ichidan oching.');else{load();timer=setInterval(()=>load(true),30000)}
})();
