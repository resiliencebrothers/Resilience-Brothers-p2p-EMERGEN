**Revisión de mensajería y verificación de los dos pendientes del informe general — Resilience**

Versión revisada: `6cc9ee527ed5e328f909a17c6488f62eff64a432` (`6cc9ee5`), rama `main`, 22 de septiembre de 2026. La rama seguía apuntando a esta versión al terminar la comprobación.

**Resultado:** los pendientes W01 y W02 del informe general quedan corregidos en las reproducciones revisadas. Mensajería todavía tiene seis grupos de problemas confirmados: cuatro de prioridad alta y dos de prioridad media. Cinco amplían casos de la auditoría anterior que solo quedaron resueltos parcialmente; uno afecta al nuevo registro de efectivo del mensajero.

El código del repositorio permaneció intacto. Todas las reproducciones propias usaron datos sintéticos y funciones del código actual; no se realizaron operaciones sobre cuentas ni bases de datos reales.

**Qué se contrastó**

Se compararon las correcciones con `Auditoria_Mensajeria_y_Mejoras_eeed556.md` —MSG01 a MSG11— y `Verificacion_Pendientes_Resilience_d66806c.md` —W01 y W02, además de la cobertura de CI W03—. El segundo informe es el que contenía los dos pendientes de la revisión general de lotes, intercambios y mercado. La auditoría separada de monedas, tasas y convertidor FX01–FX11 no se vuelve a evaluar en este informe.

| Caso anterior | Estado en esta revisión | Evidencia |
|---|---|---|
| W01 · Recuperación incompleta de lotes | Corregido en los casos probados | Con una inserción fallida quedan 499 registros y el plan sigue pendiente; cerrar devuelve 409. La recuperación completa 500/500 y entonces permite cerrar. Un escritor retrasado no añade registros después del cierre. |
| W02 · Reverso perdido en fondo de empresa | Corregido en ambas variantes | El fallo de un reverso deja el ingreso recuperable; la recuperación produce un ingreso y un reverso, neto 0. También se resuelve el rechazo concurrente durante la reconstrucción de marcas. |
| W03 · Pruebas recientes fuera de CI | Corregido para los archivos comprobados | CI incluye las iteraciones 287–291 y termina correctamente en este mismo commit. |
| MSG01 · Avance atrasado de una entrega | Corregido en las dos carreras originales | Cancelación y reasignación ganan; el avance obsoleto devuelve 409. |
| MSG02 · Entregas duplicadas | Corregido para nuevas creaciones concurrentes | Dos creaciones: 200/409, una entrega y una comisión de 8 USDT. Se ejecutó la inicialización del índice con datos sintéticos. |
| MSG03 · Origen rechazado | Parcial; queda N03 | La creación y aceptación se bloquean y el rechazo normal cancela la recogida. Una escritura fallida todavía deja una recogida aceptada operativa. |
| MSG04 · Sincronización de tarifa y entrega | Parcial; queda N02 | Se recuperan la creación y actualización fallidas sin cobrar de nuevo. Dos sincronizaciones que terminan fuera de orden aún dejan una tarifa desactualizada. |
| MSG05 · Comisión pagada mutable | Parcial; queda N01 | La carrera original, con confirmación totalmente terminada, conserva el histórico y señala el ajuste. La ventana entre el inicio del pago y el sello final sigue permitiendo modificar la comisión mostrada. |
| MSG06 · Rechazo de reserva atrasado | Corregido en el caso probado | Devuelve 409 y conserva la reserva del nuevo mensajero. |
| MSG07 · Límites que ocultan datos | Parcial; queda N05 | 51 entregas confirmadas suman correctamente 408 USDT; una reserva antigua ya aparece aunque haya 50 trabajos libres. Persisten límites en reservas dirigidas y totales diarios. |
| MSG08 · GPS de otro mensajero o antiguo | Corregido en los casos originales | Reasignar elimina las coordenadas anteriores; una posición de hace 24 horas queda marcada y presentada como antigua. |
| MSG09 · Cruce de conversaciones | Parcial; queda N06 | Se descartan respuestas GET y páginas antiguas de otro chat. El envío pendiente del chat anterior todavía puede volver a cargarlo sobre el actual. |
| MSG10 · Refresco del panel y enlace de push | Corregido en los casos probados | Funcionan los callbacks de evento, intervalo y recuperación de visibilidad. El service worker abre `/dashboard/deliveries`, una ruta existente. |
| MSG11 · Tarifas no finitas | Corregido en el caso original | NaN, Infinity, −Infinity y precio negativo devuelven 400 sin alterar el precio guardado. |

Las correcciones de W01 se encuentran en [la resolución del plan de carga](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/vip_batch_ops.py#L62). Las de W02 se ven en [el cierre de las marcas después del reverso](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/credit_recovery.py#L229) y en [la nueva lectura del estado antes de compensar](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/credit_recovery.py#L577). Los controles de intercambios y mercado que ya pasaban en el informe anterior también siguen pasando en esta ejecución.

**Problemas que Emergent debe resolver**

| ID | Prioridad | Problema | Resultado reproducido |
|---|---|---|---|
| N01 | Alta | La tarifa puede cambiar después de iniciar el pago de la comisión y antes de sellar la entrega. | Se abonan 8 USDT y el panel muestra 16 USDT ganados, sin ajuste pendiente. |
| N02 | Alta | Una sincronización vieja puede sobrescribir una tarifa nueva que ya terminó de sincronizarse. | Origen con tarifa 30 USDT, entrega con tarifa 20 USDT y sin tarea pendiente; se pagan 16 USDT de comisión en lugar de 24 al 80 %. |
| N03 | Alta | El rechazo de un depósito no conserva una tarea recuperable si falla la cancelación de su recogida. | Depósito rechazado; después de dos recuperaciones el mensajero todavía puede poner la recogida en camino. |
| N04 | Alta | Un fallo al registrar efectivo recogido se oculta y no se recupera automáticamente. | Recogida de 1.500 USD marcada como realizada, con cero eventos en el registro de efectivo. |
| N05 | Media | Siguen existiendo límites sin paginación o agregación completa. | Se muestran 50 de 51 reservas dirigidas; el resumen diario cuenta 2.000 de 2.001 entregas. |
| N06 | Media | Un envío pendiente de otro chat puede contaminar el chat actual. | Con B seleccionado aparecen el contexto de A y mensajes de A y B; se borra el borrador de B. |

**N01 — Comisión e histórico incoherentes durante el pago.**

La confirmación fija `payout_credited=True` y `courier_share_paid_usdt=8`, pero conserva temporalmente `status="delivered"` mientras ejecuta el abono. El actualizador de tarifa solo excluye `confirmed` y `cancelled`: aún puede escribir una comisión distinta durante ese intervalo. Después se sella la entrega y los resúmenes siguen sumando `courier_share_usdt`, el campo que acaba de cambiar. [Actualización de la comisión](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/deliveries.py#L438), [inicio del pago y sello](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/deliveries.py#L572) y [total mostrado al mensajero](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/routes/deliveries.py#L100).

Reproducción: entrega realizada, tarifa 10 USDT y comisión 8; iniciar confirmación y detener el abono al usuario después del claim; modificar la tarifa a 20; reanudar y ejecutar dos recuperaciones. El saldo abonado y la instantánea pagada son 8, pero `courier_share_usdt` y el total de ganancias muestran 16. No existe `fee_adjustment_pending`.

Corrección propuesta: hacer que las modificaciones de tarifa respeten también el inicio del pago y su versión; congelar de forma coherente todos los importes liquidados y usar esos importes en los informes. Si la nueva tarifa ya se cobró, conservar un ajuste explícito e idempotente hasta resolverlo. No basta con excluir el estado `confirmed`.

Criterio de aceptación: repetir la pausa exacta entre claim y abono; el histórico y el total pagado deben seguir coincidiendo con 8. Si corresponde aumentar la comisión a 16, la diferencia debe permanecer pendiente y registrarse una sola vez al liquidarla. Verificar también la variante de anular la tarifa en ese intervalo.

**N02 — Sincronización fuera de orden que pierde la tarifa vigente.**

`sync_delivery_from_doc` lee la versión pendiente, actualiza la entrega y luego borra únicamente la tarea que leyó. Ese filtro protege el borrado, pero no impide que la escritura sobre la entrega use valores antiguos después de una sincronización más nueva. [Lectura y limpieza de la tarea](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/deliveries.py#L501) y [escritura sin versión en la entrega](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/deliveries.py#L438).

Reproducción: partir de tarifa 10; cambiar a 20 y detener la primera sincronización justo antes de escribir la entrega; cambiar a 30 y dejar terminar la segunda sincronización; reanudar la primera. El origen queda en 30, la entrega vuelve a 20 y ambas tareas terminan sin dejar trabajo pendiente. Dos recuperaciones no corrigen el resultado. Al completar la entrega se abonan 16 USDT; con la tarifa vigente de 30 y reparto del 80 %, corresponden 24.

Corrección propuesta: usar una revisión monotónica aplicada también en la entrega, o serializar las sincronizaciones por operación con un protocolo recuperable. La validación de versión y la escritura deben impedir que un ejecutor antiguo retroceda el estado. Una lectura previa adicional por sí sola deja otra ventana de concurrencia.

Criterio de aceptación: forzar el orden de escritura 30→20; el resultado debe permanecer en tarifa 30 y comisión 24, sin un segundo cargo al cliente. Una recuperación repetida debe ser idempotente.

**N03 — Recogida aceptada que continúa después de rechazar el depósito.**

El rechazo actualiza el depósito antes de intentar cancelar la entrega. Si la cancelación falla, la excepción solo se registra en logs. No queda una tarea durable de propagación del rechazo y los avances de una entrega ya aceptada no comprueban nuevamente el origen. [Rechazo y excepción](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/routes/deposits.py#L497), [cancelación de entrega](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/deliveries.py#L340) y [avance del mensajero](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/routes/deliveries.py#L461).

Reproducción: depósito de efectivo de 1.500 USD con recogida ya aceptada; rechazarlo e inyectar un único fallo de escritura al cancelar la entrega; retirar el fallo y ejecutar dos recuperaciones. El rechazo devuelve 200 y la transición posterior a `on_the_way` también devuelve 200. La nueva comprobación al aceptar protege las entregas que aún no se habían aceptado, pero no esta variante.

Corrección propuesta: persistir la intención de cancelar o abrir una incidencia junto con el rechazo y reintentar hasta resolverla. Comprobar la compatibilidad del origen en las transiciones relevantes, coordinando las carreras con el movimiento físico. Si ya hubo recogida, mantenerla como incidencia trazable en vez de ocultar el movimiento.

Criterio de aceptación: después del fallo temporal y la recuperación, una recogida que todavía no se realizó debe quedar cancelada; un avance posterior debe devolver conflicto. Si la recogida física gana la carrera, debe quedar una incidencia pendiente visible. No basta con una notificación o un log.

**N04 — Efectivo recogido que desaparece del registro del mensajero.**

Es un problema del nuevo módulo de custodia de efectivo. Primero se cambia la entrega a `delivered`; después `auto_events_for_delivered` intenta crear el evento. El helper captura el error y lo deja solo en logs, sin una tarea de recuperación. Repetir el mismo avance tampoco vuelve a ejecutar el registro: el estado ya no permite esa transición. [Llamada después de cambiar el estado](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/routes/deliveries.py#L548) y [registro automático y manejo de errores](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/services/courier_cash.py#L64).

Reproducción: recogida de depósito de 1.500 USD, estado `arrived`; ejecutar la inicialización que añade el PIN y usar ese PIN válido; inyectar el fallo al insertar `courier_cash_events`. La transición responde 200 y queda `delivered`. Tras retirar el fallo y ejecutar dos recuperaciones siguen existiendo cero eventos. Repetir `delivered` responde 400.

Esto prueba una omisión en el control del efectivo a rendir; no demuestra que el dinero haya desaparecido físicamente ni que haya ocurrido en producción.

Corrección propuesta: grabar una tarea de registro de efectivo en la misma operación que sella el movimiento físico. Procesarla y limpiarla solo cuando exista el evento idempotente; usar la misma clave `op_key` tanto en el flujo normal como en el recuperador. Añadir una reconciliación para entregas ya realizadas cuyo evento automático falte.

Criterio de aceptación: después de un fallo y dos recuperaciones debe existir exactamente un evento `collected` de 1.500 USD y el pendiente de rendición debe reflejarlo. Repetir el recuperador no debe duplicarlo. Aplicar el mismo criterio a la entrega física de retiros.

**N05 — Registros y totales todavía truncados.**

Las ganancias históricas del mensajero ya se agregan correctamente, pero la consulta de reservas dirigidas sigue devolviendo como máximo 50, sin paginación, y el resumen administrativo del día suma una lista limitada a 2.000. [Consulta de reservas](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/routes/deliveries.py#L69) y [resumen diario](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/backend/routes/deliveries.py#L144).

Se reprodujeron dos variantes: con 51 reservas para el mismo mensajero aparecen 50; con 2.001 entregas confirmadas en el mismo día, cada una con comisión de 8, se informan 2.000 y 16.000 USDT en lugar de 2.001 y 16.008 USDT. La segunda requiere ese volumen diario; no se presume que la plataforma ya lo alcance.

Corrección propuesta: paginar los listados y calcular los totales con agregación sobre todos los resultados del filtro. Presentar el total real y permitir recorrer todas las páginas; evitar depender de subir el límite.

Criterio de aceptación: recuperar las 51 reservas sin pérdidas ni duplicados y obtener el conteo y suma correctos para 2.001 confirmaciones, independientemente del tamaño de página.

**N06 — El envío del chat anterior sigue contaminando el actual.**

Los GET que ya estaban en vuelo al cambiar de entrega quedan correctamente invalidados. Sin embargo, `send` conserva el `load` de la conversación anterior. Cuando termina el POST, ejecuta ese `load` capturando la generación actual, por lo que su resultado vuelve a considerarse válido. También limpia el texto aunque ahora pertenezca al chat nuevo. [Generación capturada al cargar](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/frontend/src/components/DeliveryChatDialog.jsx#L51) y [continuación del envío](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/frontend/src/components/DeliveryChatDialog.jsx#L109).

Reproducción con los callbacks reales: enviar en A y dejar su POST pendiente; cambiar a B, cargar sus mensajes y escribir un borrador; resolver el POST de A. Se ejecuta un nuevo GET de A que pasa el control de generación. B sigue seleccionado, pero el contexto mostrado cambia a A, se mezclan mensajes de A/B y el borrador de B queda vacío.

No se observó una evasión de los permisos del servidor: la prueba usa dos conversaciones a las que el mismo usuario tiene acceso. El fallo es de aislamiento del estado visible y puede inducir respuestas en el hilo equivocado.

Corrección propuesta: capturar entrega y generación al iniciar el POST; comprobar ambas antes de cualquier efecto posterior sobre texto, carga, errores o estado de envío. Una función de carga antigua tampoco debe poder validar una conversación distinta por capturar una generación nueva.

Criterio de aceptación: al resolver el envío de A después de abrir B, B conserva su contexto, mensajes y borrador; no se aplica ninguna carga de A a su pantalla. Mantener las pruebas ya correctas de GET atrasado, paginación y conservación del mensaje frontera.

**Validación y alcance de la conclusión**

La ejecución propia registra **74 comprobaciones satisfactorias**: 58 verificaciones y 8 controles de backend, más 8 comprobaciones de frontend. Los **7 escenarios negativos** se agrupan en los **6 problemas** anteriores porque N05 tiene dos reproducciones. Son comprobaciones del harness de auditoría, no 74 tests de pytest ni una certificación de ausencia de bugs.

El backend ejecuta funciones originales extraídas por AST, con base de datos en memoria y pausas controladas entre lecturas/escrituras. Se sustituyen autenticación, notificaciones y servicios externos para aislar los flujos; por tanto, este informe no certifica permisos HTTP, infraestructura ni comportamiento de una base de datos de producción. Los índices únicos relevantes se simulan y el código de inicialización de entregas se ejecuta donde aplica. Las propiedades de concurrencia dependen de los filtros y órdenes de escritura examinados, además de la simulación.

El frontend ejecuta callbacks y hooks extraídos del código, junto con el manejador real del service worker, con solicitudes simuladas. No se ejecutó una sesión completa de navegador ni se inspeccionó la aplicación desplegada.

Además se comprobaron los resultados remotos de [GitHub Actions, ejecución 35728161255](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/actions/runs/35728161255), correspondiente exactamente a `6cc9ee5`: **551 pruebas aprobadas, 1 omitida y 1 advertencia**; mypy sin errores en **102 archivos** y ESLint correcto. La selección de CI incluye las nuevas regresiones de mensajería y W01/W02, según [Makefile](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/6cc9ee527ed5e328f909a17c6488f62eff64a432/Makefile#L58). No equivale a haber ejecutado todos los archivos de pruebas del repositorio.

Los archivos usados por las reproducciones y las referencias principales —39 fuentes— se cotejaron por hash de blob con el árbol del commit. No se deduce de estas pruebas que los fallos hayan ocurrido en cuentas reales. Tampoco se declara terminada una auditoría de todas las mejoras nuevas de PIN, incidencias, métricas o migración de datos históricos.

**Entrega para Emergent**

Priorizar N01–N04 antes de cerrar la revisión de mensajería. Añadir las seis familias de casos a pruebas automatizadas, conservando las regresiones actuales de W01/W02 y los flujos que ya pasan. Para N01, N02, N03, N04 y N06 son necesarias pausas o fallos en los puntos descritos; un flujo secuencial sin fallos no verifica esas correcciones.

Se adjuntan a continuación los resultados y los scripts de reproducción. Los scripts documentan el estado de esta versión: las aserciones de `findings` esperan observar el fallo auditado. Al convertirlos en tests de aceptación de una corrección, usar los resultados esperados descritos arriba.

Para reproducir en una copia aislada del commit, extraer ambos scripts de los bloques siguientes. El de Python necesita Python 3.12 y Pydantic 2; el de JavaScript usa módulos integrados de Node. Pasar la ruta del backend al primero y la raíz del repositorio al segundo:

```bash
python audit_verify_6cc9ee5.py /ruta/copia-6cc9ee5/backend
node audit_frontend_6cc9ee5.cjs /ruta/copia-6cc9ee5
```

La suite suministrada no arranca el servidor, no lee variables de conexión y no ejecuta peticiones reales. Genera únicamente la salida de auditoría y una fixture JSON local de chat. Las rutas y funciones del repositorio se leen sin modificarlas.


**Anexo: audit_6cc9ee5_metadata.json**

SHA-256: `62e108f25c883a09ba2469a353d5651ae6c54df60979bffb362536947c134ed0`

```json
{
  "commit": "6cc9ee527ed5e328f909a17c6488f62eff64a432",
  "date_utc": "2026-09-22T12:56:39.537216+00:00",
  "head_rechecked_unchanged": true,
  "repository": "resiliencebrothers/Resilience-Brothers-p2p-EMERGEN",
  "backend_execution": "AST original functions and synthetic in-memory DB; no application startup, no live requests",
  "frontend_execution": "Original JS callbacks/hooks and service-worker handler; no browser E2E",
  "python": "3.12.14",
  "remote_ci_run": 35728161255,
  "source_files_verified": [
    {
      "path": ".github/workflows/ci.yml",
      "git_blob_sha": "624b846d83f399e1b0f2bbf78bca5d97b630c830"
    },
    {
      "path": "Makefile",
      "git_blob_sha": "86e13048282f6082f2068e9c19cecd1ead1cc511"
    },
    {
      "path": "backend/routes/admin.py",
      "git_blob_sha": "3c1bb3437f47289663b8d0436bf4fb4cef67c4d8"
    },
    {
      "path": "backend/routes/admin_withdrawals.py",
      "git_blob_sha": "b6fc109495dc6b4c9b32ab75090be58ddcb1f783"
    },
    {
      "path": "backend/routes/deliveries.py",
      "git_blob_sha": "a0eb33a5fc0d84b296c26463c60b86841f2d6d62"
    },
    {
      "path": "backend/routes/delivery_chat.py",
      "git_blob_sha": "ee4c64c052fe587b0ba9f5ab7a1206edc88b379a"
    },
    {
      "path": "backend/routes/deposits.py",
      "git_blob_sha": "e272083893b6627e907ec56f16cfdd570353ffd1"
    },
    {
      "path": "backend/routes/municipality_rates.py",
      "git_blob_sha": "c70552b785d1cb23c9b6c84afa2c472f750cd923"
    },
    {
      "path": "backend/routes/orders.py",
      "git_blob_sha": "b460877fa750c0ed4eb12fd81d6ab584817fc97a"
    },
    {
      "path": "backend/routes/vip_batches.py",
      "git_blob_sha": "aeb82bc5eabf14dada026292e31978507251d399"
    },
    {
      "path": "backend/scheduler.py",
      "git_blob_sha": "68d9bf6bd847261a86da0a5c72dffccfdc10c8b9"
    },
    {
      "path": "backend/server.py",
      "git_blob_sha": "7a1959042b9af43dca71377baecd32fec2981643"
    },
    {
      "path": "backend/services/balances.py",
      "git_blob_sha": "b74afd053bae03e33652b844aedff45d5b1d55f8"
    },
    {
      "path": "backend/services/company_funds_common.py",
      "git_blob_sha": "54adbe20451639cc3c10c4162d8cd8c5e8e39ea0"
    },
    {
      "path": "backend/services/courier_cash.py",
      "git_blob_sha": "ab399db464b36bd4cf265f60469deee98305fc59"
    },
    {
      "path": "backend/services/courier_fee.py",
      "git_blob_sha": "375718b2cce038ec8a90b8d28d81783ce0e3b7b0"
    },
    {
      "path": "backend/services/credit_markers.py",
      "git_blob_sha": "5fa4b689e5a0cb72875780befb311cc559c1d4a2"
    },
    {
      "path": "backend/services/credit_recovery.py",
      "git_blob_sha": "a8a63929154fafe7885b463b4297f51a4901f306"
    },
    {
      "path": "backend/services/deliveries.py",
      "git_blob_sha": "7fbc3526e3f2eb40e991273387a80981ca301677"
    },
    {
      "path": "backend/services/delivery_rules.py",
      "git_blob_sha": "8146363430f61b6e7e05756ea9d7e33c68e6fd2e"
    },
    {
      "path": "backend/services/delivery_settlement.py",
      "git_blob_sha": "8dbc8ce0df148b6412f6056096c75c28a14a0258"
    },
    {
      "path": "backend/services/inventory.py",
      "git_blob_sha": "c2ca5ff45700ff7df6eaf4203b836432f6413500"
    },
    {
      "path": "backend/services/marketplace_fx.py",
      "git_blob_sha": "2f2a5c70377679218f463abab5e4f8317da648f9"
    },
    {
      "path": "backend/services/orders_helpers.py",
      "git_blob_sha": "8a51ee7ab41b7a9ee1ebe3ef747dc44b68624c2a"
    },
    {
      "path": "backend/services/payment_accounts.py",
      "git_blob_sha": "30be5b12628b5eb457737b8c13fb361ab4d50f5a"
    },
    {
      "path": "backend/services/permissions.py",
      "git_blob_sha": "103fe01ba103fae8682a6b6e9c448e111ede187f"
    },
    {
      "path": "backend/services/rate_tiers.py",
      "git_blob_sha": "6d1aeb61979f33dce097bac39d708cb5f1f809e4"
    },
    {
      "path": "backend/services/vip_batch_ops.py",
      "git_blob_sha": "0f10e484876d3473b30119a995e63145c3684c33"
    },
    {
      "path": "backend/tests/test_iter288_audit_mensajeria.py",
      "git_blob_sha": "928b58bd8aac114f2bda9261eb7db4603cc4da8d"
    },
    {
      "path": "backend/tests/test_iter289_fase_a_mejoras.py",
      "git_blob_sha": "b3212102f375c15069f3318637c68546be981d18"
    },
    {
      "path": "backend/tests/test_iter290_fase_b_mejoras.py",
      "git_blob_sha": "165cf0e68936ea2713a32e1c2c85e6be8437a150"
    },
    {
      "path": "backend/tests/test_iter291_w01_w02_fase_c.py",
      "git_blob_sha": "630dde9832a339254147ff3e5f64375ceddc6791"
    },
    {
      "path": "frontend/public/service-worker.js",
      "git_blob_sha": "511014ea75cdcfd688c04bcd9ed8dee2bb472ab2"
    },
    {
      "path": "frontend/src/App.js",
      "git_blob_sha": "acc73b0947c07291b3c4ff0bafce93b9a62c361f"
    },
    {
      "path": "frontend/src/components/DeliveryChatDialog.jsx",
      "git_blob_sha": "e422c6f7965b9037ac41823c40a7a1134ad5e2ab"
    },
    {
      "path": "frontend/src/components/DeliveryTrackCard.jsx",
      "git_blob_sha": "c25b07ed9896a848ec566158ea0d12de14d02950"
    },
    {
      "path": "frontend/src/pages/Dashboard.jsx",
      "git_blob_sha": "66438c46e24db1b4da5198f20cbec838b450d6fe"
    },
    {
      "path": "frontend/src/pages/dashboard/CourierPanel.jsx",
      "git_blob_sha": "0910f136a3a10f0fa921d4147b1ba683e5fb9d13"
    },
    {
      "path": "frontend/src/services/deliveryEta.js",
      "git_blob_sha": "a4ef76283c1f1efdc6ff30f394a3a86482a30a8d"
    }
  ],
  "source_count": 39,
  "backend_positive_checks": 66,
  "frontend_positive_checks": 8,
  "bug_groups": 6,
  "negative_scenarios": 7,
  "repository_code_modified": false
}
```


**Anexo: audit_6cc9ee5_ci_summary.json**

SHA-256: `d72b85bdda2acb26660440e0a668f53769fdcb47262125d1f8aafd16ddc72d6c`

```json
{
  "run_id": 35728161255,
  "sha": "6cc9ee527ed5e328f909a17c6488f62eff64a432",
  "url": "https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/actions/runs/35728161255",
  "jobs": [
    {
      "job_id": 106746816447,
      "name": "Backend · mypy",
      "conclusion": "success",
      "excerpts": [
        "2026-09-22T12:37:21.2630266Z Success: no issues found in 102 source files"
      ]
    },
    {
      "job_id": 106746816682,
      "name": "Backend · pytest",
      "conclusion": "success",
      "excerpts": [
        "2026-09-22T12:37:36.8180518Z \ttests/test_iter287_audit_v01_v03.py \\",
        "2026-09-22T12:37:36.8180811Z \ttests/test_iter288_audit_mensajeria.py \\",
        "2026-09-22T12:37:36.8181146Z \ttests/test_iter289_fase_a_mejoras.py \\",
        "2026-09-22T12:37:36.8181418Z \ttests/test_iter290_fase_b_mejoras.py \\",
        "2026-09-22T12:37:36.8181679Z \ttests/test_iter291_w01_w02_fase_c.py \\",
        "2026-09-22T12:41:22.2407145Z 551 passed, 1 skipped, 1 warning in 224.62s (0:03:44)"
      ]
    },
    {
      "job_id": 106746816786,
      "name": "Frontend · ESLint",
      "conclusion": "success",
      "excerpts": [
        "2026-09-22T12:36:36.7458152Z Done in 17.29s.",
        "2026-09-22T12:36:39.0805899Z Done in 2.16s."
      ]
    }
  ]
}
```


**Anexo: audit_verify_6cc9ee5_results.json**

SHA-256: `15fcd4b645e1d1d3715dd46dcc49a1cec403016fd8137daca73db46d72f182de`

```json
{
  "commit": "6cc9ee527ed5e328f909a17c6488f62eff64a432",
  "checks": [
    {
      "id": "EX01",
      "case": "pending and rejected cash orders do not credit residue",
      "orders": 2,
      "balance_usd": 0
    },
    {
      "id": "EX01",
      "case": "approved residue recovers once after credit failure",
      "balance_usd": 0.75,
      "healer_cycles": 2
    },
    {
      "id": "EX02",
      "case": "same-state retry after failed marker creation credits once",
      "usdt": 100
    },
    {
      "id": "EX02",
      "case": "rejection wins before accumulation claim",
      "balance_usdt": 0
    },
    {
      "id": "R01",
      "case": "rejection after monetary claim blocked",
      "http": [
        200,
        409
      ],
      "final_status": "approved",
      "balance_usdt": 100,
      "healer_cycles": 2
    },
    {
      "id": "ME01",
      "case": "fee charge",
      "kind": "withdrawal",
      "http": [
        200,
        409
      ],
      "final_balance": 90,
      "fee": 10.0
    },
    {
      "id": "ME01",
      "case": "fee refund",
      "kind": "withdrawal",
      "http": [
        200,
        409
      ],
      "final_balance": 100,
      "fee": 0.0
    },
    {
      "id": "ME01",
      "case": "fee interruption",
      "kind": "withdrawal",
      "http": [
        500,
        200
      ],
      "final_balance": 90,
      "fee": 10.0
    },
    {
      "id": "R02",
      "case": "aborted courier fee cannot debit with later funds",
      "kind": "withdrawal",
      "initial_balance": 5,
      "new_income": 100,
      "final_balance": 105,
      "recorded_fee": 0,
      "http": 400
    },
    {
      "id": "ME01",
      "case": "fee charge",
      "kind": "redemption",
      "http": [
        200,
        409
      ],
      "final_balance": 90,
      "fee": 10.0
    },
    {
      "id": "ME01",
      "case": "fee refund",
      "kind": "redemption",
      "http": [
        200,
        409
      ],
      "final_balance": 100,
      "fee": 0.0
    },
    {
      "id": "ME01",
      "case": "fee interruption",
      "kind": "redemption",
      "http": [
        500,
        200
      ],
      "final_balance": 90,
      "fee": 10.0
    },
    {
      "id": "R02",
      "case": "aborted courier fee cannot debit with later funds",
      "kind": "redemption",
      "initial_balance": 5,
      "new_income": 100,
      "final_balance": 105,
      "recorded_fee": 0,
      "http": 400
    },
    {
      "id": "R02",
      "case": "refund waits for failed fee rollback then returns only paid money",
      "initial_balance": 100,
      "final_balance": 100,
      "concurrent_reject_http": 409,
      "fee_update_http": 400
    },
    {
      "id": "LO01",
      "case": "atomic quota under normal concurrent uploads",
      "http": [
        200,
        409
      ],
      "stored": 500
    },
    {
      "id": "LO01",
      "case": "all historical overflow items remain visible",
      "returned": 550
    },
    {
      "id": "R03",
      "case": "close waits for active upload",
      "close_while_upload_http": 409,
      "append_http": 200,
      "final_close_http": 200,
      "stored_items": 1
    },
    {
      "id": "R03",
      "case": "partial insert releases only remaining quota",
      "stored_after_failed_insert": 475,
      "reserved_after_failed_insert": 475,
      "subsequent_http": [
        200,
        409
      ],
      "final_stored": 500,
      "final_reserved": 500
    },
    {
      "id": "LO02",
      "case": "blocked account cannot create or append",
      "account_status": "blocked",
      "http": [
        403,
        403
      ]
    },
    {
      "id": "LO02",
      "case": "blocked account cannot create or append",
      "account_status": "under_review",
      "http": [
        403,
        403
      ]
    },
    {
      "id": "MR01",
      "case": "refund after vendor delivery",
      "interrupted": false,
      "buyer": 100,
      "seller": 0,
      "stock": 1,
      "healer_cycles": 2
    },
    {
      "id": "MR01",
      "case": "refund after vendor delivery",
      "interrupted": true,
      "buyer": 100,
      "seller": 0,
      "stock": 1,
      "healer_cycles": 2
    },
    {
      "id": "MR02",
      "case": "company sale trace recovery",
      "failed_collection": null,
      "buyer": 90,
      "stock": 1,
      "sales": 1,
      "fund_inflow": 10
    },
    {
      "id": "MR02",
      "case": "company sale trace recovery",
      "failed_collection": "inventory_movements",
      "buyer": 90,
      "stock": 1,
      "sales": 1,
      "fund_inflow": 10
    },
    {
      "id": "MR02",
      "case": "company sale trace recovery",
      "failed_collection": "company_fund_adjustments",
      "buyer": 90,
      "stock": 1,
      "sales": 1,
      "fund_inflow": 10
    },
    {
      "id": "R04",
      "case": "original company-sale route and recoverer write only one sale",
      "real_units_sold": 1,
      "recorded_sale_movements": 1,
      "recorded_sales_CUP": 1000.0,
      "buyer_usdt": 90,
      "stock": 1
    },
    {
      "id": "R05",
      "case": "late sale inflow is compensated after rejection",
      "final_status": "rejected",
      "buyer_usdt": 100,
      "stock": 2,
      "fund_net_usdt": 0
    },
    {
      "id": "ME02",
      "case": "cancel wins against stale confirmation",
      "http": [
        200,
        409
      ],
      "courier_usdt": 0
    },
    {
      "id": "ME02",
      "case": "new reservation prevents old courier claim",
      "http": 403,
      "reserved_for": "courier-b"
    },
    {
      "id": "ME03",
      "case": "pickup linked deposit settles once",
      "interrupted": false,
      "client_usd": 100,
      "courier_usdt": 8,
      "healer_cycles": 2
    },
    {
      "id": "ME03",
      "case": "pickup linked deposit settles once",
      "interrupted": true,
      "client_usd": 100,
      "courier_usdt": 8,
      "healer_cycles": 2
    },
    {
      "id": "ME04",
      "case": "recent page, scoped reads and previous page",
      "total": 301,
      "recent": 300,
      "older": 1
    },
    {
      "id": "V01",
      "case": "overlapping recovery restores burned unpaid fee",
      "initial_usdt": 100,
      "product_paid": 100,
      "fee_after_recovery": 0,
      "fee_update_http": 400,
      "reject_http": 200,
      "final_usdt": 100,
      "healer_cycles_after_rejection": 2
    },
    {
      "id": "V01",
      "case": "failed rollback write is recovered before exact refund",
      "initial_usdt": 100,
      "product_paid": 100,
      "fee_after_recovery": 0,
      "debit_log_state": "burned",
      "injected_write_failures": 1,
      "live_overlap": false,
      "reject_http": 200,
      "final_usdt": 100,
      "healer_cycles_after_rejection": 2
    },
    {
      "id": "V01",
      "case": "compensated debit and stale settler preserve new funds",
      "debit_state": "undone",
      "synthetic_terminal_fixture": true,
      "balance_usdt": 50,
      "fee_usdt": 0,
      "late_settle": "insufficient"
    },
    {
      "id": "V02",
      "case": "original stale-writer case completed without overflow",
      "mode": "close",
      "first_upload_http": 200,
      "second_action_http": 200,
      "final_status": "closed",
      "stored": 500,
      "reserved": 500,
      "items_added_after_close": 0,
      "limit": 500,
      "healer_cycles_after_resume": 2
    },
    {
      "id": "V02",
      "case": "original stale-writer case completed without overflow",
      "mode": "replacement_upload",
      "first_upload_http": 200,
      "second_action_http": 409,
      "final_status": "open",
      "stored": 500,
      "reserved": 500,
      "items_added_after_close": 0,
      "limit": 500,
      "healer_cycles_after_resume": 2
    },
    {
      "id": "V03",
      "case": "original orphan inflow with failed marker is compensated",
      "injected_write_failures": 1,
      "final_status": "rejected",
      "buyer_usdt": 100,
      "stock": 2,
      "pending_plan": false,
      "fund_net_usdt": 0,
      "inflows": 1,
      "reversals": 1,
      "healer_cycles_after_failure": 2
    },
    {
      "id": "W01",
      "case": "failed item remains recoverable and blocks close",
      "writer_resumed": false,
      "first_close_http": 409,
      "second_close_http": 200,
      "stored": 500,
      "reserved": 500,
      "late_items": 0
    },
    {
      "id": "W01",
      "case": "failed item remains recoverable and blocks close",
      "writer_resumed": true,
      "first_close_http": 409,
      "second_close_http": 200,
      "stored": 500,
      "reserved": 500,
      "late_items": 0
    },
    {
      "id": "W02",
      "case": "failed compensation remains recoverable until one reversal completes",
      "pending_case": "V03",
      "injected_write_failures": 1,
      "failed_write": "fund reversal insert",
      "final_status": "rejected",
      "buyer_usdt": 100,
      "stock": 2,
      "marks_ensured": true,
      "pending_plan": false,
      "fund_net_usdt": 0,
      "expected_fund_net_usdt": 0,
      "healer_cycles_after_failure": 2
    },
    {
      "id": "W02",
      "case": "orphan sweep rereads status and compensates concurrent rejection",
      "pending_case": "V03",
      "synthetic_orphan_fixture": true,
      "reject_http": 200,
      "final_status": "rejected",
      "buyer_usdt": 100,
      "stock": 2,
      "marks_ensured": true,
      "pending_plan": false,
      "fund_net_usdt": 0,
      "expected_fund_net_usdt": 0,
      "healer_cycles_after_race": 2
    },
    {
      "id": "MSG01",
      "case": "stale progress blocked",
      "mode": "cancel",
      "http": 409
    },
    {
      "id": "MSG01",
      "case": "stale progress blocked",
      "mode": "reassign",
      "http": 409
    },
    {
      "id": "MSG02",
      "case": "concurrent manual creation converges to one job and payout",
      "http": [
        200,
        409
      ],
      "jobs": 1,
      "paid": 8
    },
    {
      "id": "MSG03",
      "case": "rejected origin blocks manual creation",
      "http": 409
    },
    {
      "id": "MSG03",
      "case": "deposit rejection cancels pickup and blocks acceptance",
      "http": 409
    },
    {
      "id": "MSG04",
      "case": "interrupted job synchronization recovers without another charge",
      "mode": "creation",
      "source_fee": 10,
      "job_fee": 10,
      "balance": 90
    },
    {
      "id": "MSG04",
      "case": "interrupted job synchronization recovers without another charge",
      "mode": "update",
      "source_fee": 20,
      "job_fee": 20,
      "balance": 90
    },
    {
      "id": "MSG05",
      "case": "original late sync preserves sealed history and flags adjustment",
      "paid": 8,
      "recorded": 8,
      "pending_adjustment_share": 16
    },
    {
      "id": "MSG06",
      "case": "stale reservation rejection preserves new reservation",
      "http": 409,
      "reserved_for": "courier-b"
    },
    {
      "id": "MSG07",
      "case": "earnings include complete history",
      "jobs": 51,
      "earnings": 408,
      "visible_history": 50
    },
    {
      "id": "MSG07",
      "case": "old reservation survives open queue limit",
      "visible": 51,
      "reserved_visible": true
    },
    {
      "id": "MSG08",
      "case": "reassignment clears previous GPS"
    },
    {
      "id": "MSG11",
      "case": "invalid municipality price rejected",
      "input": "NaN",
      "http": 400
    },
    {
      "id": "MSG11",
      "case": "invalid municipality price rejected",
      "input": "Infinity",
      "http": 400
    },
    {
      "id": "MSG11",
      "case": "invalid municipality price rejected",
      "input": "-Infinity",
      "http": 400
    },
    {
      "id": "MSG11",
      "case": "invalid municipality price rejected",
      "input": -1,
      "http": 400
    }
  ],
  "findings": [
    {
      "id": "N01",
      "case": "fee update between payout claim and seal rewrites displayed commission",
      "previous": "MSG05",
      "fee_http": 200,
      "actual_paid": 8,
      "paid_snapshot": 8,
      "displayed_share": 16,
      "displayed_earnings": 16,
      "adjustment_pending": false
    },
    {
      "id": "N02",
      "case": "old fee synchronization overwrites newer completed synchronization",
      "previous": "MSG04",
      "source_fee": 30,
      "job_fee": 20,
      "client_balance": 80.0,
      "sync_pending": false,
      "courier_paid": 16,
      "expected_at_80_percent": 24
    },
    {
      "id": "N03",
      "case": "failed cancellation of rejected pickup is never retried",
      "previous": "MSG03",
      "reject_http": 200,
      "progress_http": 200,
      "origin_status": "rejected",
      "job_status": "on_the_way",
      "healer_passes": 2
    },
    {
      "id": "N04",
      "case": "cash pickup ledger event lost after transient failure",
      "delivery_http": 200,
      "retry_http": 400,
      "collected_usd": 1500,
      "ledger_events": 0,
      "healer_passes": 2
    },
    {
      "id": "N05",
      "case": "more than 50 directed reservations remain inaccessible in panel",
      "previous": "MSG07",
      "stored": 51,
      "visible": 50
    },
    {
      "id": "N05",
      "case": "daily administrative totals capped at 2000 confirmations",
      "previous": "MSG07",
      "stored": 2001,
      "counted": 2000,
      "expected_earnings": 16008,
      "reported_earnings": 16000
    }
  ],
  "controls": [
    {
      "case": "negative exchange amount rejected"
    },
    {
      "case": "reactivated account can append to own batch"
    },
    {
      "case": "chat denies outsiders",
      "http": 403
    },
    {
      "case": "closed chat blocks writing",
      "http": 409
    },
    {
      "case": "simultaneous conversions cannot spend the same source or charge an orphan fee",
      "http": [
        200,
        409
      ],
      "usdt": 19.99,
      "cup": 8000
    },
    {
      "case": "batch item concurrent approval credits once",
      "http": [
        200,
        409
      ],
      "balance_usdt": 25
    },
    {
      "case": "batch approval interrupted during credit heals exactly once",
      "balance_usdt": 25,
      "healer_cycles": 2
    },
    {
      "case": "concurrent market redemptions cannot oversell the last unit",
      "http": [
        200,
        400
      ],
      "stock": 0,
      "buyer_balance": 90,
      "redemptions": 1
    }
  ],
  "source_paths": [
    "backend/routes/admin.py",
    "backend/routes/admin_withdrawals.py",
    "backend/routes/deliveries.py",
    "backend/routes/delivery_chat.py",
    "backend/routes/deposits.py",
    "backend/routes/municipality_rates.py",
    "backend/routes/orders.py",
    "backend/routes/vip_batches.py",
    "backend/services/balances.py",
    "backend/services/company_funds_common.py",
    "backend/services/courier_cash.py",
    "backend/services/courier_fee.py",
    "backend/services/credit_markers.py",
    "backend/services/credit_recovery.py",
    "backend/services/deliveries.py",
    "backend/services/delivery_rules.py",
    "backend/services/delivery_settlement.py",
    "backend/services/inventory.py",
    "backend/services/marketplace_fx.py",
    "backend/services/orders_helpers.py",
    "backend/services/payment_accounts.py",
    "backend/services/permissions.py",
    "backend/services/rate_tiers.py",
    "backend/services/vip_batch_ops.py"
  ]
}
```


**Anexo: audit_frontend_6cc9ee5_results.json**

SHA-256: `410612434e9e315ac435b67fe7b74cb466dd821dcf2e795af85db475a10471eb`

```json
{
  "commit": "6cc9ee527ed5e328f909a17c6488f62eff64a432",
  "checks": [
    {
      "id": "MSG09",
      "case": "old refresh response discarded after chat switch",
      "displayed": "B",
      "message_deliveries": [
        "B"
      ]
    },
    {
      "id": "MSG09",
      "case": "old pagination response discarded after chat switch"
    },
    {
      "id": "R06",
      "case": "same-chat boundary preserved over repeated refresh",
      "messages": 302
    },
    {
      "id": "MSG10",
      "case": "external change refreshes panel",
      "trigger": "live"
    },
    {
      "id": "MSG10",
      "case": "external change refreshes panel",
      "trigger": "timer"
    },
    {
      "id": "MSG10",
      "case": "external change refreshes panel",
      "trigger": "focus"
    },
    {
      "id": "MSG10",
      "case": "assignment notification opens valid courier route",
      "target": "/dashboard/deliveries",
      "actual_service_worker": true
    },
    {
      "id": "MSG08",
      "case": "old GPS is flagged and rendered as stale; fresh and absent GPS controls pass"
    }
  ],
  "findings": [
    {
      "id": "N06",
      "previous": "MSG09",
      "case": "completion of previous chat send starts a fresh old-chat load using current generation",
      "selected_chat": "B",
      "displayed_context": "A",
      "message_deliveries": [
        "B",
        "A"
      ],
      "draft_b_erased": true
    }
  ],
  "browser_end_to_end": false
}
```


**Anexo: audit_verify_6cc9ee5.py**

SHA-256: `409daeeafceea9ecce554431c97c8aac7a0a5f36652a8bd4d78df438737a4b44`

```python
"""Read-only audit harness: real AST-extracted functions, synthetic in-memory data.
No repository writes, live imports, HTTP calls or production connections.
"""
import ast,asyncio,copy,json,logging,math,re,sys,types,uuid,secrets
from pathlib import Path
from datetime import datetime,timezone,timedelta
from typing import Any,Optional,Literal,Dict,List
from pydantic import BaseModel,ConfigDict,Field,ValidationError
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path('audit-6cc9ee5/backend').resolve()
LOAD_PATHS=set()
class HTTPException(Exception):
 def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail
class DuplicateKeyError(Exception):pass
MISSING=object()
def get(d,k,default=None):
 parts=k.split('.')
 def walk(node,ps):
  if not ps:return node
  p=ps[0]
  if isinstance(node,list):
   if p.isdigit():return walk(node[int(p)],ps[1:]) if int(p)<len(node) else MISSING
   vals=[walk(x,ps) for x in node];vals=[x for x in vals if x is not MISSING]
   return vals if vals else MISSING
  if isinstance(node,dict) and p in node:return walk(node[p],ps[1:])
  return MISSING
 val=walk(d,parts);return default if val is MISSING else val
def put(d,k,v):
 parts=k.split('.')
 for p in parts[:-1]:d=d[int(p)] if isinstance(d,list) else d.setdefault(p,{})
 d[int(parts[-1]) if isinstance(d,list) else parts[-1]]=copy.deepcopy(v)
def unset(d,k):
 parts=k.split('.')
 for p in parts[:-1]:
  if not isinstance(d,dict) or p not in d:return
  d=d[p]
 d.pop(parts[-1],None)
def positional_key(d,q,k):
 if '.$.' not in k:return k
 prefix,suffix=k.split('.$.',1)
 cq=(q.get(prefix) or {}).get('$elemMatch')
 if cq is None:cq={p[len(prefix)+1:]:v for p,v in q.items() if p.startswith(prefix+'.')}
 assert cq,('positional query missing',q,k)
 idx=next(i for i,row in enumerate(get(d,prefix)) if match(row,cq))
 return f'{prefix}.{idx}.{suffix}'
def eq(a,b):return b in a if isinstance(a,list) and not isinstance(b,list) else a==b
def expr(x,d):
 if isinstance(x,str) and x.startswith('$'):return get(d,x[1:])
 if isinstance(x,list):return [expr(v,d) for v in x]
 if not isinstance(x,dict):return x
 if not any(k.startswith('$') for k in x):return {k:expr(v,d) for k,v in x.items()}
 assert len(x)==1,x
 op,raw=next(iter(x.items()));v=expr(raw,d)
 if op=='$ifNull':return v[1] if v[0] is None else v[0]
 if op=='$add':return sum(v)
 if op=='$subtract':return v[0]-v[1]
 if op=='$min':return min(v)
 if op=='$max':return max(v)
 if op=='$gte':return v[0]>=v[1]
 if op=='$eq':return v[0]==v[1]
 if op=='$and':return all(v)
 if op=='$concatArrays':return sum(v,[])
 raise AssertionError('Unsupported expression '+op)
def cond(a,v,exists=True):
 if not isinstance(v,dict) or not any(str(k).startswith('$') for k in v):return eq(a,v)
 for op,b in v.items():
  if op=='$exists':ok=exists==b
  elif op=='$ne':ok=not eq(a,b)
  elif op=='$in':ok=any(eq(a,x) for x in b)
  elif op=='$nin':ok=not any(eq(a,x) for x in b)
  elif op=='$size':ok=isinstance(a,list) and len(a)==b
  elif op=='$elemMatch':ok=isinstance(a,list) and any(match(x,b) for x in a)
  elif op=='$gt':ok=any(x is not None and x>b for x in (a if isinstance(a,list) else [a]))
  elif op=='$gte':ok=any(x is not None and x>=b for x in (a if isinstance(a,list) else [a]))
  elif op=='$lt':ok=any(x is not None and x<b for x in (a if isinstance(a,list) else [a]))
  elif op=='$lte':ok=any(x is not None and x<=b for x in (a if isinstance(a,list) else [a]))
  elif op=='$regex':ok=isinstance(a,str) and re.search(b,a,re.I if 'i' in v.get('$options','') else 0)
  elif op=='$options':continue
  elif op=='$not':ok=not cond(a,b,exists)
  else:raise AssertionError('Unsupported filter '+op)
  if not ok:return False
 return True
def match(d,q):
 for k,v in q.items():
  if k=='$or':ok=any(match(d,x) for x in v)
  elif k=='$and':ok=all(match(d,x) for x in v)
  elif k=='$expr':ok=expr(v,d)
  else:ok=cond(get(d,k),v,get(d,k,MISSING) is not MISSING)
  if not ok:return False
 return True
def project(d,p):
 if not p:return copy.deepcopy(d)
 includes=[k for k,v in p.items() if v and k!='_id']
 if includes:
  out={}
  for k in includes:
   if get(d,k,MISSING) is not MISSING:put(out,k,get(d,k))
  return out
 out=copy.deepcopy(d)
 for k,v in p.items():
  if not v:unset(out,k)
 return out
class Cursor:
 def __init__(self,rows,projection=None):self.rows=copy.deepcopy(rows);self.projection=projection
 def sort(self,key,direction=1):
  keys=key if isinstance(key,list) else [(key,direction)]
  for k,dr in reversed(keys):self.rows.sort(key=lambda d:get(d,k) or '',reverse=dr<0)
  return self
 def limit(self,n):self.rows=self.rows[:n];return self
 def skip(self,n):self.rows=self.rows[n:];return self
 async def to_list(self,length=None):return [project(d,self.projection) for d in self.rows[:length]]
 def __aiter__(self):self.i=0;return self
 async def __anext__(self):
  if self.i>=len(self.rows):raise StopAsyncIteration
  d=self.rows[self.i];self.i+=1;return project(d,self.projection)
class Coll:
 def __init__(self,rows=()):self.rows=copy.deepcopy(list(rows));self.before_update=None;self.before_insert=None;self.fail=None;self.unique=[]
 async def create_index(self,keys,**kw):
  if kw.get('unique'):
   ks=[keys] if isinstance(keys,str) else [k for k,v in keys]
   self.unique.append((ks,kw.get('sparse',False)));self.check_unique()
 def check_unique(self):
  for ks,sparse in self.unique:
   seen=set()
   for row in self.rows:
    if sparse and any(get(row,k,MISSING) is MISSING for k in ks):continue
    v=tuple(get(row,k) for k in ks)
    if v in seen:raise DuplicateKeyError('Synthetic unique index collision')
    seen.add(v)
 def find(self,q=None,projection=None):return Cursor([d for d in self.rows if match(d,q or {})],projection)
 async def find_one(self,q,projection=None,sort=None):
  if projection and any(k.endswith('.$') for k in projection):
   assert sort is None
   row=next((r for r in self.rows if match(r,q)),None)
   if row is None:return None
   out={}
   for key in projection:
    if key=='_id':continue
    assert key.endswith('.$'),key
    prefix=key[:-2];cq={p[len(prefix)+1:]:v for p,v in q.items() if p.startswith(prefix+'.')}
    put(out,prefix,[next(copy.deepcopy(x) for x in get(row,prefix) if match(x,cq))])
   return out
  cur=self.find(q,projection)
  if sort:cur.sort(sort)
  rows=await cur.to_list(1);return rows[0] if rows else None
 async def count_documents(self,q):return sum(match(d,q) for d in self.rows)
 async def insert_one(self,d):
  if self.before_insert:await self.before_insert(d)
  if self.fail and self.fail({},d):raise RuntimeError('Synthetic database insert failure')
  self.rows.append(copy.deepcopy(d))
  try:self.check_unique()
  except Exception:self.rows.pop();raise
 async def insert_many(self,docs):
  for d in docs:await self.insert_one(d)
 async def update_one(self,q,u,upsert=False):
  if self.before_update:await self.before_update(q,u)
  if self.fail and self.fail(q,u):raise RuntimeError('Synthetic database update failure')
  d=next((d for d in self.rows if match(d,q)),None);inserted=False
  if d is None:
   if not upsert:return types.SimpleNamespace(matched_count=0,modified_count=0,upserted_id=None)
   d={k:copy.deepcopy(v) for k,v in q.items() if not k.startswith('$') and not isinstance(v,dict)}
   self.rows.append(d);inserted=True
  before=copy.deepcopy(d)
  if isinstance(u,list):
   for stage in u:
    if '$set' in stage:
     vals={k:expr(v,d) for k,v in stage['$set'].items()}
     for k,v in vals.items():put(d,k,v)
    elif '$unset' in stage:
     ks=stage['$unset'];ks=[ks] if isinstance(ks,str) else ks
     for k in ks:unset(d,k)
    else:raise AssertionError(stage)
  else:
   assert set(u)<=set(['$set','$inc','$unset','$push','$addToSet','$setOnInsert','$pull']),u
   if inserted:
    for k,v in u.get('$setOnInsert',{}).items():put(d,k,v)
   for k,v in u.get('$set',{}).items():put(d,positional_key(d,q,k),v)
   for k,v in u.get('$inc',{}).items():put(d,k,(get(d,k) or 0)+v)
   for k in u.get('$unset',{}):unset(d,k)
   for k,v in u.get('$push',{}).items():
    seq=get(d,k) or []
    if isinstance(v,dict) and '$each' in v:
     seq=seq+v['$each']
     if '$slice' in v:seq=seq[:v['$slice']] if v['$slice']>=0 else seq[v['$slice']:]
    else:seq=seq+[v]
    put(d,k,seq)
   for k,v in u.get('$addToSet',{}).items():
    seq=get(d,k) or []
    if v not in seq:put(d,k,seq+[v])
   for k,v in u.get('$pull',{}).items():
    seq=get(d,k) or []
    put(d,k,[x for x in seq if not (match(x,v) if isinstance(x,dict) and isinstance(v,dict) else cond(x,v))])
  try:self.check_unique()
  except Exception:
   if inserted:self.rows.remove(d)
   else:d.clear();d.update(before)
   raise
  return types.SimpleNamespace(matched_count=int(not inserted),modified_count=int(before!=d and not inserted),upserted_id='synthetic' if inserted else None)
 async def find_one_and_update(self,q,u,projection=None,return_document=False,**kw):
  before=await self.find_one(q)
  res=await self.update_one(q,u,**kw)
  if not res.matched_count:return None
  return project(next(d for d in self.rows if get(d,'id')==get(before,'id')),projection) if return_document else project(before,projection)
 async def update_many(self,q,u):
  rows=[d for d in self.rows if match(d,q)];n=0
  for row in rows:
   key='id' if 'id' in row else 'user_id';n+=(await self.update_one({key:row[key]},u)).modified_count
  return types.SimpleNamespace(modified_count=n)
 async def delete_one(self,q):
  for i,d in enumerate(self.rows):
   if match(d,q):self.rows.pop(i);return types.SimpleNamespace(deleted_count=1)
  return types.SimpleNamespace(deleted_count=0)
 async def delete_many(self,q):
  before=len(self.rows);self.rows=[d for d in self.rows if not match(d,q)];return types.SimpleNamespace(deleted_count=before-len(self.rows))
 def aggregate(self,pipeline):
  rows=copy.deepcopy(self.rows)
  for stage in pipeline:
   if '$match' in stage:rows=[d for d in rows if match(d,stage['$match'])]
   elif '$group' in stage:
    group=stage['$group'];buckets={}
    for d in rows:
     key=expr(group['_id'],d);b=buckets.setdefault(json.dumps(key,sort_keys=True),{'_id':key})
     for k,v in group.items():
      if k=='_id':continue
      if '$sum' in v:b[k]=b.get(k,0)+(expr(v['$sum'],d) or 0)
      elif '$last' in v:b[k]=expr(v['$last'],d)
      else:raise AssertionError(v)
    rows=list(buckets.values())
   elif '$sort' in stage:rows=Cursor(rows).sort(list(stage['$sort'].items())).rows
   else:raise AssertionError('Unsupported aggregation '+str(stage))
  return Cursor(rows)
class DB:
 def __getattr__(self,k):c=Coll();setattr(self,k,c);return c
 def __getitem__(self,k):return getattr(self,k)
async def noop(*a,**kw):pass
async def value(x):return x
def module(name,**attrs):
 m=types.ModuleType(name);m.__dict__.update(attrs);sys.modules[name]=m;return m
def load_module(name,path,db,user,*,names=None,extra=None):
 LOAD_PATHS.add('backend/'+path)
 e=dict(db=db,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,HTTPException=HTTPException,
        Any=Any,Optional=Optional,Literal=Literal,Dict=Dict,List=List,Request=object,
        math=math,secrets=secrets,uuid=uuid,datetime=datetime,timezone=timezone,timedelta=timedelta,logging=logging,
        iso=lambda x:x.isoformat(),now_utc=lambda:datetime.now(timezone.utc),
        logger=logging.getLogger('modules-audit'),DuplicateKeyError=DuplicateKeyError,
        require_user=lambda request:value(copy.deepcopy(user)),
        require_permission=lambda *a:value({'user_id':'synthetic-admin','role':'admin','name':'Synthetic admin'}),
        _enforce_totp_step_up=noop,_enforce_employee_currency_scope=lambda *a:None,
        log_action=noop,notify_all_admins=noop,emit_balance_changed=noop,
        assert_user_fully_verified=noop,maybe_upload_proof=lambda x,*a:x)
 e.update(extra or {})
 tree=ast.parse((ROOT/path).read_text());nodes=[]
 for n in tree.body:
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
   if names is None or n.name in names:n.decorator_list=[];nodes.append(n)
  elif isinstance(n,(ast.Assign,ast.AnnAssign)):
   try:
    v=ast.literal_eval(n.value)
    targets=n.targets if isinstance(n,ast.Assign) else [n.target]
    for t in targets:
     if isinstance(t,ast.Name):e[t.id]=v
   except (ValueError,TypeError):pass
 future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
 code=ast.fix_missing_locations(ast.Module(body=[future]+nodes,type_ignores=[]))
 m=module(name,**e);e=m.__dict__
 exec(compile(code,str(ROOT/path),'exec'),e)
 for obj in list(e.values()):
  if isinstance(obj,type) and issubclass(obj,BaseModel) and obj is not BaseModel:obj.model_rebuild(_types_namespace=e)
 return m
def fixture(balance=100):
 db=DB();user={'user_id':'client','email':'client@example.test','name':'Synthetic Client','role':'vip','account_status':'active','vip_balances':{'USDT':balance,'USD':0,'CUP':0}}
 db.users.rows=[copy.deepcopy(user)]
 module('pymongo');module('pymongo.errors',DuplicateKeyError=DuplicateKeyError);module('services');module('routes');module('audit_log',log_action=noop);module('admin_alerts',notify_all_admins=noop)
 module('routes.notifications',_insert_notification=noop)
 module('services.live_bus',publish=noop);module('services.live_events',emit_balance_changed=noop)
 module('services.reconciliation_matcher',schedule_rematch=lambda *a:None)
 module('push_service',send_push_to_user=noop,build_generic_admin_alert_payload=lambda **kw:kw)
 bal=load_module('services.balances','services/balances.py',db,user)
 mark=load_module('services.credit_markers','services/credit_markers.py',db,user)
 rec=load_module('services.credit_recovery','services/credit_recovery.py',db,user,extra={'pending_marker':mark.pending_marker,'apply_and_clear':mark.apply_and_clear})
 inv=load_module('services.inventory','services/inventory.py',db,user)
 funds=load_module('services.company_funds_common','services/company_funds_common.py',db,user)
 fee=load_module('services.courier_fee','services/courier_fee.py',db,user,extra={n:getattr(bal,n) for n in ['build_rate_lookup','convert_to_usdt','convert_from_usdt']})
 load_module('services.courier_cash','services/courier_cash.py',db,user)
 deliveries=load_module('services.deliveries','services/deliveries.py',db,user)
 deliveries._broadcast_new_delivery_to_couriers=noop
 # AST functions retain e as globals; replacing module attrs alone is not enough.
 for m in [deliveries]:m.ensure_delivery_job.__globals__['_broadcast_new_delivery_to_couriers']=noop
 settle=load_module('services.delivery_settlement','services/delivery_settlement.py',db,user)
 dr=load_module('routes.deliveries','routes/deliveries.py',db,user,extra={'build_delivery_doc':deliveries.build_delivery_doc})
 admin=load_module('routes.admin','routes/admin.py',db,user,names=[
  'update_order_status','_collect_order_payout_evidence','_validate_order_payout_evidence','_detect_crypto_network_from_delivery','_validate_crypto_tx_hash',
  '_credit_vendor_for_redemption','_claim_vendor_reversal_plan','_notify_vendor_reversal','_reverse_vendor_credit_if_any','_record_vendor_commission_inflow','_reverse_fund_inflow_if_any',
  '_assert_redemption_courier_ready','_assert_courier_job_delivered','_transition_redemption','_resume_redemption_effects','update_redemption','_apply_rejection_effects','_on_redemption_rejected',
  '_log_redemption_status_change','_apply_courier_fee_balance_delta','_notify_redemption_courier_fee','_load_redemption_for_fee','_price_redemption_fee','set_redemption_courier_fee'])
 load_module('services.vip_batch_ops','services/vip_batch_ops.py',db,user,names=['resolve_upload_plan','heal_batch_upload_plans','ensure_items_unique_index'])
 return types.SimpleNamespace(db=db,user=user,bal=bal,mark=mark,rec=rec,inv=inv,funds=funds,fee=fee,deliveries=deliveries,settle=settle,dr=dr,admin=admin)
def setg(fn,**kw):fn.__globals__.update(kw)
async def http(coro):
 try:return 200,await coro
 except HTTPException as ex:return ex.status_code,ex.detail
async def balance(f,uid='client',code='USDT'):return f.bal.get_user_balance(await f.db.users.find_one({'user_id':uid}) or {},code)
def good(case,**data):RESULTS['controls'].append({'case':case,**data})
def bug(id,case,**data):RESULTS['findings'].append({'id':id,'case':case,**data})

def exchange_runtime(f):
 pa=load_module('services.payment_accounts','services/payment_accounts.py',f.db,f.user)
 tiers=load_module('services.rate_tiers','services/rate_tiers.py',f.db,f.user)
 rules=load_module('services.delivery_rules','services/delivery_rules.py',f.db,f.user)
 oh=load_module('services.orders_helpers','services/orders_helpers.py',f.db,f.user,
   extra={'generate_payment_reference':lambda:'SYNTHETIC-REF','accumulate_vip_balance':f.bal.accumulate_vip_balance,
          'compute_total_usdt':f.bal.compute_total_usdt,'maybe_award_referral_bonus':noop})
 setg(oh.run_post_status_side_effects,check_vip_threshold_alert=noop,send_client_order_email=noop,
      send_client_order_push=noop,create_inapp_order_notification=noop)
 order=load_module('routes.orders','routes/orders.py',f.db,f.user,
  names=['create_order','_assert_delivery_method_matches_currency','OrderCreate','Redemption','RedemptionCreate','redeem_product','_load_pickup_store','_new_pickup_code','VipConvertPayload','vip_convert'],
  extra={**{n:getattr(oh,n) for n in ['OrderCreate','resolve_order_rate','build_order_from_payload']},
         **{n:getattr(f.bal,n) for n in ['assert_account_active','assert_not_defensive','get_user_balance','decrement_balance','effective_sell_rate']},
         **{n:getattr(rules,n) for n in ['is_delivery_method_allowed','allowed_delivery_methods']},
         'maybe_flag_defensive_margin':noop,'dispatch_new_order_alerts':noop})
 setg(f.admin.update_order_status,VALID_ORDER_STATUSES=oh.VALID_ORDER_STATUSES,
  authorize_status_transition=oh.authorize_status_transition,
  run_post_status_side_effects=oh.run_post_status_side_effects,publish_order_status_sse=noop)
 return order,oh

def order_doc(i='exchange',amount=100):
 return {'id':i,'user_id':'client','user_role':'vip','user_email':'client@example.test','user_name':'Synthetic Client',
   'from_code':'USD','to_code':'USDT','amount_from':amount,'amount_to':amount,'delivery_method':'accumulate','status':'pending'}


def batch_runtime(f):
 pa=load_module('services.payment_accounts','services/payment_accounts.py',f.db,f.user)
 tiers=load_module('services.rate_tiers','services/rate_tiers.py',f.db,f.user)
 rules=load_module('services.delivery_rules','services/delivery_rules.py',f.db,f.user)
 ops=load_module('services.vip_batch_ops','services/vip_batch_ops.py',f.db,f.user,
   extra={'build_rate_lookup':f.bal.build_rate_lookup,'convert_to_usdt':f.bal.convert_to_usdt,
          'effective_rates':tiers.effective_rates,'dispatch_vip_batch_alerts':noop})
 br=load_module('routes.vip_batches','routes/vip_batches.py',f.db,f.user,names=[
  'VipBatchCreate','VipBatchItemIn','VipBatchItemsBulk','_require_vip','_allowed_batch_pairs',
  '_requires_cup_card','_normalize_cup_card','create_vip_batch','add_vip_batch_items','get_vip_batch','close_vip_batch'],
  extra={**{n:getattr(ops,n) for n in ['serialize_doc','refresh_batch_totals','apply_item_decision']},
    **{n:getattr(pa,n) for n in ['get_active_accounts','pick_account']},'pa_min_required':pa.min_required,
    'allowed_delivery_methods':rules.allowed_delivery_methods,'effective_rates':tiers.effective_rates,
    'normalize_tiers':tiers.normalize_tiers,'_notify_staff_new_batch':noop,'dispatch_vip_batch_alerts':noop,
    'generate_payment_reference':lambda:'SYNTHETIC-BATCH-REF','schedule_rematch':lambda *a:None})
 f.db.rates.rows=[{'from_code':'USD','to_code':'USDT','rate_vip':1,'rate_normal':1,'real_rate':1}]
 f.db.currencies.rows=[{'code':'USD','type':'fiat','is_active':True},{'code':'USDT','type':'crypto','is_active':True}]
 return br,ops

async def batch_seed(n=0,blocked=False):
 f=fixture(0)
 if blocked:f.user['account_status']='blocked';f.db.users.rows[0]['account_status']='blocked'
 br,ops=batch_runtime(f)
 b=await br.create_vip_batch(br.VipBatchCreate(from_code='USD',to_code='USDT'),None)
 for i in range(n):
  f.db.vip_batch_items.rows.append({'id':str(i),'batch_id':b['id'],'vip_user_id':'client','holder_name':'Synthetic Holder','amount':1,'status':'pending','created_at':str(i).zfill(6),
                                  'from_code':'USD','to_code':'USDT','direction':'pair','currency':'USD'})
 return f,br,ops,b

def delivery_doc(kind='redemption'):
 return {'id':'delivery','kind':kind,'ref_id':'op','user_id':'client','client_name':'Synthetic Client','status':'delivered',
   'courier_id':'courier','courier_name':'Synthetic Courier','courier_share_usdt':8,'platform_share_usdt':2,'fee_usdt':10,
   'payout_credited':False,'timeline':[],'amount_label':'Synthetic shipment'}

async def check_core_controls():
 # Balance conversion has a single authoritative update for source, fee and destination.
 f=fixture(100);order,_=exchange_runtime(f)
 f.db.currencies.rows=[{'code':'CUP','is_convertible_to':True}]
 f.db.rates.rows=[{'from_code':'USDT','to_code':'CUP','rate_vip':100,'rate_normal':100}]
 reached=asyncio.Event();go=asyncio.Event();n=0
 async def hold(q,u):
  nonlocal n
  if q.get('user_id')=='client':
   n+=1
   if n==2:reached.set()
   await go.wait()
 f.db.users.before_update=hold
 payload=order.VipConvertPayload(from_code='USDT',to_code='CUP',amount_from=80)
 ts=[asyncio.create_task(http(order.vip_convert(payload,None))) for _ in range(2)]
 await reached.wait();go.set();codes=sorted(x[0] for x in await asyncio.gather(*ts))
 assert codes==[200,409] and round(await balance(f),2)==19.99 and await balance(f,code='CUP')==8000
 good('simultaneous conversions cannot spend the same source or charge an orphan fee',http=codes,usdt=19.99,cup=8000)
 # A batch item approval is claimed once even with overlapping administrators.
 f,br,ops,b=await batch_seed()
 r=await br.add_vip_batch_items(b['id'],br.VipBatchItemsBulk(items=[br.VipBatchItemIn(holder_name='Synthetic Sender',amount=25)]),None)
 item=r['items'][0]['id'];reached=asyncio.Event();go=asyncio.Event();n=0
 async def hold_decision(q,u):
  nonlocal n
  if u.get('$set',{}).get('status')=='approved':
   n+=1
   if n==2:reached.set()
   await go.wait()
 f.db.vip_batch_items.before_update=hold_decision
 staff={'user_id':'admin','role':'admin'}
 ts=[asyncio.create_task(http(ops.apply_item_decision(item,'approved',staff))) for _ in range(2)]
 await reached.wait();go.set();codes=sorted(x[0] for x in await asyncio.gather(*ts))
 assert codes==[200,409] and await balance(f)==25
 good('batch item concurrent approval credits once',http=codes,balance_usdt=25)
 # A failing batch credit has a persistent intent and is recovered exactly once.
 f,br,ops,b=await batch_seed()
 r=await br.add_vip_batch_items(b['id'],br.VipBatchItemsBulk(items=[br.VipBatchItemIn(holder_name='Synthetic Sender',amount=25)]),None)
 f.db.users.fail=lambda q,u:True
 await ops.apply_item_decision(r['items'][0]['id'],'approved',staff)
 assert await balance(f)==0 and f.db.vip_batch_items.rows[0].get('credit_pending')
 f.db.users.fail=None
 await f.rec.heal_pending_credits(max_age_seconds=-1);await f.rec.heal_pending_credits(max_age_seconds=-1)
 assert await balance(f)==25 and not f.db.vip_batch_items.rows[0].get('credit_pending')
 good('batch approval interrupted during credit heals exactly once',balance_usdt=25,healer_cycles=2)
 # An atomic stock reservation prevents two redemptions of the last unit.
 f=fixture(100);order,_=exchange_runtime(f)
 f.db.settings.rows=[{'id':'global','courier_rate_usdt_per_km':0}]
 f.db.products.rows=[{'id':'product','owner_id':'seller','name':'Synthetic Product','stock':1,'price_usd':10,'is_active':True,'approval_status':'approved'}]
 reached=asyncio.Event();go=asyncio.Event();n=0
 async def hold_stock(q,u):
  nonlocal n
  if u.get('$inc',{}).get('stock')==-1:
   n+=1
   if n==2:reached.set()
   await go.wait()
 f.db.products.before_update=hold_stock
 payload=order.RedemptionCreate(product_id='product',quantity=1)
 ts=[asyncio.create_task(http(order.redeem_product(payload,None))) for _ in range(2)]
 await reached.wait();go.set();codes=sorted(x[0] for x in await asyncio.gather(*ts))
 assert codes==[200,400] and f.db.products.rows[0]['stock']==0 and await balance(f)==90 and len(f.db.redemptions.rows)==1
 good('concurrent market redemptions cannot oversell the last unit',http=codes,stock=0,buyer_balance=90,redemptions=1)

def check(id,case,**data):RESULTS['checks'].append({'id':id,'case':case,**data})
async def heal(f):
 await f.rec.heal_pending_credits(max_age_seconds=-1)
 await f.rec.heal_initializing_ops(max_age_seconds=-1)

async def review_exchanges():
 f=fixture(0);order,oh=exchange_runtime(f)
 f.db.currencies.rows=[{'code':'USD','type':'fiat','is_active':True,'delivery_methods':['cash']},{'code':'USDT','type':'crypto','is_active':True}]
 f.db.rates.rows=[{'from_code':'USDT','to_code':'USD','rate_vip':1.015,'rate_normal':1.015}]
 for i in range(2):
  await order.create_order(oh.OrderCreate(from_code='USDT',to_code='USD',amount_from=50,delivery_method='cash',sender_name='Synthetic Sender'),None)
 assert await balance(f,code='USD')==0
 for o in list(f.db.orders.rows):await f.admin.update_order_status(o['id'],{'status':'rejected'},None)
 assert await balance(f,code='USD')==0
 check('EX01','pending and rejected cash orders do not credit residue',orders=2,balance_usd=0)
 o=await order.create_order(oh.OrderCreate(from_code='USDT',to_code='USD',amount_from=50,delivery_method='cash',sender_name='Synthetic Sender'),None)
 f.db.users.fail=lambda q,u:True
 try:await f.admin.update_order_status(o['id'],{'status':'approved'},None);assert False
 except RuntimeError:pass
 f.db.users.fail=None
 await heal(f);await heal(f)
 await f.admin.update_order_status(o['id'],{'status':'approved'},None)
 assert await balance(f,code='USD')==.75
 check('EX01','approved residue recovers once after credit failure',balance_usd=.75,healer_cycles=2)
 f=fixture(0);order,oh=exchange_runtime(f);f.db.orders.rows=[order_doc()]
 f.db.orders.fail=lambda q,u:'credit_pending' in u.get('$set',{})
 try:await f.admin.update_order_status('exchange',{'status':'approved'},None);assert False
 except RuntimeError:pass
 f.db.orders.fail=None
 await f.admin.update_order_status('exchange',{'status':'approved'},None)
 await f.admin.update_order_status('exchange',{'status':'approved'},None)
 await f.admin.update_order_status('exchange',{'status':'completed'},None)
 assert await balance(f)==100
 check('EX02','same-state retry after failed marker creation credits once',usdt=100)
 # Original race: rejection before credit claim now prevents the credit.
 for stage in ['before_claim','after_claim']:
  f=fixture(0);order,oh=exchange_runtime(f);f.db.orders.rows=[order_doc()]
  hit=asyncio.Event();go=asyncio.Event()
  async def pause(q,u):
   if (stage=='before_claim' and 'accumulated_at' in u.get('$set',{})) or (stage=='after_claim' and q.get('user_id')=='client'):
    hit.set();await go.wait()
  if stage=='before_claim':f.db.orders.before_update=pause
  else:f.db.users.before_update=pause
  a=asyncio.create_task(http(f.admin.update_order_status('exchange',{'status':'approved'},None)))
  await hit.wait();b,_=await http(f.admin.update_order_status('exchange',{'status':'rejected'},None));go.set();a_code,_=await a
  assert (a_code,b)==((200,200) if stage=='before_claim' else (200,409))
  if stage=='before_claim':
   assert await balance(f)==0;check('EX02','rejection wins before accumulation claim',balance_usdt=0)
  else:
   await heal(f);await heal(f)
   assert await balance(f)==100
   assert f.db.orders.rows[0]['status']=='approved'
   check('R01','rejection after monetary claim blocked',http=[a_code,b],final_status='approved',balance_usdt=100,healer_cycles=2)
 try:oh.OrderCreate(from_code='USD',to_code='USDT',amount_from=-1,delivery_method='accumulate',sender_name='Synthetic Sender');assert False
 except ValidationError:good('negative exchange amount rejected')

def fee_scene(kind,initial=100,fee_before=0):
 f=fixture(initial);cur='USD' if kind=='withdrawal' else 'USDT';f.db.users.rows[0]['vip_balances'][cur]=initial
 f.db.rates.rows=[{'from_code':'USDT','to_code':'USD','rate_vip':1,'rate_normal':1}]
 coll=f.db.withdrawals if kind=='withdrawal' else f.db.redemptions
 field='courier_fee_currency_amount' if kind=='withdrawal' else 'courier_fee_usd'
 coll.rows=[{'id':'op','user_id':'client','currency':cur,'settlement_currency':cur,'method':'cash','status':'pending','amount_usd':40,'total_usd':40,'product_name':'Synthetic Product',field:fee_before}]
 call=load_module('routes.admin_withdrawals','routes/admin_withdrawals.py',f.db,f.user,names=['set_courier_fee']).set_courier_fee if kind=='withdrawal' else f.admin.set_redemption_courier_fee
 return f,cur,coll,field,call

async def review_fees():
 for kind in ['withdrawal','redemption']:
  for mode in ['charge','refund','interruption']:
   f,cur,coll,field,call=fee_scene(kind,90 if mode=='refund' else 100,10 if mode=='refund' else 0)
   payload={'km':0 if mode=='refund' else 20}
   if mode=='interruption':
    f.db.users.fail=lambda q,u:True
    try:await call('op',payload,None);assert False
    except RuntimeError:pass
    assert coll.rows[0].get('courier_fee_op_pending')
    f.db.users.fail=None;await heal(f);await heal(f)
    code,_=await http(call('op',payload,None));codes=[500,code]
   else:
    hit=asyncio.Event();go=asyncio.Event();n=0
    async def barrier(q,u):
     nonlocal n
     if 'courier_fee_op_pending' in u.get('$set',{}):
      n+=1
      if n==2:hit.set()
      await go.wait()
    coll.before_update=barrier
    ts=[asyncio.create_task(http(call('op',payload,None))) for _ in range(2)]
    await hit.wait();go.set();codes=sorted(x[0] for x in await asyncio.gather(*ts));assert codes==[200,409]
   expected=100 if mode=='refund' else 90
   assert await balance(f,code=cur)==expected and not coll.rows[0].get('courier_fee_op_pending')
   check('ME01','fee '+mode,kind=kind,http=codes,final_balance=expected,fee=coll.rows[0][field])
  # Two executors of one pending plan: healer aborts insufficient charge,
  # old executor resumes after new money arrives. It must be fenced off.
  f,cur,coll,field,call=fee_scene(kind,5,0)
  hit=asyncio.Event();go=asyncio.Event();n=0
  async def pause_first(q,u):
   nonlocal n
   if q.get('user_id')=='client':
    n+=1
    if n==1:hit.set();await go.wait()
  f.db.users.before_update=pause_first
  a=asyncio.create_task(http(call('op',{'km':20},None)))
  await hit.wait();await heal(f)
  assert coll.rows[0][field]==0 and not coll.rows[0].get('courier_fee_op_pending')
  await f.bal.credit_balance_idempotent('client',cur,100,'synthetic-new-income')
  go.set();code,_=await a
  await heal(f)
  assert await balance(f,code=cur)==105 and coll.rows[0][field]==0
  check('R02','aborted courier fee cannot debit with later funds',kind=kind,initial_balance=5,new_income=100,final_balance=105,recorded_fee=0,http=code)
 # Rejection must not refund a published fee whose debit failed.
 f=fixture(100);order,_=exchange_runtime(f)
 f.db.settings.rows=[{'id':'global','courier_rate_usdt_per_km':0}]
 f.db.products.rows=[{'id':'product','owner_id':'seller','name':'Synthetic Product','price_usd':100,'stock':1,'approval_status':'approved','is_active':True}]
 r=await order.redeem_product(order.RedemptionCreate(product_id='product',quantity=1),None)
 assert await balance(f)==0
 f.db.settings.rows[0]['courier_rate_usdt_per_km']=.5
 hit=asyncio.Event();go=asyncio.Event()
 async def pause_rollback(q,u):
  if 'courier_fee_op_pending' in u.get('$unset',{}) and 'courier_fee_usd' in u.get('$set',{}):hit.set();await go.wait()
 f.db.redemptions.before_update=pause_rollback
 a=asyncio.create_task(http(f.admin.set_redemption_courier_fee(r['id'],{'km':20},None)))
 await hit.wait();reject_code,_=await http(f.admin.update_redemption(r['id'],{'status':'rejected'},None));assert reject_code==409
 go.set();code,_=await a
 await f.admin.update_redemption(r['id'],{'status':'rejected'},None)
 await heal(f);await heal(f)
 assert code==400 and await balance(f)==100
 check('R02','refund waits for failed fee rollback then returns only paid money',initial_balance=100,final_balance=100,concurrent_reject_http=409,fee_update_http=400)

async def seed_current_batch(n=0):
 f,br,ops,b=await batch_seed(n)
 f.db.vip_batches.rows[0]['items_reserved']=n
 return f,br,ops,b
def batch_payload(br,n):return br.VipBatchItemsBulk(items=[br.VipBatchItemIn(holder_name='Synthetic Sender',amount=10) for _ in range(n)])
async def review_batches():
 f,br,ops,b=await seed_current_batch(450);hit=asyncio.Event();go=asyncio.Event();n=0
 async def reserve_barrier(q,u):
  nonlocal n
  if u.get('$inc',{}).get('items_reserved')==50:
   n+=1
   if n==2:hit.set()
   await go.wait()
 f.db.vip_batches.before_update=reserve_barrier
 ts=[asyncio.create_task(http(br.add_vip_batch_items(b['id'],batch_payload(br,50),None))) for _ in range(2)]
 await hit.wait();go.set();codes=sorted(x[0] for x in await asyncio.gather(*ts))
 assert codes==[200,409] and len(f.db.vip_batch_items.rows)==500
 check('LO01','atomic quota under normal concurrent uploads',http=codes,stored=500)
 f,br,ops,b=await seed_current_batch(550)
 assert len((await br.get_vip_batch(b['id'],None))['items'])==550
 check('LO01','all historical overflow items remain visible',returned=550)
 f,br,ops,b=await seed_current_batch();hit=asyncio.Event();go=asyncio.Event()
 async def pause_insert(d):hit.set();await go.wait()
 f.db.vip_batch_items.before_insert=pause_insert
 a=asyncio.create_task(http(br.add_vip_batch_items(b['id'],batch_payload(br,1),None)))
 await hit.wait();close_code,_=await http(br.close_vip_batch(b['id'],None));assert close_code==409
 go.set();code,_=await a
 await br.close_vip_batch(b['id'],None)
 assert code==200 and f.db.vip_batches.rows[0]['status']=='closed' and len(f.db.vip_batch_items.rows)==1
 check('R03','close waits for active upload',close_while_upload_http=409,append_http=200,final_close_http=200,stored_items=1)
 # Ordered insert_many may insert a prefix before it fails.
 f,br,ops,b=await seed_current_batch(450);n=0
 def fail_26th(q,u):
  nonlocal n
  n+=1;return n==26
 f.db.vip_batch_items.fail=fail_26th
 try:await br.add_vip_batch_items(b['id'],batch_payload(br,50),None);assert False
 except RuntimeError:pass
 f.db.vip_batch_items.fail=None
 assert len(f.db.vip_batch_items.rows)==475 and f.db.vip_batches.rows[0]['items_reserved']==475
 hit=asyncio.Event();go=asyncio.Event();n=0
 async def partial_barrier(q,u):
  nonlocal n
  if u.get('$inc',{}).get('items_reserved')==25:
   n+=1
   if n==2:hit.set()
   await go.wait()
 f.db.vip_batches.before_update=partial_barrier
 ts=[asyncio.create_task(http(br.add_vip_batch_items(b['id'],batch_payload(br,25),None))) for _ in range(2)]
 await hit.wait();go.set();codes=[x[0] for x in await asyncio.gather(*ts)]
 assert sorted(codes)==[200,409] and len(f.db.vip_batch_items.rows)==500
 check('R03','partial insert releases only remaining quota',stored_after_failed_insert=475,reserved_after_failed_insert=475,subsequent_http=codes,final_stored=500,final_reserved=500)
 f,br,ops,b=await seed_current_batch()
 for status in ['blocked','under_review']:
  f.user['account_status']=status
  c1,_=await http(br.create_vip_batch(br.VipBatchCreate(from_code='USD',to_code='USDT'),None))
  c2,_=await http(br.add_vip_batch_items(b['id'],batch_payload(br,1),None))
  assert (c1,c2)==(403,403)
  check('LO02','blocked account cannot create or append',account_status=status,http=[c1,c2])
 f.user['account_status']='active'
 await br.add_vip_batch_items(b['id'],batch_payload(br,1),None)
 good('reactivated account can append to own batch')

async def company_scene(failing=None):
 f=fixture(100);order,_=exchange_runtime(f)
 load_module('services.marketplace_fx','services/marketplace_fx.py',f.db,f.user)
 f.db.settings.rows=[{'id':'global','courier_rate_usdt_per_km':0,'store_currency_code':'CUP'}]
 f.db.rates.rows=[{'from_code':'USDT','to_code':'CUP','rate_vip':100,'rate_normal':100}]
 f.db.products.rows=[{'id':'product','owner_id':'','name':'Synthetic Company Product','price_usd':1000,'cost_usd':600,'stock':2,'is_active':True}]
 if failing:f.db[failing].fail=lambda q,u:True
 created=await order.redeem_product(order.RedemptionCreate(product_id='product',quantity=1,delivery_address='Synthetic address'),None)
 if failing:f.db[failing].fail=None
 return f,created
async def review_market():
 for interrupted in [False,True]:
  f=fixture(100);order,_=exchange_runtime(f)
  f.db.users.rows.append({'user_id':'seller','role':'vip','vip_balances':{'USDT':0}})
  f.db.settings.rows=[{'id':'global','courier_rate_usdt_per_km':0,'vendor_commission_pct':5}]
  f.db.products.rows=[{'id':'product','owner_id':'seller','owner_name':'Synthetic Seller','name':'Synthetic Product','price_usd':100,'cost_usd':0,'stock':1,'approval_status':'approved','is_active':True}]
  created=await order.redeem_product(order.RedemptionCreate(product_id='product',quantity=1,delivery_address='Synthetic address'),None)
  if interrupted:f.db.users.fail=lambda q,u:q.get('user_id')=='seller' and u.get('$inc',{}).get('vip_balances.USDT',0)>0
  try:await f.admin.update_redemption(created['id'],{'status':'delivered'},None)
  except RuntimeError:assert interrupted
  f.db.users.fail=None
  await f.admin.update_redemption(created['id'],{'status':'rejected'},None)
  await heal(f);await heal(f)
  assert await balance(f)==100 and await balance(f,'seller')==0 and f.db.products.rows[0]['stock']==1
  check('MR01','refund after vendor delivery',interrupted=interrupted,buyer=100,seller=0,stock=1,healer_cycles=2)
 for failing in [None,'inventory_movements','company_fund_adjustments']:
  f,created=await company_scene(failing)
  await heal(f);await heal(f)
  assert await balance(f)==90 and f.db.products.rows[0]['stock']==1
  assert len(f.db.inventory_movements.rows)==1 and sum(r['amount'] for r in f.db.company_fund_adjustments.rows)==10
  check('MR02','company sale trace recovery',failed_collection=failing,buyer=90,stock=1,sales=1,fund_inflow=10)
 # The original web sale and its recoverer can both pass the existence check.
 f=fixture(100);order,_=exchange_runtime(f)
 load_module('services.marketplace_fx','services/marketplace_fx.py',f.db,f.user)
 f.db.settings.rows=[{'id':'global','courier_rate_usdt_per_km':0,'store_currency_code':'CUP'}]
 f.db.rates.rows=[{'from_code':'USDT','to_code':'CUP','rate_vip':100,'rate_normal':100}]
 f.db.products.rows=[{'id':'product','owner_id':'','name':'Synthetic Company Product','price_usd':1000,'cost_usd':600,'stock':2,'is_active':True}]
 first=asyncio.Event();hit=asyncio.Event();go=asyncio.Event();n=0
 async def pause_inv(d):
  nonlocal n
  n+=1
  if n==1:first.set()
  if n==2:hit.set()
  await go.wait()
 f.db.inventory_movements.before_insert=pause_inv
 creator=asyncio.create_task(order.redeem_product(order.RedemptionCreate(product_id='product',quantity=1),None))
 await first.wait()
 ts=[creator,asyncio.create_task(heal(f))]
 await hit.wait();go.set();await asyncio.gather(*ts)
 assert len(f.db.inventory_movements.rows)==1 and await balance(f)==90 and f.db.products.rows[0]['stock']==1
 check('R04','original company-sale route and recoverer write only one sale',real_units_sold=1,recorded_sale_movements=1,recorded_sales_CUP=sum(r['total'] for r in f.db.inventory_movements.rows),buyer_usdt=90,stock=1)
 # Recovery already read pending, rejection completes before inflow insert.
 f,created=await company_scene('company_fund_adjustments');hit=asyncio.Event();go=asyncio.Event()
 async def pause_fund(d):
  if d['adjustment_type']=='inflow':hit.set();await go.wait()
 f.db.company_fund_adjustments.before_insert=pause_fund
 a=asyncio.create_task(heal(f));await hit.wait()
 await f.admin.update_redemption(created['id'],{'status':'rejected'},None)
 assert await balance(f)==100 and f.db.products.rows[0]['stock']==2
 go.set();await a;await heal(f);await heal(f)
 net=sum(r['amount']*(1 if r['adjustment_type']=='inflow' else -1) for r in f.db.company_fund_adjustments.rows)
 assert net==0 and f.db.redemptions.rows[0]['status']=='rejected'
 check('R05','late sale inflow is compensated after rejection',final_status='rejected',buyer_usdt=100,stock=2,fund_net_usdt=0)

async def review_deliveries():
 f=fixture(0);f.db.users.rows.append({'user_id':'courier','vip_balances':{'USDT':0}});f.db.deliveries.rows=[delivery_doc()]
 hit=asyncio.Event();go=asyncio.Event()
 async def pause(q,u):
  if u.get('$set',{}).get('payout_credited') is True:hit.set();await go.wait()
 f.db.deliveries.before_update=pause
 a=asyncio.create_task(http(f.dr.admin_confirm_delivery('delivery',{},None)))
 await hit.wait();cancel,_=await http(f.dr.admin_cancel_delivery('delivery',{},None));go.set();confirm,_=await a
 assert (cancel,confirm)==(200,409) and await balance(f,'courier')==0 and f.db.deliveries.rows[0]['status']=='cancelled'
 check('ME02','cancel wins against stale confirmation',http=[cancel,confirm],courier_usdt=0)
 f=fixture(0);f.user['is_courier']=True
 f.db.users.rows.append({'user_id':'courier-b','name':'Synthetic Courier B','is_courier':True})
 f.db.deliveries.rows=[{**delivery_doc(),'status':'available','courier_id':None,'assigned_to_courier_id':None}]
 hit=asyncio.Event();go=asyncio.Event()
 async def pause_claim(q,u):
  if u.get('$set',{}).get('status')=='accepted':hit.set();await go.wait()
 f.db.deliveries.before_update=pause_claim
 a=asyncio.create_task(http(f.dr.claim_delivery('delivery',None)))
 await hit.wait();await f.dr.admin_assign_delivery('delivery',{'courier_id':'courier-b'},None);go.set();code,_=await a
 assert code==403 and f.db.deliveries.rows[0]['assigned_to_courier_id']=='courier-b'
 check('ME02','new reservation prevents old courier claim',http=403,reserved_for='courier-b')
 for failed in [False,True]:
  f=fixture(0);f.db.users.rows.append({'user_id':'courier','role':'vip','vip_balances':{'USDT':0}})
  f.db.deliveries.rows=[delivery_doc('deposit')];f.db.deposits.rows=[{'id':'op','user_id':'client','currency':'USD','amount':100,'status':'pending'}]
  dep=load_module('routes.deposits','routes/deposits.py',f.db,f.user,names=['confirm_deposit_from_delivery','_do_confirm_deposit'],extra={'_notify_client_decision':noop})
  module('email_service',notify_deposit_confirmed=lambda *a:None);f.settle.register_settlement_handler('deposit',dep.confirm_deposit_from_delivery)
  if failed:f.db.deposits.fail=lambda q,u:u.get('$set',{}).get('status')=='confirmed'
  code,resp=await http(f.dr.admin_confirm_delivery('delivery',{},None));assert code==200
  if failed:assert resp.get('settlement_pending')
  f.db.deposits.fail=None;await heal(f);await heal(f)
  assert await balance(f,code='USD')==100 and await balance(f,'courier')==8 and not f.db.deliveries.rows[0].get('settlement_pending')
  check('ME03','pickup linked deposit settles once',interrupted=failed,client_usd=100,courier_usdt=8,healer_cycles=2)

async def chat_scene():
 f=fixture(0);f.db.deliveries.rows=[{**delivery_doc(),'status':'accepted'}]
 perms=load_module('services.permissions','services/permissions.py',f.db,f.user)
 chat=load_module('routes.delivery_chat','routes/delivery_chat.py',f.db,f.user,extra={'_has_permission':perms._has_permission})
 base=datetime.now(timezone.utc)-timedelta(days=1)
 for i in range(301):
  f.db.delivery_chat.rows.append({'id':str(i),'delivery_id':'delivery','sender_id':'courier','sender_kind':'courier','text':'Synthetic '+str(i),'created_at':(base+timedelta(seconds=i)).isoformat(),'read_by':['courier']})
 return f,chat
async def review_chat():
 f,chat=await chat_scene();r=await chat.get_chat('delivery',None)
 assert len(r['messages'])==300 and r['messages'][-1]['id']=='300' and r['has_more']
 assert 'client' not in f.db.delivery_chat.rows[0]['read_by'] and 'client' in f.db.delivery_chat.rows[-1]['read_by']
 older=await chat.get_chat('delivery',None,before=r['messages'][0]['created_at'])
 assert [x['id'] for x in older['messages']]==['0'] and not older['has_more']
 check('ME04','recent page, scoped reads and previous page',total=301,recent=300,older=1)
 # Frontend data/older merge: emulate verbatim JSX state updates with API data.
 saved_older=copy.deepcopy(older['messages']);old_recent_ids=[x['id'] for x in r['messages']]
 chat.require_user=lambda req:value({'user_id':'courier','role':'vip','name':'Synthetic Courier'})
 latest=await chat.send_chat('delivery',{'text':'Synthetic new 302'},None)
 chat.require_user=lambda req:value(copy.deepcopy(f.user));fresh=await chat.get_chat('delivery',None)
 Path('audit_6cc9ee5_chat_fixture.json').write_text(json.dumps({'older':saved_older,'previous':r,'data':fresh,'olderHasMore':older['has_more'],'total_stored':len(f.db.delivery_chat.rows)}))
 c,_=await http(chat._chat_context('delivery',{'user_id':'outsider','role':'vip'}));assert c==403;good('chat denies outsiders',http=403)
 f.db.deliveries.rows[0]['status']='confirmed';c,_=await http(chat.send_chat('delivery',{'text':'Closed'},None));assert c==409;good('closed chat blocks writing',http=409)

async def fee_abort_scene():
 f=fixture(100);order,_=exchange_runtime(f)
 f.db.settings.rows=[{'id':'global','courier_rate_usdt_per_km':0}]
 f.db.products.rows=[{'id':'product','owner_id':'seller','name':'Synthetic Product','price_usd':100,'stock':1,'approval_status':'approved','is_active':True}]
 r=await order.redeem_product(order.RedemptionCreate(product_id='product',quantity=1),None)
 assert await balance(f)==0
 f.db.settings.rows[0]['courier_rate_usdt_per_km']=.5
 return f,r

async def review_fee_abort_overlap():
 f,r=await fee_abort_scene();hit=asyncio.Event();go=asyncio.Event();n=0
 async def pause_rollback(q,u):
  nonlocal n
  if 'courier_fee_op_pending' in u.get('$unset',{}) and 'courier_fee_usd' in u.get('$set',{}):
   n+=1
   if n==1:hit.set();await go.wait()
 f.db.redemptions.before_update=pause_rollback
 a=asyncio.create_task(http(f.admin.set_redemption_courier_fee(r['id'],{'km':20},None)))
 await hit.wait()
 before=copy.deepcopy(f.db.redemptions.rows[0])
 assert before.get('courier_fee_op_pending') and before['courier_fee_usd']==10
 await heal(f)
 after=copy.deepcopy(f.db.redemptions.rows[0])
 assert not after.get('courier_fee_op_pending') and after['courier_fee_usd']==0
 reject_code,_=await http(f.admin.update_redemption(r['id'],{'status':'rejected'},None))
 go.set();fee_code,_=await a
 f.db.redemptions.before_update=None
 await heal(f);await heal(f)
 assert reject_code==200 and fee_code==400 and await balance(f)==100
 check('V01','overlapping recovery restores burned unpaid fee',initial_usdt=100,product_paid=100,fee_after_recovery=0,fee_update_http=fee_code,reject_http=reject_code,final_usdt=100,healer_cycles_after_rejection=2)

async def review_fee_abort_failed_write():
 f,r=await fee_abort_scene()
 f.db.redemptions.fail=lambda q,u:'courier_fee_op_pending' in u.get('$unset',{}) and 'courier_fee_usd' in u.get('$set',{})
 try:
  await f.admin.set_redemption_courier_fee(r['id'],{'km':20},None)
  assert False,'Rollback must fail'
 except RuntimeError:pass
 f.db.redemptions.fail=None
 plan=f.db.redemptions.rows[0]['courier_fee_op_pending']
 log=await f.db.credit_ops.find_one({'op_id':plan['op_id']})
 assert log['state']=='burned' and await balance(f)==0
 await heal(f)
 assert not f.db.redemptions.rows[0].get('courier_fee_op_pending') and f.db.redemptions.rows[0]['courier_fee_usd']==0
 reject_code,_=await http(f.admin.update_redemption(r['id'],{'status':'rejected'},None))
 await heal(f);await heal(f)
 assert reject_code==200 and await balance(f)==100
 check('V01','failed rollback write is recovered before exact refund',initial_usdt=100,product_paid=100,fee_after_recovery=0,debit_log_state='burned',injected_write_failures=1,live_overlap=False,reject_http=200,final_usdt=100,healer_cycles_after_rejection=2)

async def review_fee_undone():
 f,r=await fee_abort_scene()
 f.db.redemptions.fail=lambda q,u:'courier_fee_op_pending' in u.get('$unset',{}) and 'courier_fee_usd' in u.get('$set',{})
 try:await f.admin.set_redemption_courier_fee(r['id'],{'km':20},None)
 except RuntimeError:pass
 f.db.redemptions.fail=None
 plan=copy.deepcopy(f.db.redemptions.rows[0]['courier_fee_op_pending'])
 # Durable compensated state: this is an explicit synthetic state fixture,
 # not a claim that the route above produced 'undone'.
 log=next(x for x in f.db.credit_ops.rows if x['op_id']==plan['op_id']);log['state']='undone'
 f.db.users.rows[0]['vip_balances']['USDT']=50
 await heal(f)
 late=await f.fee.settle_fee_change_plan('redemptions',r['id'],'client',plan)
 assert await balance(f)==50 and f.db.redemptions.rows[0]['courier_fee_usd']==0
 assert not f.db.redemptions.rows[0].get('courier_fee_op_pending')
 check('V01','compensated debit and stale settler preserve new funds',debit_state='undone',synthetic_terminal_fixture=True,balance_usdt=50,fee_usdt=0,late_settle=late)

async def review_batch_stale_writer():
 for mode in ['close','replacement_upload']:
  f,br,ops,b=await seed_current_batch(450)
  hit=asyncio.Event();go=asyncio.Event();n=0
  async def pause_first(d):
   nonlocal n
   n+=1
   if n==1:hit.set();await go.wait()
  f.db.vip_batch_items.before_insert=pause_first
  a=asyncio.create_task(http(br.add_vip_batch_items(b['id'],batch_payload(br,50),None)))
  await hit.wait();assert f.db.vip_batches.rows[0]['items_reserved']==500
  await heal(f)
  assert f.db.vip_batches.rows[0]['items_reserved']==500 and not f.db.vip_batches.rows[0].get('upload_plans')
  assert len(f.db.vip_batch_items.rows)==500
  if mode=='close':code,_=await http(br.close_vip_batch(b['id'],None))
  else:code,_=await http(br.add_vip_batch_items(b['id'],batch_payload(br,50),None))
  assert code==(200 if mode=='close' else 409)
  go.set();upload_code,_=await a
  await heal(f);await heal(f)
  row=f.db.vip_batches.rows[0];stored=len(f.db.vip_batch_items.rows)
  assert upload_code==200 and stored==500 and row['items_reserved']==500
  check('V02','original stale-writer case completed without overflow',mode=mode,first_upload_http=upload_code,second_action_http=code,final_status=row['status'],stored=stored,reserved=row['items_reserved'],items_added_after_close=0,limit=500,healer_cycles_after_resume=2)

async def start_paused_company_sale():
 f=fixture(100);order,_=exchange_runtime(f)
 load_module('services.marketplace_fx','services/marketplace_fx.py',f.db,f.user)
 f.db.settings.rows=[{'id':'global','courier_rate_usdt_per_km':0,'store_currency_code':'CUP'}]
 f.db.rates.rows=[{'from_code':'USDT','to_code':'CUP','rate_vip':100,'rate_normal':100}]
 f.db.products.rows=[{'id':'product','owner_id':'','name':'Synthetic Company Product','price_usd':1000,'cost_usd':600,'stock':2,'is_active':True}]
 hit=asyncio.Event();go=asyncio.Event()
 async def pause_fund(d):
  if d['adjustment_type']=='inflow':hit.set();await go.wait()
 f.db.company_fund_adjustments.before_insert=pause_fund
 creator=asyncio.create_task(order.redeem_product(order.RedemptionCreate(product_id='product',quantity=1),None))
 await hit.wait()
 return f,creator,go

async def reject_and_clear_pending(f):
 rid=f.db.redemptions.rows[0]['id']
 reject_code,_=await http(f.admin.update_redemption(rid,{'status':'rejected'},None))
 assert reject_code==200 and await balance(f)==100 and f.db.products.rows[0]['stock']==2
 await heal(f)
 assert not f.db.redemptions.rows[0].get('sale_trace_pending')
 assert not f.db.company_fund_adjustments.rows
 return rid

def fund_net(f):
 return sum(r['amount']*(1 if r['adjustment_type']=='inflow' else -1) for r in f.db.company_fund_adjustments.rows)

async def review_fund_cleared_plan():
 f,creator,go=await start_paused_company_sale();await reject_and_clear_pending(f)
 failures=0
 def fail_marker(q,u):
  nonlocal failures
  fail='fund_inflow_at' in u.get('$set',{})
  if fail:failures+=1
  return fail
 f.db.redemptions.fail=fail_marker
 go.set();await creator
 f.db.redemptions.fail=None
 await heal(f);await heal(f)
 row=f.db.redemptions.rows[0]
 assert failures==1 and fund_net(f)==0 and row['status']=='rejected' and not row.get('sale_trace_pending')
 assert await balance(f)==100 and f.db.products.rows[0]['stock']==2
 assert len(f.db.company_fund_adjustments.rows)==2
 check('V03','original orphan inflow with failed marker is compensated',injected_write_failures=failures,final_status='rejected',buyer_usdt=100,stock=2,pending_plan=False,fund_net_usdt=0,inflows=1,reversals=1,healer_cycles_after_failure=2)





async def verify_fund_compensation_failure():
 f,creator,go=await start_paused_company_sale();await reject_and_clear_pending(f)
 failures=0
 def fail_reverse(q,u):
  nonlocal failures
  if u.get('adjustment_type')=='outflow' and failures==0:failures+=1;return True
  return False
 f.db.company_fund_adjustments.fail=fail_reverse
 go.set();await creator
 f.db.company_fund_adjustments.fail=None
 await heal(f);await heal(f)
 row=f.db.redemptions.rows[0]
 inflow=f.db.company_fund_adjustments.rows[0]
 assert failures==1 and fund_net(f)==0 and row['status']=='rejected' and not row.get('sale_trace_pending')
 assert inflow['marks_ensured'] is True and len(f.db.company_fund_adjustments.rows)==2
 assert await balance(f)==100 and f.db.products.rows[0]['stock']==2
 check('W02','failed compensation remains recoverable until one reversal completes',pending_case='V03',injected_write_failures=failures,failed_write='fund reversal insert',final_status='rejected',buyer_usdt=100,stock=2,marks_ensured=True,pending_plan=False,fund_net_usdt=0,expected_fund_net_usdt=0,healer_cycles_after_failure=2)

async def verify_fund_recovery_stale_status():
 f,creator,go=await start_paused_company_sale()
 # Fail the marker write so the creator leaves an inflow for orphan recovery.
 f.db.redemptions.fail=lambda q,u:'fund_inflow_at' in u.get('$set',{})
 go.set();await creator;f.db.redemptions.fail=None
 assert fund_net(f)==10 and not f.db.redemptions.rows[0].get('fund_inflow_at')
 # The orphan sweep intentionally operates independently of the pending plan.
 # Remove only the plan in a synthetic fixture to exercise that exact branch.
 f.db.redemptions.rows[0].pop('sale_trace_pending',None)
 hit=asyncio.Event();resume=asyncio.Event()
 async def pause_mark(q,u):
  if 'fund_inflow_at' in u.get('$set',{}):hit.set();await resume.wait()
 f.db.redemptions.before_update=pause_mark
 a=asyncio.create_task(heal(f));await hit.wait()
 rid=f.db.redemptions.rows[0]['id']
 code,_=await http(f.admin.update_redemption(rid,{'status':'rejected'},None));assert code==200
 resume.set();await a;f.db.redemptions.before_update=None
 await heal(f);await heal(f)
 assert fund_net(f)==0 and f.db.company_fund_adjustments.rows[0]['marks_ensured'] is True
 assert await balance(f)==100 and f.db.products.rows[0]['stock']==2
 check('W02','orphan sweep rereads status and compensates concurrent rejection',pending_case='V03',synthetic_orphan_fixture=True,reject_http=200,final_status='rejected',buyer_usdt=100,stock=2,marks_ensured=True,pending_plan=False,fund_net_usdt=0,expected_fund_net_usdt=0,healer_cycles_after_race=2)

def add_courier(f,uid='courier'):
 u={'user_id':uid,'name':'Synthetic '+uid,'role':'vip','is_courier':True,'account_status':'active','vip_balances':{'USDT':0}}
 f.db.users.rows.append(u)
 return u
def act_as(f,uid):
 u=next(r for r in f.db.users.rows if r['user_id']==uid)
 f.dr.require_user=lambda request:value(copy.deepcopy(u))
def init_chat(f):
 perms=load_module('services.permissions','services/permissions.py',f.db,f.user)
 return load_module('routes.delivery_chat','routes/delivery_chat.py',f.db,f.user,extra={'_has_permission':perms._has_permission})
def make_ref(f,status='pending',fee=10):
 r={'id':'op','user_id':'client','user_name':'Synthetic Client','status':status,'total_usd':40,'settlement_currency':'USDT','courier_fee_usdt':fee,'courier_fee_usd':fee,'courier_km':20,'product_name':'Synthetic product','quantity':1,'delivery_address':'Synthetic address'}
 f.db.redemptions.rows=[r]
 return r
def seed_delivery(f,status='available'):
 now=datetime.now(timezone.utc).isoformat()
 d={**delivery_doc(),'status':status,'assigned_to_courier_id':None,'created_at':now,'updated_at':now}
 if status=='available':d.update(courier_id=None,courier_name=None)
 f.db.deliveries.rows=[d];return d
async def complete_job(f,did):
 for state in ('on_the_way','arrived','delivered'):
  pin=(await f.db.deliveries.find_one({'id':did})).get('delivery_pin')
  await f.dr.courier_update_status(did,{'status':state,'pin':pin},None)
 return await f.dr.admin_confirm_delivery(did,{},None)
async def heal(f):
 await f.rec.heal_pending_credits(max_age_seconds=-1)
 await f.rec.heal_initializing_ops(max_age_seconds=-1)


RESULTS={'commit':'6cc9ee527ed5e328f909a17c6488f62eff64a432','checks':[],'findings':[],'controls':[]}

async def verify_w01():
 for resume in [False,True]:
  f,br,ops,b=await seed_current_batch(450)
  hit=asyncio.Event();go=asyncio.Event();n=0
  async def pause(d):
   nonlocal n
   n+=1
   if n==1:hit.set();await go.wait()
  f.db.vip_batch_items.before_insert=pause
  task=asyncio.create_task(http(br.add_vip_batch_items(b['id'],batch_payload(br,50),None)))
  await hit.wait()
  if not resume:
   task.cancel()
   try:await task
   except asyncio.CancelledError:pass
  failures=0
  def fail(q,u):
   nonlocal failures
   if failures==0:failures+=1;return True
   return False
  f.db.vip_batch_items.fail=fail
  await heal(f);f.db.vip_batch_items.fail=None
  assert len(f.db.vip_batch_items.rows)==499 and f.db.vip_batches.rows[0]['upload_plans']
  code,_=await http(br.close_vip_batch(b['id'],None));assert code==409
  await heal(f)
  assert len(f.db.vip_batch_items.rows)==500 and not f.db.vip_batches.rows[0].get('upload_plans')
  code2,_=await http(br.close_vip_batch(b['id'],None));assert code2==200
  if resume:
   go.set();upload_code,_=await task;assert upload_code==200
  await heal(f);await heal(f)
  assert len(f.db.vip_batch_items.rows)==500 and f.db.vip_batches.rows[0]['items_reserved']==500
  check('W01','failed item remains recoverable and blocks close',writer_resumed=resume,first_close_http=409,second_close_http=200,stored=500,reserved=500,late_items=0)

async def verify_w02():
 await verify_fund_compensation_failure()
 await verify_fund_recovery_stale_status()

async def verify_messaging():
 for mode in ['cancel','reassign']:
  f=fixture(0);add_courier(f);add_courier(f,'courier-b');act_as(f,'courier')
  seed_delivery(f,'arrived' if mode=='cancel' else 'accepted');state='delivered' if mode=='cancel' else 'on_the_way'
  hit=asyncio.Event();go=asyncio.Event()
  async def pause(q,u):
   if u.get('$set',{}).get('status')==state:hit.set();await go.wait()
  f.db.deliveries.before_update=pause
  task=asyncio.create_task(http(f.dr.courier_update_status('delivery',{'status':state},None)))
  await hit.wait()
  if mode=='cancel':await f.dr.admin_cancel_delivery('delivery',{},None)
  else:await f.dr.admin_assign_delivery('delivery',{'courier_id':'courier-b'},None)
  go.set();code,_=await task;assert code==409 and await balance(f,'courier')==0
  assert f.db.deliveries.rows[0]['status']==('cancelled' if mode=='cancel' else 'available')
  check('MSG01','stale progress blocked',mode=mode,http=409)
 f=fixture(0);add_courier(f);act_as(f,'courier');make_ref(f);await f.deliveries.ensure_indexes()
 hit=asyncio.Event();go=asyncio.Event();n=0
 async def pause_insert(d):
  nonlocal n
  n+=1
  if n==2:hit.set()
  await go.wait()
 f.db.deliveries.before_insert=pause_insert
 tasks=[asyncio.create_task(http(f.dr.admin_create_delivery({'kind':'redemption','ref_id':'op'},None))) for _ in range(2)]
 await hit.wait();go.set();responses=await asyncio.gather(*tasks)
 assert sorted(r[0] for r in responses)==[200,409] and len(f.db.deliveries.rows)==1
 f.db.deliveries.before_insert=None;did=f.db.deliveries.rows[0]['id']
 await f.dr.claim_delivery(did,None);await complete_job(f,did);await heal(f)
 assert await balance(f,'courier')==8
 check('MSG02','concurrent manual creation converges to one job and payout',http=[200,409],jobs=1,paid=8)
 f=fixture(0);make_ref(f,status='rejected')
 code,_=await http(f.dr.admin_create_delivery({'kind':'redemption','ref_id':'op'},None));assert code==409
 check('MSG03','rejected origin blocks manual creation',http=409)
 f,dep=deposit_fixture();await dep.admin_reject_deposit('op',dep.RejectPayload(admin_note='Synthetic rejection'),None)
 assert f.db.deliveries.rows[0]['status']=='cancelled'
 code,_=await http(f.dr.claim_delivery('delivery',None));assert code==409
 check('MSG03','deposit rejection cancels pickup and blocks acceptance',http=409)
 for mode in ['creation','update']:
  f=fixture(100);make_ref(f,fee=0 if mode=='creation' else 10)
  if mode=='update':seed_delivery(f)
  await f.deliveries.ensure_indexes()
  f.db.deliveries.fail=(lambda q,u:True) if mode=='creation' else (lambda q,u:'fee_usdt' in u.get('$set',{}))
  code,_=await http(f.admin.set_redemption_courier_fee('op',{'km':20 if mode=='creation' else 40},None))
  assert f.db.redemptions.rows[0].get('delivery_sync_pending')
  f.db.deliveries.fail=None;await heal(f);await heal(f)
  expected=10 if mode=='creation' else 20
  assert code==200 and await balance(f)==90 and len(f.db.deliveries.rows)==1 and f.db.deliveries.rows[0]['fee_usdt']==expected
  assert not f.db.redemptions.rows[0].get('delivery_sync_pending')
  check('MSG04','interrupted job synchronization recovers without another charge',mode=mode,source_fee=expected,job_fee=expected,balance=90)
 # Original MSG05 interleaving: pause fee update, confirm to completion, resume.
 f=fixture(100);add_courier(f);make_ref(f);seed_delivery(f,'delivered')
 hit=asyncio.Event();go=asyncio.Event()
 async def pause_fee(q,u):
  if u.get('$set',{}).get('fee_usdt')==20:hit.set();await go.wait()
 f.db.deliveries.before_update=pause_fee
 task=asyncio.create_task(http(f.admin.set_redemption_courier_fee('op',{'km':40},None)))
 await hit.wait();await f.dr.admin_confirm_delivery('delivery',{},None);go.set();code,_=await task
 d=f.db.deliveries.rows[0]
 assert code==200 and d['courier_share_usdt']==8 and d['courier_share_paid_usdt']==8 and d['fee_adjustment_pending']['courier_share_usdt']==16 and await balance(f,'courier')==8
 check('MSG05','original late sync preserves sealed history and flags adjustment',paid=8,recorded=8,pending_adjustment_share=16)
 f=fixture(0);add_courier(f);add_courier(f,'courier-b');act_as(f,'courier');d=seed_delivery(f);d['assigned_to_courier_id']='courier'
 hit=asyncio.Event();go=asyncio.Event()
 async def pause_reject(q,u):
  fields=u.get('$set',{})
  if 'assigned_to_courier_id' in fields and fields['assigned_to_courier_id'] is None and 'status' not in fields:hit.set();await go.wait()
 f.db.deliveries.before_update=pause_reject
 task=asyncio.create_task(http(f.dr.reject_reservation('delivery',{'reason':'Synthetic unavailable'},None)))
 await hit.wait();await f.dr.admin_assign_delivery('delivery',{'courier_id':'courier-b'},None);go.set();code,_=await task
 assert code==409 and d['assigned_to_courier_id']=='courier-b'
 check('MSG06','stale reservation rejection preserves new reservation',http=409,reserved_for='courier-b')
 f=fixture(0);add_courier(f);act_as(f,'courier');init_chat(f)
 base=datetime.now(timezone.utc)-timedelta(hours=1)
 for i in range(51):f.db.deliveries.rows.append({**delivery_doc(),'id':str(i),'status':'confirmed','updated_at':(base+timedelta(seconds=i)).isoformat()})
 result=await f.dr.courier_deliveries(None)
 assert result['earnings']['confirmed_usdt']==408 and result['earnings']['completed_count']==51
 check('MSG07','earnings include complete history',jobs=51,earnings=408,visible_history=50)
 f.db.deliveries.rows=[]
 for i in range(51):f.db.deliveries.rows.append({**delivery_doc(),'id':str(i),'status':'available','courier_id':None,'created_at':(base+timedelta(seconds=i)).isoformat(),'assigned_to_courier_id':'courier' if i==0 else None})
 result=await f.dr.courier_deliveries(None);assert len(result['available'])==51 and result['available'][0]['reserved_for_me']
 check('MSG07','old reservation survives open queue limit',visible=51,reserved_visible=True)
 f=fixture(0);add_courier(f);add_courier(f,'courier-b');init_chat(f);seed_delivery(f,'accepted');act_as(f,'courier')
 await f.dr.courier_share_location({'lat':23.1,'lon':-82.3},None)
 await f.dr.admin_assign_delivery('delivery',{'courier_id':'courier-b'},None);act_as(f,'courier-b');await f.dr.claim_delivery('delivery',None)
 act_as(f,'client');tracked=await f.dr.track_my_deliveries(None);courier=tracked['items'][0]['courier']
 assert courier['name']=='Synthetic courier-b' and not courier.get('location')
 check('MSG08','reassignment clears previous GPS')
 f=fixture(0);rates=load_module('routes.municipality_rates','routes/municipality_rates.py',f.db,f.user)
 f.db.courier_municipality_rates.rows=[{'id':'muni','municipality':'Synthetic Area','price_usdt':3,'active':True}]
 for raw in ['NaN','Infinity','-Infinity',-1]:
  code,_=await http(rates.admin_update_rate('muni',{'price_usdt':raw},None));assert code==400
  check('MSG11','invalid municipality price rejected',input=raw,http=400)
 assert f.db.courier_municipality_rates.rows[0]['price_usdt']==3

def deposit_fixture(status='available'):
 f=fixture(0);add_courier(f);act_as(f,'courier')
 dep=load_module('routes.deposits','routes/deposits.py',f.db,f.user,names=['RejectPayload','admin_reject_deposit','confirm_deposit_from_delivery','_do_confirm_deposit'],extra={'_notify_client_decision':noop})
 module('email_service',notify_deposit_confirmed=lambda *a,**kw:None,notify_deposit_rejected=lambda *a,**kw:None)
 f.settle.register_settlement_handler('deposit',dep.confirm_deposit_from_delivery)
 f.db.deposits.rows=[{'id':'op','user_id':'client','currency':'USD','amount':1500,'usdt_equivalent':1500,'status':'pending','method':'cash','cash_mode':'courier','pickup_address':'Synthetic pickup address','pickup_phone':'00000000','contact_name':'Synthetic Sender'}]
 d=seed_delivery(f,status);d.update(kind='deposit',fee_usdt=0,courier_share_usdt=0,platform_share_usdt=0)
 return f,dep

async def remaining_risks():
 # Fee synchronization can still rewrite the job between payout claim and seal.
 f=fixture(100);add_courier(f);make_ref(f);seed_delivery(f,'delivered')
 hit=asyncio.Event();go=asyncio.Event()
 async def pause_payout(q,u):
  if q.get('user_id')=='courier':hit.set();await go.wait()
 f.db.users.before_update=pause_payout
 task=asyncio.create_task(f.dr.admin_confirm_delivery('delivery',{},None));await hit.wait()
 code,_=await http(f.admin.set_redemption_courier_fee('op',{'km':40},None));go.set();await task
 f.db.users.before_update=None;await heal(f);await heal(f)
 d=f.db.deliveries.rows[0]
 assert d['status']=='confirmed' and d['courier_share_paid_usdt']==8 and d['courier_share_usdt']==16 and await balance(f,'courier')==8 and not d.get('fee_adjustment_pending')
 init_chat(f);act_as(f,'courier');panel=await f.dr.courier_deliveries(None)
 assert panel['earnings']['confirmed_usdt']==16
 bug('N01','fee update between payout claim and seal rewrites displayed commission',previous='MSG05',fee_http=code,actual_paid=8,paid_snapshot=8,displayed_share=16,displayed_earnings=16,adjustment_pending=False)
 # Sync generation checks only the cleanup, not the job write itself.
 f=fixture(100);make_ref(f);seed_delivery(f)
 hit=asyncio.Event();go=asyncio.Event()
 async def pause_old_fee(q,u):
  if u.get('$set',{}).get('fee_usdt')==20:hit.set();await go.wait()
 f.db.deliveries.before_update=pause_old_fee
 task=asyncio.create_task(f.admin.set_redemption_courier_fee('op',{'km':40},None));await hit.wait()
 code,_=await http(f.admin.set_redemption_courier_fee('op',{'km':60},None));assert code==200
 go.set();await task;f.db.deliveries.before_update=None;await heal(f);await heal(f)
 r=f.db.redemptions.rows[0];d=f.db.deliveries.rows[0]
 assert r['courier_fee_usdt']==30 and d['fee_usdt']==20 and not r.get('delivery_sync_pending')
 add_courier(f);act_as(f,'courier');await f.dr.claim_delivery('delivery',None);await complete_job(f,'delivery')
 assert await balance(f,'courier')==16
 bug('N02','old fee synchronization overwrites newer completed synchronization',previous='MSG04',source_fee=30,job_fee=20,client_balance=await balance(f),sync_pending=False,courier_paid=16,expected_at_80_percent=24)
 # Durable propagation of a deposit rejection is still absent on DB failure.
 f,dep=deposit_fixture('accepted')
 f.db.deliveries.fail=lambda q,u:u.get('$set',{}).get('status')=='cancelled'
 code,_=await http(dep.admin_reject_deposit('op',dep.RejectPayload(admin_note='Synthetic rejection'),None))
 f.db.deliveries.fail=None;await heal(f);await heal(f)
 progress,_=await http(f.dr.courier_update_status('delivery',{'status':'on_the_way'},None))
 assert code==200 and progress==200 and f.db.deposits.rows[0]['status']=='rejected'
 bug('N03','failed cancellation of rejected pickup is never retried',previous='MSG03',reject_http=200,progress_http=200,origin_status='rejected',job_status='on_the_way',healer_passes=2)
 # New cash ledger cannot reconstruct a failed automatic event.
 f,dep=deposit_fixture('arrived');await f.deliveries.ensure_indexes()
 pin=f.db.deliveries.rows[0].get('delivery_pin')
 f.db.courier_cash_events.fail=lambda q,u:True
 code,_=await http(f.dr.courier_update_status('delivery',{'status':'delivered','pin':pin},None))
 f.db.courier_cash_events.fail=None;await heal(f);await heal(f)
 retry,_=await http(f.dr.courier_update_status('delivery',{'status':'delivered','pin':pin},None))
 assert code==200 and retry==400 and not f.db.courier_cash_events.rows and f.db.deliveries.rows[0]['status']=='delivered'
 bug('N04','cash pickup ledger event lost after transient failure',delivery_http=200,retry_http=400,collected_usd=1500,ledger_events=0,healer_passes=2)
 # Remaining hard limit affects real totals and unretrievable reservations.
 f=fixture(0);add_courier(f);act_as(f,'courier');init_chat(f);now=datetime.now(timezone.utc).isoformat()
 f.db.deliveries.rows=[{**delivery_doc(),'id':str(i),'status':'available','assigned_to_courier_id':'courier','created_at':now} for i in range(51)]
 result=await f.dr.courier_deliveries(None)
 assert len(result['available'])==50
 bug('N05','more than 50 directed reservations remain inaccessible in panel',previous='MSG07',stored=51,visible=50)
 f.db.deliveries.rows=[{**delivery_doc(),'id':str(i),'status':'confirmed','updated_at':now} for i in range(2001)]
 result=await f.dr.admin_deliveries_summary(None)
 assert result['confirmed_count']==2000 and result['courier_earned_usdt']==16000
 bug('N05','daily administrative totals capped at 2000 confirmations',previous='MSG07',stored=2001,counted=2000,expected_earnings=16008,reported_earnings=16000)

async def main():
 for fn in [review_exchanges,review_fees,review_batches,review_market,review_deliveries,review_chat,check_core_controls,review_fee_abort_overlap,review_fee_abort_failed_write,review_fee_undone,review_batch_stale_writer,review_fund_cleared_plan,verify_w01,verify_w02,verify_messaging,remaining_risks]:
  print('RUN',fn.__name__,file=sys.stderr,flush=True)
  await asyncio.wait_for(fn(),30)
 RESULTS['source_paths']=sorted(LOAD_PATHS)
 print(json.dumps(RESULTS,indent=2,default=str))
if __name__=='__main__':asyncio.run(main())
```


**Anexo: audit_frontend_6cc9ee5.cjs**

SHA-256: `c0950c62a86bf819a007b36509221bc282bb95c3adfeca3c26648863b6cae60e`

```javascript
const fs=require('fs'),assert=require('assert/strict'),vm=require('vm'),path=require('path');
const root=process.argv[2]||'audit-6cc9ee5';
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const out={commit:'6cc9ee527ed5e328f909a17c6488f62eff64a432',checks:[],findings:[],browser_end_to_end:false};
const flush=()=>new Promise(r=>setImmediate(r));
function chatHarness(){
 const src=read('frontend/src/components/DeliveryChatDialog.jsx');
 const updater=src.match(/setMessages\(\(prev\) => \{([\s\S]*?)\n    \}\);/)[1];
 const loadBody=src.match(/const load = useCallback\(\(\) => \{([\s\S]*?)\n  \}, \[deliveryId, mergeMessages\]\);/)[1];
 const resetBody=src.match(/useEffect\(\(\) => \{\n(    \/\/ MSG09[\s\S]*?)\n  \}, \[deliveryId\]\);/)[1];
 const olderBody=src.match(/const loadOlder = async \(\) => \{([\s\S]*?)\n  \};/)[1];
 const sendBody=src.match(/const send = async \(\) => \{([\s\S]*?)\n  \};/)[1];
 const merge=new Function('prev','incoming',updater);
 const genRef={current:0},requests=[];
 const state={messages:[],data:null,text:'',busy:false,reached:false};
 const axios={get:(url,options)=>new Promise(resolve=>requests.push({method:'get',url,options,resolve})),post:(url,body)=>new Promise(resolve=>requests.push({method:'post',url,body,resolve}))};
 const setMessages=v=>{state.messages=typeof v==='function'?v(state.messages):v;};
 const setData=v=>{state.data=v;},setText=v=>{state.text=v;},setBusy=v=>{state.busy=v;},setReachedStart=v=>{state.reached=v;};
 const mergeMessages=incoming=>{if(incoming?.length)state.messages=merge(state.messages,incoming);};
 const reset=()=>new Function('genRef','setMessages','setReachedStart','setData','setText',resetBody)(genRef,setMessages,setReachedStart,setData,setText);
 const make=id=>{
  const load=new Function('deliveryId','genRef','axios','API','setData','mergeMessages','setReachedStart',loadBody).bind(null,id,genRef,axios,'/api',setData,mergeMessages,setReachedStart);
  const older=new Function('allMessages','busy','deliveryId','genRef','axios','API','mergeMessages','setReachedStart','return (async()=>{'+olderBody+'})();').bind(null,state.messages,state.busy,id,genRef,axios,'/api',mergeMessages,setReachedStart);
  const send=new Function('text','busy','deliveryId','axios','API','setBusy','setText','load','toast','return (async()=>{'+sendBody+'})();').bind(null,state.text,state.busy,id,axios,'/api',setBusy,setText,load,{error:()=>{}});
  return {load,older,send};
 };
 const respond=(req,id)=>req.resolve({data:{messages:[{id:id+'1',delivery_id:id,created_at:'2026-09-22T10:00:00Z'}],has_more:false,courier_name:id,my_kind:'client'}});
 return {state,requests,reset,make,respond,merge};
}
async function chats(){
 const c=chatHarness();c.reset();c.make('A').load();c.reset();c.make('B').load();
 c.respond(c.requests[1],'B');await flush();c.respond(c.requests[0],'A');await flush();
 assert.equal(c.state.data.courier_name,'B');assert.deepEqual(c.state.messages.map(m=>m.delivery_id),['B']);
 out.checks.push({id:'MSG09',case:'old refresh response discarded after chat switch',displayed:'B',message_deliveries:['B']});
 const d=chatHarness();d.reset();d.state.messages=[{id:'A1',created_at:'2026-09-22T10:00:00Z'}];const older=d.make('A').older();
 d.reset();d.make('B').load();d.respond(d.requests[1],'B');await flush();d.respond(d.requests[0],'A');await older;
 assert.deepEqual(d.state.messages.map(m=>m.delivery_id),['B']);
 out.checks.push({id:'MSG09',case:'old pagination response discarded after chat switch'});
 const e=chatHarness();e.reset();e.state.text='Synthetic A message';const send=e.make('A').send();
 assert.equal(e.requests[0].method,'post');e.reset();e.make('B').load();e.respond(e.requests[1],'B');await flush();
 e.state.text='Draft for B';e.requests[0].resolve({data:{}});await send;
 assert.equal(e.requests[2].url,'/api/deliveries/A/chat');e.respond(e.requests[2],'A');await flush();
 assert.equal(e.state.data.courier_name,'A');assert.deepEqual(e.state.messages.map(m=>m.delivery_id),['B','A']);assert.equal(e.state.text,'');
 out.findings.push({id:'N06',previous:'MSG09',case:'completion of previous chat send starts a fresh old-chat load using current generation',selected_chat:'B',displayed_context:'A',message_deliveries:['B','A'],draft_b_erased:true});
 let ms=Array.from({length:301},(_,i)=>({id:String(i),created_at:String(i).padStart(4,'0')}));const page=Array.from({length:300},(_,i)=>({id:String(i+2),created_at:String(i+2).padStart(4,'0')}));
 ms=c.merge(ms,page);assert.equal(ms.length,302);assert(ms.some(m=>m.id==='1'));assert.equal(c.merge(ms,page).length,302);
 out.checks.push({id:'R06',case:'same-chat boundary preserved over repeated refresh',messages:302});
}
async function panel(){
 const src=read('frontend/src/pages/dashboard/CourierPanel.jsx'),start=src.indexOf('export default function CourierPanel({ embedded = false }) {');
 const body=src.slice(start+src.slice(start).indexOf('{\n')+2,src.indexOf('\n  if (!data) {',start));
 const factory=new Function('useTranslation','useState','useRef','useCallback','useEffect','axios','API','toast','NEXT_ACTION','navigator','useLiveEvent','setInterval','clearInterval','document',body+'\nreturn {load};');
 let server={available:[],mine:[],history:[]},displayed=null,stateIndex=0,getCalls=0;const effects=[],events={},timers=[],listeners={};
 const doc={hidden:false,addEventListener:(k,f)=>{listeners[k]=f;},removeEventListener:()=>{}};
 factory(()=>({t:x=>x}),v=>{const idx=stateIndex++;return [v,x=>{if(idx===0)displayed=x;}];},v=>({current:v}),f=>f,f=>effects.push(f),{get:async()=>{getCalls++;return {data:JSON.parse(JSON.stringify(server))};}},'/api',{error:()=>{},success:()=>{}},{},{},(k,f)=>{events[k]=f;},(f,ms)=>{timers.push({f,ms});return 1;},()=>{},doc);
 const cleanups=effects.map(f=>f());await flush();assert.equal(getCalls,1);
 for(const [id,trigger] of [['live',()=>events.delivery_changed()],['timer',()=>timers.find(t=>t.ms===30000).f()],['focus',()=>listeners.visibilitychange()]]){
  server.available=[{id}];trigger();await flush();assert.equal(displayed.available[0].id,id);
  out.checks.push({id:'MSG10',case:'external change refreshes panel',trigger:id});
 }
 cleanups.forEach(f=>{if(typeof f==='function')f();});
}
async function push(){
 const route=read('backend/routes/deliveries.py');const assign=route.slice(route.indexOf('async def admin_assign_delivery'),route.indexOf('@router.post("/admin/deliveries/{did}/confirm")'));
 const url=assign.match(/url="([^"]+)"/)[1];assert.equal(url,'/dashboard/deliveries');
 const routes=Array.from(read('frontend/src/App.js').matchAll(/<Route path="([^"]+)"/g),m=>m[1]);assert(routes.some(r=>r===url||(r.endsWith('/*')&&url.startsWith(r.slice(0,-1)))));
 const sw=read('frontend/public/service-worker.js'),click=sw.slice(sw.indexOf('self.addEventListener("notificationclick"'));let handler,navigated,wait;
 vm.runInNewContext(click,{self:{addEventListener:(name,fn)=>{handler=fn;},location:{origin:'https://example.test'},clients:{matchAll:async()=>[],openWindow:async target=>{navigated=target;}}}});
 handler({notification:{close:()=>{},data:{url}},waitUntil:p=>{wait=p;}});await wait;assert.equal(navigated,url);
 assert(read('frontend/src/pages/Dashboard.jsx').includes('deliveries'));
 out.checks.push({id:'MSG10',case:'assignment notification opens valid courier route',target:url,actual_service_worker:true});
}
function eta(){
 const src=read('frontend/src/services/deliveryEta.js').replace(/export /g,''),fn=new Function(src+'\nreturn etaFromDelivery;')();
 const d={delivery_latitude:23.11,delivery_longitude:-82.31,courier_location:{lat:23.1,lon:-82.3,updated_at:new Date(Date.now()-86400000).toISOString()}};
 assert(fn(d).stale);d.courier_location.updated_at=new Date().toISOString();assert(!fn(d).stale);assert.equal(fn({}),null);
 assert(/eta && eta.stale/.test(read('frontend/src/components/DeliveryTrackCard.jsx')));
 out.checks.push({id:'MSG08',case:'old GPS is flagged and rendered as stale; fresh and absent GPS controls pass'});
}
(async()=>{await chats();await panel();await push();eta();console.log(JSON.stringify(out,null,2));})().catch(e=>{console.error(e);process.exit(1);});
```
