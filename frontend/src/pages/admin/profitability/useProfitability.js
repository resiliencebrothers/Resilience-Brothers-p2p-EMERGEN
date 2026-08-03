// iter113 — data hook for the profitability calculator tab.
import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { API } from "@/App";

const DEFAULT_CALC = {
  mode: "combined",
  pairId: "", fromCode: "", toCode: "",
  sell: "", buy: "", buyPct: "", sellPct: "",
  qty: "1", opsPerDay: "10", daysPerMonth: "26",
};

export function useProfitability() {
  const { t } = useTranslation();
  const [rates, setRates] = useState([]);
  const [currencies, setCurrencies] = useState([]);
  const [settings, setSettings] = useState({});
  const [operations, setOperations] = useState([]);
  const [totals, setTotals] = useState(null);
  const [calc, setCalc] = useState(DEFAULT_CALC);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [opDialogOpen, setOpDialogOpen] = useState(false);

  const loadOperations = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/admin/profitability/operations`, { withCredentials: true });
      setOperations(r.data.items || []);
      setTotals(r.data.totals || null);
    } catch {
      toast.error(t("common.loadError", "Error al cargar datos"));
    }
  }, [t]);

  const load = useCallback(async () => {
    try {
      const [r, c, s] = await Promise.all([
        axios.get(`${API}/rates`, { withCredentials: true }),
        axios.get(`${API}/currencies`, { withCredentials: true }),
        axios.get(`${API}/admin/profitability/settings`, { withCredentials: true }),
      ]);
      setRates((r.data || []).map((x) => ({ ...x, id: x.id || `${x.from_code}-${x.to_code}` })));
      setCurrencies((c.data || []).filter((x) => x.is_active !== false));
      const map = {};
      (s.data.items || []).forEach((it) => { map[it.currency] = it; });
      setSettings(map);
    } catch {
      toast.error(t("common.loadError", "Error al cargar datos"));
    }
    loadOperations();
  }, [loadOperations, t]);

  useEffect(() => { load(); }, [load]);

  const pctFor = useCallback(
    (code) => settings[(code || "").trim().toUpperCase()] || { buy_pct: 0, sell_pct: 0 },
    [settings]
  );

  const loadPairIntoCalc = useCallback((row) => {
    setCalc((prev) => ({
      ...prev,
      pairId: row.pairId || "",
      fromCode: row.fromCode || "",
      toCode: row.toCode || "",
      sell: row.sell === null || row.sell === undefined ? "" : String(row.sell),
      buy: row.buy === null || row.buy === undefined ? "" : String(row.buy),
      buyPct: row.buyPct === null || row.buyPct === undefined ? "" : String(row.buyPct),
      sellPct: row.sellPct === null || row.sellPct === undefined ? "" : String(row.sellPct),
    }));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const saveSettings = useCallback(async (items) => {
    const r = await axios.put(`${API}/admin/profitability/settings`, { items }, { withCredentials: true });
    const map = {};
    (r.data.items || []).forEach((it) => { map[it.currency] = it; });
    setSettings((prev) => ({ ...prev, ...map }));
    toast.success(t("profitability.settings.saved"));
  }, [t]);

  const createOperation = useCallback(async (payload) => {
    await axios.post(`${API}/admin/profitability/operations`, payload, { withCredentials: true });
    toast.success(t("profitability.dialog.saved"));
    loadOperations();
  }, [loadOperations, t]);

  const deleteOperation = useCallback(async (id) => {
    try {
      await axios.delete(`${API}/admin/profitability/operations/${id}`, { withCredentials: true });
      toast.success(t("profitability.ops.deleted"));
      loadOperations();
    } catch {
      toast.error(t("profitability.ops.deleteFailed"));
    }
  }, [loadOperations, t]);

  return {
    rates, currencies, settings, operations, totals,
    calc, setCalc, pctFor, loadPairIntoCalc,
    settingsOpen, setSettingsOpen, opDialogOpen, setOpDialogOpen,
    saveSettings, createOperation, deleteOperation,
  };
}
