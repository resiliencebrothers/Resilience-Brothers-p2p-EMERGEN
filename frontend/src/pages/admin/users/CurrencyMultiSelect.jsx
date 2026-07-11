import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { ChevronDown } from "lucide-react";

export function CurrencyMultiSelect({ userId, allCurrencies, selected, onToggle, onSave, onClear }) {
  const [open, setOpen] = useState(false);
  const selectedSet = new Set((selected || []).map((c) => String(c).toUpperCase()));
  const label =
    selectedSet.size === 0
      ? "Todas (sin restricción)"
      : selectedSet.size <= 3
        ? Array.from(selectedSet).join(", ")
        : `${selectedSet.size} monedas`;

  return (
    <div className="flex items-center gap-2" data-testid={`allowed-currencies-row-${userId}`}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            data-testid={`open-currencies-${userId}`}
            className="rounded-none w-44 h-9 justify-between bg-[#0a0a0a] border border-white/10 hover:bg-[#1a1a1a] text-xs font-mono"
          >
            <span className={selectedSet.size === 0 ? "text-neutral-500" : "text-white"}>
              {label}
            </span>
            <ChevronDown className="w-3 h-3 text-neutral-500" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-56 p-0 bg-[#1A1730] border border-white/10 rounded-none text-white"
        >
          <div className="px-3 py-2 micro-label text-neutral-500 border-b border-white/10">
            Selecciona monedas autorizadas
          </div>
          <div className="max-h-60 overflow-y-auto">
            {allCurrencies.length === 0 && (
              <div className="px-3 py-3 text-xs text-neutral-500">No hay monedas configuradas</div>
            )}
            {allCurrencies.map((c) => {
              const code = c.code;
              const isOn = selectedSet.has(code);
              return (
                <label
                  key={c.id || code}
                  className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-white/5"
                  data-testid={`currency-option-${userId}-${code}`}
                >
                  <Checkbox
                    checked={isOn}
                    onCheckedChange={(v) => onToggle(code, !!v)}
                    className="border-white/20 data-[state=checked]:bg-[#8B5CF6] data-[state=checked]:text-white"
                  />
                  <span className="font-mono text-sm">{code}</span>
                  {c.name && <span className="text-xs text-neutral-500 truncate">· {c.name}</span>}
                </label>
              );
            })}
          </div>
          <div className="border-t border-white/10 px-3 py-2 flex justify-between items-center gap-2">
            <button
              type="button"
              onClick={onClear}
              data-testid={`clear-currencies-${userId}`}
              className="text-xs text-neutral-400 hover:text-[#EF4444]"
            >
              Limpiar (todas)
            </button>
            <Button
              size="sm"
              data-testid={`save-currencies-${userId}`}
              onClick={() => { setOpen(false); onSave(); }}
              className="bg-[#8B5CF6] hover:bg-[#A78BFA] text-white rounded-none h-8 text-xs"
            >
              Guardar
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
