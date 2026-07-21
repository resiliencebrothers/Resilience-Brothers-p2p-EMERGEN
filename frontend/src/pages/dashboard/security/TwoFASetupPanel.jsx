import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Copy } from "lucide-react";

export default function TwoFASetupPanel({ setupData, verifyCode, onVerifyCodeChange, onVerify, busy, onCopy }) {
  const { t } = useTranslation();
  return (
    <div className="tactile-card p-6" data-testid="security-setup-panel">
      <h2 className="font-display text-xl mb-4">{t("security.setup.step1")}</h2>
      <div className="flex flex-col sm:flex-row gap-6">
        <div className="bg-white p-3 rounded">
          <img src={setupData.qr_data_url} alt={t("security.setup.qrAlt")} className="w-48 h-48" />
        </div>
        <div className="flex-1 space-y-3 text-sm">
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("security.setup.recommendedApps")}</div>
            <div className="text-neutral-300">{t("security.setup.recommendedAppsValue")}</div>
          </div>
          <div>
            <div className="micro-label text-neutral-500 mb-1">{t("security.setup.cantScan")}</div>
            <div className="flex items-center gap-2 font-mono text-xs bg-[#0a0a0a] border border-white/10 p-2">
              <code className="flex-1 break-all" data-testid="security-manual-secret">{setupData.secret}</code>
              <button onClick={() => onCopy(setupData.secret)}>
                <Copy className="w-3.5 h-3.5 text-neutral-400" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <h2 className="font-display text-xl mt-6 mb-3">{t("security.setup.step2")}</h2>
      <div className="flex gap-3 items-center">
        <Input
          data-testid="security-verify-input"
          maxLength={6}
          value={verifyCode}
          onChange={(e) => onVerifyCodeChange(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder={t("security.setup.verifyPlaceholder")}
          className="rounded-none bg-[#0a0a0a] border-white/10 h-12 w-32 font-mono text-center text-xl tracking-widest"
        />
        <Button
          data-testid="security-verify-btn"
          onClick={onVerify}
          disabled={busy || verifyCode.length !== 6}
          className="rounded-none bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold h-12 px-6 uppercase tracking-wider text-xs"
        >
          {busy ? t("security.setup.verifying") : t("security.setup.activate")}
        </Button>
      </div>
    </div>
  );
}
