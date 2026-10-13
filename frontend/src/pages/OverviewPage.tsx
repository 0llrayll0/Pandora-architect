import { EmptyState } from '@/components/EmptyState'
import { ProjectStatusBadge } from '@/components/ProjectStatusBadge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { useActiveRun } from '@/hooks/useActiveRun'
import { formatDateTime, formatNumber, formatPercent, runStateLabel } from '@/lib/format'
import type { RunSummaryPackage } from '@/lib/types'
import { useAnalyzeProject, useRunSummary } from '@/store/api'

/** Rótulos pt-BR para as métricas reais do backend. */
const METRIC_LABELS: Record<string, string> = {
  files_scanned: 'Arquivos escaneados',
  total_lines: 'Linhas totais',
  code_lines: 'Linhas de código',
  comment_lines: 'Linhas de comentário',
  blank_lines: 'Linhas em branco',
  classes: 'Classes',
  functions: 'Funções',
  methods: 'Métodos',
  parse_errors: 'Erros de parse',
  dependencies_confirmed: 'Dep. confirmadas',
  dependencies_external: 'Dep. externas',
  dependencies_unresolved: 'Dep. não resolvidas',
  max_complexity: 'Complexidade máx.',
  avg_complexity: 'Complexidade média',
  complexity_hotspots: 'Hotspots de complexidade',
}

const METRIC_ORDER = Object.keys(METRIC_LABELS)

function MetricGrid({ metrics }: { metrics: Record<string, number> }) {
  const entries = METRIC_ORDER.filter((key) => key in metrics)
  if (entries.length === 0) return null

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {entries.map((key) => {
        const value = metrics[key]
        const isDecimal = !Number.isInteger(value)
        return (
          <div
            key={key}
            className="rounded-lg border border-zinc-800/80 bg-zinc-900/50 px-3.5 py-3"
          >
            <p className="text-[11px] text-zinc-500">{METRIC_LABELS[key]}</p>
            <p className="mt-0.5 font-mono text-lg font-semibold text-zinc-100">
              {isDecimal ? value.toFixed(1) : formatNumber(value)}
            </p>
          </div>
        )
      })}
    </div>
  )
}

/** Bloco de estado da run (progresso quando ativa, resultado quando finais). */
function RunStatePanel({
  pkg,
  projectId,
}: {
  pkg: RunSummaryPackage | undefined
  projectId: number
}) {
  const analyze = useAnalyzeProject()
  if (!pkg) return null

  const { run, files } = pkg
  const active = run.state === 'running' || run.state === 'pending'

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>Análise #{run.id}</CardTitle>
          <CardDescription>
            Iniciada em {formatDateTime(run.started_at ?? run.created_at)}
            {run.finished_at ? ` · concluída em ${formatDateTime(run.finished_at)}` : ''}
          </CardDescription>
        </div>
        <ProjectStatusBadge state={run.state} />
      </CardHeader>
      <CardContent className="space-y-4">
        {active && (
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs text-zinc-400">
              <span>{run.stage || runStateLabel(run.state)}</span>
              <span className="font-mono">{formatPercent(run.progress)}</span>
            </div>
            <Progress value={run.progress} aria-label="Progresso da análise" />
            <p className="text-[11px] text-zinc-500">
              {formatNumber(run.files_processed)}/{formatNumber(run.files_total)} arquivos
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <div>
            <p className="text-zinc-500">Arquivos</p>
            <p className="font-mono text-zinc-200">
              {formatNumber(files.total)}
              {files.parse_errors > 0 && (
                <span className="text-amber-400"> ({formatNumber(files.parse_errors)} c/ erro)</span>
              )}
            </p>
          </div>
          <div>
            <p className="text-zinc-500">Símbolos</p>
            <p className="font-mono text-zinc-200">{formatNumber(run.symbols_count)}</p>
          </div>
          <div>
            <p className="text-zinc-500">Dependências</p>
            <p className="font-mono text-zinc-200">{formatNumber(run.dependencies_count)}</p>
          </div>
          <div>
            <p className="text-zinc-500">Módulos</p>
            <p className="font-mono text-zinc-200">{formatNumber(run.modules_count)}</p>
          </div>
        </div>

        {run.state === 'failed' && run.error && (
          <p className="rounded-md border border-rose-900/60 bg-rose-950/40 px-3 py-2 font-mono text-xs text-rose-300">
            {run.error}
          </p>
        )}

        {run.state !== 'running' && run.state !== 'pending' && (
          <Button
            variant="outline"
            size="sm"
            disabled={analyze.isPending}
            onClick={() => analyze.mutate(projectId)}
          >
            Nova análise
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

export function OverviewPage({ projectId }: { projectId: number }) {
  const { runId, runs, run } = useActiveRun(projectId)
  const { data: summary, isLoading } = useRunSummary(runId)

  if (runId === null) {
    return (
      <EmptyState
        title="Nenhuma análise neste projeto"
        description="Clique em “Analisar” no topo para escanear os arquivos do repositório e gerar métricas reais."
      />
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Análise</h1>
        <p className="text-sm text-zinc-500">
          Métricas da run #{runId}
          {run ? ` · ${runStateLabel(run.state)}` : ''} — dados reais do backend.
        </p>
      </div>

      <RunStatePanel pkg={summary} projectId={projectId} />

      {isLoading && !summary && <p className="text-sm text-zinc-500">Carregando métricas…</p>}

      {summary && (
        <Card>
          <CardHeader>
            <CardTitle>Métricas do repositório</CardTitle>
            <CardDescription>Escopo do projeto · run #{summary.run.id}</CardDescription>
          </CardHeader>
          <CardContent>
            <MetricGrid metrics={summary.metrics} />
            {Object.keys(summary.metrics).length === 0 && (
              <p className="text-sm text-zinc-500">
                Sem métricas disponíveis para esta run.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {runs.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Análises recentes</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-zinc-800/80">
              {runs.slice(0, 8).map((r) => (
                <li
                  key={r.id}
                  className="flex items-center justify-between py-2 text-sm"
                >
                  <span className="font-mono text-zinc-300">#{r.id}</span>
                  <span className="text-zinc-500">{formatDateTime(r.created_at)}</span>
                  <ProjectStatusBadge state={r.state} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
