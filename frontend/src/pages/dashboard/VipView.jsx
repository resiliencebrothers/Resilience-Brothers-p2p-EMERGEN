import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Wallet, FileDown } from "lucide-react";

import { VipBalancesGrid } from "./vip/VipBalancesGrid";
import { VipWithdrawalForm } from "./vip/VipWithdrawalForm";
import { VipWithdrawalHistory } from "./vip/VipWithdrawalHistory";
import { VipLedgerDialog } from "./vip/VipLedgerDialog";
import VerificationGateBanner from "@/components/VerificationGateBanner";

export default function VipView() {
  const { refresh } = useAuth();
  const [withdrawals, setWithdrawals] = useState([]);
  const [balances, setBalances] = useState({ balances: [], total_usdt: 0 });
  // iter52 — per-currency ledger (which orders contributed to each balance)
  const [ledger, setLedger] = useState({ by_currency: {}, total_orders: 0 });
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledgerCurrency, setLedgerCurrency] = useState("");
  const [closingDate, setClosingDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [downloading, setDownloading] = useState(false);

  const downloadClosing = async () => {
    setDownloading(true);
    try {
      const res = await axios.get(`${API}/vip/daily-closing`, {
        params: { date: closingDate },
        responseType: "blob",
        withCredentials: true,
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `cierre_vip_${closingDate}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Cierre descargado");
    } catch (_) {
      toast.error("Error al generar el cierre");
    } finally {
      setDownloading(false);
    }
  };

  const load = useCallback(async () => {
    // Each call independent so a 403 on one (legacy guard) doesn't break the page
    try {
      const r = await axios.get(`${API}/vip/withdrawals/mine`, { withCredentials: true });
      setWithdrawals(r.data);
    } catch (_) { setWithdrawals([]); }
    try {
      const b = await axios.get(`${API}/vip/balances`, { withCredentials: true });
      setBalances(b.data);
    } catch (_) { setBalances({ balances: [], total_usdt: 0 }); }
    try {
      const l = await axios.get(`${API}/vip/balance-ledger`, { withCredentials: true });
      setLedger(l.data);
    } catch (_) { setLedger({ by_currency: {}, total_orders: 0 }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const handleDrillDown = (currency) => {
    setLedgerCurrency(currency);
    setLedgerOpen(true);
  };

  const handleWithdrawalSubmitted = async () => {
    await load();
    await refresh();
  };

  return (
    <div className="space-y-8" data-testid="vip-view">
      <div>
        <div className="micro-label text-[#8B5CF6] mb-2">/ Saldo y Retiros</div>
        <h1 className="font-display text-3xl">Tu balance acumulado</h1>
      </div>

      <div className="relative overflow-hidden bg-gradient-to-b from-[#181628] to-[#1A1730] border border-white/[0.08] rounded-2xl p-8 shadow-2xl shadow-black/50 hover:border-violet-500/20 transition-colors duration-500">
        <div className="absolute -top-24 -right-24 w-64 h-64 bg-violet-500/20 blur-[100px] rounded-full pointer-events-none" />
        <Wallet className="w-8 h-8 text-violet-400 mb-3 relative" />
        <div className="text-xs font-semibold tracking-[0.22em] text-violet-300/70 uppercase mb-3 block relative">
          Valor total (USDT)
        </div>
        <div className="text-5xl sm:text-6xl font-mono tabular-nums tracking-tight font-semibold text-white drop-shadow-[0_2px_10px_rgba(0,0,0,0.5)] relative">
          {balances.total_usdt?.toLocaleString(undefined, { maximumFractionDigits: 2 }) || "0.00"}{" "}
          <span className="text-2xl text-neutral-400">USDT</span>
        </div>
        <div className="text-sm text-neutral-500 mt-2 relative">
          Equivalente consolidado de todas tus monedas · usa tasa normal
        </div>
      </div>

      <VipBalancesGrid
        balances={balances}
        ledger={ledger}
        onDrillDown={handleDrillDown}
      />

      <div className="tactile-card p-6">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h2 className="font-display text-xl flex items-center gap-2">
              <FileDown className="w-5 h-5 text-[#8B5CF6]" /> Cierre Diario
            </h2>
            <p className="text-sm text-neutral-400 mt-1">
              Descarga el reporte PDF de tus órdenes aprobadas del día.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Input
              data-testid="closing-date-input"
              type="date"
              value={closingDate}
              onChange={(e) => setClosingDate(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-11 font-mono w-44"
            />
            <Button
              data-testid="download-closing-btn"
              onClick={downloadClosing}
              disabled={downloading}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-semibold rounded-none h-11"
            >
              <FileDown className="w-4 h-4 mr-2" />
              {downloading ? "Generando..." : "Descargar PDF"}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <VerificationGateBanner blocking action="withdraw">
          <VipWithdrawalForm
            balances={balances}
            onSubmitted={handleWithdrawalSubmitted}
          />
        </VerificationGateBanner>
        <VipWithdrawalHistory withdrawals={withdrawals} />
      </div>

      <VipLedgerDialog
        open={ledgerOpen}
        onOpenChange={setLedgerOpen}
        currency={ledgerCurrency}
        bucket={ledger.by_currency?.[ledgerCurrency]}
      />
    </div>
  );
}
