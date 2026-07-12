import { useAuth } from "@/context/AuthContext";
import { useNavigate, useLocation } from "react-router-dom";
import { useState, useEffect } from "react";
import { useTranslation, Trans } from "react-i18next";
import { toast } from "sonner";
import { ArrowUpRight, ShieldCheck, Globe2, Zap, Activity, Boxes, BadgeCheck, ChevronRight, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import EmailAuthDialog from "@/components/EmailAuthDialog";
import { useScrollParallax } from "@/hooks/useScrollParallax";
import { CompactLanguageSwitcher } from "@/components/CompactLanguageSwitcher";

export default function Landing() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const [emailAuthOpen, setEmailAuthOpen] = useState(false);
  const [prefillEmail, setPrefillEmail] = useState("");
  const scrollY = useScrollParallax();

  // Handle "?verified=1&email=..." from the verify-email flow:
  // show a success toast and auto-open the login dialog with the email pre-filled.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("verified") === "1") {
      const email = params.get("email") || "";
      setPrefillEmail(email);
      setEmailAuthOpen(true);
      toast.success("¡Correo verificado! Inicia sesión para continuar.", { duration: 5000 });
      // Clean URL so a refresh doesn't re-trigger the toast/dialog.
      navigate("/", { replace: true });
    }
  }, [location.search, navigate]);

  const handleEnter = () => {
    if (user) navigate(user.role === "admin" || user.role === "employee" ? "/admin" : "/dashboard");
    else login();
  };

  const handleEmailAuth = () => {
    if (user) navigate(user.role === "admin" || user.role === "employee" ? "/admin" : "/dashboard");
    else { setPrefillEmail(""); setEmailAuthOpen(true); }
  };

  return (
    <div className="min-h-screen bg-[#14101F] text-white">
      {/* HEADER */}
      <header className="sticky top-0 inset-x-0 z-50 glass-panel">
        <div className="max-w-7xl mx-auto px-6 lg:px-12 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-12 w-12 object-contain" />
            <div>
              <div className="font-display text-sm leading-none">RESILIENCE</div>
              <div className="micro-label text-neutral-500 text-[0.6rem]">Brothers · P2P</div>
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-8 micro-label text-neutral-400">
            <a href="#about" className="hover:text-white transition-colors">{t("landing.nav.about")}</a>
            <a href="#services" className="hover:text-white transition-colors">{t("landing.nav.services")}</a>
            <a href="#how" className="hover:text-white transition-colors">{t("landing.nav.how")}</a>
            <a href="#vip" className="hover:text-white transition-colors">{t("landing.nav.vip")}</a>
          </nav>
          <div className="flex items-center gap-3">
            <CompactLanguageSwitcher testid="landing-lang-switcher" />
            <Button
              data-testid="header-login-btn"
              onClick={user ? handleEnter : handleEmailAuth}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none px-5 h-10"
            >
              {user ? t("landing.header.enterPanel") : t("landing.header.loginButton")} <ArrowUpRight className="w-4 h-4 ml-1" />
            </Button>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="relative pt-32 pb-24 overflow-hidden">
        <div
          className="absolute inset-0 bg-cover bg-center opacity-55 will-change-transform"
          style={{
            backgroundImage: "url(https://images.unsplash.com/photo-1644088379091-d574269d422f?crop=entropy&cs=srgb&fm=jpg&q=85)",
            transform: `translate3d(0, ${scrollY * 0.35}px, 0)`,
          }}
        ></div>
        <div className="absolute inset-0 bg-gradient-to-b from-[#14101F]/20 via-[#14101F]/55 to-[#14101F]"></div>
        <div className="relative max-w-7xl mx-auto px-6 lg:px-12 grid lg:grid-cols-12 gap-8 items-end">
          <div className="lg:col-span-8 fade-up">
            <div className="flex items-center gap-3 mb-6">
              <span className="w-2 h-2 bg-[#22C55E] rounded-full pulse-dot"></span>
              <span className="micro-label text-neutral-400">{t("landing.hero.livePill")}</span>
            </div>
            <h1 className="font-display text-4xl sm:text-5xl lg:text-7xl leading-[0.95] mb-6">
              {t("landing.hero.titleLine1")}<br />
              <span className="text-[#8B5CF6]">{t("landing.hero.titleAccent")}</span><br />
              {t("landing.hero.titleLine3")}
            </h1>
            <p className="text-neutral-300 text-base md:text-lg max-w-2xl leading-relaxed mb-8">
              {t("landing.hero.descriptionA")}
              <span className="text-white"> {t("landing.hero.descriptionHighlight")} </span>
              {t("landing.hero.descriptionB")}
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <Button
                data-testid="hero-start-btn"
                onClick={handleEnter}
                className="inline-flex items-center justify-center bg-violet-600 hover:bg-violet-500 text-white font-medium text-base py-3 px-8 h-14 rounded-full transition-all duration-300 shadow-[0_4px_14px_0_rgba(139,92,246,0.39)] hover:shadow-[0_6px_20px_rgba(139,92,246,0.5)] hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#14101F]"
              >
                {t("landing.hero.startButton")} <ChevronRight className="w-5 h-5 ml-1" />
              </Button>
              <Button
                data-testid="hero-email-btn"
                onClick={handleEmailAuth}
                variant="ghost"
                className="inline-flex items-center justify-center bg-transparent border border-white/15 hover:border-white/30 hover:bg-white/5 text-white font-medium text-sm py-3 px-8 h-14 rounded-full transition-all duration-300 hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:ring-offset-2 focus-visible:ring-offset-[#14101F]"
              >
                <Mail className="w-4 h-4 mr-2" /> {t("landing.hero.emailButton")}
              </Button>
            </div>
            <p className="text-[0.7rem] text-neutral-500 mt-3 max-w-md">
              <Trans
                i18nKey="landing.hero.emailFallback"
                components={[
                  <button key="email-fallback-link" onClick={handleEmailAuth} className="text-[#8B5CF6] hover:underline" data-testid="hero-email-link" />,
                ]}
              />
            </p>
          </div>
          <div className="lg:col-span-4 grid grid-cols-2 gap-4 mt-8 lg:mt-0">
            {[
              { v: "+12", l: t("landing.hero.kpiCountries") },
              { v: "VIP", l: t("landing.hero.kpiVipRate") },
              { v: "24h", l: t("landing.hero.kpiSettlement") },
              { v: "100%", l: t("landing.hero.kpiP2p") },
            ].map((s) => (
              <div key={s.l} className="tactile-card p-4">
                <div className="font-display text-2xl text-[#8B5CF6]">{s.v}</div>
                <div className="micro-label text-neutral-500 mt-2">{s.l}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ABOUT — TETRIS GRID */}
      <section id="about" className="py-20 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-6 lg:px-12">
          <div className="flex items-start justify-between mb-12 flex-wrap gap-4">
            <div>
              <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.about.eyebrow")}</div>
              <h2 className="font-display text-3xl lg:text-5xl max-w-2xl">{t("landing.about.title")}</h2>
            </div>
            <p className="text-neutral-400 max-w-md text-sm md:text-base leading-relaxed">
              {t("landing.about.description")}
            </p>
          </div>
          <div className="grid grid-cols-12 gap-4">
            <div className="col-span-12 lg:col-span-7 tactile-card p-8 relative overflow-hidden min-h-[280px] grain-overlay">
              <Globe2 className="w-10 h-10 text-[#8B5CF6] mb-6" />
              <h3 className="font-display text-2xl mb-3">{t("landing.about.globalTitle")}</h3>
              <p className="text-neutral-400 max-w-md">
                {t("landing.about.globalDescription")}
              </p>
            </div>
            <div className="col-span-6 lg:col-span-5 tactile-card p-6 min-h-[280px] flex flex-col justify-between">
              <ShieldCheck className="w-10 h-10 text-[#8B5CF6]" />
              <div>
                <h3 className="font-display text-xl mb-2">{t("landing.about.proofsTitle")}</h3>
                <p className="text-neutral-400 text-sm">{t("landing.about.proofsDescription")}</p>
              </div>
            </div>
            <div className="col-span-6 lg:col-span-4 tactile-card p-6 min-h-[220px]">
              <Zap className="w-9 h-9 text-[#8B5CF6] mb-4" />
              <h3 className="font-display text-xl mb-2">{t("landing.about.settlementTitle")}</h3>
              <p className="text-neutral-400 text-sm">{t("landing.about.settlementDescription")}</p>
            </div>
            <div className="col-span-12 lg:col-span-4 tactile-card p-6 min-h-[220px]">
              <Activity className="w-9 h-9 text-[#8B5CF6] mb-4" />
              <h3 className="font-display text-xl mb-2">{t("landing.about.dynamicRatesTitle")}</h3>
              <p className="text-neutral-400 text-sm">{t("landing.about.dynamicRatesDescription")}</p>
            </div>
            <div className="col-span-12 lg:col-span-4 tactile-card p-6 min-h-[220px]">
              <Boxes className="w-9 h-9 text-[#8B5CF6] mb-4" />
              <h3 className="font-display text-xl mb-2">{t("landing.about.goodsTitle")}</h3>
              <p className="text-neutral-400 text-sm">{t("landing.about.goodsDescription")}</p>
            </div>
          </div>
        </div>
      </section>

      {/* SERVICES */}
      <section id="services" className="py-20 border-t border-white/5 bg-[#0c0c0c]">
        <div className="max-w-7xl mx-auto px-6 lg:px-12">
          <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.services.eyebrow")}</div>
          <h2 className="font-display text-3xl lg:text-5xl mb-12 max-w-3xl">{t("landing.services.title")}</h2>
          <div className="grid lg:grid-cols-2 gap-6">
            <div className="tactile-card p-8 hover:glow-yellow transition-shadow">
              <div className="flex items-center justify-between mb-6">
                <span className="micro-label text-neutral-500">{t("landing.services.section01")}</span>
                <span className="text-xs font-mono text-[#22C55E]">{t("landing.services.active")}</span>
              </div>
              <h3 className="font-display text-3xl mb-4">{t("landing.services.cryptoTitle")}</h3>
              <p className="text-neutral-400 mb-6">{t("landing.services.cryptoDescription")}</p>
              <ul className="space-y-3 text-sm">
                {(t("landing.services.cryptoBullets", { returnObjects: true }) || []).map((b) => (
                  <li key={b} className="flex items-center gap-3 text-neutral-300">
                    <BadgeCheck className="w-4 h-4 text-[#8B5CF6] shrink-0" />
                    {b}
                  </li>
                ))}
              </ul>
            </div>
            <div className="tactile-card p-8 hover:glow-yellow transition-shadow relative overflow-hidden">
              <div
                className="absolute inset-0 bg-cover bg-center opacity-20 will-change-transform"
                style={{
                  backgroundImage: "url(https://images.unsplash.com/photo-1493946740644-2d8a1f1a6aff?crop=entropy&cs=srgb&fm=jpg&q=85)",
                  transform: `translate3d(0, ${scrollY * 0.08}px, 0)`,
                }}
              ></div>
              <div className="relative">
                <div className="flex items-center justify-between mb-6">
                  <span className="micro-label text-neutral-500">{t("landing.services.section02")}</span>
                  <span className="text-xs font-mono text-[#8B5CF6]">{t("landing.services.vipOnly")}</span>
                </div>
                <h3 className="font-display text-3xl mb-4">{t("landing.services.marketplaceTitle")}</h3>
                <p className="text-neutral-400 mb-6">{t("landing.services.marketplaceDescription")}</p>
                <ul className="space-y-3 text-sm">
                  {(t("landing.services.marketplaceBullets", { returnObjects: true }) || []).map((b) => (
                    <li key={b} className="flex items-center gap-3 text-neutral-300">
                      <BadgeCheck className="w-4 h-4 text-[#8B5CF6] shrink-0" />
                      {b}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="py-20 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-6 lg:px-12">
          <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.how.eyebrow")}</div>
          <h2 className="font-display text-3xl lg:text-5xl mb-12 max-w-3xl">{t("landing.how.title")}</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
            {(t("landing.how.steps", { returnObjects: true }) || []).map((s) => (
              <div key={s.n} className="tactile-card p-6">
                <div className="font-display text-5xl text-[#8B5CF6]/30">{s.n}</div>
                <h3 className="font-display text-lg mt-4 mb-2">{s.t}</h3>
                <p className="text-neutral-400 text-sm">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* VIP */}
      <section id="vip" className="py-20 border-t border-white/5 bg-[#0c0c0c]">
        <div className="max-w-7xl mx-auto px-6 lg:px-12 grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <div className="micro-label text-[#8B5CF6] mb-3">{t("landing.vipSection.eyebrow")}</div>
            <h2 className="font-display text-3xl lg:text-5xl mb-6">{t("landing.vipSection.title")}</h2>
            <p className="text-neutral-400 mb-8 text-base leading-relaxed">
              {t("landing.vipSection.descriptionA")}{" "}
              <span className="text-white">{t("landing.vipSection.descriptionHighlight")}</span>{" "}
              {t("landing.vipSection.descriptionB")}
            </p>
            <div className="grid grid-cols-2 gap-3">
              {[
                ["0%", t("landing.vipSection.kpiCommission")],
                ["+5", t("landing.vipSection.kpiRate")],
                [t("landing.vipSection.kpiCourierValue"), t("landing.vipSection.kpiCourier")],
                [t("landing.vipSection.kpiAccumulateValue"), t("landing.vipSection.kpiAccumulate")],
              ].map(([v, l]) => (
                <div key={l} className="border border-white/10 p-4">
                  <div className="font-display text-2xl text-[#8B5CF6]">{v}</div>
                  <div className="micro-label text-neutral-500 mt-1">{l}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="relative">
            <div className="aspect-square bg-black flex items-center justify-center border border-[#8B5CF6]/20 overflow-hidden">
              <img
                src="/branding/logo-1200.png"
                alt="Resilience Brothers"
                className="w-4/5 h-4/5 object-contain"
              />
            </div>
            <div className="absolute bottom-0 left-0 right-0 p-6 glass-panel">
              <div className="micro-label text-[#8B5CF6] mb-2">{t("landing.vipSection.statusLabel")}</div>
              <p className="font-display text-xl">{t("landing.vipSection.statusTagline")}</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 border-t border-white/5">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <h2 className="font-display text-4xl lg:text-6xl mb-6">
            {t("landing.cta.title")}
          </h2>
          <p className="text-neutral-400 mb-8 text-lg">{t("landing.cta.subtitle")}</p>
          <Button
            data-testid="cta-signup-btn"
            onClick={handleEnter}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none px-10 h-14 text-base"
          >
            {t("landing.cta.googleButton")} <ArrowUpRight className="w-5 h-5 ml-1" />
          </Button>
          <div className="mt-4">
            <button
              data-testid="cta-email-link"
              onClick={handleEmailAuth}
              className="text-sm text-neutral-400 hover:text-[#8B5CF6] underline underline-offset-4"
            >
              {t("landing.cta.emailLink")}
            </button>
          </div>
        </div>
      </section>

      <footer className="border-t border-white/5 py-8">
        <div className="max-w-7xl mx-auto px-6 lg:px-12 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <img src="/branding/logo-300.png" alt="Resilience Brothers" className="h-9 w-9 object-contain" />
            <span className="micro-label text-neutral-500">{t("landing.footer.copy")}</span>
          </div>
          <span className="micro-label text-neutral-600">{t("landing.footer.tagline")}</span>
        </div>
      </footer>

      <EmailAuthDialog open={emailAuthOpen} onClose={() => setEmailAuthOpen(false)} initialEmail={prefillEmail} />
    </div>
  );
}
