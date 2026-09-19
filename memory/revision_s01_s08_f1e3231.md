**Resilience — revisión de billetes, cuentas de efectivo, depósitos y retiros**

Fecha: 19 de septiembre de 2026.

Repositorio: `resiliencebrothers/Resilience-Brothers-p2p-EMERGEN`. Versión revisada: [`f1e3231db6f0360179b8081cc44aefe72d9a9945`](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/commit/f1e3231db6f0360179b8081cc44aefe72d9a9945), `main`, reconfirmada al terminar las comprobaciones. Comparación contra `591c886502f8b60d8216e8dee1d4b28022b1e1b5`: seis commits posteriores.

**Resultado de la revisión**

R01, el pendiente histórico de la última auditoría, queda corregido en su reproducción: la cuenta y la caja terminan en 140 USD, el banco en 60 USD y solo se crea un movimiento, incluso repitiendo la recuperación. Los 26 grupos de controles anteriores también siguen pasando.

Los cambios nuevos están implementados y sus casos básicos funcionan, pero **no corresponde dar por cerrados todos los bugs de caja**. Encontré ocho puntos pendientes: uno de prioridad alta, seis de prioridad media y uno de prioridad baja. Seis hallazgos se reprodujeron con funciones reales del proyecto y una base de datos simulada; uno procede de inspección estática del frontend y otro del resultado real del CI.

El más importante es **S01: un depósito de 40 USD en otra cuenta de efectivo y su posterior traslado a la cuenta principal pueden incrementar Caja de Efectivo dos veces**. En la reproducción, el fondo y las cuentas suman 140 USD, pero la caja registra 180 USD.

No se modificó código de la plataforma, el repositorio remoto ni datos reales. Los valores del informe son datos sintéticos; no demuestran incidentes en cuentas de producción.

| ID | Prioridad | Hallazgo | Evidencia |
|---|---|---|---|
| S01 | **Alta** | Depósito en una cuenta de efectivo secundaria y traslado a la principal duplican el importe en Caja de Efectivo. | Reproducción: cuentas 140 USD; caja 180 USD. |
| S02 | Media | El servidor acepta transferencias y pagos de empresa en efectivo sin desglose de billetes. | Dos reproducciones: saldo 60 USD; billetes siguen representando 100 USD. |
| S03 | Media | Los desgloses del fondo y los de Caja de Efectivo no se sincronizan en ambas direcciones; los pagos de clientes completados en caja no actualizan el inventario por cuenta. | Dos reproducciones con desgloses ausentes o contradictorios. |
| S04 | Media | Se pueden retirar denominaciones que no existen en un conteo reciente. | Conteo 5×20; traslado 4×10 aceptado; quedan −4 billetes de 10. |
| S05 | Media | Un conteo realizado mientras una transferencia está pendiente puede omitirla cuando se confirma después. | Cuenta y caja 60 USD; billetes derivados 100 USD. |
| S06 | Baja | Añadir una denominación no actualiza los formularios que ya estaban montados en la página. | Inspección del estado y la invalidación de `useCashDenoms`. |
| S07 | Media | La tabla unificada solo recibe los 100 depósitos/ajustes más recientes; su filtro no busca los anteriores. | Con 101 depósitos, la llamada usada por la pantalla devuelve 100. |
| S08 | Media | El CI del commit revisado falla en mypy. | Falta la anotación de tipo de `_HAS_DENOMS`, en `account_denoms.py:16`. |

**Comprobación de los cambios comunicados por Emergent**

| Cambio comunicado | Lo observado | Estado |
|---|---|---|
| Billetes actuales = último conteo ± movimientos detallados posteriores | El servicio incorpora ajustes, traslados y retiros de empresa. El caso básico de depósito y pago detallado pasa. | Parcial: S02–S05. |
| Caja física por denominación suma todas las cuentas | El agregado suma las cuentas cash no fusionadas. Un traslado detallado entre dos cuentas conserva el total de billetes del agregado. | Funciona en ese caso; S01 y S03 afectan la coherencia con el módulo Caja de Efectivo. |
| Desglose por cuenta precargado con el estado actual | El formulario toma `denoms_current`, en lugar de depender solo del conteo guardado. | Implementado; el valor derivado depende de resolver S02–S05. |
| Selector de cuenta de efectivo al depositar | Existe y filtra las opciones por método cash. El depósito conserva la cuenta elegida. | Implementado; falta ajustar el espejo físico: S01. |
| Botones separados Depósito y Retiro; eliminación de Ajuste manual en la pantalla | La pantalla abre flujos separados; el diálogo de depósito envía `adjustment_type: "inflow"`. | Confirmado por inspección del frontend. |
| Tabla unificada con filtro por tipo | Combina retiros, depósitos y salidas históricas por ajuste; tiene filtros de tipo, estado y persona. | Implementado; historial incompleto: S07. |
| Billetes obligatorios en transferencias y retiros de efectivo | Hay controles en la interfaz, y se valida la suma si el servidor recibe un desglose. | El servidor no obliga a enviarlo: S02; tampoco valida disponibilidad por denominación: S04. |
| Añadir denominaciones desde Caja física | Existe configuración persistente y se consulta desde los validadores. | Implementado; formularios existentes quedan desactualizados: S06. |
| Regla CUP | El mapa de caja sigue reconociendo CUP y USD; CUPE/CUPT no se convierten en CUP. | Control anterior repetido satisfactoriamente. |

**S01 — El depósito en otra cuenta de efectivo se refleja también en la caja principal**

Prioridad alta. Reproducido con las funciones reales de creación de depósitos y transferencias.

El nuevo selector permite atribuir un depósito a otra cuenta de efectivo. Sin embargo, `mirror_adjustment_to_cash_box()` refleja cualquier ajuste cash en la caja automática sin comprobar `account_id`. Después, una transferencia desde esa cuenta secundaria hacia la principal genera otra entrada física porque su destino es la cuenta canónica. Se contabiliza dos veces el mismo efectivo en `cash_box_movements`.

| Paso de la reproducción | Cuenta principal | Cuenta secundaria | Fondo total | Caja de Efectivo |
|---|---:|---:|---:|---:|
| Inicio | 100 | 0 | 100 | 100 |
| Depósito de 40 en la secundaria | 100 | 40 | 140 | 140 |
| Traslado de esos 40 a la principal | 140 | 0 | 140 | **180** |

El agregado nuevo de billetes por cuenta termina correctamente en 7×20 = 140 USD, lo que hace visible la divergencia con Caja de Efectivo. Sea una caja principal o un consolidado, un traslado interno no justifica elevar el total de efectivo existente de 140 a 180.

Referencias: [espejo de depósitos sin filtro por cuenta](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/cash_box_sync.py#L203-L232), [espejo de transferencias según sus cuentas](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/cash_box_sync.py#L299-L347), [selector nuevo del depósito](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/frontend/src/pages/admin/company-funds/AdjustmentDialog.jsx#L280-L290).

Corrección propuesta: respetar la identidad de la cuenta en todos los espejos. Si la caja automática representa la cuenta principal, un depósito atribuido a otra cuenta no debe entrar allí; el consolidado por moneda debe sumar las cuentas por separado. Si se opta por una caja global, los movimientos entre cuentas incluidas en ella deben ser internos sin entrada neta. Aplicar una única regla a depósitos, pagos y transferencias, y disponer de una reparación trazable para los espejos que ya hayan quedado duplicados.

Aceptación: repetir los tres pasos anteriores debe terminar en fondo 140, cuentas 140 y caja coherente con su alcance, sin llegar a 180. Repetir el recuperador no debe añadir movimientos; cualquier reparación histórica debe invalidar el arqueo afectado y conservar el vínculo a la operación original.

**S02 — El desglose de efectivo sigue siendo opcional en el servidor**

Prioridad media. Reproducido por dos rutas distintas.

La transferencia valida billetes solo dentro de `if payload.denominations`; el pago de empresa hace lo mismo dentro de `if raw_denoms`. Omitir el campo permite confirmar la salida. Que la interfaz lo solicite no garantiza que lo exijan integraciones, clientes anteriores o solicitudes con datos incompletos.

Con 100 USD en la cuenta y cinco billetes de 20, una transferencia de 40 sin `denominations` se acepta: saldo contable 60, inventario de billetes 100. Un retiro de empresa de 40 marcado pagado desde la misma cuenta, sin desglose, produce el mismo resultado.

Referencias: [validación condicional de la transferencia](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/company_fund_accounts.py#L457-L470), [validación condicional del pago](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/admin_company_funds.py#L1312-L1326).

Corrección propuesta: una vez resuelta la cuenta efectiva, exigir desglose no vacío si sale o entra efectivo según la regla de negocio. Aplicar la validación antes de confirmar, consumir o registrar el pago; conservar un tratamiento explícito para datos históricos sin desglose.

Aceptación: una transferencia con extremo cash y un pago desde cuenta cash deben rechazar la ausencia de billetes sin cambiar estados, saldos ni movimientos. Los importes y denominaciones válidos deben seguir funcionando. Una operación bancaria sin efectivo debe conservar su comportamiento válido.

**S03 — El desglose se pierde al pasar entre el fondo y Caja de Efectivo**

Prioridad media. Reproducido en pagos de empresa y de clientes; el espejo de transferencias presenta la misma asignación de valores vacíos por inspección del código.

Aunque el pago empresarial ya guarda `denominations`, su espejo físico sigue escribiendo `denominations: None` y `denoms_pending: True`. La transferencia también descarta el desglose de su documento de origen. Completar posteriormente los billetes desde Caja de Efectivo solo modifica `cash_box_movements`; no actualiza la operación de origen que usa `current_account_denoms()`.

Reproducciones:

- Pago empresarial de 40 con `{"20": 2}`: el documento del pago conserva esos billetes, pero su espejo queda sin desglose. Caja permite completar ese espejo con `{"10": 4}`, dejando dos desgloses distintos para la misma salida.
- Pago de cliente de 40 desde la cuenta principal: después de completar su movimiento en Caja con `{"20": 2}`, cuenta y saldo de caja quedan en 60, pero el inventario por cuenta sigue en 100. El servicio nuevo no consulta retiros de clientes ni los desgloses completados en sus movimientos físicos.

Referencias: [espejo del pago empresarial](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/cash_box_sync.py#L235-L264), [espejo de la transferencia](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/cash_box_sync.py#L329-L346), [completar un movimiento vinculado](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/cash_boxes.py#L300-L325), [fuentes del inventario por cuenta](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/account_denoms.py#L28-L78).

Corrección propuesta: definir un desglose autorizado único por operación y propagarlo al espejo. Si ya existe, no permitir otro incompatible desde Caja. Al completar operaciones históricas, hacer que el inventario por cuenta vea ese desglose y contemple los pagos de clientes, sin contar simultáneamente el origen y su espejo como dos salidas.

Aceptación: el pago o traslado con billetes conocidos debe generar un espejo con esos mismos billetes y sin pendiente. Completar un retiro histórico de cliente debe reducir exactamente una vez las denominaciones de su cuenta, también tras reintentar o recuperar. Un desglose contradictorio debe rechazarse o pasar por una corrección trazable que actualice todas las vistas.

**S04 — Se aceptan billetes que no están disponibles en un conteo reciente**

Prioridad media. Reproducido con un conteo real de la ruta, dentro del entorno simulado.

La validación comprueba denominaciones permitidas, cantidades y suma del importe, pero no contrasta las cantidades con los billetes disponibles en la cuenta de origen. La autorización de gasto comprueba el saldo total, no su composición.

Secuencia: registrar un conteo de 5×20 USD, trasladar 40 USD indicando 4×10. El traslado se confirma y el inventario resultante es `{"20": 5, "10": -4}`. El total matemático es 60 USD, pero la composición es físicamente imposible respecto al conteo recién registrado.

Referencias: [validador del importe por denominación](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/admin_company_funds.py#L116-L138), [autorización del traslado por saldo total](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/company_fund_accounts.py#L472-L507), [aplicación de cantidades al inventario](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/account_denoms.py#L19-L25).

Corrección propuesta: validar y consumir disponibilidad por denominación bajo el mismo control de concurrencia de la salida. Si el inventario histórico es incompleto, tratarlo como una conciliación pendiente explícita; no presentar cantidades negativas como una composición de billetes válida. Un cambio físico de billetes debe quedar registrado antes de utilizarlos.

Aceptación: con 5×20 y ningún billete de 10, pedir 4×10 debe rechazarse sin cambios; 2×20 debe aceptarse. Dos salidas concurrentes no deben usar los mismos billetes. Cubrir tanto traslados como pagos.

**S05 — Un conteo puede excluir una transferencia confirmada después**

Prioridad media. Reproducido controlando el orden de dos solicitudes.

El inventario filtra transferencias posteriores al último conteo por `created_at`. La transferencia asigna esa fecha cuando todavía está `pending` y conserva el valor al confirmarse. Mientras está pendiente, el conteo puede guardarse: no comparte el cerrojo de gasto. Si la confirmación ocurre después, la consulta considera que la transferencia es anterior al conteo y no aplica sus billetes.

Reproducción: partir de 5×20; iniciar una transferencia de 2×20 y pausarla antes de confirmar; guardar un conteo de 5×20; confirmar la transferencia. Saldo contable y de caja: 60 USD. Inventario derivado: 5×20 = 100 USD, cuando corresponderían 3×20 = 60 USD.

Referencias: [corte por fecha de creación de la transferencia](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/account_denoms.py#L52-L64), [creación provisional y confirmación](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/company_fund_accounts.py#L509-L552), [guardado del conteo](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/company_fund_accounts.py#L193-L253).

Corrección propuesta: establecer un corte consistente entre conteo y movimientos efectivos, usando una secuencia o revisión, o coordinación transaccional equivalente. Guardar el momento de confirmación ayuda, pero hay que evitar una nueva carrera entre el conteo y esa confirmación; cambiar solo el nombre del campo no garantiza consistencia. Prever también el tratamiento de transferencias históricas sin ese dato.

Aceptación: repetir exactamente la intercalación anterior debe dejar cuenta y composición de billetes en 60; un conteo posterior que ya incluya una transferencia no debe aplicarla por segunda vez.

**S06 — Las denominaciones añadidas no actualizan los formularios ya montados**

Prioridad baja. Hallazgo por inspección estática; no se ejecutó el navegador de producción.

`invalidateCashDenoms()` solo asigna `cache = null`. Cada consumidor conserva un estado propio y carga los datos en un efecto con dependencias vacías. `AdjustmentDialog` está montado permanentemente por `AdminCompanyFunds`, incluso cuando está cerrado. Añadir, por ejemplo, 10000 CUP desde Caja física no actualiza el estado de ese diálogo al abrirlo después en la misma página.

Referencias: [caché y efecto del hook](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/frontend/src/hooks/useCashDenoms.js#L14-L32), [invalidación tras añadir un billete](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/frontend/src/pages/admin/company-funds/CashBoxDenominationsDialog.jsx#L122-L134), [diálogo montado desde el contenedor](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/frontend/src/pages/admin/AdminCompanyFunds.jsx#L105-L110).

Corrección propuesta: una caché compartida reactiva que notifique a los consumidores, o recargar la configuración al abrir los formularios. Aceptación en navegador: añadir una denominación y, sin recargar la página ni salir del módulo, usarla en un depósito y un traslado.

**S07 — El filtro de la tabla unificada no cubre todo el historial**

Prioridad media. Reproducida la selección del backend y revisado el consumidor del frontend.

La pantalla solicita `/admin/company-funds/adjustments` sin parámetros de paginación. El endpoint devuelve como máximo los 100 registros más recientes por defecto. Después, la tabla une y filtra en memoria solo los registros recibidos; no ofrece un cursor para recuperar los anteriores. El contador de total también se construye con ese conjunto parcial.

Con 101 depósitos guardados, la llamada exacta usada por la pantalla entrega 100. Un depósito antiguo con un nombre distinto no llega al filtro del navegador y no se puede encontrar desde esa tabla, aunque siga registrado en el fondo. No se pierde el saldo contable; se pierde acceso al historial completo desde esa vista.

Referencias: [límite y orden del endpoint](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/routes/admin_company_funds.py#L1568-L1588), [petición sin paginación](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/frontend/src/pages/admin/company-funds/useCompanyFunds.js#L67-L78), [unión y filtro local](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/frontend/src/pages/admin/company-funds/useCompanyFunds.js#L202-L233).

Corrección propuesta: paginación y búsqueda/filtros coherentes en el servidor, con un total real o indicación clara de que se muestran resultados parciales. Elevar el tope a 500 desplaza el problema. Aceptación: con más de 100 depósitos, localizar y abrir uno antiguo desde la misma tabla y mantener correctos los filtros por tipo y persona.

**S08 — El CI vuelve a quedar en rojo por mypy**

Prioridad media como bloqueo de validación; este error de tipos por sí solo no demuestra un fallo en ejecución.

La [ejecución 35448764716](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/actions/runs/35448764716), correspondiente al commit auditado, terminó con `failure`:

| Job | Resultado observado |
|---|---|
| Backend · pytest | Aprobado: `412 passed, 1 skipped, 1 warning in 149.46s`. |
| Frontend · ESLint | Aprobado. |
| Backend · mypy | Fallido: falta anotación de tipo para `_HAS_DENOMS`; un error en 101 archivos comprobados. |

El error está en [`backend/services/account_denoms.py:16`](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f1e3231db6f0360179b8081cc44aefe72d9a9945/backend/services/account_denoms.py#L16). Añadir una anotación compatible con la consulta MongoDB y volver a ejecutar el mismo job. No hace falta eliminar o relajar el control para resolverlo.

La ejecución de pytest corresponde a la selección crítica del proyecto, no a todo el inventario de pruebas. Sus resultados favorables no cubren las interacciones reproducidas en este informe.

**Validación y alcance**

Resultado local: **29 grupos favorables** —26 controles anteriores, R01 corregido y dos escenarios nuevos—, junto con ocho reproducciones negativas que sustentan seis hallazgos distintos: S01, S02, S03, S04, S05 y S07. S02 y S03 tienen dos reproducciones cada uno. S06 es una conclusión de inspección del frontend y S08 está confirmado por el registro del CI.

Se analizaron por AST 363 archivos Python de la copia de backend, sin errores de sintaxis. Se inspeccionaron los cambios de lógica, rutas, interfaz y pruebas. Los 27 archivos descargados para la comparación se verificaron contra sus hashes de contenido Git. La copia conserva los archivos anteriores que no cambiaron; no se editó el checkout de trabajo de la plataforma.

La reproducción usa funciones reales extraídas mediante AST y colecciones en memoria. No se importó ni arrancó el servidor de producción. Autenticación, 2FA, notificaciones y auditoría externa se sustituyen por funciones locales; el reloj se controla en casos de concurrencia. En los escenarios del presupuesto empresarial, los agregados de ganancias y retiros de clientes se fijan a cero; los controles de paridad de clientes utilizan la función real de saldos por cuenta. Los códigos `http` del resultado representan aceptación o `HTTPException` de la función de ruta, sin atravesar la capa HTTP real.

No se probó la interfaz en un navegador ni se consultaron saldos de producción, y no se verificó el commit desplegado. Por tanto, este informe confirma defectos de la versión revisada y resultados de pruebas, no su incidencia real ni la ausencia de otros bugs.

**Orden de corrección sugerido**

1. Resolver S01 y reconciliar los espejos que pudieran haberse generado con la regla anterior.
2. Resolver S02–S05 como parte de la consistencia de billetes: desglose obligatorio, fuente única, disponibilidad y corte del conteo.
3. Completar la actualización de formularios y el acceso al historial de S06–S07.
4. Recuperar el job de mypy de S08 y añadir los escenarios del informe a las pruebas de regresión antes de declarar cerrado el cambio.

**Anexo para Emergent: ejecución reproducible**

Guardar el bloque Python completo como `cash_review_f1e3231.py` y ejecutarlo contra una copia del commit auditado:

```bash
python cash_review_f1e3231.py /ruta/al/repositorio/backend
```

Requiere Python, `pydantic` 2.x y datos de zona horaria `America/Havana`. No requiere credenciales, conexión a MongoDB ni acceso a producción. Incluye una función histórica literal de `70d3eaf` únicamente para construir el estado de la reproducción de R01; las recuperaciones posteriores utilizan la versión actual.

El script comprueba tanto los escenarios favorables como los resultados defectuosos esperados. Su salida sin excepciones no significa que S01–S07 estén corregidos: significa que las reproducciones coinciden con lo documentado. Al implementar las correcciones, convertir las aserciones de los defectos en sus respectivos criterios de aceptación.

**Resultados obtenidos**

```json
{
  "commit": "f1e3231db6f0360179b8081cc44aefe72d9a9945",
  "older_controls": [
    {
      "case": "N01 original expired-lock interleaving",
      "old_request_status": 409,
      "fund": 20
    },
    {
      "case": "N02 source balance then real transfer",
      "cash": 0,
      "bank": 20
    },
    {
      "case": "N03 wrong currency and disabled account",
      "status": 400,
      "withdrawal": "pending"
    },
    {
      "case": "N04 normal concurrent transfers",
      "statuses": [
        200,
        400
      ],
      "box": 20
    },
    {
      "case": "N04 identical operation-id retry",
      "transfers": 1,
      "box": 60
    },
    {
      "case": "N05 failed revision recovered",
      "box": 200,
      "closing_valid": false,
      "movements": 2
    },
    {
      "case": "N06 same automatic account identity",
      "accounts": 1
    },
    {
      "case": "N06 internal transfer has no physical outflow",
      "box": 100
    },
    {
      "case": "CUP rule",
      "CUP": "CUP",
      "CUPE": null,
      "CUPT": null
    }
  ],
  "previous_findings": [
    {
      "case": "M01 former owner resumes before fence stamp",
      "statuses": [
        409,
        200
      ],
      "fund": 20,
      "box": 20
    },
    {
      "case": "M02 backfill before authorization",
      "http": 409,
      "transfer": "aborted",
      "account": 100,
      "box": 100
    },
    {
      "case": "M03 complete merge and backfill twice plus alias payout",
      "no_index_collision": true,
      "mirrored_adjustment": 40,
      "payout_account": "cash-account",
      "box_after_payout": 120
    },
    {
      "case": "M04 historical mirror annulled exactly once",
      "account": 200,
      "box": 200,
      "compensations": 1,
      "closing_valid": false
    },
    {
      "case": "M05 paid origin immutable",
      "origin": "cash-account",
      "attempted": "bank",
      "http": 409,
      "accounts": {
        "cash-account": 60.0,
        "bank": 100.0
      },
      "box": 60.0
    },
    {
      "case": "M05 paid origin immutable",
      "origin": "bank",
      "attempted": "cash-account",
      "http": 409,
      "accounts": {
        "cash-account": 100.0,
        "bank": 60.0
      },
      "box": 100.0
    },
    {
      "case": "M06 real portable suite check",
      "result": "PASS",
      "location": "/workspace/scratch/7dc8319995d5/audit-f1e3231"
    }
  ],
  "latest_fixes": [
    {
      "case": "P01 expired authorized transfer",
      "same_operation_id": false,
      "http": [
        409,
        200
      ],
      "confirmed": 1,
      "account": 20,
      "box": 20,
      "retry_duplicate": false
    },
    {
      "case": "P01 expired authorized transfer",
      "same_operation_id": true,
      "http": [
        409,
        200
      ],
      "confirmed": 1,
      "account": 20,
      "box": 20,
      "retry_duplicate": false
    },
    {
      "case": "P02 recovery aborts before confirmation",
      "http": 409,
      "account_after_rejection": 100,
      "box_after_rejection": 100,
      "subsequent_retry_confirmed": 1,
      "box_after_retry": 20
    },
    {
      "case": "P02 historical aborted mirror with marker",
      "account": 100,
      "box": 100,
      "compensations": 1,
      "closing_valid": false
    },
    {
      "case": "P03 canonical transfer and actual adjustment route",
      "bank_to_alias": {
        "account": 140.0,
        "bank": 60.0,
        "box": 140.0
      },
      "alias_as_origin": "cash-account",
      "equivalent_endpoints_http": 400,
      "adjustment_account": "cash-account",
      "alias_balance": 0
    },
    {
      "case": "P03 historical alias links repaired",
      "account": 160,
      "box": 160,
      "alias_balance": 0
    }
  ],
  "q01_q02": [
    {
      "case": "Q01 missing marker recovered and mirror annulled",
      "account": 100,
      "box": 100,
      "source_status": "aborted",
      "source_marker_present": true,
      "compensations": 1,
      "closing_valid": false
    },
    {
      "case": "Q02 marker reevaluated while repointing alias",
      "account": 140,
      "box": 140,
      "bank": 60,
      "canonical_destination": "cash-account",
      "physical_entries": 1,
      "closing_valid": false
    }
  ],
  "additional_controls": [
    {
      "case": "Q01 compensation is not relinked as original",
      "source_marker_present": false,
      "additional_movements": 0
    },
    {
      "case": "Q02 bank alias remains non-cash",
      "destination": "bank",
      "marker": "na",
      "physical_entries": 0,
      "box": 100
    }
  ],
  "r01_fix": [
    {
      "finding": "R01",
      "status": "corrected",
      "continuation_of": "Q02",
      "case": "upgrade recovers na after previous release already repointed alias",
      "prior_repoint_commit": "70d3eaf89e9aa88a0a8a2f06cde0a6019d46ac30",
      "canonical_destination": "cash-account",
      "before_upgrade": {
        "account": 140,
        "bank": 60,
        "box": 100,
        "marker": "na"
      },
      "after_two_current_recoveries": {
        "account": 140.0,
        "bank": 60.0,
        "box": 140.0,
        "marker": "cmov_tr_historicaltransfer",
        "physical_entries": 1
      }
    }
  ],
  "denomination_review": {
    "favorable_cases": [
      {
        "case": "deposit and detailed enterprise payment update account bills",
        "account_bills": {
          "20": 5
        },
        "account_bill_total": 100
      },
      {
        "case": "detailed transfer conserves aggregate account bills",
        "origin": {
          "20": 3
        },
        "destination": {
          "20": 2
        },
        "total": 100
      }
    ],
    "reproduced_cases": [
      {
        "finding": "S03",
        "case": "paid bills discarded by mirror; conflicting completion accepted",
        "payment_denominations": {
          "20": 2
        },
        "initial_mirror_denominations": null,
        "initial_mirror_pending": true,
        "subsequent_mirror_denominations": {
          "10": 4
        },
        "account_bills_unchanged": {
          "20": 5
        }
      },
      {
        "finding": "S01",
        "case": "secondary cash deposit followed by internal transfer is counted twice in cash box",
        "after_deposit": {
          "fund": 140.0,
          "accounts": {
            "cash-account": 100.0,
            "secondary": 40.0
          },
          "box": 140.0
        },
        "after_transfer": {
          "fund": 140.0,
          "accounts": {
            "cash-account": 140.0,
            "secondary": 0.0
          },
          "box": 180.0
        },
        "aggregate_account_bills": {
          "20": 7
        },
        "aggregate_bill_total": 140
      },
      {
        "finding": "S02",
        "case": "cash transfer without bill breakdown accepted",
        "http": 200,
        "account_balance": 60,
        "account_bill_total": 100,
        "saved_denominations": null
      },
      {
        "finding": "S02",
        "case": "enterprise cash payment without bill breakdown accepted",
        "http": 200,
        "account_balance": 60,
        "account_bill_total": 100
      },
      {
        "finding": "S04",
        "case": "transfer spends denominations absent from counted inventory",
        "http": 200,
        "initial_bills": {
          "20": 5
        },
        "requested_bills": {
          "10": 4
        },
        "remaining_bills": {
          "20": 5,
          "10": -4
        },
        "remaining_total": 60
      },
      {
        "finding": "S05",
        "case": "count while transfer pending causes confirmed bills to be skipped",
        "account_balance": 60,
        "box_balance": 60,
        "account_bill_total": 100,
        "bills": {
          "20": 5
        },
        "expected_bills": {
          "20": 3
        },
        "transfer_created_before_count": true,
        "transfer_confirmed_after_count": true
      },
      {
        "finding": "S03",
        "case": "completed client cash withdrawal never reaches account bill inventory",
        "completed_cashbox_bills": {
          "20": 2
        },
        "account_balance": 60,
        "box_balance": 60,
        "account_bill_total": 100
      },
      {
        "finding": "S07",
        "case": "unified table adjustment request omits older deposit",
        "stored_deposits": 101,
        "returned_by_default": 100,
        "oldest_deposit_available_to_client_filter": false
      }
    ]
  }
}
```

**Script completo**

SHA-256 del script: `778e64bc30bd2b0cbb701138d7e9d8f1b5ff448b3e543ce65f1efec624559718`.

```python
import ast, asyncio, copy, json, sys, types, uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field, ValidationError

ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path('audit-f1e3231/backend').resolve()
class HTTPException(Exception):
    def __init__(self,status_code,detail): self.status_code=status_code; self.detail=detail
def put(d,k,v):
    parts=k.split('.')
    for p in parts[:-1]: d=d.setdefault(p,{})
    d[parts[-1]]=v
def load(path,names,env):
    tree=ast.parse((ROOT/path).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name in names]
    for n in nodes: n.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/path),'exec'),env)
async def noop(*a,**kw): pass
def env(db): return dict(db=db,HTTPException=HTTPException,datetime=datetime,timezone=timezone,Optional=Optional,Any=Any,Request=object,BaseModel=BaseModel,Field=Field,Literal=Literal,uuid=uuid,iso=lambda x:x.isoformat(),now_utc=lambda:datetime.now(timezone.utc))
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
        if k=='$expr':
            assert set(v)=={'$eq'}, v
            args=[get(d,x[1:]) if isinstance(x,str) and x.startswith('$') else x for x in v['$eq']]
            ok=args[0]==args[1]
        elif k=='$or':ok=any(match(d,x) for x in v)
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
def module(name, **kw):
    m=types.ModuleType(name)
    for k,v in kw.items():setattr(m,k,v)
    sys.modules[name]=m
    return m
# Extensions required by the current version; no live imports or connections.
old_get=get
def get(d,k):
    parts=k.split('.')
    if isinstance(d,list) and parts[0].isdigit():
        i=int(parts[0]);v=d[i] if i<len(d) else None
        return get(v,'.'.join(parts[1:])) if len(parts)>1 else v
    return old_get(d,k)
old_condition=condition
def condition(a,v):
    if isinstance(v,dict) and '$gt' in v:
        if a is None or not a>v['$gt']:return False
        v={k:x for k,x in v.items() if k!='$gt'}
    return old_condition(a,v)
BaseColl=Coll
class Coll(BaseColl):
    async def update_one(self,q,u,**kw):
        if kw.get('upsert') and not any(match(d,q) for d in self.rows):
            self.rows.append({k:copy.deepcopy(v) for k,v in q.items() if not isinstance(v,dict)})
        if '$pull' not in u:return await super().update_one(q,u)
        if self.before_update:await self.before_update(q,u)
        if self.fail and self.fail(q,u):raise RuntimeError('simulated update failure')
        for d in self.rows:
            if not match(d,q):continue
            before=copy.deepcopy(d)
            for k,v in u['$pull'].items():put(d,k,[x for x in get(d,k) if not condition(x,v)])
            return types.SimpleNamespace(matched_count=1,modified_count=int(before!=d))
        return types.SimpleNamespace(matched_count=0,modified_count=0)
    async def delete_many(self,q):
        before=len(self.rows);self.rows=[d for d in self.rows if not match(d,q)]
        return types.SimpleNamespace(deleted_count=before-len(self.rows))
def runtime(db):
    e=env(db)
    e.update(logger=logging.getLogger('audit'),Dict=dict,List=list,Response=object)
    module('services')
    module('services.live_events',emit_balance_changed=noop)
    module('services.live_bus',publish=noop)
    return e
async def async_value(x):return x

def source_constant(path,name):
    for n in ast.parse((ROOT/path).read_text()).body:
        targets=n.targets if isinstance(n,ast.Assign) else [n.target] if isinstance(n,ast.AnnAssign) else []
        if any(isinstance(t,ast.Name) and t.id==name for t in targets):
            return ast.literal_eval(n.value)
    raise AssertionError('Missing source constant: '+name)
from zoneinfo import ZoneInfo
from pydantic import ConfigDict
# Extend only Mongo operations used by cash accounting and the current fixes.
class Cursor(Cursor):
    def __aiter__(self):self.i=0;return self
    async def __anext__(self):
        if self.i>=len(self.rows):raise StopAsyncIteration
        row=copy.deepcopy(self.rows[self.i]);self.i+=1;return row
class Coll(Coll):
    def find(self,q,*args):return Cursor([d for d in self.rows if match(d,q)])
    async def count_documents(self,q):return sum(match(d,q) for d in self.rows)
    def aggregate(self,pipe):
        rows=self.rows
        for st in pipe:
            if '$match' in st:rows=[d for d in rows if match(d,st['$match'])]
            elif '$group' in st:
                g=st['$group'];assert g=={'_id':'$type','total':{'$sum':'$amount'}},g
                totals={}
                for d in rows:totals[d['type']]=totals.get(d['type'],0)+d['amount']
                rows=[{'_id':k,'total':v} for k,v in totals.items()]
            else:raise AssertionError(st)
        return Cursor(rows)
    async def update_one(self,q,u,**kw):
        if '$setOnInsert' in u:
            if self.fail and self.fail(q,u):raise RuntimeError('simulated insert failure')
            exists=any(match(d,q) for d in self.rows)
            if not exists and kw.get('upsert'):
                self.rows.append(copy.deepcopy(u['$setOnInsert']))
                return types.SimpleNamespace(matched_count=0,modified_count=0,upserted_id='fake')
            return types.SimpleNamespace(matched_count=int(exists),modified_count=0,upserted_id=None)
        return await super().update_one(q,u,**kw)


class DuplicateKeyError(Exception): pass
class Coll(Coll):
    async def distinct(self,key,q=None):
        out=[]
        for d in self.rows:
            v=get(d,key)
            if match(d,q or {}) and v not in out:out.append(v)
        return out
    async def update_many(self,q,u):
        n=0
        for d in list(self.rows):
            if match(d,q):
                r=await self.update_one({'id':d['id']},u)
                n+=r.modified_count
        return types.SimpleNamespace(modified_count=n)

def cash_runtime(db):
    e=runtime(db)
    e['DEFAULT_CASH_DENOMINATIONS']=source_constant('services/denominations.py','DEFAULT_CASH_DENOMINATIONS')
    e['_SETTINGS_KEY']=source_constant('services/denominations.py','_SETTINGS_KEY')
    load('services/denominations.py',['get_cash_denominations','add_cash_denomination'],e)
    module('services.denominations',DEFAULT_CASH_DENOMINATIONS=e['DEFAULT_CASH_DENOMINATIONS'],get_cash_denominations=e['get_cash_denominations'],add_cash_denomination=e['add_cash_denomination'])
    e['CASH_DENOMINATIONS']=e['DEFAULT_CASH_DENOMINATIONS']
    e['_HAS_DENOMS']=source_constant('services/account_denoms.py','_HAS_DENOMS')
    load('services/account_denoms.py',['_apply','current_account_denoms','cash_denoms_by_currency'],e)
    module('services.account_denoms',current_account_denoms=e['current_account_denoms'],cash_denoms_by_currency=e['cash_denoms_by_currency'])
    e.update(_TZ=ZoneInfo('America/Havana'),FUNDS=('CUP','USD'),DENOMS=e['DEFAULT_CASH_DENOMINATIONS'],ConfigDict=ConfigDict,DuplicateKeyError=DuplicateKeyError,asyncio=asyncio,timedelta=timedelta,_MirrorFn=Any)
    user={'user_id':'admin','name':'Synthetic admin','role':'admin'}
    e.update(require_user=lambda *a:async_value(user),require_admin=lambda *a:async_value(user),require_permission=lambda *a:async_value(user),_enforce_employee_currency_scope=lambda *a:None,_enforce_totp_step_up=noop,log_action=noop,maybe_upload_proof=lambda *a:None)
    e['_LINK_FIELDS']=source_constant('routes/cash_boxes.py','_LINK_FIELDS')
    load('services/cash_box_core.py',['fund_balance'],e)
    e['_fund_balance']=e['fund_balance']
    module('services.cash_box_core',FUNDS=e['FUNDS'],fund_balance=e['fund_balance'])
    load('routes/cash_boxes.py',['_ledger_linked','_bump_fund_rev','BoxUpdate','InitialSet','MovementCreate','MovementUpdate','ArqueoCreate','_is_staff','_get_box_checked','_clean_denoms','_month_range_utc','set_initial','update_box','create_movement','update_movement','delete_movement','create_arqueo','monthly_report'],e)
    load('services/cash_box_arqueo.py',['havana_day_start_utc','closing_arqueo_status','pending_arqueo_funds'],e)
    module('services.cash_box_arqueo',notify_arqueo_discrepancy=noop,havana_day_start_utc=e['havana_day_start_utc'])
    e.update(norm_code=lambda c:str(c or '').strip().upper(),_norm_code=lambda c:str(c or '').strip().upper(),COMPANY_BOX_NAME='Fondo Resilience',CASH_BOX_NAME='Fondo Resilience',SYSTEM_PURPOSE='company_cash',NOT_APPLICABLE='na',_BOX_INDEX_READY=False,_FUND_BY_CURRENCY=source_constant('services/cash_box_sync.py','_FUND_BY_CURRENCY'),HAS_ACC={'$nin':[None,'']})
    syncnames=[n.name for n in ast.parse((ROOT/'services/cash_box_sync.py').read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    load('services/cash_box_sync.py',syncnames,e)
    tree=ast.parse((ROOT/'services/cash_box_sync.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='_SOURCES')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'source constants','exec'),e)
    module('services.cash_box_sync',**{n:e[n] for n in syncnames})
    fanames=['get_or_create_cash_box','resolve_fund_account','auto_paid_from_account','account_assigned_balances','consolidate_duplicate_cash_accounts','_linked_account_fields','repoint_merged_alias_links','_repoint_field','_ensure_cash_account_identity','resolve_payout_account']
    e['_CASH_ACC_INDEX_READY']=False
    load('services/fund_accounts.py',fanames,e)
    module('services.fund_accounts',**{n:e[n] for n in fanames})
    bnames=[n.name for n in ast.parse((ROOT/'services/company_fund_budget.py').read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    for name in ['_EPS','_LOCK_STALE_MINUTES','_LOCK_WAIT_SECONDS','_RESYNC_QUIET_MINUTES','_CLAIM_HEAL_QUIET_SECONDS','_INDEX_READY']:
        e[name]=source_constant('services/company_fund_budget.py',name)
    load('services/company_fund_budget.py',bnames,e)
    module('services.company_fund_budget',**{n:e[n] for n in bnames})
    load('routes/admin_company_funds.py',['CompanyWithdrawal','CompanyWithdrawalCreate','_aggregate_by_currency','_aggregate_manual_adjustments','_aggregate_client_balances','_gather_fund_sources','_compute_company_funds','_build_fund_row','create_company_withdrawal','update_company_withdrawal','_paid_from_account_fields','_claim_cw_transition','_pay_company_withdrawal','_mirror_paid_company_withdrawal','_assert_available_company_funds','_validate_paid_from_balance','_parse_denomination_entry','_validate_denominations'],e)
    e['_CW_TRANSITIONS']=source_constant('routes/admin_company_funds.py','_CW_TRANSITIONS')
    # Empty trade-profit and client-withdrawal aggregates in company-budget scenarios.
    # Client parity controls use the actual account_assigned_balances function.
    e['_aggregate_withdrawals_by_role']=lambda:async_value(({},{}))
    e['_aggregate_profit_by_currency']=lambda:async_value(({},{}))
    e['assert_can_manage_company_funds']=noop
    e['_account_assigned_balances']=e['account_assigned_balances']
    module('routes.admin_company_funds',_validate_denominations=e['_validate_denominations'],_compute_company_funds=e['_compute_company_funds'],CASH_DENOMINATIONS=e['CASH_DENOMINATIONS'])
    load('routes/company_fund_accounts.py',['FundAccountUpdate','update_fund_account','FundTransferCreate','transfer_between_fund_accounts'],e)
    return e

def adj(i='a',amount=100,account='cash-account',method='cash',currency='USD'):
    return {'id':i,'currency':currency,'method':method,'adjustment_type':'inflow','amount':amount,'source_name':'Synthetic owner','account_id':account,'denominations':{'20':int(amount/20)},'created_at':datetime.now(timezone.utc).isoformat()}
async def seed(amount=100):
    a=adj(amount=amount)
    db=DB(company_fund_adjustments=Coll([a]),fund_accounts=Coll([{'id':'cash-account','currency':'USD','method':'cash','name':'Fondo Resilience','system_purpose':'company_cash','is_active':True}]))
    e=cash_runtime(db);await e['mirror_adjustment_to_cash_box'](a)
    return db,e,db.cash_boxes.rows[0]['id']
async def create(e,amount):
    return await e['create_company_withdrawal'](e['CompanyWithdrawalCreate'](amount=amount,currency='USD',beneficiary='Synthetic supplier'),None)
async def pay(e,i,account='cash-account'):
    return await e['update_company_withdrawal'](i,{'status':'paid','paid_from_account_id':account},None)
async def totals(db,e,bid):
    return {'fund':(await e['_compute_company_funds'](['USD']))[0]['balance'],'accounts':await e['account_assigned_balances']('USD'),'box':await e['fund_balance'](await db.cash_boxes.find_one({'id':bid}),'USD')}
async def http_code(awaitable):
    try:await awaitable;return 200
    except HTTPException as ex:return ex.status_code
async def transfer(e,amount,frm='cash-account',to='bank'):
    return await e['transfer_between_fund_accounts'](e['FundTransferCreate'](amount=amount,currency='USD',from_account_id=frm,to_account_id=to,note='Synthetic transfer'),None)


# Simulate declared unique indexes for the account-migration regression.
class Coll(Coll):
    def _validate_unique(self):
        for keys,partial in getattr(self,'unique_defs',[]):
            seen=set()
            for row in self.rows:
                if partial and not match(row,partial):continue
                value=tuple(get(row,key) for key in keys)
                if value in seen:raise DuplicateKeyError('simulated declared unique-index collision')
                seen.add(value)
    async def create_index(self,keys,**kwargs):
        if not kwargs.get('unique'):return
        definition=((keys,) if isinstance(keys,str) else tuple(k for k,_ in keys),kwargs.get('partialFilterExpression'))
        self.unique_defs=getattr(self,'unique_defs',[])
        if definition in self.unique_defs:return
        self.unique_defs.append(definition)
        try:self._validate_unique()
        except Exception:self.unique_defs.pop();raise
    async def update_one(self,q,u,**kwargs):
        before=copy.deepcopy(self.rows)
        result=await super().update_one(q,u,**kwargs)
        try:self._validate_unique()
        except DuplicateKeyError:self.rows=before;raise
        return result

def bank(db):
    db.fund_accounts.rows.append({'id':'bank','name':'Bank','currency':'USD','method':'bank','is_active':True})
def clock_for(e):
    clock=[datetime.now(timezone.utc)];e['now_utc']=lambda:clock[0]
    return clock
async def transfer_with_id(e,amount,op='operation-A',frm='cash-account',to='bank'):
    return await e['transfer_between_fund_accounts'](e['FundTransferCreate'](amount=amount,currency='USD',from_account_id=frm,to_account_id=to,operation_id=op,note='Synthetic transfer'),None)
def client_routes(e):
    names=['_assert_paid_lock','_raise_withdrawal_race','_claim_transition_with_effects','_collect_payout_evidence','_validate_paid_evidence','_assert_cash_courier_ready','update_withdrawal','_post_status_side_effects']
    load('routes/admin_withdrawals.py',names,e)
    module('routes')
    module('routes.notifications',notify_user_withdrawal_step=noop)

async def controls():
    out=[]
    # N01 original: A is paused AFTER writing its fence and checking funds.
    db,e,bid=await seed();clock=clock_for(e)
    db.company_withdrawals.rows=[{'id':i,'currency':'USD','amount':80,'status':'pending'} for i in ['w1','w2']]
    paused=asyncio.Event();go=asyncio.Event();once=True
    async def pause_after_check(q,u):
        nonlocal once
        if once and q.get('id')=='w1' and u.get('$set',{}).get('status')=='paid':
            once=False;paused.set();await go.wait()
    db.company_withdrawals.before_update=pause_after_check
    task=asyncio.create_task(http_code(pay(e,'w1')));await paused.wait()
    clock[0]+=timedelta(minutes=3);await pay(e,'w2');go.set();result=await task
    assert result==409 and (await totals(db,e,bid))['fund']==20
    out.append({'case':'N01 original expired-lock interleaving','old_request_status':409,'fund':20})

    db,e,bid=await seed(20);bank(db)
    db.company_fund_adjustments.rows.append(adj('bank-in',80,'bank','transfer'))
    w=await create(e,80)
    assert await http_code(pay(e,w['id']))==409
    await transfer(e,60,'bank','cash-account');await pay(e,w['id'])
    row=await totals(db,e,bid)
    assert row['accounts']=={'cash-account':0,'bank':20} and row['box']==0
    out.append({'case':'N02 source balance then real transfer','cash':0,'bank':20})

    db,e,bid=await seed()
    db.fund_accounts.rows.append({'id':'cup-account','name':'CUP','currency':'CUP','method':'cash','is_active':True,'system_purpose':'company_cash'})
    w=await create(e,40)
    assert await http_code(pay(e,w['id'],'cup-account'))==400
    db.fund_accounts.rows[0]['is_active']=False
    assert await http_code(pay(e,w['id']))==400
    assert db.company_withdrawals.rows[0]['status']=='pending'
    out.append({'case':'N03 wrong currency and disabled account','status':400,'withdrawal':'pending'})

    db,e,bid=await seed();bank(db)
    original=db.fund_account_transfers.insert_one;paused=asyncio.Event();go=asyncio.Event();once=True;contending=asyncio.Event()
    async def delayed(doc):
        nonlocal once
        if once:once=False;paused.set();await go.wait()
        await original(doc)
    db.fund_account_transfers.insert_one=delayed
    t1=asyncio.create_task(http_code(transfer(e,80)));await paused.wait()
    async def notice(q,u):
        if u.get('$set',{}).get('pay_lock'):contending.set()
    db.company_fund_budgets.before_update=notice
    t2=asyncio.create_task(http_code(transfer(e,80)));await contending.wait();go.set()
    codes=sorted(await asyncio.gather(t1,t2))
    assert codes==[200,400] and (await totals(db,e,bid))['box']==20
    out.append({'case':'N04 normal concurrent transfers','statuses':codes,'box':20})

    db,e,bid=await seed();bank(db)
    a=await transfer_with_id(e,40);b=await transfer_with_id(e,40)
    assert a['id']==b['id'] and len(db.fund_account_transfers.rows)==1 and (await totals(db,e,bid))['box']==60
    out.append({'case':'N04 identical operation-id retry','transfers':1,'box':60})

    db,e,bid=await seed()
    await e['create_arqueo'](bid,e['ArqueoCreate'](fund='USD',counted={'20':5}),None)
    a=adj('old-in',100);a['created_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    db.company_fund_adjustments.rows.append(a)
    db.cash_boxes.fail=lambda q,u:'fund_revs.USD' in u.get('$inc',{})
    try:await e['mirror_adjustment_to_cash_box'](a);raise AssertionError('revision should fail')
    except RuntimeError:pass
    db.cash_boxes.fail=None;await e['backfill_cash_operations']()
    assert (await totals(db,e,bid))['box']==200 and not (await e['closing_arqueo_status'](bid,'USD'))[1]
    assert len(db.cash_box_movements.rows)==2
    out.append({'case':'N05 failed revision recovered','box':200,'closing_valid':False,'movements':2})

    db=DB();e=cash_runtime(db)
    a,b=await asyncio.gather(e['get_or_create_cash_box']('USD'),e['get_or_create_cash_box']('USD'))
    assert a['id']==b['id'] and len(db.fund_accounts.rows)==1
    out.append({'case':'N06 same automatic account identity','accounts':1})

    db,e,bid=await seed()
    db.fund_accounts.rows.append({'id':'dup','name':'Legacy cash','currency':'USD','method':'cash','is_active':True,'system_purpose':'company_cash'})
    tr={'id':'internal','currency':'USD','amount':40,'from_account_id':'cash-account','to_account_id':'dup'}
    assert await e['mirror_fund_transfer_to_cash_box'](tr) is None
    assert (await totals(db,e,bid))['box']==100
    out.append({'case':'N06 internal transfer has no physical outflow','box':100})

    assert [e['fund_for_currency'](c) for c in ['CUP','CUPE','CUPT']]==['CUP',None,None]
    out.append({'case':'CUP rule','CUP':'CUP','CUPE':None,'CUPT':None})
    return out

def add_duplicate_account(db,name='Fondo Resilience'):
    db.fund_accounts.rows.append({'id':'dup','name':name,'currency':'USD','method':'cash','system_purpose':'company_cash','is_active':True,'created_at':datetime.now(timezone.utc).isoformat()})

def legacy_transfer(status='confirmed',target='bank'):
    return {'id':'historical-transfer','currency':'USD','amount':80,'from_account_id':'cash-account','to_account_id':target,'status':status,'created_at':datetime.now(timezone.utc).isoformat()}

async def verify_latest_fixes():
    out=[]
    for same_id in [False,True]:
        db,e,bid=await seed();bank(db);clock=clock_for(e)
        paused=asyncio.Event();go=asyncio.Event();once=True
        async def before_confirm(q,u):
            nonlocal once
            if once and u.get('$set',{}).get('status')=='confirmed':
                once=False;paused.set();await go.wait()
        db.fund_account_transfers.before_update=before_confirm
        ta=asyncio.create_task(http_code(transfer_with_id(e,80,'op-a')));await paused.wait()
        clock[0]+=timedelta(minutes=3)
        op_b='op-a' if same_id else 'op-b'
        sb=await http_code(transfer_with_id(e,80,op_b))
        go.set();sa=await ta
        row=await totals(db,e,bid)
        assert [sa,sb]==[409,200] and row['accounts']=={'cash-account':20,'bank':80} and row['box']==20
        confirmed=[t for t in db.fund_account_transfers.rows if t['status']=='confirmed']
        assert len(confirmed)==1
        retry=await transfer_with_id(e,80,op_b)
        assert retry['id']==confirmed[0]['id']
        assert len(db.cash_box_movements.rows)==2
        out.append({'case':'P01 expired authorized transfer','same_operation_id':same_id,'http':[sa,sb],'confirmed':1,'account':20,'box':20,'retry_duplicate':False})

    db,e,bid=await seed();bank(db);clock=clock_for(e)
    paused=asyncio.Event();go=asyncio.Event();once=True
    async def before_confirm(q,u):
        nonlocal once
        if once and u.get('$set',{}).get('status')=='confirmed':
            once=False;paused.set();await go.wait()
    db.fund_account_transfers.before_update=before_confirm
    task=asyncio.create_task(http_code(transfer_with_id(e,80,'retry-op')));await paused.wait()
    clock[0]+=timedelta(minutes=11)
    await e['backfill_cash_operations']()
    assert db.fund_account_transfers.rows[0]['status']=='aborted'
    go.set();status=await task
    await e['backfill_cash_operations']();row=await totals(db,e,bid)
    assert status==409 and row['accounts']=={'cash-account':100} and row['box']==100
    a=await transfer_with_id(e,80,'retry-op');b=await transfer_with_id(e,80,'retry-op')
    assert a['id']==b['id'] and (await totals(db,e,bid))['box']==20
    out.append({'case':'P02 recovery aborts before confirmation','http':409,'account_after_rejection':100,'box_after_rejection':100,'subsequent_retry_confirmed':1,'box_after_retry':20})

    # Historical P02 residue WITH the reverse marker: repaired exactly once.
    db,e,bid=await seed();bank(db)
    tr=legacy_transfer('aborted');db.fund_account_transfers.rows.append(copy.deepcopy(tr))
    await e['mirror_fund_transfer_to_cash_box']({**tr,'status':'confirmed'})
    assert (await totals(db,e,bid))['box']==20
    await e['create_arqueo'](bid,e['ArqueoCreate'](fund='USD',counted={'20':1}),None)
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    row=await totals(db,e,bid)
    assert row['accounts']=={'cash-account':100} and row['box']==100
    assert len([m for m in db.cash_box_movements.rows if m.get('annuls_movement_id')])==1
    assert not (await e['closing_arqueo_status'](bid,'USD'))[1]
    out.append({'case':'P02 historical aborted mirror with marker','account':100,'box':100,'compensations':1,'closing_valid':False})

    db,e,bid=await seed();bank(db)
    db.company_fund_adjustments.rows.append(adj('bank-in',100,'bank','transfer'))
    add_duplicate_account(db);await e['_ensure_cash_account_identity']()
    assert (await e['resolve_fund_account']('dup'))['id']=='cash-account'
    tr=await transfer(e,40,'bank','dup')
    await e['backfill_cash_operations']();row=await totals(db,e,bid)
    assert tr['to_account_id']=='cash-account' and row['accounts']=={'cash-account':140,'bank':60} and row['box']==140
    from_alias=await transfer(e,20,'dup','bank')
    assert from_alias['from_account_id']=='cash-account'
    assert await http_code(transfer(e,10,'dup','cash-account'))==400
    assert len(db.fund_account_transfers.rows)==2
    # Actual adjustment route; only the catalog lookup is a synthetic USD row.
    e['CASH_DENOMINATIONS']=source_constant('services/denominations.py','DEFAULT_CASH_DENOMINATIONS')
    names=['CompanyFundAdjustment','CompanyFundAdjustmentCreate','_parse_denomination_entry','_validate_denominations','_validate_adjustment_currency','_resolve_adjustment_account','_assert_can_manage_company_funds','_resolve_cash_denominations','_log_adjustment_action','create_company_fund_adjustment']
    load('routes/admin_company_funds.py',names,e)
    module('routes.market',_find_currency_lenient=lambda code:async_value({'code':'USD','is_active':True} if code=='USD' else None))
    payload=e['CompanyFundAdjustmentCreate'](adjustment_type='inflow',currency='USD',amount=20,method='cash',source_name='Synthetic alias deposit',account_id='dup',denominations={'20':1})
    adjustment=await e['create_company_fund_adjustment'](payload,None)
    assert adjustment['account_id']=='cash-account'
    await e['backfill_cash_operations']();row2=await totals(db,e,bid)
    assert row2['accounts']=={'cash-account':140,'bank':80} and row2['box']==140
    out.append({'case':'P03 canonical transfer and actual adjustment route','bank_to_alias':{'account':row['accounts']['cash-account'],'bank':row['accounts']['bank'],'box':row['box']},'alias_as_origin':'cash-account','equivalent_endpoints_http':400,'adjustment_account':adjustment['account_id'],'alias_balance':row2['accounts'].get('dup',0)})

    # Normal historical alias links without stale no-applicable markers.
    db,e,bid=await seed();bank(db)
    db.company_fund_adjustments.rows.append(adj('bank-in',100,'bank','transfer'))
    add_duplicate_account(db);await e['_ensure_cash_account_identity']()
    db.company_fund_adjustments.rows.append(adj('old-alias-deposit',20,'dup'))
    db.fund_account_transfers.rows.append({**legacy_transfer(),'amount':40,'from_account_id':'bank','to_account_id':'dup'})
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    row=await totals(db,e,bid)
    assert row['accounts']=={'cash-account':160,'bank':60} and row['box']==160
    assert db.company_fund_adjustments.rows[-1]['account_id']=='cash-account'
    assert db.fund_account_transfers.rows[0]['to_account_id']=='cash-account'
    out.append({'case':'P03 historical alias links repaired','account':160,'box':160,'alias_balance':0})
    return out

async def recovery_edge_cases():
    out=[]
    # Residue of P02 plus interruption between physical write and source marker.
    db,e,bid=await seed();bank(db)
    tr=legacy_transfer('aborted');db.fund_account_transfers.rows.append(copy.deepcopy(tr))
    db.fund_account_transfers.fail=lambda q,u:'cash_box_movement_id' in u.get('$set',{})
    try:
        await e['mirror_fund_transfer_to_cash_box']({**tr,'status':'confirmed'})
        raise AssertionError('marker write should fail')
    except RuntimeError:
        pass
    db.fund_account_transfers.fail=None
    assert 'cash_box_movement_id' not in db.fund_account_transfers.rows[0]
    assert len([m for m in db.cash_box_movements.rows if m.get('source_transfer_id')==tr['id']])==1
    await e['create_arqueo'](bid,e['ArqueoCreate'](fund='USD',counted={'20':1}),None)
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    row=await totals(db,e,bid)
    assert row['accounts']=={'cash-account':100} and row['box']==100
    assert db.fund_account_transfers.rows[0].get('cash_box_movement_id')
    assert len([m for m in db.cash_box_movements.rows if m.get('annuls_movement_id')])==1
    assert not (await e['closing_arqueo_status'](bid,'USD'))[1]
    out.append({'case':'Q01 missing marker recovered and mirror annulled','account':100,'box':100,'source_status':'aborted','source_marker_present':True,'compensations':1,'closing_valid':False})

    # Before the P03 repair, a renamed merged alias was judged non-cash.
    db,e,bid=await seed();bank(db)
    db.company_fund_adjustments.rows.append(adj('bank-in',100,'bank','transfer'))
    add_duplicate_account(db,'Historical renamed cash');await e['_ensure_cash_account_identity']()
    tr={**legacy_transfer(),'amount':40,'from_account_id':'bank','to_account_id':'dup'}
    db.fund_account_transfers.rows.append(copy.deepcopy(tr))
    # _backfill and mirror_fund_transfer_to_cash_box are unchanged from 9ea9251:
    # this establishes the historical marker before the new repointing step.
    await e['_backfill'](db.fund_account_transfers,{'status':'confirmed'},e['mirror_fund_transfer_to_cash_box'])
    assert db.fund_account_transfers.rows[0]['cash_box_movement_id']=='na'
    await e['create_arqueo'](bid,e['ArqueoCreate'](fund='USD',counted={'20':5}),None)
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    row=await totals(db,e,bid)
    assert db.fund_account_transfers.rows[0]['to_account_id']=='cash-account'
    assert row['accounts']=={'cash-account':140,'bank':60} and row['box']==140
    assert db.fund_account_transfers.rows[0]['cash_box_movement_id'].startswith('cmov_tr_')
    assert len([m for m in db.cash_box_movements.rows if m.get('source_transfer_id')==tr['id']])==1
    assert not (await e['closing_arqueo_status'](bid,'USD'))[1]
    out.append({'case':'Q02 marker reevaluated while repointing alias','account':140,'box':140,'bank':60,'canonical_destination':'cash-account','physical_entries':1,'closing_valid':False})
    return out

async def main():
    result={'commit':'f1e3231db6f0360179b8081cc44aefe72d9a9945','older_controls':await controls(),'previous_findings':await verify_previous_findings(),'latest_fixes':await verify_latest_fixes(),'q01_q02':await recovery_edge_cases(),'additional_controls':await additional_controls(),'r01_fix':await remaining_findings()}
    result['denomination_review']=await run_current_revision_cases()
    print(json.dumps(result,indent=2))



async def verify_previous_findings():
    out=[]
    # Same M01 interleaving as dd10586: A has not stamped its fence yet.
    db,e,bid=await seed();clock=clock_for(e)
    db.company_withdrawals.rows=[{'id':i,'currency':'USD','amount':80,'status':'pending'} for i in ['w1','w2']]
    before_stamp=asyncio.Event();resume_a=asyncio.Event();before_pay_b=asyncio.Event();resume_b=asyncio.Event()
    a_once=True;b_once=True
    async def delay(q,u):
        nonlocal a_once,b_once
        sets=u.get('$set',{})
        if a_once and q.get('id')=='w1' and sets.get('pay_fence'):
            a_once=False;before_stamp.set();await resume_a.wait()
        if b_once and q.get('id')=='w2' and sets.get('status')=='paid':
            b_once=False;before_pay_b.set();await resume_b.wait()
    db.company_withdrawals.before_update=delay
    ta=asyncio.create_task(http_code(pay(e,'w1')));await before_stamp.wait()
    clock[0]+=timedelta(minutes=3)
    tb=asyncio.create_task(http_code(pay(e,'w2')));await before_pay_b.wait()
    resume_a.set();sa=await ta;resume_b.set();sb=await tb
    row=await totals(db,e,bid)
    assert (sa,sb)==(409,200) and row['fund']==20 and row['box']==20
    out.append({'case':'M01 former owner resumes before fence stamp','statuses':[sa,sb],'fund':20,'box':20})

    # Same M02: backfill interleaves before authority; provisional now ignored.
    db,e,bid=await seed();bank(db);clock=clock_for(e)
    original=db.fund_account_transfers.insert_one;written=asyncio.Event();go=asyncio.Event()
    async def after_insert(doc):
        await original(doc);written.set();await go.wait()
    db.fund_account_transfers.insert_one=after_insert
    task=asyncio.create_task(http_code(transfer(e,80)));await written.wait()
    clock[0]+=timedelta(minutes=3);await create(e,1)
    await e['backfill_cash_operations']();go.set();status=await task
    await e['backfill_cash_operations']();row=await totals(db,e,bid)
    assert status==409 and db.fund_account_transfers.rows[0]['status']=='aborted'
    assert row['accounts']=={'cash-account':100} and row['box']==100
    out.append({'case':'M02 backfill before authorization','http':409,'transfer':'aborted','account':100,'box':100})

    db,e,bid=await seed()
    db.fund_accounts.rows.append({'id':'dup','name':'Fondo Resilience','currency':'USD','method':'cash','is_active':True,'system_purpose':'company_cash','created_at':datetime.now(timezone.utc).isoformat()})
    await e['_ensure_cash_account_identity']()
    a=adj('pending-adjustment',40);db.company_fund_adjustments.rows.append(a)
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    dup=await db.fund_accounts.find_one({'id':'dup'})
    assert dup.get('merged_into')=='cash-account' and 'system_purpose' not in dup
    assert 'cash_box_movement_id' in db.company_fund_adjustments.rows[-1]
    assert len(db.cash_box_movements.rows)==2 and (await totals(db,e,bid))['box']==140
    assert (await e['resolve_payout_account']('dup','USD'))['id']=='cash-account'
    w=await create(e,20);await pay(e,w['id'],'dup')
    assert db.company_withdrawals.rows[-1]['paid_from_account_id']=='cash-account'
    out.append({'case':'M03 complete merge and backfill twice plus alias payout','no_index_collision':True,'mirrored_adjustment':40,'payout_account':'cash-account','box_after_payout':120})

    db,e,bid=await seed()
    db.fund_accounts.rows.append({'id':'dup','name':'Legacy renamed cash','currency':'USD','method':'cash','is_active':True,'system_purpose':'company_cash','created_at':datetime.now(timezone.utc).isoformat()})
    a=adj('duplicate-in',100,'dup');db.company_fund_adjustments.rows.append(a);await e['mirror_adjustment_to_cash_box'](a)
    db.fund_account_transfers.rows.append({'id':'old-internal','currency':'USD','amount':40,'from_account_id':'cash-account','to_account_id':'dup','cash_box_movement_id':'old-incorrect-mirror'})
    db.cash_box_movements.rows.append({'id':'old-incorrect-mirror','box_id':bid,'fund':'USD','type':'salida','amount':40,'source_transfer_id':'old-internal','created_at':datetime.now(timezone.utc).isoformat()})
    await e['create_arqueo'](bid,e['ArqueoCreate'](fund='USD',counted={'20':8}),None)
    assert (await e['closing_arqueo_status'](bid,'USD'))[1]
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    row=await totals(db,e,bid)
    assert row['accounts']['cash-account']==200 and row['box']==200
    annuls=[m for m in db.cash_box_movements.rows if m.get('annuls_movement_id')=='old-incorrect-mirror']
    assert len(annuls)==1 and not (await e['closing_arqueo_status'](bid,'USD'))[1]
    out.append({'case':'M04 historical mirror annulled exactly once','account':200,'box':200,'compensations':1,'closing_valid':False})

    for origin,target in [('cash-account','bank'),('bank','cash-account')]:
        db,e,bid=await seed();bank(db);client_routes(e)
        db.company_fund_adjustments.rows.append(adj('bank-in',100,'bank','transfer'))
        db.withdrawals.rows.append({'id':'client-w','user_id':'synthetic-client','currency':'USD','amount_usd':40,'status':'approved','method':'cash','cash_delivery_mode':'office_pickup'})
        await e['update_withdrawal']('client-w',{'status':'paid','paid_from_account_id':origin},None)
        before=await e['account_assigned_balances']('USD');physical=(await totals(db,e,bid))['box']
        code=await http_code(e['update_withdrawal']('client-w',{'status':'paid','paid_from_account_id':target},None))
        assert code==409
        for payload in [{'status':'paid'},{'status':'paid','paid_from_account_id':origin}]:
            assert await http_code(e['update_withdrawal']('client-w',payload,None))==200
        await e['backfill_cash_operations']()
        assert await e['account_assigned_balances']('USD')==before
        assert (await totals(db,e,bid))['box']==physical
        out.append({'case':'M05 paid origin immutable','origin':origin,'attempted':target,'http':409,'accounts':before,'box':physical})

    # Execute the actual portable CI check without importing the test module.
    p=ROOT/'tests/test_iter271_flujo_caja_m01_m06.py'
    e={'Path':Path,'__file__':str(p)}
    load('tests/test_iter271_flujo_caja_m01_m06.py',['TestM06PortableCriticalSuite'],e)
    e['TestM06PortableCriticalSuite']().test_critical_suite_check_is_portable()
    out.append({'case':'M06 real portable suite check','result':'PASS','location':str(ROOT.parent)})
    return out

# Original helper from commit 70d3eaf89e9aa88a0a8a2f06cde0a6019d46ac30.
LEGACY_REPOINT_SOURCE = 'async def repoint_merged_alias_links() -> int:\n    """P03 — re-apunta a la cuenta canónica cualquier vínculo NUEVO que haya\n    vuelto a caer en un alias fusionado (formularios abiertos antes de la\n    migración, reintentos, integraciones): el alias jamás acumula saldo."""\n    n = 0\n    async for alias in db.fund_accounts.find(\n            {"merged_into": {"$nin": [None, ""]}},\n            {"_id": 0, "id": 1, "merged_into": 1}):\n        target = str(alias["merged_into"])\n        for coll, field in _linked_account_fields():\n            res = await coll.update_many({field: alias["id"]},\n                                         {"$set": {field: target}})\n            n += int(res.modified_count)\n    if n:\n        logger.warning("[fund-accounts] %s vínculo(s) re-apuntados desde "\n                       "alias fusionados a su cuenta canónica", n)\n    return n'

async def additional_controls():
    out=[]
    # The inverse-link repair must never treat a compensation as its source.
    db,e,bid=await seed();bank(db)
    tr=legacy_transfer('aborted');db.fund_account_transfers.rows.append(copy.deepcopy(tr))
    db.cash_box_movements.rows.append({'id':'compensation-only','box_id':bid,
        'fund':'USD','type':'entrada','amount':15,
        'source_transfer_id':tr['id'],'annuls_movement_id':'missing-original',
        'created_at':datetime.now(timezone.utc).isoformat()})
    await e['_relink_aborted_transfer_movements']()
    await e['_repair_aborted_transfer_mirrors']()
    await e['_relink_aborted_transfer_movements']()
    await e['_repair_aborted_transfer_mirrors']()
    assert 'cash_box_movement_id' not in db.fund_account_transfers.rows[0]
    assert len(db.cash_box_movements.rows)==2
    out.append({'case':'Q01 compensation is not relinked as original',
        'source_marker_present':False,'additional_movements':0})

    # A merged bank alias must still be classified as bank after reevaluation.
    db,e,bid=await seed();bank(db)
    db.fund_accounts.rows.extend([
        {'id':'bank-2','name':'Bank 2','currency':'USD','method':'bank','is_active':True},
        {'id':'old-bank','name':'Old bank','currency':'USD','method':'bank',
         'is_active':False,'merged_into':'bank'}])
    tr={**legacy_transfer(),'amount':10,'from_account_id':'bank-2',
        'to_account_id':'old-bank','cash_box_movement_id':'na'}
    db.fund_account_transfers.rows.append(tr)
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    assert tr['to_account_id']=='bank' and tr['cash_box_movement_id']=='na'
    assert not [m for m in db.cash_box_movements.rows if m.get('source_transfer_id')==tr['id']]
    assert (await totals(db,e,bid))['box']==100
    out.append({'case':'Q02 bank alias remains non-cash','destination':'bank',
        'marker':'na','physical_entries':0,'box':100})
    return out


async def remaining_findings():
    # Reconstruct the exact final state produced by the previous release.
    # Only its historical repointing function is executed from an embedded
    # verbatim AST extract; all recovery functions below use current sources.
    db,e,bid=await seed();bank(db)
    db.company_fund_adjustments.rows.append(adj('bank-in',100,'bank','transfer'))
    add_duplicate_account(db,'Historical renamed cash')
    await e['_ensure_cash_account_identity']()
    tr={**legacy_transfer(),'amount':40,'from_account_id':'bank','to_account_id':'dup'}
    db.fund_account_transfers.rows.append(copy.deepcopy(tr))
    await e['_backfill'](db.fund_account_transfers,{'status':'confirmed'},
        e['mirror_fund_transfer_to_cash_box'])
    assert db.fund_account_transfers.rows[0]['cash_box_movement_id']=='na'
    legacy_env=dict(e)
    exec(compile(ast.parse(LEGACY_REPOINT_SOURCE),
        '70d3eaf/repoint_merged_alias_links','exec'),legacy_env)
    await legacy_env['repoint_merged_alias_links']()
    before=await totals(db,e,bid)
    assert db.fund_account_transfers.rows[0]['to_account_id']=='cash-account'
    assert before['accounts']=={'cash-account':140,'bank':60} and before['box']==100
    await e['backfill_cash_operations']();await e['backfill_cash_operations']()
    after=await totals(db,e,bid)
    source=db.fund_account_transfers.rows[0]
    assert after['accounts']=={'cash-account':140,'bank':60} and after['box']==140
    assert source['cash_box_movement_id'].startswith('cmov_tr_')
    assert len([m for m in db.cash_box_movements.rows if m.get('source_transfer_id')==tr['id']])==1
    return [{'finding':'R01','status':'corrected','continuation_of':'Q02',
        'case':'upgrade recovers na after previous release already repointed alias',
        'prior_repoint_commit':'70d3eaf89e9aa88a0a8a2f06cde0a6019d46ac30',
        'canonical_destination':source['to_account_id'],
        'before_upgrade':{'account':140,'bank':60,'box':100,'marker':'na'},
        'after_two_current_recoveries':{'account':after['accounts']['cash-account'],
            'bank':after['accounts']['bank'],'box':after['box'],
            'marker':source['cash_box_movement_id'],'physical_entries':1}}]


class Coll(Coll):
    async def find_one(self,q,*args,sort=None,**kwargs):
        rows=[copy.deepcopy(d) for d in self.rows if match(d,q)]
        for field,order in reversed(sort or []):
            rows.sort(key=lambda d:get(d,field) or '',reverse=order<0)
        return rows[0] if rows else None


def adjustment_routes(e):
    names=['CompanyFundAdjustment','CompanyFundAdjustmentCreate',
        '_validate_adjustment_currency','_resolve_adjustment_account',
        '_assert_can_manage_company_funds','_resolve_cash_denominations',
        '_log_adjustment_action','create_company_fund_adjustment']
    load('routes/admin_company_funds.py',names,e)
    module('routes.market',_find_currency_lenient=lambda code:async_value(
        {'code':code,'is_active':True} if code in ('USD','CUP') else None))


async def deposit(e,account,amount=40,denoms=None):
    adjustment_routes(e)
    payload=e['CompanyFundAdjustmentCreate'](adjustment_type='inflow',
        currency='USD',amount=amount,method='cash',source_name='Synthetic owner',
        account_id=account,denominations=denoms or {'20':int(amount/20)})
    return await e['create_company_fund_adjustment'](payload,None)


async def bills(db,e,account='cash-account'):
    acc=await db.fund_accounts.find_one({'id':account})
    return await e['current_account_denoms'](acc)


async def transfer_bills(e,amount=40,frm='cash-account',to='bank',denoms=None):
    return await e['transfer_between_fund_accounts'](
        e['FundTransferCreate'](currency='USD',amount=amount,
            from_account_id=frm,to_account_id=to,denominations=denoms),None)


async def snapshot(db,e,denoms):
    load('routes/company_fund_accounts.py',
        ['DenomsSnapshotPayload','save_account_denoms'],e)
    e['_notify_denoms_mismatch']=noop
    return await e['save_account_denoms']('cash-account',
        e['DenomsSnapshotPayload'](denominations=denoms),None)


async def run_current_revision_cases():
    good=[];bad=[]

    # Normal new flow: an explicit deposit and detailed enterprise payout.
    db,e,bid=await seed();bank(db)
    await deposit(e,'cash-account',40)
    cw=await create(e,40)
    paid=await e['update_company_withdrawal'](cw['id'],{
        'status':'paid','paid_from_account_id':'cash-account',
        'denominations':{'20':2}},None)
    cur=await bills(db,e)
    assert cur['denominations']=={'20':5} and cur['total']==100
    good.append({'case':'deposit and detailed enterprise payment update account bills',
        'account_bills':cur['denominations'],'account_bill_total':cur['total']})
    physical=await db.cash_box_movements.find_one({'source_withdrawal_id':cw['id']})
    assert physical['denominations'] is None and physical['denoms_pending'] is True
    # A conflicting second breakdown is accepted in the cash box because the
    # mirror discarded the breakdown already supplied at payment time.
    await e['update_movement'](bid,physical['id'],
        e['MovementUpdate'](denominations={'10':4}),None)
    assert (await bills(db,e))['denominations']=={'20':5}
    physical=await db.cash_box_movements.find_one({'id':physical['id']})
    assert physical['denominations']=={'10':4}
    bad.append({'finding':'S03','case':'paid bills discarded by mirror; conflicting completion accepted',
        'payment_denominations':paid['denominations'],
        'initial_mirror_denominations':None,'initial_mirror_pending':True,
        'subsequent_mirror_denominations':physical['denominations'],
        'account_bills_unchanged':cur['denominations']})

    # New explicit destination makes a previously automatic mirror inconsistent:
    # deposit in another cash account, then move the same money to canonical.
    db,e,bid=await seed()
    db.fund_accounts.rows.append({'id':'secondary','name':'Secondary cash',
        'currency':'USD','method':'cash','is_active':True})
    await deposit(e,'secondary',40)
    first=await totals(db,e,bid)
    await transfer_bills(e,40,'secondary','cash-account',{'20':2})
    after=await totals(db,e,bid)
    aggregate=await e['cash_denoms_by_currency']()
    assert first['accounts']=={'cash-account':100,'secondary':40} and first['box']==140
    assert after['accounts']=={'cash-account':140,'secondary':0} and after['box']==180
    assert aggregate=={'USD':{20:7}}
    bad.append({'finding':'S01','case':'secondary cash deposit followed by internal transfer is counted twice in cash box',
        'after_deposit':first,'after_transfer':after,
        'aggregate_account_bills':{'20':7},'aggregate_bill_total':140})

    # Mandatory denomination breakdown is not enforced by the server.
    db,e,bid=await seed();bank(db)
    code=await http_code(transfer_bills(e))
    cur=await bills(db,e);row=await totals(db,e,bid)
    assert code==200 and cur['total']==100 and row['accounts']['cash-account']==60
    bad.append({'finding':'S02','case':'cash transfer without bill breakdown accepted',
        'http':code,'account_balance':60,'account_bill_total':100,
        'saved_denominations':db.fund_account_transfers.rows[0]['denominations']})
    db,e,bid=await seed();bank(db)
    cw=await create(e,40);code=await http_code(pay(e,cw['id']))
    cur=await bills(db,e);row=await totals(db,e,bid)
    assert code==200 and cur['total']==100 and row['accounts']['cash-account']==60
    bad.append({'finding':'S02','case':'enterprise cash payment without bill breakdown accepted',
        'http':code,'account_balance':60,'account_bill_total':100})

    # Correct amount but unavailable denominations: accepted as negative bills.
    db,e,bid=await seed();bank(db)
    await snapshot(db,e,{'20':5})
    code=await http_code(transfer_bills(e,denoms={'10':4}))
    cur=await bills(db,e)
    assert code==200 and cur['denominations']=={'20':5,'10':-4}
    bad.append({'finding':'S04','case':'transfer spends denominations absent from counted inventory',
        'http':code,'initial_bills':{'20':5},'requested_bills':{'10':4},
        'remaining_bills':cur['denominations'],'remaining_total':cur['total']})

    # Transfer began before a count but becomes effective afterwards.
    db,e,bid=await seed();bank(db);clock=clock_for(e)
    paused=asyncio.Event();go=asyncio.Event();once=True
    async def before_confirm(q,u):
        nonlocal once
        if once and u.get('$set',{}).get('status')=='confirmed':
            once=False;paused.set();await go.wait()
    db.fund_account_transfers.before_update=before_confirm
    task=asyncio.create_task(transfer_bills(e,denoms={'20':2}))
    await paused.wait()
    clock[0]+=timedelta(seconds=1)
    snap=await snapshot(db,e,{'20':5})
    clock[0]+=timedelta(seconds=1)
    go.set();tr=await task
    cur=await bills(db,e);row=await totals(db,e,bid)
    assert tr['created_at']<snap['created_at'] and tr['status']=='confirmed'
    assert row['accounts']['cash-account']==60 and row['box']==60 and cur['total']==100
    bad.append({'finding':'S05','case':'count while transfer pending causes confirmed bills to be skipped',
        'account_balance':60,'box_balance':60,'account_bill_total':100,
        'bills':cur['denominations'],'expected_bills':{'20':3},
        'transfer_created_before_count':True,'transfer_confirmed_after_count':True})

    # Detailed client withdrawal completed through the existing cash-box route.
    db,e,bid=await seed();client_routes(e)
    db.withdrawals.rows.append({'id':'client-paid','user_id':'synthetic-client',
        'currency':'USD','amount_usd':40,'status':'approved','method':'cash',
        'cash_delivery_mode':'office_pickup'})
    await e['update_withdrawal']('client-paid',
        {'status':'paid','paid_from_account_id':'cash-account'},None)
    mov=await db.cash_box_movements.find_one({'source_client_withdrawal_id':'client-paid'})
    await e['update_movement'](bid,mov['id'],e['MovementUpdate'](denominations={'20':2}),None)
    cur=await bills(db,e);row=await totals(db,e,bid)
    assert row['accounts']['cash-account']==60 and row['box']==60 and cur['total']==100
    bad.append({'finding':'S03','case':'completed client cash withdrawal never reaches account bill inventory',
        'completed_cashbox_bills':{'20':2},'account_balance':60,
        'box_balance':60,'account_bill_total':100})

    # Standard two-account detailed transfer conserves aggregate bills.
    db,e,bid=await seed()
    db.fund_accounts.rows.append({'id':'secondary','name':'Secondary cash',
        'currency':'USD','method':'cash','is_active':True})
    await transfer_bills(e,40,'cash-account','secondary',{'20':2})
    a=await bills(db,e);b=await bills(db,e,'secondary')
    assert a['denominations']=={'20':3} and b['denominations']=={'20':2}
    assert await e['cash_denoms_by_currency']()=={'USD':{20:5}}
    good.append({'case':'detailed transfer conserves aggregate account bills',
        'origin':a['denominations'],'destination':b['denominations'],'total':100})

    # The new unified table requests adjustments without pagination parameters.
    db=DB();e=cash_runtime(db)
    start=datetime(2026,9,1,tzinfo=timezone.utc)
    for i in range(101):
        db.company_fund_adjustments.rows.append({**adj(str(i)),
            'source_name':'Old searched deposit' if i==0 else 'Recent deposit',
            'created_at':(start+timedelta(seconds=i)).isoformat()})
    load('routes/admin_company_funds.py',['list_company_fund_adjustments'],e)
    rows=await e['list_company_fund_adjustments'](None)
    assert len(rows)==100 and not any(r['id']=='0' for r in rows)
    bad.append({'finding':'S07','case':'unified table adjustment request omits older deposit',
        'stored_deposits':101,'returned_by_default':100,
        'oldest_deposit_available_to_client_filter':False})
    return {'favorable_cases':good,'reproduced_cases':bad}


if __name__=='__main__':
    asyncio.run(asyncio.wait_for(main(),30))
```
