import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export default function LegalLayout({ title, eyebrow, lastUpdated, children }) {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white" data-testid={`legal-${(eyebrow || "").toLowerCase()}`}>
      <header className="border-b border-white/10 sticky top-0 bg-[#0A0A0A]/95 backdrop-blur z-10">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="text-xs uppercase tracking-widest text-neutral-400 hover:text-[#EAB308] flex items-center gap-2">
            <ArrowLeft className="w-4 h-4" /> Volver al inicio
          </Link>
          <span className="text-xs uppercase tracking-widest text-neutral-500">Resilience Brothers</span>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12">
        <p className="micro-label text-[#EAB308] mb-3">/ {eyebrow}</p>
        <h1 className="font-display text-4xl sm:text-5xl leading-tight mb-3">{title}</h1>
        <p className="text-xs text-neutral-500 font-mono mb-10">Última actualización: {lastUpdated}</p>

        <article className="prose prose-invert max-w-none text-neutral-300 leading-relaxed space-y-6 [&_h2]:text-white [&_h2]:font-display [&_h2]:text-2xl [&_h2]:mt-10 [&_h2]:mb-3 [&_h3]:text-white [&_h3]:font-semibold [&_h3]:mt-6 [&_h3]:mb-2 [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-1 [&_a]:text-[#EAB308] [&_a]:underline">
          {children}
        </article>

        <footer className="mt-16 pt-8 border-t border-white/10 text-xs text-neutral-500 flex flex-wrap gap-x-6 gap-y-2">
          <Link to="/privacy" className="hover:text-[#EAB308]">Política de Privacidad</Link>
          <Link to="/terms" className="hover:text-[#EAB308]">Condiciones del Servicio</Link>
          <span className="ml-auto">© {new Date().getFullYear()} Resilience Brothers</span>
        </footer>
      </main>
    </div>
  );
}
