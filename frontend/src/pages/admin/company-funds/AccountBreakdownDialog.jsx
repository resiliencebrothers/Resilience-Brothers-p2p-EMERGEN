/**
 * iter194 — AccountBreakdownDialog
 *
 * Opens when the operator clicks a fund card's balance. Shows how the
 * currency's gross balance is distributed across internal accounts
 * (payment accounts + custom fund accounts) plus the "Sin asignar" bucket.
 * Inline tools: create a custom account and transfer/reassign balance
 * between accounts (2FA).
 */
import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { API } from "@/App";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import TotpPromptDialog, { handleTotpError } from "@/components/TotpPromptDialog";
import {
  Landmark, Wallet, Banknote, CircleDollarSign, Plus, ArrowLeftRight, Layers,
} from "lucide-react";
import { toast } from "sonner";

const UNASSIGNED = "__unassigned__";
const fmt2 = (n) =>
  Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

const METHOD_ICONS = {
  bank: Landmark,
  cash: Banknote,
  crypto: Wallet,
  other: CircleDollarSign,
};

export default function AccountBreakdownDialog({ currency, onClose }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [mode, setMode] = useState(null); // null | "create" | "transfer"

  const load = useCallback(async () => {
    if (!currency) return;
    try {
      const r = await axios.get(
        `${API}/admin/company-funds/accounts/${currency}`,
        { withCredentials: true },
      );
      setData(r.data);
    } catch {
      toast.error(t("admin.companyFunds.loadError"));
    }
  }, [currency, t]);

  useEffect(() => {
    setData(null);
    setMode(null);
    if (currency) load();
  }, [currency, load]);

  return (
    <Dialog open={!!currency} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent
        data-testid="account-breakdown-dialog"
        className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-lg max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <Layers className="w-5 h-5 text-[#8B5CF6]" />
            {t("admin.companyFunds.breakdownTitle", { currency })}
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            {t("admin.companyFunds.breakdownSub", { currency })}
          </DialogDescription>
        </DialogHeader>

        {!data ? (
          <div className="text-sm text-neutral-500 py-6 text-center">…</div>
        ) : (
          <div className="space-y-4">
            <AccountList data={data} t={t} />

            <div className="grid grid-cols-2 gap-2">
              <Button
                data-testid="open-create-account"
                variant="outline"
                onClick={() => setMode(mode === "create" ? null : "create")}
                className="rounded-none border-white/20 hover:bg-white/5"
              >
                <Plus className="w-4 h-4 mr-1" /> {t("admin.companyFunds.newAccountBtn")}
              </Button>
              <Button
                data-testid="open-transfer-form"
                onClick={() => setMode(mode === "transfer" ? null : "transfer")}
                className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
              >
                <ArrowLeftRight className="w-4 h-4 mr-1" /> {t("admin.companyFunds.transferBtn")}
              </Button>
            </div>

            {mode === "create" && (
              <CreateAccountForm
                currency={currency}
                t={t}
                onDone={() => { setMode(null); load(); }}
              />
            )}
            {mode === "transfer" && (
              <TransferForm
                currency={currency}
                accounts={data.accounts}
                t={t}
                onDone={() => { setMode(null); load(); }}
              />
            )}

            <TransfersHistory transfers={data.transfers} t={t} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function AccountList({ data, t }) {
  return (
    <div className="space-y-1.5">
      {data.accounts.length === 0 && Math.abs(data.unassigned) < 0.005 && (
        <div className="text-xs text-neutral-500 py-2">
          {t("admin.companyFunds.breakdownEmpty")}
        </div>
      )}
      {data.accounts.map((a) => <AccountRow key={a.id} a={a} t={t} />)}
      <div
        className="flex items-center justify-between gap-3 px-3 py-2.5 border border-[#F59E0B]/25 bg-[#F59E0B]/5"
        data-testid="fund-unassigned-row"
      >
        <div>
          <div className="text-sm text-[#F59E0B]">{t("admin.companyFunds.unassigned")}</div>
          <div className="text-[0.6rem] text-neutral-500">
            {t("admin.companyFunds.unassignedHint")}
          </div>
        </div>
        <span className="font-mono tabular-nums text-[#F59E0B]">
          {fmt2(data.unassigned)}
        </span>
      </div>
      <div
        className="flex items-center justify-between gap-3 px-3 py-2 border-t border-white/10"
        data-testid="fund-breakdown-total"
      >
        <span className="text-[0.65rem] uppercase tracking-widest text-neutral-400">
          {t("admin.companyFunds.accountsTotal")}
        </span>
        <span className="font-display text-lg tabular-nums text-[#22C55E]">
          {fmt2(data.total_balance)} <span className="text-xs text-neutral-500">{data.currency}</span>
        </span>
      </div>
    </div>
  );
}

function AccountRow({ a, t }) {
  const Icon = METHOD_ICONS[a.method] || CircleDollarSign;
  const sourceLabel = a.source === "payment"
    ? t("admin.companyFunds.sourcePayment")
    : a.source === "custom"
      ? t("admin.companyFunds.sourceCustom")
      : t("admin.companyFunds.deletedAccount");
  return (
    <div
      className="flex items-center justify-between gap-3 px-3 py-2.5 border border-white/10 bg-white/[0.02]"
      data-testid={`fund-account-row-${a.id}`}
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <Icon className="w-4 h-4 text-[#8B5CF6] flex-shrink-0" />
        <div className="min-w-0">
          <div className="text-sm truncate">{a.label}</div>
          <div className="text-[0.6rem] uppercase tracking-widest text-neutral-500 flex items-center gap-1.5">
            <span>{sourceLabel}</span>
            {!a.is_active && (
              <span className="text-[#F59E0B]">{t("admin.companyFunds.badgeInactive")}</span>
            )}
          </div>
        </div>
      </div>
      <span
        className={`font-mono tabular-nums whitespace-nowrap ${
          a.balance >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"
        }`}
        data-testid={`fund-account-balance-${a.id}`}
      >
        {fmt2(a.balance)}
      </span>
    </div>
  );
}

const METHOD_KEYS = ["bank", "cash", "crypto", "other"];

function CreateAccountForm({ currency, t, onDone }) {
  const [name, setName] = useState("");
  const [method, setMethod] = useState("bank");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/company-funds/accounts`,
        { name: name.trim(), currency, method, note: note.trim() },
        { withCredentials: true },
      );
      toast.success(t("admin.companyFunds.accCreated"));
      onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || t("admin.common.genericError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border border-white/10 bg-[#0a0a0a]/50 p-3 space-y-3" data-testid="create-account-form">
      <div>
        <Label className="micro-label text-neutral-500">{t("admin.companyFunds.accName")}</Label>
        <Input
          data-testid="acc-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("admin.companyFunds.accNamePh")}
          className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
        />
      </div>
      <div>
        <Label className="micro-label text-neutral-500">{t("admin.companyFunds.accMethod")}</Label>
        <Select value={method} onValueChange={setMethod}>
          <SelectTrigger data-testid="acc-method" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none">
            {METHOD_KEYS.map((m) => (
              <SelectItem key={m} value={m}>
                {t(`admin.companyFunds.accMethod_${m}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label className="micro-label text-neutral-500">{t("admin.companyFunds.accNote")}</Label>
        <Input
          data-testid="acc-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
        />
      </div>
      <Button
        data-testid="acc-create-submit"
        disabled={name.trim().length < 2 || busy}
        onClick={submit}
        className="w-full bg-[#22C55E] hover:bg-[#16A34A] text-black rounded-none"
      >
        {t("admin.companyFunds.accCreate")}
      </Button>
    </div>
  );
}

function TransferForm({ currency, accounts, t, onDone }) {
  const navigate = useNavigate();
  const [from, setFrom] = useState(UNASSIGNED);
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [askTotp, setAskTotp] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (code) => {
    setBusy(true);
    try {
      await axios.post(
        `${API}/admin/company-funds/accounts/transfer`,
        {
          currency,
          from_account_id: from === UNASSIGNED ? null : from,
          to_account_id: to === UNASSIGNED ? null : to,
          amount: parseFloat(amount),
          note: note.trim(),
          totp_code: code,
        },
        { withCredentials: true },
      );
      toast.success(t("admin.companyFunds.trDone"));
      setAskTotp(false);
      onDone();
    } catch (e) {
      if (!handleTotpError(e, navigate)) {
        toast.error(e.response?.data?.detail || t("admin.common.genericError"));
      }
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = to !== "" && from !== to && parseFloat(amount) > 0;

  const optionItems = (excludeId, testId) => (
    <SelectContent className="bg-[#1A1730] border-white/10 text-white rounded-none" data-testid={testId}>
      <SelectItem value={UNASSIGNED}>{t("admin.companyFunds.unassigned")}</SelectItem>
      {accounts.filter((a) => a.id !== excludeId).map((a) => (
        <SelectItem key={a.id} value={a.id}>{a.label}</SelectItem>
      ))}
    </SelectContent>
  );

  return (
    <div className="border border-white/10 bg-[#0a0a0a]/50 p-3 space-y-3" data-testid="transfer-form">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="micro-label text-neutral-500">{t("admin.companyFunds.trFrom")}</Label>
          <Select value={from} onValueChange={setFrom}>
            <SelectTrigger data-testid="tr-from" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10">
              <SelectValue />
            </SelectTrigger>
            {optionItems(to, "tr-from-options")}
          </Select>
        </div>
        <div>
          <Label className="micro-label text-neutral-500">{t("admin.companyFunds.trTo")}</Label>
          <Select value={to} onValueChange={setTo}>
            <SelectTrigger data-testid="tr-to" className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10">
              <SelectValue placeholder="—" />
            </SelectTrigger>
            {optionItems(from, "tr-to-options")}
          </Select>
        </div>
      </div>
      <div>
        <Label className="micro-label text-neutral-500">{t("admin.companyFunds.trAmount")}</Label>
        <Input
          data-testid="tr-amount"
          type="number"
          step="any"
          min="0"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10 font-mono"
        />
      </div>
      <div>
        <Label className="micro-label text-neutral-500">{t("admin.companyFunds.trNote")}</Label>
        <Input
          data-testid="tr-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 h-10"
        />
      </div>
      <Button
        data-testid="tr-submit"
        disabled={!canSubmit || busy}
        onClick={() => setAskTotp(true)}
        className="w-full bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none"
      >
        {t("admin.companyFunds.trSubmit")}
      </Button>

      <TotpPromptDialog
        open={askTotp}
        title={t("admin.companyFunds.trTotpTitle")}
        description={t("admin.companyFunds.trTotpDesc")}
        busy={busy}
        onConfirm={submit}
        onCancel={() => setAskTotp(false)}
      />
    </div>
  );
}

function TransfersHistory({ transfers, t }) {
  if (!transfers || transfers.length === 0) return null;
  return (
    <div className="space-y-1" data-testid="transfers-history">
      <div className="text-[0.6rem] uppercase tracking-widest text-neutral-500 pb-1 border-b border-white/5">
        {t("admin.companyFunds.trHistory")}
      </div>
      {transfers.slice(0, 10).map((tr) => (
        <div key={tr.id} className="flex items-center justify-between gap-2 text-[0.68rem] font-mono py-1">
          <span className="text-neutral-400 truncate">
            {tr.from_label || t("admin.companyFunds.unassigned")}
            <span className="text-neutral-600"> → </span>
            {tr.to_label || t("admin.companyFunds.unassigned")}
          </span>
          <span className="text-[#8B5CF6] tabular-nums whitespace-nowrap">
            {fmt2(tr.amount)}
          </span>
        </div>
      ))}
    </div>
  );
}
