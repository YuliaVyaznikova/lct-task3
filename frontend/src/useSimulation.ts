import { useCallback, useEffect, useRef, useState } from 'react'

import { hhmm, minutes } from './colors'
import type { PlanEvent } from './types'

export type Speed = 30 | 60 | 120

const MIN_CLOCK_STEP_MINUTES = 0.25
const MAX_FRAME_INTERVAL_SECONDS = 0.066
const RESUME_COUNTDOWN_SECONDS = 3

export interface SimEvent {
  id: string
  event: PlanEvent
  source: 'scenario' | 'added'
  status: 'pending' | 'running' | 'done' | 'failed'
  error?: string
  summary?: { moved: number; frozen: number; planId: string; seconds: number; added?: string }
}

export function eventId(event: PlanEvent): string {
  if (event.type === 'urgent_order') return `urgent:${event.order.id}`
  if (event.type === 'new_order') return `new:${event.order.id}`
  if (event.type === 'cancel_order') return `cancel:${event.order_id}`
  if (event.type === 'engineer_delayed') return `delay:${event.engineer_id}:${event.time}`
  return `off:${event.engineer_id}`
}

interface Options {
  range: [number, number]
  run: (event: PlanEvent) => Promise<SimEvent['summary']>
}

export function useSimulation({ range, run }: Options) {
  const [clock, setClockState] = useState(range[0])
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<Speed>(60)
  const [events, setEvents] = useState<SimEvent[]>([])
  const [resumeIn, setResumeIn] = useState<number | null>(null)

  const clockRef = useRef(clock)
  const eventsRef = useRef(events)
  const runningRef = useRef(false)
  const wasPlayingRef = useRef(false)
  const runRef = useRef(run)
  clockRef.current = clock
  eventsRef.current = events
  runRef.current = run

  const reset = useCallback((prepared: PlanEvent[], start: number) => {
    setPlaying(false)
    setResumeIn(null)
    setClockState(start)
    clockRef.current = start
    const list: SimEvent[] = prepared
      .map((event) => ({ id: eventId(event), event, source: 'scenario' as const, status: 'pending' as const }))
      .sort((a, b) => minutes(a.event.time) - minutes(b.event.time))
    setEvents(list)
    eventsRef.current = list
  }, [])

  const fire = useCallback(async (item: SimEvent) => {
    runningRef.current = true
    setEvents((list) => list.map((e) => (e.id === item.id ? { ...e, status: 'running' } : e)))
    try {
      const summary = await runRef.current(item.event)
      setEvents((list) => list.map((e) => (e.id === item.id ? { ...e, status: 'done', summary } : e)))
      if (wasPlayingRef.current) setResumeIn(RESUME_COUNTDOWN_SECONDS)
    } catch (err) {
      setEvents((list) => list.map((e) => (e.id === item.id ? { ...e, status: 'failed', error: (err as Error).message } : e)))
      if (wasPlayingRef.current) setResumeIn(RESUME_COUNTDOWN_SECONDS)
    } finally {
      runningRef.current = false
    }
  }, [])

  const setClock = useCallback(
    (target: number, fromPlayback = false) => {
      if (runningRef.current) return
      const boundedTarget = Math.max(range[0], Math.min(range[1], target))
      const nextPendingEvent = eventsRef.current
        .filter((event) => event.status === 'pending' && minutes(event.event.time) <= boundedTarget)
        .sort((a, b) => minutes(a.event.time) - minutes(b.event.time))[0]
      if (nextPendingEvent) {
        const eventClock = Math.max(minutes(nextPendingEvent.event.time), Math.min(clockRef.current, boundedTarget))
        clockRef.current = eventClock
        setClockState(eventClock)
        wasPlayingRef.current = fromPlayback
        setPlaying(false)
        void fire(nextPendingEvent)
        return
      }
      clockRef.current = boundedTarget
      setClockState(boundedTarget)
      if (boundedTarget >= range[1]) setPlaying(false)
    },
    [range, fire],
  )

  useEffect(() => {
    if (!playing) return
    let frame = 0
    let lastFrameAt = performance.now()
    let accumulatedMinutes = 0
    const tick = (now: number) => {
      const elapsedSeconds = (now - lastFrameAt) / 1000
      lastFrameAt = now
      accumulatedMinutes += (elapsedSeconds * speed) / 60
      if (accumulatedMinutes >= MIN_CLOCK_STEP_MINUTES || elapsedSeconds > MAX_FRAME_INTERVAL_SECONDS) {
        setClock(clockRef.current + accumulatedMinutes, true)
        accumulatedMinutes = 0
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, speed, setClock])

  useEffect(() => {
    if (runningRef.current) return
    const dueEvent = events.find((event) => event.status === 'pending' && minutes(event.event.time) <= clockRef.current)
    if (dueEvent) {
      wasPlayingRef.current = playing
      setPlaying(false)
      void fire(dueEvent)
    }
  }, [events, fire, playing])

  useEffect(() => {
    if (resumeIn === null) return
    if (resumeIn <= 0) {
      setResumeIn(null)
      setPlaying(true)
      return
    }
    const timer = window.setTimeout(() => setResumeIn((v) => (v === null ? null : v - 1)), 1000)
    return () => window.clearTimeout(timer)
  }, [resumeIn])

  const add = useCallback((event: PlanEvent) => {
    const item: SimEvent = { id: eventId(event), event, source: 'added', status: 'pending' }
    setEvents((list) => [...list.filter((e) => e.id !== item.id), item].sort((a, b) => minutes(a.event.time) - minutes(b.event.time)))
  }, [])

  const toggle = useCallback(() => {
    setResumeIn(null)
    if (runningRef.current) return
    setPlaying((p) => {
      if (!p && clockRef.current >= range[1]) {
        clockRef.current = range[0]
        setClockState(range[0])
      }
      return !p
    })
  }, [range])

  return {
    clock,
    clockLabel: hhmm(Math.floor(clock)),
    playing,
    speed,
    setSpeed,
    events,
    busy: events.some((e) => e.status === 'running'),
    resumeIn,
    cancelResume: () => setResumeIn(null),
    setClock: (t: number) => {
      setResumeIn(null)
      setClock(t)
    },
    toggle,
    reset,
    add,
    range,
  }
}

export type Simulation = ReturnType<typeof useSimulation>
