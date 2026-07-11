/**
 * iter52 — Admin balance-ledger drill-down dialog.
 *
 * Opens when a staff member clicks the History icon next to a user's
 * balance in the AdminUsers table. Shows every `accumulate` order that
 * actually credited the user's `vip_balances`, grouped by destination
 * currency. Used to resolve disputes like "I sent Zelle twice but only one
 * shows up" — the staff can see exactly which orders contributed.
 *
 * Reads from GET /api/admin/users/{user_id}/balance-ledger.
 */
import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { History, Coins } from "lucide-react";

export default function AdminUserLedgerDialog({ user, open, onClose }) {
  const [ledger, setLedger] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeCurrency, setActiveCurrency] = useState(null);

  useEffect(() => {
    if (!open || !user) return;
    setLoading(true);
    axios.get(
      `${API}/admin/users/${user.user_id}/balance-ledger`,
      { withCredentials: true },
    )
      .then((r) => {
        setLedger(r.data);
        const codes = Object.keys(r.data?.by_currency || {});
        setActiveCurrency(codes[0] || null);
      })
      .catch(() => setLedger({ by_currency: {}, total_orders: 0 }))
      .finally(() => setLoading(false));
  }, [open, user]);

  if (!user) return null;

  const codes = Object.keys(ledger?.by_currency || {});
  const bucket = activeCurrency ? ledger?.by_currency?.[activeCurrency] : null;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent
        className="bg-[#111] border-white/10 text-white rounded-none max-w-3xl max-h-[85vh] overflow-y-auto"
        data-testid="admin-ledger-dialog"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 flex-wrap">
            <History className="w-5 h-5 text-[#8B5CF6]" />
            Auditoría de saldo · {user.name}
            <span className="text-xs text-neutral-500 font-mono">{user.email}</span>
          </DialogTitle>
        </DialogHeader>
        <div className="pt-2">
          {loading && (
            <div className="text-sm text-neutral-400 text-center py-8" data-testid="ledger-loading">
              Cargando...
            </div>
          )}
          {!loading && ledger?.total_orders === 0 && (
            <div className="text-sm text-neutral-500 text-center py-8" data-testid="ledger-empty">
              Este usuario no tiene órdenes acumuladas registradas.
            </div>
          )}
          {!loading && ledger?.total_orders > 0 && (
            <>
              <div className="text-xs text-neutral-500 mb-3">
                {ledger.total_orders} {ledger.total_orders === 1 ? "orden" : "órdenes"} acreditadas en total.
              </div>
              {/* Currency tabs */}
              <div
                className="flex gap-1 mb-4 overflow-x-auto border-b border-white/10"
                data-testid="ledger-currency-tabs"
              >
                {codes.map((code) => (
                  <button
                    key={code}
                    onClick={() => setActiveCurrency(code)}
                    className={`text-sm px-3 py-2 transition-colors flex items-center gap-2 ${
                      activeCurrency === code
                        ? "text-[#8B5CF6] border-b-2 border-[#8B5CF6] font-semibold"
                        : "text-neutral-400 hover:text-white"
                    }`}
                    data-testid={`ledger-tab-${code}`}
                  >
                    <Coins className="w-3.5 h-3.5" />
                    {code}
                    <span className="text-[0.65rem] text-neutral-500">
                      ({ledger.by_currency[code].orders.length})
                    </span>
                  </button>
                ))}
              </div>
              {bucket && (
                <>
                  <div className="border border-[#8B5CF6]/30 bg-[#8B5CF6]/5 p-3 flex justify-between items-baseline mb-3">
                    <span className="text-xs text-neutral-400">Total acreditado en {activeCurrency}:</span>
                    <span
                      className="font-mono text-lg text-[#8B5CF6]"
                      data-testid={`ledger-total-${activeCurrency}`}
                    >
                      {bucket.total.toLocaleString(undefined, { maximumFractionDigits: 4 })} {activeCurrency}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {bucket.orders.map((o) => (
                      <div
                        key={o.id}
                        className="border border-white/10 p-3 text-sm hover:border-[#8B5CF6]/30 transition-colors"
                        data-testid={`admin-ledger-order-${o.id}`}
                      >
                        <div className="flex justify-between items-start gap-2 flex-wrap">
                          <div>
                            <div className="font-mono">
                              +{Number(o.amount_to).toLocaleString(undefined, { maximumFractionDigits: 4 })} {o.to_code}
                            </div>
                            <div className="text-xs text-neutral-500 mt-0.5">
                              desde {Number(o.amount_from).toLocaleString(undefined, { maximumFractionDigits: 2 })} {o.from_code}
                              {o.sender_name && (
                                <span className="text-neutral-600"> · {o.sender_name}</span>
                              )}
                            </div>
                          </div>
                          <div className="text-right">
                            <span className="text-[0.65rem] uppercase tracking-wider text-[#22C55E]">
                              {o.status}
                            </span>
                            <div className="text-[0.65rem] text-neutral-600 mt-0.5">
                              {new Date(o.accumulated_at || o.created_at).toLocaleString()}
                            </div>
                          </div>
                        </div>
                        <div className="text-[0.6rem] text-neutral-700 font-mono mt-2 break-all">
                          ID: {o.id}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
