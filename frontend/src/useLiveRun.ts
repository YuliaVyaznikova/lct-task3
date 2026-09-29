import { useCallback, useRef, useState } from 'react'

import { VARIANT_ORDER } from './labels'
import type { RunningJob } from './types'
import { useSnapshot } from './useSnapshot'

const SNAPSHOT_MS = 2000

const watchedKey = (job: RunningJob, chosen: string | null) =>
  chosen ?? job.expected[0] ?? VARIANT_ORDER.find((key) => key in job.byVariant) ?? Object.keys(job.byVariant)[0] ?? null

function watchedProgress(job: RunningJob | null, chosen: string | null) {
  if (!job) {
    return null
  }
  const key = watchedKey(job, chosen)
  if (key && job.byVariant[key]) {
    return job.byVariant[key]
  }
  return Object.keys(job.byVariant).length ? null : job.last
}

export function useLiveRun(job: RunningJob | null) {
  const [watchKey, setWatchKey] = useState<string | null>(null)
  const [peekKey, setPeekKey] = useState<string | null>(null)
  const watchRef = useRef<string | null>(null)

  const watchVariant = useCallback((key: string | null) => {
    watchRef.current = key
    setWatchKey(key)
  }, [])

  const watching = job ? watchedKey(job, watchKey) : null
  const liveProgress = useSnapshot(watchedProgress(job, watchKey), SNAPSHOT_MS, watching)
  const peeked = useSnapshot(job && peekKey ? job.byVariant[peekKey] ?? null : null, SNAPSHOT_MS, peekKey)

  return { watchRef, watchVariant, setPeekKey, watching, liveProgress, liveRoutes: peeked?.routes ?? null }
}
