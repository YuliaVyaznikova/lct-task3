import L from 'leaflet'

const iconCache = new Map<string, L.DivIcon>()
function cachedIcon(key: string, make: () => L.DivIcon): L.DivIcon {
  let icon = iconCache.get(key)
  if (!icon) {
    icon = make()
    iconCache.set(key, icon)
  }
  return icon
}

export function visitIcon(n: number, color: string, mods: string[]): L.DivIcon {
  const cls = ['vm', ...mods].join(' ')
  return cachedIcon(`v|${n}|${color}|${cls}`, () =>
    L.divIcon({
      className: 'vm-wrap',
      html: `<div class="${cls}" style="--c:${color}">${n}</div>`,
      iconSize: [20, 20],
      iconAnchor: [10, 10],
    }),
  )
}

export function engineerIcon(short: string, color: string, status: string, dim: boolean): L.DivIcon {
  return cachedIcon(`e|${short}|${color}|${status}|${dim}`, () =>
    L.divIcon({
      className: 'em-wrap',
      html: `<div class="em em-${status}${dim ? ' dim' : ''}" style="--c:${color}">${escapeHtml(short)}</div>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    }),
  )
}

export const PLACE_GLYPH = {
  office:
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M3 1h10v14H3zM5 3v2h2V3zm4 0v2h2V3zM5 7v2h2V7zm4 0v2h2V7zm-2 4v4h2v-4z"/></svg>',
  base:
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M8 1l7 5v9H1V6zM4 9v6h8V9zm1 2h6v1H5zm0 2h6v1H5z"/></svg>',
} as const

export const placeMarkHtml = (kind: keyof typeof PLACE_GLYPH) => `<div class="place-mark ${kind}">${PLACE_GLYPH[kind]}</div>`

export const officeIcon = L.divIcon({
  className: 'vm-wrap',
  html: placeMarkHtml('office'),
  iconSize: [28, 28],
  iconAnchor: [14, 14],
})
export const baseIcon = L.divIcon({
  className: 'vm-wrap',
  html: placeMarkHtml('base'),
  iconSize: [26, 26],
  iconAnchor: [13, 13],
})
export const pinIcon = L.divIcon({
  className: 'vm-wrap',
  html: '<div class="pick-pin"></div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
})

function escapeHtml(text: string) {
  return text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string)
}

export function shortName(name: string): string {
  const digits = name.match(/(\d+)\s*$/)
  if (digits) {
    return digits[1]
  }
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}
