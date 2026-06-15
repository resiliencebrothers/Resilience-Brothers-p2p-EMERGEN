# Guía de Despliegue — Resilience Brothers P2P

> Subdominio objetivo: **`p2p.resiliencebrothers.com`**
> Dominio raíz reservado para tu otra app web existente.

---

## ✅ Pre-requisitos (haz esto antes de hacer el deploy)

### 1. Acceso a tu proveedor de dominio
Confirma que tienes acceso al panel de DNS de `resiliencebrothers.com` (donde administras los registros). Puede ser:
- Cloudflare
- Namecheap
- GoDaddy
- Google Domains
- Otro registrar

### 2. (Opcional) Limpieza previa de DNS
Si en tu DNS ya existe un registro `A`, `AAAA` o `CNAME` para el subdominio `p2p`, **elimínalo** ahora para evitar conflictos durante la verificación de Entri.

```
Buscar y eliminar (si existen):
- p2p     A      → cualquier IP
- p2p     CNAME  → cualquier valor
```

---

## 🚀 Paso a paso: Deploy + dominio personalizado

### Paso 1: Hacer el deploy del proyecto
1. En el **chat input de Emergent** (esta interfaz), encontrarás la opción **"Deploy"**.
2. Haz click en **Deploy**.
3. Emergent te dará una URL temporal del tipo `*.emergentagent.com`.
4. Espera a que el deploy termine (típicamente 2-3 minutos).

> ⚠️ **Costo**: 50 créditos/mes por app desplegada. Tu app actual en `resiliencebrothers.com` sigue funcionando sin cambios.

### Paso 2: Vincular el subdominio
1. En el panel post-deploy de Emergent, busca la opción **"Link domain"** o **"Custom domain"**.
2. Ingresa exactamente: **`p2p.resiliencebrothers.com`**
3. Emergent te conectará automáticamente con **Entri** (servicio de configuración DNS).

### Paso 3: Configurar DNS vía Entri
1. **Entri detectará automáticamente** tu proveedor de DNS (Cloudflare, Namecheap, etc.).
2. Tienes dos opciones:
   - **Auto-config (recomendado)**: Entri te pide login en tu proveedor de DNS y configura los registros por ti.
   - **Manual**: Entri te muestra los registros exactos (CNAME) y tú los agregas a mano en tu panel.
3. Los registros típicos serán algo como:
   ```
   Tipo:   CNAME
   Nombre: p2p
   Valor:  <hostname que Entri te indique>
   TTL:    3600 (o "automático")
   ```

### Paso 4: Esperar propagación DNS
- **Tiempo típico**: 5-15 minutos.
- **Máximo**: hasta 24h en casos raros (depende del TTL anterior).
- **Verificar**: abre `https://p2p.resiliencebrothers.com` en una pestaña incógnito. Si carga la landing de Resilience Brothers, ¡listo!

### Paso 5: SSL automático
- Emergent configura **HTTPS automáticamente** vía Let's Encrypt una vez que el DNS resuelve.
- No tienes que hacer nada extra.

---

## 📧 Configuración de Resend (en progreso según mencionaste)

Una vez Resend te confirme que el dominio `resiliencebrothers.com` está **verified**:

### Paso 1: Actualiza el remitente en el código
El email actual usa el sandbox (`@resend.dev`). Cuando esté verificado, modificamos el archivo:

`/app/backend/email_service.py` — buscar la línea con `from_email` y cambiarla a:
```python
from_email = "Resilience Brothers <notificaciones@resiliencebrothers.com>"
```

Avísame cuando Resend marque el dominio como verified y lo cambio en un commit (es un cambio de 1 línea).

### Paso 2: Probar el flujo
Una vez actualizado:
- Crea una orden de prueba con un cliente
- Apruébala como admin
- El cliente debe recibir un email desde `notificaciones@resiliencebrothers.com` (no más sandbox 403s en los logs).

> 💡 **Nota importante**: Una sola verificación de Resend para el dominio raíz `resiliencebrothers.com` cubre **ambas apps** (la tuya existente y esta P2P), sin importar en qué subdominio estén.

---

## ✅ Checklist post-deploy

Una vez `p2p.resiliencebrothers.com` esté activo, verifica:

- [ ] Carga la landing pública correctamente.
- [ ] Login con Google funciona (debe redirigir bien al subdominio).
- [ ] Como admin: ves Dashboard, Auditoría, Ingresos, Tasas, etc.
- [ ] PWA instalable desde móvil (aparece "Add to Home Screen" en iOS/Android).
- [ ] Push notifications: activa el toggle y deberías recibir notificaciones al aprobar órdenes.
- [ ] Audit Log se llena cuando apruebas/rechazas órdenes.
- [ ] Defensive Mode: crea una orden con margen bajo → debe quedar en `requires_double_approval`.

---

## 🛠 Troubleshooting

### "Domain not verifying" tras 30 minutos
1. Confirma en `dnschecker.org` que el CNAME `p2p.resiliencebrothers.com` resuelve al hostname de Emergent.
2. Si no resuelve, revisa que no haya registros `A` viejos compitiendo.
3. Limpia caché DNS local: `sudo systemctl flush-dns` (Linux) o `ipconfig /flushdns` (Windows).

### "Mixed content" o errores HTTPS
- Espera 5 min más después de que el DNS propague — el SSL automático tarda un poco.
- Si persiste, contacta al soporte de Emergent desde la pestaña Support.

### Login no funciona en el subdominio
- Vacía cookies del navegador para `resiliencebrothers.com` y vuelve a intentar.
- Confirma que el flujo de Emergent Google Auth no esté cacheando una URL vieja.

### Emails todavía van al sandbox después de verificar Resend
- Avísame para actualizar el remitente en `email_service.py` (es 1 línea de código).
- Reiniciar backend: `sudo supervisorctl restart backend`.

---

## 📊 Resumen final

| Item | Estado |
|---|---|
| Subdominio elegido | `p2p.resiliencebrothers.com` |
| Dominio raíz | Reservado para tu otra app — sin cambios |
| Deploy Emergent | Pendiente (paso 1) |
| DNS Entri | Pendiente (paso 3) |
| SSL | Automático tras DNS |
| Resend dominio | **En verificación** (lo confirmarás tú) |
| Resend remitente en código | Pendiente actualizar a `@resiliencebrothers.com` después de verify |

---

**Cuando termines el deploy**, vuelve aquí y avísame si:
1. ✅ Todo cargó bien — para hacer el smoke test de los flujos.
2. ❌ Algo falla — para ayudarte a debuggear.
3. 📧 Resend ya está verified — para cambiar el remitente.
