import CopyableText from "@/components/CopyableText";
import ExplorerLink from "@/components/ExplorerLink";

const WITHDRAWAL_STATUS_STYLES = {
  paid: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  approved: "bg-[#22C55E]/10 text-[#22C55E] border-[#22C55E]/30",
  rejected: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30",
  pending: "bg-[#8B5CF6]/10 text-[#8B5CF6] border-[#8B5CF6]/30",
};

// Labels are method-specific: cash deliveries use "Entregado / En progreso"
// while transfers/crypto use "Pagado / Confirmado".
const WITHDRAWAL_LABELS_BY_METHOD = {
  cash:     { paid: "Entregado", approved: "En progreso", pending: "Pendiente", rejected: "Rechazado" },
  transfer: { paid: "Pagado",    approved: "Confirmado",  pending: "Pendiente", rejected: "Rechazado" },
  crypto:   { paid: "Pagado",    approved: "Confirmado",  pending: "Pendiente", rejected: "Rechazado" },
};

function getWithdrawalLabel(method, status) {
  const map = WITHDRAWAL_LABELS_BY_METHOD[method] ?? WITHDRAWAL_LABELS_BY_METHOD.transfer;
  return map[status] ?? status;
}

/**
 * iter55.29 — Extracted from VipView. Renders the VIP client's withdrawal
 * history, including crypto-payout hash + explorer link when applicable.
 */
export function VipWithdrawalHistory({ withdrawals }) {
  return (
    <div className="tactile-card p-6">
      <h2 className="font-display text-xl mb-4">Historial de Retiros</h2>
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {withdrawals.length === 0 && (
          <p className="text-neutral-500 text-sm">Sin retiros aún.</p>
        )}
        {withdrawals.map((w) => (
          <WithdrawalRow key={w.id} w={w} />
        ))}
      </div>
    </div>
  );
}


function WithdrawalRow({ w }) {
  const label = getWithdrawalLabel(w.method, w.status);
  const statusStyle = WITHDRAWAL_STATUS_STYLES[w.status] || WITHDRAWAL_STATUS_STYLES.pending;
  return (
    <div className="border border-white/10 p-3 text-sm" data-testid={`withdrawal-row-${w.id}`}>
      <div className="flex justify-between items-start">
        <div>
          <div className="font-mono">
            {w.amount_usd} {w.currency || "USD"} · {w.method}
            {w.crypto_network ? ` · ${w.crypto_network}` : ""}
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            {new Date(w.created_at).toLocaleString()}
          </div>
        </div>
        <span className={`text-xs uppercase tracking-wider border px-2 py-1 ${statusStyle}`}>
          {label}
        </span>
      </div>
      {(w.payout_proof_image || w.payout_tx_hash) && (
        <div className="mt-3 border-t border-white/5 pt-2 space-y-2">
          {w.payout_tx_hash && (
            <div
              className="text-[0.65rem] text-neutral-400 flex flex-wrap items-center gap-2"
              data-testid={`payout-hash-${w.id}`}
            >
              <span className="text-neutral-600">Hash:</span>
              <span className="text-[#22C55E]">
                <CopyableText
                  value={w.payout_tx_hash}
                  label="Copiar hash"
                  toastMessage="Hash copiado"
                  testid={`payout-hash-copy-${w.id}`}
                />
              </span>
              <ExplorerLink
                network={w.crypto_network}
                txHash={w.payout_tx_hash}
                testid={`payout-explorer-${w.id}`}
              />
            </div>
          )}
          {w.payout_proof_image && (
            <a
              href={w.payout_proof_image}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-[#8B5CF6] underline underline-offset-4"
              data-testid={`payout-proof-${w.id}`}
            >
              Ver captura de la transferencia
            </a>
          )}
        </div>
      )}
    </div>
  );
}
