const fs = require('fs'), assert = require('assert/strict');
const src = fs.readFileSync('/app/frontend/src/components/BalanceConverterCard.jsx', 'utf8');
const body = src.match(/const submit = async \(\) => \{([\s\S]*?)\n  \};/)[1];
function scenario(errors) {
  const payloads = [];
  let index = 0;
  const globals = {
    amount: '10', toCode: 'CUP', fromCode: 'USDT',
    positive: [{ currency: 'USDT', amount: 100 }],
    belowMinSource: false, previewSourceUsdt: 10,
    CONVERT_MIN_SOURCE_USDT: 1, CONVERT_FEE_USDT: 0.01, usdtBalance: 100,
    setBusy: () => {}, opIdRef: { current: null },
    crypto: { randomUUID: () => `rt02-op-${payloads.length + 1}` },
    API: '/api', previewRate: 100,
    toast: { error: () => {}, success: () => {}, warning: () => {} },
    setOpen: () => {}, refresh: async () => {}, onConverted: null,
    extractDetailMessage: (e, f) => e?.response?.data?.detail?.code || f,
  };
  globals.axios = { post: async (url, p) => { payloads.push(p); const e = errors[index++]; if (e) throw e; return { data: { amount_to: 1000, usdt_fee: 0.01 } }; } };
  const invoke = () => new Function(...Object.keys(globals), 'return (async()=>{' + body + '})();')(...Object.values(globals));
  return { payloads, invoke, globals };
}
(async () => {
  // 1. 500 tras mover saldo → CONSERVA la clave.
  const a = scenario([{ response: { status: 500, data: { detail: 'seal failed' } } }, null]);
  await a.invoke(); await a.invoke();
  assert.equal(a.payloads.length, 2);
  assert.equal(a.payloads[0].op_id, a.payloads[1].op_id);
  console.log('PASS 5xx conserva op_id:', a.payloads.map(p => p.op_id).join(','));
  // 2. red → 409 in-progress → CONSERVA en ambos.
  const b = scenario([new Error('network'), { response: { status: 409, data: { detail: { code: 'CONVERSION_IN_PROGRESS' } } } }, null]);
  await b.invoke(); await b.invoke(); await b.invoke();
  assert.equal(new Set(b.payloads.map(p => p.op_id)).size, 1);
  console.log('PASS red+409-en-curso conservan op_id:', b.payloads.map(p => p.op_id).join(','));
  // 3. 409 QUOTE_CHANGED (terminal, no ejecutó) → renueva.
  const c = scenario([{ response: { status: 409, data: { detail: { code: 'QUOTE_CHANGED', amount_to: 800 } } } }, null]);
  await c.invoke(); await c.invoke();
  assert.notEqual(c.payloads[0].op_id, c.payloads[1].op_id);
  console.log('PASS 409 terminal renueva op_id:', c.payloads.map(p => p.op_id).join(','));
  // 4. éxito → renueva para la próxima intención.
  const d = scenario([null, null]);
  await d.invoke(); await d.invoke();
  assert.notEqual(d.payloads[0].op_id, d.payloads[1].op_id);
  console.log('PASS éxito renueva op_id:', d.payloads.map(p => p.op_id).join(','));
  // 5. 400 saldo insuficiente (terminal) → renueva.
  const e = scenario([{ response: { status: 400, data: { detail: 'saldo' } } }, null]);
  await e.invoke(); await e.invoke();
  assert.notEqual(e.payloads[0].op_id, e.payloads[1].op_id);
  console.log('PASS 400 terminal renueva op_id');
  console.log('RT02 FRONTEND: 5/5 OK');
})().catch(err => { console.error('FAIL', err); process.exit(1); });
