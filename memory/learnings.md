
## Regla crítica de edición (2 incidentes en Jun 2026, iter172-173)
NUNCA emitir múltiples search_replace/create_file al MISMO archivo dentro de un mismo batch paralelo: las ediciones parten del mismo snapshot y la última pisa a las anteriores aunque la herramienta reporte "Edit was successful". Síntomas vistos: proyección perdida en reconciliation_matcher.py, render de pestaña perdido en AdminReconciliation.jsx, bloque i18n perdido en es.json (llegó a producción). Ediciones al mismo archivo → SIEMPRE secuenciales; verificar con lectura/aserción programática después.
