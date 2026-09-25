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

export function labelIcon(text: string, color: string, dim: boolean): L.DivIcon {
  return cachedIcon(`l|${text}|${color}|${dim}`, () =>
    L.divIcon({
      className: 'map-label-wrap',
      html: `<div class="map-label${dim ? ' dim' : ''}" style="--c:${color}">${escapeHtml(text)}</div>`,
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    }),
  )
}

export function engineerIcon(short: string, color: string, status: string): L.DivIcon {
  return cachedIcon(`e|${short}|${color}|${status}`, () =>
    L.divIcon({
      className: 'em-wrap',
      html: `<div class="em em-${status}" style="--c:${color}">${escapeHtml(short)}</div>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    }),
  )
}

export const officeIcon = L.divIcon({
  className: 'vm-wrap',
  html: '<div class="office-mark"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
})
export const baseIcon = L.divIcon({
  className: 'vm-wrap',
  html: '<div class="office-mark hollow"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
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
  if (digits) return digits[1]
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}
