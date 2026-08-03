import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Share2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * iter112 — "Compartir app" button. Uses the native Web Share sheet on
 * mobile (WhatsApp, Telegram, SMS…) and falls back to copying the link
 * on desktop browsers without navigator.share.
 */
export const ShareAppButton = ({
  url,
  text = "",
  label,
  variant = "outline",
  className = "",
  testid = "share-app-btn",
}) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const onShare = async () => {
    const payload = { title: "Resilience Brothers P2P", text, url };
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share(payload);
        return;
      } catch (e) {
        if (e?.name === "AbortError") return;
      }
    }
    try {
      await navigator.clipboard.writeText(text ? `${text} ${url}` : url);
      setCopied(true);
      toast.success(t("common.shareLinkCopied"));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("common.shareLinkError"));
    }
  };

  return (
    <Button
      data-testid={testid}
      variant={variant}
      onClick={onShare}
      className={className}
      title={label || t("landing.shareApp")}
      aria-label={label || t("landing.shareApp")}
    >
      {copied ? <Check className="w-4 h-4" /> : <Share2 className="w-4 h-4" />}
      {label ? <span className="ml-2">{label}</span> : null}
    </Button>
  );
};
