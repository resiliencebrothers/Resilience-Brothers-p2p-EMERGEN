import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ArrowDown, ArrowUp, Download, Receipt, X, ExternalLink } from "lucide-react";

export function TransactionDetailModal({ selected, onClose, onNavigate }) {
  if (!selected) {
    // Keep the Dialog mounted but with no selected data → closed.
    return (
      <Dialog open={false} onOpenChange={onClose}>
        <DialogContent className="hidden" />
      </Dialog>
    );
  }

  return (
    <Dialog open={!!selected} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        data-testid="tx-detail-modal"
        className="bg-[#0c0c0c] border border-white/10 text-white max-w-2xl rounded-none"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-white">
            <Receipt className="w-5 h-5 text-[#EAB308]" />
            Detalle de Transacción
            {selected.direction === "in" ? (
              <span className="ml-2 text-[#22C55E] text-xs font-bold uppercase flex items-center gap-1">
                <ArrowDown className="w-3 h-3" /> Entrada
              </span>
            ) : (
              <span className="ml-2 text-[#EF4444] text-xs font-bold uppercase flex items-center gap-1">
                <ArrowUp className="w-3 h-3" /> Salida
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-3 border border-white/5 p-4 bg-[#0a0a0a]">
            <div>
              <div className="micro-label text-neutral-500 mb-1">Moneda</div>
              <div className="font-mono text-[#EAB308] text-lg">{selected.currency}</div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">Monto</div>
              <div className="font-mono text-xl">{selected.amount.toLocaleString()}</div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">Titular cuenta</div>
              <div className="font-medium" data-testid="tx-modal-holder">
                {selected.holder_name || "—"}
              </div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">Cliente</div>
              <div className="text-neutral-300">{selected.client_name}</div>
              <div className="text-xs text-neutral-500">{selected.client_email}</div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">Método</div>
              <div className="uppercase text-xs">{selected.method}</div>
            </div>
            <div>
              <div className="micro-label text-neutral-500 mb-1">Estado</div>
              <div className="uppercase text-xs text-[#22C55E]">{selected.status}</div>
            </div>
            <div className="col-span-2">
              <div className="micro-label text-neutral-500 mb-1">Fecha</div>
              <div className="font-mono text-xs">
                {new Date(selected.created_at).toLocaleString()}
              </div>
            </div>
            <div className="col-span-2">
              <div className="micro-label text-neutral-500 mb-1">
                {selected.ref_type === "withdrawal" ? "ID Retiro" : "ID Orden"}
              </div>
              <div className="font-mono text-xs text-neutral-400">{selected.ref_id}</div>
            </div>
          </div>

          {selected.delivery_details && (
            <div className="border border-white/5 p-4 bg-[#0a0a0a]">
              <div className="micro-label text-neutral-500 mb-2">
                {selected.direction === "in" ? "Datos del envío" : "Datos del beneficiario"}
              </div>
              <div className="text-sm whitespace-pre-wrap font-mono text-neutral-300">
                {selected.delivery_details}
              </div>
            </div>
          )}

          {selected.admin_note && (
            <div className="border border-[#EAB308]/30 p-4 bg-[#EAB308]/5">
              <div className="micro-label text-[#EAB308] mb-2">Nota admin</div>
              <div className="text-sm text-neutral-300">{selected.admin_note}</div>
            </div>
          )}

          {(selected.direction === "in" || selected.ref_type === "order_payout") && (
            <div>
              <div className="micro-label text-neutral-500 mb-2 flex items-center justify-between">
                <span>
                  {selected.ref_type === "order_payout"
                    ? "Comprobante del pago al cliente"
                    : "Comprobante de transferencia"}
                </span>
                {selected.proof_image && (
                  <a
                    href={selected.proof_image}
                    download={`comprobante_${selected.ref_id?.slice(0, 8)}.png`}
                    data-testid="tx-proof-download"
                    className="text-[#EAB308] hover:underline normal-case tracking-normal flex items-center gap-1"
                  >
                    <Download className="w-3 h-3" /> Descargar
                  </a>
                )}
              </div>
              {selected.proof_image ? (
                <a
                  href={selected.proof_image}
                  target="_blank"
                  rel="noreferrer"
                  data-testid="tx-proof-open"
                  className="block border border-white/10 bg-[#0a0a0a] p-2"
                >
                  <img
                    src={selected.proof_image}
                    alt="Comprobante"
                    className="w-full max-h-96 object-contain bg-black"
                    onError={(e) => { e.currentTarget.style.display = "none"; }}
                  />
                </a>
              ) : (
                <div className="border border-dashed border-white/10 p-6 text-center text-neutral-600 text-xs">
                  Sin comprobante adjunto
                </div>
              )}
            </div>
          )}

          {selected.direction === "out" && selected.ref_type !== "order_payout" && (
            <div className="border border-dashed border-white/10 p-4 text-center text-xs text-neutral-500">
              <X className="w-4 h-4 inline mr-1" />
              Las salidas no tienen comprobante de transferencia entrante (son pagos de la plataforma al cliente).
            </div>
          )}

          <div className="pt-2 flex justify-end">
            <Button
              data-testid="tx-modal-goto-source"
              onClick={() => onNavigate(selected)}
              className="rounded-none bg-[#EAB308] hover:bg-[#EAB308]/90 text-black font-bold h-10 px-4 text-xs uppercase tracking-wider"
            >
              <ExternalLink className="w-3.5 h-3.5 mr-2" />
              {selected.ref_type === "withdrawal" ? "Ir a Retiros VIP" : "Ir a Órdenes"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
