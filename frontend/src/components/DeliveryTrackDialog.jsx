import { useTranslation } from "react-i18next";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Bike, Search } from "lucide-react";
import DeliveryTrackCard, { useDeliveryForRef } from "@/components/DeliveryTrackCard";

/**
 * iter208 — Diálogo "Seguir Entrega" que abre el cliente por cada
 * retiro/depósito específico. Muestra timeline + ETA de la mensajería
 * asociada a ese refId. Reemplaza el bloque global del dashboard para
 * mejor organización cuando hay múltiples entregas.
 */
export default function DeliveryTrackDialog({ refId, open, onClose }) {
  const { t } = useTranslation();
  const { items, loading } = useDeliveryForRef(refId, open);

  return (
    <Dialog open={!!open} onOpenChange={(o) => !o && onClose?.()}>
      <DialogContent
        data-testid="delivery-track-dialog"
        className="bg-[#0c0c0c] border border-[#8B5CF6]/30 text-white rounded-none max-w-md max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bike className="w-5 h-5 text-[#8B5CF6]" />
            {t("tracker.dialogTitle")}
          </DialogTitle>
        </DialogHeader>

        <div className="mt-2 space-y-3">
          {loading && items.length === 0 && (
            <div className="text-xs text-neutral-500 py-6 text-center" data-testid="delivery-track-loading">
              {t("common.loading")}
            </div>
          )}
          {!loading && items.length === 0 && (
            <div
              className="text-xs text-neutral-500 py-6 text-center flex flex-col items-center gap-2"
              data-testid="delivery-track-empty"
            >
              <Search className="w-6 h-6 text-neutral-600" />
              {t("tracker.noJob")}
            </div>
          )}
          {items.map((d) => <DeliveryTrackCard key={d.id} d={d} />)}
        </div>
      </DialogContent>
    </Dialog>
  );
}
