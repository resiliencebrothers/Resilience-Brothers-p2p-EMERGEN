import { fmtNum } from "./userStatsMeta";

export default function NetPositionCard({ netPosition }) {
  const direction = netPosition.direction;
  return (
    <div className="tactile-card p-6" data-testid="user-stats-net-position">
      <div className="micro-label text-neutral-500 mb-2">Posición neta empresa ↔ cliente</div>
      {direction === "platform_owes_client" && (
        <>
          <div className="font-display text-4xl text-emerald-400 tabular-nums">
            +{fmtNum(netPosition.net_usdt, 2)} USDT
          </div>
          <div className="text-sm text-neutral-400 mt-1">
            La empresa <strong className="text-emerald-400">le debe</strong> este monto al cliente
            (saldo acumulado {fmtNum(netPosition.platform_owes_client_usdt, 2)} USDT − deuda pendiente {fmtNum(netPosition.client_owes_platform_usdt, 2)} USDT).
          </div>
        </>
      )}
      {direction === "client_owes_platform" && (
        <>
          <div className="font-display text-4xl text-red-400 tabular-nums">
            −{fmtNum(Math.abs(netPosition.net_usdt), 2)} USDT
          </div>
          <div className="text-sm text-neutral-400 mt-1">
            El cliente <strong className="text-red-400">le debe</strong> este monto a la empresa
            (deuda por capital operativo {fmtNum(netPosition.client_owes_platform_usdt, 2)} USDT − saldo acumulado {fmtNum(netPosition.platform_owes_client_usdt, 2)} USDT).
          </div>
        </>
      )}
      {direction === "even" && (
        <>
          <div className="font-display text-4xl text-neutral-400 tabular-nums">
            0.00 USDT
          </div>
          <div className="text-sm text-neutral-500 mt-1">
            Cuentas equilibradas — sin saldo pendiente en ningún sentido.
          </div>
        </>
      )}
    </div>
  );
}
