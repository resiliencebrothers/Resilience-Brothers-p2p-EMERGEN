import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { CheckCircle2, RefreshCw, ShieldAlert } from "lucide-react";

export default function TwoFAStatusCard({ status, busy, hasSetupData, onStartSetup, onRegen, onDisable }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card p-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          {status?.enabled ? (
            <>
              <CheckCircle2 className="w-6 h-6 text-[#22C55E]" />
              <div>
                <div className="text-white font-semibold" data-testid="security-status">{t("security.statusOn")}</div>
                <div className="text-xs text-neutral-500">
                  {t("security.statusOnDetails", {
                    date: status.setup_at ? new Date(status.setup_at).toLocaleDateString() : "—",
                    count: status.recovery_codes_remaining || 0,
                  })}
                </div>
              </div>
            </>
          ) : (
            <>
              <ShieldAlert className="w-6 h-6 text-[#8B5CF6]" />
              <div>
                <div className="text-white font-semibold" data-testid="security-status">{t("security.statusOff")}</div>
                <div className="text-xs text-neutral-500">{t("security.statusOffHint")}</div>
              </div>
            </>
          )}
        </div>
        {!status?.enabled && !hasSetupData && (
          <Button
            data-testid="security-setup-btn"
            onClick={onStartSetup}
            disabled={busy}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-10 px-4 uppercase tracking-wider text-xs"
          >
            {busy ? t("security.buttonLoading") : t("security.activate2fa")}
          </Button>
        )}
        {status?.enabled && (
          <div className="flex gap-2">
            <Button
              data-testid="security-regen-btn"
              onClick={onRegen}
              className="rounded-none bg-transparent border border-white/15 hover:border-[#8B5CF6]/60 text-white h-10 px-3 uppercase tracking-wider text-xs"
            >
              <RefreshCw className="w-3.5 h-3.5 mr-2" /> {t("security.regenerateCodes")}
            </Button>
            <Button
              data-testid="security-disable-btn"
              onClick={onDisable}
              className="rounded-none bg-transparent border border-[#EF4444]/40 hover:bg-[#EF4444]/10 text-[#EF4444] h-10 px-3 uppercase tracking-wider text-xs"
            >
              {t("security.deactivate")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
