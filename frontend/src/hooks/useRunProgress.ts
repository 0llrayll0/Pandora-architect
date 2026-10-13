import { useEffect, useRef } from 'react'
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
 *
 * As dependências do efeito são EXCLUSIVAMENTE `runId`/`projectId`: os
 * callbacks (store zustand + invalidador de queries) são lidos de
 * `callbacksRef.current` no ponto de uso (dentro de `apply`, `onerror` e do
 * cleanup), então nenhum re-render recria o `EventSource` e os handlers
 * sempre enxergam a referência mais recente.
 */
export function useRunProgress(runId: number | null, projectId: number | null): void {
  const setLiveProgress = useAppStore((s) => s.setLiveProgress)
  const invalidate = useInvalidateRunData()

  // mantém a referência mais recente sem entrar na lista de deps do efeito
  const callbacksRef = useRef({ setLiveProgress, invalidate })
  useEffect(() => {
    callbacksRef.current = { setLiveProgress, invalidate }
  }, [setLiveProgress, invalidate])

  useEffect(() => {
    if (runId === null || projectId === null) {
      callbacksRef.current.setLiveProgress(null)
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
      callbacksRef.current.setLiveProgress(progress)

      if (payload.event === 'end' || TERMINAL_STATES.has(progress.state)) {
        source.close()
        callbacksRef.current.invalidate(runId, projectId)
        // limpa a barra de progresso ao vivo após o fim
        callbacksRef.current.setLiveProgress(null)
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
        callbacksRef.current.invalidate(runId, projectId)
        callbacksRef.current.setLiveProgress(null)
      }
    })
    source.onerror = () => {
      // EventSource tenta reconectar sozinho; em erro fatal o browser fecha.
      // Aqui fechamos o SSE manualmente e invalidamos as queries uma única
      // vez — não há polling agendado: `useProjectRuns`/`useProjects` não
      // têm `refetchInterval` (só `useHealth` tem).
      source.close()
      callbacksRef.current.invalidate(runId, projectId)
      callbacksRef.current.setLiveProgress(null)
    }

    return () => {
      source.close()
      callbacksRef.current.setLiveProgress(null)
    }
  }, [runId, projectId])
}
