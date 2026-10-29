/**
 * Provider-level regression for the email/password sign-in race (auditoría
 * login). These tests drive the REAL `signInWithPassword` from AuthProvider
 * (not a helper), interleaving the network responses by hand, which is exactly
 * what the previous helper-only suite could not certify.
 *
 * RESIDUAL being guarded: if a login attempt is superseded (logout / another
 * login) while its confirmation `/auth/me` is in flight, and that confirmation
 * then fails, the abandoned attempt must surface AUTH_STALE — never a late
 * "SESSION_UNCONFIRMED" that the dialog would wrongly show or act on.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { act } from "react-dom/test-utils";

// Opt in to React 18's concurrent act() support for this manual root.
global.IS_REACT_ACT_ENVIRONMENT = true;

jest.mock("@/App", () => ({ API: "http://test.local" }));
jest.mock("@/sentry", () => ({ setSentryUser: () => {}, captureError: () => {} }));
jest.mock("@/lib/langSync", () => ({ applyServerLanguage: () => {} }));
jest.mock("axios", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));

import axios from "axios";
import { AuthProvider, useAuth, AUTH_STATUS } from "@/context/AuthContext";

const USER = { user_id: "u1", role: "vip", email: "a@b.com", name: "Ana" };

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

let ctx;
function Capture() { ctx = useAuth(); return null; }

let getQueue;
let container;
let root;

beforeAll(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { href: "http://localhost/", hash: "", assign: jest.fn() },
  });
});

beforeEach(() => {
  ctx = undefined;
  getQueue = [];
  axios.get.mockReset();
  axios.post.mockReset();
  // Every /auth/me resolves through a manually-settled deferred (FIFO).
  axios.get.mockImplementation(() => {
    const d = deferred();
    getQueue.push(d);
    return d.promise;
  });
  axios.post.mockImplementation((url) => {
    if (String(url).endsWith("/auth/login")) return Promise.resolve({ data: USER });
    return Promise.resolve({ data: {} }); // /auth/logout, /auth/logout-all
  });
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  act(() => { root && root.unmount(); });
  container.remove();
});

async function mountAnonymous() {
  await act(async () => {
    root = ReactDOM.createRoot(container);
    root.render(<AuthProvider><Capture /></AuthProvider>);
  });
  // The mount /auth/me resolves to 401 → anonymous, settling initial load.
  await act(async () => { getQueue[0].reject({ response: { status: 401 } }); });
}

test("RESIDUAL — attempt superseded by logout while confirming → AUTH_STALE (never SESSION_UNCONFIRMED)", async () => {
  await mountAnonymous();

  let settled = null;
  act(() => {
    ctx.signInWithPassword({ email: "a@b.com", password: "x" })
      .then(() => { settled = { ok: true }; })
      .catch((e) => { settled = { err: e }; });
  });
  // Flush: POST /auth/login resolves and the confirmation /auth/me is issued.
  await act(async () => {});
  expect(getQueue.length).toBe(2); // [0] mount, [1] confirm — still pending

  // A logout lands mid-flight and bumps the auth generation → attempt is stale.
  await act(async () => { await ctx.logout(); });

  // Now the in-flight confirmation fails (e.g. old cookie 401).
  await act(async () => { getQueue[1].reject({ response: { status: 401 } }); });

  expect(settled).not.toBeNull();
  expect(settled.err).toBeDefined();
  expect(settled.err.code).toBe("AUTH_STALE");
});

test("CONTROL — current attempt whose confirmation fails still reports SESSION_UNCONFIRMED", async () => {
  await mountAnonymous();

  let settled = null;
  act(() => {
    ctx.signInWithPassword({ email: "a@b.com", password: "x" })
      .then(() => { settled = { ok: true }; })
      .catch((e) => { settled = { err: e }; });
  });
  await act(async () => {}); // confirm /auth/me issued as getQueue[1]

  // No logout/login in between: the attempt is still current.
  await act(async () => {
    getQueue[1].reject({ response: { status: 401 } }); // confirmation fails
    // The outer catch re-resolves the real session via checkAuth → getQueue[2].
  });
  await act(async () => { getQueue[2] && getQueue[2].reject({ response: { status: 401 } }); });

  expect(settled.err).toBeDefined();
  expect(settled.err.code).toBe("SESSION_UNCONFIRMED");
});

test("HAPPY — credentials accepted and confirmation matches → authenticated", async () => {
  await mountAnonymous();

  let settled = null;
  act(() => {
    ctx.signInWithPassword({ email: "a@b.com", password: "x" })
      .then((u) => { settled = { ok: true, user: u }; })
      .catch((e) => { settled = { err: e }; });
  });
  await act(async () => {}); // confirm /auth/me issued
  await act(async () => { getQueue[1].resolve({ data: USER }); });

  expect(settled.ok).toBe(true);
  expect(settled.user.user_id).toBe("u1");
  expect(ctx.status).toBe(AUTH_STATUS.AUTHENTICATED);
  expect(ctx.user.user_id).toBe("u1");
});
