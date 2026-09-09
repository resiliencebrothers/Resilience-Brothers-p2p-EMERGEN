# Segunda revisión — Resilience Brothers P2P

**Versión revisada:** `a4b45dc11379bdb941b721c6e790017a9a5e3810`, `main`, commit del 8 de septiembre de 2026 a las 23:00:29 UTC. Comparada con `e8355f042cc4e7155275feb8e13fac4b454b7cc7`.

**Resultado:** hay mejoras comprobables, pero quedan fallos de integridad en estados, recuperación, amortización, inventario y mensajería. Esta revisión identifica **12 hallazgos**, varios como correcciones incompletas de los anteriores y otros derivados de los flujos nuevos. No se modificó código del proyecto ni se operó sobre cuentas reales.

## Qué mejoró

La instalación de dependencias ya funciona en CI. El job de pytest termina con **241 passed, 1 skipped, 1 warning**; ESLint pasa. El job de mypy continúa fallando con **25 errores en 11 archivos**. Es la suite crítica, no la suite completa. Fuente: [ejecución 34288649594](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/actions/runs/34288649594).

En el código se añadieron validación de producto activo/aprobado, moneda explícita de liquidación, conversión de saldos mediante un único update, preparación del importe neto antes de recuperarlo y totales de caja mediante agregación. Las pruebas nuevas de la auditoría ya están incluidas en `Makefile:test-critical`.

Se analizaron sintácticamente **340 archivos Python sin errores de sintaxis**. Se ejecutaron además **11 escenarios aislados** de esta revisión con funciones originales y almacenamiento simulado. Que la suite crítica pase no invalida estos contraejemplos: los casos de interrupción e intercalado fijados aquí no están suficientemente cubiertos por ella.

## Seguimiento de los 12 puntos anteriores

| Anterior | Estado en esta versión |
|---|---|
| R01 — Estados de retiro concurrentes | Parcial. Hay update condicional, pero estado y reembolso aún se exponen por separado: S01. |
| R02 — Reactivar canjes sin cobrar | El camino normal vuelve a cobrar y reservar. Persisten interrupciones y ciclos de pago al vendedor: S02, S04 y S05. |
| R03 — Débitos sin operación | La conversión agrupa saldo origen, comisión y destino. La creación usa `initializing`, pero la recuperación y otros efectos aún tienen huecos: S03, S04 y S10. |
| R04 — Recuperación del bruto | Hay `prepared=false` y recálculo. El plan de amortización no es estable al reintentar: S08. |
| R05 — Dedupe de créditos | El registro duradero cubre el camino normal. Puede faltar si falla su escritura: S06. |
| R06 — Productos inactivos/no aprobados | Corregido en el flujo de compra revisado: chequeo inicial y condiciones al reservar; cubierto por las nuevas pruebas de CI. |
| R07 — USD frente a USDT | Precio, débito principal, reembolso y vendedor usan la moneda declarada; antiguos sin campo mantienen USD. Falta adaptar el cálculo de mensajería: S09. |
| R08 — Amortizar más deuda de la disponible | El update ahora condiciona remanente y orden aplicada. No cerrar aún la lógica completa de amortización por S08. |
| R09 — Ventas rechazadas en estadísticas | Dashboard excluye rechazadas. Control y rotación conservan otra lógica: S11. |
| R10 — Día de Cuba | Límites explícitos corregidos. La selección automática de “hoy” aún toma fecha UTC: S11. |
| R11 — Caja truncada a 20.000 | Corregido en `fund_summary`: agrega importes y denominaciones, y cuenta todos los documentos. No certifica otros exports que aún tienen límites. |
| R12 — CI y cobertura | pytest y lint pasan; regresiones incluidas. Falta mypy: S12. |

## Hallazgos para Emergent

### S01 — Alta: el retiro puede seguir aprobado y reembolsado; un fallo puede también perder el reembolso

**Código:** [backend/routes/admin_withdrawals.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/admin_withdrawals.py), `update_withdrawal` (277–346), `_reconcile_balance_on_status_change` (91–173).

El claim publica el estado nuevo antes de ejecutar la reconciliación. Otra petición puede leer ese estado todavía sin su efecto de saldo. Intercalado reproducido: la primera publica `rejected` y se pausa antes del reembolso; la segunda lee `rejected`, publica `approved` y no vuelve a cobrar porque aún no existe `balance_refunded=true`; la primera continúa y devuelve 100. Resultado: **aprobado y saldo +100**. Ambas peticiones usan el código actual; no necesitan compartir una lectura antigua.

También se reprodujo una interrupción justo después de publicar `rejected`, antes de crear `credit_pending`. Repetir el rechazo no devuelve el dinero porque el estado ya es `rejected`; ambos recuperadores carecen de marcador para resolverlo. Reembolso esperado 100, real 0.

**Corregir:** reclamar una transición intermedia con versión/identidad y su plan persistente de efectos en el mismo update; impedir otra transición hasta completarla. Publicar el estado final solo cuando saldo y evidencia estén consolidados. Reanudar efectos aunque se repita el estado. Bloquear también `initializing` y `failed_init` en el endpoint de retiros: ocultarlos de la lista no impide una llamada directa del personal.

**Aceptación:** fijar pausas después del claim, antes del reembolso y antes del recobro; combinar rechazo/aprobación/pago/cancelación. Verificar consistencia tras cada interrupción y recuperación, no solo al terminar dos requests rápidos.

### S02 — Alta: un rechazo de canje puede quedar con stock o reversos sin completar

**Código:** [backend/routes/admin.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/admin.py), `update_redemption` (665–712), `_apply_rejection_effects` (715–730), `_on_redemption_rejected` (813–844).

`rejection_applied=true` se guarda antes de completar abono, stock, vendedor, fondo y mensajería. Si el abono termina y falla la restitución de stock, el marcador ya fue eliminado. Reintentar `rejected` no ejecuta los efectos porque `rejection_applied` es verdadero.

**Reproducido:** reembolso de 100 aplicado; fallo al devolver una unidad; tras repetir rechazo y ejecutar recuperadores, stock sigue 0 en vez de 1.

Existe un hueco similar al pasar a `delivered`: se publica el estado antes de crear la intención del pago al vendedor, y repetir el mismo estado no reanuda ese pago. Además, `confirm_pickup_by_code` (571–586) conserva una escritura de entrega solo por ID: puede sobrescribir un rechazo concurrente tras haber leído el canje como pendiente.

**Corregir:** un plan de transición con pasos persistentes e idempotentes para cada efecto. No usar un flag de “completado” al iniciar. Encaminar también entrega por código por la misma máquina de estados condicional.

**Aceptación:** caída después de cada efecto de rechazo/entrega; rechazo simultáneo con recogida por código. El reintento debe completar exactamente lo que falta, sin ocultar efectos pendientes.

### S03 — Alta: el recuperador de `initializing` puede devolver fondos de una operación ya activada

**Código:** [backend/services/credit_recovery.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/credit_recovery.py), `heal_initializing_ops` (124–184); [backend/routes/orders.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/orders.py), activación de canjes (543–553) y retiros (946–952).

El recuperador lee candidatos antiguos y devuelve saldo/stock antes de reclamar que siguen siendo suyos. Si el creador sigue vivo y activa el documento mientras tanto, el recuperador devuelve el dinero y luego su update condicional a `failed_init` no coincide. La devolución ya ocurrió.

**Reproducido:** retirada inicialmente `initializing`, débito registrado de 100; el creador la activa justo antes del abono de recuperación. Resultado: **`pending` con 100 devueltos**. El supuesto necesario es una petición lenta o reanudada después del umbral de 120 segundos.

La variante inversa también requiere protección: el creador no comprueba el resultado del update de activación y puede devolver éxito o crear efectos auxiliares aunque el recuperador haya ganado.

**Corregir:** reclamar propiedad de recuperación mediante estado/versionado antes de compensar. El creador debe perder su derecho a seguir cobrando/activando si vence esa propiedad. Comprobar siempre el resultado de activación; no basta con releer antes de devolver.

**Aceptación:** pausar creador antes del débito y antes de activar; ejecutar recuperador y reanudarlo. Probar ambos órdenes. Resultado único: activa y cobrada, o fallida y totalmente compensada.

### S04 — Alta: la reactivación de canjes vuelve a crear débitos y reservas huérfanos

**Código:** [backend/routes/admin.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/admin.py), `_reactivate_rejected_redemption` (733–804).

Se generan op_ids con un nonce, se reserva stock y se cobra antes de registrar el nuevo estado. Esos op_ids no quedan en un plan de reactivación del canje. Si el proceso falla antes del claim final, el documento sigue `rejected`, ya sin dinero ni stock, y los recuperadores no lo seleccionan.

**Reproducido:** canje rechazado de 100 con una unidad restituida; fallo después de reservar y cobrar, antes de guardar `pending`. Tras recuperar: estado rechazado, saldo 0 y stock 0. Reintentar crea otros identificadores y puede cobrar/reservar nuevamente si hay recursos suficientes.

**Corregir:** persistir primero un intento de reactivación recuperable con identificadores estables, importe, moneda y cantidad; reclamar estado intermedio y completar o compensar todas sus fases. El ID del intento no debe regenerarse en un retry del mismo intento.

**Aceptación:** interrupciones antes/después de reserva, cobro, claim y compensaciones; una sola reactivación o restitución total comprobable.

### S05 — Alta: una venta entregada, rechazada y reactivada puede dejar al vendedor sin cobrar

**Código:** [backend/routes/admin.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/admin.py), `_reactivate_rejected_redemption` (770–804), `_credit_vendor_for_redemption` (412–451), `_record_vendor_commission_inflow` (482–506).

La reactivación restablece los flags de rechazo, pero conserva `vendor_credited_at`, `vendor_credit_reversed_at` y marcas de fondos del ciclo anterior. El helper de pago exige que `vendor_credited_at` esté vacío, por lo que impide el abono del nuevo ciclo aunque el pago anterior se haya revertido.

**Reproducido:** venta de 100, comisión 5%, vendedor previamente pagado y revertido; reactivación a entregado cobra otros 100 al comprador, pero el vendedor recibe **0 en vez de 95**. Se sustituyó únicamente el guard de disponibilidad de mensajería y los servicios externos; se ejecutaron la reactivación y el helper de crédito originales.

**Corregir:** modelar cada ciclo de liquidación y reverso con identificadores persistentes separados. Revisar también el restablecimiento de los fondos de empresa y la comisión. Borrar flags indiscriminadamente sin separar ciclos permitiría nuevos duplicados.

**Aceptación:** `entregado → rechazado → pendiente → entregado`, tanto vendedor VIP como producto de empresa; verificar cliente, vendedor, comisión y fondo. Repetir todo el ciclo.

### S06 — Alta, condicionada a fallo: el registro duradero de créditos puede no existir

**Código:** [backend/services/balances.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/balances.py), `_ops_log` (173–191), `_registry_push` (194–195), `credit_balance_idempotent` (198–221).

El saldo se modifica primero. Después se intenta guardar `credit_ops`, pero cualquier fallo se silencia. El registro embebido sigue limitado, ahora a 2.000 operaciones. Si falla el log y el identificador acaba expulsado, un marcador/reintento antiguo vuelve a acreditar. Los reintentos que encuentran el identificador embebido tampoco reparan el log faltante porque `_ops_log` solo se ejecuta si el saldo se modifica.

**Reproducido:** falla la escritura del log del primer crédito de 100; luego entran 2.000 créditos de 1 y se repite el original. Saldo **2.200 en vez de 2.100**. La prueba de CI cubre expulsión con log existente, no log fallido.

**Corregir:** garantizar retención del identificador hasta confirmar su persistencia duradera y la imposibilidad de replay del origen; reparar logs pendientes. La marca duradera y el saldo deben formar parte de un protocolo consistente, no dos escrituras de mejor esfuerzo. No resolver insertando primero la marca y abonando después sin recuperación.

**Aceptación:** fallos del índice/insert del log y caída entre saldo y log; superar 2.000 operaciones, reintentar y ejecutar múltiples recuperadores sin duplicar ni omitir dinero.

### S07 — Alta, condicionada al volumen: el stock hereda el límite de deduplicación de 500 operaciones

**Código:** [backend/services/inventory.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/inventory.py), `apply_stock_idempotent` (48–71); [backend/services/credit_recovery.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/credit_recovery.py) (157–168 y 187–205).

`applied_stock_ops` conserva solo las últimas 500 operaciones y no tiene un registro duradero equivalente. Al expulsar un ID se puede reaplicar el descuento. El recuperador de canjes también usa la presencia del ID para decidir si devuelve stock: puede dejar de reconocer una reserva real antigua.

**Reproducido:** stock inicial 1.000, descuento de 1, otros 500 movimientos de +1; repetir el descuento original deja **1.498 en lugar de 1.499**. El riesgo de negocio requiere un intento/movimiento aún pendiente que sobreviva hasta esa expulsión.

**Corregir:** conservar el vínculo de cada reserva/movimiento y compensación durante toda su vida recuperable. Aplicar una estrategia duradera que no pueda separarse del cambio de stock; cubrir también los identificadores de reverso.

**Aceptación:** movimiento interrumpido seguido de 501 operaciones sobre el mismo producto; reintentar/recuperar mantiene exactamente el stock esperado.

### S08 — Alta: la misma amortización cambia de importe al reintentarse con varias deudas

**Código:** [backend/services/balances.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/balances.py), `_apply_capital_request_repayment` (331–423), especialmente el porcentaje de la deuda activa más antigua (380–381).

El reintento recuerda contribuciones pasadas, pero vuelve a calcular el presupuesto desde las deudas actualmente activas. Si la primera llamada liquidó la deuda más antigua, el porcentaje del nuevo primer préstamo puede ser diferente.

**Reproducido con las funciones originales:** deuda A de 10 al 10%, deuda B de 100 al 50%; una entrada de 100 aplica 10 a A y devuelve neto 90. Al repetir la misma orden, usa el 50% de B, aplica otros 40 y devuelve neto **50**. Una recuperación tras fallar la preparación del marcador puede por ello acreditar menos dinero del debido. El caso de CI tiene una sola deuda y no detecta esta variante.

**Corregir:** persistir el porcentaje/presupuesto y el plan definitivo por orden antes de aplicar amortizaciones. Un retry debe continuar el mismo plan y producir el mismo neto, aunque cambien las deudas, sus porcentajes o lleguen otras órdenes.

**Aceptación:** al menos dos deudas con porcentajes distintos; liquidación de la primera y caída antes del neto; varias ejecuciones de la misma orden y recuperadores simultáneos.

### S09 — Alta: mensajería convertida a USD se descuenta ahora como USDT

**Código:** [backend/routes/orders.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/orders.py), cotización del canje (433–469) y débito (535–537); [backend/routes/admin.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/admin.py), `_price_redemption_fee` (916–936) y `_apply_courier_fee_balance_delta` (864–883); [backend/services/courier_fee.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/courier_fee.py), `fee_in_currency` (73–77).

El saldo de los canjes nuevos ya es USDT, pero las llamadas de tarifa siguen pasando `USD`. `fee_currency_amount` es, por tanto, un importe convertido a USD. Ese número se suma al cobro en USDT. También se calcula la exención por umbral como si el total del producto estuviera en USD.

**Reproducido:** con una tasa sintética 1 USDT = 1,10 USD, una tarifa de 10 USDT se convierte a 11 USD y el helper de cobro descuenta **11 USDT**. No se afirma que esa sea la tasa actual de producción; si la tasa es 1:1, el fallo queda oculto.

**Corregir:** pasar la moneda de liquidación real a todas las cotizaciones, cargos, ajustes, exenciones y previews. Nuevos USDT; antiguos sin campo USD. Separar nombres de campos/unidades para impedir mezclar cifras convertidas.

**Aceptación:** tasas diferentes de 1:1, tarifa por km y municipio, exención, cobro manual y automático, nuevos y antiguos, incluido reembolso.

### S10 — Alta: recuperar inventario no completa la contabilidad y puede conservar una venta imposible

**Código:** [backend/services/credit_recovery.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/credit_recovery.py), recuperación de movimientos (187–205); [backend/services/inventory.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/inventory.py), `record_movement` (182–204), `_record_fund_flow` (319–350), `build_dashboard` (526–548).

Si no hay stock al recuperar una venta, se marca a la vez `stock_applied=true` y `stock_apply_failed=true`, conservando la fila `venta`. Dashboard y cierre no filtran ese fallo y pueden contabilizar ingresos por una venta no aplicada. **Reproducido:** stock 0, venta pendiente de 1 por 100; recuperador conserva esa venta de 100 con ambos flags verdaderos.

En la recuperación exitosa solo se aplica stock; no se llama ni se programa `_record_fund_flow`. Si se interrumpió antes de ese efecto, el movimiento queda completado en stock sin su entrada/salida al fondo. Este segundo punto se confirma por lectura del flujo, no mediante contabilidad real.

**Corregir:** estados inequívocos de pendiente/completado/fallido y efectos contables idempotentes recuperables. Excluir operaciones no completadas de KPIs. Completar fondo de empresa y demás efectos antes de marcar toda la operación como finalizada.

**Aceptación:** recuperar con stock insuficiente y con stock suficiente; en el primer caso no reconocer venta y en el segundo conciliar stock, movimiento y fondo, una sola vez.

### S11 — Media: control/rotación aún difieren del dashboard y “hoy” cambia antes en UTC

**Código:** [backend/services/inventory.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/services/inventory.py), `build_control_rows` (376–392), `build_rotation` (429–449), `build_dashboard` (518–548); [backend/routes/inventory.py](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/a4b45dc11379bdb941b721c6e790017a9a5e3810/backend/routes/inventory.py), valores de fecha por defecto (306–330).

Se corrigió la exclusión de canjes rechazados en dashboard, pero control/rotación siguen agregando las filas `venta` sin consultar rechazo. La misma compra anulada puede desaparecer de ingresos y continuar inflando velocidad de ventas o unidades de hoy.

Los límites `_day_bounds` ya usan Cuba, pero varias funciones eligen primero `today = iso(now_utc())[:10]`. A las 22:30 de Cuba del 8 de septiembre, la fecha UTC es 9: se aplican correctamente límites de Cuba al día equivocado. El cierre diario obtiene el día local y por eso difiere.

**Evidencia:** inspección estática. No se realizaron pruebas visuales de estas pantallas.

**Corregir:** un único criterio de venta efectiva para todos los indicadores; obtener “hoy” en `America/Havana` antes de convertir límites a UTC. Conservar límites exclusivos al día siguiente.

**Aceptación:** venta rechazada, consulta de control/rotación/dashboard/cierre, fechas sin parámetros a las 22:30 de Cuba y cambios de horario.

### S12 — Media: mypy sigue bloqueando CI

**Fuente:** [job de mypy 102269992313](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/actions/runs/34288649594/job/102269992313).

Resultado: **25 errores en 11 archivos, 94 archivos comprobados**. Ya no falla instalación: ahora se ejecuta el analizador y detecta problemas de tipos/anotaciones.

Ejemplos: `routes/orders.py:926–927` accede a un valor potencialmente `None`; `routes/orders.py:1412` mezcla tipos en la construcción de expresiones; `routes/admin_withdrawals.py:463` devuelve valor donde la firma declara `None`; hay anotaciones ausentes y tipos incompatibles en caja, inventario, fondos, entregas, usuarios, referidos, municipio, etiquetas y rutas geográficas. No todos estos avisos equivalen a un bug de ejecución demostrado.

**Corregir:** revisar las 25 observaciones, ajustar guardas cuando corresponda y anotar correctamente estructuras heterogéneas. No silenciar globalmente mypy ni degradar el gate para obtener verde.

**Aceptación:** pytest, ESLint y mypy pasan sobre el mismo commit; después ejecutar la suite completa y el build del frontend. Mantener la prueba omitida identificada con su motivo.

## Prioridad de trabajo

1. **S01–S04:** asegurar que ningún estado final se publique sin plan recuperable y que creador, administrador y recuperador no compitan por los mismos efectos.
2. **S05–S10:** ciclo de vendedor, retención duradera, amortización estable, moneda de mensajería y contabilidad de inventario.
3. **S11–S12:** coherencia de indicadores y cierre de CI.

Las pruebas de concurrencia deben fijar el punto de pausa, no depender de que dos requests coincidan por casualidad. Inyectar también fallo después de cada escritura relevante, recuperar y volver a repetir. Reconciliar saldos y registros históricos solo con un procedimiento explícito sobre datos verificados; este informe no demuestra incidentes reales.

## Límites de esta revisión

Se revisaron los cambios y sus flujos relacionados, con comparación de código y lectura directa de CI. Las reproducciones locales extraen funciones originales y sustituyen MongoDB, autenticación y servicios externos; no son pruebas HTTP integrales ni simulan todas las garantías de MongoDB. Los casos de concurrencia se ordenan deliberadamente para probar intercalados concretos. No se invocó el servidor real ni se cargaron credenciales del proyecto.

No se ejecutó localmente la suite completa ni se certificó la seguridad de producción, configuración efectiva, infraestructura, migraciones existentes o cada pantalla. Los resultados de pytest/lint/mypy citados corresponden a GitHub Actions en el commit fijado. El código actual estaba todavía en ese mismo commit al finalizar la comprobación.

## Anexo: salida de las reproducciones aisladas

```json
[
  {
    "case": "withdrawal rejection crash then retry and heal",
    "status": "rejected",
    "refund_expected": 100,
    "refund_actual": 0
  },
  {
    "case": "withdrawal overlapping rejection and approval with fresh second read",
    "status": "approved",
    "refunded_balance": 100
  },
  {
    "case": "redemption rejection stock failure after refund then retry and heal",
    "refund": 100,
    "stock_expected": 1,
    "stock_actual": 0,
    "rejection_applied": true
  },
  {
    "case": "initialization recovery versus activation",
    "status": "pending",
    "refunded_balance": 100
  },
  {
    "case": "reactivation crash after stock and debit",
    "status": "rejected",
    "remaining_balance": 0,
    "remaining_stock": 0,
    "healer_recovers": false
  },
  {
    "case": "credit durable-log failure plus 2000 newer operations",
    "expected_balance": 2100,
    "actual_balance": 2200
  },
  {
    "case": "stock replay after 500 operations",
    "expected_stock": 1499,
    "actual_stock": 1498
  },
  {
    "case": "same repayment order retried with two debts at different percentages",
    "first_net": 90.0,
    "retry_net": 50.0,
    "second_debt_remaining": 60.0
  },
  {
    "case": "vendor sale reactivated after prior payment and reversal",
    "buyer_debit": 100,
    "vendor_credit_expected": 95,
    "vendor_credit_actual": 0
  },
  {
    "case": "courier fee calculated USD but charged USDT at USDT-to-USD 1.1",
    "quoted_fee_usdt": 10,
    "debited_usdt": 11
  },
  {
    "case": "inventory recovery insufficient stock",
    "stock_applied": true,
    "stock_apply_failed": true,
    "sale_row_total": 100
  }
]
```

## Anexo: script para reproducir en Emergent

Guardar el bloque como `revision_checks.py` fuera del proyecto y ejecutar `python revision_checks.py /ruta/al/backend` con Python y Pydantic 2. Solo lee funciones del backend; la base de datos está simulada en memoria. No importa el servidor ni modifica el proyecto. Algunos servicios externos se sustituyen o no están disponibles; los logs de esas dependencias no forman parte de los fallos bajo prueba. Las aserciones validan que el fallo existe en esta versión; al corregirlo, deben transformarse en pruebas que exijan el resultado correcto.

```python
import ast, asyncio, copy, json, sys, types, uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field, ValidationError

ROOT=Path(sys.argv[1])
class HTTPException(Exception):
    def __init__(self,status_code,detail): self.status_code=status_code; self.detail=detail
def get(d,k):
    for p in k.split('.'):
        if not isinstance(d,dict) or p not in d: return None
        d=d[p]
    return d
def put(d,k,v):
    parts=k.split('.')
    for p in parts[:-1]: d=d.setdefault(p,{})
    d[parts[-1]]=v
def match(d,q):
    for k,v in q.items():
        a=get(d,k)
        if isinstance(v,dict):
            for op,b in v.items():
                if op=='$ne' and (a==b or isinstance(a,list) and b in a): return False
                if op=='$exists' and (a is not None)!=b: return False
                if op=='$gte' and (a is None or a<b): return False
                if op=='$in' and a not in b: return False
        elif a!=v: return False
    return True
class Coll:
    def __init__(self,rows=()): self.rows=copy.deepcopy(list(rows)); self.fail=None
    def find(self,q,*args):
        rows=[copy.deepcopy(d) for d in self.rows if match(d,q)]
        class Cursor:
            def sort(self,*args):return self
            async def to_list(self,n):return rows[:n]
        return Cursor()
    async def find_one(self,q,*args): return next((copy.deepcopy(d) for d in self.rows if match(d,q)),None)
    async def update_one(self,q,u):
        if self.fail and self.fail(q,u): raise RuntimeError('simulated database failure')
        for d in self.rows:
            if not match(d,q): continue
            before=copy.deepcopy(d)
            for k,v in u.get('$set',{}).items(): put(d,k,copy.deepcopy(v))
            for k,v in u.get('$inc',{}).items(): put(d,k,(get(d,k) or 0)+v)
            for k,v in u.get('$push',{}).items():
                old=get(d,k) or []
                put(d,k,(old+v['$each'])[v['$slice']:] if isinstance(v,dict) and '$each' in v else old+[v])
            for k in u.get('$unset',{}): d.pop(k,None)
            return types.SimpleNamespace(matched_count=1,modified_count=int(before!=d))
        return types.SimpleNamespace(matched_count=0,modified_count=0)
class DB:
    def __init__(self,**cols): self.__dict__.update(cols)
    def __getitem__(self,k): return getattr(self,k)
def load(path,names,env):
    tree=ast.parse((ROOT/path).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name in names]
    for n in nodes: n.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/path),'exec'),env)
async def noop(*a,**kw): pass
def env(db): return dict(db=db,HTTPException=HTTPException,datetime=datetime,timezone=timezone,Optional=Optional,Any=Any,Request=object,BaseModel=BaseModel,Field=Field,Literal=Literal,uuid=uuid,iso=lambda x:x.isoformat(),now_utc=lambda:datetime.now(timezone.utc))
def recovery(e):
    load('services/balances.py',['credit_balance_idempotent','accumulate_vip_balance'],e)
    load('services/credit_recovery.py',['pending_marker','apply_and_clear'],e)
    m=types.ModuleType('services.credit_recovery')
    m.pending_marker=e['pending_marker'];m.apply_and_clear=e['apply_and_clear']
    sys.modules['services']=types.ModuleType('services');sys.modules['services.credit_recovery']=m

# Simulador estricto de las operaciones de documento usadas en estas pruebas.
import logging
from datetime import timedelta
def get(d,k):
    parts=k.split('.')
    if isinstance(d,list):return [get(x,k) for x in d]
    if not isinstance(d,dict):return None
    a=d.get(parts[0])
    return get(a,'.'.join(parts[1:])) if len(parts)>1 else a
def eq(a,b):return b in a if isinstance(a,list) and not isinstance(b,list) else a==b
def condition(a,v):
    if not isinstance(v,dict):return eq(a,v)
    for op,b in v.items():
        if op=='$ne': ok=not eq(a,b)
        elif op=='$exists':ok=(a is not None)==b
        elif op=='$gte':ok=a is not None and a>=b
        elif op=='$lte':ok=a is not None and a<=b
        elif op=='$lt':ok=a is not None and a<b
        elif op=='$in':ok=any(eq(a,x) for x in b)
        elif op=='$nin':ok=not any(eq(a,x) for x in b)
        elif op=='$not':ok=not condition(a,b)
        elif op=='$elemMatch':ok=isinstance(a,list) and any(match(x,b) for x in a)
        else:raise AssertionError('unsupported operator '+op)
        if not ok:return False
    return True
def match(d,q):
    for k,v in q.items():
        if k=='$or':ok=any(match(d,x) for x in v)
        else:ok=condition(get(d,k),v)
        if not ok:return False
    return True
class Cursor:
    def __init__(self,rows):self.rows=copy.deepcopy(rows)
    def sort(self,k,order=1):self.rows.sort(key=lambda d:get(d,k) or '',reverse=order<0);return self
    async def to_list(self,n):return self.rows[:n]
class Coll:
    def __init__(self,rows=()):self.rows=copy.deepcopy(list(rows));self.fail=None;self.before_update=None
    def find(self,q,*args):return Cursor([d for d in self.rows if match(d,q)])
    async def find_one(self,q,*args):return next((copy.deepcopy(d) for d in self.rows if match(d,q)),None)
    async def create_index(self,*a,**kw):pass
    async def insert_one(self,d):
        if self.fail and self.fail({},d):raise RuntimeError('simulated insert failure')
        self.rows.append(copy.deepcopy(d))
    async def delete_one(self,q):
        for i,d in enumerate(self.rows):
            if match(d,q):self.rows.pop(i);return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)
    async def update_one(self,q,u):
        if self.before_update:await self.before_update(q,u)
        if self.fail and self.fail(q,u):raise RuntimeError('simulated update failure')
        for d in self.rows:
            if not match(d,q):continue
            before=copy.deepcopy(d)
            for k,v in u.get('$set',{}).items():put(d,k,copy.deepcopy(v))
            for k,v in u.get('$inc',{}).items():put(d,k,(get(d,k) or 0)+v)
            for k,v in u.get('$push',{}).items():
                old=get(d,k) or []
                put(d,k,(old+v['$each'])[v['$slice']:] if isinstance(v,dict) and '$each' in v else old+[v])
            for k in u.get('$unset',{}):d.pop(k,None)
            return types.SimpleNamespace(matched_count=1,modified_count=int(before!=d))
        return types.SimpleNamespace(matched_count=0,modified_count=0)
class DB:
    def __init__(self,**cols):self.__dict__.update(cols)
    def __getattr__(self,k):v=Coll();setattr(self,k,v);return v
    def __getitem__(self,k):return getattr(self,k)
def runtime(db):
    e=env(db);e.update(timedelta=timedelta,logger=logging.getLogger('test'),_OPS_LOG_READY=False)
    load('services/balances.py',['_ops_log','_registry_push','credit_balance_idempotent','debit_balance_idempotent','op_was_applied','_apply_capital_request_repayment','accumulate_vip_balance'],e)
    load('services/credit_recovery.py',['pending_marker','apply_and_clear','heal_initializing_ops','heal_pending_credits'],e)
    load('services/inventory.py',['apply_stock_idempotent','movement_delta'],e)
    e['PENDING_COLLECTIONS']=('orders','deposits','redemptions','withdrawals','deliveries','capital_requests','users')
    sys.modules['services']=types.ModuleType('services')
    for mod,names in {'balances':['credit_balance_idempotent','debit_balance_idempotent','op_was_applied','_apply_capital_request_repayment'],'credit_recovery':['pending_marker','apply_and_clear'],'inventory':['apply_stock_idempotent','movement_delta']}.items():
        m=types.ModuleType('services.'+mod)
        for n in names:setattr(m,n,e[n])
        sys.modules['services.'+mod]=m
    return e
async def main():
    out=[]
    # 1. Caída después de publicar rejected, antes de guardar intención.
    db=DB(withdrawals=Coll([{'id':'w','user_id':'u','currency':'USDT','amount_usd':100,'status':'pending','method':'transfer'}]),users=Coll([{'user_id':'u','vip_balances':{'USDT':0}}]))
    e=runtime(db)
    async def actor(*a,**kw):return {'user_id':'admin','role':'admin'}
    e.update(require_permission=actor,_enforce_totp_step_up=noop,_assert_paid_lock=lambda *a:None,_enforce_employee_currency_scope=lambda *a:None,_collect_payout_evidence=lambda *a:None,_validate_paid_evidence=lambda *a:None,_assert_cash_courier_ready=noop,_post_status_side_effects=noop)
    load('routes/admin_withdrawals.py',['update_withdrawal','_reconcile_balance_on_status_change'],e)
    reconcile=e['_reconcile_balance_on_status_change']
    async def crash(*a):raise RuntimeError('crash after status claim')
    e['_reconcile_balance_on_status_change']=crash
    try:await e['update_withdrawal']('w',{'status':'rejected'},None)
    except RuntimeError:pass
    e['_reconcile_balance_on_status_change']=reconcile
    await e['update_withdrawal']('w',{'status':'rejected'},None)
    await e['heal_initializing_ops']();await e['heal_pending_credits']()
    assert get(db.users.rows[0],'vip_balances.USDT')==0 and 'credit_pending' not in db.withdrawals.rows[0]
    out.append({'case':'withdrawal rejection crash then retry and heal','status':'rejected','refund_expected':100,'refund_actual':0})

    # 1b. Dos peticiones reales de función: la segunda lee el nuevo estado
    # mientras la primera aún no registró el reembolso.
    db.withdrawals.rows=[{'id':'w2','user_id':'u','currency':'USDT','amount_usd':100,'status':'pending','method':'transfer'}]
    started=asyncio.Event();resume=asyncio.Event()
    async def pause_reconcile(w,status,upd):
        if status=='rejected':started.set();await resume.wait()
        await reconcile(w,status,upd)
    e['_reconcile_balance_on_status_change']=pause_reconcile
    task=asyncio.create_task(e['update_withdrawal']('w2',{'status':'rejected'},None))
    await started.wait()
    await e['update_withdrawal']('w2',{'status':'approved'},None)
    resume.set();await task
    assert db.withdrawals.rows[0]['status']=='approved' and db.withdrawals.rows[0]['balance_refunded'] and get(db.users.rows[0],'vip_balances.USDT')==100
    out.append({'case':'withdrawal overlapping rejection and approval with fresh second read','status':'approved','refunded_balance':100})

    # 1c. Rechazo de canje: falla la devolución de stock después del abono.
    rr={'id':'r','user_id':'u','product_id':'p','status':'pending','quantity':1,'total_usd':100,'settlement_currency':'USDT'}
    db=DB(redemptions=Coll([rr]),users=Coll([{'user_id':'u','vip_balances':{'USDT':0}}]),products=Coll([{'id':'p','stock':0}]))
    e=runtime(db);e.update(require_permission=actor,_log_redemption_status_change=noop)
    load('routes/admin.py',['update_redemption','_apply_rejection_effects','_on_redemption_rejected'],e)
    db.products.fail=lambda q,u:True
    try:await e['update_redemption']('r',{'status':'rejected'},None)
    except RuntimeError:pass
    db.products.fail=None
    await e['update_redemption']('r',{'status':'rejected'},None)
    await e['heal_initializing_ops']();await e['heal_pending_credits']()
    assert get(db.users.rows[0],'vip_balances.USDT')==100 and db.products.rows[0]['stock']==0
    out.append({'case':'redemption rejection stock failure after refund then retry and heal','refund':100,'stock_expected':1,'stock_actual':0,'rejection_applied':db.redemptions.rows[0]['rejection_applied']})

    # 2. Recuperador leyó initializing; creador activa antes de la devolución.
    db=DB(users=Coll([{'user_id':'u','vip_balances':{'USDT':0},'applied_credit_ops':['debit-w']}]),withdrawals=Coll([{'id':'w','user_id':'u','currency':'USDT','amount_usd':100,'status':'initializing','init_op_id':'debit-w','created_at':'2000-01-01T00:00:00+00:00'}]))
    e=runtime(db)
    async def activate(q,u):
        if u.get('$inc',{}).get('vip_balances.USDT')==100:
            db.users.before_update=None
            await db.withdrawals.update_one({'id':'w','status':'initializing'},{'$set':{'status':'pending'},'$unset':{'init_op_id':''}})
    db.users.before_update=activate
    await e['heal_initializing_ops']()
    assert db.withdrawals.rows[0]['status']=='pending' and get(db.users.rows[0],'vip_balances.USDT')==100
    out.append({'case':'initialization recovery versus activation','status':'pending','refunded_balance':100})

    # 3. Reactivar canje: caída tras cobro antes del claim final.
    r={'id':'r','user_id':'u','product_id':'p','status':'rejected','rejection_applied':True,'quantity':1,'total_usd':100,'settlement_currency':'USDT'}
    db=DB(redemptions=Coll([r]),users=Coll([{'user_id':'u','vip_balances':{'USDT':100}}]),products=Coll([{'id':'p','stock':1}]))
    e=runtime(db);load('routes/admin.py',['_reactivate_rejected_redemption'],e)
    db.redemptions.fail=lambda q,u:get(u,'$set.status')=='pending'
    try:await e['_reactivate_rejected_redemption'](copy.deepcopy(r),'r','pending',{'user_id':'admin'})
    except RuntimeError:pass
    db.redemptions.fail=None;await e['heal_initializing_ops']()
    assert get(db.users.rows[0],'vip_balances.USDT')==0 and db.products.rows[0]['stock']==0 and db.redemptions.rows[0]['status']=='rejected'
    out.append({'case':'reactivation crash after stock and debit','status':'rejected','remaining_balance':0,'remaining_stock':0,'healer_recovers':False})

    # 4. Dedupe duradero: log fallido y expulsión después de 2000 operaciones.
    db=DB(users=Coll([{'user_id':'u','vip_balances':{'USDT':0}}]));e=runtime(db)
    db.credit_ops.fail=lambda q,u:True
    await e['credit_balance_idempotent']('u','USDT',100,'first')
    db.credit_ops.fail=None
    for i in range(2000):await e['credit_balance_idempotent']('u','USDT',1,f'next-{i}')
    duplicated=await e['credit_balance_idempotent']('u','USDT',100,'first')
    assert duplicated and get(db.users.rows[0],'vip_balances.USDT')==2200
    out.append({'case':'credit durable-log failure plus 2000 newer operations','expected_balance':2100,'actual_balance':2200})

    # 5. Stock: registro limitado a 500, reintento de una operación antigua.
    db=DB(products=Coll([{'id':'p','stock':1000}]));e=runtime(db)
    await e['apply_stock_idempotent']('p',-1,'original')
    for i in range(500):await e['apply_stock_idempotent']('p',1,f'other-{i}')
    st=await e['apply_stock_idempotent']('p',-1,'original')
    assert st=='applied' and db.products.rows[0]['stock']==1498
    out.append({'case':'stock replay after 500 operations','expected_stock':1499,'actual_stock':1498})

    # 6. Una orden reintentada cambia el porcentaje al liquidar la deuda más antigua.
    db=DB(capital_requests=Coll([{'id':'d1','user_id':'u','currency_code':'USDT','status':'disbursed','discount_pct':10,'debt_remaining':10,'disbursed_at':'2000-01-01'}, {'id':'d2','user_id':'u','currency_code':'USDT','status':'disbursed','discount_pct':50,'debt_remaining':100,'disbursed_at':'2000-01-02'}]));e=runtime(db)
    n1=await e['_apply_capital_request_repayment']('u','USDT',100,'o')
    n2=await e['_apply_capital_request_repayment']('u','USDT',100,'o')
    assert n1==90 and n2==50
    out.append({'case':'same repayment order retried with two debts at different percentages','first_net':n1,'retry_net':n2,'second_debt_remaining':db.capital_requests.rows[1]['debt_remaining']})

    # 7. Entrega-rechazo-reactivación mantiene vendor_credited_at antiguo.
    r={'id':'r','user_id':'buyer','product_id':'p','quantity':1,'total_usd':100,'settlement_currency':'USDT','status':'rejected','rejection_applied':True,'vendor_owner_id':'seller','vendor_credited_at':'2000-01-01','vendor_credit_net':95,'vendor_credit_reversed_at':'2000-01-02'}
    db=DB(redemptions=Coll([r]),products=Coll([{'id':'p','stock':1,'owner_id':'seller'}]),users=Coll([{'user_id':'buyer','vip_balances':{'USDT':100}},{'user_id':'seller','vip_balances':{'USDT':0}}]));e=runtime(db)
    e.update(_assert_redemption_courier_ready=noop)
    load('routes/admin.py',['_reactivate_rejected_redemption','_credit_vendor_for_redemption','_record_vendor_commission_inflow'],e)
    await e['_reactivate_rejected_redemption'](r,'r','delivered',{'user_id':'admin'})
    assert get(db.users.rows[0],'vip_balances.USDT')==0 and get(db.users.rows[1],'vip_balances.USDT')==0 and db.redemptions.rows[0]['status']=='delivered'
    out.append({'case':'vendor sale reactivated after prior payment and reversal','buyer_debit':100,'vendor_credit_expected':95,'vendor_credit_actual':0})

    # 8. Mensajería aún se cotiza en USD pero se cobra la cifra en USDT.
    db=DB(users=Coll([{'user_id':'u','vip_balances':{'USDT':100}}]));e=runtime(db)
    load('services/balances.py',['decrement_balance','get_user_balance','convert_from_usdt'],e)
    sys.modules['services.balances'].decrement_balance=e['decrement_balance'];sys.modules['services.balances'].get_user_balance=e['get_user_balance']
    async def rate_lookup():return {('USDT','USD'):1.1}
    e['build_rate_lookup']=rate_lookup
    load('services/courier_fee.py',['fee_in_currency'],e)
    fee=await e['fee_in_currency'](10,'USD')
    load('routes/admin.py',['_apply_courier_fee_balance_delta'],e)
    await e['_apply_courier_fee_balance_delta']({'user_id':'u','settlement_currency':'USDT'},fee)
    assert fee==11 and get(db.users.rows[0],'vip_balances.USDT')==89
    out.append({'case':'courier fee calculated USD but charged USDT at USDT-to-USD 1.1','quoted_fee_usdt':10,'debited_usdt':11})

    # 9. Movimiento imposible recuperado se marca stock_applied aunque no se aplicó.
    db=DB(products=Coll([{'id':'p','stock':0}]),inventory_movements=Coll([{'id':'m','product_id':'p','type':'venta','quantity':1,'total':100,'needs_stock':True,'stock_applied':False,'created_at':'2000-01-01T00:00:00+00:00'}]));e=runtime(db)
    await e['heal_initializing_ops']()
    m=db.inventory_movements.rows[0]
    assert m['stock_applied'] and m['stock_apply_failed'] and db.products.rows[0]['stock']==0
    out.append({'case':'inventory recovery insufficient stock','stock_applied':True,'stock_apply_failed':True,'sale_row_total':100})
    print(json.dumps(out,indent=2))
asyncio.run(main())

```

