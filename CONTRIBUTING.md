# Contributing to Resilience Brothers P2P

Thanks for helping build a safer, faster P2P platform. This guide is short on
purpose — read it once, then keep it as reference.

---

## TL;DR (already knows the drill)

```bash
git checkout -b feat/short-descriptive-name
make install-hooks               # one-time per clone
# ... edit code, add tests ...
make test-critical               # ~1 min, must pass before push
git commit -m "feat: describe what changed"   # hook runs the same tests
git push origin feat/short-descriptive-name
# open PR against `main`; wait for the 3 CI checks + 1 approval
```

---

## 1. Branching model

- **`main`** — protected. Production-ready code only. All merges via PR.
- **`feat/...`** — new user-facing feature (`feat/vip-capital-limits`,
  `feat/referral-leaderboard`).
- **`fix/...`** — bug fix (`fix/kyc-mobile-viewport`, `fix/audit-hash-race`).
- **`chore/...`** — infra, deps, CI, tests, docs only (no product behavior change).
- **`refactor/...`** — pure code restructure, zero behavior change, zero API drift.

One PR = one concern. Split large changes into a stack of smaller PRs whenever
possible — they land faster and roll back cleaner.

## 2. Commit message format (Conventional Commits)

```
<type>: <one-line summary in imperative mood, ≤72 chars>

<optional body — the WHY, not the WHAT. Wrap at 72.>

<optional footer with ref: e.g. "Refs: iter55.36e" or "Fixes #123">
```

**Types**: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`, `security`.

**Good**:
- `feat: add USDT residue balance for cash-fiat orders`
- `fix: prevent double-approval when TOTP step-up races with UI dismiss`
- `security: block wallet address paste on network mismatch (BingX-style)`

**Bad**:
- `updates` (no type, no summary)
- `WIP` (never merge a WIP commit — squash it first)
- `Fixed a lot of stuff` (vague, unauditable 6 months later)

## 3. Local dev checklist (before every push)

| Step | Command | Duration | When to skip |
| --- | --- | --- | --- |
| 1. Backend lint | `make ruff` | ~2s | Never — catches undefined names early |
| 2. Frontend lint | `make lint` | ~15s | If no `.jsx/.js` changed |
| 3. Critical tests | `make test-critical` | ~1 min | If only docs/CSS changed |
| 4. Full suite | `make test-all` | ~8-9 min | Optional for tiny PRs; CI runs nightly anyway |

The pre-commit hook (installed via `make install-hooks`) auto-runs steps 1+3
when `backend/*.py` files are staged. Skip it only with `--no-verify` for real
emergencies (production down + you're mid-fix).

## 4. Writing tests

Every new feature or bug fix ships **with a test** — otherwise it's not really
done. We're at 935 passing tests because of this discipline; don't be the
person who breaks the streak.

- **Backend**: add a file `backend/tests/test_iter<N>_<feature>.py`. Use the
  fixtures in `conftest.py` (`ADMIN_TOKEN`, `make_admin_totp()`, etc). Hit
  the real HTTP layer via `requests` — motor + pytest-asyncio work but see
  the [event loop caveat](./memory/PRD.md#iter5536b) before mixing them.
- **Frontend**: add a `data-testid` on every new interactive element and on
  every element showing critical info. The testing agent + Playwright suite
  drive UI flows through these.

If you're fixing a bug: **reproduce it in a test first** (the test should fail
on `main` and pass on your branch). This is non-negotiable — it's the only
way to prove the fix works and to catch regressions later.

## 5. Sensitive data / secrets

The pre-commit hook blocks common secret patterns (BIP39 mnemonics, private
keys, xpubs, AWS/Google keys, JWTs, `.env` files). If you need to add a new
credential:

- Backend: append to `backend/.env` locally + `Settings → Environment` in
  Emergent for the deployed env.
- Frontend: use `frontend/.env` with the `REACT_APP_` prefix (only these are
  exposed to the browser bundle).
- **Never** hard-code an API key or endpoint in source. If the linter can grep
  it, so can an attacker.

## 6. PR checklist (paste into the PR body)

```markdown
## What changed
- [ ] Brief bullet-list of the user-visible or infra-visible changes.

## Why
- [ ] One paragraph on the motivation / the bug this closes / the metric it moves.

## How verified
- [ ] `make test-critical` — 91/91 green locally
- [ ] `make test-all` — 935/935 green locally (or noted N/A for docs-only PR)
- [ ] Manually clicked through the changed flow on the preview URL
- [ ] Screenshot / GIF attached (for UI changes)

## Risk
- [ ] None / Low / Medium / High
- [ ] Rollback plan: revert the merge commit + redeploy (default).
      Data migration required? Note it here.

## Refs
- Related iter / PRD section / issue.
```

## 7. Merge criteria

Your PR merges when **all 4** are true:

1. **CI**: `Backend · pytest`, `Backend · mypy`, `Frontend · ESLint` — all green.
2. **Review**: ≥1 approval from a maintainer (or ≥2 for security-sensitive
   changes — anything touching `auth_utils`, `permissions`, `TOTP`, `audit_log`,
   `cloudflare_blocks`, `withdrawals`, `capital_requests`).
3. **Conversations**: every review comment resolved (or a follow-up issue linked).
4. **Branch**: up to date with `main` (rebase, don't merge-commit).

The maintainer clicks **"Squash and merge"** so `main` history stays linear
and readable. Your feature branch commits are preserved in the squash body.

## 8. Linter baseline (what we intentionally accept)

External static analyzers occasionally flag patterns we've reviewed and
consciously kept. If your reviewer's tool raises any of the following, the
answer is **"working as intended"** — no code change needed. Point them here.

| Pattern | Why it's fine |
| --- | --- |
| `if x is None:` / `if x is not None:` (315+ instances) | PEP 8 recommended idiom. `is` is correct for singleton comparisons. Only `is <literal-int/str/list>` is a bug (ruff `F632` catches those — none in this codebase). |
| `if x is True:` / `if x is False:` | Also PEP 8; distinguishes the singleton from truthy/falsy values, which matters for our audit trail (`True` ≠ `1`). |
| FastAPI routes with 8+ `Query(...)` parameters (e.g. `list_transactions`, `export_transactions_csv/pdf` in `routes/admin.py`) | These are URL query params, one per key. Wrapping into a `Pydantic` model via `Depends()` adds boilerplate without changing behavior and breaks OpenAPI param docs. |
| `JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP` in test files | The **pyotp docs sample** base32 secret — public by design, only used to seed the 4 test users on the local/CI DB. Production `TOTP_MASTER_KEY` is unrelated. Consolidated to `conftest.TEST_TOTP_SECRET` (env-overridable). |
| Functions >50 lines (`admin_user_stats` 140 lines, `generate_vip_closing_pdf` 112 lines, etc.) | Long doesn't mean wrong. Each is a single-responsibility "compose a payload/PDF" pipeline. Splitting for its own sake adds indirection with no readability gain. Refactor only when a real bug forces it. |
| React components >300 lines (`AdminUserStatsPage`, `ExchangeView`, `AdminOrders`, `SecuritySettings`, `AdminWithdrawals`, `AdminSecurity`, `AdminHealth`) | Same rationale. All have `data-testid` coverage + passing E2E tests. When you touch them for a bug fix, extract only the sub-tree you're actually changing — don't rewrite the neighborhood. |
| Nested ternaries in JSX (`BalanceConverterCard`, `AdminKYC`, `AdminUsers`, `EmailAuthDialog`) | Short (2-3 levels max) and used for badge color / label selection. Rewriting as if/else or lookup tables would triple the LOC. |
| Filter/map in JSX render (`BalanceConverterCard:241`, `CashDetailsTable:158`, `UserFunctionsDialog:166`) | Affected lists are ≤10 items. `useMemo` wrapping costs more (dependency array bugs) than it saves. Revisit only if profiling shows a real render bottleneck. |
| Missing `react-hooks/exhaustive-deps` warnings from external analyzers | Our `eslint.hooks.config.mjs` has the rule at `warn` — the CI job (`yarn lint`) blocks on 0 warnings. If external tools report warnings we don't, their config is stricter than ours by policy. |

If you have a genuine finding NOT in this table, open a PR + explain the
concrete bug it prevents. We add rules based on real risk, not analyzer noise.

## 9. Getting help

- **Product / roadmap questions**: read `/app/memory/PRD.md` first — it has
  the changelog + P0/P1/P2 backlog.
- **Ops runbook** (incident, secret rotation, on-call playbooks):
  `/app/docs/incident-response.md`.
- **Test credentials**: `/app/memory/test_credentials.md`.

Welcome aboard. 🚀
