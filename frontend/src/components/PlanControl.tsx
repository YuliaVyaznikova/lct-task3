import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { OBJECTIVE_LABEL } from '../labels'
import { balancePhaseS } from '../usePlanningRequests'
import type { Objective, Plan, ScenarioBrief } from '../types'

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

interface PlanControlProps {
  brief: ScenarioBrief | undefined
  params: PlanParamsUi
  onParams: (params: PlanParamsUi) => void
  plan: Plan | null
  busy: boolean
  onPlan: () => void
}

const isChanged = (params: PlanParamsUi) =>
  params.objective !== DEFAULT_PARAMS.objective ||
  params.timeLimit !== DEFAULT_PARAMS.timeLimit ||
  params.lunch !== DEFAULT_PARAMS.lunch ||
  params.allowReschedule ||
  params.engineerCount !== null

function useDismiss(open: boolean, close: () => void) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) {
      return
    }
    const outside = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) {
        close()
      }
    }
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && close()
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [open, close])
  return box
}

export function PlanControl({ brief, params, onParams, plan, busy, onPlan }: PlanControlProps) {
  const [open, setOpen] = useState(false)
  const box = useDismiss(open, () => setOpen(false))
  const changed = isChanged(params)
  const set = (patch: Partial<PlanParamsUi>) => onParams({ ...params, ...patch })
  return (
    <div className="plan-control" ref={box}>
      <div className="plan-split">
        <button type="button" className="primary plan-btn" disabled={busy || !brief} onClick={onPlan}>
          Спланировать день
        </button>
        <button
          type="button"
          className={`primary plan-arrow ${open ? 'on' : ''}`}
          aria-label="Параметры расчёта"
          aria-expanded={open}
          title="Параметры расчёта"
          onClick={() => setOpen(!open)}
        >
          <ArrowGlyph />
          {changed && <i className="badge-dot" />}
        </button>
      </div>
      {open && (
        <div className="popover" role="dialog" aria-label="Параметры расчёта">
          <label className="field">
            <span className="field-label">Цель</span>
            <select value={params.objective} onChange={(e) => set({ objective: e.target.value as Objective })}>
              {Object.entries(OBJECTIVE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">
              Время на расчёт <b>{params.timeLimit} с</b>
              {balancePhaseS(params.objective) > 0 && ` + ${balancePhaseS(params.objective)} с на ровную загрузку`}
            </span>
            <input type="range" min={5} max={90} value={params.timeLimit} onChange={(e) => set({ timeLimit: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span className="field-label">
              Бригад на смене <b>{params.engineerCount ?? brief?.engineers ?? '\u00a0'}</b>
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
  )
}

function ArrowGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 16 16" aria-hidden>
      <path d="M4 10l4-4 4 4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
