import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Server-side paginator. Reads {page, total, pageSize} and emits onPageChange(newPage).
 * Hides itself when there is nothing to paginate.
 */
export function Pagination({ page, total, pageSize, loading = false, onPageChange, testidPrefix = "pagination" }) {
  if (!total || total <= pageSize) return null;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = page * pageSize + 1;
  const end = Math.min((page + 1) * pageSize, total);
  const atFirst = page === 0;
  const atLast = (page + 1) * pageSize >= total;

  return (
    <div
      className="flex items-center justify-between text-xs text-neutral-400"
      data-testid={testidPrefix}
    >
      <div className="font-mono">{start}–{end} de {total}</div>
      <div className="flex items-center gap-2">
        <Button
          data-testid={`${testidPrefix}-prev`}
          disabled={atFirst || loading}
          onClick={() => onPageChange(Math.max(0, page - 1))}
          className="rounded-none bg-transparent border border-white/15 hover:border-[#EAB308]/60 hover:bg-[#EAB308]/5 disabled:opacity-30 disabled:cursor-not-allowed text-white h-9 px-3 font-mono text-xs uppercase tracking-wider"
        >
          <ChevronLeft className="w-3.5 h-3.5 mr-1" /> Anterior
        </Button>
        <span
          className="font-mono text-neutral-500 px-2"
          data-testid={`${testidPrefix}-indicator`}
        >
          Página {page + 1} de {pageCount}
        </span>
        <Button
          data-testid={`${testidPrefix}-next`}
          disabled={atLast || loading}
          onClick={() => onPageChange(page + 1)}
          className="rounded-none bg-transparent border border-white/15 hover:border-[#EAB308]/60 hover:bg-[#EAB308]/5 disabled:opacity-30 disabled:cursor-not-allowed text-white h-9 px-3 font-mono text-xs uppercase tracking-wider"
        >
          Siguiente <ChevronRight className="w-3.5 h-3.5 ml-1" />
        </Button>
      </div>
    </div>
  );
}
