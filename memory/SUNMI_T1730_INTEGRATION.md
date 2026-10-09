# Integración caja SUNMI D3 Mini (T1730) — Impresión de ticket + Gaveta

**Objetivo:** imprimir el ticket de venta en la impresora térmica integrada de la
SUNMI D3 Mini (T1730) y abrir la gaveta de efectivo, desde la plataforma web/PWA
de mercado e inventario.

**Estado (iter356):** desarrollado y **verificado por SIMULACIÓN** antes de comprar
el equipo. La verificación FÍSICA (impresora + gaveta imprimiendo/abriendo en la
T1730 real) queda pendiente y es el criterio de cierre.

---

## Arquitectura

- **Backend genera el ESC/POS** (lenguaje estándar de impresoras térmicas), de forma
  determinista y testeable: `services/receipt_printing.py` + rutas en `routes/pos.py`.
  - `POST /api/admin/pos/receipt/build` → `{ plaintext, escpos_b64, escpos_len, width, open_drawer }`
  - `GET  /api/admin/pos/receipt/sample?width=48|32` → payload de ejemplo + build
  - `GET  /api/admin/pos/drawer/open` → ESC/POS del pulso de gaveta (base64)
- **Frontend decide el TRANSPORTE** (`src/lib/receiptPrinter.js`) y la UI está en la
  pestaña **Inventario → Caja** (`InventoryPrintTab.jsx`):
  - `simulacion` — muestra el ticket y el volcado ESC/POS en pantalla. Sin hardware.
  - `sunmi` — envía el ESC/POS por el **JS USDK OFICIAL de SUNMI** (`sunmi-js-sdk`,
    puente JS → `printer.commandApi.sendEscCommand(['<hex>'])`). El SDK habla con el
    servicio local del equipo (`ws://localhost:7070/ws`, lo instala la app "JS USDK"
    de la Sunmi App Store y se lanza por el deep link `sunmi://com.sunmi:8888/websdk`).
    SOLO reporta éxito ante un **ACK positivo (code===1)** del equipo; error, sin
    respuesta o socket no conectado = fallo (timeout de seguridad en el cliente).
    SUN-06 — recuperación: el SDK no reconecta, así que en cada envío se verifica
    el socket y, si cayó, se DESCARTA y reconstruye la instancia (arrancando el
    servicio por el deep link ANTES de abrir la conexión). No se reenvían trabajos
    en silencio: un reintento es siempre una acción explícita del usuario.
  - `navegador` — imprime el ticket por el servicio de impresión del sistema/Android.

### Logo del negocio en la cabecera (iter357)
- El ticket imprime el logo de Resilience Brothers como bitmap ESC/POS `GS v 0`
  (raster), centrado en la cabecera. Origen: `backend/assets/logo_original_black_bg.png`
  (claro sobre negro) → escala al ~70% del ancho del papel (múltiplo de 8, tope 190 px)
  → se invierte + se trama (dithering) para que lo claro imprima como tinta.
  Determinista y cacheado por ancho. Toggle "Imprimir logo en el ticket" (por defecto ON).
- El nombre del negocio SIGUE imprimiéndose como texto nítido bajo el logo, así que
  el logo funciona como marca aunque el wordmark se vea granulado en térmica.

### Comandos ESC/POS usados
- `ESC @` (init), `ESC a` (alineación), `ESC E` (negrita), `GS !` (tamaño),
- `GS v 0` **logo raster** del negocio en la cabecera (iter357),
- `GS V 0` corte total (autocortador del modelo 80 mm),
- **gaveta:** `ESC p 0 25 250` = `1b 70 00 19 fa` (pin 0, 25 ms on, 250 ms off),
  añadido al final del ticket SOLO si "Abrir gaveta al imprimir" está activo
  (**por defecto OFF** desde iter357), o por el botón "Abrir gaveta".
- Ancho: 48 columnas (80 mm) / 32 columnas (58 mm).
- **Texto ASCII-seguro + anti-inyección (iter357):** los acentos/ñ/¡ se transliteran
  (Café→Cafe) y se ELIMINAN los bytes de control (<0x20/0x7f) de todo texto de
  usuario, de modo que ningún campo pueda inyectar comandos de impresora ni un
  pulso de gaveta. Solo sobrevive ASCII imprimible (0x20–0x7e).

---

## ✅ Verificado por SIMULACIÓN (sin equipo) — iter356

Pruebas: `backend/tests/test_iter356_receipt_printing.py` (12/12) + revisión visual
en la pestaña Caja (modo Simulación).

- [x] El ESC/POS inicia con `ESC @` y contiene el corte total `GS V 0`.
- [x] El pulso de gaveta `ESC p 0 25 250` se añade cuando `open_drawer=True` y se
      OMITE cuando `False`; va después del corte.
- [x] `GET /drawer/open` devuelve exactamente `ESC @ + ESC p 0 25 250`.
- [x] Ancho 80 mm (48 col) y 58 mm (32 col) respetan el número de columnas.
- [x] Transliteración ASCII-segura (Café→Cafe, ¡Gracias→Gracias).
- [x] `build_receipt` → el base64 decodifica exactamente al ESC/POS; `escpos_len` coincide.
- [x] Totales/ítems/pagado/cambio se renderizan y cuadran.
- [x] Rutas protegidas (401/403 sin permiso `products`); sample/build/drawer responden 200.
- [x] UI: selección de transporte, ancho, toggle de gaveta, datos del negocio;
      "Ticket de prueba", "Abrir gaveta", "Imprimir desde venta reciente",
      vista del ticket + volcado ESC/POS en hexadecimal.
- [x] Transporte `navegador` (window.print) imprime el ticket en texto.

---

## ⏳ PENDIENTE de verificación FÍSICA en la T1730 (criterio de cierre)

> La integración se considerará VERIFICADA cuando impresora y gaveta funcionen en
> la T1730 real. Nada de esto se puede comprobar sin el equipo.

1. **Preparar el transporte en el equipo.** La SUNMI D3 Mini trae SUNMI OS
   (Android 13, sin GMS). Instalar un navegador Chromium e instalar la app PWA.
   Instalar la app **"JS USDK"** desde la SUNMI App Store: levanta el servicio
   local `ws://localhost:7070/ws` con el que habla `sunmi-js-sdk`.
2. **Ajustar en la UI (pestaña Caja):** transporte = "SUNMI (equipo)". No hay que
   configurar URL: el JS USDK gestiona su propio socket. La app PWA debe lanzarse en
   el propio equipo para que el deep link `sunmi://com.sunmi:8888/websdk` abra el servicio.
3. **Protocolo (ya implementado con el SDK oficial).**
   `receiptPrinter.js::sendEscposToSunmi` usa `new SUNMI()` → `init()` →
   `launchPrinterService()` → `printer.commandApi.sendEscCommand(['<hex>'])`, donde
   `<hex>` es el ESC/POS en hexadecimal. La promesa SOLO se resuelve con ACK `code===1`;
   si el equipo no responde, el timeout de 8 s rechaza (no hay falsos "éxito").
4. **Imprimir "Ticket de prueba"** → confirmar que sale el ticket completo CON LOGO y
   que el **autocortador** corta (modelo 80 mm).
5. **"Abrir gaveta"** → confirmar que la **gaveta** se abre con el pulso.
6. **"Imprimir desde una venta reciente"** → confirmar ticket real correcto.
7. **Página de códigos / acentos (opcional):** si se quieren acentos/ñ, fijar la
   codepage del equipo (p. ej. CP850) y sustituir la transliteración ASCII por el
   encoding correspondiente en `receipt_printing.py::_line`.
8. **Modelo 58 mm vs 80 mm:** confirmar el ancho correcto (32/48) según la variante
   comprada. El logo escala automáticamente al ancho elegido.

### Checklist físico resumido
- [ ] App "JS USDK" instalada (servicio local ws://localhost:7070/ws)
- [ ] Ticket de prueba impreso y cortado
- [ ] Logo del negocio visible y reconocible en la cabecera
- [ ] Gaveta abre con el pulso (solo cuando el toggle está activo)
- [ ] Ticket desde venta real correcto
- [ ] (opcional) Acentos/codepage ajustados
- [ ] Ancho de papel confirmado (80/58 mm)

---

## Notas
- No se usaron API keys ni servicios de pago; es impresión local por ESC/POS.
- El flujo de venta de inventario NO se modificó: la impresión es un módulo aparte
  reutilizable. Como mejora futura, se puede añadir un botón "Imprimir ticket"
  directamente tras registrar una venta.
