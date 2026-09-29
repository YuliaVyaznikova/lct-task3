import { useRef } from 'react'

import { api } from '../api'
import type { Plan, ScenarioBrief, Tab, UploadProgress } from '../types'
import { StopGlyph } from './common'

export const TABS: [Tab, string][] = [
  ['map', 'Карта'],
  ['schedule', 'Расписание'],
  ['compare', 'Сравнение с базовым'],
]

interface TopbarProps {
  scenarios: ScenarioBrief[]
  scenarioId: string
  onScenario: (id: string) => void
  onUpload: (file: File) => void
  uploading: boolean
  uploadProgress: UploadProgress | null
  onCancelUpload: () => void
  plan: Plan | null
  busy: boolean
  tab: Tab
  onTab: (tab: Tab) => void
  lockedTabs: boolean
  simNeedsDecision: boolean
}

function formatDate(date: string) {
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) {
    return date
  }
  return d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' })
}

export function Topbar({ scenarios, scenarioId, onScenario, onUpload, uploading, uploadProgress, onCancelUpload, plan, busy, tab, onTab, lockedTabs, simNeedsDecision }: TopbarProps) {
  const file = useRef<HTMLInputElement>(null)
  const brief = scenarios.find((s) => s.id === scenarioId)
  return (
    <header className="topbar">
      <div className="tb-left">
        <span className="brand-mark" aria-hidden />
        <label className="area">
          <span className="area-label">Участок</span>
          <select value={scenarioId} onChange={(e) => onScenario(e.target.value)} disabled={busy || !scenarios.length}>
            {!scenarios.length && <option value={scenarioId}>…</option>}
            {scenarios.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="icon-btn"
          aria-label="Загрузить свои данные"
          title="Загрузить свои данные: CSV или JSON"
          disabled={busy || uploading}
          onClick={() => file.current?.click()}
        >
          <UploadGlyph />
        </button>
        <input
          ref={file}
          type="file"
          accept=".csv,.json"
          hidden
          onChange={(e) => {
            const picked = e.target.files?.[0]
            e.target.value = ''
            if (picked) {
              onUpload(picked)
            }
          }}
        />
        {uploading ? (
          <span className="tb-date tb-upload" role="status">
            {uploadProgress ? `Ищем адреса: ${uploadProgress.done} из ${uploadProgress.total}` : 'Загружаем файл…'}
            <button type="button" className="tb-stop" onClick={onCancelUpload} aria-label="Остановить загрузку" title="Остановить загрузку">
              <StopGlyph />
            </button>
          </span>
        ) : (
          brief && <span className="tb-date">{formatDate(brief.date)}</span>
        )}
      </div>

      <nav className="tb-tabs" role="tablist" aria-label="Разделы">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? 'on' : ''}
            disabled={lockedTabs && key !== 'map'}
            onClick={() => onTab(key)}
          >
            {label}
            {key === 'map' && simNeedsDecision && (
              <span className="tab-alert" role="status">
                нужно решение
              </span>
            )}
          </button>
        ))}
      </nav>

      <div className="tb-right">
        {plan && (
          <a className="button ghost" href={api.exportUrl(plan.id)} target="_blank" rel="noreferrer">
            Выгрузка
          </a>
        )}
      </div>
    </header>
  )
}

function UploadGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <path d="M8 10.5V2.5M4.8 5.5L8 2.3l3.2 3.2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2.5 10v2.5a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V10" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}
