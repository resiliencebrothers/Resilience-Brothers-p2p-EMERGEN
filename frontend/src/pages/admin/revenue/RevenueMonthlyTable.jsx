import { Button } from "@/components/ui/button";
import { Calendar, Download, FileText, Send } from "lucide-react";

export function RevenueMonthlyTable({ monthly, exporting, onDownload, onAskSend, fmt }) {
  return (
    <div className="tactile-card overflow-hidden" data-testid="revenue-monthly-card">
      <div className="px-6 py-4 border-b border-white/10">
        <h2 className="font-display text-lg flex items-center gap-2">
          <Calendar className="w-5 h-5 text-[#EAB308]" /> Registro Mensual
        </h2>
        <p className="text-xs text-neutral-500 mt-1">
          Descarga el detalle diario de cada mes en CSV o PDF.
          El día 1 de cada mes a las 09:00 UTC el PDF del mes anterior se envía
          automáticamente a todos los admins.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#0a0a0a]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">Mes</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Órdenes</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Volumen</th>
              <th className="px-4 py-3 micro-label text-neutral-500">P2P</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Marketplace</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Total</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Exportar</th>
            </tr>
          </thead>
          <tbody data-testid="monthly-rows">
            {monthly.length === 0 && (
              <tr>
                <td colSpan="7" className="text-center text-neutral-500 py-8">
                  Aún no hay meses con datos.
                </td>
              </tr>
            )}
            {monthly.map(m => (
              <tr key={m.bucket} className="border-b border-white/5">
                <td className="px-4 py-3 font-mono font-semibold">{m.bucket}</td>
                <td className="px-4 py-3 font-mono">{m.orders}</td>
                <td className="px-4 py-3 font-mono text-neutral-400">{fmt(m.volume_usdt)} USDT</td>
                <td className="px-4 py-3 font-mono">{fmt(m.p2p_profit_usdt)} USDT</td>
                <td className="px-4 py-3 font-mono">{fmt(m.marketplace_profit_usdt)} USDT</td>
                <td className="px-4 py-3 font-mono text-[#22C55E] font-bold">
                  {fmt(m.total_profit_usdt)} USDT
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2 flex-wrap">
                    <Button
                      size="sm"
                      data-testid={`export-csv-${m.bucket}`}
                      disabled={exporting === `${m.bucket}-csv`}
                      onClick={() => onDownload(m.bucket, "csv")}
                      className="rounded-none bg-transparent border border-white/10 hover:bg-white/5 h-8 text-xs"
                    >
                      <FileText className="w-3 h-3 mr-1" /> CSV
                    </Button>
                    <Button
                      size="sm"
                      data-testid={`export-pdf-${m.bucket}`}
                      disabled={exporting === `${m.bucket}-pdf`}
                      onClick={() => onDownload(m.bucket, "pdf")}
                      className="rounded-none bg-[#EAB308] hover:bg-[#FACC15] text-black h-8 text-xs"
                    >
                      <Download className="w-3 h-3 mr-1" /> PDF
                    </Button>
                    <Button
                      size="sm"
                      data-testid={`send-now-${m.bucket}`}
                      onClick={() => onAskSend(m.bucket)}
                      className="rounded-none bg-transparent border border-[#22C55E]/40 text-[#22C55E] hover:bg-[#22C55E]/10 h-8 text-xs"
                    >
                      <Send className="w-3 h-3 mr-1" /> Enviar
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
