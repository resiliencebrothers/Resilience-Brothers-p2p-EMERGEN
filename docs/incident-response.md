# 🚨 Incident Response Runbook — Resilience Brothers

**Última actualización:** Jul 4, 2026 (iter47)
**Alcance:** Compromiso de seguridad, fuga de datos, hijack de dominio/DNS/email, brecha en servidor o DB, LLM key drenaje, ataque activo.

Este documento es **operativo** — pensado para ser leído bajo presión, no como referencia académica.
Si estás en pánico: ve a la sección [🔴 Primeros 15 minutos](#-primeros-15-minutos-checklist-emergencia).

---

## 📞 Contactos de emergencia (rellena antes de necesitarlos)

| Rol | Nombre | Teléfono / Email | Fuera de horario |
|-----|--------|------------------|------------------|
| Admin principal | _____________________ | _____________________ | _____________________ |
| Admin backup | _____________________ | _____________________ | _____________________ |
| Registrar (Cloudflare/Namecheap) | Soporte 24/7 | https://dash.cloudflare.com/support | — |
| Emergent Support | support@emergent | Chat en dashboard | — |
| Sentry Alertas | sentry.io org admin | _____________________ | — |
| Cyber-insurance (si aplica) | _____________________ | _____________________ | — |

---

## 🔴 Primeros 15 minutos — Checklist Emergencia

Cuando detectes o sospeches un compromiso activo, ejecuta EN ORDEN:

### Minuto 0-2: Aislar
```bash
# 1. Activar modo defensivo (bloquea nuevos registros + operaciones sensibles)
curl -X POST "$API_URL/api/admin/defensive-mode" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"enabled": true, "reason": "incident-response"}'
```

### Minuto 2-5: Cortar accesos
- [ ] **Revocar TODAS las sesiones activas**:
  ```javascript
  // En MongoDB shell:
  db.user_sessions.deleteMany({})
  ```
- [ ] **Rotar `SESSION_SECRET`** en `/app/backend/.env` → restart backend → **invalida cookies emitidos**
- [ ] **Cambiar contraseñas de admins** vía `/admin/users` (o SQL directo si el panel está comprometido)

### Minuto 5-10: Bloquear comunicaciones externas
- [ ] **Suspender GitHub Actions / auto-deploy** (Repo → Settings → Actions → Disable)
- [ ] **Revocar tokens API** (TronGrid, BscScan, Resend, Sentry, Emergent LLM key)
- [ ] **Bloquear IP del atacante** en Cloudflare Dashboard → Security → WAF → Custom Rule

### Minuto 10-15: Preservar evidencia
- [ ] **Snapshot MongoDB** antes de tocar nada:
  ```bash
  mongodump --uri="$MONGO_URL" --out=/tmp/incident_$(date +%Y%m%d_%H%M)/
  ```
- [ ] **Guardar logs**:
  ```bash
  cp /var/log/supervisor/backend.*.log /tmp/incident_logs/
  ```
- [ ] **Screenshot / grabar** cualquier UI comprometida
- [ ] **Notificar por WhatsApp/Signal** al backup admin

---

## 🎯 Playbooks por tipo de incidente

### 1. Compromiso de dominio (DNS hijack, transferencia no autorizada)

**Síntomas:**
- Cliente reporta que la web se ve diferente o pide credenciales adicionales
- Emails de "Domain transfer" no solicitados en el registrar
- WHOIS muestra registrar diferente
- Certificado SSL cambió (revisa `crt.sh` para tu dominio)

**Acciones:**
1. **Contacta al registrar por teléfono** (chat/email es más lento). Cloudflare: +1-888-99-CFCF
2. Solicita **rollback de cambios recientes** al soporte del registrar
3. Verifica DNS records esperados vs actuales:
   ```bash
   dig +short resiliencebrothers.com @1.1.1.1
   dig +short resiliencebrothers.com @8.8.8.8
   dig +short MX resiliencebrothers.com
   dig +short TXT resiliencebrothers.com
   ```
4. Si DNSSEC está activo, verifica cadena de firmas:
   ```bash
   dig +dnssec resiliencebrothers.com
   ```
5. Notifica a clientes por email interno (usa `noreply@` NO el hijackeado):
   > "Detectamos actividad inusual en nuestro DNS. Si en las últimas horas viste
   > un mensaje pidiendo actualizar tu contraseña, IGNÓRALO. Vamos a resolver en X horas."

### 2. Compromiso de correo corporativo

**Síntomas:**
- Emails enviados desde tu cuenta que no reconoces
- Reglas de reenvío desconocidas
- Sesiones activas en IPs raras (Google Workspace → Security → Login events)

**Acciones:**
1. Google Workspace Admin → **Force sign-out** de la cuenta comprometida
2. Deshabilita cuenta temporalmente
3. Revisa **reglas de reenvío** (Configuración → Filtros): elimina cualquiera no reconocida
4. Rota contraseñas de TODOS los servicios donde ese email hacía reset (banco, registrar, GitHub, admin panel...)
5. Activa **Google Advanced Protection Program** si no estaba
6. Reset de recovery email/phone

### 3. Compromiso de GitHub / código malicioso desplegado

**Síntomas:**
- Commits que no reconoces en `main`
- Behavior extraño en producción sin cambios documentados
- Alertas de Dependabot ignoradas
- Actions ejecutándose fuera de horario

**Acciones:**
1. **Revertir a commit conocido bueno**:
   ```bash
   git log --oneline -20
   git revert <commit-malicious>
   git push origin main
   ```
2. **Rotar todos los secrets** que hayan podido leerse desde el repo:
   - `SESSION_SECRET`, `MONGO_URL`, `RESEND_API_KEY`, `SENTRY_DSN` (si sensible), `EMERGENT_LLM_KEY`
3. Auditoría GitHub → **Security log** de la última semana
4. Verificar **branch protection** sigue activo (require reviews, no force push)
5. Rotar personal access tokens (PATs) de cualquier colaborador con acceso

### 4. Base de datos comprometida (fuga)

**Síntomas:**
- Datos de usuarios apareciendo en foros / breach forums
- Alertas de acceso desde IPs no reconocidas
- Colecciones vacías o corruptas
- Documentos modificados masivamente

**Acciones:**
1. **Rotar contraseña de MongoDB user** (Atlas → Database Access)
2. **Restaurar backup** más reciente PREVIO al compromiso:
   ```bash
   mongorestore --uri="$MONGO_URL_NEW" --nsInclude="resilience.*" /path/to/backup
   ```
3. **Forzar reset de contraseña a TODOS los usuarios** (correo + banner in-app)
4. Notificar a autoridades locales si hay >X registros de PII expuestos (obligación regulatoria en muchas jurisdicciones)
5. **Cambiar VAPID keys** (invalidará suscripciones push existentes, pero previene phishing por push)

### 5. Ataque activo (DDoS, brute-force, scraping)

**Síntomas:**
- Sentry alerts en cascada
- Latency alta en `/api/*`
- 429s en logs
- Órdenes falsas siendo creadas

**Acciones:**
1. Activar **modo bajo demanda de Cloudflare** (Under Attack Mode):
   Dashboard → Security → Settings → Security Level: "Under Attack"
2. Endurecer rate limits en `security_middleware.py`:
   - Baja `default_limits` a `50/minute`
   - Baja `/auth/login` a `3/minute`
3. Revisar `db.login_attempts` para identificar patrones:
   ```javascript
   db.login_attempts.aggregate([
     {$group: {_id: "$ip", count: {$sum: 1}}},
     {$sort: {count: -1}}, {$limit: 20}
   ])
   ```
4. Bloquear IPs específicas en Cloudflare WAF

### 6. LLM key drenaje

**Síntomas:**
- Notificación "Universal Key low balance" reciente
- Uso masivo inesperado en el dashboard de Emergent
- Endpoint `/api/notify-me` u otro llamando a LLM en loop

**Acciones:**
1. Ve al Profile → Universal Key → **Pausar auto top-up**
2. Revisa Sentry por endpoints con >100 calls/min
3. Añade rate limit específico en endpoint LLM (`@limiter.limit("10/minute")`)
4. Contacta support@emergent para reversion de cargos por abuse

---

## 🔐 Rotación de secrets (checklist trimestral o post-incidente)

Rotar en este orden (dependency-aware):

- [ ] `SESSION_SECRET` (invalida sesiones existentes — comunicar antes)
- [ ] `MONGO_URL` password (Atlas → Database Access → Edit user → new password)
- [ ] `EMERGENT_LLM_KEY` (Profile → Regenerate)
- [ ] `RESEND_API_KEY` (dashboard Resend → API Keys → Rotate)
- [ ] `SENTRY_DSN` (Project Settings → Client Keys → New)
- [ ] `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` (regenerar con `py_vapid`)
- [ ] `GOOGLE_CLIENT_SECRET` (Google Cloud Console → Credentials)
- [ ] `FERNET_KEY` (si se implementa)

Después de rotar: `supervisorctl restart backend` + verificar `/api/health`.

---

## 📊 Post-incidente

Dentro de las 72 h del incidente:

1. **Escribir el post-mortem** en `/app/docs/post-mortems/YYYY-MM-DD_slug.md` con:
   - Timeline detallado
   - Root cause (no personas — proceso)
   - Damage assessment (fondos, PII, reputación)
   - Action items con owners
2. **Publicar transparencia** a clientes si hubo fuga de datos
3. **Actualizar este runbook** con lecciones aprendidas
4. **Simular** el incidente en un entorno de staging cada 6 meses

---

## 🛡️ Estado actual de defensas (iter47)

Verificado activo:
- ✅ Rate limiting (slowapi): 10/min login, 5/hour register, 3/hour forgot-password, 5/hour appeals
- ✅ Security headers: HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
- ✅ CORS estricto (whitelist en env, wildcard rechazado en prod)
- ✅ Origin allowlist middleware (defensa in-depth vs. `*` rewrites del proxy)
- ✅ Sentry captura errores 500+
- ✅ TOTP en acciones de alto riesgo
- ✅ Sesiones expirables (7 días default)

Pendientes de activar por el usuario:
- ⚠️ Domain lock + 2FA hardware key en registrar
- ⚠️ DNSSEC + CAA records
- ⚠️ Google Advanced Protection Program
- ⚠️ Cloudflare frente al backend (proxy + WAF)
- ⚠️ SPF/DKIM/DMARC en email corporativo
- ⚠️ Backups off-site 3-2-1
- ⚠️ Cuenta break-glass offline
