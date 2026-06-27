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

## Prioritized Backlog
### P0 — Waiting on user
- ✅ ~~Verify `resiliencebrothers.com` DNS in Resend~~ — DONE (jun 26, 2026): domain verified, `EMAIL_SENDER` switched to `noreply@resiliencebrothers.com`. Production deploy still pending so user can paste `APP_PUBLIC_URL=https://p2p.resiliencebrothers.com` in Emergent Secrets and click Deploy.

### P1
- **Refactor Phase 3 cont.**: extract `routes/orders.py` (orders + withdrawals + redemptions, ~600 lines) and `routes/admin.py` (stats, audit, transactions, revenue, queue, company-funds, users, defensive-mode — ~900 lines) from `server.py` (still 2377 lines). After both, server.py would be ~800 lines — pure app bootstrap + cross-cutting helpers.
- Multi-currency display of VIP balance across UI (legacy single-USD widgets if any remain).
- Search + pagination in admin tables (audit, orders, users) when data grows.
- Visual highlight (red tint) of negative-profit cards on AdminRevenue.
- Add `<th>Real</th>` column in AdminRates table (data already exposed via GET /api/rates).
- Move `_assert_not_defensive` from `server.py` to a small `system_state.py` module to eliminate the 2 lazy `from server import` calls inside `routes/auth.py`.

### P2
- Sentry / error monitoring integration.
- Real crypto wallet integration (on-chain USDT/BTC verification).
- Stripe / Zelle webhooks for auto-confirmation.
- Replace base64 proof storage with Emergent Object Storage.
- Auto-seed dev session tokens (`test_session_admin_X`, `_employee_X`, `_vip_X`, `_normal_X`) in `conftest.py` so iter20+ tests no longer require manual user_sessions insertion.
- Reject-phone analytics: count of users currently under_review, scammers blocked per week, false-positive rate (admin un-blocked / total blocks).
- Self-service appeal flow: under_review users can submit an "I'm not a scammer" form that lands in a staff queue.
- POST /admin/blocked-contacts → status_code=201 + add `VerifyPhonePayload(BaseModel)` for OpenAPI/consistency (code-review notes from iter30).
- Lift NotificationBell state into AuthContext to avoid double-polling when two bell instances are mounted simultaneously (minor — currently invisible to users).

## Test Credentials
See `/app/memory/test_credentials.md` and `/app/auth_testing.md`.

## Key Files
- `/app/backend/server.py` — All API routes + models.
- `/app/frontend/src/App.js` — Router + AuthCallback gate.
- `/app/frontend/src/pages/Landing.jsx` — Public landing.
- `/app/frontend/src/pages/Dashboard.jsx` — Client shell + nav.
- `/app/frontend/src/pages/AdminPanel.jsx` — Admin shell + nav.
- `/app/frontend/src/pages/dashboard/*` and `/admin/*` — Feature views.
- `/app/design_guidelines.json` — Design system reference.
