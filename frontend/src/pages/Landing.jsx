import { useAuth } from "@/context/AuthContext";
import { useNavigate, useLocation } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import EmailAuthDialog from "@/components/EmailAuthDialog";
import { useScrollParallax } from "@/hooks/useScrollParallax";
import LandingHeader from "@/pages/landing/LandingHeader";
import LandingHero from "@/pages/landing/LandingHero";
import LandingPromoBanner from "@/pages/landing/LandingPromoBanner";
import LandingAbout from "@/pages/landing/LandingAbout";
import LandingServices from "@/pages/landing/LandingServices";
import LandingVipAndCta from "@/pages/landing/LandingVipAndCta";

/**
 * iter100 — Slim orchestrator that composes the split landing sections.
 * All copy stays in i18n; each section owns its own layout.
 */
export default function Landing() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const [emailAuthOpen, setEmailAuthOpen] = useState(false);
  const [prefillEmail, setPrefillEmail] = useState("");
  const scrollY = useScrollParallax();

  // iter112 — capture ?ref=CODE so the post-login claim can apply it.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const ref = (params.get("ref") || "").trim().toUpperCase();
    if (ref && /^[A-Z0-9]{4,16}$/.test(ref)) {
      try { localStorage.setItem("rb_ref_code", ref); } catch {}
      toast.info(t("landing.refCaptured"), { duration: 5000 });
      navigate("/", { replace: true });
    }
  }, [location.search, navigate, t]);

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

  const handleEnter = useCallback(() => {
    if (user) navigate(user.role === "admin" || user.role === "employee" ? "/admin" : "/dashboard");
    else login();
  }, [user, navigate, login]);

  const handleEmailAuth = useCallback(() => {
    if (user) navigate(user.role === "admin" || user.role === "employee" ? "/admin" : "/dashboard");
    else { setPrefillEmail(""); setEmailAuthOpen(true); }
  }, [user, navigate]);

  const closeEmailAuth = useCallback(() => setEmailAuthOpen(false), []);

  return (
    <div className="min-h-screen bg-[#14101F] text-white">
      <LandingHeader user={user} onEnter={handleEnter} onEmailAuth={handleEmailAuth} />
      <LandingHero scrollY={scrollY} onEnter={handleEnter} onEmailAuth={handleEmailAuth} />
      <LandingPromoBanner onEmailAuth={handleEmailAuth} />
      <LandingAbout />
      <LandingServices scrollY={scrollY} />
      <LandingVipAndCta onEnter={handleEnter} onEmailAuth={handleEmailAuth} />
      <EmailAuthDialog open={emailAuthOpen} onClose={closeEmailAuth} initialEmail={prefillEmail} />
    </div>
  );
}
