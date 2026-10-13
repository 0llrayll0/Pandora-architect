import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { EmptyState } from '@/components/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { useActiveRun } from '@/hooks/useActiveRun'
import { formatNumber, runStateLabel } from '@/lib/format'
import type { DependencyClassification, DependencyItem } from '@/lib/types'
import { useDependencies } from '@/store/api'

type Filter = DependencyClassification | 'all'

const FILTER_LABELS: Record<Filter, string> = {
  all: 'Todas',
  confirmed: 'Confirmadas',
  external: 'Externas',
  unresolved: 'Não resolvidas',
}

const CLASS_VARIANT: Record<DependencyClassification, 'success' | 'cyan' | 'warning'> = {
  confirmed: 'success',
  external: 'cyan',
  unresolved: 'warning',
}

function DependencyRow({ item }: { item: DependencyItem }) {
  return (
    <li className="grid grid-cols-1 gap-1 px-4 py-3 text-sm sm:grid-cols-[1fr_auto] sm:items-center sm:gap-3">
      <div className="min-w-0">
        <p className="truncate font-mono text-xs text-zinc-200">
          {item.source_module || item.source_path}
          <span className="text-zinc-600"> → </span>
          <span className="text-cyan-300">{item.raw}</span>
        </p>
        <p className="truncate text-[11px] text-zinc-500">
          {item.target_path || item.module}
          {item.names.length > 0 && ` · ${item.names.join(', ')}`}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={CLASS_VARIANT[item.classification]}>
          {FILTER_LABELS[item.classification as Filter] ?? item.classification}
        </Badge>
        <span className="w-10 text-right font-mono text-[11px] text-zinc-500">
          {Math.round(item.confidence * 100)}%
        </span>
      </div>
    </li>
  )
}

export function DependenciesPage({ projectId }: { projectId: number }) {
  const { runId, run } = useActiveRun(projectId)
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')

  const { data, isLoading } = useDependencies(runId, filter, '')

  // filtro de texto local (endpoint não expõe busca)
  const items = useMemo(() => {
    const list = data?.items ?? []
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter(
      (item) =>
        item.raw.toLowerCase().includes(q) ||
        item.source_module.toLowerCase().includes(q) ||
        item.source_path.toLowerCase().includes(q) ||
        item.target_path.toLowerCase().includes(q),
    )
  }, [data, search])

  if (runId === null) {
    return (
      <EmptyState
        title="Sem análise para exibir"
        description="Execute uma análise do projeto para descobrir as dependências entre módulos."
      />
    )
  }

  const total = data?.total ?? 0
  const shown = items.length
  const fetched = data?.items.length ?? 0

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Dependências</h1>
        <p className="text-sm text-zinc-500">
          Importações resolvidas da run #{runId}
          {run ? ` (${runStateLabel(run.state)})` : ''}.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filtrar por módulo, arquivo ou import…"
            className="pl-8"
            aria-label="Filtrar dependências"
          />
        </div>
        <Select
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          className="w-full sm:w-44"
          aria-label="Classificação"
        >
          {(Object.keys(FILTER_LABELS) as Filter[]).map((key) => (
            <option key={key} value={key}>
              {FILTER_LABELS[key]}
            </option>
          ))}
        </Select>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>
            {formatNumber(total)} dependência{total === 1 ? '' : 's'}
          </CardTitle>
          <span className="text-xs text-zinc-500">
            exibindo {formatNumber(shown)}
            {fetched < total ? ` de ${formatNumber(fetched)} carregadas` : ''}
          </span>
        </CardHeader>
        <CardContent className="px-0">
          {isLoading && <p className="px-4 pb-3 text-sm text-zinc-500">Carregando…</p>}

          {!isLoading && total === 0 && (
            <EmptyState
              className="m-4 border-0"
              title="Nenhuma dependência registrada"
              description="Esta análise não encontrou importações entre módulos."
            />
          )}

          {!isLoading && total > 0 && shown === 0 && (
            <EmptyState
              className="m-4 border-0"
              title="Nada corresponde ao filtro"
              description="Ajuste a busca ou a classificação para ver outros resultados."
            />
          )}

          {shown > 0 && (
            <ul className="divide-y divide-zinc-800/70">
              {items.map((item) => (
                <DependencyRow key={item.id} item={item} />
              ))}
            </ul>
          )}

          {fetched >= 200 && (
            <p className="px-4 pt-3 text-[11px] text-zinc-600">
              Mostrando os primeiros 200 registros — refine o filtro para reduzir o conjunto.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
