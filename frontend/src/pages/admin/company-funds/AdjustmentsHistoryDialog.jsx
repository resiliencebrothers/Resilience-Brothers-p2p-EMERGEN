import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { HandCoins } from "lucide-react";
import AdjustmentsTable from "./AdjustmentsTable";

/**
 * iter55.36k — Move the "Ajustes manuales de capital" section (capital
 * injections and partner withdrawals) into a dedicated dialog. Motivation:
 * before this change the table was rendered INLINE under "Retiros del fondo",
 * so as company withdrawals accumulated the capital-adjustments block was
 * pushed further off-screen — hurting the operator's ability to audit
 * treasury movements at a glance.
 *
 * The dialog is opened by a "Depósitos" button in the treasury header row,
 * making the section discoverable regardless of the withdrawals list length.
 * Creation of new adjustments continues to happen through `AdjustmentDialog`
 * (unchanged, opened by "Ajuste manual").
 */
export default function AdjustmentsHistoryDialog({ open, onOpenChange, items }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-[#1A1730] border-white/10 text-white rounded-none max-w-6xl max-h-[85vh] overflow-y-auto"
        data-testid="adjustments-history-dialog"
      >
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <HandCoins className="w-5 h-5 text-[#8B5CF6]" />
            Depósitos y ajustes manuales de capital
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            Aportes propios (inyección de capital) o retiros del socio.
            Se reflejan en el balance por moneda. Muestra los últimos ajustes
            en orden descendente por fecha.
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2" data-testid="adjustments-history-body">
          <AdjustmentsTable items={items} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
