import { hhmm } from '../time'

interface SwitchConfirmProps {
  clock: number
  onConfirm: () => void
  onCancel: () => void
}

export function SwitchConfirm({ clock, onConfirm, onCancel }: SwitchConfirmProps) {
  return (
    <div className="switch-confirm" role="alertdialog" aria-label="Смена плана">
      <span>
        <b>Симуляция начнётся заново.</b> Она на паузе в {hhmm(Math.floor(clock))}.
      </span>
      <button type="button" className="primary small" onClick={onConfirm}>
        Переключить план
      </button>
      <button type="button" className="ghost small" onClick={onCancel}>
        Отмена
      </button>
    </div>
  )
}
