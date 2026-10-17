// TOOLS-02 — barra de escenarios guardados de la calculadora de rentabilidad.
// Privados por cuenta: guardar el estado actual, cargar, renombrar, borrar.
import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Save, FolderOpen, Pencil, Trash2, Check, X } from "lucide-react";

export default function ProfitScenariosBar({ calc, setCalc }) {
  const { t } = useTranslation();
  const [list, setList] = useState([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState("");

  const load = useCallback(() => {
    axios.get(`${API}/profit/scenarios`, { withCredentials: true })
      .then((r) => setList(r.data || [])).catch(() => setList([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (name.trim().length < 1) return toast.error(t("tools.scenarios.nameRequired"));
    setBusy(true);
    try {
      await axios.post(`${API}/profit/scenarios`, { name: name.trim(), calc },
        { withCredentials: true });
      setName(""); load();
      toast.success(t("tools.scenarios.saved"));
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
    finally { setBusy(false); }
  };

  const loadScenario = (s) => {
    setCalc({ ...s.calc });
    toast.success(t("tools.scenarios.loaded", { name: s.name }));
  };

  const overwrite = async (s) => {
    try {
      await axios.put(`${API}/profit/scenarios/${s.id}`, { calc },
        { withCredentials: true });
      load();
      toast.success(t("tools.scenarios.updated"));
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const rename = async (id) => {
    if (editName.trim().length < 1) return;
    try {
      await axios.put(`${API}/profit/scenarios/${id}`, { name: editName.trim() },
        { withCredentials: true });
      setEditingId(null); load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  const remove = async (id) => {
    if (!window.confirm(t("tools.scenarios.deleteConfirm"))) return;
    try {
      await axios.delete(`${API}/profit/scenarios/${id}`, { withCredentials: true });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Error"); }
  };

  return (
    <div className="tactile-card p-4 space-y-3" data-testid="profit-scenarios-bar">
      <div className="flex items-center gap-2">
        <FolderOpen className="w-4 h-4 text-[#8B5CF6]" />
        <p className="micro-label text-neutral-400">{t("tools.scenarios.title")}</p>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <Input data-testid="scenario-name-input" value={name} maxLength={60}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          placeholder={t("tools.scenarios.namePlaceholder")}
          className="rounded-none h-9 bg-[#0a0a0a] border-white/10 w-[220px] text-sm" />
        <Button data-testid="scenario-save-btn" onClick={save} disabled={busy} size="sm"
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-9">
          <Save className="w-4 h-4 mr-1" /> {t("tools.scenarios.save")}
        </Button>
      </div>
      {list.length === 0 ? (
        <p className="text-xs text-neutral-500" data-testid="scenario-empty">
          {t("tools.scenarios.empty")}
        </p>
      ) : (
        <div className="flex flex-wrap gap-2" data-testid="scenario-list">
          {list.map((s) => (
            <div key={s.id} data-testid={`scenario-item-${s.id}`}
              className="flex items-center gap-0.5 border border-white/10 bg-white/[0.03] pl-1">
              {editingId === s.id ? (
                <>
                  <Input autoFocus value={editName} maxLength={60}
                    onChange={(e) => setEditName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && rename(s.id)}
                    className="rounded-none h-8 bg-[#0a0a0a] border-white/10 w-[140px] text-xs" />
                  <button onClick={() => rename(s.id)} data-testid={`scenario-rename-save-${s.id}`}
                    className="px-1.5 text-emerald-400 hover:text-emerald-300"><Check className="w-3.5 h-3.5" /></button>
                  <button onClick={() => setEditingId(null)}
                    className="px-1.5 text-neutral-400 hover:text-white"><X className="w-3.5 h-3.5" /></button>
                </>
              ) : (
                <>
                  <button onClick={() => loadScenario(s)} data-testid={`scenario-load-${s.id}`}
                    className="px-2.5 h-8 text-xs text-neutral-200 hover:text-white">{s.name}</button>
                  <button onClick={() => overwrite(s)} title={t("tools.scenarios.overwrite")}
                    data-testid={`scenario-overwrite-${s.id}`}
                    className="px-1.5 text-neutral-500 hover:text-[#A78BFA]"><Save className="w-3 h-3" /></button>
                  <button onClick={() => { setEditingId(s.id); setEditName(s.name); }}
                    data-testid={`scenario-rename-${s.id}`}
                    className="px-1.5 text-neutral-500 hover:text-white"><Pencil className="w-3 h-3" /></button>
                  <button onClick={() => remove(s.id)} data-testid={`scenario-delete-${s.id}`}
                    className="px-1.5 text-neutral-500 hover:text-red-400"><Trash2 className="w-3 h-3" /></button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
