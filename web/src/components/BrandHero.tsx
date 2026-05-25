import { useMemo } from "react";

// Pixel rhino mascot — colored block art rendered as inline-styled spans.
// Each segment is [fgColor, text, bgColor?]. Half-block characters ▀/▄
// encode two vertical pixels via fg (top half) + bg (bottom half), so the
// mascot fits in 7 rows × 14 cols instead of the original 14 × 28.
type Segment = [string, string, string?];
type Row = Segment[];

const PIXEL_RHINO: Row[] = [
  [
    ["", " "],
    ["#164E63", "▄"],
    ["#164E63", "▀▀", "#22D3EE"],
    ["#164E63", "▄"],
    ["", "    "],
    ["#164E63", "▄"],
    ["#164E63", "▀▀", "#22D3EE"],
    ["#164E63", "▄"],
    ["", " "],
  ],
  [
    ["#164E63", "█"],
    ["#22D3EE", "▀", "#67E8F9"],
    ["#67E8F9", "██"],
    ["#22D3EE", "▀", "#67E8F9"],
    ["#164E63", "▀▀▀▀", "#67E8F9"],
    ["#22D3EE", "▀", "#67E8F9"],
    ["#67E8F9", "██"],
    ["#22D3EE", "▀", "#67E8F9"],
    ["#164E63", "█"],
  ],
  [
    ["#164E63", "█"],
    ["#67E8F9", "████"],
    ["#67E8F9", "▀", "#0891B2"],
    ["#0891B2", "██"],
    ["#67E8F9", "▀", "#0891B2"],
    ["#67E8F9", "████"],
    ["#164E63", "█"],
  ],
  [
    ["#164E63", "█"],
    ["#67E8F9", "██"],
    ["#67E8F9", "▀", "#164E63"],
    ["#0891B2", "▀▀▀▀▀▀", "#67E8F9"],
    ["#67E8F9", "▀", "#164E63"],
    ["#67E8F9", "██"],
    ["#164E63", "█"],
  ],
  [
    ["#164E63", "█"],
    ["#67E8F9", "█"],
    ["#67E8F9", "▀▀", "#F9A8D4"],
    ["#67E8F9", "██████"],
    ["#67E8F9", "▀▀", "#F9A8D4"],
    ["#67E8F9", "█"],
    ["#164E63", "█"],
  ],
  [
    ["#164E63", "█"],
    ["#67E8F9", "▀", "#22D3EE"],
    ["#F9A8D4", "▀▀", "#67E8F9"],
    ["#67E8F9", "▀", "#22D3EE"],
    ["#67E8F9", "████"],
    ["#67E8F9", "▀", "#22D3EE"],
    ["#F9A8D4", "▀▀", "#67E8F9"],
    ["#67E8F9", "▀", "#22D3EE"],
    ["#164E63", "█"],
  ],
  [
    ["", " "],
    ["#164E63", "▀██▀"],
    ["", "    "],
    ["#164E63", "▀██▀"],
    ["", " "],
  ],
];

const HERMES_WORDMARK_LINES: { color: string; bold?: boolean; text: string }[] = [
  { color: "#67E8F9", bold: true, text: "      ___           ___           ___                 " },
  { color: "#67E8F9", bold: true, text: "     /\\  \\         /\\  \\         /\\  \\          ___   " },
  { color: "#22D3EE", bold: true, text: "    /::\\  \\       /::\\  \\       /::\\  \\        /\\  \\  " },
  { color: "#22D3EE", bold: true, text: "   /:/\\ \\  \\     /:/\\:\\  \\     /:/\\:\\  \\       \\:\\  \\ " },
  { color: "#06B6D4", bold: true, text: "  _\\:\\~\\ \\  \\   /:/  \\:\\  \\   /::\\~\\:\\  \\      /::\\__\\" },
  { color: "#06B6D4", bold: true, text: " /\\ \\:\\ \\ \\__\\ /:/__/ \\:\\__\\ /:/\\:\\ \\:\\__\\  __/:/\\/__/" },
  { color: "#0891B2", bold: true, text: " \\:\\ \\:\\ \\/__/ \\:\\  \\ /:/  / \\/__\\:\\/:/  / /\\/:/  /   " },
  { color: "#0891B2", bold: true, text: "  \\:\\ \\:\\__\\    \\:\\  /:/  /       \\::/  /  \\::/__/    " },
  { color: "#0E7490", bold: true, text: "   \\:\\/:/  /     \\:\\/:/  /         \\/__/    \\:\\__\\    " },
  { color: "#0E7490", bold: true, text: "    \\::/  /       \\::/  /                    \\/__/    " },
  { color: "#155E75", bold: true, text: "     \\/__/         \\/__/                              " },
  { color: "#67E8F9", bold: true, text: "      ___           ___     " },
  { color: "#22D3EE", bold: true, text: "     /\\  \\         |\\__\\    " },
  { color: "#22D3EE", bold: true, text: "    /::\\  \\        |:|  |   " },
  { color: "#06B6D4", bold: true, text: "   /:/\\:\\  \\       |:|  |   " },
  { color: "#06B6D4", bold: true, text: "  /::\\~\\:\\  \\      |:|__|__ " },
  { color: "#0891B2", bold: true, text: " /:/\\:\\ \\:\\__\\     /::::\\__\\" },
  { color: "#0891B2", bold: true, text: " \\/__\\:\\ \\/__/    /:/~~/~   " },
  { color: "#0E7490", bold: true, text: "      \\:\\__\\     /:/  /     " },
  { color: "#155E75", bold: true, text: "       \\/__/     \\/__/      " },
];

export interface PixelRhinoProps {
  /** Font-size in CSS units. Defaults to 0.5rem so the mascot fits compactly. */
  size?: string;
  className?: string;
  ariaLabel?: string;
}

export function PixelRhino({
  size = "0.5rem",
  className,
  ariaLabel = "Hermes pixel rhino mascot",
}: PixelRhinoProps) {
  const rows = useMemo(() => PIXEL_RHINO, []);

  return (
    <pre
      aria-label={ariaLabel}
      role="img"
      className={className}
      style={{
        fontSize: size,
        lineHeight: 1,
        fontFamily:
          "ui-monospace, 'SF Mono', Menlo, Monaco, 'Cascadia Mono', Consolas, monospace",
        margin: 0,
        userSelect: "none",
        whiteSpace: "pre",
      }}
    >
      {rows.map((row, i) => (
        <div key={i}>
          {row.map(([color, text, bg], j) => (
            <span key={j} style={{ backgroundColor: bg, color }}>
              {text}
            </span>
          ))}
        </div>
      ))}
    </pre>
  );
}

export interface HermesWordmarkProps {
  size?: string;
  className?: string;
  ariaLabel?: string;
}

export function HermesWordmark({
  size = "0.5rem",
  className,
  ariaLabel = "Hermes Agent wordmark",
}: HermesWordmarkProps) {
  return (
    <pre
      aria-label={ariaLabel}
      role="img"
      className={className}
      style={{
        fontSize: size,
        lineHeight: 1,
        fontFamily:
          "ui-monospace, 'SF Mono', Menlo, Monaco, 'Cascadia Mono', Consolas, monospace",
        margin: 0,
        userSelect: "none",
        whiteSpace: "pre",
      }}
    >
      {HERMES_WORDMARK_LINES.map((line, i) => (
        <div
          key={i}
          style={{ color: line.color, fontWeight: line.bold ? 700 : 400 }}
        >
          {line.text}
        </div>
      ))}
    </pre>
  );
}

export interface BrandHeroProps {
  /** Optional tagline below the mascot/wordmark. */
  tagline?: string;
  /** Show the wordmark beside the mascot when the container is wide enough. */
  showWordmark?: boolean;
  className?: string;
}

export function BrandHero({
  tagline,
  showWordmark = true,
  className,
}: BrandHeroProps) {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "0.75rem",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "center",
          gap: "1.25rem",
        }}
      >
        <PixelRhino size="0.6rem" />
        {showWordmark && <HermesWordmark size="0.5rem" />}
      </div>
      {tagline && (
        <p
          style={{
            color: "#0E7490",
            fontSize: "0.875rem",
            margin: 0,
            textAlign: "center",
          }}
        >
          {tagline}
        </p>
      )}
    </div>
  );
}
