import { useCallback } from 'react'
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiGet, apiSend, errorMessage } from '@/lib/api'
import type {
  AnalysesPackage,
  ComparePackage,
  CyclesPackage,
  DependencyClassification,
  DependencyItem,
  ExplorerFile,
  ExplorerTree,
  GraphPackage,
  Health,
  HotspotsPackage,
  MetricsPackage,
  Paged,
  Project,
  ProjectCreate,
  RunSummary,
  RunSummaryPackage,
} from '@/lib/types'

const KEY = {
  health: ['health'] as const,
  projects: ['projects'] as const,
  project: (id: number) => ['projects', id] as const,
  runs: (projectId: number) => ['projects', projectId, 'runs'] as const,
  summary: (runId: number) => ['runs', runId, 'summary'] as const,
  dependencies: (runId: number, classification: string, q: string) =>
    ['runs', runId, 'dependencies', classification, q] as const,
  cycles: (runId: number) => ['runs', runId, 'cycles'] as const,
  graph: (runId: number, includeSymbols: boolean) =>
    ['runs', runId, 'graph', includeSymbols ? 'symbols' : 'no-symbols'] as const,
  metrics: (runId: number) => ['runs', runId, 'metrics'] as const,
  hotspots: (runId: number, limit: number) => ['runs', runId, 'hotspots', limit] as const,
  analyses: (projectId: number) => ['projects', projectId, 'analyses'] as const,
  compare: (projectId: number, base: number, target: number) =>
    ['projects', projectId, 'compare', base, target] as const,
  explorer: (projectId: number, path: string, depth: number) =>
    ['projects', projectId, 'explorer', path, depth] as const,
  explorerFile: (projectId: number, path: string) =>
    ['projects', projectId, 'explorer-file', path] as const,
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useHealth() {
  return useQuery({
    queryKey: KEY.health,
    queryFn: () => apiGet<Health>('/api/health'),
    refetchInterval: 30_000,
  })
}

export function useProjects() {
  return useQuery({
    queryKey: KEY.projects,
    queryFn: () => apiGet<Project[]>('/api/projects'),
  })
}

export function useProjectRuns(projectId: number | null) {
  return useQuery({
    queryKey: KEY.runs(projectId ?? 0),
    queryFn: () => apiGet<RunSummary[]>(`/api/projects/${projectId}/runs`),
    enabled: projectId !== null,
  })
}

export function useRunSummary(runId: number | null) {
  return useQuery({
    queryKey: KEY.summary(runId ?? 0),
    queryFn: () => apiGet<RunSummaryPackage>(`/api/analysis/runs/${runId}/summary`),
    enabled: runId !== null,
  })
}

export function useDependencies(
  runId: number | null,
  classification: DependencyClassification | 'all',
  search: string,
) {
  const params = new URLSearchParams({ limit: '200' })
  if (classification !== 'all') params.set('classification', classification)
  return useQuery({
    queryKey: KEY.dependencies(runId ?? 0, classification, search),
    queryFn: () =>
      apiGet<Paged<DependencyItem>>(
        `/api/analysis/runs/${runId}/dependencies?${params.toString()}`,
      ),
    enabled: runId !== null,
  })
}

export function useCycles(runId: number | null) {
  return useQuery({
    queryKey: KEY.cycles(runId ?? 0),
    queryFn: () => apiGet<CyclesPackage>(`/api/graph/${runId}/cycles`),
    enabled: runId !== null,
  })
}

/** Grafo de arquitetura da run (nós/arestas com tipos do backend). */
export function useGraph(runId: number | null, includeSymbols: boolean) {
  return useQuery({
    queryKey: KEY.graph(runId ?? 0, includeSymbols),
    queryFn: () =>
      apiGet<GraphPackage>(
        `/api/graph/${runId}?include_symbols=${includeSymbols ? 'true' : 'false'}`,
      ),
    enabled: runId !== null,
    staleTime: 60_000,
    // mantém o grafo anterior visível durante a troca de visão/símbolos
    // (evita o flash do estado de loading a cada toggle)
    placeholderData: keepPreviousData,
  })
}

/** Métricas persistidas da run, incluindo a seção `graph` (Fase 2). */
export function useRunMetrics(runId: number | null) {
  return useQuery({
    queryKey: KEY.metrics(runId ?? 0),
    queryFn: () => apiGet<MetricsPackage>(`/api/analysis/runs/${runId}/metrics`),
    enabled: runId !== null,
  })
}

/** Hotspots explicáveis (score + componentes + pesos) da run. */
export function useHotspots(runId: number | null, limit = 25) {
  return useQuery({
    queryKey: KEY.hotspots(runId ?? 0, limit),
    queryFn: () =>
      apiGet<HotspotsPackage>(`/api/analysis/runs/${runId}/hotspots?limit=${limit}`),
    enabled: runId !== null,
  })
}

/** Histórico de análises do projeto com resumo do grafo. */
export function useAnalyses(projectId: number | null) {
  return useQuery({
    queryKey: KEY.analyses(projectId ?? 0),
    queryFn: () => apiGet<AnalysesPackage>(`/api/projects/${projectId}/analyses`),
    enabled: projectId !== null,
  })
}

/** Diff entre duas runs do mesmo projeto. */
export function useCompare(
  projectId: number | null,
  base: number | null,
  target: number | null,
) {
  const enabled = projectId !== null && base !== null && target !== null && base !== target
  return useQuery({
    queryKey: KEY.compare(projectId ?? 0, base ?? 0, target ?? 0),
    queryFn: () =>
      apiGet<ComparePackage>(
        `/api/projects/${projectId}/compare?base=${base}&target=${target}`,
      ),
    enabled,
  })
}

export function useExplorerTree(
  projectId: number | null,
  path: string,
  depth: number,
) {
  // O backend espera caminho RELATIVO à raiz (raiz = string vazia).
  // Remove barra inicial (nunca enviar caminho absoluto), colapsa "//",
  // remove barra final; "/" ou vazio vira "" — evita 403 path_not_allowed.
  const normalizedPath =
    path.replace(/^\/+/, '').replace(/\/+$/, '').replace(/\/{2,}/g, '/') || ''
  const params = new URLSearchParams({ path: normalizedPath, depth: String(depth) })
  return useQuery({
    queryKey: KEY.explorer(projectId ?? 0, normalizedPath, depth),
    queryFn: () =>
      apiGet<ExplorerTree>(`/api/projects/${projectId}/explorer?${params.toString()}`),
    enabled: projectId !== null,
  })
}

export function useExplorerFile(projectId: number | null, path: string | null) {
  return useQuery({
    queryKey: KEY.explorerFile(projectId ?? 0, path ?? ''),
    queryFn: () =>
      apiGet<ExplorerFile>(
        `/api/projects/${projectId}/explorer/file?path=${encodeURIComponent(path ?? '')}`,
      ),
    enabled: projectId !== null && path !== null && path !== '',
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProjectCreate) =>
      apiSend<Project>('POST', '/api/projects', payload),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: KEY.projects })
      toast.success(`Projeto "${project.name}" adicionado.`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiSend<void>('DELETE', `/api/projects/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEY.projects })
      toast.success('Projeto removido do Pandora. Nenhum arquivo foi apagado.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}

export function useAnalyzeProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (projectId: number) =>
      apiSend<RunSummary>('POST', `/api/projects/${projectId}/analyze`, {}),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: KEY.projects })
      queryClient.invalidateQueries({ queryKey: KEY.runs(run.project_id) })
      toast.info(`Análise #${run.id} iniciada.`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
}

/**
 * Invalida tudo que depende de uma run (após conclusão via SSE).
 *
 * `useCallback` com `[queryClient]` garante referência ESTÁVEL entre renders:
 * sem isso a função nova a cada render recriava o `useEffect` de
 * `useRunProgress` → `EventSource` reabria → `onerror` → invalidate → loop.
 */
export function useInvalidateRunData() {
  const queryClient = useQueryClient()
  return useCallback(
    (runId: number, projectId: number) => {
      void queryClient.invalidateQueries({ queryKey: KEY.projects })
      void queryClient.invalidateQueries({ queryKey: ['runs', runId] })
      void queryClient.invalidateQueries({ queryKey: KEY.runs(projectId) })
    },
    [queryClient],
  )
}
