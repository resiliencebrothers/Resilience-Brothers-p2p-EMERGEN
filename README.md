# Resilience Brothers — P2P Trading Platform

[![CI](https://github.com/resilience-brothers/p2p-exchange-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/resilience-brothers/p2p-exchange-hub/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-935%20total%20%C2%B7%2091%20critical-22C55E?style=flat-square&logo=pytest&logoColor=white)](./backend/tests)
[![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20Motor-8B5CF6?style=flat-square&logo=fastapi&logoColor=white)](./backend)
[![Frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Tailwind-8B5CF6?style=flat-square&logo=react&logoColor=white)](./frontend)
[![Database](https://img.shields.io/badge/database-MongoDB-22C55E?style=flat-square&logo=mongodb&logoColor=white)](./backend/db_client.py)
[![Deployed](https://img.shields.io/badge/deployed-p2p.resiliencebrothers.com-8B5CF6?style=flat-square)](https://p2p.resiliencebrothers.com)
[![Security](https://img.shields.io/badge/2FA-TOTP%20required-EAB308?style=flat-square&logo=letsencrypt&logoColor=white)](./backend/routes/totp.py)
[![Storage](https://img.shields.io/badge/storage-Cloudflare%20R2-EAB308?style=flat-square&logo=cloudflare&logoColor=white)](./backend/services/storage_service.py)

> Replace `resilience-brothers/p2p-exchange-hub` in the CI badge URL with your actual GitHub org/repo slug once the repo lives on GitHub.

Global P2P trading platform for digital assets, fiat currency and physical goods.
Connects businesses and clients across LatAm with dynamic commissions, KYC/AML,
granular RBAC, on-chain crypto verification and a full compliance audit trail.

---

## Quick Start

```bash
# Full backend suite (~8-9 min, 935 tests)
make test-all

# Critical regression subset (~1 min, 91 tests) — run before pushing
make test-critical

# Ultra-fast drift check (~15s, 6 tests) — used in pre-commit
make smoke

# Wire up the pre-commit hook (one-time per clone)
make install-hooks
```

## Pre-commit Hook

The `.githooks/pre-commit` script runs automatically on every commit and:

1. **Scans for secrets** — blocks BIP39 mnemonics, private keys, xpubs, AWS/Google
   keys, JWTs and `.env` files from being committed.
2. **Warns on large files** — surfaces staged files >1 MB that likely don't
   belong in Git.
3. **Runs the critical regression suite** — 91 tests, ~1 min, only when
   `backend/*.py` files are staged. Catches:
   - RBAC-lite permission drift (iter55.16)
   - Audit log integrity (iter55.16b)
   - Company funds adjustments (iter55.15)
   - Notification lifecycle (iter55.18)
   - Crypto network mismatch (iter55.19c / 19h)
   - Session TTL cap (iter55.37)
   - TOTP step-up gates (iter13/14)

### Bypass options

| Situation | Command |
| --- | --- |
| Emergency hotfix, skip everything | `git commit --no-verify` |
| Skip only the test suite (keep secret-scan) | `SKIP_CRITICAL_TESTS=1 git commit` |
| Frontend-only or docs-only changes | Hook auto-skips tests |

## Continuous Integration

GitHub Actions workflow `.github/workflows/ci.yml` mirrors the pre-commit gate
at the remote level so PRs from clones without the hook still get caught:

| Trigger | What runs | Duration |
| --- | --- | --- |
| **Push / PR to main-master-develop** | `mypy` + `make test-critical` (91 tests) + ESLint | ~2-3 min |
| **Nightly cron (03:00 UTC)** | Same jobs but `make test-all` (935 tests) | ~10-12 min |
| **Manual dispatch** (Actions tab) | Same as push | ~2-3 min |

The nightly full-suite catches slow-drift regressions that the fast critical
subset can miss (e.g. iter55.36b's motor event-loop contamination — invisible
in isolation, only surfaces under the full suite load).

Test users are seeded idempotently by `backend/scripts/seed_test_users.py`
before the FastAPI backend starts, using placeholder secrets set in the
workflow's `env:` block (no real credentials in CI).

## Architecture

- **Backend**: FastAPI + Motor (MongoDB async) at `/backend/server.py`. All
  routes prefixed with `/api`.
- **Frontend**: React 19 + React Router + Tailwind + Shadcn UI at `/frontend/src`.
- **Auth**: Custom Google OAuth 2.0 (`/api/auth/google/login`) + email/password
  fallback. First registered user auto-promoted to admin.
- **Storage**: Cloudflare R2 for proof uploads (base64 → object storage on the
  fly, iter35).
- **Security**: TOTP 2FA on all financial actions, IP blocklist middleware,
  rate limits (slowapi), CORS allowlist, security headers (HSTS/CSP), automated
  anomaly scan every 5 min, monthly audit report auto-emailed to ops (iter55.21).

## Roles

| Role | Commission | Marketplace | Balance | Rates |
| --- | --- | --- | --- | --- |
| **Normal** | 5% | ❌ | N/A | `rate_normal` |
| **VIP** | 0% | ✅ redeem for goods | Accumulated USD | `rate_vip` |
| **Staff Member** | — | — | — | Granular per-permission RBAC (13 codes) |
| **Admin** | — | — | — | Full access + treasury adjustments |

## Key Endpoints

| Endpoint | Description |
| --- | --- |
| `POST /api/orders` | Create P2P order (with proof upload) |
| `POST /api/vip/withdraw` | VIP balance withdrawal (transfer / crypto / cash) |
| `POST /api/vip/redeem` | Redeem VIP balance for marketplace goods |
| `POST /api/kyc/submit` | Submit KYC docs (3 images to R2) |
| `POST /api/capital-requests` | VIP capital request (auto-discounting FIFO) |
| `GET /api/admin/audit/monthly.pdf` | Owner-grade monthly compliance report |
| `GET /api/admin/security/audit` | Live security dashboard (sessions, floods, new IPs) |
| `POST /api/admin/security/cloudflare/blocks` | Manual IP block (app + CF edge) |

## Documentation

- `/app/memory/PRD.md` — Full product requirements + changelog
- `/app/memory/test_credentials.md` — Test user credentials
- `/app/docs/incident-response.md` — Ops runbook (incident playbooks, secret rotation)

## Deployment

- **Preview** (dev): auto-updated via Emergent platform on every commit
- **Production**: `https://p2p.resiliencebrothers.com` — requires manual redeploy from the Emergent dashboard after preview validation
