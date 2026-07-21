/**
 * iter85 — BulkImportDialog
 *
 * Bulk-import dialog with two views:
 *   1. Input view: example paste + textarea + Import button.
 *   2. Result view: 3-tile summary (imported / skipped / invalid) +
 *      warning about affected active accounts + list of invalid entries.
 */
import { useTranslation, Trans } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Upload, CheckCircle2, AlertTriangle, SkipForward } from "lucide-react";

export default function BulkImportDialog({
  importOpen, setImportOpen,
  importText, setImportText,
  importing, importResult,
  onSubmit, onReset,
}) {
  const { t } = useTranslation();
  return (
    <Dialog
      open={importOpen}
      onOpenChange={(o) => { if (!o) onReset(); else setImportOpen(true); }}
    >
      <DialogContent
        data-testid="bulk-import-dialog"
        className="bg-[#14101F] border-white/10 text-white rounded-none max-w-2xl max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl flex items-center gap-2">
            <Upload className="w-6 h-6 text-[#8B5CF6]" /> {t("admin.blocked.importDialogTitle")}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("admin.blocked.importDesc")}
          </DialogDescription>
        </DialogHeader>
        {!importResult ? (
          <ImportInputView
            importText={importText}
            setImportText={setImportText}
            importing={importing}
            onSubmit={onSubmit}
            onReset={onReset}
            t={t}
          />
        ) : (
          <ImportResultView importResult={importResult} onReset={onReset} t={t} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ImportInputView({ importText, setImportText, importing, onSubmit, onReset, t }) {
  return (
    <div className="space-y-4">
      <div className="bg-[#0F0F0F] border border-white/5 p-3 text-[0.7rem] text-neutral-500 font-mono leading-relaxed">
        <div className="text-[0.65rem] text-neutral-400 mb-2 font-sans uppercase tracking-wider">
          {t("admin.blocked.exampleTitle")}
        </div>
        Estafador ❌️<br />
        +5359804084<br />
        +5356455618<br />
        📌Son la misma persona<br />
        📌Se hace pasar por Remesero<br />
        <br />
        Juan Pérez<br />
        +1-305-555-1234<br />
        📌Estafó $500 en venta USDT
      </div>
      <div>
        <Label className="micro-label text-neutral-500">
          {t("admin.blocked.importListLabel")}
        </Label>
        <Textarea
          data-testid="bulk-import-textarea"
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder={t("admin.blocked.importPh")}
          className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[280px] font-mono text-xs"
        />
      </div>
      <div className="flex justify-between items-center pt-2">
        <span className="text-[0.65rem] text-neutral-600">
          {t("admin.blocked.importFooter")}
        </span>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onReset} className="rounded-none">
            {t("admin.blocked.cancel")}
          </Button>
          <Button
            data-testid="bulk-import-submit"
            onClick={onSubmit}
            disabled={importing || !importText.trim()}
            className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none"
          >
            {importing ? t("admin.blocked.importing") : t("admin.blocked.importBtn")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ImportResultView({ importResult, onReset, t }) {
  return (
    <div className="space-y-4" data-testid="bulk-import-result">
      <div className="grid grid-cols-3 gap-2">
        <ResultTile
          icon={<CheckCircle2 className="w-6 h-6 mx-auto text-[#22C55E] mb-1" />}
          value={importResult.imported_count}
          testId="import-count-imported"
          label={t("admin.blocked.imported")}
          tone="text-[#22C55E]"
        />
        <ResultTile
          icon={<SkipForward className="w-6 h-6 mx-auto text-[#8B5CF6] mb-1" />}
          value={importResult.skipped_count}
          testId="import-count-skipped"
          label={t("admin.blocked.skipped")}
          tone="text-[#8B5CF6]"
        />
        <ResultTile
          icon={<AlertTriangle className="w-6 h-6 mx-auto text-[#EF4444] mb-1" />}
          value={importResult.invalid_count}
          testId="import-count-invalid"
          label={t("admin.blocked.invalid")}
          tone="text-[#EF4444]"
        />
      </div>
      {importResult.affected_active_accounts > 0 && (
        <div className="border-l-2 border-[#8B5CF6] bg-[#8B5CF6]/5 p-3 text-xs text-[#FEF3C7]">
          <Trans
            i18nKey="admin.blocked.importAffected"
            values={{ n: importResult.affected_active_accounts }}
            components={{ 1: <span className="font-semibold" />, 2: <strong /> }}
          />
        </div>
      )}
      {importResult.invalid?.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">
            {t("admin.blocked.invalidEntriesTitle")}
          </div>
          <div className="bg-[#0F0F0F] border border-[#EF4444]/30 p-2 max-h-32 overflow-y-auto text-xs font-mono">
            {importResult.invalid.map((it) => (
              <div key={`${it.phone}-${it.reason}`} className="text-neutral-400">
                • <span className="text-[#EF4444]">{it.phone}</span> — {it.reason}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex justify-end pt-2">
        <Button
          data-testid="bulk-import-close"
          onClick={onReset}
          className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white font-bold rounded-none"
        >
          {t("admin.blocked.closeBtn")}
        </Button>
      </div>
    </div>
  );
}

function ResultTile({ icon, value, testId, label, tone }) {
  return (
    <div className="tactile-card p-4 text-center">
      {icon}
      <div className={`font-display text-2xl ${tone}`} data-testid={testId}>{value}</div>
      <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">{label}</div>
    </div>
  );
}
