// Origen de cada fila del libro contable: en qué sección NACE el movimiento
// y a dónde debe ir el admin para operarlo. Transacciones solo lee.
export const ORIGIN = {
  order: {
    route: "/admin/orders", go: "orders", idKey: "order",
    cls: "text-[#A78BFA] border-[#8B5CF6]/40 bg-[#8B5CF6]/10",
  },
  order_payout: {
    route: "/admin/orders", go: "orders", idKey: "order",
    cls: "text-[#A78BFA] border-[#8B5CF6]/40 bg-[#8B5CF6]/10",
  },
  deposit: {
    route: "/admin/withdrawals?tab=deposits", go: "deposits", idKey: "deposit",
    cls: "text-emerald-400 border-emerald-500/40 bg-emerald-500/10",
  },
  withdrawal: {
    route: "/admin/withdrawals", go: "withdrawals", idKey: "withdrawal",
    cls: "text-orange-400 border-orange-500/40 bg-orange-500/10",
  },
  company_adjustment: {
    route: "/admin/company-funds", go: "company", idKey: "movement",
    cls: "text-amber-400 border-amber-500/40 bg-amber-500/10",
  },
  company_withdrawal: {
    route: "/admin/company-funds", go: "company", idKey: "movement",
    cls: "text-amber-400 border-amber-500/40 bg-amber-500/10",
  },
  vip_batch_item: {
    route: "/admin/vip-batches", go: "vip", idKey: "batch",
    cls: "text-sky-400 border-sky-500/40 bg-sky-500/10",
  },
};

export const FALLBACK_ORIGIN = {
  route: "/admin/orders", go: "orders", idKey: "ref",
  cls: "text-neutral-400 border-white/15 bg-white/5",
};

export const originOf = (refType) => ORIGIN[refType] || FALLBACK_ORIGIN;

// Valor del filtro «Origen» → lista de ref_type que entiende el backend.
export const ORIGIN_FILTERS = {
  all: "",
  orders: "order,order_payout",
  deposits: "deposit",
  withdrawals: "withdrawal",
  company: "company_adjustment,company_withdrawal",
  vip: "vip_batch_item",
};
