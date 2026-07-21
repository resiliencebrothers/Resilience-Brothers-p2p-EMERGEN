/**
 * iter — computeQuickRange + detectActivePreset pure-function tests.
 *
 * Run: yarn test src/components/__tests__/QuickDateRange.test.js
 */
import { computeQuickRange, detectActivePreset } from "../QuickDateRange";

// A fixed reference "now" used by every test so the assertions are stable
// regardless of when the suite is executed.
const NOW = new Date(2026, 5, 15); // Jun 15, 2026 local

describe("computeQuickRange", () => {
  test("last 7 days is [today-6 .. today] inclusive", () => {
    const r = computeQuickRange("7d", NOW);
    expect(r.until).toBe("2026-06-15");
    expect(r.since).toBe("2026-06-09");
  });

  test("this month starts on day 1 and ends today", () => {
    const r = computeQuickRange("month", NOW);
    expect(r.since).toBe("2026-06-01");
    expect(r.until).toBe("2026-06-15");
  });

  test("this year starts on Jan 1 and ends today", () => {
    const r = computeQuickRange("year", NOW);
    expect(r.since).toBe("2026-01-01");
    expect(r.until).toBe("2026-06-15");
  });

  test("unknown preset clears the range", () => {
    expect(computeQuickRange("nope", NOW)).toEqual({ since: "", until: "" });
  });

  test("7-day window crossing a month boundary", () => {
    // Mar 2, 2026 → since should land on Feb 24 of the same year.
    const near = new Date(2026, 2, 2);
    const r = computeQuickRange("7d", near);
    expect(r.until).toBe("2026-03-02");
    expect(r.since).toBe("2026-02-24");
  });
});

describe("detectActivePreset", () => {
  test("detects last-7-days when since/until match", () => {
    const r = computeQuickRange("7d", NOW);
    expect(detectActivePreset(r.since, r.until, NOW)).toBe("7d");
  });

  test("detects this-month when since/until match", () => {
    const r = computeQuickRange("month", NOW);
    expect(detectActivePreset(r.since, r.until, NOW)).toBe("month");
  });

  test("detects this-year when since/until match", () => {
    const r = computeQuickRange("year", NOW);
    expect(detectActivePreset(r.since, r.until, NOW)).toBe("year");
  });

  test("returns null for arbitrary user-entered range", () => {
    expect(detectActivePreset("2024-01-10", "2024-02-20", NOW)).toBeNull();
  });

  test("returns null when either bound is empty", () => {
    expect(detectActivePreset("", "2026-06-15", NOW)).toBeNull();
    expect(detectActivePreset("2026-06-09", "", NOW)).toBeNull();
    expect(detectActivePreset("", "", NOW)).toBeNull();
  });
});
