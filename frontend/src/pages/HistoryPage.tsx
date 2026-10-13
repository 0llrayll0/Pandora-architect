import { useMemo, useState } from 'react'
import { ArrowRight, History, Plus, Minus, GitBranch } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/EmptyState'
import { ProjectStatusBadge } from '@/components/ProjectStatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime, formatNumber, runStateLabel } from '@/lib/format'
import { useAnalyses, useCompare } from '@/store/api'

/** Rótulos pt-BR para as métricas comparadas. */
const METRIC_LABELS: Record<string, string> = {
  nodes: 'Nós do grafo',
  edges: 'Arestas',
  weak_components: 'Componentes fracos',
  strong_components: 'Componentes fortes',
  cycles: 'Ciclos',
  avg_instability: 'Instabilidade média',
}

function Delta({ value }: { value: number }) {
  if (value === 0) return <span className="text-zinc-500">—</span>
  const positive = value > 0
  return (
    <span
      className={
        positive ? 'font-mono text-amber-300' : 'font-mono text-emerald-300'
      }
    >
      {positive ? '+' : ''}
      {value}
    </span>
  )
}

export function HistoryPage({ projectId }: { projectId: number }) {
  const { data, isLoading, error } = useAnalyses(projectId)
  const [baseId, setBaseId] = useState<number | null>(null)
  const [targetId, setTargetId] = useState<number | null>(null)

  const items = data?.items ?? []

  // base default: análise mais antiga; target default: a mais recente
  const [base, target] = useMemo<[number | null, number | null]>(() => {
    if (items.length < 2) return [null, null]
    const oldest = items[items.length - 1]
    const newest = items[0]
    return [baseId ?? oldest.id, targetId ?? newest.id]
  }, [items, baseId, targetId])

  const compare = useCompare(projectId, base, target)

  if (isLoading) return <p className="text-sm text-zinc-500">Carregando histórico…</p>

  if (error) {
    return (
      <EmptyState
        title="Falha ao carregar histórico"
        description={error instanceof Error ? error.message : 'Erro inesperado.'}
      />
    )
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={<History className="h-8 w-8" />}
        title="Sem análises neste projeto"
        description="Execute uma análise para começar a acompanhar a evolução das métricas."
      />
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Histórico de análises</h1>
        <p className="text-sm text-zinc-500">
          {formatNumber(data?.total ?? 0)} análise
          {(data?.total ?? 0) === 1 ? '' : 's'} neste projeto.
        </p>
      </div>

      {/* Lista de análises */}
      <Card>
        <CardHeader>
          <CardTitle>Análises</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-zinc-800/80">
            {items.map((item) => (
              <li key={item.id} className="grid gap-2 py-3 text-sm sm:grid-cols-4">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-zinc-200">#{item.id}</span>
                  <ProjectStatusBadge state={item.state} />
                </div>
                <span className="text-zinc-500">
                  {formatDateTime(item.created_at)}
                </span>
                {item.graph === null ? (
                  <span className="text-xs text-zinc-600">
                    Sem métricas de grafo (análise anterior à Fase 2)
                  </span>
                ) : (
                  <span className="font-mono text-xs text-zinc-400">
                    {formatNumber(item.graph.nodes)} nós ·{' '}
                    {formatNumber(item.graph.edges)} arestas ·{' '}
                    {formatNumber(item.graph.cycles)} ciclo
                    {item.graph.cycles === 1 ? '' : 's'}
                  </span>
                )}
                <span className="text-right font-mono text-xs text-zinc-500">
                  {runStateLabel(item.state)} · {formatNumber(item.symbols_count)} símb.
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {/* Comparador — só quando há ao menos duas análises */}
      {items.length >= 2 && base !== null && target !== null && (
        <Card>
          <CardHeader>
            <CardTitle>Comparar análises</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <select
                value={base}
                onChange={(event) => setBaseId(Number(event.target.value))}
                className="rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 font-mono text-sm text-zinc-200"
                aria-label="Análise base"
              >
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    base · #{item.id}
                  </option>
                ))}
              </select>
              <ArrowRight className="h-4 w-4 text-zinc-500" />
              <select
                value={target}
                onChange={(event) => setTargetId(Number(event.target.value))}
                className="rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 font-mono text-sm text-zinc-200"
                aria-label="Análise destino"
              >
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    destino · #{item.id}
                  </option>
                ))}
              </select>
            </div>

            {base === target ? (
              <p className="text-sm text-zinc-500">
                Selecione duas análises diferentes para ver o diff.
              </p>
            ) : compare.isError ? (
              <p className="text-sm text-rose-400">
                {compare.error instanceof Error
                  ? compare.error.message
                  : 'Erro ao comparar.'}
              </p>
            ) : compare.isFetching ? (
              <p className="text-sm text-zinc-500">Comparando…</p>
            ) : compare.data ? (
              <div className="space-y-4">
                {/* arquivos */}
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className="rounded-md bg-zinc-900/60 px-3 py-2">
                    <p className="text-[11px] text-zinc-500">Arquivos alterados</p>
                    <p className="font-mono text-lg text-zinc-100">
                      {formatNumber(compare.data.files.modified.length)}
                    </p>
                  </div>
                  <div className="rounded-md bg-zinc-900/60 px-3 py-2">
                    <p className="text-[11px] text-zinc-500">Adicionados</p>
                    <p className="flex items-center gap-1 font-mono text-lg text-emerald-300">
                      <Plus className="h-3.5 w-3.5" />
                      {formatNumber(compare.data.files.added.length)}
                    </p>
                  </div>
                  <div className="rounded-md bg-zinc-900/60 px-3 py-2">
                    <p className="text-[11px] text-zinc-500">Removidos</p>
                    <p className="flex items-center gap-1 font-mono text-lg text-rose-300">
                      <Minus className="h-3.5 w-3.5" />
                      {formatNumber(compare.data.files.removed.length)}
                    </p>
                  </div>
                </div>

                {/* métricas */}
                <div className="grid gap-2 sm:grid-cols-3">
                  {Object.entries(compare.data.metrics).map(([key, metric]) => (
                    <div key={key} className="rounded-md border border-zinc-800 px-3 py-2">
                      <p className="text-[11px] text-zinc-500">
                        {METRIC_LABELS[key] ?? key}
                      </p>
                      <p className="font-mono text-sm text-zinc-200">
                        {metric.base} → {metric.target}{' '}
                        <Delta value={metric.delta} />
                      </p>
                    </div>
                  ))}
                </div>

                {/* dependências */}
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="success">
                    +{formatNumber(compare.data.dependencies.added.length)} dep.
                  </Badge>
                  <Badge variant="danger">
                    −{formatNumber(compare.data.dependencies.removed.length)} dep.
                  </Badge>
                  <Badge variant="secondary">
                    {formatNumber(compare.data.symbols.added.length)} símb. novos
                  </Badge>
                </div>

                {/* ciclos novos/quebrados */}
                <div className="space-y-1.5">
                  {compare.data.cycles.new.length > 0 && (
                    <p className="flex items-center gap-2 text-xs text-amber-300">
                      <GitBranch className="h-3.5 w-3.5" />
                      {compare.data.cycles.new.length} ciclo
                      {compare.data.cycles.new.length === 1 ? '' : 's'} novo
                      {compare.data.cycles.new.length === 1 ? '' : 's'} desde a base
                    </p>
                  )}
                  {compare.data.cycles.broken.length > 0 && (
                    <p className="flex items-center gap-2 text-xs text-emerald-300">
                      <GitBranch className="h-3.5 w-3.5" />
                      {compare.data.cycles.broken.length} ciclo
                      {compare.data.cycles.broken.length === 1 ? '' : 's'} quebrado
                      {compare.data.cycles.broken.length === 1 ? '' : 's'} desde a base
                    </p>
                  )}
                  {compare.data.cycles.new.length === 0 &&
                    compare.data.cycles.broken.length === 0 && (
                      <p className="text-xs text-zinc-500">
                        {formatNumber(compare.data.cycles.unchanged)} ciclo(s)
                        inalterado(s) entre as análises.
                      </p>
                    )}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
