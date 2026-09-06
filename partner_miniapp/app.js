(() => {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const q = (id) => document.getElementById(id);
  const all = (selector) => Array.from(document.querySelectorAll(selector));

  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor('#f5f5f7'); } catch (_) {}
    try { tg.setBackgroundColor('#f5f5f7'); } catch (_) {}
  }

  const initData = tg && tg.initData ? tg.initData : '';
  let currentView = 'home';

  function haptic(type = 'light') {
    try { tg?.HapticFeedback?.impactOccurred(type); } catch (_) {}
  }

  function setText(id, value) {
    const el = q(id);
    if (el) el.textContent = value;
  }

  function showView(name) {
    currentView = name;
    all('.view').forEach((view) => view.classList.toggle('active', view.id === name));
    all('.bottom-nav [data-go]').forEach((btn) => btn.classList.toggle('active', btn.dataset.go === name));
    window.scrollTo({ top: 0, behavior: 'smooth' });
    haptic('light');
  }

  all('[data-go]').forEach((button) => {
    button.addEventListener('click', () => showView(button.dataset.go));
  });

  function showError(message) {
    setText('errorMessage', message || 'Mini Appni Hamkor bot ichidan qayta oching.');
    showView('error');
  }

  async function loadStats() {
    if (!initData) {
      showError('Telegram tasdiqlashi topilmadi. Panelni Hamkor bot ichidagi Mini App tugmasidan oching.');
      return;
    }

    q('refresh')?.classList.add('loading');
    try {
      const res = await fetch('/api/partner-miniapp/stats', {
        headers: { 'X-Telegram-Init-Data': initData },
        cache: 'no-store'
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        if (res.status === 403) {
          showError('Bu panel faqat tasdiqlangan hamkorlar uchun.');
        } else if (res.status === 401) {
          showError('Telegram sessiyasi tasdiqlanmadi. Mini Appni bot ichidan qayta oching.');
        } else {
          showError('Statistikani yuklab bo‘lmadi. Keyinroq qayta urinib ko‘ring.');
        }
        return;
      }

      const stats = data.stats || {};
      const earned = stats.earned_label || '0 UZS';
      setText('clicks', stats.clicks ?? '0');
      setText('trials', stats.trials ?? '0');
      setText('sales', stats.sales ?? '0');
      setText('promo_sales', stats.promo_sales ?? '0');
      setText('earned', earned);
      setText('earnedLarge', earned);
      setText('partnerName', data.partner?.full_name ? `${data.partner.full_name}` : 'Hamkor paneli');
      if (data.referral_link) setText('referral_link', data.referral_link);
    } catch (err) {
      console.warn('Partner stats yuklanmadi', err);
      showError('Internet yoki server bilan aloqa bo‘lmadi. Qayta urinib ko‘ring.');
    } finally {
      q('refresh')?.classList.remove('loading');
    }
  }

  async function copyReferral() {
    const text = q('referral_link')?.textContent?.trim() || '';
    if (!text || text === 'Yuklanmoqda…') return;
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch (_) {}

    haptic('medium');
    if (tg?.showPopup) {
      tg.showPopup({
        title: copied ? 'Nusxalandi' : 'Referral link',
        message: copied ? 'Referral link clipboardga nusxalandi.' : text,
        buttons: [{ type: 'ok' }]
      });
    } else {
      alert(copied ? 'Referral link nusxalandi.' : text);
    }
  }

  q('copyReferral')?.addEventListener('click', copyReferral);
  q('refresh')?.addEventListener('click', () => {
    haptic('light');
    loadStats();
  });
  q('retry')?.addEventListener('click', () => {
    showView('home');
    loadStats();
  });
  q('closeToPayout')?.addEventListener('click', () => {
    haptic('medium');
    if (tg?.showPopup) {
      tg.showPopup({
        title: 'Pul yechish',
        message: 'Mini App yopilgach bot menyusidagi “💸 Pul yechish” tugmasini bosing.',
        buttons: [{ type: 'ok' }]
      }, () => tg.close());
    } else if (tg) {
      tg.close();
    }
  });

  loadStats();
})();
