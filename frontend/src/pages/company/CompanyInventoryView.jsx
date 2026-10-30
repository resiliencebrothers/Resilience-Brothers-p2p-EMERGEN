import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Warehouse, Store, ArrowRightLeft, PackagePlus, Undo2, History, SlidersHorizontal, Bell } from "lucide-react";
import { toast } from "sonner";

export default function CompanyInventoryView() {
  const { t, i18n } = useTranslation();
  const [rows, setRows] = useState([]);
  const [stores, setStores] = useState([]);
  const [moves, setMoves] = useState([]);
  const [dialog, setDialog] = useState(null); // {mode, product, storeId?}
  const [qty, setQty] = useState("");
  const [storeId, setStoreId] = useState("");
  const [busy, setBusy] = useState(false);

  const moveLabel = (type) => t(`company.inventory.move.${type}`, { defaultValue: type });

  const load = useCallback(() => {
    axios.get(`${API}/company/inventory`, { withCredentials: true }).then((r) => setRows(r.data)).catch(() => {});
    axios.get(`${API}/company/inventory/moves`, { withCredentials: true }).then((r) => setMoves(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    axios.get(`${API}/company/stores`, { withCredentials: true }).then((r) => setStores(r.data)).catch(() => {});
  }, [load]);

  const openDialog = (mode, product, preStore = "", preVal = "") => {
    setDialog({ mode, product });
    setQty(mode === "adjust" ? String(product.total)
      : mode === "storemin" ? String(preVal ?? "") : "");
    setStoreId(preStore);
  };

  const submit = async () => {
    const n = parseFloat(qty);
    const { mode, product } = dialog;
    if (mode === "adjust") {
      if (isNaN(n) || n < 0) return toast.error(t("company.inventory.invalidTotal"));
    } else if (mode === "storemin") {
      if (isNaN(n) || n < 0) return toast.error(t("company.inventory.invalidMin"));
    } else if (!n || n <= 0) {
      return toast.error(t("company.inventory.invalidQty"));
    }
    if ((mode === "distribute" || mode === "return") && !storeId) return toast.error(t("company.inventory.chooseStore"));
    setBusy(true);
    // F2-02 — clave estable de operación: se genera UNA vez y se conserva en el
    // reintento por pérdida de respuesta, para que el servidor deduplique.
    const opId = (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
    let body;
    if (mode === "receive") body = { product_id: product.product_id, qty: n, op_id: opId };
    else if (mode === "adjust") body = { product_id: product.product_id, new_total: n, expected_total: product.total, op_id: opId };
    else if (mode === "storemin") body = { product_id: product.product_id, store_id: storeId, min_stock: n };
    else body = { product_id: product.product_id, store_id: storeId, qty: n, op_id: opId };
    const okMsg = mode === "receive" ? t("company.inventory.received")
      : mode === "distribute" ? t("company.inventory.distributedOk")
      : mode === "return" ? t("company.inventory.returnedOk")
      : mode === "storemin" ? t("company.inventory.storeMinUpdatedOk")
      : t("company.inventory.stockAdjustedOk");
    const endpoint = mode === "storemin" ? "store-min" : mode;
    const doPost = () => axios.post(`${API}/company/inventory/${endpoint}`, body, { withCredentials: true });
    try {
      try {
        await doPost();
      } catch (e1) {
        // Sin respuesta del servidor (red) → reintenta UNA vez con la MISMA clave.
        if (!e1.response) { await doPost(); } else { throw e1; }
      }
      toast.success(okMsg);
      setDialog(null); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("company.inventory.opFailed"));
    } finally { setBusy(false); }
  };

  const title = dialog?.mode === "receive" ? t("company.inventory.dialogReceive")
    : dialog?.mode === "distribute" ? t("company.inventory.dialogDistribute")
    : dialog?.mode === "adjust" ? t("company.inventory.dialogAdjust")
    : dialog?.mode === "storemin" ? t("company.inventory.dialogStoremin")
    : t("company.inventory.dialogReturn");

  return (
    <div className="space-y-6" data-testid="company-inventory-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">{t("company.inventory.sectionLabel")}</div>
        <h2 className="font-display text-2xl flex items-center gap-3">
          <Warehouse className="w-6 h-6 text-[#8B5CF6]" /> {t("company.inventory.title")}
        </h2>
        <p className="text-sm text-neutral-500 mt-1">{t("company.inventory.subtitle")}</p>
      </div>

      {rows.length === 0 && (
        <p className="text-neutral-500 text-center py-12 tactile-card" data-testid="company-inventory-empty">
          {t("company.inventory.empty")}
        </p>
      )}

      <div className="space-y-4">
        {rows.map((p) => (
          <div key={p.product_id} className="tactile-card p-4" data-testid={`company-inv-${p.product_id}`}>
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <h3 className="font-display text-lg">{p.name}</h3>
                <div className="flex items-center gap-4 mt-2 text-sm">
                  <span className="text-neutral-400">{t("company.inventory.total")} <span className="text-white font-mono" data-testid={`company-inv-total-${p.product_id}`}>{p.total}</span></span>
                  <span className="flex items-center gap-1 text-[#8B5CF6]">
                    <Warehouse className="w-4 h-4" /> {t("company.inventory.central")} <span className="font-mono" data-testid={`company-inv-central-${p.product_id}`}>{p.central}</span>
                  </span>
                  {p.over_distributed && <span className="text-amber-400 text-xs">{t("company.inventory.overDistributed")}</span>}
                  {p.low && (
                    <span className="flex items-center gap-1 text-amber-300 text-xs border border-amber-500/30 bg-amber-500/10 px-2 py-0.5" data-testid={`company-inv-low-${p.product_id}`}>
                      {t("company.inventory.lowStock", { n: p.min_stock })}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex gap-2">
                <Button data-testid={`company-inv-receive-${p.product_id}`} size="sm" variant="outline"
                  onClick={() => openDialog("receive", p)}
                  className="rounded-none border-white/15 hover:border-[#8B5CF6] text-white">
                  <PackagePlus className="w-4 h-4 mr-1" /> {t("company.inventory.receive")}
                </Button>
                <Button data-testid={`company-inv-distribute-${p.product_id}`} size="sm"
                  onClick={() => openDialog("distribute", p)}
                  className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white">
                  <ArrowRightLeft className="w-4 h-4 mr-1" /> {t("company.inventory.distribute")}
                </Button>
                <Button data-testid={`company-inv-adjust-${p.product_id}`} size="sm" variant="outline"
                  onClick={() => openDialog("adjust", p)}
                  className="rounded-none border-white/15 hover:border-amber-400 text-white">
                  <SlidersHorizontal className="w-4 h-4 mr-1" /> {t("company.inventory.adjust")}
                </Button>
              </div>
            </div>
            {p.stores.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/5 flex flex-wrap gap-2">
                {p.stores.map((s) => (
                  <div key={s.store_id} className={`flex items-center gap-2 bg-[#0a0a0a] border px-3 py-1.5 text-sm ${s.low ? "border-amber-500/40" : "border-white/10"}`} data-testid={`company-inv-store-${p.product_id}-${s.store_id}`}>
                    <Store className="w-3.5 h-3.5 text-neutral-500" />
                    <span className="text-neutral-300">{s.store_name}</span>
                    <span className={`font-mono ${s.low ? "text-amber-300" : "text-white"}`} data-testid={`company-inv-store-qty-${p.product_id}-${s.store_id}`}>{s.qty}</span>
                    {s.min > 0 && (
                      <span className="text-[0.6rem] text-neutral-500" data-testid={`company-inv-store-min-${p.product_id}-${s.store_id}`}>{t("company.inventory.storeMinShort", { n: s.min })}</span>
                    )}
                    {s.low && (
                      <span className="text-[0.6rem] text-amber-300" data-testid={`company-inv-store-low-${p.product_id}-${s.store_id}`}>{t("company.inventory.lowShort")}</span>
                    )}
                    <button data-testid={`company-inv-storemin-${p.product_id}-${s.store_id}`}
                      onClick={() => openDialog("storemin", p, s.store_id, s.min)}
                      className="text-neutral-500 hover:text-amber-300" title={t("company.inventory.storeMinTooltip")}>
                      <Bell className="w-3.5 h-3.5" />
                    </button>
                    <button data-testid={`company-inv-return-${p.product_id}-${s.store_id}`}
                      onClick={() => openDialog("return", p, s.store_id)}
                      className="text-neutral-500 hover:text-[#8B5CF6]" title={t("company.inventory.returnTooltip")}>
                      <Undo2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {moves.length > 0 && (
        <div className="tactile-card p-4" data-testid="company-inventory-moves">
          <h3 className="font-display text-base flex items-center gap-2 mb-3"><History className="w-4 h-4 text-[#8B5CF6]" /> {t("company.inventory.movesTitle")}</h3>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {moves.map((m) => (
              <div key={m.id} className="flex items-center justify-between text-xs text-neutral-400 border-b border-white/5 py-1.5">
                <span>{moveLabel(m.type)}{m.store_name ? ` · ${m.store_name}` : ""}</span>
                <span className="flex items-center gap-3">
                  <span className="font-mono text-white">{m.qty}</span>
                  <span className="text-neutral-600">{new Date(m.created_at).toLocaleString(i18n.language || "es")}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">{title}</DialogTitle></DialogHeader>
          {dialog && (
            <div className="space-y-3">
              {dialog.mode === "adjust" ? (
                <p className="text-sm text-neutral-400">{dialog.product.name} · {t("company.inventory.adjustTotalCurrent")}: <span className="font-mono text-white">{dialog.product.total}</span> · {t("company.inventory.distributedLabel")}: <span className="font-mono text-white">{dialog.product.distributed}</span></p>
              ) : (
                <p className="text-sm text-neutral-400">{dialog.product.name} · {t("company.inventory.centralAvailable")}: <span className="font-mono text-white">{dialog.product.central}</span></p>
              )}
              {(dialog.mode === "distribute" || dialog.mode === "return" || dialog.mode === "storemin") && (
                <div>
                  <Label className="micro-label text-neutral-500">{t("company.inventory.store")}</Label>
                  {dialog.mode === "distribute" ? (
                    <Select value={storeId} onValueChange={setStoreId}>
                      <SelectTrigger data-testid="company-inv-store-select" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10">
                        <SelectValue placeholder={t("company.inventory.storePlaceholder")} />
                      </SelectTrigger>
                      <SelectContent className="bg-[#1A1730] border-white/10 text-white">
                        {stores.map((s) => (
                          <SelectItem key={s.id} value={s.id} data-testid={`company-inv-store-opt-${s.id}`}>{s.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input disabled value={dialog.product.stores.find((s) => s.store_id === storeId)?.store_name || ""} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10" />
                  )}
                </div>
              )}
              <div>
                <Label className="micro-label text-neutral-500">{dialog.mode === "adjust" ? t("company.inventory.newTotalLabel") : dialog.mode === "storemin" ? t("company.inventory.storeMinLabel") : t("company.inventory.qtyLabel")}</Label>
                <Input data-testid="company-inv-qty" type="number" step="any" min="0" value={qty}
                  onChange={(e) => setQty(e.target.value)} className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" autoFocus />
                {dialog.mode === "adjust" && (
                  <p className="text-xs text-neutral-500 mt-1">{t("company.inventory.adjustHint", { n: dialog.product.distributed })}</p>
                )}
                {dialog.mode === "storemin" && (
                  <p className="text-xs text-neutral-500 mt-1">{t("company.inventory.storeMinHint")}</p>
                )}
              </div>
              <Button data-testid="company-inv-submit" onClick={submit} disabled={busy}
                className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
                {busy ? t("company.inventory.saving") : t("company.inventory.confirm")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
