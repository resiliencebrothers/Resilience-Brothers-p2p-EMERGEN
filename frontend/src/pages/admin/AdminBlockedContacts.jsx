import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API } from "@/App";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Ban, Plus, Trash2, Search, Upload, CheckCircle2, AlertTriangle, SkipForward } from "lucide-react";
import { toast } from "sonner";

const emptyForm = { phone: "", email: "", name: "", reason: "", notes: "" };

export default function AdminBlockedContacts() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  // Bulk import state
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/admin/blocked-contacts`, {
        params: { q: q || undefined, limit: 100 },
        withCredentials: true,
      });
      setItems(r.data.items);
      setTotal(r.data.total);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al cargar bloqueos");
    } finally { setLoading(false); }
  }, [q]);

  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    if (!form.phone && !form.email) {
      toast.error("Indica al menos un teléfono o un email");
      return;
    }
    if (!form.reason.trim()) {
      toast.error("Indica el motivo del bloqueo");
      return;
    }
    setSaving(true);
    try {
      await axios.post(`${API}/admin/blocked-contacts`,
        { phone: form.phone || null, email: form.email || null,
          name: form.name || null,
          reason: form.reason.trim(), notes: form.notes || null },
        { withCredentials: true },
      );
      toast.success("Contacto bloqueado");
      setForm(emptyForm); setOpen(false); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al bloquear");
    } finally { setSaving(false); }
  };

  const remove = async (id) => {
    if (!window.confirm("¿Quitar este bloqueo? El contacto podrá volver a registrarse.")) return;
    try {
      await axios.delete(`${API}/admin/blocked-contacts/${id}`, { withCredentials: true });
      toast.success("Bloqueo eliminado"); load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error");
    }
  };

  const submitBulkImport = async () => {
    if (!importText.trim()) {
      toast.error("Pega la lista antes de importar");
      return;
    }
    setImporting(true);
    setImportResult(null);
    try {
      const r = await axios.post(`${API}/admin/blocked-contacts/bulk-import`,
        { text: importText },
        { withCredentials: true },
      );
      setImportResult(r.data);
      if (r.data.imported_count > 0) {
        toast.success(`${r.data.imported_count} contactos importados`);
      } else if (r.data.skipped_count > 0) {
        toast.info("Todos los contactos ya estaban en la lista");
      } else {
        toast.warning("No se encontraron teléfonos válidos");
      }
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Error al importar");
    } finally { setImporting(false); }
  };

  const resetImport = () => {
    setImportText("");
    setImportResult(null);
    setImportOpen(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-3xl flex items-center gap-2"><Ban className="w-7 h-7 text-[#EF4444]" /> Contactos bloqueados</h1>
          <p className="text-xs text-neutral-500 mt-1">Lista de teléfonos y emails vetados. Si un teléfono está aquí, el dueño no podrá operar en la plataforma.</p>
        </div>
        <div className="flex gap-2">
          <Button data-testid="bulk-import-blocked-btn"
            onClick={() => { setImportText(""); setImportResult(null); setImportOpen(true); }}
            variant="outline"
            className="border-white/20 hover:border-[#EAB308] hover:bg-[#EAB308]/10 text-white rounded-none">
            <Upload className="w-4 h-4 mr-1" /> Importar lista
          </Button>
          <Button data-testid="add-blocked-contact-btn"
            onClick={() => { setForm(emptyForm); setOpen(true); }}
            className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none">
            <Plus className="w-4 h-4 mr-1" /> Bloquear contacto
          </Button>
        </div>
      </div>

      <div className="tactile-card p-3 flex items-center gap-2">
        <Search className="w-4 h-4 text-neutral-500 ml-2" />
        <Input
          data-testid="blocked-contacts-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Buscar por teléfono, nombre, email, motivo..."
          className="rounded-none bg-transparent border-none focus-visible:ring-0 h-9"
        />
        <span className="text-xs text-neutral-500 mr-2 font-mono">{total} total</span>
      </div>

      <div className="tactile-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-[#0F0F0F]">
            <tr className="text-left">
              <th className="px-4 py-3 micro-label text-neutral-500">Teléfono</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Nombre</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Email</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Motivo</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Bloqueado por</th>
              <th className="px-4 py-3 micro-label text-neutral-500">Fecha</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan="7" className="text-center text-neutral-500 py-8">Cargando...</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan="7" className="text-center text-neutral-500 py-8">No hay contactos bloqueados</td></tr>}
            {items.map((c) => (
              <tr key={c.id} data-testid={`blocked-row-${c.id}`} className="border-b border-white/5 hover:bg-white/[0.02]">
                <td className="px-4 py-3 font-mono text-neutral-300">{c.phone || <span className="text-neutral-600">—</span>}</td>
                <td className="px-4 py-3 text-neutral-300 text-xs">{c.name || <span className="text-neutral-600">—</span>}</td>
                <td className="px-4 py-3 text-neutral-300 text-xs break-all">{c.email || <span className="text-neutral-600">—</span>}</td>
                <td className="px-4 py-3 text-neutral-400 text-xs max-w-xs">
                  <div className="line-clamp-2 whitespace-pre-line">{c.reason}</div>
                  {c.notes && <div className="text-[0.65rem] text-neutral-600 mt-1 line-clamp-1">{c.notes}</div>}
                </td>
                <td className="px-4 py-3 text-xs text-neutral-500 break-all">{c.created_by_email}</td>
                <td className="px-4 py-3 text-xs text-neutral-500">{new Date(c.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => remove(c.id)}
                    data-testid={`unblock-${c.id}`}
                    title="Quitar bloqueo"
                    className="text-neutral-400 hover:text-[#22C55E]"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* CREATE DIALOG */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="block-contact-dialog" className="bg-[#0A0A0A] border-white/10 text-white rounded-none max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">Bloquear contacto</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label className="micro-label text-neutral-500">Teléfono (E.164)</Label>
              <Input
                data-testid="block-phone-input"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+5350123456"
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 font-mono"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Nombre (opcional)</Label>
              <Input
                data-testid="block-name-input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Ej: Juan Pérez / Estafador conocido"
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Email (opcional)</Label>
              <Input
                data-testid="block-email-input"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="scammer@example.com"
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
              />
            </div>
            <p className="text-[0.65rem] text-neutral-600 -mt-2">Indica al menos uno: teléfono y/o email.</p>
            <div>
              <Label className="micro-label text-neutral-500">Motivo *</Label>
              <Input
                data-testid="block-reason-input"
                required
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                placeholder="Ej: comprobante falsificado en orden #1234"
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10"
              />
            </div>
            <div>
              <Label className="micro-label text-neutral-500">Notas internas</Label>
              <Textarea
                data-testid="block-notes-input"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="Detalles adicionales para el equipo"
                className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[80px]"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setOpen(false)} className="rounded-none">Cancelar</Button>
              <Button
                data-testid="block-submit"
                onClick={submit}
                disabled={saving}
                className="bg-[#EF4444] hover:bg-[#DC2626] text-white rounded-none"
              >
                {saving ? "Bloqueando..." : "Bloquear"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* BULK IMPORT DIALOG */}
      <Dialog open={importOpen} onOpenChange={(o) => { if (!o) resetImport(); else setImportOpen(true); }}>
        <DialogContent data-testid="bulk-import-dialog" className="bg-[#0A0A0A] border-white/10 text-white rounded-none max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl flex items-center gap-2">
              <Upload className="w-6 h-6 text-[#EAB308]" /> Importar lista de estafadores
            </DialogTitle>
            <DialogDescription className="text-neutral-500 text-xs">
              Pega el chat de WhatsApp tal cual. El sistema detectará automáticamente teléfonos, nombres y motivos.
            </DialogDescription>
          </DialogHeader>
          {!importResult ? (
            <div className="space-y-4">
              <div className="bg-[#0F0F0F] border border-white/5 p-3 text-[0.7rem] text-neutral-500 font-mono leading-relaxed">
                <div className="text-[0.65rem] text-neutral-400 mb-2 font-sans uppercase tracking-wider">Ejemplo de formato aceptado:</div>
                Estafador ❌️<br />
                +5359804084<br />
                +5356455618<br />
                📌Son la misma persona<br />
                📌Se hace pasar por Remesero<br />
                <br />
                Juan Pérez<br />
                +1-305-555-1234<br />
                📌Estafó $500 en venta USDT
              </div>
              <div>
                <Label className="micro-label text-neutral-500">Tu lista (uno por línea)</Label>
                <Textarea
                  data-testid="bulk-import-textarea"
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder="Pega aquí el mensaje completo de WhatsApp..."
                  className="rounded-none mt-1 bg-[#0a0a0a] border-white/10 min-h-[280px] font-mono text-xs"
                />
              </div>
              <div className="flex justify-between items-center pt-2">
                <span className="text-[0.65rem] text-neutral-600">
                  Los duplicados se ignoran. Las cuentas activas con números importados quedan en revisión automáticamente.
                </span>
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={resetImport} className="rounded-none">Cancelar</Button>
                  <Button
                    data-testid="bulk-import-submit"
                    onClick={submitBulkImport}
                    disabled={importing || !importText.trim()}
                    className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none"
                  >
                    {importing ? "Importando..." : "Importar"}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4" data-testid="bulk-import-result">
              <div className="grid grid-cols-3 gap-2">
                <div className="tactile-card p-4 text-center">
                  <CheckCircle2 className="w-6 h-6 mx-auto text-[#22C55E] mb-1" />
                  <div className="font-display text-2xl text-[#22C55E]" data-testid="import-count-imported">{importResult.imported_count}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">Importados</div>
                </div>
                <div className="tactile-card p-4 text-center">
                  <SkipForward className="w-6 h-6 mx-auto text-[#EAB308] mb-1" />
                  <div className="font-display text-2xl text-[#EAB308]" data-testid="import-count-skipped">{importResult.skipped_count}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">Duplicados</div>
                </div>
                <div className="tactile-card p-4 text-center">
                  <AlertTriangle className="w-6 h-6 mx-auto text-[#EF4444] mb-1" />
                  <div className="font-display text-2xl text-[#EF4444]" data-testid="import-count-invalid">{importResult.invalid_count}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-neutral-500">Inválidos</div>
                </div>
              </div>
              {importResult.affected_active_accounts > 0 && (
                <div className="border-l-2 border-[#EAB308] bg-[#EAB308]/5 p-3 text-xs text-[#FEF3C7]">
                  ⚠️ <span className="font-semibold">{importResult.affected_active_accounts}</span> cuenta(s) activa(s) en la plataforma coincidía(n) con números importados. Se han movido a <strong>&quot;bajo revisión&quot;</strong> automáticamente y no pueden operar hasta que un miembro autorizado del staff las re-verifique.
                </div>
              )}
              {importResult.invalid?.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Entradas inválidas (no importadas):</div>
                  <div className="bg-[#0F0F0F] border border-[#EF4444]/30 p-2 max-h-32 overflow-y-auto text-xs font-mono">
                    {importResult.invalid.map((it) => (
                      <div key={`${it.phone}-${it.reason}`} className="text-neutral-400">• <span className="text-[#EF4444]">{it.phone}</span> — {it.reason}</div>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex justify-end pt-2">
                <Button
                  data-testid="bulk-import-close"
                  onClick={resetImport}
                  className="bg-[#EAB308] hover:bg-[#FACC15] text-black font-bold rounded-none"
                >
                  Cerrar
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
