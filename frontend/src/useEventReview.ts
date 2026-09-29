import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { addedLabel, type EventRecord, type EventReview } from './derive'
import type { Scenario, Variant } from './types'

export interface ReviewRequest {
  records: Record<string, EventRecord>
  variants: Variant[]
  recommended: string
  scenario: Scenario
}

interface PendingReview extends ReviewRequest {
  decide: (planId: string | null) => void
}

export function useEventReview() {
  const [pending, setPending] = useState<PendingReview | null>(null)
  const [choice, setChoice] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [details, setDetails] = useState(false)

  const shownId = hover ?? choice ?? pending?.recommended ?? null

  const review = useMemo<EventReview | null>(() => {
    const shown = pending && shownId ? pending.records[shownId] : null
    if (!pending || !shown) {
      return null
    }
    const chosen = choice ?? pending.recommended
    return {
      record: shown,
      scenario: pending.scenario,
      added: addedLabel(shown.event, shown.after, pending.scenario),
      decide: (apply) => pending.decide(apply ? chosen : null),
      variants: pending.variants,
      chosen,
      dropsByPlan: Object.fromEntries(Object.entries(pending.records).map(([id, record]) => [id, record.diff.newly_unassigned])),
      onChoose: (planId) => {
        setChoice(planId)
        setHover(null)
      },
      onPreview: setHover,
      previewed: hover,
    }
  }, [pending, shownId, choice, hover])

  useEffect(() => {
    if (!review) {
      setDetails(false)
    }
  }, [review])

  const reviewRef = useRef<EventReview | null>(null)
  reviewRef.current = review

  const ask = useCallback((request: ReviewRequest) => {
    setChoice(request.recommended)
    setHover(null)
    return new Promise<string | null>((decide) => setPending({ ...request, decide }))
  }, [])

  const close = useCallback(() => setPending(null), [])

  return { review, reviewRef, shownId, details, setDetails, ask, close }
}
