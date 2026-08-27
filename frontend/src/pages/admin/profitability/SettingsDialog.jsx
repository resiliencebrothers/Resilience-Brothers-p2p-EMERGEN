// iter113 — per-currency transfer % defaults editor.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";

export default function SettingsDialog({ open, onOpenChange, currencies, settings, onSave }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setRows(currencies.map((c) => {
      const s = settings[c.code] || {};
      return { currency: c.code, name: c.name, buy_pct: s.buy_pct ?? "", sell_pct: s.sell_pct ?? "" };
    }));
  }, [open, currencies, settings]);

  const setVal = (idx, key) => (e) =>
    setRows((p) => p.map((r, i) => (i === idx ? { ...r, [key]: e.target.value } : r)));

  const save = async () => {
    setBusy(true);
    try {
      const items = rows
        .filter((r) => r.buy_pct !== "" || r.sell_pct !== "")
        .map((r) => ({ currency: r.currency, buy_pct: Number(r.buy_pct) || 0, sell_pct: Number(r.sell_pct) || 0 }));
      await onSave(items);
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[85vh] overflow-y-auto" data-testid="profit-settings-dialog">
        <DialogHeader>
          <DialogTitle>{t("profitability.settings.title")}</DialogTitle>
          <DialogDescription>{t("profitability.settings.description")}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[50vh] overflow-y-auto space-y-2 pr-1">
          <div className="grid grid-cols-[1fr_5rem_5rem] gap-2 text-[0.65rem] text-neutral-500 uppercase tracking-wide px-1">
            <span>{t("profitability.settings.currency")}</span>
            <span>{t("profitability.settings.buyPct")}</span>
            <span>{t("profitability.settings.sellPct")}</span>
          </div>
          {rows.map((r, idx) => (
            <div key={r.currency} className="grid grid-cols-[1fr_5rem_5rem] gap-2 items-center" data-testid={`settings-row-${r.currency}`}>
              <div>
                <div className="font-mono text-sm text-neutral-200">{r.currency}</div>
                <div className="text-[0.6rem] text-neutral-500">{r.name}</div>
              </div>
              <input type="number" step="any" min="0" value={r.buy_pct} onChange={setVal(idx, "buy_pct")}
                placeholder="0"
                data-testid={`settings-buypct-${r.currency}`}
                className="bg-white/[0.04] border border-white/10 rounded-md px-2 py-1.5 text-xs font-mono text-neutral-200 focus:outline-none focus:border-[#8B5CF6]/60" />
              <input type="number" step="any" min="0" value={r.sell_pct} onChange={setVal(idx, "sell_pct")}
                placeholder="0"
                data-testid={`settings-sellpct-${r.currency}`}
                className="bg-white/[0.04] border border-white/10 rounded-md px-2 py-1.5 text-xs font-mono text-neutral-200 focus:outline-none focus:border-[#8B5CF6]/60" />
            </div>
          ))}
        </div>
        <Button onClick={save} disabled={busy} className="w-full" data-testid="profit-settings-save-btn">
          {t("profitability.settings.save")}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
