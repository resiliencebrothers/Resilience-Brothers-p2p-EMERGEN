/**
 * iter88 — ExportCsvDialog
 *
 * Small modal that lets the admin pick an optional date range (since/until)
 * and downloads the company-funds movements as a CSV. Empty range = export
 * the whole history.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import axios from "axios";
import { toast } from "sonner";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Download } from "lucide-react";
import QuickDateRange from "@/components/QuickDateRange";

export default function ExportCsvDialog({ open, onOpenChange }) {
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
      const url = `${API}/admin/company-funds/export.csv?${params.toString()}`;
      const r = await axios.get(url, { responseType: "blob", withCredentials: true });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: r.headers["content-type"] }));
      const a = document.createElement("a");
      a.href = blobUrl;
      const ts = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      a.download = `company_funds_${ts}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success(t("admin.companyFunds.exportedToast"));
      onOpenChange(false);
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.companyFunds.exportError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="cw-export-dialog"
        className="bg-[#0c0c0c] border border-white/10 text-white max-w-md rounded-none"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Download className="w-5 h-5 text-[#8B5CF6]" />
            {t("admin.companyFunds.exportTitle")}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("admin.companyFunds.exportSub")}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="micro-label text-neutral-500">
              {t("admin.companyFunds.exportSince")}
            </Label>
            <Input
              data-testid="cw-export-since"
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="rounded-none bg-[#0a0a0a] border-white/10 h-10 mt-1 font-mono text-xs"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">
              {t("admin.companyFunds.exportUntil")}
            </Label>
            <Input
              data-testid="cw-export-until"
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
          testIdPrefix="cw-export-quick"
          className="pt-1"
        />
        <div className="text-[0.65rem] text-neutral-500 font-mono mt-2">
          {t("admin.companyFunds.exportHint")}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            className="rounded-none text-neutral-400 hover:text-white hover:bg-white/5"
          >
            {t("admin.companyFunds.cancel")}
          </Button>
          <Button
            data-testid="cw-export-download"
            disabled={busy}
            onClick={download}
            className="rounded-none bg-[#8B5CF6] hover:bg-[#8B5CF6]/90 text-white font-mono text-xs uppercase tracking-wider"
          >
            <Download className="w-3.5 h-3.5 mr-2" />
            {busy ? t("admin.companyFunds.exportWorking") : t("admin.companyFunds.exportDo")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
