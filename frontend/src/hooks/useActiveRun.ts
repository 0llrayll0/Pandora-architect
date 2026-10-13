import { useMemo } from 'react'
import { useProjectRuns } from '@/store/api'
import { useAppStore } from '@/store/app'
import type { RunSummary } from '@/lib/types'

interface ActiveRun {
  runId: number | null
  runs: RunSummary[]
  run: RunSummary | null
  isRefetching: boolean
  selectRun: (id: number | null) => void
}

/**
 * Resolve a run ativa do projeto: a selecionada manualmente, senão
 * a mais recente do projeto. Null quando nunca houve análise.
 */
export function useActiveRun(projectId: number | null): ActiveRun {
  const selectedRunId = useAppStore((s) => s.selectedRunId)
  const setSelectedRun = useAppStore((s) => s.setSelectedRun)
  const { data: runs = [], isFetching } = useProjectRuns(projectId)

  const run = useMemo(() => {
    if (runs.length === 0) return null
    const selected = selectedRunId !== null ? runs.find((r) => r.id === selectedRunId) : undefined
    return selected ?? runs[0]
  }, [runs, selectedRunId])

  return {
    runId: run?.id ?? null,
    runs,
    run,
    isRefetching: isFetching,
    selectRun: setSelectedRun,
  }
}
