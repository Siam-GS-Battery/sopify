import type { ThemeColors } from './theme.js'

const RICH_RE = /\[(?:bold\s+)?(?:dim\s+)?(#(?:[0-9a-fA-F]{3,8}))\]([\s\S]*?)\[\/\]/g

export type Segment = [string, string]
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

      row.push([m[1]!, m[2]!])
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

const PIXEL_RHINO = `[#164E63]    ████            ████    [/]
[#164E63]  ██[/][#22D3EE]████[/][#164E63]██        ██[/][#22D3EE]████[/][#164E63]██  [/]
[#164E63]██[/][#22D3EE]██[/][#67E8F9]████[/][#22D3EE]██[/][#164E63]████████[/][#22D3EE]██[/][#67E8F9]████[/][#22D3EE]██[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]████████████████████████[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]██████████[/][#0891B2]████[/][#67E8F9]██████████[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]████████[/][#0891B2]████████[/][#67E8F9]████████[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]██████[/][#0891B2]████████████[/][#67E8F9]██████[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]████[/][#164E63]██[/][#67E8F9]████████████[/][#164E63]██[/][#67E8F9]████[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]████████████████████████[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]██[/][#F9A8D4]████[/][#67E8F9]████████████[/][#F9A8D4]████[/][#67E8F9]██[/][#164E63]██[/]
[#164E63]██[/][#67E8F9]██[/][#F9A8D4]████[/][#67E8F9]████████████[/][#F9A8D4]████[/][#67E8F9]██[/][#164E63]██[/]
[#164E63]██[/][#22D3EE]██[/][#67E8F9]████[/][#22D3EE]██[/][#67E8F9]████████[/][#22D3EE]██[/][#67E8F9]████[/][#22D3EE]██[/][#164E63]██[/]
[#164E63]  ████████        ████████  [/]
[#164E63]    ████            ████    [/]`

const DEFAULT_LOGO_ROWS = parseRichMarkup(HERMES_TEXT_LOGO)
const DEFAULT_HERO_ROWS = parseRichMarkup(PIXEL_RHINO)

export const LOGO_WIDTH = 56
export const CADUCEUS_WIDTH = 28

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

  return rows.map(row =>
    row.map(([color, text]) => {
      if (!color) {
        return [color, text] as Segment
      }

      const key = remap[color.toLowerCase()] ?? remap[color.toUpperCase()] ?? remap[color]
      const themeColor = key ? c[key] : undefined

      return [themeColor ?? color, text] as Segment
    })
  )
}

export const logo = (c: ThemeColors, customLogo?: string): Row[] =>
  customLogo ? parseRichMarkup(customLogo) : themed(DEFAULT_LOGO_ROWS, c)

export const caduceus = (c: ThemeColors, customHero?: string): Row[] =>
  customHero ? parseRichMarkup(customHero) : themed(DEFAULT_HERO_ROWS, c)

export const artWidth = (rows: Row[]) => rows.reduce((m, row) => Math.max(m, rowWidth(row)), 0)
