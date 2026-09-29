import { useCallback, useEffect, useRef, useState } from 'react'

import { api, streamJob } from './api'
import { isAbort } from './plan-session'
import type { Scenario, ScenarioBrief, UploadProgress } from './types'

const DEFAULT_SCENARIO = 'demo'

interface RunningUpload {
  controller: AbortController
  jobId: string | null
}

export function useScenarioCatalog(onError: (message: string | null) => void) {
  const [scenarios, setScenarios] = useState<ScenarioBrief[]>([])
  const [scenarioId, setScenarioId] = useState(DEFAULT_SCENARIO)
  const [scenarioVersion, setScenarioVersion] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null)
  const uploadRef = useRef<RunningUpload | null>(null)

  const load = useCallback(() => {
    api
      .scenarios()
      .then((list) => {
        setScenarios(list)
        setScenarioId((current) => (list.length && !list.some((s) => s.id === current) ? list[0].id : current))
      })
      .catch((e) => onError((e as Error).message))
  }, [onError])
  useEffect(load, [load])

  const cancelUpload = useCallback(() => {
    const current = uploadRef.current
    uploadRef.current = null
    current?.controller.abort()
    if (current?.jobId) {
      api.cancelJob(current.jobId).catch(() => undefined)
    }
  }, [])

  const upload = useCallback(
    async (file: File) => {
      cancelUpload()
      const current: RunningUpload = { controller: new AbortController(), jobId: null }
      uploadRef.current = current
      setUploading(true)
      setUploadProgress(null)
      onError(null)
      try {
        const { job_id } = await api.uploadJob(file, current.controller.signal)
        current.jobId = job_id
        if (current.controller.signal.aborted) {
          api.cancelJob(job_id).catch(() => undefined)
          return
        }
        const loaded = await streamJob<Scenario, UploadProgress>(job_id, { onProgress: setUploadProgress, signal: current.controller.signal })
        setScenarios(await api.scenarios())
        setScenarioId(loaded.id)
        setScenarioVersion((version) => version + 1)
      } catch (e) {
        if (!isAbort(e)) {
          onError(`Файл не загружен: ${(e as Error).message}`)
        }
      } finally {
        if (uploadRef.current === current) {
          uploadRef.current = null
        }
        setUploading(false)
        setUploadProgress(null)
      }
    },
    [onError, cancelUpload],
  )

  return { scenarios, scenarioId, setScenarioId, scenarioVersion, uploading, uploadProgress, upload, cancelUpload, reload: load }
}
