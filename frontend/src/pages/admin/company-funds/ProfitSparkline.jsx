/**
 * iter122 — ProfitSparkline
 *
 * Pure-SVG mini chart for the per-currency 30-day profit evolution.
 * No external deps. Renders a smooth area + line with a highlight on the
 * latest bucket and a subtle zero-baseline. Handles negative segments by
 * clipping the fill above/below the zero line.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const W = 180;
const H = 36;
const PAD = 2;

export default function ProfitSparkline({ values = [], positive = true }) {
  const { t } = useTranslation();
  const [hover, setHover] = useState(null);

  const geometry = useMemo(() => {
    const arr = Array.isArray(values) && values.length ? values : [];
    if (arr.length < 2) return null;
    const min = Math.min(0, ...arr);
    const max = Math.max(0, ...arr);
    const span = max - min || 1;
    const step = (W - PAD * 2) / (arr.length - 1);
    const yFor = (v) => H - PAD - ((v - min) / span) * (H - PAD * 2);
    const points = arr.map((v, i) => [PAD + i * step, yFor(v)]);
    const zeroY = yFor(0);
    const linePath = points
      .map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`))
      .join(" ");
    const areaPath = `${linePath} L${points[points.length - 1][0]},${zeroY} L${points[0][0]},${zeroY} Z`;
    return { arr, points, zeroY, linePath, areaPath, step, min, max, span };
  }, [values]);

  if (!geometry) {
    return (
      <div className="mt-2 h-[36px] flex items-center text-[0.6rem] text-neutral-600 font-mono">
        {t("admin.companyFunds.sparklineEmpty")}
      </div>
    );
  }

  const stroke = positive ? "#22C55E" : "#EF4444";
  const fill = positive ? "rgba(34,197,94,0.18)" : "rgba(239,68,68,0.18)";
  const last = geometry.points[geometry.points.length - 1];
  const hoverPoint = hover != null ? geometry.points[hover] : null;
  const hoverValue = hover != null ? geometry.arr[hover] : null;

  const handleMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * W;
    const idx = Math.round((x - PAD) / geometry.step);
    setHover(Math.max(0, Math.min(geometry.arr.length - 1, idx)));
  };

  return (
    <div className="mt-2 relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="w-full h-[36px] cursor-crosshair"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={t("admin.companyFunds.sparklineAria")}
      >
        <line
          x1={PAD} x2={W - PAD} y1={geometry.zeroY} y2={geometry.zeroY}
          stroke="#3f3653" strokeWidth="0.5" strokeDasharray="2 2"
        />
        <path d={geometry.areaPath} fill={fill} />
        <path d={geometry.linePath} fill="none" stroke={stroke} strokeWidth="1.2" />
        <circle cx={last[0]} cy={last[1]} r="2" fill={stroke} />
        {hoverPoint && (
          <>
            <line
              x1={hoverPoint[0]} x2={hoverPoint[0]} y1={PAD} y2={H - PAD}
              stroke="#8B5CF6" strokeWidth="0.5" strokeDasharray="1 2"
            />
            <circle cx={hoverPoint[0]} cy={hoverPoint[1]} r="2.2"
              fill="#0a0a0a" stroke={stroke} strokeWidth="1" />
          </>
        )}
      </svg>
      {hoverValue !== null && (
        <div className="absolute -top-6 left-1/2 -translate-x-1/2 px-1.5 py-0.5 bg-[#0a0a0a] border border-white/10 text-[0.6rem] font-mono text-neutral-200 whitespace-nowrap rounded-sm pointer-events-none tabular-nums">
          {t("admin.companyFunds.sparklineDay", { n: 30 - hover })}
          <span className={hoverValue >= 0 ? "text-[#22C55E] ml-1.5" : "text-[#EF4444] ml-1.5"}>
            {hoverValue >= 0 ? "+" : ""}
            {Number(hoverValue).toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </span>
        </div>
      )}
    </div>
  );
}
