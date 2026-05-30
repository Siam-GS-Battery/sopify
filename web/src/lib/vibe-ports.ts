/**
 * Fixed dev-server ports for the two right-pane surfaces.
 *
 * Per spec/VIBE_CODE_PANEL_SPEC.md §4 each surface filters its iframe to a
 * single hardcoded port. Other 517x ports remain published by the sandbox
 * so ad-hoc dev servers still work; the right-pane filter just locks down
 * which one renders in the preview.
 */
export const VIBE_DEV_PORT = 5174;
export const PANEL_DEV_PORT = 5173;

export interface DevServerLike {
  port: number;
  url: string;
}

/**
 * Find the matching dev server entry by port, or return null. Callers use
 * the resulting `url` as the iframe `src`; null → no preview shows.
 */
export function pickDevServerForPort<T extends DevServerLike>(
  servers: readonly T[],
  port: number,
): T | null {
  for (const s of servers) {
    if (s.port === port) return s;
  }
  return null;
}
