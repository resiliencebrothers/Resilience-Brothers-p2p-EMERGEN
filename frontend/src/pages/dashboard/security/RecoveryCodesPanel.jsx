import { Trans, useTranslation } from "react-i18next";
import { AlertTriangle, Copy } from "lucide-react";

export default function RecoveryCodesPanel({ recoveryCodes, onCopy, onAcknowledged }) {
  const { t } = useTranslation();
  return (
    <div className="border border-[#8B5CF6]/40 bg-[#8B5CF6]/5 p-5" data-testid="security-recovery-codes">
      <div className="flex items-start gap-3 mb-3">
        <AlertTriangle className="w-5 h-5 text-[#8B5CF6] mt-0.5" />
        <div>
          <div className="font-semibold text-[#8B5CF6]">{t("security.recovery.title")}</div>
          <div className="text-xs text-neutral-400 mt-1">
            <Trans i18nKey="security.recovery.warning" components={{ 1: <strong /> }} />
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 font-mono text-sm">
        {recoveryCodes.map((c) => (
          <div key={c} className="bg-[#0a0a0a] border border-white/10 px-3 py-2 flex items-center justify-between">
            <code>{c}</code>
            <button onClick={() => onCopy(c)}><Copy className="w-3 h-3 text-neutral-500" /></button>
          </div>
        ))}
      </div>
      <div className="flex justify-end mt-3 gap-2">
        <button onClick={() => onCopy(recoveryCodes.join("\n"))} className="text-xs text-[#8B5CF6] underline">
          {t("security.recovery.copyAll")}
        </button>
        <button
          onClick={onAcknowledged}
          data-testid="security-codes-acknowledged"
          className="text-xs text-neutral-500 hover:text-white underline"
        >
          {t("security.recovery.acknowledged")}
        </button>
      </div>
    </div>
  );
}
