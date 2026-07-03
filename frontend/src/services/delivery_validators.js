/**
 * iter55.10 — Central validators for `delivery_details` per (to_code, method).
 *
 * Every entry returns { ok, hint, feedback } where:
 *   - `hint`     is shown BEFORE the user types (short instruction + example)
 *   - `feedback` (from `validate()`) is the live feedback below the textarea
 *   - `ok`       is used to render green ✓ vs red ⚠
 *
 * Adding a new country / rail: append an entry to VALIDATORS[to_code][method]
 * and (optionally) a country-agnostic fallback if you want gentle guidance
 * without hard-blocking exotic destinations.
 */

const digitCount = (str) => (str.match(/\d/g) || []).length;

// -------- Individual validator factories --------

const validators = {
  // Cuba — CUP transfer (16-digit magnetic card)
  cup_transfer: {
    hint: "La cuenta bancaria cubana debe tener 16 dígitos (ej. 9212 9598 7274 4356).",
    icon: "📇",
    example: "Juan Pérez\n9212 9598 7274 4356",
    validate: (text) => {
      const n = digitCount(text);
      if (n === 0) return null;
      if (n === 16) return { ok: true, feedback: "✓ 16 dígitos detectados" };
      return { ok: false, feedback: `⚠ ${n} dígitos — faltan/sobran ${Math.abs(16 - n)}` };
    },
  },

  // Cuba — CUP cash (person at address)
  cup_cash: {
    hint: "Incluye nombre completo, teléfono cubano (+53 XXXX XXXX) y dirección de entrega.",
    icon: "🏠",
    example: "María López\n+53 5432 1098\nCalle 23 nº 123, Vedado, La Habana",
    validate: (text) => {
      const hasPhone = /\+?53[\s-]?\d{4}[\s-]?\d{4}/.test(text) || /\b\d{8}\b/.test(text);
      const hasName = text.trim().split(/\s+/).length >= 2;
      const long = text.trim().length >= 30;
      if (!hasName && !hasPhone) return null;
      if (hasName && hasPhone && long) return { ok: true, feedback: "✓ Nombre + teléfono + dirección detectados" };
      const missing = [];
      if (!hasName) missing.push("nombre completo");
      if (!hasPhone) missing.push("teléfono cubano (8 dígitos)");
      if (!long) missing.push("dirección más detallada");
      return { ok: false, feedback: `⚠ Falta: ${missing.join(", ")}` };
    },
  },

  // México — CLABE 18 digits
  mxn_transfer: {
    hint: "La cuenta CLABE mexicana tiene 18 dígitos.",
    icon: "🏦",
    example: "María García\nCLABE: 646180157012345678",
    validate: (text) => {
      const n = digitCount(text);
      if (n === 0) return null;
      if (n === 18) return { ok: true, feedback: "✓ 18 dígitos (CLABE)" };
      return { ok: false, feedback: `⚠ ${n} dígitos — CLABE espera 18` };
    },
  },

  // Brasil — PIX (CPF/CNPJ/email/phone/random)
  brl_transfer: {
    hint: "Chave PIX: CPF (11 dígitos), CNPJ (14), email, teléfono (+55...) o chave aleatoria UUID.",
    icon: "🇧🇷",
    example: "PIX: cliente@email.com",
    validate: (text) => {
      const trimmed = text.trim();
      if (!trimmed) return null;
      const digits = digitCount(text);
      const isEmail = /@[\w.-]+\.\w{2,}/.test(text);
      const isPhone = /\+?55/.test(text) && digits >= 10;
      const isCpf = digits === 11;
      const isCnpj = digits === 14;
      const isUuid = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.test(text);
      const ok = isEmail || isPhone || isCpf || isCnpj || isUuid;
      return ok
        ? { ok: true, feedback: `✓ PIX válido (${isEmail ? "email" : isPhone ? "teléfono" : isCpf ? "CPF" : isCnpj ? "CNPJ" : "UUID"})` }
        : { ok: false, feedback: "⚠ Formato PIX no reconocido" };
    },
  },

  // Zelle (US) — email or US phone
  zelle_transfer: {
    hint: "Zelle acepta email o teléfono US (+1 XXX-XXX-XXXX).",
    icon: "💠",
    example: "cliente@email.com  o  +1 305 123 4567",
    validate: (text) => {
      const t = text.trim();
      if (!t) return null;
      const isEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(t) || /@[\w.-]+\.\w{2,}/.test(text);
      const digits = digitCount(text);
      const isUsPhone = digits >= 10 && digits <= 11 && /\+?1?[\s.\-(]?\d{3}/.test(text);
      const ok = isEmail || isUsPhone;
      return ok
        ? { ok: true, feedback: `✓ ${isEmail ? "Email" : "Teléfono US"} válido para Zelle` }
        : { ok: false, feedback: "⚠ Zelle espera email o teléfono US" };
    },
  },

  // US transfer — routing + account
  usd_transfer: {
    hint: "Cuenta US: routing number (9 dígitos) + número de cuenta.",
    icon: "🏦",
    example: "Titular: John Doe\nRouting: 021000021\nAccount: 1234567890",
    validate: (text) => {
      const n = digitCount(text);
      if (n === 0) return null;
      if (n >= 13) return { ok: true, feedback: `✓ ${n} dígitos (routing + cuenta)` };
      return { ok: false, feedback: `⚠ Muy corto (${n} dígitos). Incluye routing (9) + cuenta.` };
    },
  },

  // Colombia — cédula (6-10 digits) + banco + cuenta
  cop_transfer: {
    hint: "Cuenta colombiana: cédula titular + banco + número de cuenta.",
    icon: "🇨🇴",
    example: "Ana Ruiz\nCC 1024567890\nBancolombia · 0011234567",
    validate: (text) => {
      if (digitCount(text) < 8) return { ok: false, feedback: "⚠ Falta cédula o número de cuenta" };
      return { ok: true, feedback: "✓ Datos completos" };
    },
  },

  // Euro — IBAN (varies per country, ~14–34 alphanumeric)
  eur_transfer: {
    hint: "IBAN europeo: 2 letras país + hasta 34 caracteres.",
    icon: "🇪🇺",
    example: "María López\nES91 2100 0418 4502 0005 1332",
    validate: (text) => {
      const iban = text.replace(/\s/g, "").match(/[A-Z]{2}\d{2}[A-Z0-9]{10,30}/i);
      if (!iban) return digitCount(text) === 0 ? null : { ok: false, feedback: "⚠ No detecto un IBAN válido" };
      return { ok: true, feedback: `✓ IBAN detectado (${iban[0].length} chars)` };
    },
  },

  // AED — UAE IBAN
  aed_transfer: {
    hint: "IBAN de EAU: 23 caracteres (AE + 21 dígitos).",
    icon: "🇦🇪",
    example: "AE07 0331 2345 6789 0123 456",
    validate: (text) => {
      const iban = text.replace(/\s/g, "").match(/AE\d{21}/i);
      if (!iban) return digitCount(text) === 0 ? null : { ok: false, feedback: "⚠ IBAN AE debe iniciar con AE + 21 dígitos" };
      return { ok: true, feedback: "✓ IBAN AE válido" };
    },
  },

  // Crypto — universal
  crypto_wallet: {
    // Dynamic hint per token below
    icon: "🔗",
    validate: (text, ctx) => {
      const clean = text.trim();
      if (!clean) return null;
      const code = (ctx?.code || "").toUpperCase();

      // Network keywords the user may include ("TRC20", "BEP20", "ERC20"...)
      const upper = text.toUpperCase();
      const netHints = {
        BEP20: /\b(BEP[\s-]?20|BSC|BINANCE\s*SMART\s*CHAIN)\b/.test(upper),
        TRC20: /\b(TRC[\s-]?20|TRON)\b/.test(upper),
        ERC20: /\b(ERC[\s-]?20|ETH(EREUM)?)\b/.test(upper),
        POLYGON: /\b(POLYGON|MATIC)\b/.test(upper),
      };

      // TRC20 (USDT/TRX): starts with T + base58, 34 chars — inequivocable
      const trc20 = clean.match(/T[1-9A-HJ-NP-Za-km-z]{33}/);
      if (trc20) {
        return { ok: true, feedback: "✓ Dirección TRC20 (Tron) válida" };
      }
      // BTC-style — inequivocable
      if (/^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$/.test(clean)) {
        return { ok: true, feedback: "✓ Dirección BTC válida" };
      }
      // 0x + 40 hex — could be ERC20 / BEP20 / POLYGON. Require the user to
      // spell out the network in the text so staff sends on the correct chain.
      const evm = clean.match(/0x[a-fA-F0-9]{40}/);
      if (evm) {
        if (netHints.BEP20) return { ok: true, feedback: "✓ Dirección BEP20 (Binance Smart Chain) válida" };
        if (netHints.ERC20) return { ok: true, feedback: "✓ Dirección ERC20 (Ethereum) válida" };
        if (netHints.POLYGON) return { ok: true, feedback: "✓ Dirección POLYGON válida" };
        // Address is syntactically correct but the network is ambiguous — this
        // is critical because sending BEP20 funds to an ERC20-only exchange
        // loses the money. Warn instead of confirming.
        return {
          ok: false,
          feedback: "⚠ Dirección 0x válida pero falta indicar la RED (BEP20, ERC20 o POLYGON)",
        };
      }
      // Solana: base58, 32-44 chars, not starting with T
      if (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(clean) && !clean.startsWith("T")) {
        return code === "SOL"
          ? { ok: true, feedback: "✓ Dirección Solana válida" }
          : null;
      }
      return { ok: false, feedback: "⚠ Formato de wallet no reconocido. Verifica red y dirección." };
    },
  },
};

// -------- Dispatch table (to_code + method → validator key) --------

const dispatch = {
  CUP: { transfer: "cup_transfer", cash: "cup_cash" },
  CUPT: { transfer: "cup_transfer" },
  CUPE: { transfer: "cup_transfer", cash: "cup_cash" },
  MXN: { transfer: "mxn_transfer" },
  BRL: { transfer: "brl_transfer" },
  ZELLE: { transfer: "zelle_transfer" },
  USD: { transfer: "usd_transfer" },
  COP: { transfer: "cop_transfer" },
  EUR: { transfer: "eur_transfer" },
  AED: { transfer: "aed_transfer" },
};

/**
 * Return the validator descriptor for a given `(to_code, method)` combo, or
 * `null` when we don't have specific rules. Callers should render the hint
 * and feedback in the UI when a descriptor is returned.
 */
export function getDeliveryValidator(toCode, method, currencyType) {
  if (!toCode || !method) return null;
  // Crypto: covered generically by wallet-shape regex regardless of code
  if (method === "crypto" || currencyType === "crypto") {
    const code = (toCode || "").toUpperCase();
    // Per-token guidance — BEP20 is our client base's most-used USDT network.
    const guidance = {
      USDT: {
        hint: "Wallet USDT. Redes soportadas: BEP20 (recomendada), TRC20, ERC20. Indica la red junto a la dirección.",
        example: "0x1234abcd… (Red: BEP20)\n— o —\nTKa1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q (TRC20)",
      },
      BTC: {
        hint: "Wallet Bitcoin (BTC). Acepta segwit (bc1…), legacy (1…) o P2SH (3…).",
        example: "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
      },
    };
    const g = guidance[code] || {
      hint: `Dirección de wallet para ${toCode}. Verifica la red antes de enviar.`,
      example: "0xabcdef0123456789… (Red: BEP20/ERC20)",
    };
    return { ...validators.crypto_wallet, ...g, code: toCode };
  }
  const key = dispatch[toCode.toUpperCase()]?.[method];
  return key ? { ...validators[key], code: toCode } : null;
}

/** Convenience for the admin-side one-line summary shown as a badge. */
export function getDeliveryBadge(toCode, method, deliveryDetails, currencyType) {
  const v = getDeliveryValidator(toCode, method, currencyType);
  if (!v || !deliveryDetails) return null;
  return v.validate(deliveryDetails, { code: toCode });
}
