/**
 * Regresión de la auditoría de inicio de sesión (AUTH-01/02/03).
 * Lógica pura — no necesita React ni red.
 */
import {
  AUTH_STATUS,
  isValidUser,
  createAuthGeneration,
  reduceAuthCheck,
  confirmLoginIdentity,
} from "../authGuard";

const VALID = { user_id: "u1", role: "normal" };
const VALID2 = { user_id: "u2", role: "admin" };

describe("isValidUser — contrato de identidad (AUTH-03)", () => {
  test("acepta un usuario con user_id y role no vacíos", () => {
    expect(isValidUser(VALID)).toBe(true);
  });
  test.each([
    ["null", null],
    ["objeto sin identidad", { message: "ok" }],
    ["user_id vacío", { user_id: "", role: "normal" }],
    ["role ausente", { user_id: "u1" }],
    ["HTML/string", "<html>200</html>"],
  ])("rechaza %s", (_label, value) => {
    expect(isValidUser(value)).toBe(false);
  });
});

describe("createAuthGeneration — descarte de respuestas atrasadas (AUTH-01)", () => {
  test("una respuesta capturada antes de un login posterior queda obsoleta", () => {
    const gen = createAuthGeneration();
    const captured = gen.current();   // /auth/me inicial arranca en gen 0
    gen.bump();                       // ocurre un login
    expect(gen.isStale(captured)).toBe(true);
  });
  test("una respuesta de la generación vigente no es obsoleta", () => {
    const gen = createAuthGeneration();
    const captured = gen.current();
    expect(gen.isStale(captured)).toBe(false);
  });
  test("logout tras login invalida la respuesta del login (no restaura usuario)", () => {
    const gen = createAuthGeneration();
    gen.bump();                       // login
    const loginGen = gen.current();
    gen.bump();                       // logout
    expect(gen.isStale(loginGen)).toBe(true);
  });
});

describe("reduceAuthCheck — máquina de estados (AUTH-02)", () => {
  test("200 con identidad válida → autenticado", () => {
    expect(reduceAuthCheck({ user: null }, { ok: true, user: VALID }))
      .toEqual({ user: VALID, status: AUTH_STATUS.AUTHENTICATED });
  });
  test("200 con cuerpo inválido → anónimo (AUTH-03: no se confía en 200 vacío)", () => {
    expect(reduceAuthCheck({ user: null }, { ok: true, user: { message: "ok" } }))
      .toEqual({ user: null, status: AUTH_STATUS.ANONYMOUS });
  });
  test("401 → anónimo confirmado", () => {
    expect(reduceAuthCheck({ user: VALID }, { ok: false, httpStatus: 401 }))
      .toEqual({ user: null, status: AUTH_STATUS.ANONYMOUS });
  });
  test("503 con sesión ya confirmada → mantiene la sesión (no cierra)", () => {
    expect(reduceAuthCheck({ user: VALID }, { ok: false, httpStatus: 503 }))
      .toEqual({ user: VALID, status: AUTH_STATUS.AUTHENTICATED });
  });
  test("error de red con sesión confirmada → mantiene la sesión", () => {
    expect(reduceAuthCheck({ user: VALID }, { ok: false, httpStatus: undefined }))
      .toEqual({ user: VALID, status: AUTH_STATUS.AUTHENTICATED });
  });
  test("error transitorio en el arranque (sin usuario) → estado recuperable, no anónimo", () => {
    expect(reduceAuthCheck({ user: null }, { ok: false, httpStatus: 503 }))
      .toEqual({ user: null, status: AUTH_STATUS.ERROR });
  });
});

describe("confirmLoginIdentity — confirmación de sesión (AUTH-03)", () => {
  test("login válido + /auth/me válido con el mismo user_id → ok", () => {
    expect(confirmLoginIdentity(VALID, VALID)).toEqual({ ok: true });
  });
  test("login 200 sin identidad válida → rechazado (no anuncia éxito)", () => {
    expect(confirmLoginIdentity({ message: "ok" }, VALID).ok).toBe(false);
  });
  test("/auth/me no reconoce la sesión (cuerpo inválido) → rechazado", () => {
    expect(confirmLoginIdentity(VALID, null).ok).toBe(false);
  });
  test("identidad distinta entre login y /auth/me → rechazado", () => {
    expect(confirmLoginIdentity(VALID, VALID2)).toEqual({ ok: false, reason: "mismatch" });
  });
});

describe("escenario compuesto AUTH-01 — /auth/me inicial atrasado no borra el login", () => {
  // Modela el patrón real de AuthContext: la comprobación inicial captura su
  // generación; el login la bumpea y aplica identidad; la vieja respuesta 401
  // resuelve DESPUÉS y, por ser obsoleta, NO debe tocar el estado.
  test("comprobación inicial pendiente → login correcto → 401 viejo ignorado", () => {
    const gen = createAuthGeneration();
    const state = { user: null, status: AUTH_STATUS.CHECKING };

    // 1) /auth/me inicial arranca.
    const initialGen = gen.current();

    // 2) El usuario inicia sesión: bump + confirmación válida aplicada.
    gen.bump();
    const loginGen = gen.current();
    const confirmed = confirmLoginIdentity(VALID, VALID);
    expect(confirmed.ok).toBe(true);
    if (!gen.isStale(loginGen)) {
      state.user = VALID;
      state.status = AUTH_STATUS.AUTHENTICATED;
    }

    // 3) Llega la respuesta ATRASADA del /auth/me inicial (401). Es obsoleta.
    const staleOutcome = { ok: false, httpStatus: 401 };
    if (!gen.isStale(initialGen)) {
      const next = reduceAuthCheck({ user: state.user }, staleOutcome);
      state.user = next.user;
      state.status = next.status;
    }

    // El usuario sigue autenticado; la respuesta vieja no lo expulsó.
    expect(state.user).toEqual(VALID);
    expect(state.status).toBe(AUTH_STATUS.AUTHENTICATED);
  });
});
