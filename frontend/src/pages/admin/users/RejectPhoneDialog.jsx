import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Ban } from "lucide-react";

export function RejectPhoneDialog({ target, reason, setReason, onClose, onConfirm }) {
  return (
    <Dialog open={!!target} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        data-testid="reject-phone-dialog"
        className="bg-[#0A0A0F] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-display text-2xl flex items-center gap-2">
            <Ban className="w-6 h-6 text-[#EF4444]" /> Rechazar y bloquear teléfono
          </DialogTitle>
          <DialogDescription className="text-neutral-500 text-xs">
            El número{" "}
            <span className="font-mono text-[#EF4444]">{target?.phone}</span>{" "}
            de <span className="text-neutral-300">{target?.email}</span>{" "}
            se agregará a la lista de bloqueados. La cuenta del usuario quedará{" "}
            <strong className="text-[#8B5CF6]">en revisión</strong> y no podrá operar
            en la plataforma. Esta acción se puede revertir borrando el contacto
            de la lista de bloqueos.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="micro-label text-neutral-500">Motivo del bloqueo *</Label>
            <Textarea
              data-testid="reject-phone-reason-input"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Ej: comprobante falsificado, sospecha de estafa en grupo de WhatsApp, etc."
              className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[100px]"
              autoFocus
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={onClose} className="rounded-none">
              Cancelar
            </Button>
            <Button
              data-testid="reject-phone-confirm"
              onClick={onConfirm}
              disabled={reason.trim().length < 3}
              className="bg-[#EF4444] hover:bg-[#DC2626] text-white font-bold rounded-none"
            >
              Continuar al 2FA
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
