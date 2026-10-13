import dagre from '@dagrejs/dagre'
import type { Edge, Node } from '@xyflow/react'
import type { GraphPackage } from '@/lib/types'

/**
 * Transforma o payload real de `GET /api/graph/{run_id}` em nós/arestas do
 * React Flow. Nada é inventado: todo campo vem do backend; os nós de
 * diretório do modo overview são agrupamentos determinísticos dos `path`
 * reais dos arquivos.
 */

export type MapNodeKind =
  | 'directory'
  | 'file'
  | 'module'
  | 'symbol'
  | 'external'
  | 'unresolved'

/** Orientação do layout do dagre (horizontal ou vertical). */
export type MapLayoutDirection = 'LR' | 'TB'

export type MapNodeData = {
  label: string
  sublabel: string
  kind: MapNodeKind
  path: string
  module: string
  language: string
  lines: number | null
  complexity: number | null
  symbolKind: string
  lineno: number | null
  fileCount: number
  files: string[]
  inCycle: boolean
  inDegree: number
  outDegree: number
  matched: boolean
  dimmed: boolean
  /** Orientação aplicada no último layout (posiciona os handles do nó). */
  dir?: MapLayoutDirection
  /** Filhos realmente desenhados dentro de um nó de diretório (container). */
  shownChildren?: number
}

export type MapNode = Node<MapNodeData>

export type MapEdgeData = {
  label: string
  kind: string
  classification: string
  confidence: number | null
  count: number
  highlighted: boolean
  /** Aresta ligada a um resultado da busca (animação de fluxo). */
  searched: boolean
  dimmed: boolean
}

export type MapEdge = Edge<MapEdgeData>

/** Fallback quando `edge.data` está ausente (`Edge<T>` torna `data` opcional). */
export const EMPTY_EDGE_DATA: MapEdgeData = {
  label: '',
  kind: '',
  classification: '',
  confidence: null,
  count: 0,
  highlighted: false,
  searched: false,
  dimmed: false,
}

/** `edge.data` nunca undefined — use antes de ler/escrever campos da aresta. */
export function edgeDataOf(edge: MapEdge): MapEdgeData {
  return edge.data ?? EMPTY_EDGE_DATA
}

/** Ordem de exibição (e de corte progressivo) por tipo de nó. */
const KIND_ORDER: Record<MapNodeKind, number> = {
  directory: 0,
  module: 1,
  file: 2,
  external: 3,
  unresolved: 4,
  symbol: 5,
}

const KINDS = Object.keys(KIND_ORDER) as MapNodeKind[]

export const ALL_NODE_KINDS = KINDS

export function isMapNodeKind(value: string): value is MapNodeKind {
  return (KINDS as string[]).includes(value)
}

/** Diretório pai de um path ('' quando o arquivo está na raiz). */
export function dirnameOf(path: string): string {
  const index = path.lastIndexOf('/')
  return index === -1 ? '' : path.slice(0, index)
}

const ROOT_LABEL = '(raiz)'

/** Rótulo legível de um diretório. */
export function dirLabel(dir: string): string {
  return dir === '' ? ROOT_LABEL : dir
}

/** Último segmento de um path ('main.py' em 'app/main.py'). */
export function basenameOf(path: string): string {
  const index = path.lastIndexOf('/')
  return index === -1 ? path : path.slice(index + 1)
}

function emptyData(kind: MapNodeKind, label: string, sublabel: string): MapNodeData {
  return {
    label,
    sublabel,
    kind,
    path: '',
    module: '',
    language: '',
    lines: null,
    complexity: null,
    symbolKind: '',
    lineno: null,
    fileCount: 0,
    files: [],
    inCycle: false,
    inDegree: 0,
    outDegree: 0,
    matched: false,
    dimmed: false,
  }
}

/** Cria um nó React Flow sem posição (o layout atribui depois). */
function makeNode(id: string, data: MapNodeData): MapNode {
  // `type` controla qual componente de `nodeTypes` o React Flow renderiza
  // (registrado como `architecture` em ArchitectureMapCanvas).
  return { id, type: 'architecture', position: { x: 0, y: 0 }, data, draggable: true }
}

// ---------------------------------------------------------------------------
// Visão geral — só arquivos/módulos, agrupados por diretório
// ---------------------------------------------------------------------------

/**
 * Grafo da visão geral: arquivos agrupados em nós-container de diretório
 * (derivados dos `path` reais) + módulos/externos/não-resolvidos do payload.
 *
 * Cada container é um nó React Flow pai (`parentId`) e os arquivos viram
 * filhos posicionados dentro dele — a hierarquia de pastas fica legível de
 * relance. As arestas continuam agregadas no nível do diretório.
 */
export function buildOverviewGraph(pkg: GraphPackage): { nodes: MapNode[]; edges: MapEdge[] } {
  const dirFiles = new Map<string, string[]>()
  const dirLines = new Map<string, number>()
  const children: MapNode[] = []
  const nodes: MapNode[] = []

  for (const item of pkg.nodes) {
    if (item.type === 'file') {
      const path = item.path ?? ''
      const dir = dirnameOf(path)
      const list = dirFiles.get(dir) ?? []
      list.push(path)
      dirFiles.set(dir, list)
      dirLines.set(dir, (dirLines.get(dir) ?? 0) + (item.lines ?? 0))

      // filho do container: mesma fila usada para o cap do grid (ordem estável)
      const child = emptyData('file', basenameOf(path), '')
      child.path = path
      child.module = item.module ?? ''
      child.language = item.language ?? ''
      child.lines = item.lines ?? null
      child.complexity = item.complexity ?? null
      const parts: string[] = []
      if (child.lines !== null) parts.push(`${child.lines} lin`)
      if (child.language) parts.push(child.language)
      child.sublabel = parts.join(' · ')
      children.push({ ...makeNode(item.id, child), parentId: `dir:${dir}` })
    } else if (item.type === 'module' || item.type === 'external' || item.type === 'unresolved') {
      if (!isMapNodeKind(item.type)) continue
      nodes.push(makeNode(item.id, emptyData(item.type, item.label, item.module ?? '')))
    }
  }

  for (const [dir, files] of dirFiles) {
    const data = emptyData('directory', dirLabel(dir), `${files.length} arquivo${files.length === 1 ? '' : 's'}`)
    data.files = [...files].sort()
    data.fileCount = files.length
    data.lines = dirLines.get(dir) ?? 0
    data.path = dir
    nodes.push(makeNode(`dir:${dir}`, data))
  }

  // cap do grid: só os primeiros GROUP_CHILD_LIMIT arquivos por diretório
  // entram no container (fileCount continua o total real do payload)
  const childrenByParent = new Map<string, MapNode[]>()
  for (const child of children) {
    const parentId = child.parentId ?? ''
    const list = childrenByParent.get(parentId) ?? []
    list.push(child)
    childrenByParent.set(parentId, list)
  }
  const keptChildren: MapNode[] = []
  for (const list of childrenByParent.values()) {
    list.sort((a, b) => a.id.localeCompare(b.id))
    keptChildren.push(
      ...list.slice(0, GROUP_CHILD_LIMIT).map((child) => ({ ...child, extent: 'parent' as const })),
    )
  }

  nodes.push(...keptChildren)
  // ordenação determinística (o layout reemite containers antes dos filhos)
  nodes.sort((a, b) => a.id.localeCompare(b.id))
  const edges = aggregateOverviewEdges(pkg, nodes)
  return { nodes, edges }
}

/** Mapeia o endpoint de uma aresta do payload para o nó do modo overview. */
function overviewEndpoint(id: string): string | null {
  if (id.startsWith('file:')) return `dir:${dirnameOf(id.slice('file:'.length))}`
  if (id.startsWith('symbol:')) return null // símbolos não aparecem no overview
  return id
}

function aggregateOverviewEdges(pkg: GraphPackage, nodes: MapNode[]): MapEdge[] {
  const present = new Set(nodes.map((n) => n.id))
  const seen = new Map<string, MapEdge>()

  for (const dep of pkg.edges) {
    const source = overviewEndpoint(dep.source)
    const target = overviewEndpoint(dep.target)
    if (!source || !target || source === target) continue
    if (!present.has(source) || !present.has(target)) continue

    const key = `${source}>${target}`
    const existing = seen.get(key)
    if (existing) {
      if (existing.data) existing.data.count += 1
      continue
    }
    seen.set(key, {
      id: `${source}~${target}`,
      source,
      target,
      type: 'default',
      data: {
        label: dep.label ?? dep.type,
        kind: dep.type,
        classification: dep.classification ?? '',
        confidence: dep.confidence ?? null,
        count: 1,
        highlighted: false,
        searched: false,
        dimmed: false,
      },
    })
  }

  return [...seen.values()].sort((a, b) => a.id.localeCompare(b.id))
}

// ---------------------------------------------------------------------------
// Visão detalhada — todos os nós do payload
// ---------------------------------------------------------------------------

/** Grafo detalhado: todos os nós (arquivo/módulo/símbolo/externo/não-resolvido). */
export function buildDetailGraph(pkg: GraphPackage): { nodes: MapNode[]; edges: MapEdge[] } {
  const nodes: MapNode[] = pkg.nodes.map((item) => {
    const kind: MapNodeKind = isMapNodeKind(item.type) ? item.type : 'unresolved'
    const data = emptyData(kind, item.label, '')
    data.path = item.path ?? ''
    data.module = item.module ?? ''
    data.language = item.language ?? ''
    data.lines = item.lines ?? null
    data.complexity = item.complexity ?? null
    data.symbolKind = item.kind ?? ''
    data.lineno = item.lineno ?? null
    // sublabel secundária por tipo (tudo vindo de campos reais do payload)
    if (kind === 'file') data.sublabel = dirnameOf(data.path) || ROOT_LABEL
    else if (kind === 'symbol')
      data.sublabel = data.lineno !== null ? `linha ${data.lineno}` : data.module
    else data.sublabel = data.module
    return makeNode(item.id, data)
  })

  nodes.sort((a, b) => a.id.localeCompare(b.id))
  const present = new Set(nodes.map((n) => n.id))
  const edges: MapEdge[] = []

  for (const dep of pkg.edges) {
    if (!present.has(dep.source) || !present.has(dep.target)) continue
    edges.push({
      id: `${dep.source}~${dep.target}`,
      source: dep.source,
      target: dep.target,
      type: 'default',
      data: {
        label: dep.label ?? dep.type,
        kind: dep.type,
        classification: dep.classification ?? '',
        confidence: dep.confidence ?? null,
        count: 1,
        highlighted: false,
        searched: false,
        dimmed: false,
      },
    })
  }

  edges.sort((a, b) => a.id.localeCompare(b.id))
  return { nodes, edges }
}

// ---------------------------------------------------------------------------
// Filtros, graus, ciclos e destaque
// ---------------------------------------------------------------------------

export interface GraphFilter {
  kinds: Set<MapNodeKind>
  hideExternal: boolean
  search: string
}

/** Aplica filtros de tipo/busca e calcula graus, ciclos e matches. */
export function prepareGraph(
  nodes: MapNode[],
  edges: MapEdge[],
  filter: GraphFilter,
  cycleNodeIds: Set<string>,
): { nodes: MapNode[]; edges: MapEdge[]; totalNodes: number; totalEdges: number; matchedIds: string[] } {
  const term = filter.search.trim().toLowerCase()

  const matches = (data: MapNodeData): boolean =>
    term === '' ||
    data.label.toLowerCase().includes(term) ||
    data.sublabel.toLowerCase().includes(term) ||
    data.path.toLowerCase().includes(term)

  const kindVisible = (kind: MapNodeKind): boolean => {
    if (!filter.kinds.has(kind)) return false
    if (filter.hideExternal && (kind === 'external' || kind === 'unresolved')) return false
    return true
  }

  // 1) marca matches e aplica filtros de tipo
  const kept: MapNode[] = []
  const matchedIds: string[] = []
  const keptIds = new Set<string>()

  for (const node of nodes) {
    const data = node.data
    const matched = matches(data)
    if (matched) matchedIds.push(node.id)
    if (!kindVisible(data.kind)) continue
    kept.push({
      ...node,
      data: {
        ...data,
        matched: term !== '' && matched,
        dimmed: false,
        // nó participa de ciclo quando o arquivo que o originou participa
        inCycle:
          data.inCycle ||
          cycleNodeIds.has(node.id) ||
          (data.kind === 'directory' && data.files.some((f) => cycleNodeIds.has(`file:${f}`))),
      },
    })
    keptIds.add(node.id)
  }

  // 2) arestas entre nós mantidos
  const keptEdges = edges.filter((e) => keptIds.has(e.source) && keptIds.has(e.target))

  // 3) graus de entrada/saída (sobre o subgrafo filtrado)
  const inDegree = new Map<string, number>()
  const outDegree = new Map<string, number>()
  for (const edge of keptEdges) {
    outDegree.set(edge.source, (outDegree.get(edge.source) ?? 0) + 1)
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1)
  }

  const finalNodes = kept.map((node) => ({
    ...node,
    data: {
      ...node.data,
      inDegree: inDegree.get(node.id) ?? 0,
      outDegree: outDegree.get(node.id) ?? 0,
    },
  }))

  return {
    nodes: finalNodes,
    edges: keptEdges,
    totalNodes: nodes.length,
    totalEdges: edges.length,
    matchedIds: term === '' ? [] : matchedIds,
  }
}

/** Recorta o grafo para no máximo `limit` nós (carregamento progressivo). */
export function limitGraph(
  nodes: MapNode[],
  edges: MapEdge[],
  limit: number,
): { nodes: MapNode[]; edges: MapEdge[] } {
  if (nodes.length <= limit) return { nodes, edges }
  const order = (kind: MapNodeKind) => KIND_ORDER[kind]
  const ranked = [...nodes].sort((a, b) => {
    const ka = order(a.data.kind) - order(b.data.kind)
    return ka !== 0 ? ka : a.id.localeCompare(b.id)
  })
  const visible = new Set(ranked.slice(0, limit).map((n) => n.id))
  return {
    nodes: nodes.filter((n) => visible.has(n.id)),
    edges: edges.filter((e) => visible.has(e.source) && visible.has(e.target)),
  }
}

/**
 * Destaca as dependências de entrada/saída do nó selecionado: vizinhos e
 * arestas ligadas ficam vivos; o resto é esmaecido.
 */
export function highlightSelection(
  nodes: MapNode[],
  edges: MapEdge[],
  selectedId: string | null,
): { nodes: MapNode[]; edges: MapEdge[] } {
  if (!selectedId) {
    return {
      nodes: nodes.map((n) => ({ ...n, data: { ...n.data, dimmed: false } })),
      edges: edges.map((e) => ({
        ...e,
        data: { ...edgeDataOf(e), highlighted: false, dimmed: false },
      })),
    }
  }

  const related = new Set<string>([selectedId])
  const liveEdges = new Set<string>()
  for (const edge of edges) {
    if (edge.source === selectedId || edge.target === selectedId) {
      related.add(edge.source)
      related.add(edge.target)
      liveEdges.add(edge.id)
    }
  }

  return {
    nodes: nodes.map((n) => ({
      ...n,
      data: { ...n.data, dimmed: !related.has(n.id) },
    })),
    edges: edges.map((e) => ({
      ...e,
      data: {
        ...edgeDataOf(e),
        highlighted: liveEdges.has(e.id),
        dimmed: !liveEdges.has(e.id),
      },
    })),
  }
}

/**
 * Marca as arestas que tocam um resultado da busca: elas ganham animação de
 * fluxo para o caminho encontrado ficar evidente mesmo sem seleção.
 */
export function highlightSearch(edges: MapEdge[], matchedIds: string[]): MapEdge[] {
  const matched = new Set(matchedIds)
  return edges.map((e) => ({
    ...e,
    data: {
      ...edgeDataOf(e),
      searched: matched.size > 0 && (matched.has(e.source) || matched.has(e.target)),
    },
  }))
}

// ---------------------------------------------------------------------------
// Layout determinístico (dagre, com containers de diretório na visão geral)
// ---------------------------------------------------------------------------

/** Largura/altura base de um nó card. */
const NODE_WIDTH = 208
const NODE_HEIGHT = 78
const NODE_WIDTH_MAX = 264

/** Geometria dos filhos dentro de um container de diretório. */
const CHILD_WIDTH = 176
const CHILD_HEIGHT = 46
const CHILD_GAP = 10
const GROUP_PAD_X = 14
const GROUP_HEADER_HEIGHT = 46
const GROUP_PAD_BOTTOM = 14
const GROUP_OVERFLOW_HEIGHT = 22
const GROUP_MIN_WIDTH = 252
/** Máximo de arquivos desenhados dentro de um container (o resto fica no painel). */
export const GROUP_CHILD_LIMIT = 12

/** Altura do cabeçalho de um container — o grid de filhos começa abaixo dele. */
export const GROUP_HEADER_H = GROUP_HEADER_HEIGHT

/** Tamanho de um nó card; nós mais conectados ficam um pouco maiores. */
export function nodeSize(data: MapNodeData): { width: number; height: number } {
  const degree = data.inDegree + data.outDegree
  const extra = Math.min(NODE_WIDTH_MAX - NODE_WIDTH, Math.floor(degree / 2) * 8)
  return { width: NODE_WIDTH + extra, height: NODE_HEIGHT }
}

/** Colunas do grid de filhos de um container. */
function groupCols(shown: number): number {
  if (shown <= 1) return 1
  if (shown <= 4) return 2
  return 3
}

/** Tamanho de um container de diretório a partir dos filhos desenhados. */
export function groupSize(
  shown: number,
  overflow: boolean,
): { width: number; height: number; cols: number } {
  const cols = groupCols(shown)
  const rows = Math.ceil(shown / cols)
  const width = Math.max(
    GROUP_MIN_WIDTH,
    cols * CHILD_WIDTH + (cols - 1) * CHILD_GAP + GROUP_PAD_X * 2,
  )
  const height =
    GROUP_HEADER_HEIGHT +
    rows * CHILD_HEIGHT +
    Math.max(0, rows - 1) * CHILD_GAP +
    GROUP_PAD_BOTTOM +
    (overflow ? GROUP_OVERFLOW_HEIGHT : 0)
  return { width, height, cols }
}

/**
 * Posiciona os nós com dagre. Determinístico: entradas ordenadas por id.
 *
 * Suporta containers (`parentId`): os pais entram no dagre com o tamanho já
 * calculado a partir dos filhos, e os filhos são acomodados numa grade
 * dentro do pai. `rankdir` define a orientação do fluxo de dependências.
 */
export function layoutGraph(
  nodes: MapNode[],
  edges: MapEdge[],
  options: { rankdir?: MapLayoutDirection } = {},
): MapNode[] {
  if (nodes.length === 0) return nodes
  const rankdir: MapLayoutDirection = options.rankdir ?? 'LR'

  const byId = new Map(nodes.map((n) => [n.id, n]))
  const childrenOf = new Map<string, MapNode[]>()
  const roots: MapNode[] = []

  for (const node of nodes) {
    const parentId = node.parentId
    if (parentId && parentId !== node.id && byId.has(parentId)) {
      const list = childrenOf.get(parentId) ?? []
      list.push(node)
      childrenOf.set(parentId, list)
    } else {
      // pai filtrado/cortado: o filho vira um nó comum (sem órfão no React Flow)
      roots.push(
        parentId ? { ...node, parentId: undefined, extent: undefined } : node,
      )
    }
  }
  roots.sort((a, b) => a.id.localeCompare(b.id))

  const sizeOf = new Map<string, { width: number; height: number }>()
  const colsOf = new Map<string, number>()
  for (const root of roots) {
    const children = childrenOf.get(root.id)
    if (children && children.length > 0) {
      const group = groupSize(children.length, root.data.fileCount > children.length)
      sizeOf.set(root.id, { width: group.width, height: group.height })
      colsOf.set(root.id, group.cols)
    } else {
      sizeOf.set(root.id, nodeSize(root.data))
    }
  }

  const graph = new dagre.graphlib.Graph()
  graph.setDefaultEdgeLabel(() => ({}))
  graph.setGraph({
    rankdir,
    nodesep: 56,
    ranksep: rankdir === 'LR' ? 108 : 88,
    marginx: 48,
    marginy: 48,
  })

  for (const root of roots) {
    const size = sizeOf.get(root.id)
    if (size) graph.setNode(root.id, { width: size.width, height: size.height })
  }

  // aresta vira aresta do container quando um dos extremos é um filho
  const rootOf = (id: string): string => {
    if (sizeOf.has(id)) return id
    const parentId = byId.get(id)?.parentId
    return parentId && sizeOf.has(parentId) ? parentId : id
  }
  for (const edge of [...edges].sort((a, b) => a.id.localeCompare(b.id))) {
    const source = rootOf(edge.source)
    const target = rootOf(edge.target)
    if (source === target) continue
    if (graph.hasNode(source) && graph.hasNode(target)) graph.setEdge(source, target)
  }

  dagre.layout(graph)

  const result: MapNode[] = []
  for (const root of roots) {
    const size = sizeOf.get(root.id) ?? nodeSize(root.data)
    const pos = graph.node(root.id)
    const children = childrenOf.get(root.id) ?? []

    result.push({
      ...root,
      width: size.width,
      height: size.height,
      style: { width: size.width, height: size.height },
      data: { ...root.data, dir: rankdir, shownChildren: children.length },
      position: {
        x: (pos?.x ?? 0) - size.width / 2,
        y: (pos?.y ?? 0) - size.height / 2,
      },
    })

    if (children.length === 0) continue

    const cols = colsOf.get(root.id) ?? groupCols(children.length)
    const contentWidth = cols * CHILD_WIDTH + (cols - 1) * CHILD_GAP
    const offsetX = (size.width - contentWidth) / 2
    const sortedChildren = [...children].sort((a, b) => a.id.localeCompare(b.id))

    // container antes dos filhos na lista: os filhos são pintados por cima
    for (const [index, child] of sortedChildren.entries()) {
      result.push({
        ...child,
        width: CHILD_WIDTH,
        height: CHILD_HEIGHT,
        style: { width: CHILD_WIDTH, height: CHILD_HEIGHT },
        data: { ...child.data, dir: rankdir },
        position: {
          x: offsetX + (index % cols) * (CHILD_WIDTH + CHILD_GAP),
          y: GROUP_HEADER_HEIGHT + Math.floor(index / cols) * (CHILD_HEIGHT + CHILD_GAP),
        },
      })
    }
  }

  return result
}

/** Cores por tipo de nó, alinhadas ao tema violeta/ciano. */
export const KIND_STYLE: Record<MapNodeKind, { stroke: string; fill: string; dot: string }> = {
  directory: { stroke: '#7c3aed', fill: 'rgba(124,58,237,0.14)', dot: '#8b5cf6' },
  file: { stroke: '#8b5cf6', fill: 'rgba(139,92,246,0.10)', dot: '#a78bfa' },
  module: { stroke: '#22d3ee', fill: 'rgba(34,211,238,0.10)', dot: '#22d3ee' },
  symbol: { stroke: '#a78bfa', fill: 'rgba(167,139,250,0.08)', dot: '#c4b5fd' },
  external: { stroke: '#f59e0b', fill: 'rgba(245,158,11,0.08)', dot: '#fbbf24' },
  unresolved: { stroke: '#f43f5e', fill: 'rgba(244,63,94,0.08)', dot: '#fb7185' },
}

/** Rótulos legíveis dos tipos de nó. */
export const KIND_LABEL: Record<MapNodeKind, string> = {
  directory: 'Diretório',
  file: 'Arquivo',
  module: 'Módulo',
  symbol: 'Símbolo',
  external: 'Externo',
  unresolved: 'Não resolvido',
}

/** Cores por categoria de aresta (compartilhadas com a legenda). */
export const EDGE_STYLE = {
  imports: { stroke: '#22d3ee', label: 'imports' },
  contains: { stroke: '#52525b', label: 'contém' },
  external: { stroke: '#f59e0b', label: 'externo' },
  unresolved: { stroke: '#f43f5e', label: 'não resolvido' },
  highlighted: { stroke: '#67e8f9', label: 'destaque' },
} as const

/** Cor da aresta por tipo/classificação (imports confirmados em ciano). */
export function edgeColorOf(edge: MapEdge): string {
  const data = edgeDataOf(edge)
  if (data.kind === 'contains') return EDGE_STYLE.contains.stroke
  if (data.classification === 'external') return EDGE_STYLE.external.stroke
  if (data.classification === 'unresolved') return EDGE_STYLE.unresolved.stroke
  return EDGE_STYLE.imports.stroke
}
