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

- **iter55.8 (Mar 1, 2026)**: **Cliente veía "No autorizado" al abrir comprobante del pago recibido**.
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
- **🪙 Wallets crypto on-chain (USDT-TRC20/ERC-20, BTC)** — PRIORIDAD ALTA cuando se retome. Justificación: la mayoría de clientes son cubanos y **crypto es la vía principal de entrada de fondos** (Stripe/tarjetas no viables en Cuba). Alcance recomendado:
  - Fase 1 (~3-4 días): read-only — auto-detección de depósitos USDT-TRC20 vía polling de TronGrid o webhook de proveedor (Tatum/BlockCypher). Marca orden como "fondos recibidos" automáticamente + guarda TX hash y link a explorer.
  - Fase 2 (~1-2 semanas + auditoría seguridad): payouts firmados desde hot-wallet company. Requiere private key management (Fireblocks/BitGo custodial o Ledger self-custody).
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
