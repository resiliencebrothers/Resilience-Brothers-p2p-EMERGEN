import { useEffect, useState } from "react";
import axios from "axios";
import { API } from "@/App";

const IDLE = { loading: false, hasTiers: false, account: null, minRequired: null, belowMin: false };

// iter143 — resolves WHICH payment account the client must send to,
// given the currency and the amount they will send. Debounced 350ms.
export function usePaymentAccount(currencyCode, amount) {
  const [state, setState] = useState(IDLE);

  useEffect(() => {
    if (!currencyCode) { setState(IDLE); return undefined; }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    const timer = setTimeout(() => {
      axios.get(`${API}/payment-accounts/resolve`, {
        params: { currency: currencyCode, amount: Number(amount) || 0 },
        withCredentials: true,
      })
        .then((r) => {
          if (cancelled) return;
          setState({
            loading: false,
            hasTiers: !!r.data.has_tiers,
            account: r.data.account || null,
            minRequired: r.data.min_required ?? null,
            belowMin: !!r.data.below_min,
          });
        })
        .catch(() => { if (!cancelled) setState(IDLE); });
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [currencyCode, amount]);

  return state;
}
