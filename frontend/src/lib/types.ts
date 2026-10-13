/** Tipos espelhados dos schemas Pydantic do backend (backend/app/schemas.py + routers). */

export interface RunSummary {
  id: number
  project_id: number
  state: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  stage: string
  files_total: number
  files_processed: number
  files_failed: number
  symbols_count: number
  dependencies_count: number
  modules_count: number
  errors_count: number
  message: string
  error: string
  started_at: string | null
  finished_at: string | null
  created_at: string
}

/** Status de run com o campo extra `running` (GET /api/analysis/runs/{id}). */
export interface RunStatus extends RunSummary {
  running: boolean
}

export interface Project {
  id: number
  name: string
  path: string
  description: string
  extra_excluded_dirs: string[]
  extra_excluded_globs: string[]
  include_hidden: boolean
  created_at: string
  updated_at: string
  last_run: RunSummary | null
  run_count: number
}

export interface ProjectCreate {
  name?: string
  path: string
  description?: string
}

export interface RunSummaryPackage {
  run: RunStatus
  /** Métricas de projeto (scope=project) mapeadas por chave. */
  metrics: Record<string, number>
  files: { total: number; parse_errors: number }
  project: { id: number | null; name: string; path: string }
}

export type DependencyClassification = 'confirmed' | 'external' | 'unresolved'

export interface DependencyItem {
  id: number
  source_path: string
  source_module: string
  raw: string
  module: string
  level: number
  names: string[]
  target_path: string
  target_module: string
  classification: DependencyClassification
  confidence: number
}

export interface Paged<T> {
  total: number
  limit: number
  offset: number
  items: T[]
}

export interface CyclesPackage {
  available: boolean
  reason?: string
  cycles: string[][]
  count: number
  run_id?: number
  project_id?: number
  /** Detalhes por ciclo (caminho + confiança) — presente a partir da Fase 2. */
  details?: CycleDetail[]
  truncated?: boolean
  nodes_considered?: number
}

/** Nó de um ciclo no caminho completo. */
export interface CycleNode {
  id: string
  label: string
  type: string
  path: string
}

/** Aresta do caminho de um ciclo com classificação de confiança. */
export interface CyclePathEdge {
  source: string
  target: string
  classification: string
  label: string
  confidence: number
}

export interface CycleDetail {
  nodes: CycleNode[]
  path: CyclePathEdge[]
  size: number
  confidence: 'high' | 'low'
  min_edge_confidence: number
}

// ---------------------------------------------------------------------------
// Fase 2 — métricas do grafo, hotspots, histórico e comparação
// ---------------------------------------------------------------------------

export interface GraphTotals {
  nodes: number
  edges: number
  nodes_by_type: Record<string, number>
  edges_by_type: Record<string, number>
  density: number
  weak_components: number
  strong_components: number
  largest_scc: number
}

export interface DegreeEntry {
  id: string
  label: string
  type: string
  in_degree: number
  out_degree: number
  degree: number
  degree_centrality: number
}

export interface BetweennessEntry {
  id: string
  label: string
  value: number
}

/** Seção `graph` do endpoint /metrics. */
export interface GraphMetrics {
  totals: GraphTotals
  degrees: {
    top_in: DegreeEntry[]
    top_out: DegreeEntry[]
    top_total: DegreeEntry[]
    top_n: number
  }
  betweenness: {
    estimated: boolean
    sample_size: number
    exact_limit: number
    top: BetweennessEntry[]
  }
  coupling: CouplingRow[]
  coupling_summary: CouplingSummary
  complexity: PackageComplexity
  cycles: {
    available: boolean
    reason: string
    count: number
    truncated: boolean
    signatures: string[][]
  }
  computed_at: string
}

export interface CouplingRow {
  package: string
  ca: number
  ce: number
  instability: number
  modules: number
}

export interface CouplingSummary {
  packages: number
  coupled_packages: number
  avg_instability: number
}

export interface PackageComplexityRow {
  package: string
  symbols: number
  sum: number
  avg: number
  max: number
}

export interface PackageComplexity {
  by_package: PackageComplexityRow[]
  symbols: number
  total: number
  avg: number
  max: number
}

export interface MetricsPackage {
  project: Record<string, number>
  packages: Record<string, Record<string, number>>
  hotspots: { path: string; max_complexity: number }[]
  graph: GraphMetrics
}

export interface HotspotItem {
  path: string
  node_id: string
  score: number
  components: Record<string, number>
  raw: Record<string, number>
}

export interface HotspotsPackage {
  run_id: number
  note: string
  weights: Record<string, number>
  betweenness_estimated: boolean
  total: number
  limit: number
  items: HotspotItem[]
}

/** Resumo do grafo por análise no histórico. */
export interface AnalysisGraphSummary {
  nodes: number
  edges: number
  weak_components: number
  strong_components: number
  cycles: number
  avg_instability: number
  top_hotspot: HotspotItem | null
}

export interface AnalysisListItem extends RunSummary {
  graph: AnalysisGraphSummary | null
}

export interface AnalysesPackage {
  total: number
  items: AnalysisListItem[]
}

export interface MetricDelta {
  base: number | null
  target: number | null
  delta: number
}

export interface ModifiedFile {
  path: string
  base_sha256: string
  target_sha256: string
}

export interface ComparePackage {
  base: RunSummary
  target: RunSummary
  files: {
    added: string[]
    removed: string[]
    modified: ModifiedFile[]
    unchanged: number
  }
  symbols: { added: string[]; removed: string[] }
  dependencies: { added: string[]; removed: string[] }
  metrics: Record<string, MetricDelta>
  cycles: { new: string[][]; broken: string[][]; unchanged: number }
}

export interface ExplorerEntry {
  name: string
  path: string
  type: 'dir' | 'file'
  analyzed: boolean
  size_bytes?: number
}

export interface ExplorerTree {
  path: string
  root: string
  entries: ExplorerEntry[]
  analyzed_paths: number
}

export interface FileSymbol {
  name: string
  kind: string
  qualified_name: string
  lineno: number
  complexity: number
}

export interface ExplorerFile {
  path: string
  size_bytes: number
  truncated: boolean
  language: string
  parse_ok: boolean | null
  parse_error: string
  lines: number
  content: string
  symbols: FileSymbol[]
}

// ---------------------------------------------------------------------------
// Fase 3 — grafo de arquitetura (GET /api/graph/{run_id})
// ---------------------------------------------------------------------------

export type GraphNodeType = 'file' | 'module' | 'symbol' | 'external' | 'unresolved'
export type GraphEdgeType = 'contains' | 'imports'

/** Nó do grafo retornado por `GET /api/graph/{run_id}` (backend/app/analysis/graph.py). */
export interface GraphNode {
  id: string
  type: GraphNodeType | string
  label: string
  path?: string | null
  module?: string | null
  language?: string | null
  lines?: number | null
  parse_ok?: boolean | null
  /** symbol */
  kind?: string | null
  name?: string | null
  complexity?: number | null
  lineno?: number | null
}

export interface GraphEdge {
  source: string
  target: string
  type: GraphEdgeType | string
  label?: string | null
  classification?: string | null
  module?: string | null
  confidence?: number | null
}

export interface GraphCounts {
  nodes: number
  edges: number
  nodes_by_type: Record<string, number>
  edges_by_type: Record<string, number>
  density: number
  is_dag: boolean
}

export interface GraphPackage {
  nodes: GraphNode[]
  edges: GraphEdge[]
  counts: GraphCounts
  run_id: number
  project_id: number
}

export interface Health {
  status: string
  service: string
  version: string
  database: string
  python: string
  projects: number
}
