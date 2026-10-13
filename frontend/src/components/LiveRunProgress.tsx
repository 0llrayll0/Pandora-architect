import { Loader2 } from 'lucide-react'
import { Progress } from '@/components/ui/progress'
import { useAppStore } from '@/store/app'

/**
 * Barra de progresso global da análise em execução.
 * Renderiza apenas quando há progresso ao vivo (sem dados simulados).
 */
export function LiveRunProgress() {
  const live = useAppStore((s) => s.liveProgress)
  if (!live) return null

  const percent = Math.max(0, Math.min(100, live.progress))
  const detail = [live.stage, live.message].filter(Boolean).join(' · ')

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 px-4 py-3 space-y-2">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="flex items-center gap-2 text-zinc-300">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />
          Analisando projeto #{live.projectId} · run #{live.runId}
        </span>
        <span className="font-mono text-zinc-400">{percent.toFixed(0)}%</span>
      </div>
      <Progress value={percent} aria-label="Progresso da análise" />
      <div className="flex items-center justify-between gap-3 text-[11px] text-zinc-500">
        <span className="truncate">{detail || 'Processando…'}</span>
        <span className="font-mono shrink-0">
          {live.filesProcessed}/{live.filesTotal} arquivos
        </span>
      </div>
    </div>
  )
}
