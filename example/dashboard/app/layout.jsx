/* Layout: Sidebar + TopNav */

const NAV_ITEMS = [
  { key: "overview",    label: "Overview",        th: "ภาพรวม",          Icon: IconOverview },
  { key: "lines",       label: "Production Lines", th: "สายการผลิต",       Icon: IconLines },
  { key: "machines",    label: "Machines",        th: "เครื่องจักร",        Icon: IconMachine },
  { key: "alerts",      label: "Alerts",          th: "แจ้งเตือน",         Icon: IconAlerts, badge: 3 },
  { key: "reports",     label: "Reports",         th: "รายงาน",           Icon: IconReports },
  { key: "settings",    label: "Settings",        th: "ตั้งค่า",            Icon: IconSettings },
];

const Sidebar = ({ active, onSelect, collapsed, onToggle }) => {
  const W = collapsed ? 72 : 240;
  return (
    <aside style={{
      width: W,
      flex: `0 0 ${W}px`,
      height: "100vh",
      position: "sticky",
      top: 0,
      background: "var(--surface)",
      borderRight: "1px solid var(--border)",
      display: "flex",
      flexDirection: "column",
      transition: "width 200ms ease",
      overflow: "hidden",
    }}>
      {/* Logo zone */}
      <div style={{
        height: 64,
        flex: "0 0 64px",
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: collapsed ? "0" : "0 16px",
        justifyContent: collapsed ? "center" : "flex-start",
        borderBottom: "1px solid var(--border)",
      }}>
        <img src="assets/gs-logo.png" alt="GS Battery" style={{ height: 28, width: "auto", display: "block", flex: "0 0 auto" }} />
        {!collapsed && (
          <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
            <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.4, color: "var(--text-2)", lineHeight: 1.3, textTransform: "uppercase", whiteSpace: "nowrap" }}>Operations</span>
            <span style={{ fontSize: 10, color: "var(--text-3)", fontWeight: 500, lineHeight: 1.3, whiteSpace: "nowrap" }} className="mono">v 2.4.1</span>
          </div>
        )}
      </div>

      {/* Plant context */}
      {!collapsed && (
        <div style={{ padding: "16px 16px 8px" }}>
          <div style={{ fontSize: 11, color: "var(--text-3)", fontWeight: 600, letterSpacing: 0.6, textTransform: "uppercase" }}>Plant</div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 6, padding: "10px 12px", background: "#F8FAFC", borderRadius: 8, border: "1px solid var(--border)", gap: 8 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
              <span style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.3, whiteSpace: "nowrap" }}>Samut Prakan</span>
              <span style={{ fontSize: 11, color: "var(--text-2)", lineHeight: 1.4, whiteSpace: "nowrap" }}>สมุทรปราการ · TH</span>
            </div>
            <IconChevron size={16} stroke="var(--text-3)" />
          </div>
        </div>
      )}

      {/* Nav */}
      <nav style={{ flex: 1, padding: collapsed ? "12px 8px" : "12px 12px", display: "flex", flexDirection: "column", gap: 2 }}>
        {NAV_ITEMS.map(({ key, label, th, Icon: I, badge }) => {
          const isActive = key === active;
          return (
            <button key={key} onClick={() => onSelect(key)}
              title={collapsed ? label : undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: collapsed ? "10px" : "10px 12px",
                justifyContent: collapsed ? "center" : "flex-start",
                border: "1px solid transparent",
                background: isActive ? "var(--primary-soft)" : "transparent",
                color: isActive ? "var(--primary)" : "var(--text-2)",
                borderRadius: 8,
                fontWeight: isActive ? 600 : 500,
                fontSize: 14,
                textAlign: "left",
                position: "relative",
                transition: "background 120ms, color 120ms",
              }}
              onMouseEnter={(e) => { if (!isActive) { e.currentTarget.style.background = "#F3F4F6"; e.currentTarget.style.color = "var(--text-1)"; } }}
              onMouseLeave={(e) => { if (!isActive) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-2)"; } }}
            >
              <I size={18} />
              {!collapsed && (
                <span style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                  <span style={{ lineHeight: 1.25, whiteSpace: "nowrap" }}>{label}</span>
                  <span style={{ fontSize: 11, fontWeight: 400, lineHeight: 1.4, color: isActive ? "var(--primary)" : "var(--text-3)", opacity: 0.85, whiteSpace: "nowrap" }}>{th}</span>
                </span>
              )}
              {badge != null && (
                <span style={{
                  background: "var(--error)",
                  color: "#fff",
                  fontSize: 11,
                  fontWeight: 700,
                  lineHeight: 1,
                  padding: "3px 6px",
                  borderRadius: 999,
                  minWidth: 18,
                  textAlign: "center",
                  position: collapsed ? "absolute" : "static",
                  top: collapsed ? 6 : undefined,
                  right: collapsed ? 6 : undefined,
                }}>{badge}</span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Footer: collapse + system status */}
      <div style={{ padding: collapsed ? 8 : 12, borderTop: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 10 }}>
        {!collapsed && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", background: "#F8FAFC", border: "1px solid var(--border)", borderRadius: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--success)", boxShadow: "0 0 0 3px rgba(16,185,129,0.18)", flex: "0 0 8px" }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
              <span style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.3, whiteSpace: "nowrap" }}>SCADA online</span>
              <span style={{ fontSize: 11, color: "var(--text-2)", lineHeight: 1.3, whiteSpace: "nowrap" }} className="mono">latency 42ms</span>
            </div>
          </div>
        )}
        <button onClick={onToggle} title={collapsed ? "Expand" : "Collapse"}
          style={{
            display: "flex", alignItems: "center", gap: 10, padding: collapsed ? "10px" : "10px 12px",
            justifyContent: collapsed ? "center" : "flex-start",
            border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text-2)",
            borderRadius: 8, fontWeight: 500, fontSize: 13,
          }}>
          <IconCollapse size={16} style={{ transform: collapsed ? "scaleX(-1)" : "none" }} />
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
};

const SHIFTS = [
  { key: "day",   label: "Day Shift",   th: "กะกลางวัน",   hours: "06:00–14:00" },
  { key: "swing", label: "Swing Shift", th: "กะบ่าย",       hours: "14:00–22:00" },
  { key: "night", label: "Night Shift", th: "กะกลางคืน",   hours: "22:00–06:00" },
];

const TopNav = ({ shift, onShiftChange, notifOpen, onNotifToggle, notifications, onNotifClear }) => {
  const [shiftOpen, setShiftOpen] = React.useState(false);
  const current = SHIFTS.find((s) => s.key === shift) || SHIFTS[0];
  const [now, setNow] = React.useState(new Date());
  React.useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const timeStr = now.toTimeString().slice(0, 8);

  return (
    <header style={{
      height: 64,
      flex: "0 0 64px",
      background: "var(--surface)",
      borderBottom: "1px solid var(--border)",
      boxShadow: "var(--shadow-nav)",
      display: "flex",
      alignItems: "center",
      padding: "0 24px 0 24px",
      gap: 24,
      position: "sticky",
      top: 0,
      zIndex: 30,
    }}>
      {/* Title */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2, flex: "0 0 auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-3)", fontWeight: 500, lineHeight: 1.3 }}>
          <span>Operations</span><span>›</span><span>Dashboard</span>
        </div>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "var(--text-1)", letterSpacing: -0.2, lineHeight: 1.3, whiteSpace: "nowrap" }}>
          Production Overview <span style={{ color: "var(--text-2)", fontWeight: 500, fontSize: 17 }}>/ ภาพรวมการผลิต</span>
        </h1>
      </div>

      {/* Search (center-ish, decorative) */}
      <div style={{ flex: 1, display: "flex", justifyContent: "center", minWidth: 0 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          width: 320, maxWidth: "100%", height: 36, padding: "0 12px",
          background: "#F1F5F9", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-3)",
        }}>
          <IconSearch size={16} stroke="var(--text-3)" />
          <input placeholder="Search machines, alerts, reports…" style={{
            flex: 1, border: 0, outline: "none", background: "transparent", fontSize: 13, color: "var(--text-1)", fontFamily: "var(--sans)",
          }} />
          <span className="mono" style={{ fontSize: 11, padding: "2px 6px", border: "1px solid var(--border)", borderRadius: 4, background: "var(--surface)", color: "var(--text-3)" }}>⌘K</span>
        </div>
      </div>

      {/* Clock */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2, textAlign: "right", flex: "0 0 auto" }}>
        <span className="mono" style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.2 }}>{timeStr}</span>
        <span style={{ fontSize: 11, color: "var(--text-2)", lineHeight: 1.3 }}>Local · ICT</span>
      </div>

      {/* Shift selector */}
      <div style={{ position: "relative" }}>
        <button onClick={() => setShiftOpen((v) => !v)} style={{
          display: "flex", alignItems: "center", gap: 10, padding: "0 12px", height: 44,
          background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-1)", fontWeight: 600, fontSize: 13,
        }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--primary)", flex: "0 0 8px" }} />
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
            <span style={{ lineHeight: 1.2, whiteSpace: "nowrap" }}>{current.label}</span>
            <span className="mono" style={{ fontSize: 11, color: "var(--text-2)", fontWeight: 500, lineHeight: 1.2, whiteSpace: "nowrap" }}>{current.hours}</span>
          </span>
          <IconChevron size={16} stroke="var(--text-3)" style={{ transform: shiftOpen ? "rotate(180deg)" : "none", transition: "transform 120ms" }} />
        </button>
        {shiftOpen && (
          <>
            <div onClick={() => setShiftOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
            <div style={{
              position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 50,
              minWidth: 240, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, boxShadow: "0 10px 30px rgba(15,23,42,0.10)", padding: 4,
            }}>
              {SHIFTS.map((s) => (
                <button key={s.key} onClick={() => { onShiftChange(s.key); setShiftOpen(false); }}
                  style={{
                    width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "10px 12px",
                    border: 0, background: s.key === shift ? "var(--primary-soft)" : "transparent",
                    color: s.key === shift ? "var(--primary)" : "var(--text-1)", borderRadius: 6, textAlign: "left", fontWeight: 500,
                  }}
                  onMouseEnter={(e) => { if (s.key !== shift) e.currentTarget.style.background = "#F3F4F6"; }}
                  onMouseLeave={(e) => { if (s.key !== shift) e.currentTarget.style.background = "transparent"; }}
                >
                  <span style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                    <span style={{ fontSize: 13, lineHeight: 1.3 }}>{s.label} <span style={{ color: "var(--text-2)", fontWeight: 400 }}>· {s.th}</span></span>
                    <span className="mono" style={{ fontSize: 11, color: "var(--text-3)", lineHeight: 1.3 }}>{s.hours}</span>
                  </span>
                  {s.key === shift && <IconCheck size={16} stroke="var(--primary)" />}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Notification bell */}
      <div style={{ position: "relative" }}>
        <button onClick={onNotifToggle} style={{
          width: 38, height: 38, display: "inline-flex", alignItems: "center", justifyContent: "center",
          background: notifOpen ? "#F3F4F6" : "transparent", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-1)", position: "relative",
        }}>
          <IconBell size={18} />
          {notifications.length > 0 && (
            <span style={{
              position: "absolute", top: -4, right: -4, minWidth: 18, height: 18,
              background: "var(--error)", color: "#fff", fontSize: 11, fontWeight: 700, lineHeight: "18px",
              borderRadius: 999, padding: "0 5px", border: "2px solid var(--surface)", textAlign: "center",
            }}>{notifications.length}</span>
          )}
        </button>
        {notifOpen && (
          <>
            <div onClick={onNotifToggle} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
            <div style={{
              position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 50,
              width: 360, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12,
              boxShadow: "0 20px 40px rgba(15,23,42,0.12)", overflow: "hidden",
            }}>
              <div style={{ padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.3 }}>Notifications</span>
                  <span style={{ fontSize: 11, color: "var(--text-2)", lineHeight: 1.3 }}>{notifications.length} unread</span>
                </div>
                <button onClick={onNotifClear} style={{ background: "transparent", border: 0, color: "var(--primary)", fontSize: 12, fontWeight: 600 }}>Mark all read</button>
              </div>
              <div style={{ maxHeight: 360, overflowY: "auto" }}>
                {notifications.length === 0 ? (
                  <div style={{ padding: 24, textAlign: "center", color: "var(--text-2)", fontSize: 13 }}>You're all caught up.</div>
                ) : notifications.map((n) => (
                  <div key={n.id} style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", gap: 12 }}>
                    <span style={{
                      width: 28, height: 28, borderRadius: 8, flex: "0 0 28px",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: n.severity === "error" ? "var(--error-soft)" : n.severity === "warning" ? "var(--warning-soft)" : "var(--primary-soft)",
                      color: n.severity === "error" ? "var(--error)" : n.severity === "warning" ? "var(--warning)" : "var(--primary)",
                    }}>
                      {n.severity === "error" ? <IconError size={16} /> : n.severity === "warning" ? <IconWarning size={16} /> : <IconInfo size={16} />}
                    </span>
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)", lineHeight: 1.35 }}>{n.title}</span>
                      <span style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.45 }}>{n.body}</span>
                      <span className="mono" style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2, lineHeight: 1.3 }}>{n.machine} · {n.time}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {/* User */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, paddingLeft: 12, borderLeft: "1px solid var(--border)", height: 44 }}>
        <div style={{
          width: 34, height: 34, borderRadius: "50%", background: "linear-gradient(135deg,#1D4ED8,#2563EB)",
          color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 13, flex: "0 0 34px",
        }}>NP</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.25, whiteSpace: "nowrap" }}>Niran Pongsri</span>
          <span style={{ fontSize: 11, color: "var(--text-2)", lineHeight: 1.3, whiteSpace: "nowrap" }}>Production Supervisor</span>
        </div>
      </div>
    </header>
  );
};

Object.assign(window, { Sidebar, TopNav, NAV_ITEMS, SHIFTS });
