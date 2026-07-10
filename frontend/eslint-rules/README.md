# Local ESLint rules

Custom ESLint rules that guard against regressions specific to this codebase.

## `no-dialog-without-scroll`

**Severity**: `error`

Ensures every `<DialogContent>` includes a `max-h-*` utility in its className so long forms cannot silently overflow the viewport on short laptop / mobile screens.

### Why it exists

In Feb 2026 an admin reported that the "Editar/Nueva Moneda" modal on production hid its **Guardar** button on a smaller laptop screen — the Radix `DialogContent` had no `max-h` cap, so any content taller than the viewport was clipped with no scrollbar. A sweep found 13 modals with the same latent bug. This rule prevents it from ever coming back.

### Passing examples

```jsx
// ✅ Explicit max-h (any Tailwind syntax)
<DialogContent className="bg-black max-h-[85vh] overflow-y-auto">…</DialogContent>
<DialogContent className="max-h-screen overflow-y-auto">…</DialogContent>

// ✅ Intentional opt-out for hero-image wizards (OnboardingDialog pattern)
<DialogContent className="overflow-hidden p-0">…</DialogContent>

// ✅ Placeholder / closed-state modal (TransactionDetailModal pattern)
<DialogContent className="hidden" />
```

### Failing examples

```jsx
// ❌ No max-h — will trigger missingMaxH
<DialogContent className="bg-[#141414] max-w-md">…</DialogContent>

// ❌ No className at all — will trigger missingClassName
<DialogContent>…</DialogContent>
```

### Fix

Add `max-h-[85vh] overflow-y-auto` to the className (or `max-h-[90vh]` for content-heavy modals).

### Running

```bash
cd /app/frontend
yarn lint
```

The rule is wired into `eslint.hooks.config.mjs` and runs whenever `yarn lint` (or any editor with ESLint integration) is invoked.
