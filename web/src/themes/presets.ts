import type { DashboardTheme, ThemeTypography, ThemeLayout } from "./types";

/**
 * Sopify is the only dashboard theme — users cannot switch.
 */

const SOPIFY_TYPOGRAPHY: ThemeTypography = {
  fontSans:
    'Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
  fontMono:
    '"SF Mono", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace',
  baseSize: "13px",
  lineHeight: "1.5",
  letterSpacing: "0",
};

const SOPIFY_LAYOUT: ThemeLayout = {
  radius: "0.5rem",
  density: "comfortable",
};

export const sopifyTheme: DashboardTheme = {
  name: "sopify",
  label: "Sopify",
  description: "Clean light dashboard — blue primary, Roboto, Rhino-style tokens",
  palette: {
    background: { hex: "#F8FAFC", alpha: 1 },
    midground:  { hex: "#03061E", alpha: 1 },
    foreground: { hex: "#FFFFFF", alpha: 0 },
    warmGlow: "rgba(29, 99, 237, 0.18)",
    noiseOpacity: 0,
  },
  typography: SOPIFY_TYPOGRAPHY,
  layout: SOPIFY_LAYOUT,
};

export const defaultTheme: DashboardTheme = sopifyTheme;

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  sopify: sopifyTheme,
};
