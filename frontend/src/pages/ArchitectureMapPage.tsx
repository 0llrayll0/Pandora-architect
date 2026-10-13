import { useEffect, useMemo, useState } from 'react'
import {
  Eye,
  EyeOff,
  Map as MapIcon,
  Maximize2,
  MoveHorizontal,
  MoveVertical,
  RotateCcw,
  Search,
  Target,
  X,
  type LucideIcon,
} from 'lucide-react'
import { ArchitectureMapCanvas } from '@/components/map/ArchitectureMapCanvas'
import { MapSkeleton } from '@/components/map/MapSkeleton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/EmptyState'
import { useActiveRun } from '@/hooks/useActiveRun'
import {
  ALL_NODE_KINDS,
  KIND_LABEL,
  buildDetailGraph,
  buildOverviewGraph,
  highlightSearch,
  highlightSelection,
  layoutGraph,
  limitGraph,
  prepareGraph,
  type MapEdge,
  type MapLayoutDirection,
  type MapNode,
  type MapNodeKind,
} from '@/lib/graphTransform'
import { formatNumber } from '@/lib/format'
import { useCycles, useGraph } from '@/store/api'

type ViewMode = 'overview' | 'detail'

const PAGE_LIMIT = 250
const PAGE_STEP = 250

/** Orientação padrão do fluxo por visão (vertical agrupa melhor pastas). */
const DEFAULT_RANKDIR: Record<ViewMode, MapLayoutDirection> = {
  overview: 'TB',
  detail: 'LR',
}

/** Opções do seletor de direção do fluxo. */
const DIRECTIONS: { value: MapLayoutDirection; label: string; Icon: LucideIcon }[] = [
  { value: 'LR', label: 'Horizontal', Icon: MoveHorizontal },
  { value: 'TB', label: 'Vertical', Icon: MoveVertical },
]

/** Painel contextual com os dados reais do nó selecionado. */
function NodePanel({
  node,
  edges,
  nodeLabel,
  onClose,
}: {
  node: MapNode
  edges: MapEdge[]
  nodeLabel: (id: string) => string
  onClose: () => void
}) {
  const data = node.data
  const outgoing = edges.filter((e) => e.source === node.id)
  const incoming = edges.filter((e) => e.target === node.id)

  return (
    <Card className="lg:w-80 lg:shrink-0">
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
        <div className="min-w-0 space-y-1">
          <CardTitle className="break-words text-sm">{data.label}</CardTitle>
          <p className="font-mono text-[11px] text-zinc-500">{data.sublabel || '—'}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={onClose}
          aria-label="Fechar painel do nó"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Tipo</dt>
            <dd>
              <Badge variant="secondary" className="mt-0.5">
                {KIND_LABEL[data.kind]}
              </Badge>
            </dd>
          </div>
          {data.inDegree + data.outDegree > 0 && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Relações</dt>
              <dd className="text-zinc-300">
                {data.outDegree} saída · {data.inDegree} entrada
              </dd>
            </div>
          )}
        </dl>

        <dl className="space-y-1.5">
          {data.path && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Caminho</dt>
              <dd className="break-all font-mono text-[11px] text-zinc-300">{data.path}</dd>
            </div>
          )}
          {data.module && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Módulo</dt>
              <dd className="break-all font-mono text-[11px] text-zinc-300">{data.module}</dd>
            </div>
          )}
          {data.language && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Linguagem</dt>
              <dd className="text-zinc-300">{data.language}</dd>
            </div>
          )}
          {data.lines !== null && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Linhas</dt>
              <dd className="text-zinc-300">{formatNumber(data.lines)}</dd>
            </div>
          )}
          {data.complexity !== null && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Complexidade</dt>
              <dd className="text-zinc-300">{data.complexity}</dd>
            </div>
          )}
          {data.fileCount > 0 && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Arquivos</dt>
              <dd className="text-zinc-300">{data.fileCount}</dd>
            </div>
          )}
          {data.inCycle && (
            <div>
              <dt className="text-[10px] uppercase tracking-wider text-zinc-600">Ciclo</dt>
              <dd>
                <Badge variant="danger">Participa de ciclo</Badge>
              </dd>
            </div>
          )}
        </dl>

        {data.files.length > 0 && (
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wider text-zinc-600">
              Arquivos no diretório
            </p>
            <ul className="max-h-40 space-y-0.5 overflow-y-auto">
              {data.files.slice(0, 30).map((file) => (
                <li key={file} className="truncate font-mono text-[11px] text-zinc-400" title={file}>
                  {file}
                </li>
              ))}
              {data.files.length > 30 && (
                <li className="text-[11px] text-zinc-600">+ {data.files.length - 30} outros…</li>
              )}
            </ul>
          </div>
        )}

        {(outgoing.length > 0 || incoming.length > 0) && (
          <div className="space-y-2">
            {outgoing.length > 0 && (
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wider text-zinc-600">
                  sai para ({outgoing.length})
                </p>
                <ul className="space-y-0.5">
                  {outgoing.slice(0, 8).map((edge) => (
                    <li key={edge.id} className="truncate text-[11px] text-cyan-300/80">
                      → {nodeLabel(edge.target)}
                    </li>
                  ))}
                  {outgoing.length > 8 && (
                    <li className="text-[11px] text-zinc-600">+ {outgoing.length - 8}…</li>
                  )}
                </ul>
              </div>
            )}
            {incoming.length > 0 && (
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wider text-zinc-600">
                  vem de ({incoming.length})
                </p>
                <ul className="space-y-0.5">
                  {incoming.slice(0, 8).map((edge) => (
                    <li key={edge.id} className="truncate text-[11px] text-violet-300/80">
                      ← {nodeLabel(edge.source)}
                    </li>
                  ))}
                  {incoming.length > 8 && (
                    <li className="text-[11px] text-zinc-600">+ {incoming.length - 8}…</li>
                  )}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function FilterChip({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        active
          ? 'rounded-full border border-violet-500/40 bg-violet-500/15 px-2.5 py-0.5 text-[11px] font-medium text-violet-200 transition-colors hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:outline-none'
          : 'rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-0.5 text-[11px] text-zinc-500 transition-colors hover:border-zinc-700 hover:text-zinc-300 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:outline-none'
      }
    >
      {label}
    </button>
  )
}

/** Mapa da Arquitetura interativo (React Flow) sobre o grafo real da run. */
export function ArchitectureMapPage({ projectId }: { projectId: number }) {
  const { runId } = useActiveRun(projectId)
  const [viewMode, setViewMode] = useState<ViewMode>('overview')
  const [kinds, setKinds] = useState<Set<MapNodeKind>>(() => new Set(ALL_NODE_KINDS))
  const [hideExternal, setHideExternal] = useState(false)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [limit, setLimit] = useState(PAGE_LIMIT)
  const [focus, setFocus] = useState<{ id: string; nonce: number } | null>(null)
  const [rankdir, setRankdir] = useState<MapLayoutDirection>(DEFAULT_RANKDIR.overview)
  const [fitNonce, setFitNonce] = useState(0)

  // símbolos só existem no payload detalhado (e são opcionais por lá)
  const includeSymbols = viewMode === 'detail' && kinds.has('symbol')
  const graphQuery = useGraph(runId, includeSymbols)
  const cyclesQuery = useCycles(runId)

  const refit = () => setFitNonce((n) => n + 1)

  // debounce da busca (150ms)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 150)
    return () => clearTimeout(timer)
  }, [search])

  // reseta paginação/seleção/direção ao trocar de modo ou run
  useEffect(() => {
    setLimit(PAGE_LIMIT)
    setSelectedId(null)
    setRankdir(DEFAULT_RANKDIR[viewMode])
    setFitNonce((n) => n + 1)
  }, [viewMode, runId])

  const cycleNodeIds = useMemo(() => {
    const set = new Set<string>()
    for (const cycle of cyclesQuery.data?.cycles ?? []) {
      for (const id of cycle) set.add(id)
    }
    return set
  }, [cyclesQuery.data])

  /** Grafo bruto do modo atual, a partir do payload real. */
  const baseGraph = useMemo(() => {
    if (!graphQuery.data) return { nodes: [] as MapNode[], edges: [] as MapEdge[] }
    return viewMode === 'overview'
      ? buildOverviewGraph(graphQuery.data)
      : buildDetailGraph(graphQuery.data)
  }, [graphQuery.data, viewMode])

  /** Filtro + graus + matches, antes do corte progressivo. */
  const prepared = useMemo(
    () =>
      prepareGraph(
        baseGraph.nodes,
        baseGraph.edges,
        { kinds, hideExternal, search: debouncedSearch },
        cycleNodeIds,
      ),
    [baseGraph, kinds, hideExternal, debouncedSearch, cycleNodeIds],
  )

  /** Corte progressivo + layout na direção escolhida + destaques + busca. */
  const { nodes, edges } = useMemo(() => {
    const limited = limitGraph(prepared.nodes, prepared.edges, limit)
    const laidOut = layoutGraph(limited.nodes, limited.edges, { rankdir })
    const selected = highlightSelection(laidOut, limited.edges, selectedId)
    return {
      nodes: selected.nodes,
      edges: highlightSearch(selected.edges, prepared.matchedIds),
    }
  }, [prepared, limit, selectedId, rankdir])

  const nodeLabel = useMemo(() => {
    const labels = new Map<string, string>()
    for (const node of prepared.nodes) labels.set(node.id, node.data.label)
    return (id: string) => labels.get(id) ?? id
  }, [prepared])

  const selectedNode = useMemo(
    () => prepared.nodes.find((n) => n.id === selectedId) ?? null,
    [prepared, selectedId],
  )

  const hiddenCount = prepared.totalNodes - prepared.nodes.length
  const truncated = prepared.nodes.length > limit
  const remaining = prepared.nodes.length - nodes.length

  const toggleKind = (kind: MapNodeKind) => {
    setKinds((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  const centerOnMatch = () => {
    const first = prepared.matchedIds[0]
    if (!first) return
    setSelectedId(first)
    setFocus({ id: first, nonce: Date.now() })
  }

  // -----------------------------------------------------------------------
  // Estados
  // -----------------------------------------------------------------------

  if (runId === null) {
    return (
      <EmptyState
        icon={<MapIcon className="h-8 w-8" />}
        title="Sem análise para exibir"
        description="Execute uma análise do projeto para visualizar o mapa de arquitetura real do repositório."
      />
    )
  }

  if (graphQuery.isLoading && !graphQuery.data) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Mapa da Arquitetura</h1>
          <p className="text-sm text-zinc-500">Run #{runId} · montando o grafo…</p>
        </div>
        <div className="h-[65vh] min-h-[420px] overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/60">
          <MapSkeleton />
        </div>
      </div>
    )
  }

  if (graphQuery.error) {
    return (
      <EmptyState
        title="Falha ao carregar o grafo"
        description={
          graphQuery.error instanceof Error
            ? graphQuery.error.message
            : 'Erro inesperado ao consultar /api/graph.'
        }
      />
    )
  }

  if (!graphQuery.data || graphQuery.data.counts.nodes === 0) {
    return (
      <EmptyState
        icon={<MapIcon className="h-8 w-8" />}
        title="Grafo vazio"
        description="A run selecionada não contém nós de grafo (arquivos, módulos ou símbolos). Execute uma análise nova."
      />
    )
  }

  const counts = graphQuery.data.counts
  // `symbol` sai dos chips (virou toggle da barra) e `file` não aparece no
  // overview (os arquivos estão dentro dos containers de diretório)
  const visibleKinds = ALL_NODE_KINDS.filter(
    (kind) => kind !== 'symbol' && !(viewMode === 'overview' && kind === 'file'),
  )
  const clearFilters = () => {
    setSearch('')
    setDebouncedSearch('')
    setKinds(new Set(ALL_NODE_KINDS))
    setHideExternal(false)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Mapa da Arquitetura</h1>
          <p className="text-sm text-zinc-500">
            {formatNumber(counts.nodes)} nós · {formatNumber(counts.edges)} arestas · densidade{' '}
            {counts.density.toFixed(3)} · run #{runId}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Nós/arestas efetivamente no mapa */}
          <span className="rounded-md border border-zinc-800 bg-zinc-900/60 px-2 py-1 font-mono text-[11px] text-zinc-400">
            {nodes.length} nós · {edges.length} arestas
          </span>

          {/* Alternância de visão */}
          <div
            className="inline-flex rounded-md border border-zinc-800 bg-zinc-900/60 p-0.5"
            role="group"
            aria-label="Modo de visualização"
          >
            {(['overview', 'detail'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                aria-pressed={viewMode === mode}
                className={
                  viewMode === mode
                    ? 'rounded bg-violet-500/20 px-3 py-1 text-xs font-medium text-violet-200 transition-colors focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:outline-none'
                    : 'rounded px-3 py-1 text-xs text-zinc-500 transition-colors hover:text-zinc-300 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:outline-none'
                }
              >
                {mode === 'overview' ? 'Visão geral' : 'Detalhada'}
              </button>
            ))}
          </div>

          {/* Direção do fluxo de dependências */}
          <div
            className="inline-flex rounded-md border border-zinc-800 bg-zinc-900/60 p-0.5"
            role="group"
            aria-label="Direção do fluxo"
          >
            {DIRECTIONS.map(({ value, label, Icon }) => (
              <button
                key={value}
                type="button"
                onClick={() => setRankdir(value)}
                aria-pressed={rankdir === value}
                title={`Fluxo ${label.toLowerCase()}`}
                className={
                  rankdir === value
                    ? 'inline-flex items-center gap-1 rounded bg-cyan-500/15 px-2 py-1 text-xs font-medium text-cyan-200 transition-colors focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:outline-none'
                    : 'inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-zinc-500 transition-colors hover:text-zinc-300 focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:outline-none'
                }
              >
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>

          <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={refit}>
            <Maximize2 className="mr-1 h-3 w-3" />
            Ajustar
          </Button>
        </div>
      </div>

      {/* Busca + filtros */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500"
            aria-hidden="true"
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar arquivo, módulo ou símbolo…"
            className="h-8 pl-8 text-xs"
            aria-label="Buscar nó no grafo"
          />
        </div>

        {debouncedSearch.trim() !== '' && (
          <>
            <span className="text-[11px] text-zinc-500">
              {prepared.matchedIds.length} resultado
              {prepared.matchedIds.length === 1 ? '' : 's'}
            </span>
            <Button
              variant="secondary"
              size="sm"
              className="h-7 text-xs"
              onClick={centerOnMatch}
              disabled={prepared.matchedIds.length === 0}
            >
              <Target className="mr-1 h-3 w-3" />
              Centralizar
            </Button>
          </>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {visibleKinds.map((kind) => (
            <FilterChip
              key={kind}
              label={KIND_LABEL[kind]}
              active={kinds.has(kind)}
              onClick={() => toggleKind(kind)}
            />
          ))}

          {/* Símbolos: só existe no payload detalhado */}
          {viewMode === 'detail' && (
            <button
              type="button"
              onClick={() => toggleKind('symbol')}
              aria-pressed={kinds.has('symbol')}
              className="inline-flex items-center gap-1 rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-0.5 text-[11px] text-zinc-400 transition-colors hover:border-zinc-700 hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:outline-none"
            >
              {kinds.has('symbol') ? (
                <Eye className="h-3 w-3" />
              ) : (
                <EyeOff className="h-3 w-3" />
              )}
              Símbolos
            </button>
          )}

          <button
            type="button"
            onClick={() => setHideExternal((v) => !v)}
            aria-pressed={hideExternal}
            className="inline-flex items-center gap-1 rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-0.5 text-[11px] text-zinc-400 transition-colors hover:border-zinc-700 hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:outline-none"
          >
            {hideExternal ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
            Ocultar externos
          </button>
        </div>
      </div>

      {/* Aviso de ciclos */}
      {cyclesQuery.data && cyclesQuery.data.count > 0 && (
        <p className="rounded-md border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-xs text-rose-300">
          {cyclesQuery.data.count} ciclo{cyclesQuery.data.count === 1 ? '' : 's'} de importação
          detectado{cyclesQuery.data.count === 1 ? '' : 's'} — nós em ciclo aparecem com borda
          vermelha.
        </p>
      )}

      {/* Canvas + painel */}
      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="h-[65vh] min-h-[420px] flex-1 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/60">
          {nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center p-6 text-center">
              <EmptyState
                title="Nenhum nó com os filtros atuais"
                description="Reative ao menos um tipo de nó ou limpe a busca para ver o grafo."
                action={
                  <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={clearFilters}>
                    <RotateCcw className="mr-1 h-3 w-3" />
                    Limpar filtros
                  </Button>
                }
              />
            </div>
          ) : (
            <ArchitectureMapCanvas
              nodes={nodes}
              edges={edges}
              onNodeClick={(id) => setSelectedId(id)}
              onPaneClick={() => setSelectedId(null)}
              focus={focus}
              fitNonce={fitNonce}
            />
          )}
        </div>

        {selectedNode && (
          <NodePanel
            node={selectedNode}
            edges={edges}
            nodeLabel={nodeLabel}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>

      {/* Rodapé: paginação progressiva */}
      {(truncated || remaining > 0 || hiddenCount > 0) && (
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-500">
          <span>
            Exibindo {formatNumber(nodes.length)} de {formatNumber(prepared.nodes.length)} nós
            {viewMode === 'overview' ? ' (visão geral)' : ' (detalhada)'}.
          </span>
          {hiddenCount > 0 && (
            <span>{formatNumber(hiddenCount)} ocultos pelos filtros de tipo.</span>
          )}
          {(truncated || remaining > 0) && (
            <Button
              variant="secondary"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setLimit((l) => l + PAGE_STEP)}
            >
              Carregar mais {Math.min(PAGE_STEP, remaining)} nós
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
