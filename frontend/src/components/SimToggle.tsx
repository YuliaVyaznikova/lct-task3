import { cx } from '../classes'

interface SimToggleProps {
  on: boolean
  disabled: boolean
  needsDecision: boolean
  onToggle: () => void
}

export function SimToggle({ on, disabled, needsDecision, onToggle }: SimToggleProps) {
  return (
    <button type="button" className={cx('sim-toggle', on && 'on')} aria-pressed={on} disabled={disabled} onClick={onToggle}>
      Симуляция
      {needsDecision && !on && (
        <span className="tab-alert" role="status">
          нужно решение
        </span>
      )}
    </button>
  )
}
