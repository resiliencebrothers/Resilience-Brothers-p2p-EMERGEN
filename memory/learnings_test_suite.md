# Aprendizajes de la suite de tests (iter170)

## Contaminación de estado entre tests (causas raíz conocidas)
1. **conftest `_autoseed_sessions` (autouse, por función)**: re-siembra sesiones Y
   la fila KYC `verified` (`kyc_{uid}`) para vip01/normal01 antes de CADA test.
   Los tests de KYC (test_iter52_kyc) deben borrar KYC DENTRO del cuerpo del test
   (después del fixture), no solo en setup_module.
2. **Rates compartidos**: `test_rate_usdt_cup` es canónico 380/395/410.
   test_iter161 lo sobrescribía a 350 sin restaurar → rompía test_vip_convert.
   Fix: teardown_module en iter161 restaura el canon. Si un test necesita otro
   rate, DEBE restaurarlo o usar una moneda sintética (ej. ZZT).
3. **TOTP anti-replay**: tests que reutilizan el mismo código TOTP dentro de la
   ventana de 30s fallan en runs consecutivos — falsos positivos.
4. **Flakes bajo carga**: test_iter97_live_stream (SSE hello) puede fallar cuando
   la suite completa martillea el server. Pasa en aislamiento.

## Reporte de calidad (falsos positivos documentados)
- "489 comparaciones `is` incorrectas" → son `is None`/`is not None`/`is True`
  (idioma correcto). ruff F632 = 0 violaciones reales.
- "23 variables indefinidas" → ruff F821 + pyflakes = 0. Heurística del tool.
- PDFs generate_company_closing/monthly_audit/profitability ya son orquestadores
  compuestos; su longitud es ensamblaje lineal de story, no complejidad.

## Regla operativa
Ejecutar la suite completa muta la DB de test (KYC, rates, orders). Tras un run
completo, tests individuales pueden fallar por estado sucio: re-verificar en
aislamiento antes de asumir regresión.

## iter256 — nuevos aprendizajes
- Flake de fecha: tests de inventario/dashboard que calculan "hoy" con time.strftime/datetime.utcnow fallan entre 20:00 y 00:00 de Cuba (UTC ya cambió de día). Usar `from tests.conftest import today_havana`.
- Motor + _run(loop nuevo): NO llamar `_run` dos veces en el mismo test (pool ligado al primer loop ⇒ "Event loop is closed"). Consolidar todo en UNA corrutina y hacer las mutaciones intermedias con pymongo síncrono dentro de ella.
- Semántica S05: reactivar un canje re-registra el fund inflow del nuevo ciclo; los tests de asientos contables deben esperar pares inflow/outflow POR CICLO (no 2 asientos totales).
