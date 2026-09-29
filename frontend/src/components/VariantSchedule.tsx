import { useMemo } from 'react'

import type { Plan, Scenario } from '../types'
import { changesBetween } from '../variant-diff'
import { ReviewSchedule } from './ReviewSchedule'

export interface VariantOption {
  planId: string
  title: string
}

interface VariantScheduleProps {
  scenario: Scenario
  current: Plan
  currentTitle: string
  options: VariantOption[]
  otherId: string
  other: Plan | null
  onPick: (planId: string) => void
  onClose: () => void
}

export function VariantSchedule({ scenario, current, currentTitle, options, otherId, other, onPick, onClose }: VariantScheduleProps) {
  const changes = useMemo(() => (other ? changesBetween(current, other) : null), [current, other])
  if (!other || !changes) {
    return (
      <div className="review-overlay loading-screen" role="region" aria-label="Сравнение вариантов">
        <span className="spinner lg" />
      </div>
    )
  }
  const picker = (
    <div className="seg" role="radiogroup" aria-label="Сравнить с вариантом">
      {options.map((option) => (
        <button key={option.planId} type="button" role="radio" aria-checked={option.planId === otherId} className={option.planId === otherId ? 'on' : ''} onClick={() => onPick(option.planId)}>
          {option.title}
        </button>
      ))}
    </div>
  )
  return (
    <ReviewSchedule
      title={`Сравнение с выбранным: ${currentTitle}`}
      label="Сравнение вариантов"
      before={current}
      after={other}
      changes={changes}
      scenario={scenario}
      picker={picker}
      onClose={onClose}
    />
  )
}
