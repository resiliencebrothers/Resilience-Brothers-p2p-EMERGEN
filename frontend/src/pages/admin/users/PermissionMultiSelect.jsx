import { useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ChevronDown, ChevronRight, ShieldCheck,
  ClipboardList, Package, Users, Wallet,
} from "lucide-react";

/**
 * iter55.16 — Per-staff-member capability selector.
 * iter108.1 — Responsive height + collision padding so nothing gets clipped.
 * iter108.2 — Grouped by category with collapsible headers. Backend adds a
 * `category` field to each permission (source of truth in permissions.py).
 * Frontend keeps only the display metadata (label + icon).
 *
 * Props:
 *  - userId: string
 *  - catalog: [{code, category, label, description}] from /api/admin/permissions/catalog
 *  - selected: string[] of codes (empty = "todos los permisos staff")
 *  - onToggle: (code, boolValue) => void
 *  - onSave: () => void
 *  - onClear: () => void
 */

// Category display order + label + icon. Codes match the backend `category`
// field. Any permission whose category isn't listed here lands in "other".
const CATEGORIES = [
  { code: "operations", label: "Operaciones",     icon: ClipboardList },
  { code: "catalog",    label: "Catálogo",        icon: Package },
  { code: "users",      label: "Usuarios",        icon: Users },
  { code: "finance",    label: "Fondos y auditoría", icon: Wallet },
  { code: "other",      label: "Otros",           icon: ShieldCheck },
];

function groupCatalog(catalog) {
  const groups = new Map(CATEGORIES.map((c) => [c.code, { ...c, items: [] }]));
  for (const p of catalog || []) {
    const cat = groups.has(p.category) ? p.category : "other";
    groups.get(cat).items.push(p);
  }
  return Array.from(groups.values()).filter((g) => g.items.length > 0);
}

export function PermissionMultiSelect({ userId, catalog, selected, onToggle, onSave, onClear }) {
  const [open, setOpen] = useState(false);
  // Category collapse state — all open by default so the operator sees
  // everything on first click.
  const [collapsed, setCollapsed] = useState({});
  const toggleGroup = (code) => setCollapsed((s) => ({ ...s, [code]: !s[code] }));

  const selectedSet = useMemo(() => new Set(selected || []), [selected]);
  const grouped = useMemo(() => groupCatalog(catalog), [catalog]);

  const triggerLabel =
    selectedSet.size === 0
      ? "Todos (sin restricción)"
      : selectedSet.size <= 2
        ? Array.from(selectedSet).map((c) => catalog?.find((p) => p.code === c)?.label || c).join(", ")
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
              <ShieldCheck className={`w-3 h-3 ${selectedSet.size === 0 ? "text-neutral-600" : "text-[#8B5CF6]"}`} />
              <span className={selectedSet.size === 0 ? "text-neutral-500" : "text-white"}>
                {triggerLabel}
              </span>
            </span>
            <ChevronDown className="w-3 h-3 text-neutral-500" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          sideOffset={8}
          collisionPadding={16}
          className="w-80 p-0 bg-[#1A1730] border border-white/10 rounded-none text-white flex flex-col"
          style={{ maxHeight: "min(28rem, var(--radix-popover-content-available-height, 80vh))" }}
        >
          <div className="px-3 py-2 micro-label text-neutral-500 border-b border-white/10 shrink-0">
            Selecciona funciones autorizadas
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            {(!catalog || catalog.length === 0) && (
              <div className="px-3 py-3 text-xs text-neutral-500">
                Cargando catálogo…
              </div>
            )}
            {grouped.map((group) => {
              const GroupIcon = group.icon;
              const isCollapsed = !!collapsed[group.code];
              const selectedCount = group.items.filter((it) => selectedSet.has(it.code)).length;
              return (
                <div key={group.code} data-testid={`permission-group-${userId}-${group.code}`}>
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.code)}
                    data-testid={`permission-group-toggle-${userId}-${group.code}`}
                    className="w-full flex items-center gap-2 px-3 py-2 bg-black/30 border-t border-white/5 hover:bg-black/50 transition-colors"
                  >
                    {isCollapsed
                      ? <ChevronRight className="w-3 h-3 text-neutral-500" />
                      : <ChevronDown className="w-3 h-3 text-neutral-500" />}
                    <GroupIcon className="w-3.5 h-3.5 text-[#8B5CF6]" />
                    <span className="micro-label text-neutral-300 flex-1 text-left">{group.label}</span>
                    <span
                      className={`text-[0.6rem] font-mono px-1.5 py-0.5 border ${
                        selectedCount > 0
                          ? "border-[#8B5CF6]/40 bg-[#8B5CF6]/10 text-[#8B5CF6]"
                          : "border-white/10 text-neutral-500"
                      }`}
                      data-testid={`permission-group-count-${userId}-${group.code}`}
                    >
                      {selectedCount}/{group.items.length}
                    </span>
                  </button>
                  {!isCollapsed && group.items.map((p) => {
                    const isOn = selectedSet.has(p.code);
                    return (
                      <label
                        key={p.code}
                        className="flex items-start gap-2 pl-9 pr-3 py-2 cursor-pointer hover:bg-white/5"
                        data-testid={`permission-option-${userId}-${p.code}`}
                      >
                        <Checkbox
                          checked={isOn}
                          onCheckedChange={(v) => onToggle(p.code, !!v)}
                          className="border-white/20 data-[state=checked]:bg-[#8B5CF6] data-[state=checked]:text-white mt-0.5"
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
              );
            })}
          </div>
          <div className="border-t border-white/10 px-3 py-2 flex justify-between items-center gap-2 shrink-0">
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
