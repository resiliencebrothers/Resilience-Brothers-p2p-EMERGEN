import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { ChevronDown, ShieldCheck } from "lucide-react";

/**
 * iter55.16 — Per-staff-member capability selector.
 *
 * Mirrors the visual pattern of CurrencyMultiSelect so admins have a familiar
 * UX for both the currency scope and the function scope.
 *
 * Props:
 *  - userId: string
 *  - catalog: [{code, label, description}] from /api/admin/permissions/catalog
 *  - selected: string[] of codes (empty = "todos los permisos staff")
 *  - onToggle: (code, boolValue) => void
 *  - onSave: () => void
 *  - onClear: () => void
 */
export function PermissionMultiSelect({ userId, catalog, selected, onToggle, onSave, onClear }) {
  const [open, setOpen] = useState(false);
  const selectedSet = new Set(selected || []);
  const label =
    selectedSet.size === 0
      ? "Todos (sin restricción)"
      : selectedSet.size <= 2
        ? Array.from(selectedSet).map((c) => catalog.find((p) => p.code === c)?.label || c).join(", ")
        : `${selectedSet.size} permisos`;

  return (
    <div className="flex items-center gap-2" data-testid={`allowed-permissions-row-${userId}`}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            data-testid={`open-permissions-${userId}`}
            className="rounded-none w-52 h-9 justify-between bg-[#0a0a0a] border border-white/10 hover:bg-[#1a1a1a] text-xs font-mono"
          >
            <span className="flex items-center gap-1.5">
              <ShieldCheck className={`w-3 h-3 ${selectedSet.size === 0 ? "text-neutral-600" : "text-[#EAB308]"}`} />
              <span className={selectedSet.size === 0 ? "text-neutral-500" : "text-white"}>
                {label}
              </span>
            </span>
            <ChevronDown className="w-3 h-3 text-neutral-500" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-80 p-0 bg-[#141414] border border-white/10 rounded-none text-white"
        >
          <div className="px-3 py-2 micro-label text-neutral-500 border-b border-white/10">
            Selecciona funciones autorizadas
          </div>
          <div className="max-h-72 overflow-y-auto">
            {(!catalog || catalog.length === 0) && (
              <div className="px-3 py-3 text-xs text-neutral-500">
                Cargando catálogo…
              </div>
            )}
            {catalog?.map((p) => {
              const isOn = selectedSet.has(p.code);
              return (
                <label
                  key={p.code}
                  className="flex items-start gap-2 px-3 py-2 cursor-pointer hover:bg-white/5"
                  data-testid={`permission-option-${userId}-${p.code}`}
                >
                  <Checkbox
                    checked={isOn}
                    onCheckedChange={(v) => onToggle(p.code, !!v)}
                    className="border-white/20 data-[state=checked]:bg-[#EAB308] data-[state=checked]:text-black mt-0.5"
                  />
                  <div className="flex-1">
                    <div className="text-xs font-semibold text-white">{p.label}</div>
                    <div className="text-[0.65rem] text-neutral-500 leading-tight">
                      {p.description}
                    </div>
                  </div>
                </label>
              );
            })}
          </div>
          <div className="border-t border-white/10 px-3 py-2 flex justify-between items-center gap-2">
            <button
              type="button"
              onClick={onClear}
              data-testid={`clear-permissions-${userId}`}
              className="text-xs text-neutral-400 hover:text-[#EF4444]"
              title="Vacío = acceso completo staff (backward compat)"
            >
              Limpiar (todos)
            </button>
            <Button
              size="sm"
              data-testid={`save-permissions-${userId}`}
              onClick={() => { setOpen(false); onSave(); }}
              className="bg-[#EAB308] hover:bg-[#FACC15] text-black rounded-none h-8 text-xs"
            >
              Guardar
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
