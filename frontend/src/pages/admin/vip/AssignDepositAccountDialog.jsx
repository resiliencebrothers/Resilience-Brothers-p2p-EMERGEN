import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Landmark } from "lucide-react";

// Asigna/corrige la cuenta de cobro de un depósito (p. ej. depósitos
// antiguos creados antes de que el flujo guardara la cuenta).
export function AssignDepositAccountDialog({ deposit, onClose, onDone }) {
  const { t } = useTranslation();
  const [options, setOptions] = useState([]);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!deposit) return;
    setPicked(deposit.payment_account_id || "");
    axios.get(`${API}/admin/deposits/payment-account-options`, {
      params: { currency: deposit.currency }, withCredentials: true,
    })
      .then((r) => setOptions(r.data?.items || []))
      .catch(() => setOptions([]));
  }, [deposit]);

  const submit = async () => {
    if (!deposit || !picked) return;
    setBusy(true);
    try {
      await axios.put(`${API}/admin/deposits/${deposit.id}/payment-account`,
        { payment_account_id: picked }, { withCredentials: true });
      toast.success(t("adminDeposits.assignedToast"));
      onDone?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("adminDeposits.actionError"));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={!!deposit} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="assign-deposit-account-dialog"
        className="bg-[#0c0c0c] border border-emerald-500/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Landmark className="w-4 h-4 text-emerald-400" /> {t("adminDeposits.assignDialogTitle")}
          </DialogTitle>
        </DialogHeader>
        {deposit && (
          <p className="text-xs text-neutral-400">
            {t("adminDeposits.assignDialogHint", {
              amount: deposit.amount, currency: deposit.currency, client: deposit.user_name || deposit.user_email,
            })}
          </p>
        )}
        {options.length === 0 ? (
          <div className="text-xs text-amber-400 border border-amber-500/30 bg-amber-500/5 p-3" data-testid="assign-account-empty">
            {t("adminDeposits.assignNoAccounts", { currency: deposit?.currency })}
          </div>
        ) : (
          <div className="space-y-2 mt-1" data-testid="assign-account-options">
            {options.map((o) => (
              <label
                key={o.id}
                data-testid={`assign-account-option-${o.id}`}
                className={`flex items-start gap-3 border p-3 cursor-pointer transition-colors ${
                  picked === o.id ? "border-emerald-500 bg-emerald-500/5" : "border-white/10 hover:border-white/30"
                }`}
              >
                <input
                  type="radio"
                  name="deposit-account"
                  value={o.id}
                  checked={picked === o.id}
                  onChange={() => setPicked(o.id)}
                  className="mt-1 accent-emerald-500"
                />
                <div className="min-w-0">
                  <div className="text-sm text-white font-medium">
                    {o.label}
                    {o.network && <span className="ml-2 text-[0.6rem] uppercase font-mono text-[#A78BFA]">{o.network}</span>}
                  </div>
                  <pre className="text-[0.65rem] text-neutral-400 whitespace-pre-wrap font-mono mt-0.5">{o.account_details}</pre>
                </div>
              </label>
            ))}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-3 border-t border-white/5 mt-2">
          <Button variant="ghost" onClick={onClose} className="rounded-none text-neutral-400">
            {t("common.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={busy || !picked}
            data-testid="assign-account-save"
            className="rounded-none bg-emerald-500 hover:bg-emerald-400 text-black font-semibold disabled:opacity-40"
          >
            {t("adminDeposits.assignSave")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
