/* Panels: KPI strip, Output card, Machine grid, Alerts table, Energy card */

/* ----- KPI strip ----- */

const KPI_DEFS = [
  { key: "oee",         label: "OEE",          th: "ประสิทธิภาพรวม",  start: 84.2, target: 85,  trend: { value: 2.1, direction: "up" } },
  { key: "availability",label: "Availability", th: "ความพร้อมใช้งาน",  start: 91.5, target: 95,  trend: { value: 0.8, direction: "down" } },
  { key: "performance", label: "Performance",  th: "ประสิทธิภาพ",       start: 92.0, target: 92,  trend: { value: 1.2, direction: "up" } },
  { key: "quality",     label: "Quality",      th: "คุณภาพ",            start: 99.7, target: 99.5,trend: { value: 0.0, direction: "flat" } },
];

// Seeded random for stable initial sparklines
const seedRand = (seed) => {
  let s = seed;
  return () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
};
const makeSparkData = (seed, base, jitter = 1.4, n = 24) => {
  const r = seedRand(seed);
  const arr = [];
  let v = base - jitter * 1.5;
  for (let i = 0; i < n; i++) {
    v += (r() - 0.5) * jitter * 0.8;
    v = Math.max(base - jitter * 3, Math.min(base + jitter * 2, v));
    arr.push(v);
  }
  // anchor end to base
  arr[n - 1] = base;
  return arr;
};

const KpiCard = ({ def, value, sparkData }) => {
  const trend = def.trend;
  const trendColor = trend.direction === "up" ? "var(--success)" : trend.direction === "down" ? "var(--error)" : "var(--text-3)";
  const trendBg    = trend.direction === "up" ? "var(--success-soft)" : trend.direction === "down" ? "var(--error-soft)" : "#F1F5F9";
  const symbol     = trend.direction === "up" ? "↑" : trend.direction === "down" ? "↓" : "→";
  return (
    <div style={{
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)",
      padding: 20,
      display: "flex",
      flexDirection: "column",
      gap: 8,
      position: "relative",
      overflow: "hidden",
      transition: "border-color 120ms, box-shadow 120ms",
    }}
    onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "var(--shadow-md)"; e.currentTarget.style.borderColor = "var(--border-strong)"; }}
    onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "none"; e.currentTarget.style.borderColor = "var(--border)"; }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0, flex: 1 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-2)", letterSpacing: 0.4, textTransform: "uppercase", lineHeight: 1.3, whiteSpace: "nowrap" }}>{def.label}</span>
          <span style={{ fontSize: 11, color: "var(--text-3)", lineHeight: 1.4, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{def.th}</span>
        </div>
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "3px 8px", borderRadius: 999, background: trendBg, color: trendColor,
          fontSize: 11, fontWeight: 700,
        }}>
          <span className="mono">{symbol}</span>
          <span className="mono">{trend.value.toFixed(1)}%</span>
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 2 }}>
        <span className="num" style={{ fontSize: 36, fontWeight: 700, letterSpacing: -1.2, color: "var(--text-1)", lineHeight: 1 }}>
          {value.toFixed(1)}
        </span>
        <span className="num" style={{ fontSize: 16, color: "var(--text-2)", fontWeight: 500 }}>%</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 11, color: "var(--text-3)" }}>
        <span>Target <span className="mono" style={{ color: "var(--text-2)", fontWeight: 600 }}>{def.target}%</span></span>
        <span className="mono">last 24h</span>
      </div>

      <div style={{ marginTop: 4 }}>
        <Sparkline data={sparkData} width={260} height={36}
          stroke={trend.direction === "down" ? "var(--error)" : "var(--primary)"}
          fill={trend.direction === "down" ? "rgba(239,68,68,0.10)" : "rgba(37,99,235,0.10)"} />
      </div>
    </div>
  );
};

const KpiStrip = ({ values, sparks }) => (
  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
    {KPI_DEFS.map((def) => (
      <KpiCard key={def.key} def={def} value={values[def.key]} sparkData={sparks[def.key]} />
    ))}
  </div>
);

/* ----- Machine Grid ----- */

const MACHINES = [
  { id: "LINE-A-01", name: "Casting A1",   status: "running", cycle: 42.1, units: 312 },
  { id: "LINE-A-02", name: "Casting A2",   status: "running", cycle: 41.8, units: 308 },
  { id: "FORMING-03",name: "Forming 03",   status: "running", cycle: 56.4, units: 218 },
  { id: "ASSY-B-01", name: "Assembly B1",  status: "idle",    cycle: 0,    units: 0 },
  { id: "ASSY-B-02", name: "Assembly B2",  status: "running", cycle: 38.2, units: 341 },
  { id: "FILL-C-01", name: "Acid Fill C1", status: "fault",   cycle: 0,    units: 0 },
  { id: "TEST-D-01", name: "QC Test D1",   status: "running", cycle: 28.6, units: 412 },
  { id: "PACK-E-01", name: "Packing E1",   status: "down",    cycle: 0,    units: 0 },
  { id: "PACK-E-02", name: "Packing E2",   status: "running", cycle: 22.9, units: 488 },
];

const MachineTile = ({ m, selected, onSelect }) => {
  const s = STATUS[m.status];
  return (
    <button onClick={() => onSelect(m.id)}
      style={{
        textAlign: "left",
        background: "var(--surface)",
        border: `1px solid ${selected ? "var(--primary)" : "var(--border)"}`,
        boxShadow: selected ? "0 0 0 3px rgba(37,99,235,0.12)" : "none",
        borderRadius: 8,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        position: "relative",
        cursor: "pointer",
        transition: "border-color 120ms, box-shadow 120ms",
        minHeight: 96,
      }}
      onMouseEnter={(e) => { if (!selected) e.currentTarget.style.borderColor = "var(--border-strong)"; }}
      onMouseLeave={(e) => { if (!selected) e.currentTarget.style.borderColor = "var(--border)"; }}
    >
      {/* Top: id + status dot */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
          <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: "var(--text-1)", letterSpacing: 0.3, lineHeight: 1.25, whiteSpace: "nowrap" }}>{m.id}</span>
          <span style={{ fontSize: 11, color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.3 }}>{m.name}</span>
        </div>
        <span style={{
          width: 10, height: 10, borderRadius: "50%", background: s.dot, flex: "0 0 10px",
          boxShadow: m.status === "running" ? "0 0 0 3px rgba(16,185,129,0.18)" : m.status === "fault" ? "0 0 0 3px rgba(239,68,68,0.18)" : "none",
          animation: m.status === "fault" ? "pulse 1.4s ease-in-out infinite" : "none",
        }} />
      </div>

      {/* Status pill */}
      <StatusPill status={m.status} size="sm" />

      {/* Cycle */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginTop: "auto" }}>
        <span style={{ fontSize: 10, color: "var(--text-3)", fontWeight: 500, letterSpacing: 0.4, textTransform: "uppercase" }}>Cycle</span>
        <span className="num" style={{ fontSize: 13, fontWeight: 700, color: m.status === "running" ? "var(--text-1)" : "var(--text-3)" }}>
          {m.status === "running" ? `${m.cycle.toFixed(1)}s` : "—"}
        </span>
      </div>
    </button>
  );
};

const MachineGrid = ({ machines, selected, onSelect }) => (
  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
    {machines.map((m) => (
      <MachineTile key={m.id} m={m} selected={selected === m.id} onSelect={onSelect} />
    ))}
  </div>
);

/* ----- Alerts Table ----- */

const SEVERITY = {
  error:   { Icon: IconError,   color: "var(--error)",   bg: "var(--error-soft)",   label: "Critical" },
  warning: { Icon: IconWarning, color: "var(--warning)", bg: "var(--warning-soft)", label: "Warning" },
  info:    { Icon: IconInfo,    color: "var(--primary)", bg: "var(--primary-soft)", label: "Info" },
};

const AlertRow = ({ a, onAck }) => {
  const sev = SEVERITY[a.severity];
  const isAck = a.status === "ack";
  return (
    <tr style={{ borderBottom: "1px solid var(--border)", background: isAck ? "#F8FAFC" : "var(--surface)", transition: "background 120ms" }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "#F8FAFC"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = isAck ? "#F8FAFC" : "var(--surface)"; }}
    >
      <td style={{ padding: "12px 16px", whiteSpace: "nowrap" }}>
        <span className="mono" style={{ fontSize: 12, color: "var(--text-2)" }}>{a.time}</span>
      </td>
      <td style={{ padding: "12px 8px", whiteSpace: "nowrap" }}>
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 8px",
          borderRadius: 999, background: sev.bg, color: sev.color, fontSize: 11, fontWeight: 700,
        }}>
          <sev.Icon size={12} stroke={sev.color} />
          {sev.label}
        </span>
      </td>
      <td style={{ padding: "12px 8px", whiteSpace: "nowrap" }}>
        <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: "var(--text-1)" }}>{a.machine}</span>
      </td>
      <td style={{ padding: "12px 8px", color: "var(--text-1)", fontSize: 13 }}>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.35 }}>
          <span style={{ fontWeight: 500 }}>{a.message}</span>
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>{a.messageTh}</span>
        </div>
      </td>
      <td style={{ padding: "12px 16px", textAlign: "right", whiteSpace: "nowrap" }}>
        {isAck ? (
          <StatusPill status="ack" size="sm" />
        ) : (
          <button onClick={() => onAck(a.id)}
            style={{
              background: "var(--surface)", color: "var(--text-1)",
              border: "1px solid var(--border)", padding: "5px 10px",
              borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 5,
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#F3F4F6"; e.currentTarget.style.borderColor = "var(--border-strong)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "var(--surface)"; e.currentTarget.style.borderColor = "var(--border)"; }}
          >
            <IconCheck size={12} />
            Acknowledge
          </button>
        )}
      </td>
    </tr>
  );
};

const AlertsTable = ({ alerts, onAck, filter, onFilter }) => {
  const filtered = filter === "all" ? alerts : alerts.filter((a) => a.severity === filter);
  return (
    <div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: "#F8FAFC", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
            {["Time", "Severity", "Machine", "Message", ""].map((h, i) => (
              <th key={i} style={{
                padding: i === 0 ? "10px 16px" : i === 4 ? "10px 16px" : "10px 8px",
                fontSize: 11, fontWeight: 600, color: "var(--text-3)",
                textTransform: "uppercase", letterSpacing: 0.6, textAlign: i === 4 ? "right" : "left",
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 ? (
            <tr><td colSpan={5} style={{ padding: 24, textAlign: "center", color: "var(--text-2)", fontSize: 13 }}>No alerts match this filter.</td></tr>
          ) : filtered.map((a) => <AlertRow key={a.id} a={a} onAck={onAck} />)}
        </tbody>
      </table>
    </div>
  );
};

/* ----- Energy Donut Card ----- */

const ENERGY = [
  { label: "Line A", th: "สาย A", value: 312, color: "#2563EB" },
  { label: "Line B", th: "สาย B", value: 248, color: "#60A5FA" },
  { label: "Line C", th: "สาย C", value: 186, color: "#F59E0B" },
  { label: "Line D", th: "สาย D", value: 154, color: "#10B981" },
  { label: "Utilities", th: "ระบบสนับสนุน", value: 92, color: "#94A3B8" },
];

const EnergyCard = () => {
  const [hovered, setHovered] = React.useState(null);
  const total = ENERGY.reduce((a, b) => a + b.value, 0);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "center", paddingTop: 4 }}>
        <Donut data={ENERGY} hovered={hovered} onHover={setHovered} />
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {ENERGY.map((e, i) => {
          const pct = (e.value / total) * 100;
          const active = hovered === i;
          return (
            <li key={e.label}
              onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)}
              style={{
                display: "grid",
                gridTemplateColumns: "16px 1fr auto auto",
                alignItems: "center",
                gap: 10,
                padding: "6px 8px",
                borderRadius: 6,
                background: active ? "#F8FAFC" : "transparent",
                cursor: "pointer",
                transition: "background 120ms",
              }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, background: e.color, justifySelf: "center" }} />
              <span style={{ fontSize: 13, color: "var(--text-1)" }}>
                {e.label} <span style={{ color: "var(--text-3)", fontSize: 11 }}>· {e.th}</span>
              </span>
              <span className="num" style={{ fontSize: 12, color: "var(--text-2)", textAlign: "right" }}>{e.value} kWh</span>
              <span className="num" style={{ fontSize: 12, fontWeight: 600, color: "var(--text-1)", minWidth: 42, textAlign: "right" }}>{pct.toFixed(1)}%</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
};

Object.assign(window, {
  KPI_DEFS, KpiStrip, makeSparkData,
  MACHINES, MachineGrid,
  AlertsTable, SEVERITY,
  EnergyCard,
});
