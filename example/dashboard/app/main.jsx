/* App: composition + state */

const HOURS = ["07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00"];
const OUTPUT_DATA_INITIAL = [
  { label: "07:00", value: 1140 },
  { label: "08:00", value: 1195 },
  { label: "09:00", value: 1248 },
  { label: "10:00", value: 1262 },
  { label: "11:00", value: 1218 },
  { label: "12:00", value: 1158 },
  { label: "13:00", value: 1232 },
  { label: "14:00", value: 1276 },
];

const INITIAL_ALERTS = [
  { id: "a1", time: "14:08:42", severity: "error",   machine: "FILL-C-01", message: "Acid level sensor offline",       messageTh: "เซ็นเซอร์ระดับน้ำกรดขาดการเชื่อมต่อ", status: "open" },
  { id: "a2", time: "14:02:17", severity: "warning", machine: "FORMING-03", message: "Temperature exceeds threshold (74°C)", messageTh: "อุณหภูมิเกินค่าที่กำหนด (74°C)", status: "open" },
  { id: "a3", time: "13:47:55", severity: "warning", machine: "ASSY-B-01",  message: "Cycle time drift above 5%",         messageTh: "เวลารอบเครื่องเบี่ยงเบนเกิน 5%",       status: "open" },
  { id: "a4", time: "13:31:09", severity: "info",    machine: "PACK-E-01",  message: "Scheduled maintenance starting",    messageTh: "เริ่มการบำรุงรักษาตามกำหนด",          status: "open" },
  { id: "a5", time: "13:14:22", severity: "error",   machine: "LINE-A-02",  message: "Vibration anomaly detected",        messageTh: "ตรวจพบความสั่นสะเทือนผิดปกติ",       status: "ack" },
];

const App = () => {
  const [shift, setShift] = React.useState("day");
  const [collapsed, setCollapsed] = React.useState(false);
  const [active, setActive] = React.useState("overview");
  const [notifOpen, setNotifOpen] = React.useState(false);
  const [alerts, setAlerts] = React.useState(INITIAL_ALERTS);
  const [filter, setFilter] = React.useState("all");
  const [selectedMachine, setSelectedMachine] = React.useState("LINE-A-01");

  /* KPI live values: subtly tick around base */
  const [kpiValues, setKpiValues] = React.useState({ oee: 84.2, availability: 91.5, performance: 92.0, quality: 99.7 });
  const baseRef = React.useRef({ oee: 84.2, availability: 91.5, performance: 92.0, quality: 99.7 });
  React.useEffect(() => {
    const t = setInterval(() => {
      setKpiValues((prev) => {
        const next = {};
        for (const k of Object.keys(prev)) {
          const base = baseRef.current[k];
          const drift = (Math.random() - 0.5) * 0.6;
          const v = Math.max(base - 1.2, Math.min(base + 1.0, prev[k] + drift));
          next[k] = +v.toFixed(1);
        }
        return next;
      });
    }, 2500);
    return () => clearInterval(t);
  }, []);

  /* Sparkline data — recompute when shift changes (different seed) */
  const sparks = React.useMemo(() => {
    const seedBase = shift === "day" ? 13 : shift === "swing" ? 47 : 91;
    return {
      oee:          makeSparkData(seedBase + 1, 84.2, 1.6, 28),
      availability: makeSparkData(seedBase + 2, 91.5, 1.4, 28),
      performance:  makeSparkData(seedBase + 3, 92.0, 1.0, 28),
      quality:      makeSparkData(seedBase + 4, 99.7, 0.35, 28),
    };
  }, [shift]);

  /* Output chart data shifts a bit per shift */
  const outputData = React.useMemo(() => {
    if (shift === "day") return OUTPUT_DATA_INITIAL;
    if (shift === "swing") return OUTPUT_DATA_INITIAL.map((d, i) => ({
      ...d, label: ["15:00","16:00","17:00","18:00","19:00","20:00","21:00","22:00"][i],
      value: Math.round(d.value * 0.94 + (Math.sin(i) * 30)),
    }));
    return OUTPUT_DATA_INITIAL.map((d, i) => ({
      ...d, label: ["23:00","00:00","01:00","02:00","03:00","04:00","05:00","06:00"][i],
      value: Math.round(d.value * 0.82 + (Math.cos(i) * 40)),
    }));
  }, [shift]);

  /* Acknowledge */
  const ackAlert = (id) => setAlerts((prev) => prev.map((a) => a.id === id ? { ...a, status: "ack" } : a));

  /* Notifications derived from open critical/warning alerts */
  const notifications = React.useMemo(() => alerts
    .filter((a) => a.status !== "ack")
    .slice(0, 4)
    .map((a) => ({
      id: a.id, title: a.message, body: a.messageTh, machine: a.machine, time: a.time, severity: a.severity,
    })), [alerts]);

  const clearNotifs = () => setAlerts((prev) => prev.map((a) => ({ ...a, status: "ack" })));

  /* Filter chips */
  const counts = React.useMemo(() => ({
    all: alerts.length,
    error: alerts.filter((a) => a.severity === "error").length,
    warning: alerts.filter((a) => a.severity === "warning").length,
    info: alerts.filter((a) => a.severity === "info").length,
  }), [alerts]);

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)" }}>
      <Sidebar active={active} onSelect={setActive} collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopNav
          shift={shift} onShiftChange={setShift}
          notifOpen={notifOpen} onNotifToggle={() => setNotifOpen((v) => !v)}
          notifications={notifications} onNotifClear={clearNotifs}
        />

        <main style={{ padding: "24px 32px 40px", display: "flex", flexDirection: "column", gap: 20, maxWidth: 1440, width: "100%", margin: "0 auto" }}>
          {/* Sub-header strip */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "4px 10px", borderRadius: 999, background: "var(--success-soft)", color: "#047857",
                fontSize: 12, fontWeight: 600,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--success)", animation: "pulse 1.6s ease-in-out infinite" }} />
                Live
              </span>
              <span style={{ fontSize: 12, color: "var(--text-2)" }} className="mono">Updated just now · auto-refresh 5s</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button style={chipBtnStyle()}>Today</button>
              <button style={chipBtnStyle()}>7 days</button>
              <button style={chipBtnStyle()}>30 days</button>
              <button style={{ ...chipBtnStyle(), background: "var(--primary)", color: "#fff", borderColor: "var(--primary)" }}>Custom</button>
              <button style={{ ...chipBtnStyle(), borderColor: "var(--border)" }}>
                Export <span style={{ marginLeft: 4, color: "var(--text-3)" }}>↓</span>
              </button>
            </div>
          </div>

          {/* Row 1 — KPI strip */}
          <KpiStrip values={kpiValues} sparks={sparks} />

          {/* Row 2 — Output chart + Machine status */}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: 16 }}>
            <Card
              title="Output Rate"
              titleTh="อัตราการผลิต"
              action={
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                    <LegendDot color="var(--primary)" label="Units/hour" />
                    <LegendDot color="var(--success)" label="Target" dashed />
                  </div>
                  <div style={{ width: 1, height: 16, background: "var(--border)" }} />
                  <SegSwitcher options={[{ k: "h", l: "Hourly" }, { k: "s", l: "Shift" }, { k: "d", l: "Day" }]} value="h" />
                </div>
              }
              contentStyle={{ paddingTop: 8 }}
            >
              <OutputChart data={outputData} target={1200} height={260} />
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                <StatBlock label="Shift total" valueClass="num" value="9,729" suffix="units" />
                <StatBlock label="Avg / hour"  valueClass="num" value="1,216"  suffix="units" />
                <StatBlock label="Best hour"   valueClass="num" value="1,276"  suffix="units" tone="success" />
                <StatBlock label="vs Target"   valueClass="num" value="+1.3"   suffix="%"     tone="success" />
              </div>
            </Card>

            <Card
              title="Machine Status"
              titleTh="สถานะเครื่องจักร"
              action={
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="mono" style={{ fontSize: 12, color: "var(--text-2)" }}>{MACHINES.filter(m => m.status === "running").length}/{MACHINES.length} running</span>
                </div>
              }
              contentStyle={{ paddingTop: 12 }}
            >
              <MachineGrid machines={MACHINES} selected={selectedMachine} onSelect={setSelectedMachine} />
            </Card>
          </div>

          {/* Row 3 — Alerts + Energy */}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: 16 }}>
            <Card
              title="Active Alerts"
              titleTh="แจ้งเตือนที่ใช้งานอยู่"
              padding={0}
              action={
                <div style={{ display: "flex", gap: 6, paddingRight: 24, paddingBottom: 0 }}>
                  {[
                    { k: "all",     l: "All",      n: counts.all,     color: "var(--text-1)" },
                    { k: "error",   l: "Critical", n: counts.error,   color: "var(--error)" },
                    { k: "warning", l: "Warning",  n: counts.warning, color: "var(--warning)" },
                    { k: "info",    l: "Info",     n: counts.info,    color: "var(--primary)" },
                  ].map((c) => {
                    const isActive = filter === c.k;
                    return (
                      <button key={c.k} onClick={() => setFilter(c.k)} style={{
                        display: "inline-flex", alignItems: "center", gap: 6,
                        padding: "5px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                        border: `1px solid ${isActive ? "var(--primary)" : "var(--border)"}`,
                        background: isActive ? "var(--primary-soft)" : "var(--surface)",
                        color: isActive ? "var(--primary)" : "var(--text-2)",
                        cursor: "pointer",
                      }}>
                        {c.l}
                        <span className="mono" style={{
                          padding: "1px 6px", borderRadius: 999,
                          background: isActive ? "var(--primary)" : "#F1F5F9",
                          color: isActive ? "#fff" : "var(--text-2)", fontSize: 10, fontWeight: 700,
                        }}>{c.n}</span>
                      </button>
                    );
                  })}
                </div>
              }
              contentStyle={{ padding: 0 }}
            >
              <AlertsTable alerts={alerts} onAck={ackAlert} filter={filter} />
            </Card>

            <Card
              title="Energy Consumption"
              titleTh="การใช้พลังงาน"
              action={<span className="mono" style={{ fontSize: 12, color: "var(--text-2)" }}>Shift to date</span>}
            >
              <EnergyCard />
            </Card>
          </div>

          {/* Footer */}
          <footer style={{ display: "flex", justifyContent: "space-between", padding: "8px 4px", color: "var(--text-3)", fontSize: 11 }}>
            <span>© 2026 GS Battery (Thailand) Co., Ltd.</span>
            <span className="mono">v 2.4.1 · sync OK · {new Date().toLocaleDateString("en-GB")}</span>
          </footer>
        </main>
      </div>

      {/* Global keyframes */}
      <style>{`
        @keyframes pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.15); opacity: 0.7; }
        }
      `}</style>
    </div>
  );
};

/* small inline helpers */
const chipBtnStyle = () => ({
  display: "inline-flex", alignItems: "center", padding: "6px 12px", height: 32,
  background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8,
  color: "var(--text-2)", fontSize: 12, fontWeight: 600, cursor: "pointer",
});

const LegendDot = ({ color, label, dashed }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-2)" }}>
    {dashed ? (
      <svg width="18" height="3"><line x1="0" y1="1.5" x2="18" y2="1.5" stroke={color} strokeWidth="2" strokeDasharray="3 3" /></svg>
    ) : (
      <span style={{ width: 10, height: 3, background: color, borderRadius: 2 }} />
    )}
    {label}
  </span>
);

const SegSwitcher = ({ options, value }) => {
  const [v, setV] = React.useState(value);
  return (
    <div style={{ display: "inline-flex", background: "#F1F5F9", borderRadius: 8, padding: 3 }}>
      {options.map((o) => (
        <button key={o.k} onClick={() => setV(o.k)} style={{
          padding: "4px 10px", borderRadius: 6, border: 0, fontSize: 12, fontWeight: 600,
          background: v === o.k ? "var(--surface)" : "transparent",
          color: v === o.k ? "var(--text-1)" : "var(--text-2)",
          boxShadow: v === o.k ? "0 1px 2px rgba(15,23,42,0.08)" : "none",
          cursor: "pointer",
        }}>{o.l}</button>
      ))}
    </div>
  );
};

const StatBlock = ({ label, value, suffix, tone }) => (
  <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
    <span style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: 0.4, textTransform: "uppercase", fontWeight: 600, lineHeight: 1.3, whiteSpace: "nowrap" }}>{label}</span>
    <span style={{ marginTop: 4, display: "flex", alignItems: "baseline", gap: 4 }}>
      <span className="num" style={{ fontSize: 18, fontWeight: 700, color: tone === "success" ? "var(--success)" : "var(--text-1)", lineHeight: 1.2 }}>{value}</span>
      <span style={{ fontSize: 12, color: "var(--text-2)" }}>{suffix}</span>
    </span>
  </div>
);

/* Mount */
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
