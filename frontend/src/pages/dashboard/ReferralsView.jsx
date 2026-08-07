import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { ShareAppButton } from "@/components/ShareAppButton";
import { QrShareButton } from "@/components/QrShareButton";
import { Gift, Copy, Check, Users, Zap, Coins, TrendingUp } from "lucide-react";

function StatCard({ icon: Icon, label, value, testid }) {
  return (
    <div className="tactile-card p-4 flex items-center gap-3" data-testid={testid}>
      <div className="w-10 h-10 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center shrink-0">
        <Icon className="w-5 h-5 text-violet-400" />
      </div>
      <div className="min-w-0">
        <div className="font-display text-xl leading-tight truncate">{value}</div>
        <div className="text-xs text-neutral-500">{label}</div>
      </div>
    </div>
  );
}

function HowStep({ n, text }) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-6 h-6 rounded-full bg-violet-500/15 border border-violet-500/30 text-violet-300 text-xs font-semibold flex items-center justify-center shrink-0 mt-0.5">
        {n}
      </div>
      <p className="text-sm text-neutral-400 leading-relaxed">{text}</p>
    </div>
  );
}

export default function ReferralsView() {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/referrals/me`);
      setData(res.data);
    } catch {
      toast.error(t("referrals.loadError"));
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const code = data?.referral_code || "";
  const pct = data?.bonus_pct ?? 10;
  const shareUrl = `${window.location.origin}/?ref=${code}`;

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast.success(t("referrals.codeCopied"));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("common.shareLinkError"));
    }
  };

  return (
    <div className="space-y-6" data-testid="referrals-view">
      <div>
        <h1 className="font-display text-2xl flex items-center gap-2">
          <Gift className="w-6 h-6 text-violet-400" />
          {t("referrals.title")}
        </h1>
        <p className="text-sm text-neutral-500 mt-1">
          {t("referrals.subtitle", { pct })}
        </p>
      </div>

      <div className="tactile-card p-6" data-testid="referral-code-card">
        <div className="text-xs uppercase tracking-widest text-neutral-500 mb-3">
          {t("referrals.yourCode")}
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div
            className="font-display text-3xl tracking-[0.2em] text-violet-300 border border-dashed border-violet-500/40 rounded-lg px-6 py-3 bg-violet-500/5 text-center"
            data-testid="referral-code-value"
          >
            {code || "······"}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              data-testid="referral-copy-btn"
              variant="outline"
              onClick={copyCode}
              disabled={!code}
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              <span className="ml-2">{t("referrals.copyCode")}</span>
            </Button>
            <ShareAppButton
              testid="referral-share-btn"
              url={shareUrl}
              text={t("referrals.shareText", { code })}
              label={t("referrals.shareBtn")}
              variant="default"
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white"
            />
            <QrShareButton
              testid="referral-qr-btn"
              url={shareUrl}
              label={t("qrShare.button")}
              variant="outline"
              posterCode={code || ""}
            />
          </div>
        </div>
        <div className="mt-3 text-xs text-neutral-600 break-all" data-testid="referral-share-url">
          {code ? shareUrl : ""}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard icon={Users} label={t("referrals.statReferred")}
          value={data?.referred_count ?? "—"} testid="referral-stat-referred" />
        <StatCard icon={Zap} label={t("referrals.statActivated")}
          value={data?.activated_count ?? "—"} testid="referral-stat-activated" />
        <StatCard icon={Coins} label={t("referrals.statEarned")}
          value={data ? `${data.total_bonus_usdt} USDT` : "—"} testid="referral-stat-earned" />
      </div>

      <div className="tactile-card p-6" data-testid="referral-how-card">
        <h2 className="font-display text-lg mb-4">{t("referrals.howTitle")}</h2>
        <div className="space-y-3">
          <HowStep n={1} text={t("referrals.how1")} />
          <HowStep n={2} text={t("referrals.how2")} />
          <HowStep n={3} text={t("referrals.how3", { pct })} />
        </div>
      </div>

      <div className="tactile-card p-6" data-testid="referral-history-card">
        <h2 className="font-display text-lg mb-4 flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-emerald-400" />
          {t("referrals.historyTitle")}
        </h2>
        {(data?.bonuses || []).length === 0 ? (
          <p className="text-sm text-neutral-500" data-testid="referral-history-empty">
            {t("referrals.historyEmpty")}
          </p>
        ) : (
          <div className="space-y-2">
            {data.bonuses.map((b) => (
              <div
                key={b.id}
                className="flex items-center justify-between gap-3 border border-white/5 rounded-lg px-4 py-3"
                data-testid={`referral-bonus-row-${b.id}`}
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {t("referrals.bonusFrom", { name: b.referred_name || "—" })}
                  </div>
                  <div className="text-xs text-neutral-500">
                    {(b.created_at || "").slice(0, 10)} · {b.pct_applied}%
                  </div>
                </div>
                <div className="text-emerald-400 font-semibold whitespace-nowrap">
                  +{b.bonus_usdt} USDT
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
