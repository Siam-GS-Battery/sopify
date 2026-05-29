/* Charts: Output line chart + Donut */

const fmt = (n, d = 0) => n.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });

/* Output Line Chart with target line, gradient area, hover crosshair, tooltip */
const OutputChart = ({ data, target = 1200, height = 280 }) => {
  // data: [{ label: "08:00", value: 1180 }, ...]
  const wrapRef = React.useRef(null);
  const [width, setWidth] = React.useState(640);
  React.useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(400, e.contentRect.width)));
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const padL = 48, padR = 16, padT = 16, padB = 32;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const values = data.map((d) => d.value);
  const dataMax = Math.max(...values, target);
  const dataMin = Math.min(...values, target);
  const range = Math.max(50, dataMax - dataMin);
  const yMax = dataMax + range * 0.12;
  const yMin = Math.max(0, dataMin - range * 0.18);
  const yToPx = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;
  const xToPx = (i) => padL + (i / (data.length - 1)) * innerW;

  // ticks
  const tickCount = 5;
  const ticks = Array.from({ length: tickCount }, (_, i) => yMin + (i / (tickCount - 1)) * (yMax - yMin));

  const pts = data.map((d, i) => [xToPx(i), yToPx(d.value)]);
  const linePath = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${xToPx(data.length - 1)} ${yToPx(yMin)} L${xToPx(0)} ${yToPx(yMin)} Z`;

  const [hover, setHover] = React.useState(null); // index
  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if (x < padL || x > padL + innerW) { setHover(null); return; }
    const i = Math.round(((x - padL) / innerW) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  };

  const targetY = yToPx(target);

  return (
    <div ref={wrapRef} style={{ width: "100%", position: "relative" }}>
      <svg width={width} height={height} onMouseMove={onMove} onMouseLeave={() => setHover(null)}
        style={{ display: "block", cursor: "crosshair" }}>
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2563EB" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#2563EB" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* y-grid + labels */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} x2={padL + innerW} y1={yToPx(t)} y2={yToPx(t)} stroke="#E5E7EB" strokeDasharray="2 4" />
            <text x={padL - 8} y={yToPx(t) + 4} textAnchor="end" fontSize="11" fill="#9CA3AF" fontFamily="IBM Plex Mono">
              {fmt(t)}
            </text>
          </g>
        ))}
        {/* x labels */}
        {data.map((d, i) => (
          <text key={i} x={xToPx(i)} y={height - 10} textAnchor="middle" fontSize="11" fill="#9CA3AF" fontFamily="IBM Plex Mono">
            {d.label}
          </text>
        ))}
        {/* target line */}
        <line x1={padL} x2={padL + innerW} y1={targetY} y2={targetY} stroke="#10B981" strokeDasharray="4 4" strokeWidth="1.2" />
        <rect x={padL + innerW - 80} y={targetY - 22} width="80" height="18" rx="4" fill="#ECFDF5" />
        <text x={padL + innerW - 8} y={targetY - 9} textAnchor="end" fontSize="11" fontWeight="600" fill="#047857" fontFamily="IBM Plex Mono">
          Target {fmt(target)}
        </text>

        {/* area + line */}
        <path d={areaPath} fill="url(#areaGrad)" />
        <path d={linePath} fill="none" stroke="#2563EB" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

        {/* dots */}
        {pts.map(([x, y], i) => {
          const isLow = data[i].value < target;
          return (
            <circle key={i} cx={x} cy={y} r={hover === i ? 5 : 3.2}
              fill={isLow ? "#F59E0B" : "#2563EB"} stroke="#fff" strokeWidth="2" />
          );
        })}

        {/* hover crosshair */}
        {hover != null && (
          <g>
            <line x1={pts[hover][0]} x2={pts[hover][0]} y1={padT} y2={padT + innerH} stroke="#94A3B8" strokeDasharray="3 3" />
          </g>
        )}
      </svg>

      {hover != null && (() => {
        const [x, y] = pts[hover];
        const d = data[hover];
        const left = Math.min(width - 160, Math.max(0, x - 80));
        return (
          <div style={{
            position: "absolute", left, top: Math.max(0, y - 78),
            width: 160, pointerEvents: "none",
            background: "var(--text-1)", color: "#fff",
            borderRadius: 8, padding: "8px 10px", fontSize: 12, lineHeight: 1.35,
            boxShadow: "0 6px 18px rgba(15,23,42,0.25)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", color: "#CBD5E1", fontSize: 11 }}>
              <span className="mono">{d.label}</span>
              <span style={{ color: d.value >= target ? "#34D399" : "#FBBF24" }}>{d.value >= target ? "On target" : "Below"}</span>
            </div>
            <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>{fmt(d.value)} <span style={{ fontSize: 11, color: "#94A3B8", fontWeight: 500 }}>units/h</span></div>
            <div className="mono" style={{ fontSize: 11, color: "#94A3B8", marginTop: 2 }}>vs target {fmt(target)} ({d.value >= target ? "+" : ""}{fmt(d.value - target)})</div>
          </div>
        );
      })()}
    </div>
  );
};

/* Donut chart */
const Donut = ({ data, size = 200, thickness = 30, hovered, onHover }) => {
  // data: [{ label, value, color }]
  const total = data.reduce((a, b) => a + b.value, 0) || 1;
  const r = size / 2 - thickness / 2 - 2;
  const cx = size / 2, cy = size / 2;
  let acc = 0;
  const segs = data.map((d, i) => {
    const startAngle = (acc / total) * 2 * Math.PI - Math.PI / 2;
    acc += d.value;
    const endAngle = (acc / total) * 2 * Math.PI - Math.PI / 2;
    const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const path = `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
    return { d, path, i };
  });
  const totalDisplay = total;
  const focused = hovered != null ? data[hovered] : null;
  return (
    <svg width={size} height={size}>
      {segs.map((s) => (
        <path key={s.i}
          d={s.path}
          stroke={s.d.color}
          strokeWidth={hovered === s.i ? thickness + 6 : thickness}
          fill="none"
          strokeLinecap="butt"
          opacity={hovered == null || hovered === s.i ? 1 : 0.35}
          onMouseEnter={() => onHover && onHover(s.i)}
          onMouseLeave={() => onHover && onHover(null)}
          style={{ transition: "opacity 120ms, stroke-width 120ms", cursor: "pointer" }}
        />
      ))}
      <text x={cx} y={cy - 8} textAnchor="middle" fontSize="11" fill="#6B7280">
        {focused ? focused.label : "Total"}
      </text>
      <text x={cx} y={cy + 16} textAnchor="middle" fontSize="22" fontWeight="700" fill="#111827" fontFamily="IBM Plex Mono">
        {focused ? fmt(focused.value) : fmt(totalDisplay)}
      </text>
      <text x={cx} y={cy + 34} textAnchor="middle" fontSize="11" fill="#9CA3AF" fontFamily="IBM Plex Mono">kWh</text>
    </svg>
  );
};

Object.assign(window, { OutputChart, Donut, fmt });
