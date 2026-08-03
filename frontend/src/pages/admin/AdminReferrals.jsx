import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import TotpPromptDialog from "@/components/TotpPromptDialog";
import { Gift, Trophy, RefreshCw, Percent } from "lucide-react";

const MEDALS = ["text-amber-400", "text-neutral-300", "text-amber-700"];

export default function AdminReferrals() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [pctInput, setPctInput] = useState("");
  const [totpOpen, setTotpOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/referrals/leaderboard`);
      setData(res.data);
      setPctInput(String(res.data.bonus_pct));
    } catch {
      toast.error(t("adminReferrals.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const savePct = async (totpCode) => {
    const pct = parseFloat(pctInput);
    if (Number.isNaN(pct) || pct < 0 || pct > 100) {
      toast.error(t("adminReferrals.saveError"));
      return;
    }
    setSaving(true);
    try {
      await axios.put(`${API}/admin/settings`, {
        referral_bonus_pct: pct,
        totp_code: totpCode,
      });
      toast.success(t("adminReferrals.saved", { pct }));
      setTotpOpen(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || t("adminReferrals.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const items = data?.items || [];

  return (
    <div className="space-y-6" data-testid="admin-referrals-view">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-display text-2xl flex items-center gap-2">
            <Gift className="w-6 h-6 text-violet-400" />
            {t("adminReferrals.title")}
          </h1>
          <p className="text-sm text-neutral-500 mt-1">{t("adminReferrals.subtitle")}</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading} data-testid="admin-referrals-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {isAdmin && (
        <div className="tactile-card p-6" data-testid="referral-config-card">
          <h2 className="font-display text-lg mb-1 flex items-center gap-2">
            <Percent className="w-5 h-5 text-violet-400" />
            {t("adminReferrals.configTitle")}
          </h2>
          <p className="text-xs text-neutral-500 mb-4">{t("adminReferrals.configHint")}</p>
          <div className="flex items-end gap-3 flex-wrap">
            <div>
              <Label htmlFor="referral-pct" className="text-xs text-neutral-400">
                {t("adminReferrals.pctLabel")}
              </Label>
              <Input
                id="referral-pct"
                data-testid="referral-pct-input"
                type="number"
                min="0"
                max="100"
                step="0.5"
                value={pctInput}
                onChange={(e) => setPctInput(e.target.value)}
                className="w-32 mt-1"
              />
            </div>
            <Button
              data-testid="referral-pct-save-btn"
              onClick={() => setTotpOpen(true)}
              disabled={saving || pctInput === ""}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white"
            >
              {t("adminReferrals.save")}
            </Button>
          </div>
        </div>
      )}

      <div className="tactile-card p-6" data-testid="referral-leaderboard-card">
        <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
          <h2 className="font-display text-lg flex items-center gap-2">
            <Trophy className="w-5 h-5 text-amber-400" />
            {t("adminReferrals.leaderboardTitle")}
          </h2>
          {data && (
            <div className="text-xs text-neutral-500">
              Total: <span className="text-emerald-400 font-semibold">{data.total_paid_usdt} USDT</span>
              {" · "}{data.bonus_pct}%
            </div>
          )}
        </div>
        {items.length === 0 ? (
          <p className="text-sm text-neutral-500" data-testid="referral-leaderboard-empty">
            {t("adminReferrals.empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-neutral-500 border-b border-white/10">
                  <th className="py-2 pr-3">{t("adminReferrals.colRank")}</th>
                  <th className="py-2 pr-3">{t("adminReferrals.colUser")}</th>
                  <th className="py-2 pr-3 text-right">{t("adminReferrals.colReferred")}</th>
                  <th className="py-2 pr-3 text-right">{t("adminReferrals.colActivated")}</th>
                  <th className="py-2 pr-3 text-right">{t("adminReferrals.colEarned")}</th>
                  <th className="py-2">{t("adminReferrals.colLast")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row, i) => (
                  <tr
                    key={row.referrer_user_id}
                    className="border-b border-white/5"
                    data-testid={`leaderboard-row-${i}`}
                  >
                    <td className="py-2.5 pr-3">
                      {i < 3
                        ? <Trophy className={`w-4 h-4 ${MEDALS[i]}`} />
                        : <span className="text-neutral-500">{i + 1}</span>}
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="font-medium">{row.name || "—"}</div>
                      <div className="text-xs text-neutral-500">{row.email}</div>
                    </td>
                    <td className="py-2.5 pr-3 text-right">{row.referred_count}</td>
                    <td className="py-2.5 pr-3 text-right">{row.activated_count}</td>
                    <td className="py-2.5 pr-3 text-right text-emerald-400 font-semibold">
                      {row.total_bonus_usdt} USDT
                    </td>
                    <td className="py-2.5 text-xs text-neutral-500">
                      {(row.last_bonus_at || "").slice(0, 10) || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <TotpPromptDialog
        open={totpOpen}
        title={t("adminReferrals.totpTitle")}
        description={t("adminReferrals.totpDesc")}
        onConfirm={savePct}
        onCancel={() => setTotpOpen(false)}
      />
    </div>
  );
}
