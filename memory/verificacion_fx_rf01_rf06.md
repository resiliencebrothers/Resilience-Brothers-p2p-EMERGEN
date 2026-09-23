**Verificación de correcciones: monedas, tasas de cambio y convertidor — Resilience Brothers**

Revisión del 22 de septiembre de 2026, exclusivamente sobre estos módulos. Versión: [`f244eb02c64458ab900f90acdc106a348809bba6`](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/commit/f244eb02c64458ab900f90acdc106a348809bba6), rama `main`. La rama seguía apuntando a esa versión al finalizar las comprobaciones.

**Resultado: todavía no están completamente cerrados los once hallazgos.** Siete pasan los casos revisados y cuatro tienen correcciones parciales. Quedan cinco grupos de fallos funcionales confirmados, más un error de tipado en CI. Los escenarios originales de creación de saldo por redondeo, omisión de permisos de tasas, precios NaN, duplicados de catálogo y exposición de tasas internas sí tienen correcciones verificables; los límites de esos resultados se indican en la tabla.

No se modificó código del repositorio ni se realizaron operaciones sobre cuentas reales. Se contrastó el contenido actual de `Auditoria_Monedas_Tasas_Convertidor_d66806c.md`, cuya última modificación consultada es del 22/09/2026 a las 11:39:16 UTC. La revisión de mensajería pertenece a otro informe y no se vuelve a evaluar aquí.

**Estado de los once casos anteriores**

| Caso | Estado en esta revisión | Qué se verificó y qué queda |
|---|---|---|
| FX01 · Permisos y 2FA al editar tasas | Parcial | POST y PUT rechazan al empleado sin permiso; ambos exigen código para cambiar un par existente en el flujo normal. Una creación concurrente aún puede terminar actualizándolo sin código: RF03. |
| FX02 · Barrido de saldos pequeños | Parcial | El fallo de la escritura atómica no descuenta dinero. Dos barridos concurrentes de 300 CUP producen un éxito, un 409 y una comisión. La tolerancia absoluta permite repetir barridos de cantidades cripto pequeñas: RF04. |
| FX03 · Valores inválidos | Corregido en los casos probados | Se rechazan cero, negativos, NaN, infinitos y valores superiores al límite en campos de tasas; también NaN en tramos. Las tasas antiguas inválidas probadas bloquean la conversión sin descontar. |
| FX04 · Cotización y selección del barrido | Parcial | Coinciden las cotizaciones VIP, las dos direcciones configuradas y la ruta inversa. El barrido ya no inventa USD=USDT. El botón usa el endpoint, pero esa elegibilidad no se refresca cuando cambia una tasa: RF05. |
| FX05 · Monedas bloqueadas | Corregido en los casos probados | Destinos inexistentes, inactivos y no convertibles se rechazan; el barrido también respeta el bloqueo de USDT. |
| FX06 · Identidad de monedas | Corregido en los casos probados | Los códigos inválidos y duplicados se rechazan. CUP con saldo y tasa asociados no puede renombrarse a CUPT ni eliminarse. |
| FX07 · Unicidad de pares | Corregido en los casos probados | Normalización de códigos e índice único; dos creaciones dejan una sola fila y la misma tasa en consulta y valoración. La autorización de la escritura que pierde esa carrera se trata en RF03. |
| FX08 · Exposición de tasa interna | Corregido en los casos probados | El bus real entrega únicamente ID y fecha del cambio a clientes normal/VIP; REST sigue ocultando `real_rate` de la fila y de sus tramos. |
| FX09 · Registro financiero e idempotencia | Parcial | Una conversión sellada conserva su historial aunque falle el log opcional. La recuperación y los reintentos aún tienen errores: RF01 y RF02. |
| FX10 · Cotización aceptada | Corregido en los casos originales probados | La interfaz envía la tasa/total aceptados. Un cambio de 100 a 80 CUP/USDT devuelve 409 sin mover saldos y exige reconfirmar; el hook normal recarga tasas por evento y por `refresh()`. La actualización del botón del barrido queda en RF05. |
| FX11 · Precisión y redondeo | Corregido en los ejemplos originales | 1 USDT produce 0,00001 BTC; la ida y vuelta de 5,01 USDT deja 99,98 USDT desde 100, tras dos comisiones. Un resultado por debajo de la unidad mínima se rechaza antes del descuento. La integridad de saldos cripto pequeños todavía requiere RF04. |

La calificación “corregido” se limita a los casos indicados, sin certificar todo el módulo ni todas sus configuraciones posibles.

**Pendientes para Emergent**

| ID | Prioridad | Hallazgo | Consecuencia reproducida |
|---|---|---|---|
| RF04 | Alta, cuando se usan saldos de unidades pequeñas | La tolerancia de saldo del barrido es mayor que el importe cripto convertido. | Tres barridos del mismo saldo de BTC devuelven éxito, cobran tres comisiones y dejan BTC negativo. |
| RF01 | Alta | El registro de conversiones usa un marcador vacío compartido; además, elimina marcadores todavía necesarios. | Una conversión aplicada queda sin historial, otra rechazada figura como aplicada y un barrido realizado puede marcarse fallido. |
| RF02 | Alta | Los reintentos de la interfaz crean una identidad nueva; el servidor consulta la anterior demasiado tarde. | Una respuesta perdida seguida de reintento ejecuta una segunda conversión y cobra otra comisión. |
| RF03 | Alta | La creación que pierde una carrera actualiza la tasa sin volver a exigir 2FA. | Dos POST sin código cambian sucesivamente el mismo par y ambos responden 200. |
| RF05 | Media | El evento de tasas no refresca la elegibilidad del barrido. | Hay saldo convertible según el servidor, pero el botón continúa oculto hasta refrescar. |
| RF06 | Media | La comprobación mypy falla en el commit revisado. | CI no termina completamente en verde, aunque pytest y ESLint pasan. |

**RF04 — El mismo saldo cripto pequeño se puede barrer varias veces.**

El barrido usa `eps = 1e-6` y autoriza el descuento cuando el saldo es mayor o igual a `importe - eps`. Esa tolerancia se expresa en unidades de cualquier moneda. Para BTC puede superar el saldo que se intenta convertir; por eso comprobar y actualizar en una sola escritura no impide esta carrera. [Tolerancia y filtro del barrido](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/orders.py#L1748), [comparaciones por moneda](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/orders.py#L1782) y [escritura atómica](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/orders.py#L1798).

Reproducción con cotización sintética **1 USDT = 0,00001 BTC**, coherente con el ejemplo anterior de precisión. No se afirma que esa moneda o ese precio estén habilitados en producción:

| Dato | Resultado |
|---|---|
| Saldo inicial | 1 USDT + 0,0000005 BTC —50 satoshis—. |
| Valor de esos BTC al convertir | 0,05 USDT. |
| Un barrido correcto | 1,04 USDT + 0 BTC, después de una comisión de 0,01. |
| Tres solicitudes que leen el saldo antes de escribir | Las tres responden 200. |
| Saldo final observado | **1,12 USDT y −0,000001 BTC**, con tres comisiones. |

La segunda solicitud encuentra cero BTC, pero su filtro aún acepta un saldo de −0,0000005. La tercera también cumple el filtro. Es un fallo de suficiencia de saldo, aunque la escritura sea atómica.

Corrección: representar importes en unidades mínimas enteras o usar una comparación monetaria exacta y coherente con la precisión de cada moneda. No restar una tolerancia absoluta que permita gastar unidades inexistentes. Revisar también las condiciones equivalentes del convertidor normal.

Criterio de aceptación: las tres solicitudes deben producir un solo barrido y dos conflictos; BTC nunca debe quedar negativo y el resultado final debe ser 1,04 USDT. Conservar el test que ya pasa para 300 CUP e incorporar monedas con precisiones distintas.

**RF01 — El historial y su recuperación todavía no son fiables.**

La conversión normal llama a `record_conversion(..., marker_id="")`; la función guarda ese valor sin generar uno nuevo. `mark_conversions` actualiza todas las filas pendientes con ese marcador, sin limitar el usuario ni la conversión. El recuperador, en cambio, omite los marcadores vacíos. [Llamada con marcador vacío](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/orders.py#L1462), [persistencia del marcador](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/services/conversions.py#L184), [actualización de estados](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/services/conversions.py#L223) y [omisión durante la recuperación](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/services/conversions.py#L242).

Se confirmaron tres variantes:

1. **Dinero convertido sin fila visible en el historial.** Convertir 10 USDT desde 100 a 100 CUP/USDT; provocar el fallo al sellar el estado después de mover el saldo. Quedan 89,99 USDT + 1.000 CUP. La fila permanece `applying`, su marcador es vacío y dos pasadas del recuperador no la resuelven. El historial devuelve cero filas.
2. **Una conversión rechazada aparece como realizada.** Dos conversiones de 8 USDT compiten sobre 10 USDT. Una devuelve 200 y la otra 409; el saldo solo recibe 800 CUP, pero las dos filas quedan `applied` y el historial informa un total de 1.600 CUP. La confirmación de la primera alcanzó ambos registros por compartir marcador.
3. **Una prueba de ejecución se elimina demasiado pronto.** El barrido sí usa un marcador no vacío. Si falla su sello, se aplica un crédito de 3 USDT que queda pendiente de reconciliar. Tras 40 conversiones posteriores del mismo usuario, el marcador del barrido desaparece del arreglo limitado a 40. El recuperador lo marca `failed`, aunque el dinero sí se convirtió. [Recorte de marcadores](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/services/conversions.py#L208) y [decisión basada en pertenencia](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/services/conversions.py#L247).

Corrección: asignar una identidad no vacía y única a cada conversión; compartirla únicamente entre las filas del mismo barrido. Condicionar el sellado por usuario y operación. Conservar una prueba durable de la escritura monetaria mientras cualquier registro dependa de ella; no deducir “nunca ocurrió” por ausencia en una lista recortada. Corregir solo el marcador vacío no resuelve la tercera variante.

Criterio de aceptación: la conversión del primer caso reaparece una sola vez después de la recuperación; la segunda variante deja una fila aplicada y una fallida; 40 o más operaciones posteriores no convierten en fallida una operación ya ejecutada. El historial debe coincidir con los movimientos reales en todos los casos.

**RF02 — Un reintento puede convertirse en una segunda operación.**

La interfaz genera `opId` dentro de cada ejecución de `submit`. Si el servidor aplicó la operación pero la respuesta se perdió, el diálogo conserva el importe y muestra error. Al pulsar de nuevo, envía un identificador diferente; el servidor lo interpreta como una nueva conversión. [Creación de la identidad dentro del envío](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/frontend/src/components/BalanceConverterCard.jsx#L155).

Se ejecutó el callback original simulando la pérdida de la primera respuesta y se capturaron sus dos payloads. Ambos contienen 10 USDT, destino CUP y tasa 100, pero identificadores distintos. Al ejecutar esos payloads con la función real del servidor y el índice de idempotencia instalado, se producen dos conversiones: desde 100 USDT se llega a **79,98 USDT + 2.000 CUP**, en vez de **89,99 USDT + 1.000 CUP**. Son dos conversiones y dos comisiones, no dinero desaparecido sin destino.

Existe además un problema de recuperación de la respuesta: incluso usando el mismo `op_id`, el servidor comprueba catálogo, saldo, tasas y comisión antes de buscar la operación anterior. Con 10,01 USDT y una conversión de 10, la repetición del mismo identificador devuelve **400 por saldo insuficiente**, en lugar del comprobante de la conversión ya aplicada. [Validación de saldo previa](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/orders.py#L1299) y [consulta tardía de idempotencia](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/orders.py#L1447).

Corrección: mantener un identificador estable durante los reintentos de una misma intención de conversión; renovarlo cuando cambie la intención o se cierre de forma inequívoca. En el servidor, resolver el registro existente después de autenticar y comprobar su propietario, antes de las condiciones de una nueva ejecución. Asociarlo también a una huella del payload para distinguir errores de reutilización.

Criterio de aceptación: perder la respuesta y pulsar de nuevo debe recuperar el mismo comprobante, con un solo descuento y una comisión. La respuesta debe poder recuperarse aunque el saldo haya quedado en cero o la tasa haya cambiado después de la operación original.

**RF03 — Una creación concurrente cambia una tasa sin el código de confirmación.**

POST exige 2FA de confirmación si su primera lectura encuentra un par existente con valores distintos. Cuando dos solicitudes leen que el par no existe, ninguna pasa por esa confirmación. El índice único impide duplicarlo, pero la solicitud que pierde captura `DuplicateKeyError` y actualiza la fila recién creada con sus propios valores. En esa rama no se vuelve a exigir código. [Comprobación inicial](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/market.py#L606) y [actualización después del conflicto de unicidad](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/routes/market.py#L563).

Reproducción: administrador autenticado con 2FA habilitado; catálogo con USDT y CUP, sin tasa entre ambos; lanzar dos POST con precios 100 y 200, ninguno con `totp_code`, y detenerlos antes de insertar. Al reanudarlos, ambos devuelven 200: se crea la tasa 100 y luego se cambia a 200. Queda una sola fila, pero no se ha protegido la actualización que ocurrió durante la carrera.

Esta prueba no omite autenticación ni el permiso `rates`, que ahora se aplican correctamente. El fallo afecta al código de confirmación del cambio de un precio existente.

Corrección: devolver conflicto y requerir una edición explícita, o aplicar la misma autorización sensible al resolver la carrera. Evitar que una comprobación hecha con datos antiguos autorice una escritura que ahora modifica un precio distinto.

Criterio de aceptación: la solicitud que encuentra el conflicto no puede modificar el precio recién creado sin superar la confirmación exigida a una edición normal. Probar la rama real de conflicto de unicidad, además de dos llamadas secuenciales.

**RF05 — El botón del barrido no se actualiza con las tasas.**

La elegibilidad se obtiene ahora correctamente de `GET /vip/dust`. Sin embargo, `rates_updated` solo ejecuta `loadRates`; no llama a `loadDust`. El estado usado por `dustCount` puede quedar obsoleto aunque la tabla de tasas ya sea nueva. [Carga y evento del hook](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/frontend/src/components/converter/useConverterData.js#L37) y [contador del botón](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/frontend/src/components/BalanceConverterCard.jsx#L59).

Reproducción: 500 CUP con venta a 100 CUP/USDT equivalen a 5 USDT, por lo que no son saldo pequeño. Cambiar la venta a 125 hace que equivalgan a 4 USDT y sean elegibles. Se comprobó el cambio en el endpoint y se ejecutó el hook original: el evento actualiza la tasa, pero el botón sigue con cero elementos; aparece después de `refresh()` manual.

Corrección: invalidar o recargar la elegibilidad cuando cambien tasas y saldos relevantes; mantener coherentes el botón y el diálogo. Gestionar también el orden de las respuestas si coinciden varias recargas.

Criterio de aceptación: sin desmontar el componente ni ejecutar un refresco manual, el evento debe hacer aparecer el botón cuando el saldo cruza el umbral, y ocultarlo cuando deja de cumplirlo.

**RF06 — CI falla en tipado.**

La [ejecución 35745344005 de GitHub Actions](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/actions/runs/35745344005) corresponde exactamente a `f244eb0`:

| Comprobación remota | Resultado |
|---|---|
| pytest | 573 aprobadas, 1 omitida, 1 advertencia. Incluye `test_iter292_audit_monedas.py`. |
| ESLint | Correcto. |
| mypy | Fallo: falta la anotación de tipo del parámetro `v` en `_finite_rate`. Un error en 104 archivos comprobados. |

Ubicación: [backend/services/balances.py, línea 28](https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/blob/f244eb02c64458ab900f90acdc106a348809bba6/backend/services/balances.py#L28). Mensaje: `Function is missing a type annotation for one or more parameters [no-untyped-def]`.

Corrección: añadir una anotación compatible con las entradas reales aceptadas por el helper y volver a ejecutar mypy. No es evidencia de un fallo de ejecución de esa función, pero la validación automática de la revisión no está completamente aprobada.

**Reglas de negocio observadas en las correcciones**

El código implementa ahora liquidación de monedas inactivas como origen, bloqueo de esas monedas como destino y uso de tasas base en el convertidor de saldos; los tramos quedan para órdenes P2P. Estas reglas se observaron y probaron como comportamiento implementado, sin dar por hecho que sus comentarios constituyan una aprobación comercial adicional del usuario. Con base VIP 110 y tramo 115 para 50 USDT, el convertidor sigue entregando 5.500 CUP, no 5.750.

También se comprobó que 3 USD modernos más 3 USD antiguos se consideran 6 antes de decidir si hay saldo pequeño, y que una venta inferior a compra exige `allow_negative_margin=true`. No se mezcló CUP efectivo con CUPT ni se modificó la nomenclatura del negocio.

**Método y evidencia**

Se completaron **60 comprobaciones positivas locales**: 35 verificaciones, 18 controles de backend y 7 de frontend. Se reprodujeron **8 escenarios funcionales distintos**, agrupados en RF01–RF05; RF06 proviene de los registros de CI. Hay dos evidencias complementarias del mismo reintento RF02 —payloads del frontend y su ejecución en backend—, que no se cuentan como dos escenarios independientes.

Los scripts ejecutan funciones del código original mediante extracción AST y una base de datos sintética en memoria con condiciones, índices únicos, índices parciales y escrituras atómicas simuladas. Las pausas y fallos se inyectan antes o después de escrituras concretas. Las pruebas de permisos usan las funciones reales de autorización sobre usuarios simulados; no verifican el inicio de sesión HTTP de un despliegue.

Para el frontend se ejecutaron los hooks, cálculos y callbacks originales con solicitudes simuladas. No se ejecutó una sesión integral de navegador. La prueba de eventos de tasas usó el bus original con dos suscriptores simulados. No se levantó la aplicación ni se conectó una base de datos real.

Las **19 fuentes** usadas o referenciadas en la validación principal se cotejaron por hash con el árbol del commit. Las pruebas remotas de GitHub son evidencia separada: no equivalen a haber ejecutado localmente toda la suite del repositorio. Tampoco se presume que BTC, los precios sintéticos o los estados de fallo usados existan en producción.

**Criterio para cerrar la revisión**

Resolver RF01–RF04, conservar las regresiones originales que ya pasan e incorporar los escenarios descritos a las pruebas. Completar RF05 y recuperar mypy. Especialmente para RF01 y RF04, probar fallos durante el sellado, más de 40 operaciones posteriores y concurrencia con importes inferiores a la tolerancia actual; un test del flujo normal no cubre esos casos.

Los anexos incluyen resultados, metadatos, evidencia de CI y ambos scripts. Las aserciones de los apartados `findings` documentan el fallo presente en la versión auditada; al convertirlas en regresiones para una corrección, sustituirlas por los criterios de aceptación anteriores.

Para reproducir en una copia aislada del commit, extraer los dos scripts siguientes y ejecutar **primero el de frontend**, porque genera los payloads usados por la prueba del reintento en backend:

```bash
node audit_rates_frontend_f244eb0.cjs /ruta/copia-f244eb0
python audit_rates_f244eb0.py /ruta/copia-f244eb0/backend
```

El script Python requiere Python 3.12 y Pydantic 2; JavaScript usa módulos integrados de Node. Los scripts leen la copia del repositorio y generan resultados locales, sin peticiones reales ni modificaciones de su código.


**Anexo: audit_rates_f244eb0_metadata.json**

SHA-256: `c928584a3f7196eaf61c5cf1351143fe102baf7fca6be5e2e2e00979720b51cf`

```json
{
  "commit": "f244eb02c64458ab900f90acdc106a348809bba6",
  "repository": "resiliencebrothers/Resilience-Brothers-p2p-EMERGEN",
  "reviewed_at_utc": "2026-09-22T15:27:07.546889+00:00",
  "head_rechecked_unchanged": true,
  "baseline_report": "Auditoria_Monedas_Tasas_Convertidor_d66806c.md",
  "baseline_report_modified_at": "2026-09-22T11:39:16.732447Z",
  "baseline_commit": "d66806caa6280d6374e8c607d596e8163af9c2dd",
  "python": "3.12.14",
  "sources": [
    {
      "path": ".github/workflows/ci.yml",
      "git_blob_sha": "624b846d83f399e1b0f2bbf78bca5d97b630c830"
    },
    {
      "path": "Makefile",
      "git_blob_sha": "78c33c6afa9eca79db1887dd8b5e79ff0a4199a4"
    },
    {
      "path": "backend/audit_log.py",
      "git_blob_sha": "05d1cddeebac0f702a1d7125144d78da13db03da"
    },
    {
      "path": "backend/auth_utils.py",
      "git_blob_sha": "74fc6f24a8c918b3cf8e3544f054e16d687264f1"
    },
    {
      "path": "backend/routes/market.py",
      "git_blob_sha": "ad02b4e56392d4a8233a1a42675287770aaa03b3"
    },
    {
      "path": "backend/routes/orders.py",
      "git_blob_sha": "04773de1d10fe9e21de3cc1605ac0fc20eb8c211"
    },
    {
      "path": "backend/server.py",
      "git_blob_sha": "cd50aac13b91432fd2f17a26890e9e9aac3103a7"
    },
    {
      "path": "backend/services/balances.py",
      "git_blob_sha": "2ae18bb74b2036d4fcdd75d442be13e4d5c9f35b"
    },
    {
      "path": "backend/services/conversions.py",
      "git_blob_sha": "83ef02d20342be6873f6c9f5729d251740ad1d70"
    },
    {
      "path": "backend/services/credit_recovery.py",
      "git_blob_sha": "ef2774810e00077e1fb6f56cab2d1ef71d263f6a"
    },
    {
      "path": "backend/services/live_bus.py",
      "git_blob_sha": "5b1f0d91d345ca1cab721e664a506a3b3a04031f"
    },
    {
      "path": "backend/services/permissions.py",
      "git_blob_sha": "103fe01ba103fae8682a6b6e9c448e111ede187f"
    },
    {
      "path": "backend/services/rates_catalog.py",
      "git_blob_sha": "0b3f2c31b3c44ce7a9dc7a4d0ed0baff5b8ef7fd"
    },
    {
      "path": "backend/services/transactions.py",
      "git_blob_sha": "081a7543207389b764d5915698294767fe15115c"
    },
    {
      "path": "backend/tests/test_iter292_audit_monedas.py",
      "git_blob_sha": "2aeb688da49cb287629e599ebbea981b66d2e1b3"
    },
    {
      "path": "frontend/src/components/BalanceConverterCard.jsx",
      "git_blob_sha": "824ce2d4e3e7c70a0ad08c972c42143c251b40c9"
    },
    {
      "path": "frontend/src/components/converter/ConvertPreview.jsx",
      "git_blob_sha": "e74751d0cb5e6e56c24180f79fbdd1c5559a816e"
    },
    {
      "path": "frontend/src/components/converter/DustSweepDialog.jsx",
      "git_blob_sha": "fa10be24b64f1f13d19adf6e68085732065c22a4"
    },
    {
      "path": "frontend/src/components/converter/useConverterData.js",
      "git_blob_sha": "ffa34c1e7e5139726d2ca6b7b0662ab3df073d46"
    }
  ],
  "source_count": 19,
  "checks_backend": 35,
  "controls_backend": 18,
  "checks_frontend": 7,
  "total_positive_checks": 60,
  "backend_failure_cases": 7,
  "frontend_failure_cases": 2,
  "distinct_functional_scenarios": 8,
  "functional_bug_groups": 5,
  "additional_ci_issue": 1,
  "repository_modified": false,
  "live_accounts_accessed": false,
  "browser_e2e": false
}
```


**Anexo: audit_rates_f244eb0_ci_summary.json**

SHA-256: `aa045afd2494bf94d020dfbf0b89c56664e2145869756288ee7678901243205e`

```json
{
  "sha": "f244eb02c64458ab900f90acdc106a348809bba6",
  "run_id": 35745344005,
  "jobs": [
    {
      "id": 106805448424,
      "name": "Backend · mypy",
      "conclusion": "failure"
    },
    {
      "id": 106805448519,
      "name": "Frontend · ESLint",
      "conclusion": "success"
    },
    {
      "id": 106805448780,
      "name": "Backend · pytest",
      "conclusion": "success"
    }
  ],
  "logs": [
    {
      "job_id": 106805448424,
      "excerpts": [
        "2026-09-22T15:10:24.2837620Z services/balances.py:28: error: Function is missing a type annotation for one",
        "or more parameters [no-untyped-def]",
        "def _finite_rate(v) -> Optional[float]:",
        "2026-09-22T15:10:25.2435016Z Found 1 error in 1 file (checked 104 source files)"
      ]
    },
    {
      "job_id": 106805448780,
      "excerpts": [
        "2026-09-22T15:11:02.2607157Z \ttests/test_iter292_audit_monedas.py \\",
        "2026-09-22T15:15:23.9514379Z 573 passed, 1 skipped, 1 warning in 260.81s (0:04:20)"
      ]
    },
    {
      "job_id": 106805448519,
      "excerpts": [
        "2026-09-22T15:10:10.6236683Z Done in 16.86s.",
        "2026-09-22T15:10:12.9122156Z Done in 2.11s."
      ]
    }
  ],
  "url": "https://github.com/resiliencebrothers/Resilience-Brothers-p2p-EMERGEN/actions/runs/35745344005"
}
```


**Anexo: audit_rates_f244eb0_results.json**

SHA-256: `705df9f854c52b20a34b9873055a9e34953bf729f06a18603bc1d00ce7e80076`

```json
{
  "commit": "f244eb02c64458ab900f90acdc106a348809bba6",
  "checks": [
    {
      "id": "FX01",
      "case": "both write routes reject unauthorized edits",
      "actor": "employee",
      "codes": [
        403,
        403
      ]
    },
    {
      "id": "FX01",
      "case": "both write routes reject unauthorized edits",
      "actor": "admin",
      "codes": [
        401,
        401
      ]
    },
    {
      "id": "FX03",
      "case": "invalid price values rejected by model",
      "field": "rate_normal",
      "invalid_values": 6
    },
    {
      "id": "FX03",
      "case": "invalid price values rejected by model",
      "field": "rate_vip",
      "invalid_values": 6
    },
    {
      "id": "FX03",
      "case": "invalid price values rejected by model",
      "field": "rate_sell",
      "invalid_values": 6
    },
    {
      "id": "FX03",
      "case": "invalid price values rejected by model",
      "field": "real_rate",
      "invalid_values": 6
    },
    {
      "id": "FX03",
      "case": "nonfinite tier fields rejected"
    },
    {
      "id": "FX03",
      "case": "invalid legacy rate causes no debit",
      "invalid": "nan",
      "http": 400
    },
    {
      "id": "FX03",
      "case": "invalid legacy rate causes no debit",
      "invalid": "inf",
      "http": 400
    },
    {
      "id": "FX03",
      "case": "invalid legacy rate causes no debit",
      "invalid": "-1",
      "http": 400
    },
    {
      "id": "FX03",
      "case": "invalid legacy rate causes no debit",
      "invalid": "0",
      "http": 400
    },
    {
      "id": "FX11",
      "case": "previous zero-result BTC example preserves small units",
      "input_USDT": 1,
      "output_BTC": 1e-05
    },
    {
      "id": "FX11",
      "case": "previous BTC round trip cannot inflate balance",
      "bought_BTC": 5.01e-05,
      "returned_USDT": 5.01,
      "final_USDT": 99.98
    },
    {
      "id": "FX11",
      "case": "result below currency precision rejected before debit",
      "http": 400
    },
    {
      "id": "FX04",
      "case": "manual and dust use identical executable quote",
      "scenario": "VIP direct",
      "output": 3.3
    },
    {
      "id": "FX04",
      "case": "manual and dust use identical executable quote",
      "scenario": "both directions",
      "output": 2.4
    },
    {
      "id": "FX04",
      "case": "dust refuses unconfigured USD-USDT parity",
      "http": 400
    },
    {
      "id": "FX04",
      "case": "server dust selector exposes item eligible at sell price",
      "balance_CUP": 500,
      "total_USDT": 4.1666
    },
    {
      "id": "FX04",
      "case": "backend eligibility changes when sell price crosses dust threshold",
      "balance_CUP": 500,
      "before_count": 0,
      "after_count": 1,
      "after_total_USDT": 4
    },
    {
      "id": "FX02",
      "case": "failed dust atomic write moves nothing and retry charges once",
      "final": {
        "USDT": 3.99,
        "CUP": 0.0
      }
    },
    {
      "id": "FX02",
      "case": "original concurrent CUP sweeps produce one fee",
      "http": [
        200,
        409
      ],
      "final": {
        "USDT": 3.99,
        "CUP": 0.0
      }
    },
    {
      "id": "FX05",
      "case": "unavailable destination rejected",
      "mode": "inactive",
      "http": 400
    },
    {
      "id": "FX05",
      "case": "unavailable destination rejected",
      "mode": "deleted",
      "http": 400
    },
    {
      "id": "FX05",
      "case": "unavailable destination rejected",
      "mode": "nonconvertible",
      "http": 400
    },
    {
      "id": "FX05",
      "case": "both converters enforce USDT destination guard",
      "mode": "nonconvertible",
      "codes": [
        400,
        400
      ]
    },
    {
      "id": "FX05",
      "case": "both converters enforce USDT destination guard",
      "mode": "inactive",
      "codes": [
        400,
        400
      ]
    },
    {
      "id": "FX05",
      "case": "both converters enforce USDT destination guard",
      "mode": "deleted",
      "codes": [
        400,
        400
      ]
    },
    {
      "id": "FX06",
      "case": "referenced CUP cannot be renamed or deleted",
      "http": [
        409,
        409
      ],
      "balance_CUP": 300
    },
    {
      "id": "FX06",
      "case": "duplicates and unusable codes rejected",
      "duplicate_http": 409,
      "invalid_codes": [
        "",
        " ",
        "A.B",
        "TOOLONGCODE123"
      ]
    },
    {
      "id": "FX07",
      "case": "concurrent writes keep one canonical pair and consistent lookup",
      "rows": 1,
      "rate": 200.0
    },
    {
      "id": "FX08",
      "case": "REST and actual event bus hide internal prices",
      "recipients": [
        "normal",
        "vip"
      ],
      "event_fields": [
        "rate_id",
        "updated_at"
      ]
    },
    {
      "id": "FX09",
      "case": "failed optional log does not erase successfully sealed conversion",
      "records": 1,
      "history_rows": 1,
      "output_CUP": 1000
    },
    {
      "id": "FX09",
      "case": "same idempotency key returns existing receipt with sufficient remaining balance",
      "records": 1,
      "balance": 89.99
    },
    {
      "id": "FX10",
      "case": "rate change requires new confirmation before executing",
      "first_http": 409,
      "reconfirmed_output": 800
    },
    {
      "id": "FX10",
      "case": "dust rejects changed accepted total",
      "http": 409
    }
  ],
  "controls": [
    {
      "case": "normal clients cannot write rates"
    },
    {
      "case": "conversion rejects zero negative nonfinite and oversized amounts"
    },
    {
      "case": "single inverse sell price remains consistent",
      "role": "normal"
    },
    {
      "case": "single inverse sell price remains consistent",
      "role": "vip"
    },
    {
      "case": "CUP code remains canonical and distinct from CUPT",
      "normalized": "CUP"
    },
    {
      "case": "legacy and modern USD combined before dust threshold",
      "total_USD": 6,
      "dust_items": 0
    },
    {
      "case": "negative-margin price needs explicit override",
      "without_flag": 422,
      "with_flag": 200
    },
    {
      "case": "implementation uses base tier for balance conversion",
      "base_output": 5500,
      "tier_output_would_be": 5750
    },
    {
      "case": "implementation permits liquidation of inactive origin",
      "output_USDT": 3
    },
    {
      "case": "direct conversion uses role buy price and charges fee separately",
      "role": "normal",
      "output_CUP": 200.0,
      "remaining_USDT": 7.99
    },
    {
      "case": "direct conversion uses role buy price and charges fee separately",
      "role": "vip",
      "output_CUP": 220.0,
      "remaining_USDT": 7.99
    },
    {
      "case": "normal conversion merges legacy USD and modern USD atomically"
    },
    {
      "case": "normal conversion fails before atomic balance update without partial debit"
    },
    {
      "case": "conversion blocked by operational guard",
      "mode": "employee",
      "http": 403
    },
    {
      "case": "conversion blocked by operational guard",
      "mode": "blocked",
      "http": 403
    },
    {
      "case": "conversion blocked by operational guard",
      "mode": "under_review",
      "http": 403
    },
    {
      "case": "conversion blocked by operational guard",
      "mode": "defensive",
      "http": 503
    },
    {
      "case": "simultaneous normal conversions cannot spend the same balance",
      "http": [
        200,
        409
      ]
    }
  ],
  "findings": [
    {
      "id": "RF03",
      "case": "losing create overwrites concurrently created price without step-up",
      "previous": "FX01",
      "totp_enabled": true,
      "totp_code_supplied": false,
      "http": [
        200,
        200
      ],
      "first_rate": 100,
      "final_rate": 200
    },
    {
      "id": "RF01",
      "case": "applied conversion with empty marker never recovers after status failure",
      "previous": "FX09",
      "balance": {
        "USDT": 89.99,
        "CUP": 1000.0
      },
      "marker": "",
      "status": "applying",
      "history_rows": 0,
      "healer_passes": 2
    },
    {
      "id": "RF01",
      "case": "one confirmation marks both concurrent records applied although one got 409",
      "previous": "FX09",
      "http": [
        200,
        409
      ],
      "actual_CUP": 800.0,
      "history_CUP": 1600.0,
      "history_rows": 2
    },
    {
      "id": "RF01",
      "case": "40 later conversions evict a still-unresolved dust marker and mark completed sweep failed",
      "previous": "FX09",
      "sweep_credit": 3,
      "status_after_recovery": "failed",
      "intervening_conversions": 40
    },
    {
      "id": "RF02",
      "case": "successful conversion retry checked against remaining balance before idempotency lookup",
      "previous": "FX09",
      "retry_http": 400,
      "records": 1,
      "final": {
        "USDT": 0.0,
        "CUP": 1000.0
      }
    },
    {
      "id": "RF02",
      "case": "retry after lost response uses a new frontend key and performs a second conversion",
      "previous": "FX09",
      "requests": 2,
      "records": 2,
      "final": {
        "USDT": 79.97999999999999,
        "CUP": 2000.0
      }
    },
    {
      "id": "RF04",
      "case": "fixed epsilon exceeds small crypto balance and admits three concurrent sweeps",
      "previous": "FX02/FX11",
      "initial": {
        "USDT": 1,
        "BTC": 5e-07
      },
      "http": [
        200,
        200,
        200
      ],
      "actual": {
        "USDT": 1.12,
        "BTC": -1e-06
      },
      "correct_one_sweep": {
        "USDT": 1.04,
        "BTC": 0
      },
      "fee_count": 3
    }
  ],
  "source_paths": [
    "backend/audit_log.py",
    "backend/auth_utils.py",
    "backend/routes/market.py",
    "backend/routes/orders.py",
    "backend/services/balances.py",
    "backend/services/conversions.py",
    "backend/services/live_bus.py",
    "backend/services/permissions.py",
    "backend/services/rates_catalog.py",
    "backend/services/transactions.py"
  ]
}
```


**Anexo: audit_rates_frontend_f244eb0_results.json**

SHA-256: `2d7f7cb31bcba5fac1b379f0864414076ef495bef05c2cf2f565dc5df91d6213`

```json
{
  "commit": "f244eb02c64458ab900f90acdc106a348809bba6",
  "checks": [
    {
      "id": "FX04",
      "case": "button uses executable endpoint eligibility despite valuation of 5 USDT",
      "visible_count": 1,
      "dust_USDT": 4.1666
    },
    {
      "id": "CTRL",
      "case": "initial direct and inverse previews correct",
      "direct": 100,
      "inverse": 0.008333333333333333
    },
    {
      "id": "FX10",
      "case": "rate event refreshes normal conversion preview",
      "displayed_rate": 80
    },
    {
      "id": "FX10",
      "case": "explicit refresh now includes rates and dust",
      "displayed_rate": 90
    },
    {
      "id": "FX10",
      "case": "normal submit sends displayed accepted rate",
      "expected_rate": 100
    },
    {
      "id": "FX10",
      "case": "quote conflict refreshes and asks for new confirmation"
    },
    {
      "id": "FX10",
      "case": "dust submit binds displayed total",
      "expected_total_usdt": 3
    }
  ],
  "findings": [
    {
      "id": "RF05",
      "previous": "FX04/FX10",
      "case": "rates event updates rates but leaves dust eligibility stale",
      "eligible_on_server": 1,
      "visible_after_rate_event": 0,
      "visible_after_manual_refresh": 1
    },
    {
      "id": "RF02",
      "previous": "FX09",
      "case": "retry from same open conversion generates a new key after lost response",
      "first_key": "synthetic-op-1",
      "retry_key": "synthetic-op-2",
      "requests_have_identical_amounts_and_rates": true
    }
  ],
  "browser_end_to_end": false
}
```


**Anexo: audit_rates_frontend_f244eb0.cjs**

SHA-256: `067f3d82c7e9a5e6c58bed3df70e91aa0e6498a49d3d911c6641b28731ac6e9d`

```javascript
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=process.argv[2]||'audit-f244eb0';const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const out={commit:'f244eb02c64458ab900f90acdc106a348809bba6',checks:[],findings:[],browser_end_to_end:false};
const tick=()=>new Promise(r=>setImmediate(r));
function hooks(){
 const source=read('frontend/src/components/converter/useConverterData.js');
 let slots=[],index=0,effects=[],requests=[],live={};
 const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
 const useState=initial=>{const at=index++;if(!(at in slots))slots[at]=initial;return[slots[at],v=>{slots[at]=typeof v==='function'?v(slots[at]):v;}];};
 const useMemo=(fn,deps)=>{const at=index++,prior=slots[at];if(!prior||!same(prior.deps,deps))slots[at]={deps,value:fn()};return slots[at].value;};
 const useCallback=(fn,deps)=>useMemo(()=>fn,deps);
 const useEffect=(fn,deps)=>{const at=index++,prior=slots[at];if(!prior||!same(prior.deps,deps)){slots[at]={deps};effects.push(fn);}};
 const remote={rates:[{from_code:'USDT',to_code:'CUP',rate_normal:100,rate_vip:100,rate_convert:100,rate_sell:120,rate_convert_sell:120}],balances:{balances:[{currency:'USDT',amount:100,usdt_equivalent:100},{currency:'CUP',amount:500,usdt_equivalent:5}],total_usdt:105},dust:{items:[{currency:'CUP',amount:500,usdt_equivalent:4.1666,rate:1/120}],total_usdt:4.1666,can_convert:true}};
 const axios={get:async url=>{requests.push(url);const d=url.endsWith('/rates')?remote.rates:url.endsWith('/currencies')?[{code:'USDT',is_active:true},{code:'CUP',is_active:true}]:url.endsWith('/dust')?remote.dust:remote.balances;return{data:JSON.parse(JSON.stringify(d))};}};
 const src=source.replace(/^import .*;\n/gm,'').replace('export function useConverterData','function useConverterData');
 const hook=new Function('useEffect','useMemo','useState','useCallback','axios','API','useLiveEvent',src+'\nreturn useConverterData;')(useEffect,useMemo,useState,useCallback,axios,'/api',(name,fn)=>{if(name)live[name]=fn;});
 const render=()=>{index=0;const result=hook({isVip:true});effects.splice(0).forEach(fn=>fn());return result;};
 return {remote,requests,live,render};
}
async function verifyHook(){
 const h=hooks();h.render();await tick();let state=h.render();
 assert.equal(state.computeRate('USDT','CUP'),100);assert.equal(state.computeRate('CUP','USDT'),1/120);assert.equal(state.dust.items.length,1);
 const card=read('frontend/src/components/BalanceConverterCard.jsx');const countExpr=card.match(/const dustCount = ([^;]+);/)[1];const count=new Function('dust','return '+countExpr);
 assert.equal(count(state.dust),1);
 out.checks.push({id:'FX04',case:'button uses executable endpoint eligibility despite valuation of 5 USDT',visible_count:1,dust_USDT:4.1666});
 out.checks.push({id:'CTRL',case:'initial direct and inverse previews correct',direct:100,inverse:1/120});
 h.remote.rates[0].rate_convert=80;h.remote.rates[0].rate_normal=80;h.remote.rates[0].rate_vip=80;
 h.live.rates_updated();await tick();state=h.render();assert.equal(state.computeRate('USDT','CUP'),80);
 out.checks.push({id:'FX10',case:'rate event refreshes normal conversion preview',displayed_rate:80});
 h.remote.rates[0].rate_convert=90;h.remote.rates[0].rate_normal=90;h.remote.rates[0].rate_vip=90;await state.refresh();await tick();state=h.render();assert.equal(state.computeRate('USDT','CUP'),90);
 out.checks.push({id:'FX10',case:'explicit refresh now includes rates and dust',displayed_rate:90});
 // The threshold changes with the sale quote; only the rates are refreshed by SSE.
 h.remote.rates[0].rate_sell=100;h.remote.rates[0].rate_convert_sell=100;h.remote.dust={items:[],total_usdt:0,can_convert:false};await state.refresh();await tick();state=h.render();assert.equal(count(state.dust),0);
 h.remote.rates[0].rate_sell=125;h.remote.rates[0].rate_convert_sell=125;h.remote.dust={items:[{currency:'CUP',amount:500,usdt_equivalent:4,rate:1/125}],total_usdt:4,can_convert:true};
 const before=h.requests.filter(x=>x.endsWith('/dust')).length;h.live.rates_updated();await tick();state=h.render();
 assert.equal(state.computeRate('CUP','USDT'),1/125);assert.equal(count(state.dust),0);assert.equal(h.requests.filter(x=>x.endsWith('/dust')).length,before);
 await state.refresh();await tick();state=h.render();assert.equal(count(state.dust),1);
 out.findings.push({id:'RF05',previous:'FX04/FX10',case:'rates event updates rates but leaves dust eligibility stale',eligible_on_server:1,visible_after_rate_event:0,visible_after_manual_refresh:1});
}
async function verifySubmit(){
 const src=read('frontend/src/components/BalanceConverterCard.jsx');const body=src.match(/const submit = async \(\) => \{([\s\S]*?)\n  \};/)[1];
 const requests=[],errors=[],warnings=[];let n=0,closed=0;
 const axios={post:async(url,payload)=>{requests.push(payload);n++;if(n===1)throw new Error('Synthetic response lost AFTER the server applied the operation');return {data:{amount_to:1000,usdt_fee:.01}};}};
 const globals={amount:'10',toCode:'CUP',fromCode:'USDT',positive:[{currency:'USDT',amount:100}],belowMinSource:false,previewSourceUsdt:10,CONVERT_MIN_SOURCE_USDT:1,CONVERT_FEE_USDT:.01,usdtBalance:100,setBusy:()=>{},crypto:{randomUUID:()=>`synthetic-op-${requests.length+1}`},axios,API:'/api',previewRate:100,toast:{error:x=>errors.push(x),success:()=>{},warning:x=>warnings.push(x)},setOpen:()=>{closed++;},refresh:async()=>{},onConverted:null,extractDetailMessage:(e,fallback)=>fallback};
 const invoke=()=>new Function(...Object.keys(globals),'return (async()=>{'+body+'})();')(...Object.values(globals));
 await invoke();await invoke();assert.equal(errors.length,1);assert.equal(requests.length,2);assert.notEqual(requests[0].op_id,requests[1].op_id);
 assert(requests.every(p=>p.expected_rate===100));fs.writeFileSync('audit_rates_f244eb0_frontend_payloads.json',JSON.stringify(requests,null,2));
 out.findings.push({id:'RF02',previous:'FX09',case:'retry from same open conversion generates a new key after lost response',first_key:requests[0].op_id,retry_key:requests[1].op_id,requests_have_identical_amounts_and_rates:true});
 out.checks.push({id:'FX10',case:'normal submit sends displayed accepted rate',expected_rate:100});
 // Real error handler leaves dialog open and refreshes when quotation changed.
 globals.axios={post:async()=>{throw {response:{data:{detail:{code:'QUOTE_CHANGED',amount_to:800}}}};}};let refreshed=0;closed=0;globals.refresh=async()=>{refreshed++;};await invoke();assert.equal(refreshed,1);assert.equal(closed,0);assert.equal(warnings.length,1);
 out.checks.push({id:'FX10',case:'quote conflict refreshes and asks for new confirmation'});
 const dustSrc=read('frontend/src/components/converter/DustSweepDialog.jsx');const dustBody=dustSrc.match(/const submit = async \(\) => \{([\s\S]*?)\n  \};/)[1];let sent;
 const dustGlobals={setBusy:()=>{},axios:{post:async(url,p)=>{sent=p;return {data:{items:[{}],credited_usdt:3}};}},API:'/api',preview:{total_usdt:3},toast:{success:()=>{},error:()=>{},warning:()=>{}},t:x=>x,onOpenChange:()=>{},onConverted:null,setLoading:()=>{},setPreview:()=>{},extractDetailMessage:()=>''};
 await new Function(...Object.keys(dustGlobals),'return (async()=>{'+dustBody+'})();')(...Object.values(dustGlobals));assert.equal(sent.expected_total_usdt,3);
 out.checks.push({id:'FX10',case:'dust submit binds displayed total',expected_total_usdt:3});
}
(async()=>{await verifyHook();await verifySubmit();console.log(JSON.stringify(out,null,2));})().catch(e=>{console.error(e);process.exitCode=1;});
```


**Anexo: audit_rates_f244eb0.py**

SHA-256: `afe5b6f3a230f0c656d17fcf87441e72bb30ed0960f9cffee49d1edbdd5ea596`

```python
"""Read-only audit harness: real AST-extracted functions, synthetic in-memory data.
No repository writes, live imports, HTTP calls or production connections.
"""
import ast,asyncio,copy,json,logging,math,re,sys,types,uuid
from pathlib import Path
from datetime import datetime,timezone,timedelta
from typing import Any,Optional,Literal,Dict,List
from pydantic import BaseModel,ConfigDict,Field,ValidationError,field_validator,model_validator
from decimal import Context,Decimal,ROUND_FLOOR,ROUND_HALF_EVEN
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path('audit-f244eb0/backend').resolve()
SOURCE_PATHS=set()
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
 if op=='$slice':return v[0][v[1]:] if v[1]<0 else v[0][:v[1]]
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
   self.unique.append((ks,kw.get('sparse',False),kw.get('partialFilterExpression')));self.check_unique()
 def check_unique(self):
  for ks,sparse,partial in self.unique:
   seen=set()
   for row in self.rows:
    if partial and not match(row,partial):continue
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
     key=expr(group['_id'],d);b=buckets.setdefault(key,{'_id':key})
     for k,v in group.items():
      if k=='_id':continue
      assert set(v)=={'$sum'},v;b[k]=b.get(k,0)+(expr(v['$sum'],d) or 0)
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
 SOURCE_PATHS.add('backend/'+path)
 e=dict(db=db,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,HTTPException=HTTPException,
        Any=Any,Optional=Optional,Literal=Literal,Dict=Dict,List=List,Request=object,field_validator=field_validator,model_validator=model_validator,re=re,math=math,Context=Context,Decimal=Decimal,ROUND_FLOOR=ROUND_FLOOR,ROUND_HALF_EVEN=ROUND_HALF_EVEN,
        uuid=uuid,datetime=datetime,timezone=timezone,timedelta=timedelta,logging=logging,
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
   if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_SNAP_CTX' for t in n.targets):
    nodes.append(n);continue
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

async def test_positive_controls():
 for role in ['normal','vip']:
  f=fixture({'USDT':10},role=role,rates=[rate('USDT','CUP',100,110,120)])
  r=await convert(f,'USDT','CUP',2);assert r['amount_to']==(220 if role=='vip' else 200) and balances(f)['USDT']==7.99
  good('direct conversion uses role buy price and charges fee separately',role=role,output_CUP=r['amount_to'],remaining_USDT=7.99)
 f=fixture({'USDT':.01,'USD':2});f.db.users.rows[0]['vip_balance_usd']=3
 r=await convert(f,'USD','USDT',5)
 assert r['amount_to']==5 and balances(f)['USD']==0 and balances(f)['USDT']==5 and f.db.users.rows[0]['vip_balance_usd']==0
 good('normal conversion merges legacy USD and modern USD atomically')
 f=fixture({'USDT':10});f.db.users.fail=lambda q,u:True;initial=balances(f)
 try:await convert(f,'USDT','CUP',2);assert False
 except RuntimeError:pass
 assert balances(f)==initial
 good('normal conversion fails before atomic balance update without partial debit')
 for mode in ['employee','blocked','under_review','defensive']:
  f=fixture({'USDT':10})
  if mode=='employee':f.db.users.rows[0]['role']='employee'
  elif mode=='defensive':f.db.system_config.rows=[{'key':'defensive_mode','enabled':True}]
  else:f.db.users.rows[0]['account_status']=mode
  code,_=await http(convert(f,'USDT','CUP',2))
  assert code in [403,423,503],(mode,code)
  good('conversion blocked by operational guard',mode=mode,http=code)
 f=fixture({'USDT':10});hit=asyncio.Event();go=asyncio.Event();n=0
 async def barrier(q,u):
  nonlocal n
  if u.get('$inc',{}).get('vip_balances.USDT',0)<0:
   n+=1
   if n==2:hit.set()
   await go.wait()
 f.db.users.before_update=barrier
 ts=[asyncio.create_task(http(convert(f,'USDT','CUP',8))) for _ in range(2)]
 await hit.wait();go.set();codes=sorted(x[0] for x in await asyncio.gather(*ts))
 assert codes==[200,409] and abs(balances(f)['USDT']-1.99)<1e-8 and balances(f)['CUP']==800
 good('simultaneous normal conversions cannot spend the same balance',http=codes)
RESULTS={'commit':'f244eb02c64458ab900f90acdc106a348809bba6','checks':[],'controls':[],'findings':[]}
def check(id,case,**kw):RESULTS['checks'].append(dict(id=id,case=case,**kw))
def finding(id,case,**kw):RESULTS['findings'].append(dict(id=id,case=case,**kw))
def good(case,**kw):RESULTS['controls'].append(dict(case=case,**kw))
async def http(coro):
 try:return 200,await coro
 except HTTPException as e:return e.status_code,e.detail
def request(method='POST'):return types.SimpleNamespace(method=method,url=types.SimpleNamespace(path='/api/admin/rates'))
def rate(fc,tc,n=1,v=None,s=None,**kw):return {'id':f'{fc}-{tc}','from_code':fc,'to_code':tc,'rate_normal':n,'rate_vip':n if v is None else v,'rate_sell':s,**kw}
def currency(c,**kw):return {'id':'cur-'+c,'code':c,'name':c,'type':'crypto' if c in ['USDT','BTC'] else 'fiat','is_active':True,'is_convertible_to':True,**kw}
def fixture(balances=None,role='vip',rates=None):
 db=DB();u={'user_id':'client','email':'synthetic@example.test','name':'Synthetic Client','role':role,'account_status':'active','is_verified':True,'vip_balances':balances or {'USDT':100},'totp_enabled':True}
 db.users.rows=[copy.deepcopy(u)];db.rates.rows=copy.deepcopy(rates if rates is not None else [rate('USDT','USD'),rate('USDT','CUP',100)])
 db.currencies.rows=[currency(c) for c in sorted({'USDT','USD','CUP','EUR'}|set(u['vip_balances']))]
 async def current(*a,**kw):return copy.deepcopy(db.users.rows[0])
 module('services');module('routes');module('pymongo');module('pymongo.errors',DuplicateKeyError=DuplicateKeyError)
 module('services.live_bus',publish=noop);module('services.live_events',emit_balance_changed=noop)
 module('admin_alerts',notify_all_admins=noop)
 load_module('audit_log','audit_log.py',db,u,names=['_iso_now','log_action'])
 bal=load_module('services.balances','services/balances.py',db,u)
 conv=load_module('services.conversions','services/conversions.py',db,u,extra={'effective_sell_rate':bal.effective_sell_rate})
 catalog=load_module('services.rates_catalog','services/rates_catalog.py',db,u)
 perms=load_module('services.permissions','services/permissions.py',db,u)
 auth=load_module('auth_utils','auth_utils.py',db,u,names=['require_staff','require_permission','_enforce_staff_2fa_enabled','_enforce_employee_currency_scope','_enforce_totp_step_up'],extra={'require_user':current,'_PERM_VALID_CODES':{p['code'] for p in perms.PERMISSION_CATALOG},'_has_perm':perms._has_permission,'_perm_label':perms.permission_label,'_UNSAFE_METHODS':frozenset({'POST','PUT','PATCH','DELETE'})})
 market=load_module('routes.market','routes/market.py',db,u,extra={**{n:getattr(auth,n) for n in ['require_staff','require_permission','_enforce_employee_currency_scope','_enforce_totp_step_up']},'get_session_user':current,'snap_value':conv.snap_value})
 market._fanout_rate_change_push=noop;market._scan_rate_change_margin=noop
 tx=load_module('services.transactions','services/transactions.py',db,u,names=['_conversion_to_transaction','_durable_conversion_to_transaction','_fetch_conversions'])
 order=load_module('routes.orders','routes/orders.py',db,u,names=['VipConvertPayload','DustConvertPayload','vip_convert','_collect_dust','vip_dust_preview','vip_convert_dust'],extra={**{n:getattr(bal,n) for n in ['build_rate_lookup','build_convert_rate_lookup','convert_to_usdt','effective_sell_rate','get_user_balance','decrement_balance','assert_account_active','assert_not_defensive']},'require_user':current,'SMALL_BALANCE_THRESHOLD_USDT':5.0})
 return types.SimpleNamespace(db=db,user=u,bal=bal,conv=conv,catalog=catalog,order=order,market=market,auth=auth,perms=perms,tx=tx,current=current)
async def convert(f,fc,tc,amt,**kw):return await f.order.vip_convert(f.order.VipConvertPayload(from_code=fc,to_code=tc,amount_from=amt,**kw),None)
def balances(f):return copy.deepcopy(f.db.users.rows[0]['vip_balances'])

async def verify_permissions_validation():
 for mode in ['employee','admin']:
  f=fixture(role=mode);f.db.users.rows[0]['allowed_permissions']=['orders']
  p=f.market.ExchangeRateCreate(from_code='USDT',to_code='CUP',rate_normal=700,rate_vip=705)
  codes=[(await http(f.market.update_rate('USDT-CUP',p,request('PUT'))))[0],(await http(f.market.create_rate(p,request())))[0]]
  assert codes==([403,403] if mode=='employee' else [401,401]) and f.db.rates.rows[1]['rate_normal']==100
  check('FX01','both write routes reject unauthorized edits',actor=mode,codes=codes)
 f=fixture(role='normal');p=f.market.ExchangeRateCreate(from_code='USD',to_code='CUP',rate_normal=700,rate_vip=705)
 assert (await http(f.market.create_rate(p,request())))[0]==403;good('normal clients cannot write rates')
 f=fixture()
 for field in ['rate_normal','rate_vip','rate_sell','real_rate']:
  for val in [0,-1,'NaN','Infinity','-Infinity',1e13]:
   payload=dict(from_code='USDT',to_code='CUP',rate_normal=100,rate_vip=100);payload[field]=val
   try:f.market.ExchangeRateCreate(**payload);raise AssertionError('invalid price accepted')
   except ValidationError:pass
  check('FX03','invalid price values rejected by model',field=field,invalid_values=6)
 for field in ['rate_normal','rate_vip','real_rate','min_amount']:
  try:f.market.RateTier(**{**dict(min_amount=1,rate_normal=1,rate_vip=1),field:'NaN'});raise AssertionError('invalid tier')
  except ValidationError:pass
 check('FX03','nonfinite tier fields rejected')
 for val in [float('nan'),float('inf'),-1,0]:
  f=fixture({'USDT':100},rates=[rate('USDT','CUP',val)])
  code,_=await http(convert(f,'USDT','CUP',10));assert code==400 and balances(f)=={'USDT':100}
  check('FX03','invalid legacy rate causes no debit',invalid=str(val),http=400)
 for amt in [-1,0,float('nan'),float('inf'),1e10]:
  try:f.order.VipConvertPayload(from_code='USDT',to_code='CUP',amount_from=amt);raise AssertionError('invalid amount')
  except ValidationError:pass
 good('conversion rejects zero negative nonfinite and oversized amounts')

async def verify_precision_dust_quotes():
 f=fixture({'USDT':10},rates=[rate('USDT','BTC',.00001)]);f.db.currencies.rows.append(currency('BTC'))
 r=await convert(f,'USDT','BTC',1);assert r['amount_to']==.00001 and balances(f)['USDT']==8.99
 check('FX11','previous zero-result BTC example preserves small units',input_USDT=1,output_BTC=r['amount_to'])
 f=fixture({'USDT':100},rates=[rate('USDT','BTC',.00001)]);f.db.currencies.rows.append(currency('BTC'))
 buy=await convert(f,'USDT','BTC',5.01);sell=await convert(f,'BTC','USDT',buy['amount_to'])
 assert buy['amount_to']==.0000501 and sell['amount_to']==5.01 and abs(balances(f)['USDT']-99.98)<1e-10
 check('FX11','previous BTC round trip cannot inflate balance',bought_BTC=buy['amount_to'],returned_USDT=5.01,final_USDT=balances(f)['USDT'])
 f=fixture({'USDT':100},rates=[rate('USDT','BTC',1e-10)]);f.db.currencies.rows.append(currency('BTC'))
 code,_=await http(convert(f,'USDT','BTC',1));assert code==400 and balances(f)=={'USDT':100}
 check('FX11','result below currency precision rejected before debit',http=400)
 for name,rs,expected in [('VIP direct',[rate('USD','USDT',1,1.1)],3.3),('both directions',[rate('USDT','USD',1,1,1.2),rate('USD','USDT',.8,.8)],2.4)]:
  f=fixture({'USDT':1,'USD':3},rates=rs);p=await f.order.vip_dust_preview(None);r=await convert(f,'USD','USDT',3)
  assert p['total_usdt']==r['amount_to']==expected
  check('FX04','manual and dust use identical executable quote',scenario=name,output=expected)
 for role in ['normal','vip']:
  f=fixture({'USDT':1,'USD':3},role=role,rates=[rate('USDT','USD',1,1,1.2)]);p=await f.order.vip_dust_preview(None);r=await convert(f,'USD','USDT',3)
  assert p['total_usdt']==r['amount_to']==2.5;good('single inverse sell price remains consistent',role=role)
 f=fixture({'USDT':1,'EUR':2},rates=[rate('USD','EUR',.8,.85,1)])
 p=await f.order.vip_dust_preview(None);code,_=await http(f.order.vip_convert_dust(None))
 assert p['items']==[] and code==400 and balances(f)=={'USDT':1,'EUR':2}
 check('FX04','dust refuses unconfigured USD-USDT parity',http=400)
 f=fixture({'USDT':1,'CUP':500},rates=[rate('USDT','CUP',100,100,120)]);p=await f.order.vip_dust_preview(None)
 assert p['items'][0]['currency']=='CUP' and p['total_usdt']==4.1666
 check('FX04','server dust selector exposes item eligible at sell price',balance_CUP=500,total_USDT=4.1666)
 f=fixture({'USDT':1,'CUP':500},rates=[rate('USDT','CUP',90,90,100)]);a=await f.order.vip_dust_preview(None)
 f.db.rates.rows[0]['rate_sell']=125;b=await f.order.vip_dust_preview(None)
 assert len(a['items'])==0 and len(b['items'])==1 and b['total_usdt']==4
 check('FX04','backend eligibility changes when sell price crosses dust threshold',balance_CUP=500,before_count=0,after_count=1,after_total_USDT=4)
 f=fixture({'USDT':1,'CUP':300});initial=balances(f);f.db.users.fail=lambda q,u:True
 try:await f.order.vip_convert_dust(None);raise AssertionError('injected write did not fail')
 except RuntimeError:pass
 assert balances(f)==initial;f.db.users.fail=None
 r=await f.order.vip_convert_dust(None);assert r['credited_usdt']==3 and abs(balances(f)['USDT']-3.99)<1e-9
 check('FX02','failed dust atomic write moves nothing and retry charges once',final=balances(f))
 f=fixture({'USDT':1,'CUP':300});hit=asyncio.Event();go=asyncio.Event();n=0
 async def pause(q,u):
  nonlocal n
  n+=1
  if n==2:hit.set()
  await go.wait()
 f.db.users.before_update=pause
 tasks=[asyncio.create_task(http(f.order.vip_convert_dust(None))) for _ in range(2)]
 await hit.wait();go.set();rs=await asyncio.gather(*tasks)
 assert sorted(x[0] for x in rs)==[200,409] and abs(balances(f)['USDT']-3.99)<1e-9
 check('FX02','original concurrent CUP sweeps produce one fee',http=[200,409],final=balances(f))

async def verify_catalog_events():
 for mode in ['inactive','deleted','nonconvertible']:
  f=fixture({'USDT':10});d=next(x for x in f.db.currencies.rows if x['code']=='CUP')
  if mode=='deleted':f.db.currencies.rows.remove(d)
  else:d['is_active' if mode=='inactive' else 'is_convertible_to']=False
  code,_=await http(convert(f,'USDT','CUP',2));assert code==400 and balances(f)=={'USDT':10}
  check('FX05','unavailable destination rejected',mode=mode,http=400)
 for mode in ['nonconvertible','inactive','deleted']:
  f=fixture({'USDT':1,'CUP':300});d=next(x for x in f.db.currencies.rows if x['code']=='USDT')
  if mode=='deleted':f.db.currencies.rows.remove(d)
  else:d['is_convertible_to' if mode=='nonconvertible' else 'is_active']=False
  a,_=await http(convert(f,'CUP','USDT',300));b,_=await http(f.order.vip_convert_dust(None));p=await f.order.vip_dust_preview(None)
  assert a==b==400 and not p['can_convert'] and balances(f)=={'USDT':1,'CUP':300}
  check('FX05','both converters enforce USDT destination guard',mode=mode,codes=[a,b])
 f=fixture({'USDT':1,'CUP':300},role='admin');await f.catalog.ensure_market_integrity()
 p=f.market.CurrencyCreate(code='CUPT',name='Transfer',type='fiat')
 a,_=await http(f.market.update_currency('cur-CUP',p,request('PUT')));b,_=await http(f.market.delete_currency('cur-CUP',request('DELETE')))
 assert a==b==409 and any(x['code']=='CUP' for x in f.db.currencies.rows)
 check('FX06','referenced CUP cannot be renamed or deleted',http=[a,b],balance_CUP=300)
 p=f.market.CurrencyCreate(code=' cup ',name='Cash',type='fiat')
 code,_=await http(f.market.create_currency(p,request()));assert code==409
 invalid=['',' ','A.B','TOOLONGCODE123']
 for raw in invalid:
  try:f.market.CurrencyCreate(code=raw,name='Invalid',type='fiat');raise AssertionError('invalid code accepted')
  except ValidationError:pass
 check('FX06','duplicates and unusable codes rejected',duplicate_http=409,invalid_codes=invalid)
 good('CUP code remains canonical and distinct from CUPT',normalized=p.code)
 f=fixture(role='admin',rates=[]);await f.catalog.ensure_market_integrity()
 hit=asyncio.Event();go=asyncio.Event();n=0
 async def pause(d):
  nonlocal n
  n+=1
  if n==2:hit.set()
  await go.wait()
 f.db.rates.before_insert=pause
 ps=[f.market.ExchangeRateCreate(from_code=' usdt ',to_code=' cup ',rate_normal=x,rate_vip=x) for x in [100,200]]
 tasks=[asyncio.create_task(http(f.market.create_rate(p,request()))) for p in ps]
 await hit.wait();go.set();rs=await asyncio.gather(*tasks)
 assert len(f.db.rates.rows)==1 and f.db.rates.rows[0]['from_code']=='USDT' and f.db.rates.rows[0]['to_code']=='CUP'
 table=await f.bal.build_rate_lookup();assert table[('USDT','CUP')]==f.db.rates.rows[0]['rate_normal']
 check('FX07','concurrent writes keep one canonical pair and consistent lookup',rows=1,rate=table[('USDT','CUP')])
 assert [x[0] for x in rs]==[200,200]
 finding('RF03','losing create overwrites concurrently created price without step-up',previous='FX01',totp_enabled=True,totp_code_supplied=False,http=[200,200],first_rate=100,final_rate=200)
 f=fixture(role='admin',rates=[]);m=module('services.live_bus');SOURCE_PATHS.add('backend/services/live_bus.py')
 exec(compile((ROOT/'services/live_bus.py').read_text(),str(ROOT/'services/live_bus.py'),'exec'),m.__dict__)
 subs=[await m.subscribe(uid,role) for uid,role in [('normal-user','normal'),('vip-user','vip')]]
 p=f.market.ExchangeRateCreate(from_code='USDT',to_code='CUP',rate_normal=700,rate_vip=705,real_rate=750,tiers=[dict(min_amount=200,rate_normal=705,rate_vip=710,real_rate=760)])
 await f.market.create_rate(p,request());packets=[await sub.queue.get() for sub in subs]
 assert all(set(x['data'])=={'rate_id','updated_at'} for x in packets)
 f.db.users.rows[0]['role']='normal';rows=await f.market.list_rates(None)
 assert 'real_rate' not in rows[0] and 'real_rate' not in rows[0]['tiers'][0]
 for sub in subs:await m.unsubscribe(sub)
 check('FX08','REST and actual event bus hide internal prices',recipients=['normal','vip'],event_fields=['rate_id','updated_at'])

async def verify_receipts_and_quotes():
 f=fixture({'USDT':100});f.db.audit_log.fail=lambda q,u:True
 r=await convert(f,'USDT','CUP',10);tx=await f.tx._fetch_conversions({},None,'client')
 assert r['ok'] and len(tx)==1 and tx[0]['amount_to']==1000 and f.db.conversions.rows[0]['status']=='applied'
 check('FX09','failed optional log does not erase successfully sealed conversion',records=1,history_rows=1,output_CUP=1000)
 f=fixture({'USDT':100});await f.conv.ensure_conversion_indexes();a=await convert(f,'USDT','CUP',10,op_id='same-op-0001');b=await convert(f,'USDT','CUP',10,op_id='same-op-0001')
 assert b['duplicate'] and a['conversion_id']==b['conversion_id'] and balances(f)['USDT']==89.99
 check('FX09','same idempotency key returns existing receipt with sufficient remaining balance',records=len(f.db.conversions.rows),balance=89.99)
 f=fixture({'USDT':100});f.db.rates.rows[1].update(rate_normal=80,rate_vip=80)
 code,detail=await http(convert(f,'USDT','CUP',10,expected_rate=100));assert code==409 and detail['code']=='QUOTE_CHANGED' and balances(f)=={'USDT':100}
 r=await convert(f,'USDT','CUP',10,expected_rate=80);assert r['amount_to']==800
 check('FX10','rate change requires new confirmation before executing',first_http=409,reconfirmed_output=800)
 f=fixture({'USDT':1,'CUP':300});code,detail=await http(f.order.vip_convert_dust(None,f.order.DustConvertPayload(expected_total_usdt=2)))
 assert code==409 and detail['code']=='QUOTE_CHANGED' and balances(f)=={'USDT':1,'CUP':300}
 check('FX10','dust rejects changed accepted total',http=409)
 # Additional decisions implemented in this commit; no assumption of user ratification.
 f=fixture({'USDT':1,'USD':3});f.db.users.rows[0]['vip_balance_usd']=3;p=await f.order.vip_dust_preview(None)
 assert p['items']==[];good('legacy and modern USD combined before dust threshold',total_USD=6,dust_items=0)
 f=fixture(role='admin',rates=[]);p=f.market.ExchangeRateCreate(from_code='USD',to_code='CUP',rate_normal=680,rate_vip=690,rate_sell=600)
 code,detail=await http(f.market.create_rate(p,request()));assert code==422 and detail['code']=='NEGATIVE_MARGIN'
 p.allow_negative_margin=True;r=await f.market.create_rate(p,request());assert r['rate_sell']==600
 good('negative-margin price needs explicit override',without_flag=422,with_flag=200)
 f=fixture({'USDT':100},rates=[rate('USDT','CUP',100,110,120,tiers=[dict(min_amount=50,rate_normal=105,rate_vip=115)])]);r=await convert(f,'USDT','CUP',50)
 assert r['amount_to']==5500;good('implementation uses base tier for balance conversion',base_output=5500,tier_output_would_be=5750)
 f=fixture({'USDT':1,'CUP':300});next(x for x in f.db.currencies.rows if x['code']=='CUP')['is_active']=False
 r=await convert(f,'CUP','USDT',300);assert r['amount_to']==3;good('implementation permits liquidation of inactive origin',output_USDT=3)

async def remaining_receipt_risks():
 # A balance write succeeds, but the status write fails. Empty marker is skipped.
 f=fixture({'USDT':100});f.db.conversions.fail=lambda q,u:u.get('$set',{}).get('status')=='applied'
 try:await convert(f,'USDT','CUP',10);raise AssertionError('missing injected failure')
 except RuntimeError:pass
 f.db.conversions.fail=None;await f.conv.heal_pending_conversions(-1);await f.conv.heal_pending_conversions(-1)
 tx=await f.tx._fetch_conversions({},None,'client');r=f.db.conversions.rows[0]
 assert balances(f)=={'USDT':89.99,'CUP':1000} and r['status']=='applying' and r['marker_id']=='' and tx==[]
 finding('RF01','applied conversion with empty marker never recovers after status failure',previous='FX09',balance=balances(f),marker='',status='applying',history_rows=0,healer_passes=2)
 # Two records use the same empty marker: a successful conversion seals a rejected one.
 f=fixture({'USDT':10});hit=asyncio.Event();go=asyncio.Event();n=0
 async def pause(q,u):
  nonlocal n
  n+=1
  if n==2:hit.set()
  await go.wait()
 f.db.users.before_update=pause
 tasks=[asyncio.create_task(http(convert(f,'USDT','CUP',8))) for _ in range(2)]
 await hit.wait();go.set();rs=await asyncio.gather(*tasks);tx=await f.tx._fetch_conversions({},None,'client')
 assert sorted(x[0] for x in rs)==[200,409] and len(tx)==2 and all(x['status']=='applied' for x in f.db.conversions.rows)
 finding('RF01','one confirmation marks both concurrent records applied although one got 409',previous='FX09',http=[200,409],actual_CUP=balances(f)['CUP'],history_CUP=sum(x['amount_to'] for x in tx),history_rows=2)
 # Even a non-empty dust marker can be evicted before its pending status recovers.
 f=fixture({'USDT':100,'CUP':300});f.db.conversions.fail=lambda q,u:u.get('$set',{}).get('status')=='applied'
 try:await f.order.vip_convert_dust(None);raise AssertionError('missing failure')
 except RuntimeError:pass
 f.db.conversions.fail=None;dust=f.db.conversions.rows[0];marker=dust['marker_id'];assert marker and marker in f.db.users.rows[0]['recent_conversion_ids']
 f.db.audit_log.fail=lambda q,u:True
 for i in range(40):await convert(f,'USDT','CUP',1)
 assert marker not in f.db.users.rows[0]['recent_conversion_ids']
 await f.conv.heal_pending_conversions(-1);await f.conv.heal_pending_conversions(-1)
 assert dust['status']=='failed'
 finding('RF01','40 later conversions evict a still-unresolved dust marker and mark completed sweep failed',previous='FX09',sweep_credit=3,status_after_recovery='failed',intervening_conversions=40)
 f=fixture({'USDT':10.01});await f.conv.ensure_conversion_indexes();await convert(f,'USDT','CUP',10,op_id='balance-full-op')
 code,detail=await http(convert(f,'USDT','CUP',10,op_id='balance-full-op'))
 assert code==400 and len(f.db.conversions.rows)==1
 finding('RF02','successful conversion retry checked against remaining balance before idempotency lookup',previous='FX09',retry_http=400,records=1,final=balances(f))
 # Replays of the actual frontend requests are supplied by the JS harness.
 payload_file=Path('audit_rates_f244eb0_frontend_payloads.json')
 if payload_file.exists():
  payloads=json.loads(payload_file.read_text());f=fixture({'USDT':100});await f.conv.ensure_conversion_indexes()
  for p in payloads:await f.order.vip_convert(f.order.VipConvertPayload(**p),None)
  assert len(f.db.conversions.rows)==2 and abs(balances(f)['USDT']-79.98)<1e-10 and balances(f)['CUP']==2000
  finding('RF02','retry after lost response uses a new frontend key and performs a second conversion',previous='FX09',requests=2,records=2,final=balances(f))
 else:raise AssertionError('Run the accompanying frontend harness first to capture its actual request payloads')

async def remaining_dust_risk():
 f=fixture({'USDT':1,'BTC':.0000005},rates=[rate('USDT','BTC',.00001)])
 hit=asyncio.Event();go=asyncio.Event();n=0
 async def pause(q,u):
  nonlocal n
  n+=1
  if n==3:hit.set()
  await go.wait()
 f.db.users.before_update=pause
 tasks=[asyncio.create_task(http(f.order.vip_convert_dust(None))) for _ in range(3)]
 await hit.wait();go.set();rs=await asyncio.gather(*tasks)
 assert [x[0] for x in rs]==[200,200,200] and balances(f)['BTC']==-.000001 and abs(balances(f)['USDT']-1.12)<1e-10
 finding('RF04','fixed epsilon exceeds small crypto balance and admits three concurrent sweeps',previous='FX02/FX11',initial={'USDT':1,'BTC':.0000005},http=[200,200,200],actual=balances(f),correct_one_sweep={'USDT':1.04,'BTC':0},fee_count=3)

async def main():
 for fn in [verify_permissions_validation,verify_precision_dust_quotes,verify_catalog_events,verify_receipts_and_quotes,test_positive_controls,remaining_receipt_risks,remaining_dust_risk]:
  print('RUN',fn.__name__,file=sys.stderr,flush=True);await asyncio.wait_for(fn(),30)
 RESULTS['source_paths']=sorted(SOURCE_PATHS)
 print(json.dumps(RESULTS,indent=2,allow_nan=False))
if __name__=='__main__':asyncio.run(main())
```
