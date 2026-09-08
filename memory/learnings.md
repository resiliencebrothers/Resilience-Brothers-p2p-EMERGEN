
## Regla crítica de edición (2 incidentes en Jun 2026, iter172-173)
NUNCA emitir múltiples search_replace/create_file al MISMO archivo dentro de un mismo batch paralelo: las ediciones parten del mismo snapshot y la última pisa a las anteriores aunque la herramienta reporte "Edit was successful". Síntomas vistos: proyección perdida en reconciliation_matcher.py, render de pestaña perdido en AdminReconciliation.jsx, bloque i18n perdido en es.json (llegó a producción). Ediciones al mismo archivo → SIEMPRE secuenciales; verificar con lectura/aserción programática después.

## Pytest suite grande (iter242)
- NUNCA lanzar dos pytest en paralelo (misma DB → 80 fallos falsos). pkill + pgrep antes de lanzar. Logs en /app, no /tmp.
- test_iter204_cuban_geocoding depende de Nominatim externo (puede fallar sin regresión; verificar con git stash).
- Estado sucio tras corridas interrumpidas: blocked_contacts puede quedar con entradas que bloquean a usuarios de prueba (BLOCKED_CONTACT 403 en tests de phone) — limpiar residuos.

## Code review iter242 — falsos positivos verificados
- "35 undefined vars" → ruff F821 limpio. "`is` comparisons" → F632 limpio (usan `is not None`).
- TxnFilters.__init__ 9 args = parameter-object FastAPI intencional.

## Turnstile (iter246)
- Captcha real ENFORCED en register/login email. Tests: bypass central en tests/conftest.py (header X-Captcha-Bypass = TURNSTILE_TEST_BYPASS de backend/.env) — NO editar los 9 archivos de tests de auth.
- Playwright/testing agent no puede pasar el captcha (por diseño): probar auth con cookies de sesión, no con login por email.
