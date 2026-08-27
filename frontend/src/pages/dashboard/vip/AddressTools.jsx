import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation, Trans } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScanLine, BookUser, Trash2, Save, X } from "lucide-react";

const TRANS_STRONG_ONE = { 1: <strong /> };

export function parseQrAddress(text) {
  let t = (text || "").trim();
  t = t.replace(/^[a-z0-9]+:/i, "");
  return t.split("?")[0].trim();
}


export function QrScanDialog({ open, onClose, onResult }) {
  const { t } = useTranslation();
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!open) return undefined;
    setError(false);
    let scanner = null;
    let disposed = false;
    import("html5-qrcode").then(({ Html5Qrcode }) => {
      if (disposed || !document.getElementById("qr-scan-region")) return;
      scanner = new Html5Qrcode("qr-scan-region");
      scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: 220 },
        (decoded) => { onResult(parseQrAddress(decoded)); onClose(); },
        () => {},
      ).catch(() => setError(true));
    });
    return () => {
      disposed = true;
      if (scanner) {
        try { scanner.stop().then(() => scanner.clear()).catch(() => {}); } catch { /* noop */ }
      }
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#12101f] border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="qr-scan-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">{t("withdraw.scanQrTitle")}</DialogTitle>
        </DialogHeader>
        <div id="qr-scan-region" className="w-full min-h-[240px] bg-black/40" />
        {error ? (
          <p className="text-xs text-[#EF4444]" data-testid="qr-scan-error">{t("withdraw.scanQrError")}</p>
        ) : (
          <p className="text-xs text-neutral-500">{t("withdraw.scanQrHint")}</p>
        )}
      </DialogContent>
    </Dialog>
  );
}


export function AddressBookDialog({ open, onClose, onSelect }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    axios.get(`${API}/vip/crypto-addresses`, { withCredentials: true })
      .then((r) => setItems(r.data?.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [open]);
  const remove = async (id) => {
    try {
      await axios.delete(`${API}/vip/crypto-addresses/${id}`, { withCredentials: true });
      setItems((prev) => prev.filter((i) => i.id !== id));
      toast.success(t("withdraw.addressDeletedToast"));
    } catch { toast.error(t("withdraw.genericErr")); }
  };
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-[#12101f] border-white/10 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto" data-testid="address-book-dialog">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <BookUser className="w-5 h-5 text-[#8B5CF6]" /> {t("withdraw.addressBookTitle")}
          </DialogTitle>
        </DialogHeader>
        {loading && <p className="text-xs text-neutral-500">…</p>}
        {!loading && items.length === 0 && (
          <p className="text-sm text-neutral-500 py-4" data-testid="address-book-empty">
            {t("withdraw.addressBookEmpty")}
          </p>
        )}
        <div className="space-y-2 max-h-72 overflow-y-auto">
          {items.map((a) => (
            <div key={a.id} className="flex items-center gap-2 border border-white/10 bg-black/30 px-3 py-2 hover:border-[#8B5CF6]/40 transition-colors">
              <button
                type="button"
                onClick={() => { onSelect(a); onClose(); }}
                className="flex-1 text-left min-w-0"
                data-testid={`saved-address-${a.id}`}
              >
                <div className="text-sm text-white flex items-center gap-2">
                  <span className="truncate">{a.label}</span>
                  <span className="text-[0.6rem] font-mono uppercase border border-[#8B5CF6]/40 text-[#A78BFA] px-1.5 py-0.5 shrink-0">
                    {a.network}
                  </span>
                </div>
                <div className="text-[0.7rem] font-mono text-neutral-500 truncate">{a.address}</div>
              </button>
              <button
                type="button"
                onClick={() => remove(a.id)}
                data-testid={`delete-address-${a.id}`}
                className="text-neutral-500 hover:text-[#EF4444] shrink-0 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}


export function SaveAddressControl({ address, network }) {
  const { t } = useTranslation();
  const [openLabel, setOpenLabel] = useState(false);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!label.trim()) return;
    setBusy(true);
    try {
      await axios.post(`${API}/vip/crypto-addresses`, {
        label: label.trim(), address: address.trim(), network,
      }, { withCredentials: true });
      toast.success(t("withdraw.addressSavedToast"));
      setOpenLabel(false); setLabel("");
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : t("withdraw.saveAddressErr"));
    } finally { setBusy(false); }
  };
  if (!openLabel) {
    return (
      <button
        type="button"
        onClick={() => setOpenLabel(true)}
        data-testid="save-address-btn"
        className="inline-flex items-center gap-1.5 text-[0.7rem] text-[#8B5CF6] hover:text-[#A78BFA] uppercase tracking-widest font-semibold mt-2"
      >
        <Save className="w-3.5 h-3.5" /> {t("withdraw.saveAddressBtn")}
      </button>
    );
  }
  return (
    <div className="flex items-center gap-2 mt-2">
      <Input
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder={t("withdraw.addressLabelPh")}
        maxLength={60}
        data-testid="save-address-label"
        className="rounded-none bg-[#0a0a0a] border-white/10 h-9 text-xs"
      />
      <Button
        size="sm"
        onClick={save}
        disabled={busy || label.trim().length === 0}
        data-testid="save-address-confirm"
        className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white h-9 text-xs shrink-0"
      >
        {t("withdraw.confirmSaveBtn")}
      </Button>
      <button
        type="button"
        onClick={() => setOpenLabel(false)}
        data-testid="save-address-cancel"
        className="text-neutral-500 hover:text-white shrink-0"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}


export function CryptoAddressField({
  currency, details, onChange, activeNetwork, cryptoAddressMatch, cryptoNetwork, onPickSaved,
}) {
  const { t } = useTranslation();
  const [qrOpen, setQrOpen] = useState(false);
  const [bookOpen, setBookOpen] = useState(false);
  const transValues = { network: activeNetwork.label };
  return (
    <div data-testid="crypto-address-block">
      <Label className="micro-label text-neutral-500">
        {t("withdraw.addressLabel", { currency })} <span className="text-[#8B5CF6]">*</span>
      </Label>
      <div className="relative mt-2">
        <Input
          data-testid="withdraw-details"
          value={details}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t("withdraw.addressPh")}
          className="rounded-none bg-[#0a0a0a] border-white/10 h-12 font-mono pr-20"
        />
        <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center">
          <button
            type="button"
            onClick={() => setQrOpen(true)}
            data-testid="scan-qr-btn"
            title={t("withdraw.scanQrTitle")}
            className="p-1.5 text-neutral-400 hover:text-[#8B5CF6] transition-colors"
          >
            <ScanLine className="w-5 h-5" />
          </button>
          <button
            type="button"
            onClick={() => setBookOpen(true)}
            data-testid="address-book-btn"
            title={t("withdraw.addressBookTitle")}
            className="p-1.5 text-neutral-400 hover:text-[#8B5CF6] transition-colors"
          >
            <BookUser className="w-5 h-5" />
          </button>
        </div>
      </div>
      {cryptoAddressMatch === true && (
        <p data-testid="crypto-address-match-ok"
          className="text-[0.75rem] text-[#22C55E] mt-1 leading-relaxed flex items-center gap-1.5">
          <span aria-hidden>✓</span>
          <span>
            <Trans i18nKey="withdraw.cryptoMatchOk" values={transValues} components={TRANS_STRONG_ONE} />
          </span>
        </p>
      )}
      {cryptoAddressMatch === false && (
        <p data-testid="crypto-address-mismatch"
          className="text-[0.75rem] text-[#EF4444] mt-1 leading-relaxed flex items-start gap-1.5">
          <span aria-hidden className="mt-0.5">⚠</span>
          <span>
            <Trans i18nKey="withdraw.cryptoMismatch" values={transValues} components={TRANS_STRONG_ONE} />
          </span>
        </p>
      )}
      {cryptoAddressMatch === true && (
        <SaveAddressControl address={details} network={cryptoNetwork} />
      )}
      <QrScanDialog open={qrOpen} onClose={() => setQrOpen(false)} onResult={onChange} />
      <AddressBookDialog open={bookOpen} onClose={() => setBookOpen(false)} onSelect={onPickSaved} />
    </div>
  );
}
