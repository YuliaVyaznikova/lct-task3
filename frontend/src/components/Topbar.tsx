import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import type { Objective, Plan, ScenarioBrief } from '../types'

export type Tab = 'plan' | 'schedule' | 'compare' | 'sim'

export const TABS: [Tab, string][] = [
  ['plan', 'План дня'],
  ['schedule', 'Расписание'],
  ['compare', 'Сравнение с базовым'],
  ['sim', 'Симуляция'],
]

export interface PlanParamsUi {
  objective: Objective
  timeLimit: number
  lunch: boolean
  allowReschedule: boolean
  engineerCount: number | null
}

export const DEFAULT_PARAMS: PlanParamsUi = {
  objective: 'auto',
  timeLimit: 20,
  lunch: false,
  allowReschedule: false,
  engineerCount: null,
}

interface Props {
  scenarios: ScenarioBrief[]
  scenarioId: string
  onScenario: (id: string) => void
  onUpload: (file: File) => void
  uploading: boolean
  params: PlanParamsUi
  onParams: (params: PlanParamsUi) => void
  plan: Plan | null
  busy: boolean
  onPlan: () => void
  tab: Tab
  onTab: (tab: Tab) => void
  lockedTabs: boolean
}

function formatDate(date: string) {
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return date
  return d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' })
}

export function Topbar({ scenarios, scenarioId, onScenario, onUpload, uploading, params, onParams, plan, busy, onPlan, tab, onTab, lockedTabs }: Props) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const file = useRef<HTMLInputElement>(null)
  const brief = scenarios.find((s) => s.id === scenarioId)
  const set = (patch: Partial<PlanParamsUi>) => onParams({ ...params, ...patch })
  const changed =
    params.objective !== DEFAULT_PARAMS.objective ||
    params.timeLimit !== DEFAULT_PARAMS.timeLimit ||
    params.lunch ||
    params.allowReschedule ||
    params.engineerCount !== null

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

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
            if (picked) onUpload(picked)
          }}
        />
        {brief && <span className="tb-date">{uploading ? 'Загружаем файл…' : formatDate(brief.date)}</span>}
      </div>

      <nav className="tb-tabs" role="tablist" aria-label="Разделы">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? 'on' : ''}
            disabled={lockedTabs && key !== 'plan'}
            onClick={() => onTab(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="tb-right" ref={box}>
        {plan && (
          <a className="button ghost" href={api.exportUrl(plan.id)} target="_blank" rel="noreferrer">
            Выгрузка
          </a>
        )}
        <button type="button" className="primary plan-btn" disabled={busy || !scenarios.length} onClick={onPlan}>
          <CalendarGlyph />
          {busy ? 'Идёт расчёт' : 'Спланировать день'}
        </button>
        <button
          type="button"
          className={`icon-btn ${open ? 'on' : ''}`}
          aria-label="Параметры расчёта"
          aria-expanded={open}
          title="Параметры расчёта"
          onClick={() => setOpen((v) => !v)}
        >
          <GearGlyph />
          {changed && <i className="badge-dot" />}
        </button>
        {open && (
          <div className="popover params" role="dialog" aria-label="Параметры расчёта">
            <label className="field">
              <span className="field-label">Цель</span>
              <select value={params.objective} onChange={(e) => set({ objective: e.target.value as Objective })}>
                <option value="auto">Автоматически</option>
                <option value="min_engineers">Меньше инженеров</option>
                <option value="min_distance">Меньше пробега</option>
                <option value="balanced">Равномерная загрузка</option>
              </select>
            </label>
            <label className="field">
              <span className="field-label">
                Время на расчёт <b>{params.timeLimit} с</b>
              </span>
              <input type="range" min={5} max={90} value={params.timeLimit} onChange={(e) => set({ timeLimit: Number(e.target.value) })} />
            </label>
            <label className="field">
              <span className="field-label">
                Бригад на смене <b>{params.engineerCount ?? brief?.engineers ?? '—'}</b>
              </span>
              <input
                type="range"
                min={brief?.engineers_min ?? 6}
                max={20}
                value={params.engineerCount ?? brief?.engineers ?? 12}
                onChange={(e) => set({ engineerCount: Number(e.target.value) })}
              />
            </label>
            <label className="check">
              <input type="checkbox" checked={params.lunch} onChange={(e) => set({ lunch: e.target.checked })} />
              Обед 45 мин в 13:00–15:00
            </label>
            <label className="check">
              <input type="checkbox" checked={params.allowReschedule} onChange={(e) => set({ allowReschedule: e.target.checked })} />
              При событиях можно сдвигать обещанное время
            </label>
            <div className="popover-foot">
              {plan && (
                <a className="link-export" href={api.exportUrl(plan.id)} target="_blank" rel="noreferrer">
                  Выгрузка плана
                </a>
              )}
              <button type="button" className="link" disabled={!changed} onClick={() => onParams(DEFAULT_PARAMS)}>
                Сбросить
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  )
}

function CalendarGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <rect x="2" y="3" width="12" height="11" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" stroke="currentColor" strokeWidth="1.4" />
    </svg>
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
function GearGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <circle cx="8" cy="8" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  )
}
