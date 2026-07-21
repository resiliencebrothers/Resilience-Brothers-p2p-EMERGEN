/**
 * iter87 — FundCards
 *
 * The 4-column grid of company-fund balance cards. Each card shows the
 * total balance, inflow from orders + manual contributions, and outflow
 * split by kind (orders / VIP withdrawals / normal withdrawals / company
 * withdrawals / manual outflow).
 */
import { useTranslation } from "react-i18next";
import { Wallet } from "lucide-react";

const fmt2 = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function FundCards({ funds }) {
  const { t } = useTranslation();
  if (funds.length === 0) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="fund-cards">
        <div className="col-span-full text-neutral-500 text-sm">
          {t("admin.companyFunds.empty")}
        </div>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="fund-cards">
      {funds.map((f) => <FundCard key={f.currency} f={f} t={t} />)}
    </div>
  );
}

function FundCard({ f, t }) {
  return (
    <div className="tactile-card p-5" data-testid={`fund-${f.currency}`}>
      <Wallet className="w-4 h-4 text-[#8B5CF6] mb-2" />
      <div className="micro-label text-neutral-500">{f.currency}</div>
      <div
        className={`font-display text-2xl mt-1 ${
          f.balance >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"
        }`}
        data-testid={`fund-balance-${f.currency}`}
      >
        {fmt2(f.balance)}
      </div>
      <div className="text-[0.65rem] text-neutral-500 mt-3 space-y-0.5 font-mono">
        <div>+ {t("admin.companyFunds.orders")}: {fmt2(f.inflow)}</div>
        {f.manual_inflow > 0 && (
          <div className="text-[#22C55E]/80" data-testid={`fund-manual-in-${f.currency}`}>
            + {t("admin.companyFunds.ownContribution")}: {fmt2(f.manual_inflow)}
          </div>
        )}
        {(f.outflow_orders ?? 0) > 0 && (
          <div className="text-[#EF4444]/80" data-testid={`fund-order-out-${f.currency}`}>
            − {t("admin.companyFunds.deliveredToClients")}: {fmt2(f.outflow_orders)}
          </div>
        )}
        {(f.outflow_clients_vip ?? 0) > 0 && (
          <div data-testid={`fund-vip-out-${f.currency}`}>
            − {t("admin.companyFunds.vipWithdrawals")}: {fmt2(f.outflow_clients_vip)}
          </div>
        )}
        {(f.outflow_clients_normal ?? 0) > 0 && (
          <div data-testid={`fund-normal-out-${f.currency}`}>
            − {t("admin.companyFunds.normalWithdrawals")}: {fmt2(f.outflow_clients_normal)}
          </div>
        )}
        {(f.outflow_clients_vip == null && f.outflow_clients_normal == null && (f.outflow_clients ?? 0) > 0) && (
          <div>− {t("admin.companyFunds.clientWithdrawals")}: {fmt2(f.outflow_clients)}</div>
        )}
        <div>− {t("admin.companyFunds.companyOutflow")}: {fmt2(f.outflow_company)}</div>
        {f.manual_outflow > 0 && (
          <div className="text-[#EF4444]/80" data-testid={`fund-manual-out-${f.currency}`}>
            − {t("admin.companyFunds.ownOutflow")}: {fmt2(f.manual_outflow)}
          </div>
        )}
      </div>
    </div>
  );
}
