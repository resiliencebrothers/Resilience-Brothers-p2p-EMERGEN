import { useAuth } from "@/context/AuthContext";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, ShieldCheck, Globe2, Zap, Activity, Boxes, BadgeCheck, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function Landing() {
  const { user, login } = useAuth();
  const navigate = useNavigate();

  const handleEnter = () => {
    if (user) navigate(user.role === "admin" ? "/admin" : "/dashboard");
    else login();
  };

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      {/* HEADER */}
      <header className="fixed top-0 inset-x-0 z-50 glass-panel">
        <div className="max-w-7xl mx-auto px-6 lg:px-12 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-[#EAB308] flex items-center justify-center font-display text-black text-lg">RB</div>
            <div>
              <div className="font-display text-sm leading-none">RESILIENCE</div>
              <div className="micro-label text-neutral-500 text-[0.6rem]">Brothers · P2P</div>
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-8 micro-label text-neutral-400">
            <a href="#about" className="hover:text-white transition-colors">Nosotros</a>
            <a href="#services" className="hover:text-white transition-colors">Servicios</a>
            <a href="#how" className="hover:text-white transition-colors">Cómo Funciona</a>
            <a href="#vip" className="hover:text-white transition-colors">VIP</a>
          </nav>
          <Button
            data-testid="header-login-btn"
            onClick={handleEnter}
            className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-semibold rounded-none px-5 h-10"
          >
            {user ? "Entrar al Panel" : "Iniciar Sesión"} <ArrowUpRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </header>

      {/* HERO */}
      <section className="relative pt-32 pb-24 overflow-hidden">
        <div
          className="absolute inset-0 bg-cover bg-center opacity-30"
          style={{ backgroundImage: "url(https://images.unsplash.com/photo-1644088379091-d574269d422f?crop=entropy&cs=srgb&fm=jpg&q=85)" }}
        ></div>
        <div className="absolute inset-0 bg-gradient-to-b from-[#0A0A0A]/40 via-[#0A0A0A]/70 to-[#0A0A0A]"></div>
        <div className="relative max-w-7xl mx-auto px-6 lg:px-12 grid lg:grid-cols-12 gap-8 items-end">
          <div className="lg:col-span-8 fade-up">
            <div className="flex items-center gap-3 mb-6">
              <span className="w-2 h-2 bg-[#22C55E] rounded-full pulse-dot"></span>
              <span className="micro-label text-neutral-400">Live Network · 24/7 Settlement</span>
            </div>
            <h1 className="font-display text-4xl sm:text-5xl lg:text-7xl leading-[0.95] mb-6">
              Comercio P2P<br />
              <span className="text-[#EAB308]">sin fronteras.</span><br />
              Sin fricción.
            </h1>
            <p className="text-neutral-300 text-base md:text-lg max-w-2xl leading-relaxed mb-8">
              Resilience Brothers conecta empresas y clientes mediante una plataforma global de comercio P2P. Intercambia
              activos digitales, bienes, productos y servicios con herramientas financieras integradas para operaciones
              <span className="text-white"> más rápidas, seguras y eficientes </span> a escala internacional.
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <Button
                data-testid="hero-start-btn"
                onClick={handleEnter}
                className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none px-8 h-14 text-base"
              >
                Comenzar a Operar <ChevronRight className="w-5 h-5 ml-1" />
              </Button>
              <a
                href="#services"
                className="border border-white/20 hover:border-white text-white px-8 h-14 inline-flex items-center text-sm font-semibold tracking-wide transition-colors"
              >
                EXPLORAR SERVICIOS
              </a>
            </div>
          </div>
          <div className="lg:col-span-4 grid grid-cols-2 gap-4 mt-8 lg:mt-0">
            {[
              { v: "+12", l: "Países" },
              { v: "5%→0%", l: "Comisión VIP" },
              { v: "24h", l: "Settlement" },
              { v: "100%", l: "P2P" },
            ].map((s, i) => (
              <div key={i} className="tactile-card p-4">
                <div className="font-display text-2xl text-[#EAB308]">{s.v}</div>
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
              <div className="micro-label text-[#EAB308] mb-3">/ 01 — Quiénes Somos</div>
              <h2 className="font-display text-3xl lg:text-5xl max-w-2xl">Un puente operativo entre mercados.</h2>
            </div>
            <p className="text-neutral-400 max-w-md text-sm md:text-base leading-relaxed">
              Operamos como infraestructura financiera para clientes que necesitan mover valor entre criptomonedas, divisas
              y mercancías sin pasar por bancos lentos ni tarifas opacas.
            </p>
          </div>
          <div className="grid grid-cols-12 gap-4">
            <div className="col-span-12 lg:col-span-7 tactile-card p-8 relative overflow-hidden min-h-[280px] grain-overlay">
              <Globe2 className="w-10 h-10 text-[#EAB308] mb-6" />
              <h3 className="font-display text-2xl mb-3">Alcance Global</h3>
              <p className="text-neutral-400 max-w-md">
                Cuba, Brasil, México y más. Entregamos en moneda local —CUP, BRL, MXN— vía transferencia o efectivo, con
                titulares verificados en cada país.
              </p>
            </div>
            <div className="col-span-6 lg:col-span-5 tactile-card p-6 min-h-[280px] flex flex-col justify-between">
              <ShieldCheck className="w-10 h-10 text-[#EAB308]" />
              <div>
                <h3 className="font-display text-xl mb-2">Comprobantes Verificados</h3>
                <p className="text-neutral-400 text-sm">Cada transacción exige comprobante con titular. Equipo contable confirma antes de liberar fondos.</p>
              </div>
            </div>
            <div className="col-span-6 lg:col-span-4 tactile-card p-6 min-h-[220px]">
              <Zap className="w-9 h-9 text-[#EAB308] mb-4" />
              <h3 className="font-display text-xl mb-2">Liquidación Rápida</h3>
              <p className="text-neutral-400 text-sm">Operaciones aprobadas se procesan en cuestión de horas, no días.</p>
            </div>
            <div className="col-span-12 lg:col-span-4 tactile-card p-6 min-h-[220px]">
              <Activity className="w-9 h-9 text-[#EAB308] mb-4" />
              <h3 className="font-display text-xl mb-2">Tasas Dinámicas</h3>
              <p className="text-neutral-400 text-sm">Nuestros admins actualizan tasas cripto/fiat en tiempo real. VIPs reciben tasas preferenciales.</p>
            </div>
            <div className="col-span-12 lg:col-span-4 tactile-card p-6 min-h-[220px]">
              <Boxes className="w-9 h-9 text-[#EAB308] mb-4" />
              <h3 className="font-display text-xl mb-2">Mercancías Físicas</h3>
              <p className="text-neutral-400 text-sm">Canjea tu saldo VIP por contenedores de arroz, harina, refrescos y más.</p>
            </div>
          </div>
        </div>
      </section>

      {/* SERVICES */}
      <section id="services" className="py-20 border-t border-white/5 bg-[#0c0c0c]">
        <div className="max-w-7xl mx-auto px-6 lg:px-12">
          <div className="micro-label text-[#EAB308] mb-3">/ 02 — Servicios</div>
          <h2 className="font-display text-3xl lg:text-5xl mb-12 max-w-3xl">Dos plataformas. Un solo flujo.</h2>
          <div className="grid lg:grid-cols-2 gap-6">
            <div className="tactile-card p-8 hover:glow-yellow transition-shadow">
              <div className="flex items-center justify-between mb-6">
                <span className="micro-label text-neutral-500">SECCIÓN 01</span>
                <span className="text-xs font-mono text-[#22C55E]">● ACTIVA</span>
              </div>
              <h3 className="font-display text-3xl mb-4">Cripto ↔ Fiat</h3>
              <p className="text-neutral-400 mb-6">Intercambia USDT, BTC y más por dólares (Zelle), pesos cubanos, reales brasileños o pesos mexicanos.</p>
              <ul className="space-y-3 text-sm">
                {["Tasas en vivo gestionadas por admin", "Sube comprobante de pago al instante", "Confirmación humana por equipo contable", "Entrega en transferencia, efectivo o cripto"].map((t, i) => (
                  <li key={i} className="flex items-center gap-3 text-neutral-300">
                    <BadgeCheck className="w-4 h-4 text-[#EAB308] shrink-0" />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
            <div className="tactile-card p-8 hover:glow-yellow transition-shadow relative overflow-hidden">
              <div
                className="absolute inset-0 bg-cover bg-center opacity-10"
                style={{ backgroundImage: "url(https://images.unsplash.com/photo-1493946740644-2d8a1f1a6aff?crop=entropy&cs=srgb&fm=jpg&q=85)" }}
              ></div>
              <div className="relative">
                <div className="flex items-center justify-between mb-6">
                  <span className="micro-label text-neutral-500">SECCIÓN 02</span>
                  <span className="text-xs font-mono text-[#EAB308]">VIP ONLY</span>
                </div>
                <h3 className="font-display text-3xl mb-4">Marketplace Físico</h3>
                <p className="text-neutral-400 mb-6">Canjea tu saldo VIP acumulado por mercancía: arroz, harina, refrescos, aceite y más.</p>
                <ul className="space-y-3 text-sm">
                  {["Stock en tiempo real", "Sin comisión, sin mensajería para VIP", "Logística incluida", "Pedidos consolidados diarios"].map((t, i) => (
                    <li key={i} className="flex items-center gap-3 text-neutral-300">
                      <BadgeCheck className="w-4 h-4 text-[#EAB308] shrink-0" />
                      {t}
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
          <div className="micro-label text-[#EAB308] mb-3">/ 03 — Cómo Funciona</div>
          <h2 className="font-display text-3xl lg:text-5xl mb-12 max-w-3xl">Cuatro pasos. Cero confusión.</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { n: "01", t: "Crea tu orden", d: "Elige el par cripto/fiat, ingresa el monto y verifica tu tasa." },
              { n: "02", t: "Sube comprobante", d: "Captura de la transferencia con el nombre del titular." },
              { n: "03", t: "Verificación humana", d: "Nuestro equipo contable confirma la recepción del pago." },
              { n: "04", t: "Recibe tus fondos", d: "Transferencia, efectivo, cripto o acumula en saldo VIP." },
            ].map((s) => (
              <div key={s.n} className="tactile-card p-6">
                <div className="font-display text-5xl text-[#EAB308]/30">{s.n}</div>
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
            <div className="micro-label text-[#EAB308] mb-3">/ 04 — Programa VIP</div>
            <h2 className="font-display text-3xl lg:text-5xl mb-6">Para quien mueve volumen.</h2>
            <p className="text-neutral-400 mb-8 text-base leading-relaxed">
              Si tienes tus propios clientes y operas múltiples transacciones diarias, el programa VIP de Resilience Brothers
              elimina la fricción: <span className="text-white">sin comisión, tasas preferenciales, saldo acumulado</span> y
              opción de canjear por mercancía de nuestro mercado.
            </p>
            <div className="grid grid-cols-2 gap-3">
              {[
                ["0%", "Comisión"],
                ["+5", "Pts mejor tasa"],
                ["Sin costo", "Mensajería"],
                ["Acumula", "Tu saldo"],
              ].map(([v, l], i) => (
                <div key={i} className="border border-white/10 p-4">
                  <div className="font-display text-2xl text-[#EAB308]">{v}</div>
                  <div className="micro-label text-neutral-500 mt-1">{l}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="relative">
            <img
              src="https://images.unsplash.com/photo-1638262052640-82e94d64664a?crop=entropy&cs=srgb&fm=jpg&q=85"
              alt="P2P trust"
              className="w-full h-[480px] object-cover grayscale"
            />
            <div className="absolute bottom-0 left-0 right-0 p-6 glass-panel">
              <div className="micro-label text-[#EAB308] mb-2">Status: VIP Tier</div>
              <p className="font-display text-xl">Confianza verificada. Operación priorizada.</p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 border-t border-white/5">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <h2 className="font-display text-4xl lg:text-6xl mb-6">
            ¿Listo para escalar tu operación?
          </h2>
          <p className="text-neutral-400 mb-8 text-lg">Una cuenta. Acceso completo. Sin fricciones bancarias.</p>
          <Button
            data-testid="cta-signup-btn"
            onClick={handleEnter}
            className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none px-10 h-14 text-base"
          >
            Crear Cuenta con Google <ArrowUpRight className="w-5 h-5 ml-1" />
          </Button>
        </div>
      </section>

      <footer className="border-t border-white/5 py-8">
        <div className="max-w-7xl mx-auto px-6 lg:px-12 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 bg-[#EAB308] flex items-center justify-center font-display text-black text-xs">RB</div>
            <span className="micro-label text-neutral-500">© Resilience Brothers · P2P Network</span>
          </div>
          <span className="micro-label text-neutral-600">Global Trade Infrastructure</span>
        </div>
      </footer>
    </div>
  );
}
