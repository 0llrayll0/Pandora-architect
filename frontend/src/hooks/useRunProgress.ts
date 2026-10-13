import { useEffect } from 'react'
import type { LiveProgress } from '@/store/app'
import { useAppStore } from '@/store/app'
import { useInvalidateRunData } from '@/store/api'

interface SsePayload {
  event?: string
  state?: string
  progress?: number
  stage?: string
  message?: string
  files_total?: number
  files_processed?: number
  running?: boolean
}

const TERMINAL_STATES = new Set(['completed', 'failed', 'cancelled'])

/**
 * Assina o SSE de progresso de uma análise e reflete o estado no store global.
 * Encerra sozinho quando a run atinge estado terminal.
 */
export function useRunProgress(runId: number | null, projectId: number | null): void {
  const setLiveProgress = useAppStore((s) => s.setLiveProgress)
  const invalidate = useInvalidateRunData()

  useEffect(() => {
    if (runId === null || projectId === null) {
      setLiveProgress(null)
      return
    }

    const source = new EventSource(`/api/analysis/runs/${runId}/events`)

    const apply = (payload: SsePayload) => {
      const progress: LiveProgress = {
        runId,
        projectId,
        state: payload.state ?? 'running',
        progress: payload.progress ?? 0,
        stage: payload.stage ?? '',
        message: payload.message ?? '',
        filesTotal: payload.files_total ?? 0,
        filesProcessed: payload.files_processed ?? 0,
      }
      setLiveProgress(progress)

      if (payload.event === 'end' || TERMINAL_STATES.has(progress.state)) {
        source.close()
        invalidate(runId, projectId)
        // limpa a barra de progresso ao vivo após o fim
        setLiveProgress(null)
      }
    }

    source.addEventListener('progress', (event) => {
      try {
        apply(JSON.parse((event as MessageEvent<string>).data) as SsePayload)
      } catch {
        // payload malformado: ignora e mantém o último estado válido
      }
    })
    source.addEventListener('end', (event) => {
      try {
        apply(JSON.parse((event as MessageEvent<string>).data) as SsePayload)
      } catch {
        source.close()
        invalidate(runId, projectId)
        setLiveProgress(null)
      }
    })
    source.onerror = () => {
      // EventSource tenta reconectar sozinho; em erro fatal o browser fecha.
      // Sem dados ao vivo, o polling da UI (TanStack Query) assume.
      source.close()
      invalidate(runId, projectId)
      setLiveProgress(null)
    }

    return () => {
      source.close()
      setLiveProgress(null)
    }
  }, [runId, projectId, setLiveProgress, invalidate])
}
