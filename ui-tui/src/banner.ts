import type { ThemeColors } from './theme.js'

const RICH_RE = /\[(?:bold\s+)?(?:dim\s+)?(#(?:[0-9a-fA-F]{3,8}))(?:\s+on\s+(#(?:[0-9a-fA-F]{3,8})))?\]([\s\S]*?)\[\/\]/g

// [fg, text, bg?] — bg only set on half-block cells where two vertical
// pixels need different colors (rendered as Text foreground+backgroundColor).
export type Segment = [string, string, string?]
export type Row = Segment[]

export function parseRichMarkup(markup: string): Row[] {
  const rows: Row[] = []

  for (const raw of markup.split('\n')) {
    const line = raw.trimEnd()

    if (!line) {
      rows.push([['', ' ']])

      continue
    }

    const matches = [...line.matchAll(RICH_RE)]

    if (!matches.length) {
      rows.push([['', line]])

      continue
    }

    const row: Row = []
    let cursor = 0

    for (const m of matches) {
      const before = line.slice(cursor, m.index)

      if (before) {
        row.push(['', before])
      }

      row.push(m[2] ? [m[1]!, m[3]!, m[2]] : [m[1]!, m[3]!])
      cursor = m.index! + m[0].length
    }

    if (cursor < line.length) {
      row.push(['', line.slice(cursor)])
    }

    rows.push(row)
  }

  return rows
}

const HERMES_TEXT_LOGO = `[bold #67E8F9]      ___           ___           ___                 [/]
[bold #67E8F9]     /\\  \\         /\\  \\         /\\  \\          ___   [/]
[bold #22D3EE]    /::\\  \\       /::\\  \\       /::\\  \\        /\\  \\  [/]
[bold #22D3EE]   /:/\\ \\  \\     /:/\\:\\  \\     /:/\\:\\  \\       \\:\\  \\ [/]
[bold #06B6D4]  _\\:\\~\\ \\  \\   /:/  \\:\\  \\   /::\\~\\:\\  \\      /::\\__\\[/]
[bold #06B6D4] /\\ \\:\\ \\ \\__\\ /:/__/ \\:\\__\\ /:/\\:\\ \\:\\__\\  __/:/\\/__/[/]
[bold #0891B2] \\:\\ \\:\\ \\/__/ \\:\\  \\ /:/  / \\/__\\:\\/:/  / /\\/:/  /   [/]
[bold #0891B2]  \\:\\ \\:\\__\\    \\:\\  /:/  /       \\::/  /  \\::/__/    [/]
[bold #0E7490]   \\:\\/:/  /     \\:\\/:/  /         \\/__/    \\:\\__\\    [/]
[bold #0E7490]    \\::/  /       \\::/  /                    \\/__/    [/]
[bold #155E75]     \\/__/         \\/__/                              [/]
[bold #67E8F9]      ___           ___     [/]
[bold #22D3EE]     /\\  \\         |\\__\\    [/]
[bold #22D3EE]    /::\\  \\        |:|  |   [/]
[bold #06B6D4]   /:/\\:\\  \\       |:|  |   [/]
[bold #06B6D4]  /::\\~\\:\\  \\      |:|__|__ [/]
[bold #0891B2] /:/\\:\\ \\:\\__\\     /::::\\__\\[/]
[bold #0891B2] \\/__\\:\\ \\/__/    /:/~~/~   [/]
[bold #0E7490]      \\:\\__\\     /:/  /     [/]
[bold #155E75]       \\/__/     \\/__/      [/]`

// Half-block compressed (7 rows × 14 cols, was 14×28). Each ▀/▄ encodes two
// vertical pixels via foreground (top) + background (bottom).
const PIXEL_RHINO = ` [#164E63]▄[/][#164E63 on #22D3EE]▀▀[/][#164E63]▄[/]    [#164E63]▄[/][#164E63 on #22D3EE]▀▀[/][#164E63]▄[/]
[#164E63]█[/][#22D3EE on #67E8F9]▀[/][#67E8F9]██[/][#22D3EE on #67E8F9]▀[/][#164E63 on #67E8F9]▀▀▀▀[/][#22D3EE on #67E8F9]▀[/][#67E8F9]██[/][#22D3EE on #67E8F9]▀[/][#164E63]█[/]
[#164E63]█[/][#67E8F9]████[/][#67E8F9 on #0891B2]▀[/][#0891B2]██[/][#67E8F9 on #0891B2]▀[/][#67E8F9]████[/][#164E63]█[/]
[#164E63]█[/][#67E8F9]██[/][#67E8F9 on #164E63]▀[/][#0891B2 on #67E8F9]▀▀▀▀▀▀[/][#67E8F9 on #164E63]▀[/][#67E8F9]██[/][#164E63]█[/]
[#164E63]█[/][#67E8F9]█[/][#67E8F9 on #F9A8D4]▀▀[/][#67E8F9]██████[/][#67E8F9 on #F9A8D4]▀▀[/][#67E8F9]█[/][#164E63]█[/]
[#164E63]█[/][#67E8F9 on #22D3EE]▀[/][#F9A8D4 on #67E8F9]▀▀[/][#67E8F9 on #22D3EE]▀[/][#67E8F9]████[/][#67E8F9 on #22D3EE]▀[/][#F9A8D4 on #67E8F9]▀▀[/][#67E8F9 on #22D3EE]▀[/][#164E63]█[/]
 [#164E63]▀██▀[/]    [#164E63]▀██▀[/] `

const DEFAULT_LOGO_ROWS = parseRichMarkup(HERMES_TEXT_LOGO)
const DEFAULT_HERO_ROWS = parseRichMarkup(PIXEL_RHINO)

export const LOGO_WIDTH = 56
export const CADUCEUS_WIDTH = 14

const rowWidth = (row: Row) => row.reduce((n, [, t]) => n + t.length, 0)

// Recolor a default-themed art so it follows the current ThemeColors.
const themed = (rows: Row[], c: ThemeColors): Row[] => {
  const remap: Record<string, keyof ThemeColors> = {
    '#67E8F9': 'primary',
    '#22D3EE': 'primary',
    '#06B6D4': 'accent',
    '#0891B2': 'accent',
    '#0E7490': 'border',
    '#155E75': 'border',
    '#164E63': 'muted',
    '#F9A8D4': 'accent'
  }

  const resolve = (hex: string): string => {
    const key = remap[hex.toLowerCase()] ?? remap[hex.toUpperCase()] ?? remap[hex]
    const themeColor = key ? c[key] : undefined

    return themeColor ?? hex
  }

  return rows.map(row =>
    row.map(([color, text, bg]) => {
      if (!color && !bg) {
        return [color, text] as Segment
      }

      const fg = color ? resolve(color) : color
      const bgColor = bg ? resolve(bg) : undefined

      return (bgColor ? [fg, text, bgColor] : [fg, text]) as Segment
    })
  )
}

// Default wordmark + mascot keep their raw hex palette so the chat banner
// matches the CLI banner pixel-for-pixel. `themed()` only runs for the
// default art if the active theme provides ALL the rhino's source colors
// (currently no theme does), otherwise the 5-color rhino collapses into
// the theme's 3-token palette (primary/accent/muted) and the pink cheeks
// + dark cyan shadow disappear. Skins can still recolor via
// `bannerLogo`/`bannerHero`, which are parsed verbatim below.
export const logo = (c: ThemeColors, customLogo?: string): Row[] =>
  customLogo ? parseRichMarkup(customLogo) : DEFAULT_LOGO_ROWS

export const caduceus = (c: ThemeColors, customHero?: string): Row[] =>
  customHero ? parseRichMarkup(customHero) : DEFAULT_HERO_ROWS

export const artWidth = (rows: Row[]) => rows.reduce((m, row) => Math.max(m, rowWidth(row)), 0)
