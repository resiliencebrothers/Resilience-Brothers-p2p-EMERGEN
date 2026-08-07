import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { QrCode, Download, Printer, Pencil, ChevronDown, ChevronUp, RotateCcw, Save } from "lucide-react";
import { QRCodeCanvas } from "qrcode.react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { useAuth } from "@/context/AuthContext";

// iter150 — QR poster promo lives on the backend so every device (and every
// public landing visitor) sees the same in-store offer. A tiny module-level
// cache shares the fetched value across every QrShareButton instance on the
// page and keeps them in sync when admin/staff hit "Guardar".
let posterCache = null;
const posterSubscribers = new Set();

const publishPoster = (data) => {
  posterCache = { heading: data?.heading || "", promo: data?.promo || "" };
  for (const cb of posterSubscribers) cb(posterCache);
};

let inFlightFetch = null;
const fetchPoster = async () => {
  if (inFlightFetch) return inFlightFetch;
  inFlightFetch = (async () => {
    try {
      const res = await axios.get(`${API}/qr-poster`);
      publishPoster(res.data);
      return posterCache;
    } catch {
      publishPoster({ heading: "", promo: "" });
      return posterCache;
    } finally {
      inFlightFetch = null;
    }
  })();
  return inFlightFetch;
};

const esc = (s) => (s || "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

/**
 * iter149 — "Código QR" button next to the share button. Opens a dialog with
 * a scannable QR of the app/referral URL plus PNG download and a printable
 * poster for in-store promotions (operator request).
 *
 * iter150 — Promo/heading are now persisted server-side (see backend
 * `routes/qr_poster.py`) and shared globally: admin/staff edit once from
 * any device and every user + anonymous landing visitor sees the same
 * poster the next time they open the dialog.
 */
export const QrShareButton = ({
  url,
  label,
  variant = "outline",
  className = "",
  testid = "qr-share-btn",
  posterCode = "",
}) => {
  const { t } = useTranslation();
  const auth = useAuth();
  // Only admins / employees see the editing UI. Everyone else prints the
  // poster with the admin-configured promo (read-only).
  const canCustomize = auth?.user?.role === "admin" || auth?.user?.role === "employee";
  const [open, setOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [heading, setHeading] = useState(posterCache?.heading || "");
  const [promo, setPromo] = useState(posterCache?.promo || "");
  const [savedHeading, setSavedHeading] = useState(posterCache?.heading || "");
  const [savedPromo, setSavedPromo] = useState(posterCache?.promo || "");
  const [saving, setSaving] = useState(false);
  const hiResRef = useRef(null);

  // Subscribe to poster updates from any other QrShareButton instance so
  // saving in the referrals page immediately updates the landing header.
  useEffect(() => {
    const cb = (data) => {
      setHeading(data.heading);
      setPromo(data.promo);
      setSavedHeading(data.heading);
      setSavedPromo(data.promo);
    };
    posterSubscribers.add(cb);
    return () => { posterSubscribers.delete(cb); };
  }, []);

  // Load the global poster the first time the dialog opens (cheap enough
  // to skip if the cache is already populated by another instance).
  useEffect(() => {
    if (!open) return;
    if (posterCache) return;
    fetchPoster();
  }, [open]);

  const hasChanges = heading.trim() !== savedHeading.trim() || promo.trim() !== savedPromo.trim();

  const savePoster = async () => {
    setSaving(true);
    try {
      const res = await axios.put(
        `${API}/qr-poster`,
        { heading: heading.trim(), promo: promo.trim() },
        { withCredentials: true },
      );
      publishPoster(res.data);
      toast.success(t("qrShare.saved"));
    } catch (e) {
      const status = e.response?.status;
      if (status === 401 || status === 403) {
        toast.error(t("qrShare.saveForbidden"));
      } else {
        toast.error(t("qrShare.saveError"));
      }
    } finally {
      setSaving(false);
    }
  };

  const resetCustom = () => { setHeading(""); setPromo(""); };

  const pngDataUrl = () =>
    hiResRef.current?.querySelector("canvas")?.toDataURL("image/png");

  const download = () => {
    const png = pngDataUrl();
    if (!png) return;
    const a = document.createElement("a");
    a.href = png;
    a.download = posterCode
      ? `resilience-qr-${posterCode}.png`
      : "resilience-brothers-qr.png";
    a.click();
    toast.success(t("qrShare.downloaded"));
  };

  const printPoster = () => {
    const png = pngDataUrl();
    if (!png) return;
    const w = window.open("", "_blank", "width=820,height=1000");
    if (!w) {
      toast.error(t("qrShare.printError"));
      return;
    }
    // Non-staff always print the last saved (server) values. Staff print
    // whatever is currently in the inputs — even if not saved yet — so they
    // can preview before committing globally.
    const useHeading = canCustomize ? heading : savedHeading;
    const usePromo = canCustomize ? promo : savedPromo;
    const posterHeading = esc(useHeading.trim()) || t("qrShare.posterHeading");
    const promoLine = esc(usePromo.trim());
    w.document.write(`<!doctype html><html><head><title>Resilience Brothers — QR</title>
<style>
  body { font-family: Arial, Helvetica, sans-serif; margin:0; padding:56px 24px; text-align:center; color:#111; background:#fff; }
  .brand { font-size:36px; font-weight:800; letter-spacing:2px; }
  .sub { font-size:14px; color:#555; letter-spacing:5px; text-transform:uppercase; margin-top:8px; }
  .promo { margin-top:26px; background:#8B5CF6; color:#fff; font-size:26px; font-weight:800; display:inline-block; padding:14px 32px; letter-spacing:1px; }
  img { width:430px; max-width:82vw; margin:36px auto 28px; display:block; }
  .heading { font-size:28px; font-weight:700; }
  .url { font-size:16px; color:#333; margin-top:12px; font-family:monospace; word-break:break-all; }
  .code { margin-top:22px; font-size:22px; border:3px dashed #8B5CF6; display:inline-block; padding:12px 30px; letter-spacing:6px; font-weight:800; }
  .codeLabel { margin-top:26px; font-size:13px; color:#666; letter-spacing:3px; text-transform:uppercase; }
  @media print { body { padding:24px; } }
</style></head><body>
  <div class="brand">RESILIENCE BROTHERS</div>
  <div class="sub">P2P · Exchange &amp; Marketplace</div>
  ${promoLine ? `<div class="promo">${promoLine}</div>` : ""}
  <img src="${png}" alt="QR" />
  <div class="heading">${posterHeading}</div>
  <div class="url">${url}</div>
  ${posterCode ? `<div class="codeLabel">${t("qrShare.posterCodeLabel")}</div><div class="code">${posterCode}</div>` : ""}
  <script>window.onload = function () { setTimeout(function () { window.print(); }, 350); };</script>
</body></html>`);
    w.document.close();
  };

  return (
    <>
      <Button
        data-testid={testid}
        variant={variant}
        onClick={() => setOpen(true)}
        className={className}
        title={label || t("qrShare.button")}
        aria-label={label || t("qrShare.button")}
      >
        <QrCode className="w-4 h-4" />
        {label ? <span className="ml-2">{label}</span> : null}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          data-testid="qr-share-dialog"
          className="bg-[#0c0c0c] border border-white/10 text-white rounded-none max-w-sm max-h-[90vh] overflow-y-auto"
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <QrCode className="w-5 h-5 text-[#8B5CF6]" />
              {t("qrShare.title")}
            </DialogTitle>
            <DialogDescription className="text-neutral-400 text-xs">
              {t("qrShare.hint")}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col items-center gap-3">
            <div className="bg-white p-4" data-testid="qr-share-canvas">
              <QRCodeCanvas value={url} size={228} level="M" marginSize={1} />
            </div>
            <div className="text-[0.7rem] text-neutral-400 font-mono break-all text-center" data-testid="qr-share-url">
              {url}
            </div>
            {posterCode && (
              <div className="text-sm font-display tracking-[0.25em] text-violet-300 border border-dashed border-violet-500/40 px-4 py-1.5">
                {posterCode}
              </div>
            )}
            {!canCustomize && savedPromo.trim() && (
              <div
                className="bg-[#8B5CF6] text-white text-xs font-bold text-center px-3 py-1.5 uppercase tracking-widest"
                data-testid="qr-promo-readonly"
              >
                {savedPromo.trim()}
              </div>
            )}
          </div>

          <div className="pt-1">
            {canCustomize && (
              <>
                <button
                  type="button"
                  onClick={() => setCustomOpen((v) => !v)}
                  data-testid="qr-customize-toggle"
                  className="w-full flex items-center justify-between text-[0.65rem] uppercase tracking-widest text-neutral-400 hover:text-white border border-white/10 px-3 py-2 transition-colors"
                >
                  <span className="flex items-center gap-2">
                    <Pencil className="w-3.5 h-3.5 text-[#8B5CF6]" /> {t("qrShare.customize")}
                  </span>
                  {customOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                </button>
                {customOpen && (
                  <div className="border border-white/10 border-t-0 p-3 space-y-3">
                    <div>
                      <div className="micro-label text-neutral-500 text-[0.6rem] mb-1">
                        {t("qrShare.headingLabel")}
                      </div>
                      <Input
                        data-testid="qr-heading-input"
                        value={heading}
                        onChange={(e) => setHeading(e.target.value)}
                        placeholder={t("qrShare.posterHeading")}
                        maxLength={60}
                        className="rounded-none bg-black/40 border-white/10 text-white h-9 text-sm"
                      />
                    </div>
                    <div>
                      <div className="micro-label text-neutral-500 text-[0.6rem] mb-1">
                        {t("qrShare.promoLabel")}
                      </div>
                      <Input
                        data-testid="qr-promo-input"
                        value={promo}
                        onChange={(e) => setPromo(e.target.value)}
                        placeholder={t("qrShare.promoPlaceholder")}
                        maxLength={80}
                        className="rounded-none bg-black/40 border-white/10 text-white h-9 text-sm"
                      />
                    </div>
                    {promo.trim() && (
                      <div
                        className="bg-[#8B5CF6] text-white text-sm font-bold text-center px-4 py-2"
                        data-testid="qr-promo-preview"
                      >
                        {promo.trim()}
                      </div>
                    )}
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      {(heading || promo) ? (
                        <button
                          type="button"
                          onClick={resetCustom}
                          data-testid="qr-customize-reset"
                          className="flex items-center gap-1.5 text-[0.65rem] uppercase tracking-widest text-neutral-500 hover:text-white transition-colors"
                        >
                          <RotateCcw className="w-3 h-3" /> {t("qrShare.resetText")}
                        </button>
                      ) : <span />}
                      <Button
                        type="button"
                        onClick={savePoster}
                        disabled={saving || !hasChanges}
                        data-testid="qr-customize-save"
                        className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-8 text-[0.65rem] uppercase tracking-widest font-semibold px-3 disabled:opacity-40"
                      >
                        <Save className="w-3 h-3 mr-1.5" />
                        {saving ? t("qrShare.saving") : t("qrShare.save")}
                      </Button>
                    </div>
                    <p className="text-[0.65rem] text-neutral-500">{t("qrShare.customizeHint")}</p>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2 pt-2">
            <Button
              data-testid="qr-download-btn"
              variant="ghost"
              onClick={download}
              className="rounded-none border border-white/15 text-neutral-300 hover:text-white hover:border-[#8B5CF6]/50 h-10 text-xs uppercase tracking-widest font-semibold"
            >
              <Download className="w-4 h-4 mr-2" /> {t("qrShare.download")}
            </Button>
            <Button
              data-testid="qr-print-btn"
              onClick={printPoster}
              className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-10 text-xs uppercase tracking-widest font-semibold"
            >
              <Printer className="w-4 h-4 mr-2" /> {t("qrShare.print")}
            </Button>
          </div>

          {/* Hidden hi-res canvas used for PNG download + poster */}
          <div ref={hiResRef} className="hidden" aria-hidden="true">
            <QRCodeCanvas value={url} size={1024} level="M" marginSize={2} />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
};
