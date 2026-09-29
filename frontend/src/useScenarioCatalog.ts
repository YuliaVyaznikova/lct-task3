import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import type { ScenarioBrief } from './types'

const DEFAULT_SCENARIO = 'demo'

export function useScenarioCatalog(onError: (message: string | null) => void) {
  const [scenarios, setScenarios] = useState<ScenarioBrief[]>([])
  const [scenarioId, setScenarioId] = useState(DEFAULT_SCENARIO)
  const [scenarioVersion, setScenarioVersion] = useState(0)
  const [uploading, setUploading] = useState(false)

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

  const upload = useCallback(
    async (file: File) => {
      setUploading(true)
      onError(null)
      try {
        const loaded = await api.upload(file)
        setScenarios(await api.scenarios())
        setScenarioId(loaded.id)
        setScenarioVersion((version) => version + 1)
      } catch (e) {
        onError(`Файл не загружен: ${(e as Error).message}`)
      } finally {
        setUploading(false)
      }
    },
    [onError],
  )

  return { scenarios, scenarioId, setScenarioId, scenarioVersion, uploading, upload, reload: load }
}
