import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Upload } from "lucide-react";

export default function SenderAndProof({
  senderName, onSenderNameChange,
  proofImage, onProofFile,
}) {
  const { t } = useTranslation();
  return (
    <>
      <div>
        <Label className="micro-label text-neutral-500">
          {t("exchange.senderNameLabel")} <span className="text-[#8B5CF6]">*</span>
        </Label>
        <Input
          data-testid="sender-name-input"
          value={senderName}
          onChange={(e) => onSenderNameChange(e.target.value)}
          placeholder={t("exchange.senderNamePlaceholder")}
          className="rounded-none mt-2 bg-[#0a0a0a] border-white/10 h-12"
          required
        />
        <p className="text-[0.65rem] text-neutral-600 mt-1">{t("exchange.senderNameHint")}</p>
      </div>

      <div>
        <Label className="micro-label text-neutral-500">{t("exchange.proofLabel")}</Label>
        <label className="block mt-2 border-2 border-dashed border-white/15 hover:border-[#8B5CF6] p-6 cursor-pointer transition-colors">
          <input type="file" accept="image/*" onChange={onProofFile} className="hidden" data-testid="proof-upload" />
          {proofImage ? (
            <img src={proofImage} alt="proof" className="max-h-40 mx-auto" />
          ) : (
            <div className="text-center">
              <Upload className="w-8 h-8 text-neutral-500 mx-auto mb-2" />
              <p className="text-sm text-neutral-400">{t("exchange.uploadCta")}</p>
              <p className="text-xs text-neutral-600 mt-1">{t("exchange.uploadHint2")}</p>
            </div>
          )}
        </label>
      </div>
    </>
  );
}
