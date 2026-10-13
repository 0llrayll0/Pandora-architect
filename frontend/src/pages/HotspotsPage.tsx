import { Flame, Info } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/EmptyState'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useActiveRun } from '@/hooks/useActiveRun'
import { formatNumber, formatPercent } from '@/lib/format'
import { useHotspots } from '@/store/api'

/** Rótulos pt-BR para os componentes do score. */
const COMPONENT_LABELS: Record<string, string> = {
  complexity: 'Complexidade',
  degree: 'Grau',
  betweenness: 'Intermediação',
  outgoing: 'Dep. de saída',
}

const COMPONENT_ORDER = ['complexity', 'degree', 'betweenness', 'outgoing']

export function HotspotsPage({ projectId }: { projectId: number }) {
  const { runId } = useActiveRun(projectId)
  const { data, isLoading, error } = useHotspots(runId, 25)

  if (runId === null) {
    return (
      <EmptyState
        icon={<Flame className="h-8 w-8" />}
        title="Sem análise para exibir"
        description="Execute uma análise para ranquear os arquivos com maior complexidade e acoplamento."
      />
    )
  }

  if (isLoading) return <p className="text-sm text-zinc-500">Calculando hotspots…</p>

  if (error) {
    return (
      <EmptyState
        title="Falha ao carregar hotspots"
        description={error instanceof Error ? error.message : 'Erro inesperado.'}
      />
    )
  }

  if (!data || data.items.length === 0) {
    return (
      <EmptyState
        icon={<Flame className="h-8 w-8" />}
        title="Nenhum hotspot calculado"
        description="A run não tem arquivos elegíveis para o score de hotspots."
      />
    )
  }

  const weights = Object.entries(data.weights)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Hotspots</h1>
        <p className="text-sm text-zinc-500">
          {formatNumber(data.total)} arquivo
          {data.total === 1 ? '' : 's'} pontuado{data.total === 1 ? '' : 's'} · run #{runId}.
        </p>
      </div>

      {/* Nota honesta sobre o que o score é (e o que não é). */}
      <div className="flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3.5 py-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
        <p className="text-xs text-zinc-400">{data.note}</p>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm">Fórmula do score</CardTitle>
          {data.betweenness_estimated && (
            <Badge variant="warning">Intermediação estimada (amostrada)</Badge>
          )}
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {weights.map(([key, value]) => (
              <span
                key={key}
                className="rounded-md border border-zinc-800 bg-zinc-900/60 px-2.5 py-1 font-mono text-xs text-zinc-300"
              >
                {COMPONENT_LABELS[key] ?? key} = {value}
              </span>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-zinc-500">
            Cada componente é normalizado entre 0 e 1 antes do peso aplicado.
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-3">
        {data.items.map((item, index) => (
          <Card key={item.node_id}>
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-mono">
                <span className="text-zinc-500">#{index + 1}</span>
                <span className="text-zinc-200">{item.path}</span>
              </CardTitle>
              <span className="font-mono text-sm font-semibold text-violet-300">
                {item.score.toFixed(3)}
              </span>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* barra de score */}
              <div
                className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800"
                role="progressbar"
                aria-valuenow={Math.round(item.score * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`Score de ${item.path}`}
              >
                <div
                  className="h-full rounded-full bg-violet-500"
                  style={{ width: `${Math.min(100, item.score * 100)}%` }}
                />
              </div>

              {/* componentes individuais */}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {COMPONENT_ORDER.filter((key) => key in item.components).map((key) => (
                  <div key={key} className="rounded-md bg-zinc-900/60 px-2.5 py-1.5">
                    <p className="text-[10px] text-zinc-500">
                      {COMPONENT_LABELS[key] ?? key}
                    </p>
                    <p className="font-mono text-xs text-zinc-300">
                      {item.components[key].toFixed(2)}
                      <span className="text-zinc-600">
                        {' '}
                        · {formatPercent(item.components[key])}
                      </span>
                    </p>
                  </div>
                ))}
              </div>

              {/* valores brutos */}
              <p className="font-mono text-[11px] text-zinc-600">
                {'complexidade '}
                {item.raw.complexity ?? 0}
                {' · grau '}
                {item.raw.degree ?? 0}
                {' · saídas '}
                {item.raw.outgoing ?? 0}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
