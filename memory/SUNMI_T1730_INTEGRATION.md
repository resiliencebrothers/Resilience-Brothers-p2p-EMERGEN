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
  - `sunmi` — envía el ESC/POS al middleware local del equipo por WebSocket
    (`ws://127.0.0.1:8080/` por defecto, configurable en la UI).
  - `navegador` — imprime el ticket por el servicio de impresión del sistema/Android.

### Comandos ESC/POS usados
- `ESC @` (init), `ESC a` (alineación), `ESC E` (negrita), `GS !` (tamaño),
- `GS V 0` corte total (autocortador del modelo 80 mm),
- **gaveta:** `ESC p 0 25 250` = `1b 70 00 19 fa` (pin 0, 25 ms on, 250 ms off),
  añadido al final del ticket si "Abrir gaveta al imprimir" está activo, o por el
  botón "Abrir gaveta".
- Ancho: 48 columnas (80 mm) / 32 columnas (58 mm).
- **Texto ASCII-seguro:** los acentos/ñ/¡ se transliteran (Café→Cafe) para que el
  PRIMER ticket físico salga legible sin depender de la página de códigos del equipo.

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
   Para imprimir desde la web hace falta un puente al servicio de impresión:
   - Opción recomendada: middleware **SUNMI "JS USDK"** (WebSocket local). Instalarlo
     desde la SUNMI App Store y anotar el **puerto/URL** real.
   - Alternativa: app nativa puente (AIDL `woyou.aidlservice.jiuiv5.IWoyouService`,
     método `sendRAWData(byte[])`), o esquema `sunmiprint://`.
2. **Ajustar en la UI (pestaña Caja):** transporte = "SUNMI (equipo)" y la
   **URL del servicio** (`ws://127.0.0.1:<puerto>/`) según el middleware instalado.
3. **Confirmar la TRAMA del WebSocket.** `receiptPrinter.js::sendEscposToSunmi` envía
   `{"type":"escpos","data":"<base64>"}`. Verificar que el JS USDK instalado espera
   ese formato; si no, ajustar esa única función (y, si procede, enviar bytes crudos).
4. **Imprimir "Ticket de prueba"** → confirmar que sale el ticket completo y que el
   **autocortador** corta (modelo 80 mm).
5. **"Abrir gaveta"** → confirmar que la **gaveta** se abre con el pulso.
6. **"Imprimir desde una venta reciente"** → confirmar ticket real correcto.
7. **Página de códigos / acentos (opcional):** si se quieren acentos/ñ, fijar la
   codepage del equipo (p. ej. CP850) y sustituir la transliteración ASCII por el
   encoding correspondiente en `receipt_printing.py::_line`.
8. **Modelo 58 mm vs 80 mm:** confirmar el ancho correcto (32/48) según la variante
   comprada.

### Checklist físico resumido
- [ ] Middleware de impresión instalado y URL WebSocket anotada
- [ ] Ticket de prueba impreso y cortado
- [ ] Gaveta abre con el pulso
- [ ] Ticket desde venta real correcto
- [ ] (opcional) Acentos/codepage ajustados
- [ ] Ancho de papel confirmado (80/58 mm)

---

## Notas
- No se usaron API keys ni servicios de pago; es impresión local por ESC/POS.
- El flujo de venta de inventario NO se modificó: la impresión es un módulo aparte
  reutilizable. Como mejora futura, se puede añadir un botón "Imprimir ticket"
  directamente tras registrar una venta.
