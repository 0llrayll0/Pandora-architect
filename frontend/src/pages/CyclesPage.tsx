import { GitBranch } from 'lucide-react'
import { EmptyState } from '@/components/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useActiveRun } from '@/hooks/useActiveRun'
import { formatNumber } from '@/lib/format'
import type { CycleDetail, CyclesPackage } from '@/lib/types'
import { useCycles } from '@/store/api'

/** Mapa id de nó → label para exibir o caminho sem cruheid técnica. */
function labelMap(data: CyclesPackage): Map<string, string> {
  const map = new Map<string, string>()
  for (const detail of data.details ?? []) {
    for (const node of detail.nodes) map.set(node.id, node.label)
  }
  return map
}

/** Card de um ciclo: caminho completo + badge de confiança. */
function CycleCard({
  index,
  cycle,
  detail,
  labels,
}: {
  index: number
  cycle: string[]
  detail?: CycleDetail
  labels: Map<string, string>
}) {
  const confidence = detail?.confidence
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm">Ciclo {index + 1}</CardTitle>
        <div className="flex items-center gap-2">
          {confidence && (
            <Badge variant={confidence === 'high' ? 'success' : 'warning'}>
              {confidence === 'high' ? 'Confiança alta' : 'Confiança baixa'}
            </Badge>
          )}
          <Badge variant="danger">{cycle.length} módulos</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs">
          {cycle.map((node, i) => (
            <li key={`${node}-${i}`} className="flex items-center gap-2">
              <span className={i === 0 ? 'text-violet-300' : 'text-zinc-300'}>
                {labels.get(node) ?? node}
              </span>
              {i < cycle.length - 1 && (
                <span className="text-zinc-600" aria-hidden="true">
                  →
                </span>
              )}
            </li>
          ))}
          <li className="flex items-center gap-2" aria-hidden="true">
            <span className="text-zinc-600">→</span>
            <span className="text-violet-300">{labels.get(cycle[0]) ?? cycle[0]}</span>
          </li>
        </ol>

        {/* Caminho real com classificação de cada aresta (Fase 2). */}
        {detail && (
          <div className="rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-2">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
              Caminho de import
            </p>
            <ul className="space-y-1">
              {detail.path.map((edge, i) => (
                <li
                  key={`${edge.source}-${edge.target}-${i}`}
                  className="flex flex-wrap items-center gap-2 font-mono text-[11px]"
                >
                  <span className="text-zinc-400">{labels.get(edge.source) ?? edge.source}</span>
                  <span className="text-zinc-600">→</span>
                  <span className="text-zinc-400">{labels.get(edge.target) ?? edge.target}</span>
                  <span className="text-zinc-600">·</span>
                  <span className="text-zinc-500">{edge.label || 'import'}</span>
                  <Badge
                    variant={
                      edge.classification === 'confirmed' ? 'secondary' : 'outline'
                    }
                    className="text-[10px]"
                  >
                    {edge.classification} · {edge.confidence.toFixed(2)}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function CyclesPage({ projectId }: { projectId: number }) {
  const { runId } = useActiveRun(projectId)
  const { data, isLoading, error } = useCycles(runId)

  if (runId === null) {
    return (
      <EmptyState
        title="Sem análise para exibir"
        description="Execute uma análise para detectar ciclos de dependência entre módulos."
      />
    )
  }

  if (isLoading) {
    return <p className="text-sm text-zinc-500">Calculando ciclos…</p>
  }

  if (error) {
    return (
      <EmptyState
        title="Falha ao carregar ciclos"
        description={error instanceof Error ? error.message : 'Erro inesperado.'}
      />
    )
  }

  if (!data?.available) {
    return (
      <EmptyState
        icon={<GitBranch className="h-8 w-8" />}
        title="Grafo de ciclos indisponível"
        description={
          data?.reason ??
          'Os dados desta análise não permitem montar o grafo de dependências.'
        }
      />
    )
  }

  if (data.cycles.length === 0) {
    return (
      <EmptyState
        icon={<GitBranch className="h-8 w-8 text-emerald-500/60" />}
        title="Nenhum ciclo detectado"
        description="As dependências entre módulos deste repositório são acíclicas nesta análise."
      />
    )
  }

  const labels = labelMap(data)
  const detailsById = new Map(
    (data.details ?? []).map((detail, index) => [data.cycles[index]?.join('>'), detail]),
  )

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Ciclos de dependência</h1>
        <p className="text-sm text-zinc-500">
          {formatNumber(data.count)} ciclo{data.count === 1 ? '' : 's'} encontrado
          {data.count === 1 ? '' : 's'} na run #{runId}.
        </p>
      </div>

      {data.truncated && (
        <p className="rounded-md border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-xs text-amber-300">
          Lista truncada no limite configurado — pode haver mais ciclos no repositório.
        </p>
      )}

      <div className="grid gap-4">
        {data.cycles.map((cycle, index) => (
          <CycleCard
            key={`${cycle.join('>')}-${index}`}
            index={index}
            cycle={cycle}
            detail={detailsById.get(cycle.join('>'))}
            labels={labels}
          />
        ))}
      </div>
    </div>
  )
}
