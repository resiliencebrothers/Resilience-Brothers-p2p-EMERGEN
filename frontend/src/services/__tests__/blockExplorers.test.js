/**
 * iter55.19f — buildExplorerUrl + explorerLabel pure-function tests.
 *
 * Run: yarn test src/services/__tests__/blockExplorers.test.js
 */
import { buildExplorerUrl, explorerLabel } from "../blockExplorers";

describe("buildExplorerUrl", () => {
  test("returns Tronscan URL for TRC20", () => {
    expect(buildExplorerUrl("TRC20", "abc123")).toBe(
      "https://tronscan.org/#/transaction/abc123"
    );
  });

  test("returns BscScan URL for BEP20", () => {
    expect(buildExplorerUrl("BEP20", "0xdead")).toBe(
      "https://bscscan.com/tx/0xdead"
    );
  });

  test("returns Etherscan URL for ERC20", () => {
    expect(buildExplorerUrl("ERC20", "0xbeef")).toBe(
      "https://etherscan.io/tx/0xbeef"
    );
  });

  test("returns Polygonscan URL for POLYGON", () => {
    expect(buildExplorerUrl("POLYGON", "0xf00d")).toBe(
      "https://polygonscan.com/tx/0xf00d"
    );
  });

  test("case-insensitive network code", () => {
    expect(buildExplorerUrl("trc20", "abc")).toBe(
      "https://tronscan.org/#/transaction/abc"
    );
    expect(buildExplorerUrl(" Bep20 ", "abc")).toBe(
      "https://bscscan.com/tx/abc"
    );
  });

  test("returns null for empty hash", () => {
    expect(buildExplorerUrl("TRC20", "")).toBeNull();
    expect(buildExplorerUrl("TRC20", "   ")).toBeNull();
    expect(buildExplorerUrl("TRC20", null)).toBeNull();
  });

  test("returns null for empty/unsupported network", () => {
    expect(buildExplorerUrl("", "abc")).toBeNull();
    expect(buildExplorerUrl(null, "abc")).toBeNull();
    expect(buildExplorerUrl("AMBIGUOUS_0X", "abc")).toBeNull();
    expect(buildExplorerUrl("SOMETHING", "abc")).toBeNull();
  });

  test("trims whitespace from hash", () => {
    expect(buildExplorerUrl("TRC20", "  abc  ")).toBe(
      "https://tronscan.org/#/transaction/abc"
    );
  });
});

describe("explorerLabel", () => {
  test("returns friendly labels", () => {
    expect(explorerLabel("TRC20")).toBe("Tronscan");
    expect(explorerLabel("BEP20")).toBe("BscScan");
    expect(explorerLabel("ERC20")).toBe("Etherscan");
    expect(explorerLabel("POLYGON")).toBe("Polygonscan");
    expect(explorerLabel("SOLANA")).toBe("Solscan");
    expect(explorerLabel("BTC")).toBe("Mempool");
  });

  test("falls back to 'Explorer' for unknown or empty", () => {
    expect(explorerLabel("")).toBe("Explorer");
    expect(explorerLabel(null)).toBe("Explorer");
    expect(explorerLabel("MADEUP")).toBe("Explorer");
  });
});
