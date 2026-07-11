import { useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ArrowLeftRight, Wallet, ShoppingBag, ChevronLeft } from "lucide-react";

const SLIDES = [
  {
    icon: ArrowLeftRight,
    eyebrow: "01 — Intercambia",
    title: "Cripto ↔ Fiat sin fronteras",
    body: "Cambia USDT, BTC y otras criptos por dólares, euros y pesos. Subes un comprobante, nosotros confirmamos en minutos.",
  },
  {
    icon: Wallet,
    eyebrow: "02 — Acumula",
    title: "Tu saldo VIP, en cualquier moneda",
    body: "Cada operación se acumula a tu balance multi-moneda. Retira cuando quieras o úsalo para canjear productos.",
  },
  {
    icon: ShoppingBag,
    eyebrow: "03 — Canjea",
    title: "Mercancía real con tu saldo",
    body: "Arroz, harina, aceite, bebidas y más. Convierte tu saldo digital en productos físicos sin pasar por bancos.",
  },
];

export default function OnboardingDialog({ open, onClose }) {
  const { setUser, user } = useAuth();
  const [idx, setIdx] = useState(0);
  const [saving, setSaving] = useState(false);
  const slide = SLIDES[idx];
  const Icon = slide.icon;
  const isLast = idx === SLIDES.length - 1;

  const finish = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await axios.post(`${API}/me/onboarding/complete`, {}, { withCredentials: true });
      setUser({ ...user, onboarding_completed: true });
    } catch {
      // Non-blocking: even if the network call fails, dismiss locally so the user is not stuck.
      setUser({ ...user, onboarding_completed: true });
    } finally {
      setSaving(false);
      onClose?.();
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) finish(); }}>
      <DialogContent
        data-testid="onboarding-dialog"
        className="bg-[#0a0a0a] border-white/10 text-white rounded-none max-w-lg p-0 overflow-hidden"
      >
        <DialogTitle className="sr-only">{slide.title}</DialogTitle>
        <DialogDescription className="sr-only">{slide.body}</DialogDescription>

        <div className="relative h-64 bg-gradient-to-br from-[#8B5CF6]/15 via-[#141322] to-[#0a0a0a] flex items-center justify-center border-b border-white/10">
          <div className="absolute inset-0 opacity-[0.04] pointer-events-none" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, #FFF 1px, transparent 0)", backgroundSize: "16px 16px" }} />
          <Icon className="w-24 h-24 text-[#8B5CF6]" strokeWidth={1.2} />
        </div>

        <div className="p-8 pb-6">
          <div className="micro-label text-[#8B5CF6] mb-3">/ {slide.eyebrow}</div>
          <h2 className="font-display text-3xl mb-3 leading-tight" data-testid={`onboarding-title-${idx}`}>{slide.title}</h2>
          <p className="text-neutral-400 text-sm leading-relaxed mb-6">{slide.body}</p>

          {/* Progress dots */}
          <div className="flex items-center gap-2 mb-6" data-testid="onboarding-progress">
            {SLIDES.map((s, i) => (
              <button
                key={s.eyebrow}
                type="button"
                aria-label={`Ir a paso ${i + 1}`}
                onClick={() => setIdx(i)}
                className={`h-1.5 transition-all ${i === idx ? "w-8 bg-[#8B5CF6]" : "w-1.5 bg-white/20 hover:bg-white/40"}`}
              />
            ))}
          </div>

          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              data-testid="onboarding-back-btn"
              onClick={() => setIdx(Math.max(0, idx - 1))}
              disabled={idx === 0}
              className="text-sm text-neutral-500 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1.5 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
              Atrás
            </button>

            <div className="flex items-center gap-2">
              {!isLast && (
                <button
                  type="button"
                  data-testid="onboarding-skip-btn"
                  onClick={finish}
                  disabled={saving}
                  className="text-xs text-neutral-500 hover:text-white px-3 h-10 transition-colors"
                >
                  Saltar
                </button>
              )}
              <Button
                type="button"
                data-testid={isLast ? "onboarding-finish-btn" : "onboarding-next-btn"}
                onClick={() => (isLast ? finish() : setIdx(idx + 1))}
                disabled={saving}
                className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-10 px-5"
              >
                {isLast ? (saving ? "..." : "Empezar a operar →") : "Siguiente"}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
