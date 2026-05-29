/* Stroke-style icons. 20x20 by default. */
const Icon = ({ d, size = 20, stroke = "currentColor", fill = "none", strokeWidth = 1.6, children, ...rest }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={stroke} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" {...rest}>
    {d ? <path d={d} /> : children}
  </svg>
);

const IconOverview = (p) => (
  <Icon {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </Icon>
);
const IconLines = (p) => (
  <Icon {...p}>
    <path d="M3 7h18" />
    <path d="M3 12h18" />
    <path d="M3 17h18" />
    <circle cx="7" cy="7" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="14" cy="12" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="10" cy="17" r="1.3" fill="currentColor" stroke="none" />
  </Icon>
);
const IconMachine = (p) => (
  <Icon {...p}>
    <rect x="3" y="8" width="13" height="11" rx="1.5" />
    <path d="M16 12h3l2 2v5h-5" />
    <path d="M6 12h3M6 15h5" />
  </Icon>
);
const IconAlerts = (p) => (
  <Icon {...p}>
    <path d="M12 3a6 6 0 0 0-6 6v3.5L4 16h16l-2-3.5V9a6 6 0 0 0-6-6Z" />
    <path d="M10 19a2 2 0 0 0 4 0" />
  </Icon>
);
const IconReports = (p) => (
  <Icon {...p}>
    <path d="M7 3h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
    <path d="M14 3v5h5" />
    <path d="M9 13h6M9 17h4" />
  </Icon>
);
const IconSettings = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1A2 2 0 1 1 4.4 17l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1A2 2 0 1 1 7 4.4l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1A2 2 0 1 1 19.6 7l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
  </Icon>
);
const IconBell = (p) => (
  <Icon {...p}>
    <path d="M6 9a6 6 0 0 1 12 0v4l1.5 3H4.5L6 13Z" />
    <path d="M10 19a2 2 0 0 0 4 0" />
  </Icon>
);
const IconSearch = (p) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="6" />
    <path d="m20 20-3.5-3.5" />
  </Icon>
);
const IconChevron = (p) => (
  <Icon {...p}>
    <path d="m6 9 6 6 6-6" />
  </Icon>
);
const IconCollapse = (p) => (
  <Icon {...p}>
    <path d="M4 5h16M4 12h10M4 19h16" />
    <path d="m20 9-3 3 3 3" />
  </Icon>
);
const IconCheck = (p) => (
  <Icon {...p}>
    <path d="m5 12 5 5 9-11" />
  </Icon>
);
const IconArrowUp = (p) => (
  <Icon {...p}>
    <path d="M7 14l5-5 5 5" />
  </Icon>
);
const IconArrowDown = (p) => (
  <Icon {...p}>
    <path d="M7 10l5 5 5-5" />
  </Icon>
);
const IconFlat = (p) => (
  <Icon {...p}>
    <path d="M5 12h14" />
  </Icon>
);
const IconWarning = (p) => (
  <Icon {...p}>
    <path d="M12 3 2 20h20L12 3Z" />
    <path d="M12 10v4" />
    <circle cx="12" cy="17" r="0.5" fill="currentColor" stroke="none" />
  </Icon>
);
const IconError = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9 9l6 6M15 9l-6 6" />
  </Icon>
);
const IconInfo = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5" />
    <circle cx="12" cy="8" r="0.5" fill="currentColor" stroke="none" />
  </Icon>
);
const IconDot = ({ size = 8, color = "currentColor" }) => (
  <span style={{ display: "inline-block", width: size, height: size, borderRadius: "50%", background: color }} />
);

Object.assign(window, {
  Icon, IconOverview, IconLines, IconMachine, IconAlerts, IconReports, IconSettings,
  IconBell, IconSearch, IconChevron, IconCollapse, IconCheck,
  IconArrowUp, IconArrowDown, IconFlat, IconWarning, IconError, IconInfo, IconDot
});
