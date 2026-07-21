/**
 * iter92 — image-icon resolution unit tests.
 *
 * The bitmap coin logos live in /public/currency-icons/ and are mapped
 * to real currency codes through `resolveImageIcon`. We keep the logic
 * as a plain, exportable function so we can lock the mapping down
 * without needing a full DOM + Testing Library setup for this one test.
 */
import { resolveImageIcon } from "../CurrencyIcon";

describe("resolveImageIcon", () => {
  test("returns the AED coin PNG for the AED code (any casing)", () => {
    expect(resolveImageIcon("AED")).toBe("/currency-icons/aed.png");
    expect(resolveImageIcon("aed")).toBe("/currency-icons/aed.png");
  });

  test("returns the AED coin for common Dirham / Dubai naming variants", () => {
    // Operators create the currency with different codes in each region.
    expect(resolveImageIcon("DIRHAM_DUBAI")).toBe("/currency-icons/aed.png");
    expect(resolveImageIcon("dirham")).toBe("/currency-icons/aed.png");
    expect(resolveImageIcon("AED_DUBAI")).toBe("/currency-icons/aed.png");
    expect(resolveImageIcon("dubai_dirham")).toBe("/currency-icons/aed.png");
    expect(resolveImageIcon("DUBAI")).toBe("/currency-icons/aed.png");
  });

  test("returns the USD-cash coin PNG for every USDCASH* variant", () => {
    expect(resolveImageIcon("USDCASH")).toBe("/currency-icons/usd-cash.png");
    expect(resolveImageIcon("USDCASH_TEST")).toBe("/currency-icons/usd-cash.png");
    expect(resolveImageIcon("USDCASH2_TEST")).toBe("/currency-icons/usd-cash.png");
    expect(resolveImageIcon("usdcash27")).toBe("/currency-icons/usd-cash.png");
  });

  test("does NOT hijack the plain USD code (USD keeps its Zelle brand SVG)", () => {
    expect(resolveImageIcon("USD")).toBeNull();
    expect(resolveImageIcon("USDT")).toBeNull();
    expect(resolveImageIcon("USD_TEST_XFR")).toBeNull();
  });

  test("returns null for unknown / empty codes", () => {
    expect(resolveImageIcon("")).toBeNull();
    expect(resolveImageIcon(null)).toBeNull();
    expect(resolveImageIcon(undefined)).toBeNull();
    expect(resolveImageIcon("BTC")).toBeNull();
    expect(resolveImageIcon("CUP")).toBeNull();
  });
});
