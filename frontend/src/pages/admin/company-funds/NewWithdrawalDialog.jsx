/**
 * iter87 — NewWithdrawalDialog
 *
 * The "new company withdrawal" dialog. Presentation-only. Uses
 * `onContinueTotp` to trigger the TOTP prompt owned by the parent hook
 * (which then calls `submitCreate(code)`).
 */
import { useTranslation, Trans } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/context/AuthContext";

export default function NewWithdrawalDialog({
  open, onOpenChange,
  form, setForm,
  createCurrencies,
  onInvoiceUpload,
  pendingSubmit,
  onContinueTotp,
}) {
  const { t } = useTranslation();
  const { user } = useAuth();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display">{t("admin.companyFunds.dialogNewTitle")}</DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            <Trans
              i18nKey="admin.companyFunds.dialogNewSub"
              values={{ name: user?.name }}
              components={{ 1: <span className="font-mono text-white" /> }}
            />
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.companyFunds.currency")}</Label>
              <Select
                value={form.currency}
                onValueChange={(v) => setForm({ ...form, currency: v })}
              >
                <SelectTrigger
                  data-testid="company-form-currency"
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
                >
                  <SelectValue placeholder="Selecciona" />
                </SelectTrigger>
                <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
                  {createCurrencies.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="micro-label text-neutral-500">{t("admin.companyFunds.amount")}</Label>
              <Input
                data-testid="company-form-amount"
                type="number"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono"
              />
            </div>
          </div>
          <div>
            <Label className="micro-label text-neutral-500">
              {t("admin.companyFunds.beneficiaryLabel")}
            </Label>
            <Input
              data-testid="company-form-beneficiary"
              value={form.beneficiary}
              onChange={(e) => setForm({ ...form, beneficiary: e.target.value })}
              placeholder={t("admin.companyFunds.beneficiaryPh")}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">
              {t("admin.companyFunds.conceptLabel")}
            </Label>
            <Input
              data-testid="company-form-concept"
              value={form.concept}
              onChange={(e) => setForm({ ...form, concept: e.target.value })}
              placeholder={t("admin.companyFunds.conceptPh")}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">{t("admin.companyFunds.note")}</Label>
            <Textarea
              data-testid="company-form-note"
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              rows={2}
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
            />
          </div>
          <div>
            <Label className="micro-label text-neutral-500">
              {t("admin.companyFunds.invoiceLabel")}
            </Label>
            <input
              data-testid="company-form-invoice"
              type="file"
              accept="image/*"
              onChange={onInvoiceUpload}
              className="block mt-1 text-xs text-neutral-400"
            />
            {form.invoice_image && (
              <img
                src={form.invoice_image}
                alt="invoice"
                className="mt-2 max-h-32 border border-white/10"
              />
            )}
          </div>
          <Button
            data-testid="company-form-submit"
            disabled={pendingSubmit || !form.currency || !form.amount || !form.beneficiary}
            onClick={onContinueTotp}
            className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
          >
            {t("admin.companyFunds.continueTotp")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
