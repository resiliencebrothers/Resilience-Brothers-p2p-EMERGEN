import { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Save } from "lucide-react";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

const NUMBER_FIELDS = [
  "auto_match_score", "manual_review_score", "minimum_score_difference",
  "date_window_days", "amount_tolerance_pct", "max_auto_confirmation_amount",
];
const SWITCH_FIELDS = ["auto_match_enabled", "require_exact_amount", "enable_ocr"];

export default function ConfigTab() {
  const { t } = useTranslation();
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    axios.get(`${API}/admin/reconciliation/config`, { withCredentials: true })
      .then((r) => setCfg(r.data))
      .catch(() => {});
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await axios.put(`${API}/admin/reconciliation/config`, cfg, { withCredentials: true });
      setCfg(r.data);
      toast.success(t("reconciliation.config.saved"));
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    } finally { setSaving(false); }
  };

  if (!cfg) return <div className="tactile-card p-6 animate-pulse text-neutral-500">…</div>;

  return (
    <div className="tactile-card p-5 max-w-2xl space-y-5" data-testid="reconciliation-config-tab">
      {SWITCH_FIELDS.map((f) => (
        <div key={f} className="flex items-center justify-between border border-white/10 bg-white/[0.02] p-3">
          <div>
            <div className="text-sm text-white">{t(`reconciliation.config.${f}`)}</div>
            <div className="text-xs text-neutral-500">{t(`reconciliation.config.${f}Hint`)}</div>
          </div>
          <Switch
            data-testid={`recon-config-${f}`}
            checked={!!cfg[f]}
            onCheckedChange={(v) => setCfg({ ...cfg, [f]: v })}
          />
        </div>
      ))}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {NUMBER_FIELDS.map((f) => (
          <div key={f} className="space-y-1.5">
            <label className="text-xs text-neutral-400 uppercase tracking-wider">
              {t(`reconciliation.config.${f}`)}
            </label>
            <Input
              data-testid={`recon-config-${f}`}
              type="number"
              step="0.1"
              value={cfg[f] ?? ""}
              onChange={(e) => setCfg({ ...cfg, [f]: e.target.value })}
              className="rounded-none bg-[#0a0a0a] border-white/10 font-mono"
            />
          </div>
        ))}
      </div>
      <p className="text-[11px] text-neutral-500">{t("reconciliation.config.hint")}</p>
      <Button
        data-testid="recon-config-save"
        onClick={save}
        disabled={saving}
        className="rounded-none bg-violet-600 hover:bg-violet-500 text-white"
      >
        <Save className="w-4 h-4 mr-2" /> {t("reconciliation.config.save")}
      </Button>
    </div>
  );
}
