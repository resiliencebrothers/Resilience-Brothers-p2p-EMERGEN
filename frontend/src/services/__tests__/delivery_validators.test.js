/**
 * iter55.10 — Unit tests for the shared delivery-details validators.
 * Runs via CRA/Jest — pure logic, no React needed.
 */
import { getDeliveryValidator, getDeliveryBadge } from "../delivery_validators";

describe("CUP transfer (Cuban bank)", () => {
  const v = getDeliveryValidator("CUP", "transfer");
  test("returns a hint mentioning 16 dígitos", () => {
    expect(v.hint).toMatch(/16 dígitos/i);
  });
  test("accepts exactly 16 digits (with spaces)", () => {
    const r = v.validate("Juan Pérez\n9212 9598 7274 4356");
    expect(r.ok).toBe(true);
    expect(r.feedback).toMatch(/16 dígitos/);
  });
  test("rejects 14 digits with delta hint", () => {
    const r = v.validate("Juan\n9212 9598 7274 43");
    expect(r.ok).toBe(false);
    expect(r.feedback).toMatch(/14 dígitos/);
    expect(r.feedback).toMatch(/2/);
  });
  test("returns null for empty (no visible feedback)", () => {
    expect(v.validate("")).toBeNull();
  });
});

describe("MXN CLABE (18 digits)", () => {
  const v = getDeliveryValidator("MXN", "transfer");
  test("accepts 18-digit CLABE", () => {
    const r = v.validate("CLABE: 646180157012345678");
    expect(r.ok).toBe(true);
  });
  test("rejects 16-digit input (card, not CLABE)", () => {
    const r = v.validate("1234 5678 1234 5678");
    expect(r.ok).toBe(false);
  });
});

describe("BRL PIX", () => {
  const v = getDeliveryValidator("BRL", "transfer");
  test("accepts email PIX key", () => {
    const r = v.validate("cliente@bancointer.com.br");
    expect(r.ok).toBe(true);
    expect(r.feedback).toMatch(/email/i);
  });
  test("accepts CPF (11 digits)", () => {
    const r = v.validate("CPF: 12345678901");
    expect(r.ok).toBe(true);
  });
  test("accepts UUID PIX random key", () => {
    const r = v.validate("f47ac10b-58cc-4372-a567-0e02b2c3d479");
    expect(r.ok).toBe(true);
  });
});

describe("Zelle (US)", () => {
  const v = getDeliveryValidator("ZELLE", "transfer");
  test("accepts email", () => {
    const r = v.validate("me@gmail.com");
    expect(r.ok).toBe(true);
  });
  test("accepts US phone", () => {
    const r = v.validate("+1 305 123 4567");
    expect(r.ok).toBe(true);
  });
});

describe("Crypto wallets (universal)", () => {
  const v = getDeliveryValidator("USDT", "crypto", "crypto");
  test("hint mentions BEP20 as recommended for USDT", () => {
    expect(v.hint).toMatch(/BEP20/i);
    expect(v.hint).toMatch(/recomendada/i);
  });
  test("accepts TRC20 address", () => {
    // Real Tron address (34 base58 chars starting with T)
    const r = v.validate("TXYZefghjkLmnopqrstuvwxyz1234567ab");
    expect(r.ok).toBe(true);
    expect(r.feedback).toMatch(/TRC20|Tron/i);
  });
  test("accepts BEP20 address when network is explicitly declared", () => {
    const r = v.validate("0x1234567890abcdef1234567890abcdef12345678\nRed: BEP20");
    expect(r.ok).toBe(true);
    expect(r.feedback).toMatch(/BEP20|Binance/i);
  });
  test("accepts BEP20 alias (BSC)", () => {
    const r = v.validate("0x1234567890abcdef1234567890abcdef12345678 (BSC)");
    expect(r.ok).toBe(true);
    expect(r.feedback).toMatch(/BEP20/i);
  });
  test("accepts ERC20 address when network is explicit", () => {
    const r = v.validate("0x1234567890abcdef1234567890abcdef12345678 ERC20");
    expect(r.ok).toBe(true);
    expect(r.feedback).toMatch(/ERC20|Ethereum/i);
  });
  test("warns when 0x address has NO network declared (ambiguous — critical)", () => {
    const r = v.validate("0x1234567890abcdef1234567890abcdef12345678");
    expect(r.ok).toBe(false);
    expect(r.feedback).toMatch(/red/i);
    expect(r.feedback).toMatch(/BEP20/i);
  });
  test("accepts BTC bech32 address", () => {
    const btc = getDeliveryValidator("BTC", "crypto", "crypto");
    const r = btc.validate("bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh");
    expect(r.ok).toBe(true);
  });
  test("rejects random string", () => {
    const r = v.validate("this-is-not-a-wallet");
    expect(r.ok).toBe(false);
  });
});

describe("getDeliveryBadge (admin-side)", () => {
  test("null when combo has no validator (e.g. USDT/cash)", () => {
    expect(getDeliveryBadge("USDT", "cash", "some text")).toBeNull();
  });
  test("green badge for valid CUP", () => {
    const b = getDeliveryBadge("CUP", "transfer", "9212 9598 7274 4356");
    expect(b.ok).toBe(true);
  });
  test("null for empty delivery details", () => {
    expect(getDeliveryBadge("CUP", "transfer", "")).toBeNull();
  });
});

describe("Unknown code falls back gracefully", () => {
  test("null for USD cash (no rules)", () => {
    expect(getDeliveryValidator("USD", "cash")).toBeNull();
  });
  test("null for exotic currency", () => {
    expect(getDeliveryValidator("JPY", "transfer")).toBeNull();
  });
});
