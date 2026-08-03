// iter114 — export the operations log as an investor-ready PDF.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import axios from "axios";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { FileDown } from "lucide-react";
import QuickDateRange from "@/components/QuickDateRange";

export default function ProfitabilityPdfDialog({ open, onOpenChange }) {
  const { t } = useTranslation();
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (since) params.set("since", since);
      if (until) params.set("until", until);
      const r = await axios.get(`${API}/admin/profitability/operations.pdf?${params.toString()}`, {
        responseType: "blob", withCredentials: true,
      });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const slug = since && until ? `${since}_${until}` : (since || until || "historico");
      a.download = `rentabilidad_${slug}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("profitability.pdf.exportedToast"));
      onOpenChange(false);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("profitability.pdf.exportError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="profit-pdf-dialog"
        className="bg-[#0c0c0c] border border-white/10 text-white max-w-md max-h-[85vh] overflow-y-auto rounded-none"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileDown className="w-5 h-5 text-[#8B5CF6]" />
            {t("profitability.pdf.title")}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("profitability.pdf.description")}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="micro-label text-neutral-500">{t("profitability.pdf.since")}</Label>
            <Input
              data-testid="profit-pdf-since"
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 mt-1 font-mono text-xs"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("profitability.pdf.until")}</Label>
            <Input
              data-testid="profit-pdf-until"
              type="date"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 mt-1 font-mono text-xs"
            />
          </div>
        </div>
        <QuickDateRange
          since={since}
          until={until}
          onRangeChange={({ since: s, until: u }) => { setSince(s); setUntil(u); }}
          testIdPrefix="profit-pdf-quick"
          className="pt-1"
        />
        <div className="text-[0.65rem] text-neutral-500 font-mono mt-2">
          {t("profitability.pdf.hint")}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            className="rounded-none text-neutral-400 hover:text-white hover:bg-white/5"
          >
            {t("profitability.pdf.cancel")}
          </Button>
          <Button
            data-testid="profit-pdf-download"
            disabled={busy}
            onClick={download}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white font-mono text-xs uppercase tracking-wider"
          >
            <FileDown className="w-3.5 h-3.5 mr-2" />
            {busy ? t("profitability.pdf.working") : t("profitability.pdf.download")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
