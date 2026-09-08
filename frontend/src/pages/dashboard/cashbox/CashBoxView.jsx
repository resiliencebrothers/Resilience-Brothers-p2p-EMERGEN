import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  Wallet, Plus, ClipboardCheck, FileDown, Pencil, Trash2, Building2,
} from "lucide-react";
import { MovementDialog } from "./MovementDialog";
import { ArqueoDialog } from "./ArqueoDialog";
import { ReportPanel } from "./ReportPanel";
import { BillInputs, cleanCounts } from "./BillInputs";

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

// iter233 — "Caja En Vivo" integrada: cajas personales (todos) y de empresa
// (staff/admin), fondos CUP/USD, movimientos, arqueo, reporte y Excel.
export default function CashBoxView() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isStaff = ["admin", "employee"].includes(user?.role);
  const [boxes, setBoxes] = useState(null);
  const [boxId, setBoxId] = useState(null);
  const [fund, setFund] = useState("CUP");
  const [resumen, setResumen] = useState(null);
  const [movs, setMovs] = useState([]);
  const [newName, setNewName] = useState("");
  const [newScope, setNewScope] = useState("personal");
  const [movOpen, setMovOpen] = useState(false);
  const [editMov, setEditMov] = useState(null);
  const [arqueoOpen, setArqueoOpen] = useState(false);
  const [initialOpen, setInitialOpen] = useState(false);
  const [initAmount, setInitAmount] = useState("");
  const [initCounts, setInitCounts] = useState({});
  const [busy, setBusy] = useState(false);

  const box = (boxes || []).find((b) => b.id === boxId) || null;

  const loadBoxes = useCallback(async () => {
    const r = await axios.get(`${API}/cashbox/boxes`, { withCredentials: true });
    setBoxes(r.data);
    if (r.data.length && !r.data.find((b) => b.id === boxId)) setBoxId(r.data[0].id);
  }, [boxId]);
  useEffect(() => { loadBoxes().catch(() => setBoxes([])); }, [loadBoxes]);

  const loadFund = useCallback(async () => {
    if (!boxId) return;
    const [r1, r2] = await Promise.all([
      axios.get(`${API}/cashbox/boxes/${boxId}/resumen`, { params: { fund }, withCredentials: true }),
      axios.get(`${API}/cashbox/boxes/${boxId}/movimientos`, { params: { fund }, withCredentials: true }),
    ]);
    setResumen(r1.data);
    setMovs(r2.data);
  }, [boxId, fund]);
  useEffect(() => { loadFund().catch(() => {}); }, [loadFund]);

  const refresh = () => { loadFund(); loadBoxes(); };

  const createBox = async () => {
    if (newName.trim().length < 2) return toast.error(t("cashbox.nameRequired"));
    setBusy(true);
    try {
      const r = await axios.post(`${API}/cashbox/boxes`,
        { name: newName.trim(), scope: newScope }, { withCredentials: true });
      setNewName("");
      await loadBoxes();
      setBoxId(r.data.id);
      toast.success(t("cashbox.boxCreated"));
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const saveInitial = async () => {
    const amt = parseFloat(initAmount);
    if (isNaN(amt) || amt < 0) return toast.error(t("cashbox.amountRequired"));
    setBusy(true);
    try {
      await axios.post(`${API}/cashbox/boxes/${boxId}/inicial`,
        { fund, amount: amt, denominations: cleanCounts(initCounts) },
        { withCredentials: true });
      toast.success(t("cashbox.initialSaved"));
      setInitialOpen(false); setInitAmount(""); setInitCounts({});
      refresh();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const deleteMov = async (m) => {
    if (!window.confirm(t("cashbox.deleteConfirm"))) return;
    try {
      await axios.delete(`${API}/cashbox/boxes/${boxId}/movimientos/${m.id}`, { withCredentials: true });
      toast.success(t("cashbox.movementDeleted"));
      refresh();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const exportXlsx = async () => {
    try {
      const r = await axios.get(`${API}/cashbox/boxes/${boxId}/export.xlsx`,
        { params: { fund }, responseType: "blob", withCredentials: true });
      const url = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `caja_${fund}.xlsx`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("cashbox.exportDone"));
    } catch { toast.error("Error"); }
  };

  if (boxes === null) return <p className="text-neutral-500 text-sm py-8 text-center">…</p>;

  const byDay = movs.reduce((acc, m) => {
    const d = new Date(m.created_at).toLocaleDateString();
    (acc[d] = acc[d] || []).push(m);
    return acc;
  }, {});

  return (
    <div className="space-y-5" data-testid="cashbox-view">
      <div>
        <h1 className="font-display text-2xl flex items-center gap-2"><Wallet className="w-6 h-6 text-[#8B5CF6]" /> {t("cashbox.title")}</h1>
        <p className="text-sm text-neutral-500">{t("cashbox.subtitle")}</p>
      </div>

      {/* selector de cajas + crear */}
      <div className="flex flex-wrap items-center gap-2" data-testid="cashbox-selector">
        {boxes.map((b) => (
          <button key={b.id} data-testid={`cashbox-chip-${b.id}`} onClick={() => setBoxId(b.id)}
            className={`px-3 h-9 text-xs border flex items-center gap-1.5 transition-colors ${b.id === boxId ? "bg-[#8B5CF6] border-[#8B5CF6] text-white" : "border-white/15 text-neutral-400 hover:text-white"}`}>
            {b.scope === "empresa" && <Building2 className="w-3.5 h-3.5" />}
            {b.name}
          </button>
        ))}
        <div className="flex items-center gap-2">
          <Input data-testid="cashbox-new-name" value={newName} maxLength={60}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && createBox()}
            placeholder={t("cashbox.newBoxPlaceholder")}
            className="rounded-none h-9 bg-[#0a0a0a] border-white/10 w-[190px] text-sm" />
          {isStaff && (
            <select data-testid="cashbox-new-scope" value={newScope} onChange={(e) => setNewScope(e.target.value)}
              className="h-9 bg-[#0a0a0a] border border-white/10 text-xs px-2 text-white">
              <option value="personal">{t("cashbox.scopePersonal")}</option>
              <option value="empresa">{t("cashbox.scopeEmpresa")}</option>
            </select>
          )}
          <Button data-testid="cashbox-create-btn" onClick={createBox} disabled={busy} size="sm"
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9">
            <Plus className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {!box ? (
        <div className="tactile-card p-10 text-center text-neutral-500 text-sm" data-testid="cashbox-empty">
          {t("cashbox.noBoxes")}
        </div>
      ) : (
        <>
          {/* fondos CUP / USD */}
          <div className="flex gap-2" data-testid="cashbox-fund-tabs">
            {["CUP", "USD"].map((f) => (
              <button key={f} data-testid={`cashbox-fund-${f}`} onClick={() => setFund(f)}
                className={`px-5 h-10 text-sm font-bold border transition-colors ${fund === f ? "bg-emerald-600/20 border-emerald-500 text-emerald-300" : "border-white/15 text-neutral-400 hover:text-white"}`}>
                {f} <span className="font-mono text-xs ml-1">{fmt(box.balances?.[f])}</span>
              </button>
            ))}
          </div>

          {/* resumen */}
          {resumen && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="tactile-card p-4" data-testid="cashbox-kpi-balance">
                <p className="micro-label text-neutral-500">{t("cashbox.balance")}</p>
                <p className="font-display text-2xl text-white">{fmt(resumen.balance)} <span className="text-xs text-neutral-500">{fund}</span></p>
                <p className="text-[0.65rem] text-neutral-500">{t("cashbox.initialLabel")}: {fmt(resumen.initial?.amount)}</p>
              </div>
              <div className="tactile-card p-4" data-testid="cashbox-kpi-entradas">
                <p className="micro-label text-neutral-500">{t("cashbox.entradasMes")}</p>
                <p className="font-display text-2xl text-emerald-400">{fmt(resumen.entradas_mes)}</p>
              </div>
              <div className="tactile-card p-4" data-testid="cashbox-kpi-salidas">
                <p className="micro-label text-neutral-500">{t("cashbox.salidasMes")}</p>
                <p className="font-display text-2xl text-red-400">{fmt(resumen.salidas_mes)}</p>
              </div>
              <div className="tactile-card p-4" data-testid="cashbox-kpi-neto">
                <p className="micro-label text-neutral-500">{t("cashbox.netoMes")}</p>
                <p className={`font-display text-2xl ${resumen.neto_mes >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {resumen.neto_mes >= 0 ? "+" : ""}{fmt(resumen.neto_mes)}
                </p>
              </div>
            </div>
          )}

          {/* acciones */}
          <div className="flex flex-wrap gap-2">
            <Button data-testid="cashbox-new-movement-btn" onClick={() => { setEditMov(null); setMovOpen(true); }}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-10">
              <Plus className="w-4 h-4 mr-1" /> {t("cashbox.newMovement")}
            </Button>
            <Button data-testid="cashbox-arqueo-btn" onClick={() => setArqueoOpen(true)} variant="outline"
              className="rounded-none border-white/15 h-10">
              <ClipboardCheck className="w-4 h-4 mr-1" /> {t("cashbox.arqueoTitle")}
            </Button>
            <Button data-testid="cashbox-initial-btn" onClick={() => {
              setInitAmount(String(resumen?.initial?.amount ?? ""));
              setInitCounts(resumen?.initial?.denominations || {});
              setInitialOpen(true);
            }} variant="outline" className="rounded-none border-white/15 h-10">
              {t("cashbox.setInitial")}
            </Button>
            <Button data-testid="cashbox-export-btn" onClick={exportXlsx} variant="outline"
              className="rounded-none border-white/15 h-10">
              <FileDown className="w-4 h-4 mr-1" /> {t("cashbox.exportExcel")}
            </Button>
          </div>

          <div className="grid lg:grid-cols-3 gap-4">
            {/* movimientos por día */}
            <div className="lg:col-span-2 tactile-card p-4" data-testid="cashbox-movements">
              <p className="micro-label text-neutral-500 mb-2">{t("cashbox.movementsTitle")}</p>
              {movs.length === 0 ? (
                <p className="text-sm text-neutral-500 py-6 text-center" data-testid="cashbox-movements-empty">{t("cashbox.noMovements")}</p>
              ) : (
                Object.entries(byDay).map(([day, list]) => (
                  <div key={day} className="mb-3">
                    <p className="text-[0.65rem] uppercase tracking-wider text-neutral-500 border-b border-white/10 pb-1 mb-1">{day}</p>
                    {list.map((m) => (
                      <div key={m.id} className="flex items-center gap-2 py-1.5 border-b border-white/5" data-testid={`cashbox-mov-${m.id}`}>
                        <span className={`font-mono text-sm w-24 shrink-0 ${m.type === "entrada" ? "text-emerald-400" : "text-red-400"}`}>
                          {m.type === "entrada" ? "+" : "−"}{fmt(m.amount)}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm truncate">{m.concept}</p>
                          <p className="text-[0.65rem] text-neutral-500 truncate">
                            {m.responsible && `${m.responsible} · `}{m.created_by_name}
                          </p>
                        </div>
                        <button data-testid={`cashbox-mov-edit-${m.id}`} onClick={() => { setEditMov(m); setMovOpen(true); }}
                          className="text-neutral-500 hover:text-white p-1"><Pencil className="w-3.5 h-3.5" /></button>
                        <button data-testid={`cashbox-mov-delete-${m.id}`} onClick={() => deleteMov(m)}
                          className="text-neutral-500 hover:text-red-400 p-1"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>

            {/* control físico por denominación */}
            <div className="tactile-card p-4" data-testid="cashbox-bill-counter">
              <p className="micro-label text-neutral-500 mb-2">{t("cashbox.billCounterTitle")}</p>
              <table className="w-full text-sm font-mono">
                <tbody>
                  {(resumen?.denominaciones || []).map((r) => (
                    <tr key={r.denom} className="border-b border-white/5" data-testid={`bill-row-${r.denom}`}>
                      <td className="py-1 text-neutral-400">{r.denom} {fund}</td>
                      <td className={`text-right ${r.qty < 0 ? "text-red-400" : ""}`}>{r.qty}×</td>
                      <td className="text-right text-neutral-300">{fmt(r.subtotal)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-[0.65rem] text-neutral-500 mt-2">{t("cashbox.billCounterHint")}</p>
            </div>
          </div>

          <ReportPanel box={box} fund={fund} />
        </>
      )}

      {movOpen && box && (
        <MovementDialog key={editMov?.id || "new"} open={movOpen} onOpenChange={setMovOpen}
          box={box} fund={fund} editMov={editMov} onSaved={refresh} />
      )}
      {box && (
        <ArqueoDialog open={arqueoOpen} onOpenChange={setArqueoOpen}
          box={box} fund={fund} systemBalance={resumen?.balance} onSaved={refresh} />
      )}

      <Dialog open={initialOpen} onOpenChange={setInitialOpen}>
        <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto" data-testid="cashbox-initial-dialog">
          <DialogHeader>
            <DialogTitle className="font-display">{t("cashbox.initialTitle")} — {fund}</DialogTitle>
            <DialogDescription className="text-xs text-neutral-400">{t("cashbox.initialHint")}</DialogDescription>
          </DialogHeader>
          <div>
            <Label className="micro-label text-neutral-500">{t("cashbox.amount")} ({fund})</Label>
            <Input data-testid="initial-amount" type="number" step="any" min="0" value={initAmount}
              onChange={(e) => setInitAmount(e.target.value)}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono" />
          </div>
          <BillInputs fund={fund} counts={initCounts} onChange={setInitCounts} testPrefix="initial-bills" />
          <Button data-testid="initial-save" onClick={saveInitial} disabled={busy}
            className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none h-11">
            {busy ? "…" : t("cashbox.save")}
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
