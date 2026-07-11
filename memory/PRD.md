# Resilience Brothers — P2P Trading Platform

## Original Problem Statement
Plataforma web para empresa de comercio P2P "Resilience Brothers". Conecta empresas y clientes mediante una plataforma global de comercio P2P. Dos secciones: intercambio de criptomonedas por dinero Fiat, y marketplace de mercancías para clientes VIP. Admin gestiona monedas (cripto + fiat) y tasas de cambio. Diferenciación clientes VIP (sin comisión, tasas preferenciales, saldo acumulado, canje por mercancía) vs Normales (5% comisión).

## Architecture
- **Backend**: FastAPI (Python) + Motor (MongoDB async) at `/app/backend/server.py`. All routes prefixed `/api`.
- **Frontend**: React 19 + React Router + Tailwind + Shadcn UI at `/app/frontend/src`.
- **Database**: MongoDB collections: `users`, `user_sessions`, `currencies`, `rates`, `orders`, `products`, `redemptions`, `withdrawals`.
- **Auth**: Emergent OAuth (Google), httpOnly cookie + Bearer fallback. First registered user auto-promoted to admin.
- **Storage**: Proof screenshots stored as base64 data-URLs inside the order document (MVP simplicity).

## User Personas
- **Admin (Resilience team)**: Manages currencies, exchange rates, approves/rejects orders, manages users, products, withdrawals and redemptions.
- **VIP Client**: High-volume reseller. 0% commission, preferential rates, accumulated USD balance, can withdraw or redeem for goods.
- **Normal Client**: One-off user. 5% commission, standard rates.

## Core Requirements (static)
1. Google login (Emergent OAuth).
2. Admin CRUD for crypto and fiat currencies + payment account info.
3. Admin CRUD for exchange rates (rate_normal + rate_vip per pair).
4. Manual P2P order flow: pick pair → see rate → upload screenshot proof → admin approves → choose delivery.
5. VIP balance accumulation when delivery method = "accumulate" and order approved.
6. VIP marketplace: redeem balance for physical goods (rice, flour, drinks, oil...).
7. VIP withdrawals in transfer/cash/crypto.
8. Dark fintech UI (yellow accent #EAB308, Outfit + IBM Plex Sans).

- Code Quality Refactor (iter44, Jul 3 2026): reduced cyclomatic complexity across three hot paths:
  - `_compute_company_funds` (D:22 → <C:11): extracted `_aggregate_by_currency` + `_aggregate_manual_adjustments` + module-level `_norm_code` helpers in `routes/admin_company_funds.py`.
  - `notify_all_admins` (C:13 → <C:11): split into `_push_fanout_to_admins` + `_email_fanout_to_admins` in `admin_alerts.py`.
  - `_fanout_rate_change_push` (C:20 → C:11): split into `_rate_fanout_inapp` + `_rate_fanout_push` in `routes/market.py`.
  - Google OAuth `email_verified` check in `routes/auth.py:229` migrated from `is False` (PEP-8 anti-pattern for tri-state semantics) to `not claims.get("email_verified", True)`.
  - Verified GREEN by testing agent (iter44 report): 102/102 backend tests pass, zero regressions. Frontend build already compiled with zero warnings (no exhaustive-deps changes needed).
- Architectural Refactor (iter45, Jul 4 2026): reduced complexity on the four remaining D:22+ hot spots. All 4 targets now sit below the C threshold (<11). Radon codebase average dropped from C:15.19 → C:11.8.
  - `server.py:start_background_jobs` (D:28 → <C:11): whitespace migration extracted to new `services/db_migrations.py:clean_currency_whitespace` service; startup handler is now 26 lines and reads top-to-bottom as `migrate → define timeseries → start scheduler`.
  - `routes/auth.py:google_callback` (D:26 → <C:11): split into `_exchange_google_code` (token exchange + JWT audience + email validation) and `_upsert_google_user` (delegates to `_update_existing_google_user` / `_create_google_user`).
  - `services/transactions.py:build_transactions` (D:22 → <C:11): split into 3 fetch helpers (`_fetch_entradas_orders`, `_fetch_salidas_withdrawals`, `_fetch_salidas_order_payouts`) + 3 row-formatter helpers (`_order_to_entrada`, `_withdrawal_to_salida`, `_order_payout_to_salida`).
  - `transactions_pdf.py:generate_transactions_pdf` (D:22 → <C:11): split into `_build_filters_paragraph`, `_build_totals_paragraph`, `_format_entry_row`, `_build_transactions_table`.
  - Verified GREEN by testing agent (iter45 report): 138/138 backend tests pass, whitespace-migration E2E confirmed with planted dirty rows, Google OAuth live-smoke curls all green, transaction PDF export produces valid PDFs (verified %PDF- magic + byte size). Zero regressions.
- Self-Service Appeals (iter46, Jul 4 2026): P1 backlog feature complete. Clients in `account_status=under_review` can submit a written appeal directly from the yellow banner in `/dashboard` (max 1 open appeal at a time, min 10 chars); staff (admin OR employee with `can_manage_blocklist=True`) receive an in-app notification of type `new_appeal` + web push and review appeals from a new page `/admin/appeals` with tabs (pendientes/aprobadas/rechazadas/todas). Resolving/rejecting an appeal delivers the staff's textual response back to the client via a notification (`appeal_resolved` / `appeal_rejected`) but explicitly does NOT flip `account_status` — staff must still go through Users → Verificar teléfono to reactivate.
  - New router: `/app/backend/routes/appeals.py` (5 endpoints).
  - New collection: `appeals` with fields `id, user_id, user_email, user_name, user_phone, message, status, staff_response, resolved_by, resolved_by_email, resolved_at, created_at`. Idempotency via 409 on double-submit while pending.
  - New notification helpers: `notify_staff_new_appeal`, `notify_user_appeal_reviewed` in `routes/notifications.py`.
  - New UI: `/app/frontend/src/components/AppealDialog.jsx` (client dialog with textarea + history), `/app/frontend/src/pages/admin/AdminAppeals.jsx` (staff queue with resolve/reject).
  - Verified GREEN by testing agent (iter46 report): **10/10 backend tests pass** (7 supplied + 3 authz regression), **frontend E2E 100%** (client submit + pending-guard + admin resolve + admin reject + tab navigation). Zero regressions.
- Security Hardening (iter47, Jul 4 2026): 5-part defense-in-depth added at HTTP/middleware layer. New `security_middleware.py` module wires (a) strict CORS with wildcard-rejected-in-production, (b) rate limiter (slowapi) with per-endpoint buckets, (c) security headers middleware (HSTS/CSP/X-Frame/X-Content-Type-Options/Referrer-Policy/Permissions-Policy/X-Permitted-Cross-Domain-Policies), (d) Origin allowlist middleware that blocks cross-origin POST/PUT/PATCH/DELETE with 403 as defense in depth against the Emergent K8s ingress that rewrites `Access-Control-Allow-Origin: *`.
  - Rate limits applied: `/auth/login` 10/min, `/auth/register` 5/hour, `/auth/forgot-password` 3/hour, `/auth/reset-password` 10/hour, `/auth/resend-verification` 3/hour, `/appeals` 5/hour, global default 300/min.
  - Operational runbook `/app/docs/incident-response.md` created (contacts, 15-minute triage checklist, 6 incident playbooks, secret rotation, post-mortem template).
  - Pre-commit hook `/app/.githooks/pre-commit` blocks BIP39 mnemonics, private keys, xpubs, AWS keys, Google keys, JWTs, and `.env` files from being committed.
  - Verified GREEN by testing agent (iter47 report): **20 new tests PASS** (7 in test_security_middleware.py + 13 in test_iter47_security_review.py), **101/101 regression tests PASS**, mypy strict clean (28 files), frontend build 0 warnings, CORS wildcard raises RuntimeError in production, security headers verified on every response via curl.
  - Known limitation: Emergent K8s ingress rewrites Origin header from client-real to internal cluster hostname `.emergentcf.cloud`; both external + internal preview domains are in `CORS_ORIGINS` allowlist. Production deployment MUST set `CORS_ORIGINS` to explicit domain list and `RATE_LIMIT_ENABLED=true`.
- Admin Security Audit Dashboard (iter48, Jul 4 2026): admin-only page at `/admin/security` aggregating 5 signals over the last 7 days — (1) active sessions grouped by role + top-20 staff sessions with per-user "revoke all" button, (2) admin/employee logins from IPs never seen in the last 90 days, (3) top-10 IPs blocked by rate limiter, (4) latest 20 origin-allowlist violations (potential CSRF), (5) failed-login bursts by identifier (potential credential stuffing).
  - New service `/app/backend/services/security_events.py` with `log_security_event()`, `known_ip_for_user()`, `remember_login_ip()`, `ensure_indexes()`.
  - New collections: `security_events` (kind, ip, path, method, origin, user_agent, user_id, user_email, extra, created_at, _ts) with **30-day TTL index** on `_ts` for auto-cleanup — bounded growth. `user_login_ips` (user_id, ip, first_seen, last_seen) for new-IP detection.
  - New router `/app/backend/routes/admin_security.py` — GET `/admin/security/audit` + POST `/admin/security/sessions/{user_id}/revoke` (both admin-only, employee gets 403).
  - Instrumentation: `OriginAllowlistMiddleware` logs `origin_blocked` events; `_rate_limit_logged_handler` wraps slowapi 429 to log `rate_limit_hit`; `auth_login` logs `admin_new_ip` on staff login from unseen IP.
  - New UI `/app/frontend/src/pages/admin/AdminSecurity.jsx` with 4 summary cards + 5 detail panels + revoke buttons. Nav link `admin-nav-security` only rendered for role=admin.
  - Verified GREEN by testing agent (iter48 report): **9/9 iter48 tests PASS + 44/44 regression PASS**, frontend E2E 100%, missing `ShieldAlert` import in AdminPanel.jsx fixed. TTL index verified in Mongo (`ttl_ts_30d`, expireAfterSeconds=2592000).
- Automated Security Alerts Scanner (iter49, Jul 4 2026): APScheduler job runs every 5 minutes over `security_events` to detect and fanout push+email alerts to all admins on 3 anomalies:
  - `admin_multi_ip`: staff account logged in from ≥3 distinct IPs in the last 24h (threshold configurable via `ADMIN_MULTI_IP_THRESHOLD`).
  - `ip_rate_flood`: single IP triggered ≥100 rate_limit_hit events in the last 1h.
  - `origin_flood`: single IP triggered ≥20 origin_blocked events in the last 1h.
  - New service `/app/backend/services/security_alerts.py` with `run_security_alert_scan()`, `_detect_admin_multi_ip`, `_detect_ip_flood`, dedup via `security_alerts_sent` collection (anomaly_key + 6h cool-off, TTL 7d).
  - Cool-off configurable via `SECURITY_ALERT_COOLDOWN_HOURS` env var.
  - Robustness: alert-mark happens BEFORE notify_all_admins fanout so a raise in delivery cannot cause the same anomaly to re-fire every 5 minutes.
  - Reuses `admin_alerts.notify_all_admins()` for delivery (push per admin device + email to ops mailbox).
  - Alerts link to `/admin/security` dashboard so admins can drill down and revoke sessions if needed.
  - Verified GREEN by testing agent (iter49 report): **6/6 iter49 tests PASS + 53/57 regression PASS** (4 rate-limit skipped as expected under `RATE_LIMIT_ENABLED=false`), TTL index `ttl_ts_7d` verified (expireAfterSeconds=604800), scheduler startup logs both jobs.
- Cloudflare WAF IP Blocking (iter50, Jul 4 2026): automated edge-firewall enforcement layer wired into the iter49 alert scanner. When `CLOUDFLARE_AUTO_BLOCK_ENABLED=true` AND `CF_API_TOKEN` + `CF_ZONE_ID` are set, the scanner blocks any IP that triggers `ip_rate_flood` or `origin_flood` at the Cloudflare zone-level firewall BEFORE notifying admins — the alert body reflects the block outcome.
  - New service `/app/backend/services/cloudflare_client.py`: httpx wrapper over `zones/{zone_id}/firewall/access_rules/rules` REST (create/delete/list block rules). Failure policy: log-and-continue. Duplicate rule detection looks up the existing rule id so we can still persist the linkage.
  - New service `/app/backend/services/cloudflare_blocks.py`: persistent audit trail in `cloudflare_ip_blocks` collection. States: `active` / `pending_create` / `pending_delete` / `deleted` / `failed`. Idempotent create (returns `already_blocked=True` for existing active IP). Insert-first, enforce-second policy so audit is preserved even when CF is down.
  - New admin endpoints `/api/admin/security/cloudflare/blocks` (GET list, POST manual block, DELETE unblock) — all admin-only (employee=403), gated by `_require_admin_only` in `routes/admin_security.py`.
  - Graceful degradation: without CF credentials the endpoints still work — records persist locally with `status='failed'` + `reason='not_configured'` so admins keep the audit trail and the UI clearly shows the misconfiguration ("Sin credenciales" pill).
  - Startup wire: `cloudflare_blocks.ensure_indexes(db)` added to `server.py` on-event startup — indexes on `ip+status`, `cf_rule_id`, `created_at`.
  - Bug fix on session start: `routes/admin_security.py` was importing `Optional` implicitly — added to typing import (backend was in restart loop after the fork).
  - Frontend `/admin/security` gains a new panel "Cloudflare WAF · Blocklist" with 2 status pills (configured / auto-block), a table of blocks (IP, status badge with color, source, notes, created_at, unblock button), and a modal dialog to manually block an IP with warning when CF is not configured. Test-ids: `cf-refresh-btn`, `cf-add-block-btn`, `cf-blocks-table`, `cf-block-row-{id}`, `cf-unblock-btn-{id}`, `cf-block-dialog`, `cf-block-ip-input`, `cf-block-notes-input`, `cf-block-submit-btn`.
  - Verified GREEN by testing agent (iter50 report): **40/40 tests PASS** (18 iter50 unit/integration + 22 regression iter48/iter49/appeals). Frontend E2E: dialog open → submit → warning toast → row with 'FAILED' badge → desbloquear removes the row. Zero regressions. mypy strict 32/32 files.
  - Env vars required to activate real enforcement (currently OFF): `CF_API_TOKEN` (scoped token with **Zone → Firewall Services → Edit** on target zone), `CF_ZONE_ID`, `CLOUDFLARE_AUTO_BLOCK_ENABLED=true`. Manual blocks work in the local persistence layer even without these.

- App-Level IP Blocklist Middleware (iter50b, Jul 5 2026): **the pragmatic pivot** — after WHOIS/DNS analysis (`resiliencebrothers.com` on Namecheap/Route 53 with `p2p.resiliencebrothers.com` A → `162.159.142.117` which is Emergent's own Cloudflare edge), we realized migrating our DNS to a Cloudflare zone we control would NOT protect the p2p subdomain because Emergent's Cloudflare would still intercept traffic first. Migrating DNS was risky (24h propagation, no MX in Cloudflare Free means email forwarding via Namecheap SPF chain, 19 records to preserve) with zero payoff for the p2p app.
  - New `/app/backend/middleware/ip_blocklist.py`: FastAPI Starlette middleware installed LAST in `security_middleware` chain (so it runs FIRST for incoming requests via LIFO). Reads the same `cloudflare_ip_blocks` collection with a 30s in-process TTL cache. Returns `403 {code: 'IP_BLOCKED', detail: 'Tu dirección IP está bloqueada...'}` for any request whose real IP (X-Forwarded-For leftmost, RFC 7239) matches a record with status ∈ `{active, failed, pending_create}`. Records with `status='deleted'` are NOT enforced.
  - Cache invalidation: admin CRUD endpoints (`POST /api/admin/security/cloudflare/blocks` + `DELETE`) and the scanner's auto-block path all call `invalidate_cache()` so blocks/unblocks take effect within milliseconds (not 30s).
  - Scanner semantics changed: `services/security_alerts._fire_ip_flood` now gates on `APP_AUTO_BLOCK_ENABLED` (default `true`, previously gated on `CLOUDFLARE_AUTO_BLOCK_ENABLED`). If CF creds ARE also set, the block is additionally pushed to the CF edge for defense-in-depth — the alert body reflects which layer(s) succeeded.
  - Frontend `/admin/security` panel renamed to **"Blocklist de IPs (aplicación)"** with 3 pills: `Enforcement app-level: activo ✓`, `Cloudflare edge: sin credenciales / configurado ✓`, `Auto-block: solo app-level / activo`. Manual block toast says "IP bloqueada a nivel aplicación" (or "app + Cloudflare WAF" when both layers succeed).
  - Verified GREEN by testing agent (iter51 report): **52/52 iter50b+iter50+iter49+iter48+appeals + 46/46 canary regression + 88 pytest local**. E2E curl confirmed 403 enforcement, cache invalidation instant, frontend labels correct.
  - Trade-off vs Cloudflare WAF: request still reaches our ingress (Emergent's Cloudflare drops it there ~2ms), so this doesn't protect against volumetric DDoS. But Emergent's own Cloudflare + our rate-limits + this middleware handle everything up to L7 attacks fine. Truly volumetric attacks need infrastructure that customers of Emergent don't control.
  - Env var: `APP_AUTO_BLOCK_ENABLED=true` (default). Set to `false` to disable automatic blocking from the scanner (manual blocks continue to work).

- KYC/AML Light — Identity Verification Queue (iter52, Jul 5 2026): first-pass identity check flow for scaling from beta to real users. Explicit operator constraint: **no country/geo restrictions of any kind** — no IP-country vs phone-country mismatch flag, no OFAC country blocklist, no sanctioned-country logic. Country is stored as informational data only.
  - New collection `kyc_verifications`: `{id, user_id, user_email, user_name, user_phone, status, documents[], risk_score 0-100, risk_flags[], submit_ip, submit_user_agent, reviewed_by, reviewed_at, review_notes, rejection_reasons[], created_at, updated_at}`. Indexes: `(user_id, created_at desc)`, `status`, `submit_ip`.
  - `users` collection gains 3 nullable fields at approval time: `kyc_status` ∈ {unverified, pending, verified, rejected, needs_more_info}, `kyc_verified_at`, `kyc_last_submit_at`.
  - Client endpoints: `POST /api/kyc/submit` (uploads 3 base64 documents to R2 via existing `proof_upload.maybe_upload_proof`), `GET /api/kyc/my-status`. Idempotent: cannot re-submit while an active (pending/verified/needs_more_info) verification exists (409).
  - Admin/staff endpoints: `GET /api/admin/kyc/queue` (filters status+search+min_risk), `GET /api/admin/kyc/funnel`, `GET /api/admin/kyc/{id}`, `POST /api/admin/kyc/{id}/approve|reject|request-more-info`.
  - Risk scoring (all heuristics NO country-related):
    * `disposable_email` (high, +40) — email domain in the 15-domain blocklist (mailinator, tempmail, guerrillamail, etc).
    * `duplicate_name` (medium, +20) — 3+ user accounts share the exact same full name.
    * `shared_ip` (medium, +20) — 5+ KYC submissions from same IP in last 24h.
    * `early_large_order` (medium, +20) — user tried an order ≥ $500 USDT-eq in the last 30 days before verification.
    Score capped at 100. `high_risk_pending` funnel = pending items with score ≥ 40.
  - Notifications fan-out: 3 new in-app notification types (`kyc_verified`, `kyc_rejected`, `kyc_needs_more_info`) delivered to the client via existing NotificationBell component.
  - Frontend `/dashboard/kyc` (KYCView.jsx): client-side wizard. Status card with icon-per-state (unverified/pending/verified/rejected/needs_more_info). 3 upload rows for id_front + id_back + selfie with preview thumbnails + remove buttons. Enabled-only-when-all-3-loaded submit button. Rejected users see the reasons list and can resubmit.
  - Frontend `/admin/kyc` (AdminKYC.jsx): 6 funnel cards + 4 tabs + search + min_risk filter + list with rows showing risk score badge + flag count. Action dialog shows document thumbnails (clickable to open full-size), risk-flags panel, notes textarea; for reject: 7 predefined reason checkboxes + custom notes.
  - Nav: added `IdCard` icon items in both sidebars (client + admin).
  - Verified GREEN by testing agent (iter52 report): **16/16 iter52 pytest + 42/42 regression + E2E frontend flow** (client submit + admin approve + client sees "Verificado" post-approval + non-staff blocked from /admin/kyc). Zero regressions. OpenAPI at 106 paths (3 snapshots updated).
  - Out of scope (deferred to future iterations): OCR (Gemini Nano Banana) auto-extraction of name/dob/doc_number from ID + cross-check against account data · Transactional level-based limits enforcement (unverified $500/order, basic $5k/order) · Auto-promotion to VIP role · Push notifications on status changes.

- BUG FIX iter55.15 — Aportes propios ausentes del Registro de Transacciones (Jul 5 2026): operator-reported on production. Los ajustes manuales de capital (`company_fund_adjustments`, tanto inflow como outflow) y los retiros del fondo empresa (`company_withdrawals` con estado approved/paid) no aparecían en `/admin/transactions` a pesar de estar correctamente reflejados en `/admin/company-funds`.
  - **Root cause**: `services/transactions.build_transactions()` solo consultaba 3 fuentes (orders aprobadas, withdrawals VIP, order payouts). Las colecciones de capital corporativo estaban desconectadas del registro contable unificado.
  - **Fix**: 2 nuevos fetchers `_fetch_company_adjustments()` + `_fetch_company_withdrawals()` gated por `user_id is None` (los eventos company-level nunca aparecen en `/me/transactions`). Nuevos mappers `_company_adjustment_to_transaction()` + `_company_withdrawal_to_salida()` con `ref_type` diferenciado.
  - **Tests**: `test_iter55_15_company_adjustments_in_register.py` con 6 casos (bug reproducer + inflows + outflows + company_withdrawals + status filtering + regresión `/me/transactions` scope).
  - Verificado con curl E2E en preview: aporte planted +10M CUPT → aparece en `/admin/transactions?currency=CUPT` con totals in=+10M, count=1.
  - **Status**: fix en preview. El usuario necesita re-desplegar a producción (`Deploy` button) para que llegue a `p2p.resiliencebrothers.com`.

- Granular per-Staff Permissions — RBAC-lite (iter55.16, Jul 8 2026): operator reported that when trying to designate specific functions to different staff members, only `allowed_currencies` could be scoped — every "Staff Member" (role=employee) had blanket access to every staff page. Not scalable when the operator has 5+ employees with focused roles.
  - **Design constraint (from user)**: 12 capability codes, `allowed_permissions=[]` (empty/unset) means "full staff access" for backward compatibility so existing employees keep working with zero admin action.
  - **New `services/permissions.py`**: `PERMISSION_CATALOG` (12 codes: orders, withdrawals, kyc, appeals, products, rates, currencies, users, company_funds, blocked_contacts, transactions, quick_view) + `_has_permission(user, code)` pure predicate + async `require_permission(request, code)` HTTP gate + `sanitize_permissions()` to drop unknown codes.
  - **Semantics**: admin → always passes; employee with empty/unset list → passes (backward compat); employee with non-empty list → only if code is in list, else 403 with a message naming the missing permission (e.g. "No tienes el permiso 'Verificación KYC' asignado. Contacta al admin.").
  - **Endpoints gated (30+)**: KYC (6), Appeals (2), Withdrawals (2), Company Funds (5), Orders (2), Redemptions (2), Transactions register (3), Queue/Quick-view (2), Currencies (3), Rates (3), Products (3), Users list+edit (2). Legacy asserts `_assert_can_manage_blocklist`, `_assert_can_review_appeals`, `_assert_can_manage_company_funds` upgraded to honor the new permission list (new supersedes legacy booleans).
  - **New endpoint**: `GET /api/admin/permissions/catalog` — staff-only, returns 12 items with `{code, label, description}` for the frontend selector.
  - **`PUT /api/admin/users/{id}`** now accepts `allowed_permissions`. Only admins can grant/revoke; employees calling with the field get 403. Unknown codes silently sanitized. Requires TOTP step-up (unchanged).
  - **Frontend `AdminUsers`**: new "Funciones autorizadas" column between "Monedas autorizadas" and "Teléfono". `PermissionMultiSelect.jsx` (Popover + 12 Checkboxes with label+description) mirrors the visual pattern of `CurrencyMultiSelect`. Non-admin viewers see read-only count, no editor. Non-employees show "— n/a —".
  - **Frontend sidebar (`AdminPanel.jsx`)**: filters items by `hasPerm(code)` = admin OR empty perms OR code in perms. Employee with `["kyc"]` now sees only Resumen + KYC. Empty perms → all 14 staff items visible.
  - **UX polish**: the misleading yellow "ADMIN" badge next to highlighted sidebar items was replaced by a small yellow dot — no longer suggests admin-only when the item is actually staff-accessible.
  - **Verified GREEN by testing agent (iter53 report)**: **16/16 new tests + 76/77 regression** (1 pre-existing skip). Zero regressions. OpenAPI at 107 paths (+1 for catalog endpoint).
  - **Status**: fix en preview. User needs to redeploy to push to production. Once deployed, admin can assign focused responsibilities in `/admin/users` → column "Funciones autorizadas" → checkbox picker per employee.

- Audit Log Enriched with Permissions Snapshot (iter55.16b, Jul 8 2026): follow-up to iter55.16. Every entry in `audit_log` collection now includes an **immutable snapshot** of the actor's permissions at the moment of the action.
  - **New fields on each entry**: `actor_permissions` (raw list from `user.allowed_permissions` at action time) and `actor_permissions_effective` (human-readable: `"all"` for admins, `"all_staff_default"` for employees with empty list, or the raw list for scoped employees).
  - **Immutability**: the snapshot is captured at insert time — later revoking a permission does NOT rewrite historical rows. Answers forensic question "what could this employee actually do at that moment?" 6 months after the fact.
  - **Central helper `audit_log.log_action`** updated once → all 15+ call-sites across `orders.py`, `admin.py`, `admin_users.py`, `admin_company_funds.py`, `blocklist.py`, `market.py`, `withdrawals.py` etc. now auto-enrich with zero code changes at the call site.
  - **Frontend `/admin/audit`**: new column "Permisos al momento" between Rol and Acción. `PermissionsCell` component with 3 badge states: emerald "Admin · sin límite" · neutral "Staff · sin restricción" · yellow "N permisos" (with hover tooltip listing codes).
  - **CSV export** at `/admin/audit/export.csv` includes a new `actor_permissions_effective` column (encoded as `;`-joined list or the effective label).
  - **Backward compat with pre-existing rows**: old audit rows without the new fields render as "0 permisos" (yellow) — visually distinct from post-fix rows so ops can see the boundary at a glance.
  - **Verified GREEN by tests (iter55.16b)**: **5/5 new tests** covering admin snapshot, employee default, scoped employee, historical immutability, CSV column. **74/74 regression** (kyc + appeals + transactions + permissions + company adjustments). Zero regressions.
  - **Status**: fix en preview. Deploy pending.

- Monthly Audit Report — PDF export + Email delivery (iter55.17, Jul 8 2026): follow-up to iter55.16b. Owner-grade monthly report so compliance / archival can be done from a single click.
  - **New pure service `services/audit_report.py`**: `month_range_iso(year, month)` (ISO boundaries with December year rollover + leap-year February), `month_label` (Spanish month names), `compute_monthly_kpis(entries)` (executive summary aggregation: total actions, distinct actors, top 5 actors, actions grouped by family (order/rate/user/settings/kyc/appeal/withdrawal/company/vip/blocklist), anti-fraud signals count from a curated action set, permission-scope distribution admin/staff*/scoped/legacy), `compute_integrity_hash(entries, period)` (SHA-256 over the canonical projection `id · timestamp · actor · action · entity` — order-independent, sensitive to any row edit/insert/delete, tamper-evident).
  - **New PDF generator `audit_pdf_monthly.py`**: professional landscape report matching the branding of `audit_pdf.py`. Layout: (1) KPI strip with 4 cards (actions total · distinct actors · anti-fraud signals · role distribution), (2) Table "Acciones por categoría" with % of month, (3) Table "Top actores del período", (4) Table "Señales anti-fraude", (5) PageBreak → detailed chronological table of every action (with "Perms" column collapsing effective scope into `admin`/`staff*`/`N perm.`), (6) Firma de integridad SHA-256 footer.
  - **New endpoints** in `routes/admin_audit.py`:
    * `GET /admin/audit/monthly.summary?year=YYYY&month=MM` — returns `{period_label, period_slug, integrity_hash, kpis, row_count}` for live preview (used by the UI).
    * `GET /admin/audit/monthly.pdf?year=YYYY&month=MM` — streams `application/pdf` with `Content-Disposition: attachment; filename="auditoria-YYYY-MM.pdf"`. Admin-only (employee → 403). Invalid year/month → 400.
    * `POST /admin/audit/monthly/send-email` — TOTP step-up required; sends the PDF via Resend to the ops mailbox from `settings.global.ops_notifications_email` if set, otherwise fans out to all admins. Reuses `admin_alerts.resolve_admin_email_recipients`.
  - **New email template `email_service.notify_monthly_audit`**: dark branded HTML with KPI table, top 3 actors, integrity hash box + PDF attachment named `auditoria-<period-slug>.pdf`.
  - **Frontend `/admin/audit`**: new component `pages/admin/audit/MonthlyAuditReport.jsx` (~200 lines, own sub-directory). Selector Mes + Año (defaults to previous calendar month), live KPI preview (Período · Acciones · Actores · Anti-fraude in red when >0), truncated hash preview with full value in `title`. Two buttons: `audit-monthly-download` (direct blob download) and `audit-monthly-email` (opens `TotpPromptDialog` → POST). Uses the existing `TotpPromptDialog` component with `handleTotpError` mapping.
  - **New testids**: `audit-monthly-card`, `audit-monthly-month`, `audit-monthly-year`, `audit-monthly-download`, `audit-monthly-email`, `audit-monthly-summary`, `audit-monthly-count`, `audit-monthly-hash`.
  - **Verified GREEN by tests (iter55.17)**: **26/26 new tests** in `test_iter55_17_monthly_audit_pdf.py` covering (a) `month_range_iso` boundaries incl December + leap year + invalid inputs, (b) KPI aggregation (totals, group ordering, top actors desc, anti-fraud detection, permission scope buckets, empty input), (c) SHA-256 hash determinism + sensitivity + period-scoping, (d) PDF magic bytes for filled + empty months, (e) HTTP admin/employee ACLs for summary + PDF + email endpoints, (f) 400 for invalid month/year, (g) TOTP step-up gate + happy path. Plus **27/27 regression** on iter55.15/16/16b (company adjustments + permissions + audit snapshot). Frontend smoke test: card rendered with live preview + SHA-256 truncated hash + working month/year selectors.
  - **Status**: fix en preview. User needs to redeploy to push to production. Once deployed, admin can head to `/admin/audit` → choose month/year → download or email the monthly compliance PDF in one click.

- Delete notifications (iter55.18, Jul 10 2026): operator reported "no existe la opción para ir eliminando las notificaciones — se van acumulando aunque estén leídas". Fixed by adding both individual and bulk deletion, without breaking existing endpoints.
  - **Backend `routes/notifications.py`**: two new owner-scoped endpoints:
    * `DELETE /notifications/{notification_id}` — deletes one row; idempotent (returns 200 `already_gone=True` if the id is gone or belongs to someone else — no information leak, no 404 storm).
    * `DELETE /notifications/read` — bulk-deletes every row for the current user where `read=True`. Unread items are preserved. Route registered BEFORE the `{notification_id}` route to avoid FastAPI path-parameter collision.
  - **Frontend `hooks/useNotifications.js`**: 2 new methods `deleteOne(id)` + `deleteAllRead()` with optimistic UI (remove row instantly, roll back on failure via saved snapshot). Both trigger `refreshCount()` so the sidebar badge updates without waiting for the next 30s poll.
  - **Frontend `components/NotificationBell.jsx`**: per-row `✕` button appears on hover (opacity-0 → group-hover:opacity-100, red on hover) with `data-testid="notification-delete-{id}"`. Header gains a second action button "🗑 Borrar leídas" (`data-testid="delete-all-read-btn"`) rendered only when at least one read row exists; sits alongside the pre-existing "Marcar todo".
  - **New testids**: `notification-delete-{id}`, `delete-all-read-btn`.
  - **Verified GREEN by tests (iter55.18)**: **7/7 new tests** in `test_iter55_18_delete_notifications.py` (owner-happy-path, cross-owner idempotent noop, unknown-id idempotent, bulk read-only removes read rows, bulk delete only affects current user, unauth 401/403, unread-count drops after delete). Frontend E2E smoke on `/admin`: 2 planted notifs → "Borrar leídas" drops the read one, individual `✕` drops the last → empty state renders. Zero regression.
  - **Status**: fix en preview. User needs to redeploy to push to production (`https://p2p.resiliencebrothers.com`).

- Withdrawal method matches currency + Cash-mode hint (iter55.19, Jul 10 2026): operator reported that a VIP with USD-cash balance was seeing "Transferencia bancaria" as the default withdrawal method — the dropdown was hardcoded to 3 static options ignoring the currency's `delivery_methods`. Additionally, cash retrievals needed the receiver's ID/name/phone but the free-form details field gave no guidance.
  - **Frontend `pages/dashboard/VipView.jsx`**:
    * New state `allowedMethods` fed by `GET /api/currencies/{code}/delivery-methods` (backend source of truth from iter43) — refreshes whenever `currency` changes, cancellation-guarded so a fast currency flip cannot clobber the state.
    * New `useMemo` `withdrawalMethodOptions` that filters the dropdown to only the methods valid for the currency. Falls back to the historical 3-option list on network error so a transient failure doesn't leave an empty dropdown.
    * New `useEffect` auto-corrects the selected `method` when the option list narrows (e.g. user switches from CUP to CUPE → previously-selected transfer becomes cash automatically).
    * Details textarea gains a **method-aware placeholder**: cash → "Nombre y apellidos, número de ID/carné y teléfono celular...", crypto → "Dirección de la wallet (TRC20 / BEP20 / ERC20) y red", transfer → "Banco, número de cuenta y titular".
    * When method=cash, a new yellow hint (`data-testid="withdraw-cash-hint"`) makes the requirement explicit and marks the details field as required.
  - **Backend `routes/orders.py::create_withdrawal`**: added `await _assert_delivery_method_matches_currency(currency, method)` — reuses the exact same guard as `create_order`, so both flows stay in sync. Cash-only currencies now reject transfer withdrawals with a Spanish 400 detail ("Para recibir X (fiat) solo se permite: efectivo. La opción 'transferencia bancaria' no aplica.").
  - **Verified GREEN by tests (iter55.19)**: **6/6 new tests** in `test_iter55_19_withdrawal_method_matches_currency.py` covering (a) explicit `delivery_methods=["cash"]` rejects transfer, (b) same currency accepts cash happy-path, (c) heuristic-inferred cash-only currency ("USD Efectivo") rejects transfer, (d) crypto currency accepts crypto + rejects transfer, (e) `GET /currencies/{code}/delivery-methods` returns the expected list, (f) default transfer-friendly USD still works. Frontend E2E smoke: CUP → dropdown shows 2 options (transfer + cash), selecting Efectivo displays the ID/name/phone hint + updates placeholder.

- Cash withdrawal details required (iter55.19b, Jul 10 2026): follow-up right after iter55.19. Operator asked to enforce that cash withdrawals actually include the receiver's full name, ID and phone (not just a hint). Simple length-based enforcement — enough to catch empty/generic details without being a data-model overreach.
  - **Frontend `pages/dashboard/VipView.jsx::submit`**: added a pre-flight check — when `method === "cash"` and `details.trim().length < 20`, block the submit with a Spanish toast: *"Para retiros en efectivo incluye nombre y apellidos, número de ID/carné y teléfono celular del receptor (mínimo 20 caracteres)."*
  - **Backend `routes/orders.py::create_withdrawal`**: mirror validation for defense in depth (an API-direct caller can't bypass the UI). Same Spanish HTTP-400 message. Only fires when `method == "cash"`; transfer/crypto flows are untouched.
  - **Verified GREEN by tests (iter55.19b)**: **3/3 additional tests** appended to `test_iter55_19_withdrawal_method_matches_currency.py` (cash rejected with 4-char details, cash accepted with full "Juan Pérez · ID 87050112345 · +5355551234", transfer flow untouched by the new rule). Total: **9/9** in this iter. **20/20 regression** on `test_order_payout_evidence.py` + `test_email_and_closing.py`.
  - **Status**: fix en preview. User needs to redeploy to push to production.

- BingX-style crypto network mismatch detection (iter55.19c, Jul 10 2026): operator saw BingX-style "No coinciden" badge on USDT withdrawal screen and asked to replicate it. Prevents irrecoverable fund loss when a client pastes a TRC20 address but selects BEP20 (or vice versa) — the address family (Tron vs EVM) is validated live in the UI and enforced hard at the backend.
  - **New pure service `services/crypto_networks.py`**: 2 supported networks (TRC20, BEP20 — cover 95% of LatAm/Cuba USDT operations per operator decision), regex per family (`^T[1-9A-HJ-NP-Za-km-z]{33}$` for Tron base58, `^0x[0-9a-fA-F]{40}$` for EVM), `detect_family(addr)` → `tron|evm|unknown`, `is_address_valid_for_network(addr, net)` predicate, `mismatch_reason(addr, net)` returning a Spanish-friendly diagnosis ("La dirección parece de la red EVM (BSC/ETH/Polygon…), pero seleccionaste Tron (TRC20)..."). Explicit design note in the module docstring: BEP20/ERC20/Polygon/Arbitrum/Optimism all share the EVM `0x...` format so we can only distinguish families — mirrors what BingX itself does.
  - **New fields on `WithdrawalRequest` + `WithdrawalCreate`** in `routes/orders.py`: `crypto_network: str = ""` (persisted, empty for non-crypto) / `Optional[str]` (ingest). `create_withdrawal` now:
    * Rejects with 400 when `method == "crypto"` and no supported network is declared.
    * Rejects with structured 400 `{code: "CRYPTO_NETWORK_MISMATCH", message: "...", network: "BEP20"}` when the address does not match the family expected by the declared network.
    * Persists `crypto_network` on approval so admin panel + audit log always know which chain to release on.
  - **Frontend `pages/dashboard/VipView.jsx`**:
    * Client-side twin of the backend predicates: `TRC20_RE`, `EVM_RE`, `detectAddressFamily`, `validateCryptoAddress`. Kept in sync intentionally with `services/crypto_networks.py` (only 2 networks — trivial to maintain).
    * New state `cryptoNetwork` (default `TRC20`, the dominant network for USDT in LatAm).
    * New conditional block "Red on-chain *" (visible only when `method === "crypto"`, `data-testid="crypto-network-block"`) with a `<Select>` (`data-testid="withdraw-crypto-network"`) showing "Tron (TRC20)" / "BSC (BEP20)".
    * Details placeholder becomes network-specific (`"T + 33 caracteres alfanuméricos (ej. TJRabc123...)"` or `"0x + 40 caracteres hexadecimales (ej. 0xAbCdEf...)"`).
    * Live badges below the address input:
      - `crypto-address-match-ok`: green `✓ Dirección compatible con {network label}` when address matches.
      - `crypto-address-mismatch`: red `⚠ No coincide con {network label}. Revisa la red seleccionada o pega otra dirección — enviar por la red incorrecta puede perder los fondos permanentemente.` when it doesn't.
    * Hard block in `submit()`: if `method === "crypto"` and the address doesn't match the network, an error toast fires and no HTTP request is issued. Consistent with the "bloqueo duro" operator choice.
    * Retiro history now displays `{amount} {currency} · {method}{crypto_network ? " · " + crypto_network : ""}` so the client remembers which chain was used per past withdrawal.
  - **Verified GREEN by tests (iter55.19c)**: **11/11 new tests** in `test_iter55_19c_crypto_network_validation.py` covering pure predicates (supported networks list, family detection with real TRC20/EVM/garbage, cross-family mismatches, unsupported network rejection, mismatch-reason wording) + HTTP endpoint enforcement (missing network → 400, unsupported network → 400, TRC20 addr on BEP20 → structured 400 with `code: CRYPTO_NETWORK_MISMATCH`, BEP20 addr on TRC20 → 400, matching TRC20 → 200 + persisted network, matching BEP20 → 200 + persisted, transfer flow ignores stray `crypto_network` field). **Total 40/40 regression** across `iter55.19 + 19c + payout_evidence + email_and_closing`.
  - **Frontend E2E smoke**: on USDT wallet — pasting BEP20 address while TRC20 selected → red mismatch badge; switching to BEP20 network → green OK badge; pasting TRC20 address while BEP20 selected → red mismatch badge again. Exactly the BingX behavior the operator saw in the screenshot.
  - **Status**: fix en preview. User needs to redeploy to push to production. Once deployed, crypto withdrawals are safer by design — no more mistaken chain sends.

- Crypto network badge in admin views (iter55.19c-followup, Jul 10 2026): follow-up right after iter55.19c. Now that clients declare which chain their crypto withdrawal targets, staff needs to see it before approving so they release on the correct chain.
  - **`AdminWithdrawals.jsx`**: method column now appends a yellow `TRC20` / `BEP20` badge next to `crypto`. Modal detail gained a dedicated "Red on-chain" row with `data-testid="withdrawal-modal-network"`.
  - **`AdminQueue.jsx`**: the withdrawals-pending queue table shows the same compact badge so a staff scanning "Mi Cola" knows which chain to release before opening.
  - **`services/transactions._withdrawal_to_salida`**: `TransactionItem` now includes `crypto_network`. Flows through the transactions registry API + PDF/CSV exports (backward-compatible: empty string for pre-19c rows).
  - **`TransactionDetailModal.jsx`**: "Método" cell surfaces the badge (same visual as AdminWithdrawals) so an admin auditing the ledger sees the chain at a glance.
  - **Testids added**: `withdrawal-network-{id}`, `withdrawal-modal-network`, `tx-detail-crypto-network`.
  - **Verified GREEN**: 11/11 iter55.19c + 9/9 iter55.19 + 35/35 (transactions_registry + company_adjustments) = **55/55** all pass. Frontend smoke: planted a TRC20 pending withdrawal → both the row badge and the modal "Red on-chain: TRC20" render correctly on `/admin/withdrawals`.
  - **Status**: fix en preview. User needs to redeploy to push to production.

- Copy-to-clipboard button on wallet/details (iter55.19d, Jul 10 2026): operator asked for a copy button next to the client's wallet address in the withdrawal management modal — currently they had to manually highlight the text to copy, error-prone especially on mobile.
  - **New reusable component `components/CopyableText.jsx`**: renders `value` as monospace text with an inline icon-only copy button. Handles `navigator.clipboard.writeText` in secure contexts + falls back to a hidden textarea + `document.execCommand("copy")` for insecure/legacy contexts. Post-click swaps the copy icon for a green checkmark for 1.5s + fires a sonner toast (`"Wallet copiada"` / `"Datos copiados"` / configurable). Testable via `testid` prop.
  - **`AdminWithdrawals.jsx` modal**: replaced the plain `Detalles:` and `Beneficiario:` rows with `<CopyableText>` blocks. Label swaps between `"Wallet:"` (for crypto) and `"Detalles:"` (for transfer/cash). Beneficiary field is non-monospace (name, not wallet) — one prop away.
  - **`transactions/TransactionDetailModal.jsx`**: the "Datos del envío / Datos del beneficiario" block now wraps the delivery details in `<CopyableText>` so admins auditing the ledger can copy an address in one click.
  - **Testids added**: `withdrawal-copy-details`, `withdrawal-copy-beneficiary`, `tx-copy-delivery-details`.
  - **Note**: `AdminOrders.jsx` already had its own inline `CopyBtn` with the same UX (iter earlier), left untouched to avoid unnecessary refactor.
  - **Verified E2E in preview**: planted a pending TRC20 withdrawal → opened modal → clicked copy on the wallet → clipboard verified to hold `TJRabRWQdrJc7iCPFy4gnPCJcXbc17ncCk` exactly + green checkmark icon appears + sonner toast "Wallet copiada" surfaces. Beneficiary copy button also confirmed rendering.
  - **Status**: fix en preview. User needs to redeploy to push to production.

- Crypto payout: only tx hash, no screenshot required (iter55.19e, Jul 10 2026): operator asked to remove the "sube captura" UX burden for crypto payouts — the tx hash on-chain is the source of truth (the client can verify it on the explorer), so requiring a screenshot on top was noise.
  - **Backend was already correct** (iter14): for `crypto` the guard is `existing_hash OR existing_proof`, so hash alone was always accepted. No backend changes were needed.
  - **Frontend `AdminWithdrawals.jsx` modal**: replaced the mixed "hash + captura opcional" block. For `method === "crypto"` now shows ONLY the hash input (`payout-tx-hash`) with a network-aware placeholder ("TRC20 · 64 caracteres hex..." or "BEP20 · 0x + 64 hex...") and the hint *"Con el hash es suficiente — no hace falta subir captura."*. The file-upload input is omitted entirely on this branch. Transfer/cash paths untouched.
  - **Frontend `AdminOrders.jsx` modal**: same treatment. When `delivery_method === "crypto"`, only the `order-payout-tx-hash` input is rendered; the file upload label + preview live under an `else if transfer` branch. Cash + accumulate paths untouched.
  - **Frontend `dashboard/OrdersView.jsx`**: the "Comprobante del pago realizado a ti" block on the client-side detail modal now wraps the hash in `<CopyableText>` so the client copies it in one click (before it was a plain green span the client had to highlight manually).
  - **Verified GREEN**: 27/27 combined tests (payout_evidence + iter55.19 + iter55.19c). Frontend E2E smoke on `/admin/withdrawals`: planted a TRC20 pending withdrawal → opened modal → `payout-tx-hash` visible (count=1), `payout-proof-input` NOT rendered (count=0), placeholder shows "TRC20 · 64 caracteres hex...", hint copy visible. Exactly the operator's request.
  - **Status**: fix en preview. User needs to redeploy to push to production.

- Block-explorer link on crypto payouts (iter55.19f, Jul 10 2026): follow-up right after iter55.19e. Now that crypto payouts are hash-only (no screenshot), a one-click "Verify on explorer" button becomes the natural confidence booster — both for the client and for the admin auditing the ledger.
  - **New service `services/blockExplorers.js`**: pure `buildExplorerUrl(network, txHash)` → returns the canonical explorer URL for TRC20 (Tronscan), BEP20 (BscScan), ERC20 (Etherscan), POLYGON (Polygonscan), SOLANA (Solscan), BTC (Mempool). Returns `null` for missing / unsupported inputs so callers render nothing gracefully. Case-insensitive network + auto-trim hash. Companion `explorerLabel(network)` returns friendly names for the button copy.
  - **New reusable component `components/ExplorerLink.jsx`**: yellow pill button with `<ExternalLink>` icon + "Ver en {Explorer}" label. Auto-hides if `buildExplorerUrl` returns `null` (empty hash or unsupported network). Small (`sm`) / normal size variants. `target="_blank" rel="noopener noreferrer"` for security.
  - **Backend `services/transactions.py`**: `_withdrawal_to_salida` + `_order_payout_to_salida` now include `payout_tx_hash`. Bonus: withdrawal now also surfaces `payout_proof_image` (was empty before) so the ledger modal shows the transfer receipt if the operator uploaded one.
  - **Frontend touchpoints (all 4 places the hash surfaces)**:
    1. `pages/dashboard/OrdersView.jsx` (client order detail modal): explorer link next to the hash + copy button. Network inferred via `extractCryptoNetwork(delivery_details, delivery_method)`.
    2. `pages/dashboard/VipView.jsx` (client withdrawal history): hash now uses `<CopyableText>` + explorer link. Network read from the stored `crypto_network` field on the withdrawal.
    3. `pages/admin/AdminWithdrawals.jsx` (admin management modal): explorer link surfaces right under the hash input as soon as the stored `payout_tx_hash` exists — the admin verifies mid-approval that the tx actually landed. Helper caption: "verifica que la tx llegó a la wallet del cliente".
    4. `pages/admin/transactions/TransactionDetailModal.jsx` (admin ledger detail): new green-bordered "Hash on-chain del pago" block with copyable hash + explorer link. Network resolved from `crypto_network` (withdrawal) or via `extractCryptoNetwork` (order).
  - **New testids**: `my-order-explorer-link`, `payout-explorer-{withdrawal-id}`, `admin-withdrawal-explorer-link`, `tx-payout-explorer-link`, `tx-payout-hash-copy`.
  - **New unit tests `services/__tests__/blockExplorers.test.js`**: 9 pure-function cases — 6 URL builders (TRC20, BEP20, ERC20, Polygon, case-insensitive), null-safety on empty/unsupported inputs, whitespace trim, label mapping. Jest-style — runs with `yarn test`.
  - **Backend regression**: 53/53 tests pass across `test_order_payout_evidence.py + iter55.19c + transactions_registry + company_adjustments_in_register`. The new `payout_tx_hash` field additions do not break any existing shape (fields are additive strings, defaulting to empty).
  - **Frontend E2E smoke**: planted a paid TRC20 withdrawal with a mock 64-char hash → opened `/admin/withdrawals` modal → verified `admin-withdrawal-explorer-link` renders with `href=https://tronscan.org/#/transaction/{hash}` exactly. Button label "VER EN TRONSCAN" as expected.
  - **Status**: fix en preview. User needs to redeploy to push to production.

- Order-completed notification with explorer link + Mi Perfil section (iter55.19g + 55.20, Jul 10 2026): two features shipped in the same iteration since they compose the client-side "trust & control" cluster.

  **Feature A — Notification-to-explorer link (iter55.19g)**
  - **`services/orders_helpers.py::create_inapp_order_notification`**: when `new_status == "completed"` and `method == "crypto"` and a `payout_tx_hash` exists, the notification `data` payload now carries `payout_tx_hash`, `crypto_network` (detected via the same regex/keyword logic as the frontend) and a ready-to-render `explorer_url` (Tronscan/BscScan/Etherscan/Polygonscan). Message copy also becomes network-aware ("Verifica la transacción en TRC20").
  - **`components/NotificationBell.jsx`**: `<NotificationRow>` now renders a yellow `↗ Verificar en {Explorer}` inline link when `data.explorer_url` is present. Click stops propagation so the user can jump to the explorer without also marking the notification as read. Testid: `notification-explorer-{id}`.
  - **Tests**: 3 new pytest cases (`test_iter55_19g_notification_explorer_link.py`) — TRC20 order emits Tronscan URL, BEP20 order emits BscScan URL, order without hash omits `explorer_url` entirely.

  **Feature B — "Mi Perfil" section (iter55.20)**
  - **New backend router `routes/profile.py`** (~10 endpoints) — client-facing view + change flows:
    * `GET /profile/me` — full snapshot: name, email, phone (+verified), country, role, created_at, twofa_enabled, kyc_status + any pending change requests (masked).
    * `POST /profile/email/request-change` — 2FA-guarded; generates a hashed 6-digit OTP (15-min TTL), emails it to the NEW address, and sends a "someone tried to change your email" alert to the OLD address. Duplicate email + same-as-current + expired-code all return 400.
    * `POST /profile/email/confirm-change` — validates the code, applies the change, sends a "email actualizado" confirmation to both inboxes, logs an audit entry.
    * `POST /profile/phone/request-change` — 2FA-guarded; stores `pending_phone_change` on the user doc + fan-out notification to admin + staff with `can_manage_blocklist`. Client sees "Pendiente revisión admin" state.
    * `DELETE /profile/phone/pending` — client can cancel their own pending phone request.
    * `POST /profile/country/change` — instant, no 2FA needed. If the client had an APPROVED KYC, the KYC row is flipped to `pending_review` with `reset_reason=country_change:{old}→{new}` so operators re-verify.
    * `GET /admin/profile-change-requests` — admin lists pending phone changes.
    * `POST /admin/profile-change-requests/{uid}/approve-phone` — admin approve (TOTP step-up) — applies phone + marks `phone_verified=true` + notifies client.
    * `POST /admin/profile-change-requests/{uid}/reject-phone` — admin reject with mandatory reason + client notif + audit entry.
  - **New email templates in `email_service.py`**: `notify_email_change_code` (branded card with the 6-digit code), `notify_email_change_alert` (red-bordered security notice to the old inbox), `notify_email_change_success` (green-bordered post-change confirmation for both inboxes).
  - **New frontend page `pages/dashboard/ProfileView.jsx`** (~500 lines but each dialog is a focused sub-component) with:
    * Personal data card — Name/Email/Phone/Country/Created-at rows with a `<Pencil>` "Cambiar" button per editable field. Pending changes rendered inline in yellow.
    * Verification card — status badge + link to `/dashboard/kyc`.
    * Security card — 2FA status badge + link to `/dashboard/security`.
    * Three dialogs (`EmailChangeDialog`, `PhoneChangeDialog`, `CountryChangeDialog`) — each is 2FA-gated where appropriate, uses the existing `handleTotpError` helper, and shows destination masking (`sent_to_masked` from backend) so the user sees a sanitized preview of the new value before confirming.
  - **Sidebar `Dashboard.jsx`**: new nav item "Mi Perfil" (icon `UserCircle`, testid `nav-profile`) between "Mi Historial" and "Verificación". Route wired at `/dashboard/profile`.
  - **Testids added**: `profile-view`, `profile-personal/kyc/security`, `profile-email/phone/country-row(-edit)`, `email-change-dialog/-new-input/-totp-input/-code-input/-send-btn/-confirm-btn`, `phone-change-dialog/-new-input/-totp-input/-submit-btn/-cancel-pending-btn`, `country-change-dialog/-new-input/-submit-btn`, `notification-explorer-{id}`.
  - **Tests**: 14 new pytest cases (`test_iter55_20_profile_change.py`) — profile shape + email happy path + wrong code + already-taken + same-as-current + phone requires 2FA + phone creates admin-review + country change resets approved KYC + country change without KYC + admin lists pending + admin approve + admin reject + client cancels own pending.
  - **Regression**: 70/70 combined tests pass (iter55.17 + 18 + 19 + 19c + 19g + 20).
  - **Frontend E2E smoke**: `/dashboard/profile` rendered with all 3 cards, all edit buttons present, sidebar highlights "Mi Perfil" correctly.
  - **Status**: fix en preview. User needs to redeploy to push to production.

- Admin panel for pending profile changes + delegated to staff (iter55.20b, Jul 10 2026): follow-up right after iter55.20. Operator wanted the phone-change queue accessible from the admin UI AND delegable to designated staff members (same RBAC-lite pattern as KYC).
  - **New RBAC permission `profile_changes`**: added to `services/permissions.py::PERMISSION_CATALOG` — bumps the catalog from 12 → 13 entries. Label "Cambios de datos", description "Aprobar cambios de teléfono/email solicitados por clientes". Admin gets it implicitly (`role == "admin"`); staff needs it in their `allowed_permissions` array (edited from `/admin/users`).
  - **Backend `routes/profile.py`**: replaced 3 uses of `require_admin` with `require_permission(request, "profile_changes")` on the endpoints:
    * `GET /admin/profile-change-requests`
    * `POST /admin/profile-change-requests/{uid}/approve-phone`
    * `POST /admin/profile-change-requests/{uid}/reject-phone`
  - **New frontend page `pages/admin/AdminProfileChangeRequests.jsx`** (~230 lines): table with cliente + país + tel actual + tel nuevo (yellow highlight) + fecha + `[Aprobar]` (green) / `[Rechazar]` (red) per row. Approve action opens `TotpPromptDialog`. Reject flow: first collects the mandatory reason via a modal, then chains to `TotpPromptDialog` for 2FA. Empty state renders friendly "No hay solicitudes pendientes." Refresh button in header.
  - **Sidebar `AdminPanel.jsx`**: new entry "Cambios de datos" (icon `UserCog`, testid `admin-nav-profile-changes`) between "KYC" and "Fondo Empresa", gated by `hasPerm("profile_changes")` — appears for admins + any employee with the permission granted. Route wired at `/admin/profile-change-requests`.
  - **New testids**: `admin-profile-change-requests`, `profile-changes-refresh`, `profile-changes-loading/empty`, `profile-change-row-{uid}`, `profile-change-approve-{uid}`, `profile-change-reject-{uid}`, `profile-change-reject-dialog/-reason/-continue`, `admin-nav-profile-changes`.
  - **Tests**: 3 new pytest cases appended to `test_iter55_20_profile_change.py` (staff with empty perms = permissive default can list, staff with scoped perms *without* profile_changes → 403, staff with profile_changes explicit → can approve). Total **17/17** in the file. Regression on `test_iter55_16_permissions.py` catalog test updated to expect 13 items instead of 12. **61/61 combined pass** (iter55.16 + 16b + 20 + 19g + 19 + 19c).
  - **Frontend E2E smoke**: planted a pending phone change → opened `/admin/profile-change-requests` → panel renders row with VIP data + Aprobar/Rechazar buttons visible; sidebar highlights "Cambios de datos".
  - **Status**: fix en preview. User needs to redeploy to push to production.

- Email fan-out on phone change approval / rejection (iter55.20c, Jul 10 2026): follow-up right after iter55.20b. Client now receives an email (not only the in-app notification) whenever staff decides on their phone-change request — so the message doesn't get missed if the client isn't logged in.
  - **New email templates in `email_service.py`**:
    * `notify_phone_change_approved(to, name, new_phone_masked)` — green-bordered card confirming the number is verified, includes a security nudge ("si no reconoces este cambio, contacta soporte").
    * `notify_phone_change_rejected(to, name, new_phone_masked, reason)` — red-bordered card with the mandatory rejection reason quoted verbatim + hint on how to retry from the profile page.
  - **Endpoints in `routes/profile.py`**: `approve_phone_change` and `reject_phone_change` now call the corresponding email helper right after inserting the in-app notification (best-effort, doesn't block on failure).
  - **Tests**: 3 new pytest cases in `test_iter55_20_profile_change.py` — endpoint side-effect (approval still applies phone + Mongo state matches), pure unit test on `notify_phone_change_approved` (verifies `_send` is invoked with masked phone in HTML + Spanish subject), pure unit test on `notify_phone_change_rejected` (verifies reason appears verbatim in body). Total in file: **20/20**. **46/46 combined pass** (iter55.20 + 16 + 19g + 18).
  - **Status**: fix en preview. User needs to redeploy to push to production.

- Two-in-one: tx_hash format guard + monthly audit auto-send (iter55.19h + 55.21, Jul 10 2026): both were long-standing P2 items on the backlog and share the same crypto/audit compliance theme.

  **Feature A — TX hash format validation vs declared network (iter55.19h)**
  - Extended `services/crypto_networks.py`: new regexes `_TRC20_HASH_RE` (64 hex, no `0x`) and `_EVM_HASH_RE` (`0x` + 64 hex) plus `detect_hash_family`, `is_tx_hash_valid_for_network`, `tx_hash_mismatch_reason`, `TX_HASH_PLACEHOLDERS`.
  - **Withdrawals** `routes/admin_withdrawals.py::_collect_payout_evidence`: when the withdrawal declares `crypto_network` AND method=crypto AND admin pastes `payout_tx_hash`, we validate the hash format against the declared family. Wrong family → structured `HTTPException(400, detail={"code": "TX_HASH_NETWORK_MISMATCH", "message": "...", "network": ...})`. Backward-compat: legacy withdrawals without `crypto_network` skip the guard.
  - **Orders** `routes/admin.py::_collect_order_payout_evidence`: same guard, but network is sniffed from `delivery_details` (looking for `TRC20` / `BEP20` substring — same heuristic used elsewhere).
  - **New reusable frontend module `services/cryptoValidators.js`**: extracted the previously-inline TRC20/EVM address regexes from `VipView.jsx` + added hash regexes + `validateCryptoHash` + `CRYPTO_NETWORKS` config with per-network `addressPlaceholder` / `hashPlaceholder`. Kept `services/blockExplorers.js` untouched (that's the URL builder). `VipView.jsx` refactored to import from the shared module.
  - **`AdminWithdrawals.jsx` modal**: live tx_hash badge under the input — green `✓ Hash compatible con Tron (TRC20)` when the pasted hash matches the family, red `⚠ No coincide con Tron (TRC20). Revisa el hash pegado — probablemente lo copiaste del explorer equivocado.` when it doesn't. Same "no coinciden" visual as the address guard. Testids: `payout-hash-match-ok`, `payout-hash-mismatch`.
  - **Tests**: 9 pytest cases in `test_iter55_19h_tx_hash_network_validation.py` — pure predicates (detect family, matrix cross-family, unknown, unsupported, address-not-mistaken-for-hash), HTTP guard on withdrawals (TRC20 rejects BEP20 hash + BEP20 rejects TRC20 + matching accepts + no-network legacy skips), orders (TRC20 order with wrong hash → 400, matching → 200).
  - Frontend E2E smoke on `/admin/withdrawals`: TRC20 withdrawal → paste BEP20 hash → red mismatch badge; paste TRC20 hash → green OK badge. Exactly the "no coinciden" behavior BingX shows.

  **Feature B — Monthly audit auto-send scheduler (iter55.21)**
  - **`scheduler.py`**: new async function `run_monthly_audit_email(db)` — reuses everything from iter55.17 (`_build_monthly_bundle` semantics via direct calls to `services.audit_report.compute_monthly_kpis` + `compute_integrity_hash` + `audit_pdf_monthly.generate_monthly_audit_pdf`). Fetches audit entries for the previous calendar month (via `services.transactions.fetch_audit_entries`), renders the PDF, then fans out via `email_service.notify_monthly_audit` to `resolve_admin_email_recipients` (respects `ops_notifications_email` override).
  - **Opt-out flag**: `settings.global.auto_send_monthly_audit == False` short-circuits the job silently. Any other value (including missing) = enabled. Owner can disable from Mongo without needing a code deploy.
  - **APScheduler wiring**: new job `monthly_audit_email` with `CronTrigger(day=1, hour=9, minute=15, timezone="UTC")` — 15 min after the existing `monthly_revenue_email` so both arrive as a natural pair. `misfire_grace_time=3600` + `coalesce=True` handle container restarts gracefully.
  - **Tests**: 5 pytest cases in `test_iter55_21_monthly_audit_scheduler.py` — `_previous_month` helper regular case + January year-rollback, `run_monthly_audit_email` calls `notify_monthly_audit` for admin recipients with PDF attachment, opt-out flag short-circuits before any send, scheduler wiring registers the new job with the expected cron string.
  - **Manual trigger already existed**: `POST /admin/audit/monthly/send-email` from iter55.17 lets the operator email any past month on demand (with TOTP step-up).
  - Supervisor logs confirm the job is registered on startup: *"Scheduler started: monthly_revenue_email (day 1 09:00 UTC) + monthly_audit_email (day 1 09:15 UTC) + security_alert_scan (every 5m)"*.

  **Combined regression**: **67/67 tests pass** across iter55.17 + 19 + 19c + 19h + 21 + order_payout_evidence. Zero new lint errors (backend + frontend).
  - **Status**: fix en preview. User needs to redeploy to push to production. Next month's audit report will be delivered automatically to the owner's inbox on day 1 at 09:15 UTC.

- Cleanup post-testing (iter55.26b, Feb 2026) — the testing_agent (iteration_54.json) reported 100% pass + 3 non-blocking code review comments. Addressed 2 of them:
  1. **Dead imports** in `pages/Dashboard.jsx` removed (`IdCard`, `ShieldCheck` — leftover from the iter55.26 sidebar cleanup).
  2. **Extracted shared status constants** to `/app/frontend/src/constants/orderStatus.js` — single source of truth for `ORDER_IN_FLIGHT`, `ORDER_COMPLETED`, `WITHDRAWAL_IN_FLIGHT`, `WITHDRAWAL_COMPLETED`, `ORDER_FILTER_STATUSES`. Both `OverviewView.jsx` and `OrdersView.jsx` now import from this module. This eliminates the exact drift pattern that caused the iter55.25 bug (dashboard counter and orders filter had duplicated sets; a future change to one but not the other would re-introduce a mismatch). All sets are `Object.freeze`d to signal immutability.
  3. **Not addressed**: the `type === "fiat"` speculative safety check on `isCashUsdDelivery` — kept simple since the only cash currency in production is USD, adding the check would gain nothing today.
  - **Regression**: 16/16 tests pass (iter55.22 + 23 + 24 + 25). `yarn lint` still clean.
  - **Deploy status of pending block**: iter55.24 (cash-USD floor) + 55.25 (counter fix) + 55.25b (deep-link pills) + 55.26 (sidebar reorder + Mi Perfil tabs) + 55.26b (this cleanup) are all **verified in preview via testing_agent (8/8 backend + 4/4 frontend E2E)** and waiting for the next production redeploy.



- Nested "Verificación" + "Seguridad" under Mi Perfil (iter55.26, Feb 2026) — owner asked for two UX standard changes:
  1. **Mi Perfil leads the sidebar** — most users click their profile first.
  2. **Verificación (KYC) y Seguridad (2FA) belong inside Mi Perfil** — they're account settings, not top-level destinations.
  - **`pages/Dashboard.jsx`**: reorder — Mi Perfil is now nav item #1. `/dashboard/kyc` and `/dashboard/security` removed from the sidebar entirely.
  - **New shared component** `/app/frontend/src/components/ProfileSectionTabs.jsx` (~60 LOC): renders `/ Mi Perfil` breadcrumb + 3-tab strip (**Datos personales** · **Verificación** · **Seguridad**). Uses `NavLink` with `end` matching so the active tab highlights correctly (`border-b-2` + yellow text). Real react-router nav means bookmarks to `/dashboard/kyc` still land users on that tab with the shared header — zero backward-compat break.
  - **Inserted into 3 pages**: `ProfileView.jsx`, `KYCView.jsx`, `SecuritySettings.jsx`. Each page kept its own `<h1>` + body content unchanged — only the header wrapper was swapped.
  - **Testids added**: `profile-section-tabs`, `profile-tab-datos`, `profile-tab-kyc`, `profile-tab-security`.
  - **Verified E2E** in preview: `/dashboard/profile` renders tabs, sidebar no longer lists Verificación/Seguridad; clicking each tab navigates + swaps content + keeps the tab strip; all 3 URLs remain bookmarkable. `yarn lint` clean.



- Dashboard → Mis Órdenes deep-link filtering (iter55.25b, Feb 2026) — turns the "PENDIENTES"/"COMPLETADAS" counter cards into clickable shortcuts. Owner mental model: "the counter and the table should be in lock-step" → make it 1-click.
  - **`OverviewView.jsx`**: `<StatCard>` gained optional `to` + `testid` props. When `to` is set, the card renders as a `react-router-dom` `<Link>` with hover ring, focus outline, and sub-label suffixed with "· ver →". Wired: Pendientes → `/dashboard/orders?filter=pending`, Completadas → `/dashboard/orders?filter=completed`. Static cards (Saldo, Estatus) render as plain divs (no navigation).
  - **`OrdersView.jsx`**: switched to `useSearchParams()` so the initial filter comes from `?filter=…`. New filter pills row above the table (`data-testid="orders-filter-pills"`) with 4 pills: `Todas / Pendientes / Completadas / Rechazadas`. Each pill uses `aria-pressed` for state and `data-testid="orders-filter-{key}"`. Clicking a pill patches the URL via `setSearchParams(..., {replace:true})` — bookmark/reload safe. Filter map:
    - `pending`   → `{pending, requires_double_approval}`
    - `completed` → `{approved, completed, delivered}` (mirrors the fixed dashboard semantics)
    - `rejected`  → `{rejected}`
  - **Testids added**: `stat-pendientes`, `stat-completadas`, `orders-filter-pills`, `orders-filter-all|pending|completed|rejected`.
  - **Verified E2E**: Playwright clicked the Pendientes card on `/dashboard` → landed on `/dashboard/orders?filter=pending` with the yellow PENDIENTES pill aria-pressed=true and the table showing only pending + doble-aprobación rows. Reload preserves the filter. `yarn lint` clean.



- Dashboard "Pendientes" counter regression fix (iter55.25, 11 Feb 2026) — owner reported: user Obrayan (Cuenta Estándar) had 1 pending order + 1 "Confirmado" (approved) order in Mis Órdenes, but the dashboard showed **PENDIENTES: 2**. iter55.22 introduced the bug by lumping `approved` into a single IN_FLIGHT set for both entity types — but the label/semantics of `approved` differ:
  - `orders.approved` = **"Confirmado"** (staff validated + paid) → **NOT** pending; success state
  - `withdrawals.approved` = **"En progreso"** for cash retiros (approved but coins not handed out yet) → **still** pending
  - The old shared set was double-counting confirmed orders as pending, breaking the invariant "counter = rows-with-Pendiente-badge".
  - **Fix** in `pages/dashboard/OverviewView.jsx`:
    - Split into two per-entity sets: `ORDER_IN_FLIGHT = {pending, requires_double_approval}` and `WITHDRAWAL_IN_FLIGHT = {pending, approved, requires_double_approval}`.
    - "Completadas" for orders now includes `approved` (Confirmado is a success state), plus `completed` / `delivered`.
    - Comment block in-file explaining the semantic divergence + link to iter55.22 origin so future refactors don't collapse them again.
  - **Numerical verification** against real preview data (`user_test_vip01`): with 250 pending, 905 approved, 68 RDA, 131 completed, 148 rejected orders + 143 pending, 64 approved, 37 paid, 370 rejected withdrawals →
    - OLD (buggy): PENDIENTES=**1430** (over-counted the 905 confirmed orders as pending)
    - NEW (fixed): PENDIENTES=**525** (318 in-flight orders + 207 in-flight withdrawals). COMPLETADAS=1073 (1036 finalized orders + 37 paid withdrawals).
  - **Tests**: new `test_iter55_25_dashboard_pending_semantics.py` — 3 cases: `/orders/mine` returns all statuses verbatim, `/vip/withdrawals/mine` too, and a doc-as-code assertion pinning the exact sets so a future frontend rewrite that diverges will fail lock-step (the frontend file references iter55.25 in a comment). **3/3 pass**. Combined with iter55.22 tests: **6/6 pass**.
  - `yarn lint` clean.

- **Production currency confirmation for iter55.24**: owner's screenshot of Mis Órdenes shows the pair `USDT → USD` — confirms the "Dolar Efectivo" currency in production has `code=USD` exactly as the iter55.24 rule expects. **Cash-USD floor will trigger correctly on prod after redeploy** with no additional config.



- Cash-USD delivery floors sub-dollar amounts (iter55.24, Feb 2026) — owner reported: "en el caso de las entregas de USD efectivo a domicilio orientarle al cliente que debe enviar un monto que dé un valor sin centavos ya que no tenemos disponibilidad de centavos dolar. Si envía un valor con centavos la plataforma da la tasa de cambio por defecto a favor de Resilience para que dé un numero sin centavos". Cuba ops does not stock coins — every cash USD payout has to be exact whole dollars.
  - **Backend** `services/orders_helpers.py`:
    - New pure helper `_cash_usd_rounds_down(to_code, delivery_method)` returns True only when `delivery_method=="cash"` AND `to_code` (case-insensitive) equals `"USD"`. Kept as small unit-testable helper so it can be swapped for a per-currency `cash_no_cents` flag later if EUR/GBP effectivo appear.
    - `build_order_from_payload()` now branches: cash-USD uses `math.floor()` for `amount_to`; every other case keeps the original `round(..., 4)` semantics. Guarantees fractional dollars can't leak into the ledger even if a modified frontend sends them.
  - **Frontend** `pages/dashboard/ExchangeView.jsx`:
    - Mirror helper `isCashUsdDelivery = deliveryMethod === "cash" && toCode.toUpperCase() === "USD"`.
    - New yellow guidance banner `data-testid="cash-usd-guidance"` appears the moment cash+USD is selected — before the user calculates — with copy: "No manejamos **centavos en dólar** físico. Envía un monto que resulte en un valor **sin decimales** al que recibe. Si el cálculo da fracción, redondeamos hacia abajo y la diferencia queda a favor de **Resilience**."
    - New row inside the calculation summary `data-testid="cash-usd-rounding-loss"` shows the exact fractional loss in red (e.g. "Redondeo cash USD: -0.75 USD") so the client sees the impact before submitting.
    - "Recibirás" now displays `.toFixed(2)` for cash-USD (whole dollars) vs `.toFixed(4)` for the rest.
  - **Bonus defensive fix** in `routes/admin_revenue.py`: `admin_revenue()` crashed with `KeyError: 'from_code'` when any order lacked required fields (found via a stray seed doc in preview). Now skips malformed orders instead of 500-ing the whole revenue page.
  - **Tests**: new `test_iter55_24_cash_usd_floor.py` — 5 cases:
    1. Pure helper matches all combinations (usd/USD/lowercase, transfer/crypto rejected, EUR not affected).
    2. E2E 325 ZELLE24 @ 0.95 → USD cash = 308.0 (screenshot scenario).
    3. Regression guard: cash+USD floors, transfer keeps 308.75 (precision preserved for wire transfers).
    4. Regression guard: cash+CUP does NOT floor (rule is USD-specific).
    5. Integer amounts stay unchanged (floor is a no-op).
    **5/5 pass**. `test_marketplace_profit_and_margin.py::TestRevenueMarketplaceSection` regains its 3/3 after the admin_revenue KeyError fix. `yarn lint` clean.
  - **Verified E2E** in preview: enabled USD cash temporarily → filled 325 → banner rendered, rounding row read "-0.75 USD" in red, "Recibirás" showed exactly "308.00 USD".
  - **Note for prod redeploy**: the rule keys off `to_code.upper() === "USD"`. If in production the cash currency was seeded with a different code (e.g. `USDCASH`, `USD_EFECTIVO`), the floor rule will NOT trigger. Recommendation: keep the currency code as `USD` OR extend the helper's whitelist to include the actual production code.



- Audit trail for withdrawal + redemption status changes (iter55.23, Feb 2026) — bug reported by owner on production: **"en auditoría cuando se rechaza un pago no sale quién lo rechazó"**. Root cause: two admin endpoints mutated the row but silently skipped `log_action`, leaving the audit ledger blind to those actions.
  - **Endpoints fixed**:
    - `routes/admin_withdrawals.py::update_withdrawal` (PUT `/admin/withdrawals/{wid}/status`) — every approve/pay/reject/pending transition now emits `action="withdrawal.{status}"` with the full actor snapshot (id/email/name/role/permissions), before/after status, amount_usd, currency, method, user_id, admin_note, and payout_tx_hash if provided.
    - `routes/admin.py::update_redemption` (PUT `/admin/redemptions/{rid}/status`) — same fix with `action="redemption.{status}"` + product_id, quantity, total_usd. Refactored the endpoint to capture `actor` from `require_permission()` once (was being discarded before).
  - **Idempotency guard**: `if new_status != current_status:` prevents duplicate rows when ops accidentally re-submits the same status (regression tested).
  - **Tests**: new `test_iter55_23_withdrawal_audit_trail.py` — 5 cases:
    1. Rejecting a withdrawal writes exactly 1 audit row with actor + amount + note.
    2. Approving also logs (happy path).
    3. Setting the same status again does NOT double-log.
    4. Rejecting a redemption also logs.
    5. New entries appear in the audit CSV export (E2E through `/admin/audit/export.csv`).
    **5/5 pass**. Regression run over the audit/permissions/withdrawals corpus: **55/55 green** — no regression.
  - **Impact on prod ops**: from this iter forward, any "quién rechazó este retiro" question has a single-query answer via `/admin/audit` (or the monthly PDF export). Historical retiros that were rejected BEFORE this deploy remain unauditable (no time-travel possible), but no new gap will appear.



- Google Maps shortcut on Dirección row (iter55.22d, Feb 2026) — follow-up to iter55.22c. Same rationale as the WhatsApp shortcut: reduces coordination friction for the mensajero.
  - **Update to** `/app/frontend/src/components/CashDetailsTable.jsx`:
    - New `<MapsCell address={…} />` sub-component. Renders a blue-hover `MapPin` icon **only** in the Dirección row. Click opens `https://www.google.com/maps/search/?api=1&query={encodeURIComponent(address)}` in a new tab (deep-links to native Maps on mobile). Toast: "Abriendo Google Maps…".
    - Row selector logic composes naturally with the existing WA shortcut: Celular → WhatsApp + Copy · Dirección → Maps + Copy · Nombre / ID → Copy only.
  - **Testids added**: `cash-details-maps`.
  - **Validation**: Playwright E2E — intercepted `window.open`, asserted URL is `https://www.google.com/maps/search/?api=1&query=Calle%2023%20n%C2%BA%20456...La%20Habana`. Dirección row = 2 buttons, Nombre row = 1 button. Zero runtime errors. `yarn lint` clean.



- WhatsApp shortcut on Celular row (iter55.22c, Feb 2026) — follow-up to iter55.22b mini-table. Ops asked for a 1-click flow: copy the phone AND open WhatsApp with a pre-loaded greeting instead of the operator having to manually strip the `+53` prefix, open WhatsApp Web, paste, then type "Hola, soy de Resilience…".
  - **Update to** `/app/frontend/src/components/CashDetailsTable.jsx`:
    - New pure helper `normalisePhone(raw)` strips everything except digits (wa.me requires bare digits). Handles `+53 5555-1234`, `(535) 555-1234`, `null`, empty string.
    - New `<WhatsappCell phone={…} />` sub-component. Renders a green-hover `MessageCircle` icon **only** in the Celular row. Click:
      1. best-effort `navigator.clipboard.writeText(phone)` (async, `.catch()` wrapped so a permission-denied doesn't crash the UI — a real regression I hit in QA when the initial version used `try/catch` around a Promise-returning call);
      2. `window.open("https://wa.me/{normalised}?text={template}", "_blank", "noopener,noreferrer")` with `WHATSAPP_TEMPLATE = "Hola, soy del equipo de Resilience Brothers. Estamos coordinando la entrega de su retiro en efectivo. ¿Puede confirmar disponibilidad para recibirlo?"`;
      3. sonner toast "Abriendo WhatsApp…".
    - Row layout tweaked (`w-16 whitespace-nowrap`) so the celular cell hosts BOTH icons (WhatsApp + Copy); other rows keep the single Copy icon.
  - **Testids added**: `cash-details-whatsapp`.
  - **Validation**: normaliser unit test — **5/5 pass** (bare +53, spaces+dash, parens, empty, null). Playwright E2E — clicked the WA button, intercepted `window.open`, asserted URL is exactly `https://wa.me/5355551234?text=Hola%2C%20soy%20del%20equipo%20de%20Resilience%20Brothers…` and the celular row shows 2 buttons vs 1 in every other row. **Zero runtime errors** after the async clipboard fix. `yarn lint` clean.



- Admin cash-details mini table (iter55.22b, Feb 2026) — follow-up to iter55.22 structured cash form. Ops asked to display the composed `details` block as a compact table in the admin withdrawal modal so operators can grab the phone in 1 click while on the phone with the courier, instead of scanning a paragraph.
  - **New component** `/app/frontend/src/components/CashDetailsTable.jsx` (~110 LOC): exports a named `parseCashDetails(raw)` pure function + a default `<CashDetailsTable details={…} />` React component.
    - `parseCashDetails` walks the newline-separated block, splits each line on the first `:`, and only accepts labels in the whitelist `["Nombre","Celular","Dirección","ID / Carné"]`. Requires **≥2 recognised labels** to avoid false-positives on legacy free-form details that happen to contain a colon. Returns `null` for legacy / empty / single-field inputs.
    - `<CashDetailsTable>` renders a 3-column mini-table with per-row copy button (`<Copy>` toggles to `<Check>` in `#22C55E` on success, resets after 1500 ms) driven by `navigator.clipboard.writeText` + a `sonner` toast. Rows only appear for fields that were provided (ID / Carné row hidden when the client didn't fill it).
  - **Wired into** `AdminWithdrawals.jsx` modal: when `open.method === "cash"` AND `parseCashDetails(open.details)` returns non-null, render the mini-table + a "Copiar bloque completo" fallback below. Legacy free-form retiros (pre-iter55.22) continue to render via the original `<CopyableText>` — full backward compatibility.
  - **Testids added**: `cash-details-table`, `cash-details-row-nombre`, `cash-details-row-celular`, `cash-details-row-direcci-n`, `cash-details-row-id-carn`, `cash-details-copy-<label>`.
  - **Validation**: 6-case parser unit test run (full block / no ID / legacy / empty / single field / whitespace edges) — **6/6 pass**. Visual smoke on `/admin/withdrawals` with a seeded cash retiro confirmed all 4 rows render with copy buttons; existing "Beneficiario / Estado / Nota / Evidencia / En progreso / Entregado / Rechazar" flow untouched. `yarn lint` clean.



- Client dashboard "Pendientes" fix + structured cash withdrawal form (iter55.22, Feb 2026):
  - **Bug 1 — dashboard counter**: on production `p2p.resiliencebrothers.com`, a VIP client with a **cash retiro in status="approved"** (rendered as "En progreso" in the UI) was seeing **PENDIENTES: 0** on their dashboard. Root cause: `pages/dashboard/OverviewView.jsx:24` only counted `orders.filter(o => o.status === "pending").length` — it ignored withdrawals entirely and dropped `approved` (which for cash means "en progreso"). Fix: dashboard now also fetches `/api/vip/withdrawals/mine` and counts anything in the in-flight set `{pending, approved, in_progress, requires_double_approval}` from both orders and withdrawals. "Completadas" tightened to only successful terminals (`delivered`, `completed`, `paid`) — `approved` no longer double-counts as completed.
  - **Bug 2 — free-form cash details**: the "Detalles" textarea for cash withdrawals let each client type receiver info in a different order/format ("Juan Pérez CI 91020 tel 55555"). Ops asked for a mandatory standard layout. Fix: when `method === "cash"`, the single textarea is replaced by 4 structured inputs: **Nombre y apellidos** (obligatorio, `data-testid="cash-receiver-name"`), **Teléfono celular** (obligatorio, `data-testid="cash-receiver-phone"`), **Dirección de entrega** (obligatorio, `data-testid="cash-receiver-address"`), **Número de ID / Carné** (opcional, `data-testid="cash-receiver-id"`). The frontend composes a labelled multiline block:
    ```
    Nombre: Juan Pérez Rodríguez
    Celular: +5355551234
    Dirección: Calle 23 nº 456, Vedado
    ID / Carné: 91020412345   (only if provided)
    ```
    …and posts it as `details`, so the backend / admin panel / PDFs / emails all inherit the same clean structure without any schema change. Per-field validation prevents empty/too-short receiver name, phone, or address before the request is fired.
  - **Backend compatibility**: the existing iter55.19b >=20 char gate remains untouched — the composed block is always >=40 chars — so all 9/9 iter55.19 tests continue passing.
  - **Tests**: new `test_iter55_22_client_pending_and_cash_structured.py` with 3 cases: (a) 200 + verbatim persistence of the composed block, (b) optional ID line preserved when present, (c) `/vip/withdrawals/mine` regression guard — must keep returning `approved` status so the dashboard counter stays honest. **3/3 pass**.
  - **Verified**: screenshot at 900×900 on `/dashboard/vip` with CUP + Efectivo (CUP/USD) shows the 4 structured inputs, hint copy, beneficiary + 2FA + submit button all reachable. Cash-only currencies work; non-cash flows unchanged.



- Modal-scroll audit + ESLint guardrail (Feb 2026) — triggered by owner report: on production `p2p.resiliencebrothers.com`, the "Editar Moneda" modal hid its Guardar button on a smaller laptop because `<DialogContent>` had no `max-h` cap. Radix DialogContent does NOT cap height by default → any content taller than the viewport is silently truncated with no scrollbar.
  - **Sweep** — 14 modals were missing `max-h-*`. Added `max-h-[85vh] overflow-y-auto` to all of them (still discoverable in git via the single-classname diff pattern):
    - **Admin**: `AdminCurrencies`, `AdminProducts`, `AdminRates`, `AdminWithdrawals`, `AdminKYC`, `AdminCompanyFunds`, `AdminProfileChangeRequests`, `AdminAppeals`, `AdminBlockedContacts` (block + bulk-import), `AdminSecurity` (cf-block), `users/RejectPhoneDialog`, `company-funds/AdjustmentDialog`, `transactions/TransactionDetailModal` (caught by the ESLint rule after the manual sweep).
    - **Client**: `ProfileView` (email/phone/country change — 3 dialogs), `MarketplaceView`, `MyTransactions`, `SecuritySettings` (disable 2FA + regenerate codes), `BalanceConverterCard` (VIP conversion — verified via screenshot at 900×600), `DefensiveModePanel`.
    - **Globals**: `EmailAuthDialog`, `TotpPromptDialog`, `AppealDialog`.
    - **Left intentionally opting out**: `OnboardingDialog` (hero-image wizard uses `overflow-hidden` by design), `TransactionDetailModal` closed-state placeholder (`className="hidden"`).
  - **Prevention — custom ESLint rule** `rb-local/no-dialog-without-scroll`: new file `/app/frontend/eslint-rules/no-dialog-without-scroll.mjs` walks every `<DialogContent>` JSX opening tag and enforces that its className contains a `max-h-*` utility (any Tailwind syntax: `max-h-[85vh]`, `max-h-screen`, arbitrary values, `clsx({...})` keys, template literal quasis all understood). Opts-out via `overflow-hidden` or `className="hidden"`. Severity `error`. Wired via `eslint.hooks.config.mjs` and a new `yarn lint` script in `package.json`.
  - **Validation**: rule tested against a 5-case fixture (bad no-max-h, bad no-className, ok overflow-hidden, ok explicit max-h, ok template literal) — all cases resolved correctly. On real repo: `yarn lint` reports 0 errors / 0 warnings; the very first CI run of the rule caught `TransactionDetailModal.jsx:22` that the manual sweep had missed (its sibling on line 13 is the `className="hidden"` placeholder).
  - **Bonus**: fixed 2 pre-existing `react/no-unescaped-entities` in `ProfileView.jsx:475` while touching the file.
  - **Docs**: `/app/frontend/eslint-rules/README.md` explains the rationale, opt-outs, and how to run.



- Code review cleanup pass (Feb 2026) — quick-win items from the internal Python/React review:
  - **Circular import eliminated**: `auth_utils.py` ↔ `services/permissions.py`. Old design had `require_permission()` in `services/permissions.py` doing a deferred `from auth_utils import require_user` at call time. Refactor: `services/permissions.py` is now a **pure data + predicate layer** (`PERMISSION_CATALOG`, `_has_permission`, `sanitize_permissions`, `permission_label`) with **zero FastAPI dependencies**. The HTTP gate `require_permission()` now lives in `auth_utils.py` alongside `require_user()`, importing the pure primitives at module top-level. `routes/profile.py` migrated its 3 deferred imports to a single top-level `from auth_utils import require_permission`. Result: no import cycle at any load path; simpler mental model.
  - **Unused imports (F401)**: 14 unused imports auto-fixed by ruff across `routes/admin_company_funds.py` and others. Zero F821/F823 (truly undefined names) reported.
  - **Empty catch block hardened** in `PushToggle.jsx:108`: the rollback `sub.unsubscribe()` inside the error handler used to swallow with `/* ignore */`. Now the failure is reported to Sentry with `level: "info"` so we notice if unsubscribe is unreliable on any device, without alerting the user (non-fatal path).
  - **Console statements**: `sw-register.js` and `sentry.js` — both had `console.error` behind `eslint-disable`. Wrapped with `NODE_ENV !== "production"` guards so console output is DEV-only. Production Sentry path unchanged.
  - **Inline arrays hoisted to module scope** in `AdminSecurity.jsx` (lines 232/251/269/288): 4 header arrays for `TableSimple` (`HEADERS_NEW_IP`, `HEADERS_RATE_LIMITED`, `HEADERS_ORIGIN_VIOLATIONS`, `HEADERS_LOGIN_BURSTS`) — trivial re-allocation removed on every re-render.
  - **Rejected findings (with justification)**: the review's "86 missing hook dependencies" was verified against `react-hooks/exhaustive-deps` v5.2.0 (official React plugin) with **zero violations** across all listed files (`VipView.jsx`, `ProfileView.jsx`, `MyTransactions.jsx`, `AdminSecurity.jsx`, `AdminTransactions.jsx`). The review incorrectly asked to add module-level constants (`axios`, `API`, `PAGE_SIZE`) to dependency arrays — these are stable module imports, not component-scoped state. Adding them is explicitly discouraged by the React team and would be a lint anti-pattern.
  - **Deferred (P2 refactor iteration)**: the "Important" complexity hotspots (`pdf_service.py::generate_vip_closing_pdf`, `revenue_report.py`, `BalanceConverterCard.jsx`, `VipView.jsx`, `EmailAuthDialog.jsx`, `PushToggle.jsx`) each need dedicated iterations because refactoring 200-500 line components without a matching test harness risks regressions on business-critical flows (VIP redemption, PDF exports, push subs). These belong in a separate "refactor sprint" once we have visual regression tests.
  - **Regression**: fixed `test_audit_export_and_dates.py` (2 assertions) that had been silently stale since iter55.16b added the `actor_permissions_effective` CSV column. 63/63 pass on the impacted test suites (permissions, profile change, audit toggle, audit export, monthly scheduler). Remaining failures in the full suite are pre-existing state-pollution flakes documented in the handoff (`PHONE_NOT_VERIFIED` in iter14) + brittle OpenAPI path-count snapshots — none introduced by this cleanup.



- UI toggle for monthly-audit auto-send (iter55.21b, Feb 2026): follow-up right after iter55.21 — owner asked for a UI switch instead of having to edit MongoDB by hand to flip the `settings.global.auto_send_monthly_audit` flag.
  - **Backend `routes/admin.py`**: extended `AdminSettings` model with `auto_send_monthly_audit: Optional[bool]` (nullable, matches scheduler.py opt-out semantics: `is False` = off, anything else = on). `GET /admin/settings` now returns the resolved boolean (missing → True). `PUT /admin/settings` migrated from `exclude={"totp_code"}` to `exclude={"totp_code"} + exclude_unset=True` so partial PATCH-style requests (e.g. only the flag) no longer clobber unrelated settings like `ops_notifications_email` or `vip_threshold_usdt` — critical regression guard.
  - **Frontend `pages/admin/AdminOverview.jsx`**: new "Informe mensual de auditoría · envío automático" section inside the existing "Alertas Automáticas" card. Yellow `FileText` icon + explanation copy ("Cada día 1 a las 09:15 UTC se envía por email el PDF de auditoría del mes anterior…"). Right-aligned Shadcn `<Switch>` (`data-testid="auto-audit-toggle"`) + status pill ("ACTIVO"/"DESACTIVADO", `data-testid="auto-audit-status-label"`).
  - **UX flow**: flipping the switch triggers optimistic UI + opens the existing `TotpPromptDialog` with a context-aware title ("Activar…" / "Desactivar envío automático"). Confirming sends `PUT /admin/settings` with only the flag + `totp_code`. Cancel or TOTP failure rolls the switch back to its previous position — no risk of a client-only state diverging from the server.
  - **Testids added**: `auto-audit-toggle-card`, `auto-audit-toggle`, `auto-audit-status-label`.
  - **Tests**: 6 new pytest cases in `test_iter55_21b_audit_toggle_ui.py` — (a) default flag=True when missing, (b) admin can disable, (c) admin can re-enable, (d) employee 403 (staff cannot flip global settings), (e) partial PUT (only flag) does NOT clobber ops_email or threshold, (f) explicitly-False flag surfaces in GET. **31/31 regression pass** on `test_iter55_17_monthly_audit_pdf.py + test_iter55_21_monthly_audit_scheduler.py`. Frontend E2E smoke: card renders with "ACTIVO" pill by default, PUT/GET round-trip end-to-end verified via curl.
  - **Status**: fix en preview. User needs to redeploy to push to production. Once deployed, owner can head to `/admin` → "Alertas Automáticas" card → toggle the switch and confirm with 2FA — no more direct Mongo edits.


## What's Been Implemented (Feb 2026)
- Public landing page with hero, about, services, how-it-works, VIP section, CTA.
- Google OAuth flow (login → callback → cookie session, /api/auth/me).
- Client dashboard: Overview (live rates + stats), Exchange (full P2P flow with proof upload), Orders history with modal detail, VIP Balance + withdrawals, Marketplace + redemptions.
- Admin panel: Overview stats + seed button, Orders (filter + approve/reject/complete), Withdrawals + Redemptions management, Currencies CRUD, Rates CRUD, Products CRUD, Users (role + balance editor), Revenue (P2P + Marketplace profit), Audit Log.
- Order math: VIP uses rate_vip + 0% commission; Normal uses rate_normal + 5% commission.
- Multi-currency VIP balances (`vip_balances` dict, accumulate-on-approve).
- Refund-on-reject for withdrawals + redemptions (balance + stock).
- PWA: manifest, service worker, install prompt, iOS splash, company logo.
- Push notifications via PyWebPush (VAPID).
- Email notifications via Resend (sandbox while DNS pending verification).
- PDF daily closing for VIPs (reportlab).
- Employee role (staff sub-tier, no Revenue/Audit, no admin role assignment).
- Automated admin alerts: VIP threshold breach, negative margin on order create + rate update.
- Audit Log: every staff action (rate.update, order.approved/rejected, settings.update, user.update) persisted; admin-only viewer at /admin/audit with action + actor filters. **(Feb 15, 2026 — iter8)**
- Audit Log export: admin-only CSV (UTF-8 BOM, Excel-friendly) + PDF (landscape, branded) via `GET /api/admin/audit/export.{csv,pdf}`, with the same filters applied. **(Feb 15, 2026 — iter9)**
- Audit Log date range: `since` + `until` (YYYY-MM-DD or ISO) on list + both exports, with UI date pickers and a "limpiar fechas" shortcut. **(Feb 15, 2026 — iter9)**
- Audit Log pagination: backwards-compatible offset/limit + `X-Total-Count` header; UI muestra "Anterior / Siguiente" con indicador "Página X de Y" y rango "N–M de Total". Page size = 50, reset automático al cambiar filtros. **(Feb 15, 2026 — iter9)**
- Componente `<Pagination>` reutilizable en `/components/Pagination.jsx`. Aplicado a AdminAudit, AdminOrders, AdminUsers. AdminUsers ganó búsqueda con debounce 300ms por nombre/email (case-insensitive vía regex MongoDB). AdminOrders movió su filtro de status a server-side. **(Feb 15, 2026 — iter10)**
- Menú hamburguesa móvil (shadcn Sheet) en Dashboard y AdminPanel. Cliente admin/empleado ve botón "Panel Admin" prominente. A11y compliance vía VisuallyHidden SheetTitle. Testids: `dashboard-mobile-menu-trigger`, `admin-mobile-menu-trigger`, `orders-filter-{status}`. **(Feb 17, 2026 — iter10)**
- Despliegue: app live en `https://p2p.resiliencebrothers.com` (subdominio dedicado, dominio raíz reservado para otra app del usuario). **(Feb 17, 2026)**
- Registro de Transacciones (contabilidad): `sender_name` obligatorio en órdenes + `beneficiary_name` obligatorio en retiros VIP. Nueva sección `/admin/transactions` (admin-only) muestra entradas + salidas con totales por moneda (in/out/neto). Filtros: dirección, moneda, titular (search), rango de fechas. Exports CSV (UTF-8 BOM) y PDF branded reusando ReportLab. **(Feb 17, 2026 — iter11)**
- Modal de detalle en Transacciones: rows clickeables abren Dialog con datos completos + comprobante de transferencia (imagen base64) descargable para entradas; mensaje contextual para salidas. **(Feb 18, 2026 — iter11)**
- **Refactor monolito → modular (iter27 → iter33)**. `server.py` pasó de 2316 líneas a **92 líneas** (solo bootstrap + CORS + scheduler). Routers extraídos: `routes/auth.py`, `routes/notifications.py`, `routes/blocklist.py`, `routes/market.py`, `routes/push.py`, `routes/me.py`, `routes/orders.py`, `routes/admin.py`. Helpers compartidos en `services/balances.py`, `services/orders_helpers.py`, `services/transactions.py`. OpenAPI ahora expone **80 paths con 9 tags** (Auth, Me, Orders, Admin, Market, Blocklist, Notifications, Push, System) — Swagger UI navegable. Conftest `_autoseed_sessions` re-siembra las 4 sesiones de prueba antes de cada test → suite auto-suficiente. Testing agent confirmó cero regresiones (373 passed; 15 failures pre-existentes, ajenas al refactor). **(Feb 27, 2026 — iter33)**
- **Sentry integration (iter34)**: `sentry_config.py` + `frontend/sentry.js` con backend (`sentry-sdk[fastapi] 2.63`) y frontend (`@sentry/react 10.62`). Deshabilitado por defecto, activa con `SENTRY_DSN` / `REACT_APP_SENTRY_DSN`. Auto-tag de actor (user_id, email, role) en cada error. ErrorBoundary global. Filtro de ruido: descarta HTTPException<500, ResizeObserver loop, network cancelado. 2 proyectos creados en sentry.io: `resilience-backend` (Python/FastAPI) y `resilience-frontend` (React). Test events confirmados en ambos dashboards. **(Feb 28, 2026 — iter34)**
- **Tests obsoletos modernizados (iter34)**: `test_iter16_email_auth.py` agrega `phone` requerido + actualiza expectativa de no-auto-login en verify-email. `test_marketplace_profit_and_margin.py` elimina suposición de comisión 5% (iter19 puso 0%). Resultado: 21 + 13 = 34 tests previamente rotos ahora verdes. **(Feb 28, 2026 — iter34)**
- **Cloudflare R2 Object Storage (iter35)**: abstracción provider-agnóstica (`services/storage.py` con r2/s3/none) + helper base64→storage (`services/proof_upload.py`) + proxy autenticado (`routes/files.py` con ownership check). `POST /api/orders` automáticamente sube `proof_image` base64 a R2 y persiste solo `/api/files/orders/<date>/<uuid>.png` en MongoDB. Igual para `payout_proof_image` (admin withdrawal status) y `invoice_image` (company-withdrawals). Bucket `resilience-p2p-proofs` (ENAM region), 10 GB gratis. **Cero cambios frontend** — `<img src="/api/files/...">` funciona via cookie samesite=none + secure. Testing agent: **105/105 verde** incluyendo 14 e2e contra el bucket real. **(Feb 28, 2026 — iter35)**
- **3 P2 refinements (iter36)**:
  - 📂 **`/api/openapi.json` ahora bajo `/api/*`** → Swagger UI (`/api/docs`) y ReDoc (`/api/redoc`) son alcanzables vía el ingress público (antes solo en localhost:8001).
  - 🚦 **HTTP 413 al cliente** cuando `proof_image > 8 MB` → la validación se ejecuta ANTES del check de storage para proteger MongoDB incluso en modo legacy. Detail estructurado: `{code: "PROOF_TOO_LARGE", size_mb, limit_mb, message}`.
  - 🔄 **Backfill base64 → R2** (`scripts/backfill_base64_to_r2.py`): CLI standalone con `--dry-run`/`--apply` mutuamente exclusivos, idempotente (key determinístico = doc_id), continúa al primer error y reporta resumen al final. Migración ejecutada: **159 órdenes históricas movidas a R2**, 2 oversize y 80 inválidas dejadas inline. Re-run produce 0 candidatos (idempotencia confirmada). Testing agent: **117/117 verde**. **(Feb 28, 2026 — iter36)**
- **Admin Health Dashboard (iter37)**: nueva vista `/admin/health` (admin-only) con 7 secciones agregadas en `services/health.py`: estado Sentry + contador local de errores en logs, uso de R2 (objetos, GB, costo mensual, desglose por carpeta), throughput de órdenes (1h/24h/7d + histograma horario), modo defensivo, órdenes pendientes con margen negativo (top 20 + tabla), colas de trabajo (orders/double-approval/withdrawals/phone-verifications/blocklist), counters de usuarios por estado. Endpoint `GET /api/admin/health/summary` (admin only). Auto-refresh cada 60s. Cards con `data-testid` granulares para QA. Testing agent: **117/117 verde** (14 dedicated + 103 regression), 100% frontend rendering. **(Feb 28, 2026 — iter37)**
- Filtros de monto (mín/máx) en Transacciones: validación servidor (rechazo de negativos y `min > max` con HTTP 400), propagación a CSV y PDF. Botón "Ir a Órdenes / Ir a Retiros VIP" en el modal para navegar a la sección original. **(Feb 18, 2026 — iter11)**
- Acceso ampliado a Transacciones: **empleados** ahora ven `/admin/transactions` (admin + employee = staff). Nuevo `/dashboard/transactions` para **VIPs y clientes normales** con `GET /api/me/transactions` que aísla por user_id, exports CSV/PDF propios. Nav "Mi Historial" en Dashboard mobile + desktop. **(Feb 18, 2026 — iter12)**
- 2FA / TOTP step-up para retiros: secretos cifrados con Fernet (TOTP_MASTER_KEY env var), 10 códigos de recuperación bcrypt-hashed de un solo uso. Endpoints `/api/me/2fa/{status,setup,verify-setup,disable,regenerate-recovery-codes}`. Tolerancia ±1 step (30s clock drift). Página `/dashboard/security` con QR + secret manual + códigos de recuperación. Withdrawals obligan 2FA: 412 si no configurado (con `setup_url`), 401 si código inválido. Recovery codes consumibles también funcionan. **(Feb 18, 2026 — iter13)**
- Defensive Mode: orders with profit % below `defensive_margin_pct` auto-flagged `requires_double_approval`; only an admin (not employee) can approve. **(Feb 15, 2026 — iter8)**
- 60/60 backend tests passing across iter6/iter7/iter8 (audit + defensive + revenue + alerts + multicurrency + push + email + closing).
- **iter11 (Feb 2026)**: Phase 2 TOTP 2FA step-up for high-risk admin endpoints (update_rate, update_user, update_withdrawal, update_admin_settings) + reusable `TotpPromptDialog` component across all admin panels. 204/204 backend tests pass.
- **iter12 (Feb 2026)**: Revenue Registry (Ingresos) — daily + monthly breakdown tables in AdminRevenue, monthly CSV/PDF exports via `GET /api/admin/revenue/timeseries` and `/api/admin/revenue/monthly/export`. Backed by `/app/backend/revenue_report.py`. 214/214 tests pass (10 new).
- **iter13 (Feb 2026)**: Monthly PDF now includes a bar+cumulative-line chart (ReportLab graphics). APScheduler auto-emails the previous month's PDF to all admins on day 1 at 09:00 UTC (`/app/backend/scheduler.py`). On-demand button `POST /api/admin/revenue/monthly/send-now` (TOTP-protected) for ad-hoc resends. 220/220 tests pass (6 new).
- **iter14 (Feb 2026)**: Five corrective updates: (1) AdminUsers removes editable Saldo VIP — read-only with currency breakdown; (2) Normal users now accumulate balance and request withdrawals (`/vip/balances` open to all clients, `/vip/withdraw` blocks only employees); (3) UI rename "Aprobado" → "Confirmado"; confirmed orders & paid withdrawals locked from employee edits; (4) Employees have `allowed_currencies` field controlling which orders/withdrawals they see and can act on; (5) Withdrawals require `payout_proof_image` (transfer) or `payout_tx_hash`/proof (crypto) before marking as paid. Cash method shows "En progreso → Entregado" labels. 229+10 backend tests pass.
- **iter15 (Feb 2026)**: Two new modules:
  - **Mi Cola** (`/admin/queue`): consolidated pending orders + withdrawals scoped to staff's allowed_currencies. Admin sees everything pending.
  - **Fondo Empresa** (`/admin/company-funds`): dynamic per-currency working capital (inflow − client_payouts − company_payouts). New collection `company_withdrawals` with status flow pending→approved→paid. Staff with currency scope can CREATE, only admin can change status. Each withdrawal captures beneficiary, autodetected `authorized_by`, optional invoice image. 2FA step-up required. Insufficient funds blocked. 242/242 tests pass (12 new).
- **iter17 (Feb 18, 2026)**: **Email/Password authentication fallback** (for users blocked from Google OAuth, e.g. Cuba). New endpoints `POST /api/auth/{register,login,forgot-password,reset-password}` and `GET /api/auth/verify-email/{token}`. Registration creates an **unverified** user (no auto-login). Login is blocked with 403 `EMAIL_NOT_VERIFIED` until verification. Single-use verification + reset tokens stored in `users.verification_token` / `users.password_reset_token` (24h / 2h TTL). Brute-force lockout reuses iter13 `login_attempts` logic (5 fails → 429). Resend sends the verification + reset emails (best-effort; sandbox-safe). New pages: `/auth/verify-email/:token` (`VerifyEmail.jsx`) and `/auth/reset-password/:token` (`ResetPassword.jsx`). `EmailAuthDialog.jsx` now supports three modes (login | register | forgot) with a "¿Olvidaste tu contraseña?" link. Google OAuth remains visible inside the dialog and on the landing page. StrictMode-safe verify (useRef sentinel). **17/17 backend tests + 19/19 E2E checkpoints pass** (`/app/backend/tests/test_iter16_email_auth.py`, `/app/test_reports/iteration_13.json`).
- **iter25 (Jun 26, 2026)**: **Verify-email UX fix** — clicking the verification link no longer auto-logs in. Backend `auth_verify_email` returns `{verified, email, name}` and stops creating a session. Frontend redirects to `/?verified=1&email=<encoded>`; Landing detects the query, shows toast "Correo verificado", auto-opens `EmailAuthDialog` in login mode with the email pre-filled, then cleans the URL. New `initialEmail` prop on `EmailAuthDialog`. Resend `EMAIL_SENDER` updated to `Resilience Brothers <noreply@resiliencebrothers.com>` (domain verified). Backend 4/4 + Frontend 3/3 E2E (`/app/test_reports/iteration_9.json`).
- **iter26 (Jun 26, 2026)**: **Reenviar correo de verificación** — new `POST /api/auth/resend-verification` (rate-limited 1/60s per email, generic 200 to prevent enumeration, regenerates token + last_resend_at, best-effort email). `EmailAuthDialog` adds: (1) footer link in login mode "¿No recibiste el correo de verificación?", (2) button in post-register success card, (3) button in EMAIL_NOT_VERIFIED success card. Backend 7/7 + Frontend 9/9 (`/app/test_reports/iteration_14.json`).
- **iter27 (Jun 26, 2026)**: **Refactor Phase 1 — Auth router extraction**. Created `/app/backend/db_client.py` (shared Mongo client), `/app/backend/auth_utils.py` (188 lines of helpers), `/app/backend/routes/__init__.py` + `/app/backend/routes/auth.py` (437 lines, 11 endpoints + 5 models). `server.py` reduced from 3189 → 2638 lines (-17%). Zero behavioral regression: 58/58 iter20-26 regression tests + 20/21 new structural tests pass (1 fail is ingress quirk, not refactor). Frontend smoke test confirms Landing + EmailAuthDialog still work (`/app/test_reports/iteration_15.json`).
- **iter28 (Jun 26, 2026)**: **Anti-scam Trust Layer Phase 2** — six features in one ship: (1) `POST /api/admin/blocked-contacts/bulk-import` with a WhatsApp-aware parser (`_parse_whatsapp_blocklist`) that handles block headers, decorative emoji lines, multiple E.164 phones per block, and 📌-prefixed reason lines; (2) granular permission `users.can_manage_blocklist` (default false; admin always bypasses) gating ALL blocklist + verify/reject endpoints; (3) **Verify ✅ / Reject 🚫** split — `POST /api/admin/users/{user_id}/reject-phone` blocklists the phone + keeps account `under_review`; verify-phone now refuses (409 `PHONE_IS_BLOCKED`) if the phone is on the blocklist; (4) new `users.account_status` field (`active`/`under_review`/`blocked`) with new accounts starting `under_review`; admin/employee bypass; (5) `_assert_account_active` guard added to `create_order`, `create_withdrawal`, `redeem_product` → 403 `ACCOUNT_UNDER_REVIEW`/`ACCOUNT_BLOCKED`; (6) login + Google callback re-check blocklist on every login and force `under_review` on hit. Frontend: AdminBlockedContacts bulk-import dialog with format example + result card (`import-count-imported/skipped/invalid` + `affected_active_accounts` warning); AdminUsers reject-phone dialog + permission-aware Verificar/Rechazar buttons + account_status badge; Dashboard under-review-banner + account-blocked-banner. **17/17 new + 84/85 regression + Frontend Playwright 100% pass** (`/app/backend/tests/test_iter28_anti_scam_trust.py`, `/app/test_reports/iteration_16.json`).
- **iter29 (Jun 27, 2026)**: **In-app notifications system** for 3 trust-layer events: (a) admin + staff with `can_manage_blocklist=true` get notified when a new normal/vip user completes registration with a phone (lands `under_review`); fan-out happens once per recipient. (b) the target user gets notified when staff verifies the phone (account activated). (c) the target user gets notified when staff rejects the phone (account stays `under_review`). New collection `notifications` with `{recipient_user_id, type, title, message, data, read, created_at, read_at}`. New `/app/backend/routes/notifications.py` (~150 lines): GET `/api/notifications`, GET `/api/notifications/unread-count`, POST `/api/notifications/{id}/read`, POST `/api/notifications/mark-all-read`. Triggers wired into `auth_register` (password), `set_my_phone` (Google OAuth — only on FIRST phone set, no spam on updates), `verify-phone`, `reject-phone`. Register response message updated to mention "puede tardar hasta 24 horas". New `NotificationBell.jsx` with bell + badge + popover + 30s polling + mark-as-read on click + "Marcar todo" button — integrated in Dashboard + AdminPanel (sidebar footer + mobile top bar). Backend 10/10 new + 17/17 iter28 regression + Frontend Playwright 100% pass (`/app/backend/tests/test_iter29_notifications.py`, `/app/test_reports/iteration_17.json`).
- **iter30 (Jun 27, 2026)**: **3-in-1 ship** — (A) **PWA Web Push** wired into iter29 in-app notifications: `push_service.send_push_to_user(db, user_id, payload)` + 3 payload builders (`build_new_pending_user_payload`, `build_phone_verified_payload`, `build_phone_rejected_payload`). All 3 `notify_*` helpers in `routes/notifications.py` now do BOTH in-app insert AND push fan-out (best-effort, dead subs auto-pruned). (B) **Refactor Phase 2** — extracted `/app/backend/routes/blocklist.py` (334 lines): blocked-contacts CRUD + bulk-import + verify-phone + reject-phone. Includes `_assert_can_manage_blocklist` + `_parse_whatsapp_blocklist`. `server.py`: 2904 → 2637 lines (-9% more; -17% cumulative since iter27). `_assert_account_active` kept in `server.py` (used by orders/withdrawals/redemptions). (C) **Cyclomatic complexity reduction** — `create_order` split into `_resolve_order_rate`, `_build_order_from_payload`, `_maybe_flag_defensive_margin`, `_dispatch_new_order_alerts`; `update_order_status` split into `_authorize_status_transition`, `_run_post_status_side_effects`; `EmailAuthDialog.jsx` extracted `ERROR_CODE_HANDLERS` table + `handleAuthError` helper. Zero behavioral drift: Backend 50/50 (iter25/26/28/29/30) + Frontend Playwright 100% pass (`/app/backend/tests/test_iter30_blocklist_push.py`, `/app/test_reports/iteration_18.json`).
- **iter31 (Jun 27, 2026)**: **Refactor Phase 3 (partial)** — (1) Moved `_enforce_totp_step_up` + `_enforce_employee_currency_scope` from `server.py` to `auth_utils.py`. routes/blocklist.py now imports `_enforce_totp_step_up` directly (zero lazy `from server import` left in routes/blocklist.py). (2) Extracted `/app/backend/routes/market.py` (~295 lines): all 12 endpoints for currencies/rates/products + 6 Pydantic models (Currency/CurrencyCreate/ExchangeRate/ExchangeRateCreate/Product/ProductCreate) + helpers (`_check_employee_product_perms`, `_scan_rate_change_margin`). Models re-imported into `server.py` for legacy callers (`/admin/seed`). server.py reduced 2637 → 2377 (-260 lines, -25% from original 3189). (3) Fixed `test_iter18_onboarding.py` (pre-existing bug: missing `phone` field in register payload + assumed verify-email auto-login, but iter25 removed that behavior). Cleaned 297 stale TEST_* products. Backend 60/64 PASS (failures = unrelated old test bug fixed in same iter) + Frontend Playwright 100% (`/app/test_reports/iteration_19.json`).
- **iter38 (Feb 27, 2026)**: **Code Quality — Cyclomatic Complexity refactor (P1)**. Four helpers extracted from the 4 functions flagged by `radon`:
  - `routes/admin.py update_withdrawal` (CC 20 → ≤5): `_assert_paid_lock`, `_refund_balance_on_reject`, `_collect_payout_evidence`, `_validate_paid_evidence`.
  - `routes/admin.py admin_revenue` (CC 16 → <10): `_new_pair_bucket`, `_role_bucket_for`, `_accumulate_revenue_order`, `_finalize_pair_items`.
  - `audit_pdf.py generate_audit_pdf` (CC 13 → <10): `_format_audit_ts`, `_build_audit_row`, `_build_filters_paragraph`.
  - `pdf_service.py generate_vip_closing_pdf` (CC 13 → <10): `_compute_closing_totals`, `_format_order_row`, `_build_currency_breakdown_table`.
  Plus React Hook Stale Closure audit: ESLint `react-hooks/exhaustive-deps` ran clean across all `src/**` — the original code-review report was outdated. Removed 3 unused `eslint-disable-next-line react-hooks/exhaustive-deps` directives (`PushToggle.jsx`, `AdminHealth.jsx`, `ExchangeView.jsx`). Behavior-identical: same signatures, same HTTP codes, same JSON shapes, same PDF magic bytes. **Backend 449/449 pre-existing + 16/16 new refactor regression (`test_refactor_regression_iter25.py`) pass** (`/app/test_reports/iteration_25.json`).
- **iter39 (Feb 28, 2026)**: **Bandeja única de notificaciones operativas + Backend split + Frontend component split (P1+P2)**.
  - **Centralised ops mailbox**: new `settings.global.ops_notifications_email`. When set, all admin alert emails (new order/withdrawal/redemption/margin/pending/monthly report) funnel to that single inbox via `admin_alerts.resolve_admin_email_recipients()`; push notifications still fan out per admin. UI in `AdminOverview.jsx` ("Bandeja única de notificaciones operativas" input with 2FA step-up). 7/7 tests in `test_ops_notifications_email.py`.
  - **Backend split**: `routes/admin.py` 1247 → 538 lines (-57%). 5 new sub-routers: `admin_withdrawals.py` (123 lines), `admin_users.py` (115), `admin_audit.py` (98), `admin_company_funds.py` (185), `admin_revenue.py` (299). server.py imports all 5 + re-exports `build_revenue_timeseries`. 31 admin endpoints, zero route collisions. **472/472 pytest regression + 19/19 new endpoint coverage (`test_iter38_admin_split.py`)** all green.
  - **Frontend component split**: 4 oversized pages decomposed into 17 sub-components.
    - `AdminTransactions.jsx` 499 → 172 (-65%); new dir `pages/admin/transactions/` with `TransactionsTotals`, `TransactionsFilters`, `TransactionsTable`, `TransactionDetailModal`.
    - `AdminUsers.jsx` 581 → 429 (-26%); new dir `pages/admin/users/` with `CurrencyMultiSelect`, `MarketPermsCell`, `UserPhoneCell`, `RejectPhoneDialog`.
    - `AdminRevenue.jsx` 464 → 215 (-54%); new dir `pages/admin/revenue/` with `RevenueCards`, `RevenueByPairTable`, `RevenueDailyTable`, `RevenueMonthlyTable`, `RevenueMarketplaceTable`.
    - `EmailAuthDialog.jsx` 381 → 277 (-27%); new dir `components/auth/` with `AuthSuccessPanel`, `GoogleAuthButton`, `AuthNotice`, `AuthCredentialsFields`.
    All 17 sub-components preserve the original parent `data-testid` names — testing suites need ZERO updates. Frontend live-verified in preview (4 pages + all flows). (`/app/test_reports/iteration_38.json`)
- **iter41 (Feb 28, 2026)**: **Order payout evidence — staff/admin sube captura del pago AL cliente**.
  - **Backend**: nuevos campos `payout_proof_image` y `payout_tx_hash` en el modelo `Order`. `PUT /admin/orders/{id}/status` ahora acepta esos campos. Validación obligatoria al marcar `completed`:
    - `transfer` → requiere `payout_proof_image` o devuelve `400 "Adjunta la captura del pago realizado al cliente"`.
    - `crypto` → requiere `payout_tx_hash` o `payout_proof_image` (al menos uno).
    - `cash` y `accumulate` → exentos.
    - Transiciones a `approved`/`rejected`/`pending` siguen sin exigir evidencia.
  - **Frontend admin** (`AdminOrders.jsx`): nuevo bloque en el dialog de detalle con input file (PNG/JPG, máx 4MB) + opcional TXID en órdenes crypto. Subida vía base64 → R2 (mismo helper `maybe_upload_proof("order_payouts")`).
  - **Frontend cliente** (`OrdersView.jsx`): cuando `status === "completed"` y existe `payout_proof_image` o `payout_tx_hash`, se muestra al cliente con badge verde "✓ Comprobante del pago realizado a ti" — texto explicativo + imagen clicable abriendo en pestaña nueva.
  - **Tests**: 7/7 nuevos casos en `tests/test_order_payout_evidence.py` (transfer-requires-proof, transfer-with-proof, crypto-requires-hash-or-proof, crypto-with-tx-hash, cash-exempt, accumulate-exempt, approved-does-not-require). `test_email_and_closing.test_completed_status_does_not_break` actualizado para enviar la captura. Backend total: **496 passed, 2 skipped** (`/app/test_reports/iteration_41.json` pending).
  - **Espejo del patrón** ya usado con éxito en retiros VIP (iter38). Cero nuevo riesgo arquitectónico, máxima consistencia.
- **iter40 (Feb 28, 2026)**: **Type Safety + Sentry coverage + Ternarios cosméticos + CI pipeline (P2 closure)**.
  - **Type hints + mypy**: created `/app/backend/mypy.ini` with `follow_imports = silent`, `check_untyped_defs = True`, and **`disallow_untyped_defs = True`** (strict for the scoped surface). Added explicit return types (`-> None`, `-> tuple[float, dict]`, `Dict[str, Any]`, `List[TransactionItem]`, `Callable[[], Any] -> Dict[str, Any]`) across `services/balances.py`, `services/orders_helpers.py`, `services/transactions.py`, `services/storage.py`, `services/health.py`, `server.py`. Pinned `db_client.db: Any` to neutralise motor-stubs false positives. Result: **`mypy --config-file mypy.ini` → Success: no issues found in 8 source files**. Any new function added to those files MUST be annotated.
  - **Sentry coverage**: removed 4 orphan `console.error/console.warn` from React bundle (`DefensiveModePanel.jsx` x2, `PushToggle.jsx` x2) and rerouted them to `captureError(err, { where, level })` from `@/sentry`. Service-worker registration keeps its console.error because it runs before the React bundle/Sentry SDK is initialised.
  - **Ternarios cosméticos**: extracted `WITHDRAWAL_LABELS_BY_METHOD` map + `getWithdrawalLabel(method, status)` helper in `VipView.jsx`. `OrdersView.jsx` already used STATUS_LABELS/STATUS_STYLES maps — no refactor needed.
  - **CI pipeline**: `/app/.github/workflows/ci.yml` with 3 parallel jobs:
    - `backend-mypy` → `python -m mypy --config-file mypy.ini`
    - `backend-tests` → MongoDB 7 service + uvicorn background + `pytest tests/`
    - `frontend-lint` → `yarn install --frozen-lockfile` + ESLint
    Triggers on push/PR to main/master/develop + manual `workflow_dispatch`. `concurrency` cancels in-flight runs. Failed pytest uploads uvicorn log as artifact. `mypy==2.1.0` pinned in `requirements.txt`.
  - Backend regression: **491/491 pytest green** after all P2 changes.


- **iter42 (Feb 28, 2026)**: **Heurística de método de entrega por nombre + Spanish error labels (P0 regression fix)**.
  - **`services/delivery_rules.py`** (NUEVO): single source of truth — reglas heurísticas que mapean moneda → métodos válidos. 3 niveles: (1) `delivery_methods=[…]` declarado explícito gana, (2) crypto → `["crypto"]`, (3) fiat → heurística por `name`/`code` con hints (`transferencia`/`transfer`/`zelle`/`pix`/`banco`/`wire` → solo `transfer`; `efectivo`/`cash`/`domicilio`/`billete` → solo `cash`; resto → ambos).
  - **`routes/orders.py::_assert_delivery_method_matches_currency`**: usa el helper compartido. Mensaje de error ahora con etiquetas humanas en español (`transferencia bancaria`, `efectivo`, `wallet cripto`) + tipo de moneda (`cripto`/`fiat`), p.ej. `"Para recibir CUP (fiat) solo se permite: transferencia bancaria, efectivo. La opción 'wallet cripto' no aplica."`.
  - **`ExchangeView.jsx`**: dropdown frontend ahora filtra opciones según `delivery_methods` o detecta el sub-tipo por nombre (CUPT/CUPE) — sin viajes extra al servidor para mostrar sólo lo válido.
  - **Tests fixed**: `test_cash_to_crypto_rejected` y `test_crypto_to_fiat_rejected` en `test_delivery_method_currency_match.py` (assertions sobre "cripto"/"wallet" y "fiat"/"transferencia" ahora aprobadas). Sub-typed coverage añadida en `test_subtyped_currency_delivery.py` (12 tests). `mypy --config-file mypy.ini` → **9 source files, 0 issues**.

- **iter43 (Feb 28, 2026)**: **P1 VIP-balance valuation fix + P2 mypy strict on `routes/*` + público `GET /api/currencies/{code}/delivery-methods`**.
  - **P1 — `services/balances.py::_convert_direct`**: ahora **prefiere la tasa inversa `USDT→code`** (la "tasa de valoración" del operador) sobre la directa `code→USDT` (que es la tasa de spread de orden). Esto desbloquea las 2 pruebas pre-existentes que fallaban:
    - `test_admin_alerts::test_threshold_crossing_sets_last_vip_alert_threshold` (5100 USD → 5204 USDT ≥ 5000 threshold ✓)
    - `test_multicurrency_and_stats::test_vip_legacy_plus_dict_usdt_conversion` (500 USD → 510.20 USDT ≈ 500/0.98 ✓)
    Endpoints afectados (todos contextos de valoración, no de ejecución): `/api/vip/balances`, `/api/admin/stats`, `/api/admin/revenue`, threshold de alerta.
  - **P2 — `mypy.ini`**: cobertura strict expandida de **9 → 24 archivos** (server.py + services/* + routes/*). Script `add_route_annotations.py` añadió `-> Any:` a 96 handlers/helpers; arreglos manuales en `admin.py` (`q: Dict[str, Any]`, `items: List[Dict[str, Any]]`, listas seed tipadas), `admin_users.py`, `admin_withdrawals.py`, `admin_company_funds.py`, `admin_revenue.py` (`_new_pair_bucket` ahora acepta `Optional[dict]`). Resultado: **`mypy --config-file mypy.ini` → 0 issues en 24 archivos**. CI ahora bloquea cualquier nuevo handler sin anotaciones.
  - **Nuevo endpoint público `GET /api/currencies/{code}/delivery-methods`** (`routes/market.py`): expone `allowed_delivery_methods()` como fuente de verdad para que el frontend (y futuros clientes) no dupliquen la heurística. Devuelve `{code, type, name, allowed: [...]}` — `accumulate` se omite intencionalmente (es role-gated, no un método físico).
  - **`ExchangeView.jsx`**: el `useEffect`/`useState` `allowedMethods` ahora consume el nuevo endpoint con cancellation guard; eliminadas las constantes JS duplicadas `TRANSFER_HINTS`/`CASH_HINTS`. Cualquier nueva sub-moneda (CUPT, CUPE, COP-Bancolombia, etc.) o cambio de heurística en backend se refleja automáticamente en el dropdown.
  - **Nuevos tests**: `test_currency_delivery_methods_endpoint.py` (8/8). Snapshot path-count actualizado a **83** en `test_iter27_auth_refactor.py`, `test_iter36_wiring.py`, `test_storage_iter35_e2e.py`.
  - **Backend regression**: **525/527 pytest verde** (2 skipped, 0 failed).

- **iter44 (Feb 28, 2026)**: **Admin override de métodos de entrega por moneda (checkbox-grid)**.
  - **Backend** (`routes/market.py`): `Currency` y `CurrencyCreate` modelos ahora aceptan `delivery_methods: Optional[list[Literal["transfer","cash","crypto"]]] = None`. Cuando se establece (lista no-vacía) gana sobre la heurística por nombre; cuando es `None` o `[]` se cae al heurístico. Validación Pydantic 422 para valores inválidos.
  - **Frontend** (`AdminCurrencies.jsx`): nuevo bloque `<Checkbox>` grid en el dialog de moneda (3 opciones: Transferencia bancaria / Efectivo / Cripto wallet) con texto explicativo. Bind a `form.delivery_methods` que persiste como array o `null` cuando el admin deja todo desmarcado. Testids: `cur-delivery-methods`, `cur-delivery-transfer`, `cur-delivery-cash`, `cur-delivery-crypto`.
  - **Tests**: 5/5 nuevos en `test_admin_currency_delivery_override.py` (crear con override, update para agregar, clear-override-cae-a-heurístico, 422 en valor inválido, lista vacía == sin override). Mypy 24/24 verde. ESLint verde. Path-count se mantiene en 83 (sin nuevos endpoints).

- **iter45–46 (Feb 28, 2026)**: **Mobile-first quick admin dashboard + Anti-scam analytics**.
  - **iter45 — `/admin/quick`** (`AdminQuickDashboard.jsx`): 4 cards apilados optimizados para celular: (1) Pendientes (count órdenes/retiros + 5 más recientes), (2) Fondos empresa (USDT-eq total + chips USDT/USD/CUP), (3) Acumulado VIP (USDT-eq + liquidez neta), (4) CTA grande "Ver órdenes pendientes". Acceso vía nav-item `Vista Rápida` (icon Zap).
  - **`GET /api/admin/quick-summary`**: nuevo endpoint dedicado que combina los 3 datasets en una sola request optimizada para mobile (lat. <100ms). Respeta `allowed_currencies` scope para staff role `employee`. 5 tests en `test_admin_quick_summary.py`.
  - **iter46 — Anti-scam analytics**: nuevo helper `services/anti_scam.py` con 3 funciones:
    - `mark_user_under_review(user_id)` — idempotente, sólo estampa `under_review_since` la primera vez.
    - `mark_user_active(user_id)` — calcula `last_under_review_hours` desde el timestamp anterior y lo persiste.
    - `compute_anti_scam_metrics()` — agrega `users_under_review`, `avg_resolution_hours`, `resolved_count`, `oldest_pending_hours`.
  - **Wired-in**: `routes/auth.py` (3 transiciones de creación/login) y `routes/blocklist.py` (bulk-import con pipelined `$cond` para preservar timestamps en re-blocks, `verify-phone-manual`, `reject-phone`).
  - **`GET /api/admin/health/summary`** ahora incluye `anti_scam: {...}` que la UI consume en una nueva sección "Anti-fraude · revisión de cuentas" con 4 StatCards (cola actual, tiempo medio, ticket más antiguo, resueltos histórico). Tone (warn/danger) automático según umbrales 24h/48h.
  - **Tests**: 5 en `test_anti_scam_metrics.py` (incluye end-to-end de `verify-phone-manual` con TOTP step-up). Mypy strict 25/25 archivos. ESLint limpio. **Path count: 84**. **540/542 pytest verde** (2 skipped, 0 failed).

- **iter47 (Feb 28, 2026)**: **Multi-currency display VIP en widgets legacy**.
  - **`MarketplaceView.jsx`**: el widget "Saldo" en marketplace ya NO muestra solo `vip_balance_usd` legacy. Ahora consume `GET /api/vip/balances` y muestra:
    - **Total en USDT** (valoración multi-moneda) como número grande.
    - Botón colapsable "N monedas" que despliega chips por divisa (USD, CUP, USDT, etc.) con el monto nativo de cada una.
    - Auto-refresh tras cada canje exitoso.
  - **`routes/admin_users.py::list_users`**: el endpoint admin ahora enriquece cada user normal/VIP con el campo `vip_balance_usdt` (suma legacy USD + dict balances vía valuación inverse-rate `USDT→code`). Staff (admin/employee) NO recibe el campo — `vip_balance_usd` en ellos es artefacto histórico irrelevante.
  - **`AdminUsers.jsx::renderUserBalance`**: ahora muestra `≈ {usdt_equivalent} USDT` debajo del breakdown nativo, dándole al staff un total inmediato sin un viaje extra a `/api/rates`.
  - **Tests**: 5/5 en `test_admin_users_multicurrency_display.py` (legacy-only, dict-only, ambos sumados, zero-balance, staff-no-enrich). Mypy strict 25/25 archivos. ESLint limpio. Path-count: 84 sin cambios. **545/547 pytest verde** (2 skipped).

- **iter48 (Feb 28, 2026)**: **Auto-conversión VIP CUP → USDT (instant self-conversion)**.
  - **Backend**: nuevo endpoint **`POST /api/vip/convert`** en `routes/orders.py` con payload `{from_code, to_code, amount_from}`. Reasigna fondos atómicamente entre las propias monedas del VIP — sin aprobación admin, sin delivery físico. Usa la tasa VIP cuando aplica.
    - Maneja tasas direccionales: si no existe `(from→to)`, usa la inversa `1/(to→from)` (consistente con la lógica de valuación de balances). Esto desbloquea el caso clásico CUP→USDT cuando solo se cotiza USDT→CUP.
    - Validaciones: cuenta activa, defensive-mode, monedas distintas, saldo suficiente, tasa cotizada (cualquier dirección), monto positivo.
    - Audit-loggeado con acción `vip.convert` (actor_id, from/to, amount, rate).
  - **Frontend (`MarketplaceView.jsx`)**: cada chip de divisa en el breakdown (excepto USDT) ahora tiene un ícono `ArrowRightLeft` que abre un dialog "Convertir {code} → USDT" con input + botón MÁX + confirmación. Auto-refresca el saldo tras éxito.
  - **Tests**: 8/8 en `test_vip_convert.py` (happy-path, insuficiente, misma moneda, sin tasa, employee rechazado, no auth, validación monto, audit log).
  - **Path count: 85** (actualizado en los 3 snapshot tests). Mypy strict 25/25. ESLint limpio. **553/555 pytest verde**.

- **iter49 (Feb 28, 2026)**: **Auto-conversión VIP — dropdown destino + preview en vivo**.
  - **Frontend (`MarketplaceView.jsx`)**:
    - Dialog de conversión ahora con `<Select>` para elegir moneda destino (cualquier moneda activa excepto la origen). Reemplaza el hardcoded `→ USDT`. El default es USDT (excepto cuando convirtiendo desde USDT, donde toma la primera otra activa).
    - **Preview en vivo**: card que muestra "Recibirás X {to_code} @ tasa Y" mientras el usuario escribe el monto. Cálculo client-side replica exactamente la lógica del backend (`computeRate`: directa primero, inversa como fallback, `rate_vip` para VIP/admin, `rate_normal` para normales).
    - Botón "Confirmar" deshabilitado cuando no hay tasa cotizada (UX cleaner — antes el usuario hacía el round-trip y veía un error).
    - Botón Convertir ahora visible TAMBIÉN en el chip USDT (antes oculto). Cualquier moneda↔cualquier moneda.
  - **Tests backend**: 2 nuevos en `test_vip_convert.py` cubriendo direcciones reverse (USDT→CUP usa tasa directa 395) y cross-fiat (USD→CUP usa tasa directa 395). **10/10 vip_convert tests pasando.** Mypy strict 25/25. ESLint limpio. Path-count: 85 sin cambios.
  - **End-to-end verificado via curl** contra ingress público: USDT→CUP=395, USDT→USD=0.99, CUP→USDT=1/395 inverse.

- **iter50 (Feb 28, 2026)**: **Widget convertidor en Dashboard principal (normal + VIP)**.
  - **Nuevo componente reusable `BalanceConverterCard.jsx`** (`/app/frontend/src/components/`):
    - Self-contained: fetches sus propios `vip/balances`, `rates`, `currencies`.
    - Renderiza tarjeta con título "Convertir Saldos" + breakdown de hasta 3 monedas (botón "Ver todas" si hay más) + botón inline "Convertir" en cada fila.
    - Dialog con dropdown destino + preview en vivo + botón MÁX + submit. Mismo UX que iter49.
    - Acepta `onConverted` callback para refrescar el padre.
    - Si no hay saldo positivo, muestra estado empty inviting "Recibe pagos en transferencia/efectivo…".
    - Empleados (`role=employee`) NO ven el widget (devuelve `null`).
  - **`OverviewView.jsx`**: agrega el card entre los StatCards y la grid de tasas/acciones. Visible para `isClient` (normal + VIP, no staff).
  - **`MarketplaceView.jsx`**: refactor — elimina toda la lógica inline de conversión (state, helpers, dialog) y usa el nuevo componente. -300 líneas duplicadas.
  - **Backend**: nuevo test `test_normal_role_can_convert_uses_rate_normal` verifica que usuarios normales pueden convertir y usan `rate_normal` (no `rate_vip`). **11/11 tests vip_convert verde.**
  - **104/104 tests relacionados pasando.** Mypy strict 25/25. ESLint limpio. Path-count: 85 sin cambios.

- **iter51 (Feb 28, 2026) — BUG FIX P0**: **Saldo perdido en órdenes `pending → completed` directas (sin pasar por `approved`)**.
  - **Root cause**: `services/orders_helpers.run_post_status_side_effects` solo disparaba `accumulate_vip_balance` cuando `new_status == "approved"`. Si el admin clickeaba "Completar" directamente sobre una orden pendiente (saltándose el botón "Confirmar"), la orden saltaba `pending → completed` y el saldo NUNCA se acreditaba.
  - **Caso del cliente**: O'brayan cambió 2 transferencias Zelle → CUPT con método "acumular". Solo una se acreditó porque a la otra el admin le hizo "Completar" directo.
  - **Fix**: 
    - `services/balances.accumulate_vip_balance` ahora es **idempotente** vía flag atómico `accumulated_at` en el doc de la orden. Devuelve `True/False` indicando si aplicó.
    - `run_post_status_side_effects` ahora dispara en CUALQUIER primera transición a estado "money-settled" (`approved` O `completed`), no solo `approved`. Idempotencia garantiza no double-credit en `pending → approved → completed`.
  - **Script de remediación**: `/app/backend/scripts/backfill_accumulate_balances.py` con `--dry-run` y `--apply` para acreditar retroactivamente las órdenes que perdieron el saldo. Idempotente — seguro re-ejecutar.
  - **Tests**: 6/6 nuevos en `test_accumulate_idempotent.py` (pending→completed directo, pending→approved→completed sin double-credit, dos órdenes con paths mixtos, flag persiste, rejected no acredita, helper directo idempotente). Mypy 25/25. Path-count sin cambios.

- **iter52 (Feb 28, 2026)**: **Audit Log de Saldos (admin + cliente)**.
  - **Backend**: 2 endpoints nuevos basados en el helper compartido `_build_balance_ledger`:
    - `GET /api/vip/balance-ledger` — self-service (normal + VIP, NO empleados). Lista todas las órdenes `accumulate` propias acreditadas (con `accumulated_at` set), agrupadas por divisa destino. Cada bucket trae `total` y la lista de órdenes con `id`, `from_code`, `amount_from`, `amount_to`, `status`, `accumulated_at`, `created_at`, `sender_name`.
    - `GET /api/admin/users/{user_id}/balance-ledger` — drill-down para staff sobre CUALQUIER usuario.
  - **Frontend cliente (`VipView.jsx`)**: cada tarjeta de divisa en "Saldo por moneda" ahora es **clickeable** (cuando tiene órdenes acreditadas) y abre un dialog con el desglose orden-por-orden. Muestra `+amount`, fecha de acreditación, status, ID, sender_name. Header del card muestra "N órdenes acreditadas en total".
  - **Frontend admin (`AdminUsers.jsx` + nuevo `users/AdminUserLedgerDialog.jsx`)**: ícono `History` junto al saldo de cada cliente abre un dialog con tabs por divisa, total por bucket y lista detallada de órdenes contributoras. Útil para resolver disputas tipo "envié Zelle dos veces pero solo aparece uno".
  - **Tests**: 8/8 nuevos en `test_balance_ledger.py` (auth required, excluye órdenes no-acreditadas/sin `accumulated_at`, excluye no-accumulate, agrupa correctamente, self-endpoint scope). Mypy strict 25/25. ESLint limpio (3 archivos). **Path count: 87**. **570/572 pytest verde** (2 skipped).

- **iter53 (Feb 28, 2026)**: **Code review cleanup — false positives identificados + correcciones legítimas aplicadas**.
  - **Verificación de hallazgos críticos del reporte**:
    - ❌ "3 undefined Python variables" → pylint/pyflakes/ruff reportan código **10.00/10 limpio**. Falso positivo.
    - ❌ "63 missing React hook dependencies" → ESLint con `react-hooks/exhaustive-deps` (regla oficial) pasa **limpio**. Los items reportados (API, axios, PAGE_SIZE) son identificadores module-level que NO deben ir en deps según la doc oficial de React.
  - **Correcciones legítimas aplicadas**:
    - **Unused imports en producción** (8 archivos): `revenue_report.py` (OrderedDict), `pdf_service.py` (mm, TA_LEFT, TA_RIGHT, TA_CENTER, PageBreak, Image), `admin_alerts.py` (asyncio), `scheduler.py` (global no necesario), `routes/orders.py` (Order), `routes/auth.py` (json, base64), `services/health.py` (Optional), `services/orders_helpers.py` (build_rate_lookup).
    - **`BalanceConverterCard.jsx`**: `positive` (filter) y `visible` (slice) ahora son `useMemo` con deps correctas — evita recálculo en cada apertura/cierre del dialog. Hooks colocados **antes** del early-return para cumplir rules-of-hooks.
  - **Testing**: `testing_agent_v3_fork` ejecutó la suite completa — **570 passed / 0 failed / 2 skipped (idéntico al baseline de iter52)**, smoke suite dirigida 53/53 verde, path-count canary 87, public ingress 200 OK. **Cero regresiones**. Mypy strict 25/25.

- **iter54 (Feb 28, 2026)**: **Company Fund Adjustments — Entradas y salidas manuales de capital de trabajo (P0 shipped)**.
  - Backend: nuevos endpoints `POST/GET /api/admin/company-funds/adjustments` con permiso granular `can_manage_company_funds`, TOTP obligatorio, validación de catálogo y scope por moneda. Modelos `CompanyFundAdjustment` (inflow/outflow, method, source_name, source_account, note, actor). `_compute_company_funds` ahora incluye `manual_inflow`/`manual_outflow` en el balance.
  - Bug fix crítico: `insert_one(doc)` mutaba el dict añadiendo `_id: ObjectId` → 500 al serializar. Fix: insertar copia `{**doc}` y devolver el `doc` original.
  - Frontend: `AdminCompanyFunds.jsx` — botón "Ajuste manual" abre `AdjustmentDialog` (toggle Entrada/Salida, selector moneda, método, fuente, 2FA). Nueva sección "Ajustes manuales de capital" con `AdjustmentsTable` — historial cronológico. Cards muestran "Aporte propio" (verde) y "Salida propia" (rojo).
  - Testing: 16/16 en `test_company_fund_adjustments.py`. Path count 87→88 en 3 canaries. Testing agent E2E green (`iteration_40.json`).

- **iter55.14 (Mar 3, 2026)**: **SEO hygiene — Google Search Console warnings resueltos**.
  - **Reportes recibidos**: (1) "No se ha encontrado (404)" — crawler hitting private routes returned blank HTML; (2) "Página con redirección"; (3) "Duplicada: sin canonical".
  - **Fixes en 3 archivos estáticos**:
    - **`/public/robots.txt`** (nuevo): Disallow `/dashboard`, `/admin`, `/api/`, `/auth`, `/verify-email`, `/reset-password`, `/oauth`, `/2fa`, `/service-worker.js`. Allow solo home + assets estáticos. Directiva `Sitemap:` apuntando al sitemap.xml. Cloudflare prepende su AI-crawler blocklist (aditivo, sin conflicto).
    - **`/public/sitemap.xml`** (nuevo): un solo `<url>` canónico → `https://p2p.resiliencebrothers.com/`. Todo lo demás es SPA privado que no debe indexarse.
    - **`/public/index.html`**: agregado `<link rel="canonical" href="https://p2p.resiliencebrothers.com/">`, `<meta name="robots">`, `<meta name="googlebot">`, `<meta property="og:url">`, tarjetas Twitter (`twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`).
  - **Testing**: `testing_agent_v3_fork` verificó los 9 checks — robots.txt directives presentes, sitemap.xml XML válido, canonical + og:url + twitter + robots/googlebot meta correctamente servidos, SPA sigue renderizando sin regresiones (`/app/test_reports/iteration_43.json`).

- **iter55.13 (Mar 2, 2026)**: **Badge visual de red crypto en admin (lista + modal)**.
  - Nuevos helpers `extractCryptoNetwork()` y `NETWORK_META` con colores oficiales (BEP20 amarillo, TRC20 rojo, ERC20 azul, POLYGON morado, SOL mint, BTC naranja).
  - Vista lista `/admin/orders` muestra mini-badge de red en la columna Entrega. Modal muestra badge grande con borde izquierdo del color oficial + frase contextual.
  - 34/34 tests unitarios verdes.


  - Nuevos helpers en `delivery_validators.js`: `extractCryptoNetwork(details, method)` y `NETWORK_META` (paleta de colores oficiales).
  - **Colores oficiales**: BEP20 `#F0B90B` Binance yellow · TRC20 `#FF060A` Tron red · ERC20 `#627EEA` Ethereum blue · POLYGON `#8247E5` Matic purple · SOLANA `#14F195` mint · BTC `#F7931A` Bitcoin orange · AMBIGUOUS_0X `#EF4444` (rojo alerta).
  - **Vista lista `/admin/orders`**: columna Entrega ahora muestra el método + un mini-badge de red (12px) en el color oficial. Un vistazo distingue todas las redes en la cola.
  - **Modal detalle**: badge grande con borde izquierdo del color de la red, label completo (`BEP20 · BSC`) y frase contextual (`Enviar en la red BEP20. Verifica que el wallet destino la acepte.`). Si el 0x no declaró red → badge rojo `⚠ Red no declarada` + `Contacta antes de enviar.`
  - **Testing**: 34/34 tests unitarios verdes (10 nuevos para `extractCryptoNetwork` y `NETWORK_META`). Verificado E2E con 4 órdenes seed (BEP20/TRC20/ERC20/BTC) — todas las combinaciones renderizan con el color correcto tanto en lista como en modal. ESLint limpio.

- **iter55.12 (Mar 2, 2026)**: **Selector explícito de red crypto (bloqueo de submit)**.
  - Dropdown obligatorio `data-testid="crypto-network-select"` en `ExchangeView.jsx` cuando `method=crypto`.
  - Auto-inyecta `Red: XXX` en `deliveryDetails`. Botón "Confirmar Orden" deshabilitado sin red seleccionada.
  - Opciones: BEP20 (recomendada), TRC20, ERC20, POLYGON, SOLANA, BTC.


  - **Motivación**: BEP20/ERC20/POLYGON comparten formato 0x — el keyword-in-text de iter55.11 mitiga pero no elimina el riesgo. Un dropdown fuerza la decisión.
  - **Nuevo Select** `data-testid="crypto-network-select"` que aparece solo cuando `method=crypto` o `toCurr.type=crypto`:
    - Opciones: **BEP20 · Binance Smart Chain (recomendada)**, TRC20 · Tron, ERC20 · Ethereum, POLYGON · Matic, Solana, Bitcoin.
    - Al seleccionar → auto-inyecta/reemplaza la línea `Red: XXX` en el `deliveryDetails` (elimina cualquier línea `Red:` previa antes de agregar la nueva).
    - Label marcado con `*` rojo + texto "(obligatorio)".
    - Nota de advertencia: `Enviar a la red equivocada resulta en pérdida total de los fondos. Verifica que tu wallet acepte esta red antes de confirmar.`
  - **Bloqueo del submit**: `disabled = submitting || (method=crypto && !cryptoNetwork) || (toCurr.type=crypto && method!=accumulate && !cryptoNetwork)`. Botón "Confirmar Orden" ahora muestra estado gris cuando falta la red.
  - Reset automático de `cryptoNetwork` al cambiar de método (fuera de crypto) o al crear nueva orden.
  - **Testing**: verificado E2E con Playwright — sin red: submit disabled + warning rojo. Con BEP20 seleccionado: submit enabled + feedback verde. Estados persistentes tras cambio de método. ESLint limpio.

- **iter55.11 (Mar 2, 2026)**: **Soporte BEP20 (Binance Smart Chain) en validador crypto**.
  - Validador crypto extendido: detecta keywords `BEP20`/`BSC`/`Binance Smart Chain`, `ERC20`/`ETH`, `POLYGON`/`MATIC` en el texto.
  - Sin keyword → warning: `⚠ Dirección 0x válida pero falta indicar la RED (BEP20, ERC20 o POLYGON)`.
  - Hint USDT: `Wallet USDT. Redes soportadas: BEP20 (recomendada), TRC20, ERC20`.
  - 24/24 tests unitarios verdes (4 nuevos).


  - **Requerido por operador**: BEP20 es la red USDT más usada por sus clientes en Cuba (bajos fees vs ERC20).
  - **Reto**: BEP20 y ERC20 comparten el mismo formato de dirección (`0x` + 40 hex) — la dirección sola es ambigua. Enviar BEP20 a un wallet ERC20-only pierde los fondos → **CRÍTICO**.
  - **Solución**: el validador crypto ahora requiere que el usuario declare la red en el texto (keywords: `BEP20`/`BSC`/`Binance Smart Chain`, `ERC20`/`ETH`, `POLYGON`/`MATIC`). Sin keyword → warning explícito.
  - **Nuevos feedbacks**:
    - `0x...` + `BEP20`/`BSC` → `✓ Dirección BEP20 (Binance Smart Chain) válida`
    - `0x...` + `ERC20`/`ETH` → `✓ Dirección ERC20 (Ethereum) válida`
    - `0x...` + `POLYGON`/`MATIC` → `✓ Dirección POLYGON válida`
    - `0x...` sin red → `⚠ Dirección 0x válida pero falta indicar la RED (BEP20, ERC20 o POLYGON)`
  - **Hint USDT actualizado**: `Wallet USDT. Redes soportadas: BEP20 (recomendada), TRC20, ERC20. Indica la red junto a la dirección.` + placeholder con ejemplos de ambos formatos.
  - **Testing**: 24/24 tests (4 nuevos específicos para BEP20/aliases/red-ambigua). Verificado E2E en preview: sin red → warning, con `Red: BEP20` → verde.

- **iter55.10 (Mar 2, 2026)**: **Módulo central de validadores de delivery_details (9 combos)**.
  - Nuevo `frontend/src/services/delivery_validators.js` con validadores para CUP/CUPT/CUPE (transfer 16 díg + cash), MXN (CLABE 18), BRL (PIX), ZELLE (email/phone US), USD, COP, EUR (IBAN), AED, crypto (TRC20/ERC20/BTC/Solana).
  - Refactor `ExchangeView.jsx` y `AdminOrders.jsx` para consumir el módulo. Botón "Copiar wallet" nuevo en admin.
  - 20 tests unitarios Jest/CRA (`services/__tests__/delivery_validators.test.js`).


  - **Motivación**: extender el patrón CUP/16-dígitos a todas las monedas/redes del catálogo (mejora sugerida en iter55.9).
  - Nuevo `frontend/src/services/delivery_validators.js` (~180L, pura lógica) que exporta `getDeliveryValidator(toCode, method, currencyType)` y `getDeliveryBadge(...)`.
  - **Cobertura**:
    - **CUP/CUPT/CUPE transfer**: 16 dígitos.
    - **CUP/CUPE cash**: nombre + teléfono cubano (+53 XXXX XXXX) + dirección.
    - **MXN transfer**: CLABE de 18 dígitos.
    - **BRL transfer**: PIX (email / CPF 11 / CNPJ 14 / teléfono / UUID).
    - **ZELLE transfer**: email o teléfono US.
    - **USD transfer**: routing 9 + cuenta.
    - **COP transfer**: cédula + banco + cuenta.
    - **EUR transfer**: IBAN europeo (regex `[A-Z]{2}\d{2}...`).
    - **AED transfer**: IBAN AE + 21 dígitos.
    - **crypto/wallet**: universal — TRC20 (`T...`), ERC20 (`0x...`), BTC (`bc1.../1.../3...`), Solana (base58 32-44).
  - Cada validador expone `hint`, `icon`, `example` (usado como placeholder) y `validate(text, ctx)` que retorna `{ok, feedback}` o `null` para input vacío.
  - `ExchangeView.jsx` (cliente) y `AdminOrders.jsx` (staff) ahora ambos consumen el módulo — mismo comportamiento en creación y procesamiento.
  - Botón "Copiar wallet" agregado para método crypto (extrae dirección con regex y muestra ellipsis: `Copiar wallet (TXYZ…4567)`).
  - Botón "Copiar cuenta" ahora funciona también para CLABE MXN (18 dígitos).
  - **Testing**: 20/20 tests unitarios en `services/__tests__/delivery_validators.test.js` (Jest via CRA). Verificado end-to-end en preview con USDT→MXN (CLABE) mostrando "✓ 18 dígitos (CLABE)". ESLint limpio.

- **iter55.8 (Mar 1, 2026)**: **Cliente veía "No autorizado" al abrir comprobante del pago recibido**.
  - **Root cause**: `routes/files.py::_can_access` verificaba `orders.proof_image` y `withdrawals.payout_proof_image` pero NO `orders.payout_proof_image` (comprobante que sube staff al completar orden P2P). Cliente dueño de la orden → 403.
  - **Fix**: 3ª comprobación en `_can_access` para permitir acceso del dueño a `orders.payout_proof_image`. Tests 3/3.


  - **Root cause**: `routes/files.py::_can_access` verificaba `orders.proof_image` (comprobante que sube el cliente al crear orden) y `withdrawals.payout_proof_image` (retiros VIP), pero **NO** `orders.payout_proof_image` (el nuevo campo donde staff sube el comprobante al completar la orden P2P). Cliente dueño de la orden → 403.
  - **Fix**: agregada la tercera comprobación en `_can_access` para permitir que el dueño de la orden acceda a su propio `payout_proof_image`.
  - **Tests**: 3/3 en `test_iter55_8_payout_proof_access.py` — el dueño puede acceder (no 403), otro cliente sigue bloqueado con 403 (owner check funciona), staff bypasea siempre.

- **iter55.7 (Mar 1, 2026)**: **Whitespace en códigos de moneda: propagación a rates/orders + colapso de balances**.
  - **Bugs reportados por el operador tras redeploy**:
    1. Cliente intenta orden USDT→CUP EFECTIVO → **"Tasa de cambio no disponible para ese par"** aunque la tasa está en la tabla. Root cause: la fila de tasa tenía `to_code="CUP "` (con espacio) porque migración anterior de iter55.3 solo limpió `db.currencies`, no `db.rates`.
    2. Sección Fondo Empresa mostraba **dos filas CUP EFECTIVO separadas** — una negativa (órdenes viejas con `to_code="CUP "`) y otra positiva (ajuste manual nuevo con `"CUP"`). Root cause: `_compute_company_funds` agrupaba por `code` exacto, no normalizado.
  - **Fix (3 capas)**:
    1. **`resolve_order_rate`** ahora es lenient: si el lookup exacto falla, cae a regex case-insensitive tolerante a whitespace en `from_code` Y `to_code`.
    2. **`_compute_company_funds`** normaliza cada código con `_norm(c).strip().upper()` **antes** de agregar → filas con `"CUP"` y `"CUP "` colapsan en una sola fila `CUP`.
    3. **Migración expandida al startup** (`server.py`): además de `db.currencies`, ahora limpia whitespace en `db.rates.{from_code,to_code}`, `db.orders.{from_code,to_code}`, `db.withdrawals.currency`, `db.company_withdrawals.currency` y `db.company_fund_adjustments.currency`. Idempotente, no-op tras primera corrida.
  - **Tests**: 3/3 en `test_iter55_7_currency_whitespace_e2e.py` — reproduce el bug operativo (corromper `to_code="CUP "`, cliente envía `"CUP"`, orden debe ser 200) + verifica el colapso de filas CUP en `/admin/company-funds`. Regresión completa 90/91 en baterías relevantes. Mypy 25/25.

- **iter55.6 (Mar 1, 2026)**: **In-app notifications ahora también se crean para rate changes y order status transitions**.
  - **Root cause reportado por el operador**: cliente con push activo (campanita verde) vio "No tienes notificaciones · Todo al día" en la bandeja in-app tras cambio de tasa. Los helpers `_fanout_rate_change_push` y `send_client_order_push` SOLO enviaban push OS, no creaban entradas en `db.notifications`.
  - **Fix**: `_fanout_rate_change_push` renombrado a fanout dual — primero inserta en la bandeja de TODOS los clientes activos (role vip/normal, no suspendidos) sin importar si tienen push subscription; luego envía push solo a los que sí opted-in. Admin/staff **excluidos por diseño** (no se notifican a sí mismos). Los tests confirman scope: `test_admin_does_NOT_get_inbox_entry` verifica el gate.
  - Nuevo helper `create_inapp_order_notification` en `services/orders_helpers.py` — se llama en `run_post_status_side_effects` junto a `send_client_order_push`. Genera entrada con `type=order_approved|order_completed|order_rejected` y `data.order_id` para deeplink. Copy contextual por `delivery_method`.
  - **Testing**: 5/5 en `test_iter55_6_inapp_notifications.py` — VIP + normal reciben inbox con tasa correspondiente a su rol; admin no; endpoint `/api/notifications` devuelve las entradas; order approved/completed transitions crean sus respectivas notificaciones. Logs claros: `[rate-fanout] {pair}: clients=N inapp=N push_sent=M push_dead_pruned=X push_skipped=Y`.

- **iter55.5 (Mar 1, 2026)**: **Fanout de tasa robustecido + endpoint diagnóstico**.
  - `POST /admin/rates` (upsert) ahora también dispara `_fanout_rate_change_push` (antes solo lo hacía el PUT).
  - Logging detallado en el fanout para diagnosticar en producción.
  - Nuevo endpoint `GET /api/admin/push/stats` (staff-only): total_subscriptions, by_role, client_subscriptions, sample_last_5.
  - Path count 88→89. 20/20 tests verdes.


  - **Root cause**: catálogo de producción tenía `"CUP "` (con espacio final) por typo de data-entry. `db.currencies.find_one({"code": "CUP"})` no lo encontraba → 400 "no disponible en el catálogo". Preview no lo mostraba porque su catálogo era limpio.
  - **Fix defensivo (3 capas)**:
    1. **Validators pydantic** en `Currency`/`CurrencyCreate`: `code` se normaliza con `.strip().upper()` al validar → nuevos códigos jamás pueden entrar con whitespace.
    2. **`_find_currency_lenient(code)`** en `market.py`: busca primero exacto; si falla, cae a regex case-insensitive `^\s*{code}\s*$`. Usado también en `admin_company_funds.create_company_fund_adjustment`.
    3. **`GET /api/currencies`** normaliza en cada respuesta: `code.strip().upper()` para no exponer whitespace legacy al frontend.
  - **Migración one-shot al startup**: `server.on_event('startup')` busca `code` con whitespace y hace `strip().upper()` en su lugar (idempotente, log info por cada fix). Corre en cada arranque pero es no-op si ya está limpio.
  - **Tests**: 5/5 en `test_iter55_3_currency_lenient.py` — con `CUP ` corrupto, lookup lenient permite el ajuste; endpoint `/currencies` devuelve normalizado; endpoint `/delivery-methods` no rompe; input lowercase `cup` funciona; mensaje de error para código truly-missing sigue informativo.
  - **También iter55.2 shipped**: doble X en drawer móvil (Dashboard + AdminPanel) — `SheetContent` de shadcn ya tiene su propio X. Eliminado el X custom + limpieza de imports. Testing agent E2E green (`iteration_42.json`).

- **iter55 (Mar 1, 2026)**: **Fondo Empresa + Registry + Push notifications (3 issues reportados por el operador)**.
  - Bug 1: `_compute_company_funds` no descontaba `amount_to` de órdenes `completed` con `delivery_method IN (transfer, cash, crypto)`. Fix + nuevo campo `outflow_orders`. `accumulate` NO se resta.
  - Bug 2: `build_transactions` no emitía filas de salida P2P. Fix: `ref_type='order_payout'` visible en `/admin/transactions` y `/dashboard/transactions`.
  - Feature 3a: push cuando orden pasa a `completed` (copy contextual por delivery_method).
  - Feature 3b: rate-change fanout a subscripciones de rol vip/normal (staff excluidos), tag por par → dedupe. Best-effort.
  - Tests: 17/17 en 2 archivos nuevos, suite completa 603/605, testing_agent_v3_fork E2E green (`iteration_41.json`).

- **iter55.1 (Mar 1, 2026)**: **Mensajes de error diagnósticos**.
  - Backend: mensaje de moneda no encontrada ahora incluye el código exacto enviado **entre comillas francesas** y lista todas las monedas válidas activas.
  - Frontend `PushToggle.jsx`: catch específico por `err.name` — `NotAllowedError`/`NotSupportedError`/`AbortError`/`InvalidAccessError` cada uno con mensaje accionable en el toast. Distingue error del navegador vs error del servidor vs VAPID no configurada. Facilita el diagnóstico remoto.


  - **P0 Bug 1 — Fondo Empresa no descontaba salidas P2P**: cuando un cliente completaba un intercambio (ej. USDT→CUP transferencia), la empresa físicamente pagaba el CUP pero el balance no se movía. Fix: `_compute_company_funds` ahora resta `amount_to` (en `to_code`) de todas las órdenes con `status='completed'` Y `delivery_method IN (transfer, cash, crypto)`. **`accumulate` NO se resta** (el dinero se queda en caja como pasivo VIP y se contabiliza cuando el cliente hace withdrawal). Nuevo campo en la response: `outflow_orders`. Fórmula: `balance = inflow + manual_inflow − outflow_orders − outflow_clients − outflow_company − manual_outflow`.
  - **P0 Bug 2 — Registro de transacciones incompleto**: `build_transactions` no registraba las entregas P2P. Fix: nuevas filas `direction='out'` con `ref_type='order_payout'` (currency=`to_code`, amount=`amount_to`, holder=cliente, method=`delivery_method`). Filtrable por currency/direction, exportable a CSV/PDF, visible en `/admin/transactions` (staff) y `/dashboard/transactions` (cliente).
  - **Feature 3 — Push notifications**:
    - **Order completed**: nuevo helper `build_order_completed_payload` con copy contextual según delivery_method (`accumulate`→"acreditó a tu saldo VIP", `transfer`→"transferimos X a tu cuenta", `crypto`→"enviamos a tu wallet", `cash`→"efectivo entregado"). Disparado en la transición `→ completed` (email queda solo para approved/rejected).
    - **Rate change fanout**: `PUT /admin/rates/{id}` ahora ejecuta `_fanout_rate_change_push` best-effort — envía push solo a subscripciones de rol `vip`/`normal` (staff/admin excluidos), con la tasa que aplica a cada rol (rate_vip vs rate_normal). No-op si ni `rate_normal` ni `rate_vip` cambiaron. Tag por par de monedas → reemplaza notificaciones anteriores del mismo par en el dispositivo.
  - **Frontend**: `AdminCompanyFunds.jsx` — nueva línea "Entregado a clientes" (roja) en las cards + balance rojo cuando es negativo + subtítulo actualizado. `TransactionDetailModal.jsx` — muestra "Comprobante del pago al cliente" cuando `ref_type='order_payout'` (payout_proof_image), label "ID Orden", botón "Ir a Órdenes". `MyTransactions.jsx` (cliente) — muestra "Comprobante del pago recibido".
  - **Testing**: 2 nuevos test files — `test_iter55_order_outflows.py` (7/7) y `test_iter55_push_notifications.py` (10/10 — payload builders, endpoint 200, unit test del role gating con FakeDB). Suite completa: **603 passed / 0 failed / 2 skipped**. Mypy strict 25/25. ESLint limpio. `testing_agent_v3_fork` E2E backend + frontend verificó 55/55 checks green (`/app/test_reports/iteration_41.json`).


  - **Backend** (`routes/admin_company_funds.py`):
    - Nuevos modelos: `CompanyFundAdjustment` (persistido) y `CompanyFundAdjustmentCreate` (payload).
    - Nuevo permiso granular `users.can_manage_company_funds` (admin siempre autorizado; empleados requieren flag explícito).
    - `POST /api/admin/company-funds/adjustments` — registra un movimiento manual con `adjustment_type` (`inflow`/`outflow`), `currency`, `amount>0`, `method` (`transfer`/`cash`/`crypto`), `source_name`, `source_account`, `note`. TOTP step-up obligatorio. Validaciones: moneda existe en catálogo (400 con "catálogo" en el detail), scope de empleados por `allowed_currencies` (403). Audit-logged como `company_funds.adjust` con sign `+`/`-` en el summary.
    - `GET /api/admin/company-funds/adjustments?currency=&limit=` — historial ordenado por fecha desc; empleados scoped a sus `allowed_currencies`; normal client rechazado (403).
    - `GET /api/admin/company-funds` — response schema ahora incluye `manual_inflow` y `manual_outflow` por moneda. Fórmula del balance: `inflow + manual_inflow − outflow_clients − outflow_company − manual_outflow`.
    - **Bug fix crítico durante desarrollo**: `db.company_fund_adjustments.insert_one(doc)` mutaba el dict añadiendo `_id: ObjectId`, rompiendo la serialización JSON del response (500). Fix: insertar copia superficial `{**doc}` y devolver el `doc` original limpio.
  - **Frontend** (`AdminCompanyFunds.jsx` + 2 subcomponentes nuevos `pages/admin/company-funds/`):
    - Cards de "Capital operativo" ahora muestran líneas dedicadas para **`+ Aporte propio`** (verde) y **`− Salida propia`** (rojo) — solo cuando existen. Balance en rojo si es negativo.
    - Nuevo botón "Ajuste manual" (junto a "Nuevo retiro") abre `AdjustmentDialog.jsx`: toggle grande **Entrada/Salida** (verde vs rojo), select de moneda (todas activas, filtradas por `allowed_currencies` para empleados), monto, método, `source_name` y `source_account` (label dinámico según método), nota, botón "Continuar (2FA)".
    - Nueva sección "Ajustes manuales de capital" con `AdjustmentsTable.jsx` — historial cronológico con badge coloreado por tipo, monto con sign explícito, método traducido, fuente/cuenta apilada, autor, nota.
    - Endpoint público `/api/currencies` alimenta el dropdown para permitir aportes en monedas sin flujo previo.
  - **Tests**: 16/16 en `tests/test_company_fund_adjustments.py` (POST admin/staff/normal, TOTP obligatorio, catálogo, amount>0, employee-perm gate, filter por moneda, cálculo balance con inflow/outflow). Path-count canary actualizado **87 → 88** en 3 tests (`test_iter27_auth_refactor.py`, `test_iter36_wiring.py`, `test_storage_iter35_e2e.py`). Mypy strict 25/25. ESLint limpio. `testing_agent_v3_fork` E2E backend + frontend **fully green** (`/app/test_reports/iteration_40.json`).


## Prioritized Backlog
### P0 — Waiting on user

### P1 — Prioritized next
- **Self-service appeal flow** para usuarios `under_review`: banner en dashboard + formulario + cola staff con `can_manage_blocklist`.

### P2 — Backlog
- **🪙 Wallets crypto on-chain (USDT-TRC20 + USDT-BEP20)** — **POSPUESTO por el usuario (Jul 4, 2026)** hasta disponer de un wallet frío (Ledger/Trezor/air-gapped) para generar la seed offline sin exponerla en `.env`. Justificación del usuario: mayoría de clientes son cubanos y **crypto es la vía principal de entrada de fondos** (Stripe/tarjetas no viables en Cuba), pero prioriza la seguridad de la seed sobre la velocidad de entrega.
  - **Diseño técnico ya validado (via integration_playbook_expert_v2, iter45):**
    - HD wallet BIP44: `m/44'/195'/0'/0/i` (Tron) + `m/44'/60'/0'/0/i` (BSC), librería `bip-utils` (pure-Python, sin C ext.)
    - APIs: TronGrid `v1/accounts/{addr}/transactions/trc20` + BscScan `module=account&action=tokentx&contractaddress=0x55d398326f99059fF775485246999027B3197955`
    - Polling: APScheduler cada 15s solo sobre órdenes `status=pending_deposit`
    - Auto-aprobación con **≥19 confirmaciones (TRC20)** y **≥15 confirmaciones (BEP20)**
    - Idempotencia: unique index en `tx_hash` en collection `orders`
    - Matching: address + amount (respetando 6 decimales TRC20 vs 18 decimales BEP20)
  - **Esquema seguro identificado y consensuado:** usuario genera seed OFFLINE en wallet frío → deriva `TRON_XPUB` (`m/44'/195'/0'`) y `BSC_XPUB` (`m/44'/60'/0'`) → solo carga los xpubs en `.env`. Con xpub la plataforma deriva direcciones y detecta depósitos, pero NO puede firmar transacciones ni mover fondos. Ningún agente Emergent ni infra tendría acceso a la seed (que nunca toca la plataforma).
  - Fase 2 (~1-2 semanas + auditoría seguridad, futuro lejano): payouts firmados desde hot-wallet company. Requiere private key management (Fireblocks/BitGo custodial o Ledger self-custody).
- Email diario al `ops_notifications_email` con tickets anti-fraude >48h.
- Gráfico histórico de blocks/semana en sección Anti-fraude.
- Refactor opcional: BalanceConverterCard (284L) y VipView (410L) en sub-componentes.
- Reemplazar `is` con `==` en comparaciones de literales en tests (170 instancias).
- `<th>Real</th>` column en AdminRates.

### ❌ Descartado
- **Stripe webhooks / Plaid** — no viable: mayoría de clientes son de Cuba, no tienen acceso a estos servicios financieros US.
- ✅ ~~Verify `resiliencebrothers.com` DNS in Resend~~ — DONE (jun 26, 2026): domain verified, `EMAIL_SENDER` switched to `noreply@resiliencebrothers.com`. Production deploy still pending so user can paste `APP_PUBLIC_URL=https://p2p.resiliencebrothers.com` in Emergent Secrets and click Deploy.

### P1
- **Refactor Phase 3 (closed)** ✅ — `server.py` already slim (108 lines); admin.py split into 6 modules (iter39).
- ~~Component size & nested ternaries~~ — **closed in iter39**: 4 oversized components split into 17 sub-components.
- ~~Split `routes/admin.py`~~ — **closed in iter39** (1247 → 538 lines).

### P2
- ~~Type Safety~~ — **closed in iter40**: mypy 100% green across `server.py` + `services/*`.
- ~~Sentry coverage~~ — **closed in iter40**: 0 orphan `console.error/warn` left in React bundle.
- ~~Nested ternaries~~ — **closed in iter40** (`VipView.jsx` extracted helper; `OrdersView.jsx` already clean).
- **Wallets on-chain reales** (USDT/BTC) + webhooks Stripe/Zelle de auto-confirmación.
- **Analytics anti-scam** (under_review activos, blocks/semana, falsos positivos).
- **Self-service appeal** para `under_review`.
- **Mobile-first quick admin dashboard** (1 pantalla con pendientes urgentes, balance, último PDF, botón "Acción rápida").
- Multi-currency display of VIP balance across UI (legacy single-USD widgets if any remain).
- Search + pagination in admin tables (audit, orders, users) when data grows.
- Visual highlight (red tint) of negative-profit cards on AdminRevenue.
- Add `<th>Real</th>` column in AdminRates table (data already exposed via GET /api/rates).

### P2
- Wallets on-chain reales (USDT/BTC) + Stripe/Zelle webhooks de auto-confirmación.
- Replace base64 proof storage with Emergent Object Storage. ✅ Done in iter35 (Cloudflare R2).
- Modernize stale tests. ✅ Done in iter34.
- Backfill base64 → R2 for historical orders. ✅ Done in iter36 (159 órdenes migradas).
- Optional: move `openapi.json` under `/api/openapi.json`. ✅ Done in iter36.
- Optional: surface 413 to client on oversize proof_image. ✅ Done in iter36.
- Reject-phone analytics: count of users currently under_review, scammers blocked per week, false-positive rate (admin un-blocked / total blocks).
- Self-service appeal flow: under_review users can submit an "I'm not a scammer" form that lands in a staff queue.
- POST /admin/blocked-contacts → status_code=201 + add `VerifyPhonePayload(BaseModel)` for OpenAPI/consistency (code-review notes from iter30).
- Lift NotificationBell state into AuthContext to avoid double-polling when two bell instances are mounted simultaneously (minor — currently invisible to users).

## Test Credentials
See `/app/memory/test_credentials.md` and `/app/auth_testing.md`.

## Key Files
- `/app/backend/server.py` — Slim 92-line bootstrap (CORS, router includes, scheduler hooks, Sentry init, Storage init).
- `/app/backend/sentry_config.py` — Sentry SDK init (iter34). No-op when SENTRY_DSN unset.
- `/app/backend/routes/` — `auth`, `me`, `orders`, `admin`, `market`, `blocklist`, `notifications`, `push`, `files` (one APIRouter per domain, all with OpenAPI tags).
- `/app/backend/services/` — Shared helpers: `balances`, `orders_helpers`, `transactions`, `storage` (iter35 — R2/S3 abstraction), `proof_upload` (iter35 — base64→R2 helper).
- `/app/backend/auth_utils.py` — Auth + session + TOTP step-up helpers. Auto-tags Sentry user on get_session_user.
- `/app/backend/db_client.py` — Single Mongo client + DB handle.
- `/app/backend/.env.sentry.example`, `.env.storage.example` — Documented config knobs.
- `/app/frontend/src/sentry.js` — Frontend Sentry init + helpers (iter34).
- `/app/frontend/src/index.js` — ErrorBoundary wired (iter34).
- `/app/frontend/src/context/AuthContext.jsx` — Tags Sentry user on login/logout.
- `/app/frontend/src/App.js` — Router + AuthCallback gate.
- `/app/frontend/src/pages/Landing.jsx`, `Dashboard.jsx`, `AdminPanel.jsx` — Main shells.
- `/app/frontend/src/pages/dashboard/*` and `/admin/*` — Feature views.
- `/app/design_guidelines.json` — Design system reference.
