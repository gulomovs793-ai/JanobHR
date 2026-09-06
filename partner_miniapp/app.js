(() => {
  const root = document.getElementById('app');
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const q = (id) => document.getElementById(id);
  const setText = (id, value) => {
    const el = q(id);
    if (el) el.textContent = value;
  };

  const init = tg && tg.initDataUnsafe ? tg.initDataUnsafe : {};
  const userId = init.user && init.user.id ? init.user.id : '';

  async function loadStats() {
    if (!userId) return;
    try {
      const res = await fetch(`/api/partner-miniapp/stats?user_id=${encodeURIComponent(userId)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.ok) return;
      setText('clicks', data.stats.clicks ?? '0');
      setText('trials', data.stats.trials ?? '0');
      setText('sales', data.stats.sales ?? '0');
      setText('promo_sales', data.stats.promo_sales ?? '0');
      setText('earned', data.stats.earned_label || '0 UZS');
      if (data.referral_link) setText('referral_link', data.referral_link);
    } catch (err) {
      console.warn('Partner stats yuklanmadi', err);
    }
  }

  q('copyReferral')?.addEventListener('click', () => {
    const text = q('referral_link')?.textContent || '';
    if (tg && tg.showPopup) {
      tg.showPopup({title: 'Referral link', message: text, buttons: [{type: 'ok'}]});
    } else {
      alert(text);
    }
  });

  q('openPayout')?.addEventListener('click', () => {
    if (tg) tg.close();
  });

  loadStats();
})();
