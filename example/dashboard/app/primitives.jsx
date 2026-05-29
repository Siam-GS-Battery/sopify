/* Primitives: Card, StatusPill, Trend, Sparkline */

const Card = ({ title, titleTh, action, children, padding = 24, style = {}, contentStyle = {} }) => (
  <section style={{
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
    boxShadow: "var(--shadow-sm)",
    display: "flex",
    flexDirection: "column",
    ...style,
  }}>
    {(title || action) && (
      <header style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        padding: `20px ${padding}px 0`,
        flexWrap: "wrap",
      }}>
        <div style={{ minWidth: 0 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "var(--text-1)", letterSpacing: -0.1, lineHeight: 1.4, whiteSpace: "nowrap" }}>
            {title}
            {titleTh && <span style={{ color: "var(--text-2)", fontWeight: 500, marginLeft: 8 }}>/ {titleTh}</span>}
          </h3>
        </div>
        {action && <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>{action}</div>}
      </header>
    )}
    <div style={{ padding, ...contentStyle }}>{children}</div>
  </section>
);

const STATUS = {
  running:  { label: "Running",  th: "ทำงาน",     bg: "var(--success-soft)", color: "#047857", dot: "var(--success)" },
  idle:     { label: "Idle",     th: "ว่าง",       bg: "#F1F5F9",             color: "#475569", dot: "#94A3B8" },
  down:     { label: "Down",     th: "หยุด",       bg: "var(--warning-soft)", color: "#B45309", dot: "var(--warning)" },
  fault:    { label: "Fault",    th: "ขัดข้อง",     bg: "var(--error-soft)",   color: "#B91C1C", dot: "var(--error)" },
  ack:      { label: "Acknowledged", th: "รับทราบ", bg: "#F1F5F9",             color: "#475569", dot: "#94A3B8" },
  open:     { label: "Open",     th: "เปิด",       bg: "var(--error-soft)",   color: "#B91C1C", dot: "var(--error)" },
  investigating: { label: "Investigating", th: "กำลังตรวจสอบ", bg: "var(--warning-soft)", color: "#B45309", dot: "var(--warning)" },
};

const StatusPill = ({ status, size = "md", showTh = false }) => {
  const s = STATUS[status] || STATUS.idle;
  const padY = size === "sm" ? 2 : 4;
  const padX = size === "sm" ? 8 : 10;
  const fs = size === "sm" ? 11 : 12;
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: `${padY}px ${padX}px`,
      borderRadius: 999,
      background: s.bg,
      color: s.color,
      fontSize: fs,
      fontWeight: 600,
      lineHeight: 1.2,
      whiteSpace: "nowrap",
    }}>
      <IconDot size={6} color={s.dot} />
      {s.label}{showTh && s.th ? ` · ${s.th}` : ""}
    </span>
  );
};

const Trend = ({ value, unit = "%", direction }) => {
  // direction: "up" | "down" | "flat"
  // Color: up=good (success), down=bad (error), flat=muted. (You can pass invert if down is good.)
  const color = direction === "up" ? "var(--success)" : direction === "down" ? "var(--error)" : "var(--text-3)";
  const I = direction === "up" ? IconArrowUp : direction === "down" ? IconArrowDown : IconFlat;
  const symbol = direction === "up" ? "↑" : direction === "down" ? "↓" : "→";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color, fontSize: 13, fontWeight: 600 }}>
      <span style={{ fontFamily: "var(--mono)", lineHeight: 1, fontSize: 14 }}>{symbol}</span>
      <span className="num">{value}{unit}</span>
      <span style={{ color: "var(--text-3)", fontWeight: 500, marginLeft: 2 }}>vs. yesterday</span>
    </span>
  );
};

/* Sparkline: tiny inline SVG line. data = array of numbers. */
const Sparkline = ({ data, width = 140, height = 32, stroke = "var(--primary)", fill = "rgba(37,99,235,0.10)" }) => {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const pts = data.map((v, i) => [i * stepX, height - 2 - ((v - min) / span) * (height - 6)]);
  const linePath = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${width} ${height} L0 ${height} Z`;
  return (
    <svg width={width} height={height} style={{ display: "block" }} viewBox={`0 0 ${width} ${height}`}>
      <path d={areaPath} fill={fill} />
      <path d={linePath} fill="none" stroke={stroke} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

/* Reusable plain button */
const Button = ({ variant = "primary", size = "md", icon, children, ...rest }) => {
  const sizes = {
    sm: { padding: "6px 10px", fontSize: 12, h: 28 },
    md: { padding: "10px 16px", fontSize: 14, h: 38 },
  }[size];
  const variants = {
    primary:  { background: "var(--primary)", color: "#fff", border: "1px solid var(--primary)" },
    ghost:    { background: "transparent",     color: "var(--text-2)", border: "1px solid transparent" },
    outline:  { background: "var(--surface)",  color: "var(--text-1)", border: "1px solid var(--border)" },
  }[variant];
  return (
    <button
      {...rest}
      style={{
        ...sizes,
        ...variants,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontWeight: 600,
        borderRadius: "var(--radius-sm)",
        height: sizes.h,
        lineHeight: 1,
        transition: "background 120ms, border-color 120ms, color 120ms",
        ...(rest.style || {}),
      }}
      onMouseEnter={(e) => { if (variant === "primary") e.currentTarget.style.background = "var(--primary-hover)"; if (variant === "outline") e.currentTarget.style.background = "#F9FAFB"; if (variant === "ghost") e.currentTarget.style.background = "#F3F4F6"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = variants.background; }}
    >
      {icon}
      {children}
    </button>
  );
};

Object.assign(window, { Card, StatusPill, STATUS, Trend, Sparkline, Button });
