# Aprendizajes de testing — suite backend completa (Ago 2026)

## Flakiness conocida al correr `pytest tests/` COMPLETO (1284 tests)
La suite corre contra el servidor vivo + BD compartida de desarrollo. Corridas
completas consecutivas producen 15-30 fallos ROTATIVOS (tests distintos cada
vez) que SIEMPRE pasan en aislamiento. Causas identificadas (01/08/2026):

1. **Rate limits por diseño**: `/api/vip/ledger/email` y `/api/admin/vip-ledger/email`
   tienen límite Mongo (colección `ledger_email_events`, 10/hora por usuario).
   Dos corridas completas en <1h → 429. Limpiar antes de re-correr:
   `db.ledger_email_events.delete_many({})`.
2. **Ventanas TOTP de 30s**: acciones admin sensibles rechazan códigos reusados;
   tests que caen en la misma ventana fallan con 401 esporádicos.
3. **Mutación de usuarios compartidos**: tests que cambian email/phone/kyc de
   `user_test_normal01`/`vip01` sin restaurar corrompen suites hermanas.
   - CORREGIDO: `test_iter52_kyc.py::test_risk_score_no_country_check` ahora
     restaura email/name/phone (antes dejaba `regular@example.com`, que luego
     era bloqueado por el flujo reject-phone → `BLOCKED_CONTACT` en cascada).
   - CORREGIDO: `test_audit_log_and_defensive.py` tiene fixture autouse de
     módulo que restaura `defensive_margin_pct=None` (antes quedaba en 10.0 y
     rompía aprobaciones sin TOTP en otras suites).
   - CORREGIDO: `test_iter110_phase23_ledger_ops.py` ahora usa deltas de
     `vip_balances.USDT` y restaura el saldo (antes inflaba +4000 USDT al VIP
     compartido en cada corrida).
4. **Scheduler vivo**: apscheduler (escaneo de anomalías cada 5 min) puede
   mutar estado durante la corrida.

## Valores canónicos de usuarios de prueba (scripts/seed_test_users.py)
- normal01: normal.test@resilience.com / "Normal Test" / +5350000004
- vip01: vip.test@resilience.com / "VIP Test" / +5350000003
- Si aparece `BLOCKED_CONTACT` en tests: revisar `db.blocked_contacts` por
  docs huérfanos con emails/phones de usuarios de prueba.

## Semánticas de producto que los tests deben respetar
- iter113: depósitos de capital y settlements payout operan sobre
  `users.vip_balances.USDT` (NO sobre `vip_ledger.positive_usdt`).
- iter115: los retiros de capital NO aparecen en `/api/me/transactions`
  (viven en Depósitos y Retiros); sí aparecen en `/api/admin/transactions`.
- iter117: mutaciones de staff requieren `totp_enabled: true` (412 si no).

## Protocolo recomendado
- Verificación por módulos/selección (-k) es confiable; la corrida completa
  requiere: BD saneada + limpiar `ledger_email_events` + tolerar flakes de
  ventana TOTP. Ante fallo en corrida completa: SIEMPRE re-correr el módulo
  aislado antes de asumir regresión.

## iter200 — Full-suite (1554 tests) vs suites aisladas
- Correr `pytest tests/` completo produce ~38 fallos por INTERFERENCIA entre archivos (estado compartido en Mongo: settings globales, usuarios de prueba mutados). TODOS pasan aislados. NO son regresiones — triar siempre re-ejecutando el archivo solo antes de tocar código.
- El full run SÍ vale la pena tras refactors grandes: detectó un decorador de ruta perdido (PUT /admin/orders/{id}/status) que las suites objetivo no cubrían.
- Al extraer una función que está justo debajo de un decorador @router, verificar SIEMPRE que el decorador quede pegado a la función correcta (grep "@router" ±2 líneas tras el edit).
