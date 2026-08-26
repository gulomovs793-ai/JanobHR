import { type ReactNode, useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowUpRight,
  Bot,
  CalendarClock,
  Check,
  ChevronDown,
  CircleCheck,
  Clipboard,
  Clock3,
  FileCheck2,
  Menu,
  MessageCircle,
  Mic,
  QrCode,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Router as WouterRouter, useLocation } from 'wouter';

const queryClient = new QueryClient();

const navItems = [
  { label: 'Muammo', href: '#muammo' },
  { label: 'Qanday ishlaydi', href: '#qanday-ishlaydi' },
  { label: 'Imkoniyatlar', href: '#imkoniyatlar' },
  { label: 'Tariflar', href: '#tariflar' },
  { label: 'FAQ', href: '#faq' },
];

function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <a
      href="#bosh-sahifa"
      className="focus-ring group inline-flex items-center gap-3"
      data-testid="link-brand"
      aria-label="JanobHR bosh sahifasi"
    >
      <img
        src="/logo.png"
        alt="JanobHR"
        className="h-10 w-10 rounded-[13px] object-cover shadow-[0_8px_20px_hsl(var(--primary)/.22)] transition-transform duration-300 group-hover:-rotate-6"
      />
      <span className={`font-display font-extrabold tracking-[-.04em] ${compact ? 'text-primary-foreground' : 'text-foreground'} ${compact ? 'text-lg' : 'text-xl'}`}>
        Janob<span className="text-primary">HR</span>
      </span>
    </a>
  );
}

function TelegramGlyph({ size = 18 }: { size?: number }) {
  return <MessageCircle size={size} strokeWidth={1.8} aria-hidden="true" />;
}

function Nav() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  const closeMenu = () => setOpen(false);

  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-foreground/[0.07] bg-background/90 backdrop-blur-xl">
      <div className="mx-auto flex h-[76px] max-w-[1240px] items-center justify-between px-5 sm:px-8 lg:px-10">
        <BrandMark />
        <nav className="hidden items-center gap-8 lg:flex" aria-label="Asosiy navigatsiya">
          {navItems.map((item) => (
            <a
              href={item.href}
              className="focus-ring text-[13px] font-semibold text-muted-foreground transition-colors hover:text-primary"
              key={item.href}
              data-testid={`link-nav-${item.label.toLowerCase().replaceAll(' ', '-')}`}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-4 lg:flex">
          <a href="https://t.me/janobHR_bot" target="_blank" rel="noreferrer" className="focus-ring text-[13px] font-semibold text-muted-foreground hover:text-primary" data-testid="link-nav-telegram">
            @janobHR_bot
          </a>
          <a
            href="https://t.me/janobHR_bot"
            target="_blank"
            rel="noreferrer"
            className="focus-ring inline-flex items-center gap-2 rounded-full bg-primary px-5 py-3 text-[13px] font-bold text-primary-foreground transition-[transform,background-color] duration-200 hover:-translate-y-0.5 hover:bg-[hsl(var(--primary)/.88)]"
            data-testid="button-nav-contact"
          >
            Botni sinab ko‘rish <ArrowUpRight size={16} aria-hidden="true" />
          </a>
        </div>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="focus-ring inline-flex h-11 w-11 items-center justify-center rounded-full border border-border text-primary lg:hidden"
          aria-expanded={open}
          aria-label={open ? 'Menyuni yopish' : 'Menyuni ochish'}
          data-testid="button-mobile-menu"
        >
          {open ? <X size={21} /> : <Menu size={21} />}
        </button>
      </div>
      {open && (
        <div className="border-t border-border bg-background px-5 pb-7 pt-5 lg:hidden">
          <nav className="flex flex-col gap-1" aria-label="Mobil navigatsiya">
            {navItems.map((item, index) => (
              <a
                href={item.href}
                onClick={closeMenu}
                className="focus-ring flex items-center justify-between border-b border-border py-4 text-lg font-semibold"
                key={item.href}
                data-testid={`link-mobile-nav-${index}`}
              >
                {item.label} <ArrowUpRight size={18} />
              </a>
            ))}
          </nav>
          <a
            href="https://t.me/janobHR_bot"
            target="_blank"
            rel="noreferrer"
            onClick={closeMenu}
            className="focus-ring mt-5 flex w-full items-center justify-center gap-2 rounded-full bg-primary px-5 py-4 font-bold text-primary-foreground"
            data-testid="button-mobile-contact"
          >
            Telegram orqali bog‘lanish <TelegramGlyph size={18} />
          </a>
        </div>
      )}
    </header>
  );
}

function TelegramPreview() {
  return (
    <div className="relative mx-auto w-full max-w-[470px]">
      <div className="absolute -right-8 top-10 h-44 w-44 rounded-full bg-secondary/45 blur-3xl" />
      <div className="absolute -bottom-8 left-2 h-36 w-36 rounded-full bg-accent/30 blur-3xl" />
      <div className="relative rounded-[28px] border border-primary/15 bg-[#eaf1fb] p-3 shadow-[0_28px_70px_hsl(var(--primary)/.14)] sm:p-4">
        <div className="overflow-hidden rounded-[20px] border border-[#c9dbf2] bg-[#dfebfa]">
          <div className="flex items-center justify-between bg-primary px-4 py-3 text-primary-foreground">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-primary">
                <Bot size={17} />
              </div>
              <div>
                <p className="font-display text-[12px] font-bold">JanobHR Bot</p>
                <p className="font-mono text-[8px] uppercase tracking-[.12em] text-primary-foreground/60">online</p>
              </div>
            </div>
            <span className="font-mono text-[9px] text-primary-foreground/60">09:41</span>
          </div>
          <div className="space-y-3 p-3 sm:p-4">
            <div className="max-w-[86%] rounded-[15px] rounded-tl-[4px] bg-[#f5f9fe] px-3 py-3 text-[11px] leading-relaxed text-foreground shadow-sm">
              🆕 Yangi ariza — Marketing menejeri
              <div className="mt-3 rounded-xl border border-primary/10 bg-primary/[.055] p-2.5">
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-display text-[10px] font-bold">Marketing menejeri</span>
                  <span className="rounded-full bg-primary/10 px-2 py-0.5 font-mono text-[8px] text-primary">12 nomzod</span>
                </div>
                <div className="space-y-2">
                  {['Madina Karimova', 'Sardor Abduqodirov', 'Nilufar Tursunova'].map((name, index) => (
                    <div className="flex items-center gap-2" key={name}>
                      <span className="font-mono text-[9px] text-muted-foreground">0{index + 1}</span>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                        <span className="block h-full rounded-full bg-primary" style={{ width: `${92 - index * 11}%` }} />
                      </span>
                      <span className="w-[92px] truncate text-[9px] font-semibold">{name}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="ml-auto max-w-[78%] rounded-[15px] rounded-tr-[4px] bg-secondary/80 px-3 py-2.5 text-[11px] leading-relaxed text-foreground">
              ✅ Madina bilan suhbatga chaqiraman
            </div>
            <div className="flex items-center gap-1.5 pl-1 text-[9px] text-muted-foreground">
              <span className="pulse-soft h-1.5 w-1.5 rounded-full bg-primary" />
              Suhbat vaqti nomzodga yuborilmoqda
            </div>
          </div>
          <div className="border-t border-[#c9dbf2] bg-[#eaf1fb] px-3 py-2.5">
            <div className="rounded-full border border-[#c9dbf2] bg-[#f5f9fe] px-3 py-2 text-[9px] text-muted-foreground">
              Xabar yozing...
            </div>
          </div>
        </div>
      </div>
      <div className="drift absolute -left-8 bottom-10 hidden rounded-2xl border border-primary/10 bg-card p-3 shadow-[0_15px_30px_hsl(var(--primary)/.1)] sm:block">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#d9eadc] text-primary"><CircleCheck size={15} /></span>
          <div><p className="font-mono text-[8px] uppercase tracking-wider text-muted-foreground">baholash</p><p className="font-display text-[11px] font-bold">Tahlil tayyor</p></div>
        </div>
      </div>
    </div>
  );
}

function SectionLabel({ children, light = false }: { children: string; light?: boolean }) {
  return (
    <div className="relative mb-7 inline-block">
      <span
        className={`font-hand text-2xl font-bold tracking-wide sm:text-[1.7rem] ${
          light ? 'text-secondary' : 'text-primary'
        }`}
      >
        {children}
      </span>
      <svg
        className="absolute -bottom-1 left-0 w-full"
        viewBox="0 0 100 8"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path
          d="M1 5.5C15 2 30 7 45 4C60 1 75 6.5 99 3"
          fill="none"
          strokeWidth="2.5"
          strokeLinecap="round"
          className={light ? 'stroke-secondary' : 'stroke-primary'}
        />
      </svg>
    </div>
  );
}

function WorkflowStep({ number, icon: Icon, title, children }: { number: string; icon: typeof Search; title: string; children: string }) {
  return (
    <article className="group relative border-t border-border pt-5">
      <div className="mb-9 flex items-center justify-between">
        <span className="font-mono text-[11px] font-bold text-primary">{number}</span>
        <span className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-background text-primary transition-colors group-hover:border-accent group-hover:bg-secondary/30">
          <Icon size={18} strokeWidth={1.7} />
        </span>
      </div>
      <h3 className="font-display text-xl font-extrabold tracking-[-.03em]">{title}</h3>
      <p className="mt-3 max-w-[270px] text-sm leading-6 text-muted-foreground">{children}</p>
    </article>
  );
}

function FeatureCard({ icon: Icon, eyebrow, title, children, className = '' }: { icon: typeof Search; eyebrow: string; title: string; children: string; className?: string }) {
  return (
    <article className={`group rounded-[22px] border border-border bg-card p-6 transition-[transform,box-shadow,border-color] duration-300 hover:-translate-y-1 hover:border-primary/25 hover:shadow-[0_16px_34px_hsl(var(--primary)/.09)] sm:p-7 ${className}`}>
      <span className="mb-12 flex h-11 w-11 items-center justify-center rounded-[14px] bg-secondary/45 text-primary transition-colors group-hover:bg-accent/55">
        <Icon size={20} strokeWidth={1.7} />
      </span>
      <p className="inline-block rounded-full bg-primary/10 px-3 py-1 font-mono text-xs font-bold uppercase tracking-[.14em] text-primary">{eyebrow}</p>
      <h3 className="mt-4 font-display text-xl font-extrabold tracking-[-.035em]">{title}</h3>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{children}</p>
    </article>
  );
}

function Home() {
  return (
    <div className="grain min-h-[100dvh] overflow-hidden bg-background">
      <Nav />

      <main>
        <section id="bosh-sahifa" className="site-grid relative scroll-mt-20 border-b border-border pt-[76px]">
          <div className="mx-auto grid min-h-[690px] max-w-[1240px] items-center gap-12 px-5 py-20 sm:px-8 sm:py-24 lg:grid-cols-[1.02fr_.98fr] lg:gap-16 lg:px-10 lg:py-28">
            <div className="relative z-10 max-w-[650px]">
              <div className="reveal inline-flex items-center gap-2.5 rounded-full bg-primary/10 px-4 py-2 font-mono text-xs font-bold uppercase tracking-[.14em] text-primary">
                <Sparkles size={14} className="text-accent" /> Telegram’da ishlaydigan HR bot
              </div>
              <h1 className="reveal reveal-delay-1 mt-7 max-w-[720px] font-display text-[clamp(3rem,5.3vw,5.2rem)] font-extrabold leading-[.96] tracking-[-.075em] text-foreground">
                Nomzodni <span className="text-primary">AI saralaydi.</span><br />Siz esa tanlaysiz.
              </h1>
              <p className="reveal reveal-delay-2 mt-7 max-w-[530px] text-[17px] leading-7 text-muted-foreground sm:text-lg">
                Vakansiya yaratasiz — nomzodlar Telegram botga o‘zi ariza topshiradi, AI javoblarini baholaydi, siz esa faqat mos kelganlar bilan suhbatlashasiz. Birinchi 5 ta ariza — bepul.
              </p>
              <div className="reveal reveal-delay-3 mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
                <a
                  href="https://t.me/janobHR_bot"
                  target="_blank"
                  rel="noreferrer"
                  className="focus-ring inline-flex items-center justify-center gap-3 rounded-full bg-primary px-6 py-4 text-sm font-bold text-primary-foreground shadow-[0_12px_24px_hsl(var(--primary)/.16)] transition-[transform,background-color] hover:-translate-y-0.5 hover:bg-[hsl(var(--primary)/.88)]"
                  data-testid="button-hero-contact"
                >
                  JanobHR bilan boshlash <ArrowUpRight size={17} />
                </a>
                <a href="#qanday-ishlaydi" className="focus-ring inline-flex items-center justify-center gap-2 rounded-full px-5 py-4 text-sm font-bold text-primary transition-colors hover:bg-secondary/30" data-testid="link-hero-how">
                  Qanday ishlaydi <ArrowDown size={16} />
                </a>
              </div>
              <div className="reveal reveal-delay-4 mt-12 flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex -space-x-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-background bg-primary font-mono text-[9px] text-primary-foreground">HR</span>
                  <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-background bg-secondary font-mono text-[9px] text-foreground">UZ</span>
                  <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-background bg-accent font-mono text-[9px] text-foreground">AI</span>
                </span>
                Odamlar qaror qiladi. AI esa saralab beradi.
              </div>
            </div>
            <div className="reveal reveal-delay-2 relative z-10 lg:pt-4">
              <TelegramPreview />
            </div>
          </div>
          <div className="absolute bottom-8 right-8 hidden items-center gap-3 font-mono text-[9px] uppercase tracking-[.2em] text-muted-foreground/70 lg:flex">
            <span className="h-px w-12 bg-border" /> pastga aylantiring
          </div>
        </section>

        <section id="muammo" className="scroll-mt-20 bg-background px-5 py-24 sm:px-8 lg:px-10 lg:py-32">
          <div className="mx-auto grid max-w-[1240px] gap-14 lg:grid-cols-[.88fr_1.12fr] lg:gap-24">
            <div>
              <SectionLabel>Muammo</SectionLabel>
              <h2 className="max-w-[520px] font-display text-4xl font-extrabold leading-[1.03] tracking-[-.06em] sm:text-6xl">
                Nomzod yetishmayapti emas. <span className="text-primary">Saralashga vaqt yetmayapti.</span>
              </h2>
              <p className="mt-6 max-w-[420px] text-base leading-7 text-muted-foreground">
                Ariza ko'p keladi, lekin har birini o'qib, savol berib, javobini tekshirish — kuniga bir necha soat.
              </p>
            </div>
            <div className="divide-y divide-border border-y border-border">
              {[
                ['01', 'Har bir arizani qo‘lda o‘qish', 'Kim mos, kim mos emas — buni bilish uchun har birini boshidan oxirigacha o‘qish kerak bo‘ladi.'],
                ['02', 'Ishga olib, keyin pushaymon bo‘lish', 'Suhbatda yaxshi taassurot qoldirgan odam ishda boshqacha chiqishi — tez-tez uchraydigan holat.'],
                ['03', 'Noto‘g‘ri tanlovning narxi', 'Xato tanlov — yana bir oy e’lon, yana bir oy suhbat, yana bir oy sinov muddati.'],
              ].map(([number, title, text]) => (
                <div className="flex gap-5 py-6 sm:py-7" key={number}>
                  <span className="font-mono text-sm font-bold text-primary">{number}</span>
                  <div>
                    <h3 className="font-display text-xl font-extrabold tracking-[-.03em]">{title}</h3>
                    <p className="mt-2 max-w-[500px] text-sm leading-6 text-muted-foreground">{text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="qanday-ishlaydi" className="scroll-mt-20 bg-background px-5 py-24 sm:px-8 lg:px-10 lg:py-32">
          <div className="mx-auto max-w-[1240px]">
            <div className="grid gap-12 lg:grid-cols-[.72fr_1.28fr] lg:gap-24">
              <div>
                <SectionLabel>Jarayon</SectionLabel>
                <h2 className="max-w-[440px] font-display text-4xl font-extrabold leading-[1.03] tracking-[-.06em] sm:text-5xl">
                  Arzimagan 3 ta qadam. <span className="text-primary">Ortiqcha muammolarsiz.</span>
                </h2>
                <p className="mt-6 max-w-[360px] text-base leading-7 text-muted-foreground">
                  Nomzod qayerdan kelishidan qat’i nazar (e’lon, QR-kod yoki havola orqali) — hammasi shu 3 qadamdan o‘tadi.
                </p>
                <a href="https://t.me/janobHR_bot" target="_blank" rel="noreferrer" className="focus-ring mt-8 inline-flex items-center gap-2 text-sm font-bold text-primary" data-testid="link-process-contact">
                  Botni sinab ko‘ring <ArrowUpRight size={16} />
                </a>
              </div>
              <div className="grid gap-x-8 gap-y-12 sm:grid-cols-3">
                <WorkflowStep number="01" icon={Clipboard} title="Vakansiya yaratasiz">
                  Lavozim nomini yozasiz — AI mos savollarni (filtr, ovozli, tahlil) o‘zi tuzadi.
                </WorkflowStep>
                <WorkflowStep number="02" icon={Search} title="Nomzod o‘zi topshiradi">
                  Havola yoki QR-kod orqali botga kirib, savollarga javob beradi.
                </WorkflowStep>
                <WorkflowStep number="03" icon={FileCheck2} title="Siz esa tanlaysiz">
                  AI saralab bergan ro‘yxatdan kimni suhbatga chaqirishni bosasiz.
                </WorkflowStep>
              </div>
            </div>
          </div>
        </section>

        <section id="imkoniyatlar" className="scroll-mt-20 border-y border-border bg-[#e3edfa] px-5 py-24 sm:px-8 lg:px-10 lg:py-32">
          <div className="mx-auto max-w-[1240px]">
            <div className="flex flex-col justify-between gap-8 lg:flex-row lg:items-end">
              <div>
                <SectionLabel>Botda nima bor</SectionLabel>
                <h2 className="max-w-[630px] font-display text-4xl font-extrabold leading-[1.02] tracking-[-.06em] sm:text-6xl">
                  Ishga olishni osonlashtiradigan <span className="text-primary">7 ta funksiya.</span>
                </h2>
              </div>
            </div>
            <div className="mt-14 grid gap-4 lg:grid-cols-12">
              <FeatureCard icon={Search} eyebrow="01 / Saralash" title="AI savollarni o‘zi tuzib beradi" className="lg:col-span-5 lg:min-h-[330px]">
                Lavozim nomini yozasiz — JanobHR filtr, chuqur tahlil va ovozli savollarni avtomatik tuzadi. Xohlasangiz, o‘zingiz ham qo‘lda yozishingiz mumkin.
              </FeatureCard>
              <FeatureCard icon={Mic} eyebrow="02 / Ovozli javob" title="Sizni endi alday olishmaydi" className="lg:col-span-4 lg:min-h-[330px]">
                Muhim savolga nomzod OVOZLI xabar bilan javob beradi. Tayyorlab, sun’iy intellekt bilan yozib olingan javob emas — jonli, tabiiy javob.
              </FeatureCard>
              <FeatureCard icon={ShieldCheck} eyebrow="03 / Filtr" title="To‘g‘ri kelmagan nomzod vaqtingizni olmaydi" className="lg:col-span-3 lg:min-h-[330px]">
                Talabga javob bermagan nomzod suhbatgacha yetib bormaydi. Vaqtingiz faqat haqiqiy nomzodlarga sarflanadi.
              </FeatureCard>
              <div className="relative overflow-hidden rounded-[22px] bg-primary p-7 text-primary-foreground lg:col-span-7">
                <div className="absolute -right-8 -top-12 h-44 w-44 rounded-full border-[22px] border-secondary/25" />
                <div className="absolute -bottom-16 right-20 h-48 w-48 rounded-full border border-secondary/20" />
                <p className="relative inline-block rounded-full bg-primary-foreground/12 px-3 py-1 font-mono text-xs font-bold uppercase tracking-[.14em] text-secondary">04 / E’lon qilish</p>
                <h3 className="relative mt-10 max-w-[510px] font-display text-2xl font-extrabold leading-tight tracking-[-.04em] sm:text-3xl">
                  Har bir vakansiya uchun tayyor havola va QR-kod. HH.uz, Instagram yoki bosma e’lonlarga muammosiz joylay olasiz.
                </h3>
                <div className="relative mt-9 flex items-center gap-2 text-sm font-semibold text-primary-foreground/75">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary/25"><QrCode size={15} /></span>
                  Skanerlagan kishi to‘g‘ridan-to‘g‘ri shu vakansiyaga ariza topshiradi
                </div>
              </div>
              <FeatureCard icon={CalendarClock} eyebrow="05 / Suhbat" title="Moslashuvchan vaqt" className="lg:col-span-5">
                Qabul qilingan nomzod bo‘sh suhbat vaqtlaridan birini o‘zi tanlaydi. Manzil va eslatma avtomatik yuboriladi.
              </FeatureCard>
              <FeatureCard icon={FileCheck2} eyebrow="06 / Rezyume" title="CV’dan avtomatik to‘ldiradi" className="lg:col-span-6">
                Nomzod rezyume yuklasa, oddiy faktik savollarga javob avtomatik topiladi — qayta so‘ralmaydi.
              </FeatureCard>
              <FeatureCard icon={Clock3} eyebrow="07 / Vaqt" title="HR vaqtini tejaydi" className="lg:col-span-6">
                Takroriy screeningga ketadigan energiya kamayadi. Jamoangiz esa suhbat va tanlovning o‘ziga e’tibor beradi.
              </FeatureCard>
            </div>
          </div>
        </section>

        <section id="kimlar-uchun" className="scroll-mt-20 bg-background px-5 py-24 sm:px-8 lg:px-10 lg:py-32">
          <div className="mx-auto max-w-[1240px]">
            <div className="grid gap-14 lg:grid-cols-[.8fr_1.2fr] lg:gap-24">
              <div>
                <SectionLabel>Kimlar uchun</SectionLabel>
                <h2 className="max-w-[430px] font-display text-4xl font-extrabold leading-[1.03] tracking-[-.06em] sm:text-5xl">
                  Xodim aylanmasi tez bo‘lgan bizneslar uchun.
                </h2>
              </div>
              <div className="divide-y divide-border border-y border-border">
                {[
                  ['Ko‘p filialli chakana savdo', 'Har oy bir necha filialga sotuvchi kerak bo‘lsa, har birini qo‘lda intervyu qilishga vaqt yetmaydi.'],
                  ['Yetkazib berish xizmatlari', 'Kuryer va haydovchilar tez-tez almashadi — bot doim ishlab, siz uchun saralab turadi.'],
                  ['Call-markaz va restoran tarmoqlari', 'Doimiy ochiq vakansiya bor joyda, arizalarni qo‘lda ko‘rib chiqish HRni charchatadi.'],
                ].map(([title, text], index) => (
                  <div className="group flex items-start justify-between gap-6 py-6 sm:py-7" key={title}>
                    <div className="flex gap-5">
                      <span className="font-mono text-[10px] font-bold text-accent">0{index + 1}</span>
                      <div>
                        <h3 className="font-display text-xl font-extrabold tracking-[-.03em]">{title}</h3>
                        <p className="mt-2 max-w-[430px] text-sm leading-6 text-muted-foreground">{text}</p>
                      </div>
                    </div>
                    <ArrowUpRight size={19} className="mt-1 shrink-0 text-primary opacity-35 transition-[transform,opacity] group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:opacity-100" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="relative overflow-hidden bg-[#cfe1f7] px-5 py-24 sm:px-8 lg:px-10 lg:py-32">
          <div className="absolute -right-16 top-[-100px] h-[440px] w-[440px] rounded-full border border-primary/10" />
          <div className="absolute -right-4 top-[-42px] h-[325px] w-[325px] rounded-full border border-primary/10" />
          <div className="relative mx-auto grid max-w-[1240px] gap-12 lg:grid-cols-[1fr_1fr] lg:items-center lg:gap-24">
            <div>
              <SectionLabel>Yondashuv</SectionLabel>
              <h2 className="max-w-[560px] font-display text-4xl font-extrabold leading-[1.03] tracking-[-.06em] sm:text-6xl">
                AI tanlab bermaydi.<br /><span className="text-primary">Siz tanlaysiz.</span>
              </h2>
            </div>
            <div className="max-w-[470px]">
              <p className="text-lg leading-8 text-foreground/75">
                Bot hech kimni ishga olmaydi va hech kimni butunlay rad etmaydi (faqat aniq talabga javob bermaganlarni). U faqat saralaydi — "Suhbatga chaqirish" yoki "Rad etish" tugmasini bosish sizning qo‘lingizda.
              </p>
            </div>
          </div>
        </section>

        <section id="tariflar" className="scroll-mt-20 bg-background px-5 py-24 sm:px-8 lg:px-10 lg:py-32">
          <div className="mx-auto max-w-[1240px]">
            <div className="flex flex-col justify-between gap-8 lg:flex-row lg:items-end">
              <div>
                <SectionLabel>Tariflar</SectionLabel>
                <h2 className="max-w-[560px] font-display text-4xl font-extrabold leading-[1.02] tracking-[-.06em] sm:text-6xl">
                  Avval sinab ko‘ring. <span className="text-primary">Keyin tanlang.</span>
                </h2>
              </div>
              <p className="max-w-[320px] text-sm leading-6 text-muted-foreground lg:pb-1">
                Bot yaratganingizda birinchi 5 ta ariza butunlay bepul — barcha funksiya ochiq holda sinab ko‘rasiz.
              </p>
            </div>
            <div className="mt-14 grid gap-5 lg:grid-cols-3">
              {[
                {
                  name: 'START', price: '199 000', badge: null,
                  items: ['30 ta nomzod', '1 ta vakansiya', '30 kun amal qiladi', 'AI baholash, filtr, Excel eksport'],
                },
                {
                  name: 'BUSINESS', price: '449 000', badge: 'Eng ko‘p tanlanadi',
                  items: ['100 ta nomzod', '3 ta vakansiya', '60 kun amal qiladi', 'Majburiy ovozli savol', 'Suhbat rejasi', 'Rezyumedan avtomatik to‘ldirish', 'Kengaytirilgan statistika'],
                },
                {
                  name: 'PRO', price: '999 000', badge: null,
                  items: ['300 ta nomzod', '10 ta vakansiya', '90 kun amal qiladi', 'BUSINESS’dagi barchasi', 'Bir nechta admin (jamoa)', 'Ustuvor qo‘llab-quvvatlash'],
                },
              ].map((plan) => (
                <div
                  key={plan.name}
                  className={`relative rounded-[22px] border p-7 sm:p-8 ${plan.badge ? 'border-primary bg-primary text-primary-foreground shadow-[0_20px_50px_hsl(var(--primary)/.22)] lg:-translate-y-3' : 'border-border bg-card'}`}
                >
                  {plan.badge && (
                    <span className="absolute -top-3 left-7 rounded-full bg-accent px-3 py-1 font-mono text-[9px] font-bold uppercase tracking-[.14em] text-accent-foreground">
                      {plan.badge}
                    </span>
                  )}
                  <p className={`inline-block rounded-full px-3 py-1 font-mono text-xs font-bold uppercase tracking-[.14em] ${plan.badge ? 'bg-primary-foreground/12 text-secondary' : 'bg-primary/10 text-primary'}`}>{plan.name}</p>
                  <p className="mt-4 font-display text-3xl font-extrabold tracking-[-.03em]">
                    {plan.price} <span className="text-base font-semibold opacity-60">so‘m</span>
                  </p>
                  <ul className="mt-6 space-y-3 text-sm leading-6">
                    {plan.items.map((item) => (
                      <li key={item} className="flex items-start gap-2.5">
                        <Check size={15} className={`mt-1 shrink-0 ${plan.badge ? 'text-secondary' : 'text-primary'}`} />
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="faq" className="scroll-mt-20 bg-background px-5 py-24 sm:px-8 lg:px-10 lg:py-32">
          <div className="mx-auto grid max-w-[1240px] gap-12 lg:grid-cols-[.72fr_1.28fr] lg:gap-24">
            <div>
              <SectionLabel>FAQ</SectionLabel>
              <h2 className="max-w-[420px] font-display text-4xl font-extrabold leading-[1.03] tracking-[-.06em] sm:text-5xl">
                Ko‘p so‘raladigan savollar.
              </h2>
            </div>
            <div className="divide-y divide-border border-y border-border">
              {[
                ['JanobHR qayerda ishlaydi?', 'JanobHR Telegram ichida ishlaydi. Har bir mijozga IKKITA bot beriladi: nomzodlar ariza topshiradigan bot va sizning o‘z Admin panelingiz.'],
                ['AI yakuniy qarorni o‘zi qabul qiladimi?', 'Yo‘q. JanobHR nomzodlarni bir xil mezonlar asosida tahlil qiladi va saralaydi, yakuniy "Suhbatga chaqirish" yoki "Rad etish" qarorini esa siz Admin panelda bosasiz.'],
                ['Ovozli javob nima uchun kerak?', 'Muhim savolga nomzod OVOZLI xabar bilan javob berishi shart bo‘lishi mumkin — audio to‘g‘ridan-to‘g‘ri sizga yuboriladi. Bu ChatGPT yordamida tayyorlab yozilgan javoblardan himoya qiladi.'],
                ['Sinov qanday ishlaydi?', 'Bot yaratganingizda birinchi 5 ta ariza butunlay bepul — barcha funksiya (ovozli savol, suhbat rejasi, statistika) ochiq holda sinab ko‘rasiz. Keyin sizga mos tarifni tanlaysiz.'],
                ['Har bir lavozim uchun alohida savol bo‘ladimi?', 'Ha. Lavozim nomini yozsangiz, JanobHR shu lavozimga mos savollarni (filtr, chuqur tahlil, ovozli) avtomatik tuzadi — yoki xohlasangiz o‘zingiz yozasiz.'],
              ].map(([question, answer]) => (
                <details className="group py-5" key={question}>
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-6 font-display text-lg font-extrabold tracking-[-.025em]">
                    {question}
                    <ChevronDown size={19} className="shrink-0 text-primary transition-transform group-open:rotate-180" />
                  </summary>
                  <p className="max-w-[650px] pt-3 text-sm leading-6 text-muted-foreground">{answer}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section id="boglanish" className="scroll-mt-20 bg-primary px-5 py-24 text-primary-foreground sm:px-8 lg:px-10 lg:py-32">
          <div className="mx-auto grid max-w-[1240px] gap-14 lg:grid-cols-[1.05fr_.95fr] lg:items-end lg:gap-24">
            <div>
              <SectionLabel light>Boshlash vaqti</SectionLabel>
              <h2 className="max-w-[700px] font-display text-5xl font-extrabold leading-[.98] tracking-[-.07em] sm:text-7xl">
                Yaxshi nomzodlar kutib turmaydi.
              </h2>
              <p className="mt-7 max-w-[500px] text-base leading-7 text-primary-foreground/70 sm:text-lg">
                Bepul sinov uchun botga /start yozing — birinchi 5 ta ariza sizga BUTUNLAY BEPUL.
              </p>
            </div>
            <div className="rounded-[23px] border border-primary-foreground/15 bg-primary-foreground/[.07] p-6 sm:p-8">
              <p className="font-mono text-[9px] uppercase tracking-[.17em] text-secondary">Telegram’da boshlang</p>
              <a href="https://t.me/janobHR_bot" target="_blank" rel="noreferrer" className="focus-ring mt-5 flex items-center justify-between" data-testid="link-contact-telegram">
                <span className="flex items-center gap-3"><TelegramGlyph size={19} /><span><span className="block text-xs text-primary-foreground/55">Telegram bot</span><span className="mt-0.5 block text-lg font-bold">@janobHR_bot</span></span></span>
                <ArrowUpRight size={19} />
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="bg-[#0d1e30] px-5 py-10 text-primary-foreground/75 sm:px-8 lg:px-10">
        <div className="mx-auto max-w-[1240px]">
          <div className="flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
            <div className="max-w-[280px]">
              <BrandMark compact />
              <p className="mt-3 text-sm text-primary-foreground/50">Telegram orqali ishlaydigan HR bot.</p>
            </div>
            <div className="flex flex-wrap items-center gap-x-7 gap-y-3 text-sm font-semibold">
              <a href="#bosh-sahifa" className="focus-ring hover:text-secondary" data-testid="link-footer-home">Bosh sahifa</a>
              <a href="#qanday-ishlaydi" className="focus-ring hover:text-secondary" data-testid="link-footer-process">Qanday ishlaydi</a>
              <a href="https://t.me/janobHR_bot" target="_blank" rel="noreferrer" className="focus-ring inline-flex items-center gap-2 hover:text-secondary" data-testid="link-footer-telegram"><TelegramGlyph size={15} /> @janobHR_bot</a>
            </div>
          </div>
          <div className="mt-9 border-t border-primary-foreground/10 pt-6">
            <span className="font-mono text-[10px] uppercase tracking-[.15em] text-primary-foreground/40">© 2026 JanobHR</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

function Router() {
  return (
    <RoutedErrorBoundary>
      <Home />
    </RoutedErrorBoundary>
  );
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
          <Router />
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;