import { useState } from 'react'
import {
  ChevronLeft,
  ChevronUp,
  FileCode2,
  Folder,
  FolderOpen,
  Loader2,
} from 'lucide-react'
import { EmptyState } from '@/components/EmptyState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { formatBytes, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useExplorerFile, useExplorerTree } from '@/store/api'

/** Caminho relativo à raiz do projeto; a raiz é a string vazia "". */
function parentPath(path: string): string {
  const normalized = path.replace(/\/+$/, '')
  const idx = normalized.lastIndexOf('/')
  return idx <= 0 ? '' : normalized.slice(0, idx)
}

/** Árvore de diretórios: navega por `currentPath`, seleciona arquivos. */
function TreePanel({
  projectId,
  currentPath,
  selectedFile,
  onNavigate,
  onSelectFile,
}: {
  projectId: number
  currentPath: string
  selectedFile: string | null
  onNavigate: (path: string) => void
  onSelectFile: (path: string) => void
}) {
  const { data, isLoading, error } = useExplorerTree(projectId, currentPath, 1)

  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Folder className="h-4 w-4 text-cyan-400" />
          Estrutura
        </CardTitle>
        <CardDescription className="truncate font-mono text-[11px]">
          {data?.path || '/'}
        </CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {isLoading && (
          <p className="flex items-center gap-2 px-2 py-3 text-xs text-zinc-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Carregando…
          </p>
        )}
        {error && (
          <p className="px-2 py-3 text-xs text-rose-400">
            {error instanceof Error ? error.message : 'Erro ao listar diretório.'}
          </p>
        )}

        {data && (
          <ul className="space-y-0.5 text-sm">
            {currentPath !== '' && (
              <li>
                <button
                  type="button"
                  onClick={() => onNavigate(parentPath(currentPath))}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200"
                >
                  <ChevronUp className="h-3.5 w-3.5" />
                  <span className="truncate">..</span>
                </button>
              </li>
            )}
            {data.entries.length === 0 && (
              <li className="px-2 py-3 text-xs text-zinc-500">Diretório vazio.</li>
            )}
            {data.entries.map((entry) =>
              entry.type === 'dir' ? (
                <li key={entry.path}>
                  <button
                    type="button"
                    onClick={() => onNavigate(entry.path)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-zinc-800/60',
                      entry.analyzed ? 'text-zinc-200' : 'text-zinc-500',
                    )}
                    title={entry.path}
                  >
                    <FolderOpen className="h-3.5 w-3.5 shrink-0 text-cyan-500/70" />
                    <span className="truncate">{entry.name}</span>
                  </button>
                </li>
              ) : (
                <li key={entry.path}>
                  <button
                    type="button"
                    onClick={() => onSelectFile(entry.path)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded px-2 py-1.5 pl-6 text-left hover:bg-zinc-800/60',
                      selectedFile === entry.path
                        ? 'bg-violet-500/15 text-violet-200 ring-1 ring-inset ring-violet-500/30'
                        : entry.analyzed
                          ? 'text-zinc-300'
                          : 'text-zinc-600',
                    )}
                    title={entry.path}
                  >
                    <FileCode2 className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{entry.name}</span>
                    {entry.size_bytes !== undefined && (
                      <span className="ml-auto shrink-0 font-mono text-[10px] text-zinc-600">
                        {formatBytes(entry.size_bytes)}
                      </span>
                    )}
                  </button>
                </li>
              ),
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/** Visualizador: conteúdo do arquivo + símbolos detectados. */
function FileViewer({ projectId, filePath }: { projectId: number; filePath: string | null }) {
  const { data, isLoading, error } = useExplorerFile(projectId, filePath)

  if (!filePath) {
    return (
      <EmptyState
        title="Nenhum arquivo aberto"
        description="Escolha um arquivo na árvore à esquerda para ver o conteúdo e os símbolos detectados na última análise."
      />
    )
  }
  if (isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-zinc-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Carregando arquivo…
      </p>
    )
  }
  if (error) {
    return (
      <EmptyState
        title="Falha ao abrir o arquivo"
        description={error instanceof Error ? error.message : 'Erro inesperado.'}
      />
    )
  }
  if (!data) return null

  const lines = data.content.split('\n')

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <div className="min-w-0">
            <CardTitle className="truncate font-mono text-xs">{data.path}</CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-2 pt-1">
              <Badge variant="cyan">{data.language || 'texto'}</Badge>
              <span>{formatNumber(data.lines)} linhas</span>
              <span>{formatBytes(data.size_bytes)}</span>
              {data.parse_ok === true && <Badge variant="success">parse ok</Badge>}
              {data.parse_ok === false && <Badge variant="danger">parse falhou</Badge>}
              {data.truncated && <Badge variant="warning">truncado</Badge>}
            </CardDescription>
          </div>
        </CardHeader>
        {data.parse_error && (
          <CardContent className="pt-0">
            <p className="rounded border border-rose-900/60 bg-rose-950/40 px-3 py-2 font-mono text-xs text-rose-300">
              {data.parse_error}
            </p>
          </CardContent>
        )}
      </Card>

      {data.symbols.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              Símbolos ({formatNumber(data.symbols.length)})
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <ul className="flex flex-wrap gap-1.5">
              {data.symbols.map((symbol) => (
                <li key={`${symbol.qualified_name}-${symbol.lineno}`}>
                  <span
                    className="inline-flex items-center gap-1.5 rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1 font-mono text-[11px] text-zinc-300"
                    title={`${symbol.kind} · linha ${symbol.lineno}`}
                  >
                    <span className="text-cyan-400">{symbol.name}</span>
                    <span className="text-zinc-600">{symbol.kind}</span>
                    <span className="text-zinc-600">L{symbol.lineno}</span>
                    {symbol.complexity > 0 && (
                      <span className="text-violet-400">cc {symbol.complexity}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="max-h-[60vh] overflow-auto rounded-b-xl">
            <table className="w-full border-collapse font-mono text-xs leading-5">
              <tbody>
                {lines.map((line, index) => (
                  <tr key={index} className="align-top">
                    <td className="w-12 select-none border-r border-zinc-800/80 bg-zinc-950/60 px-2 text-right text-zinc-600">
                      {index + 1}
                    </td>
                    <td className="whitespace-pre-wrap break-words px-3 text-zinc-300">
                      {line || ' '}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export function ExplorerPage({ projectId }: { projectId: number }) {
  const [currentPath, setCurrentPath] = useState('')
  const [selectedFile, setSelectedFile] = useState<string | null>(null)

  const navigateTo = (path: string) => setCurrentPath(path)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Explorador</h1>
          <p className="text-sm text-zinc-500">
            Arquivos do repositório como estão no disco — leitura somente.
          </p>
        </div>
        {currentPath !== '' && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCurrentPath(parentPath(currentPath))}
          >
            <ChevronLeft /> Diretório pai
          </Button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="min-h-[320px]">
          <TreePanel
            projectId={projectId}
            currentPath={currentPath}
            selectedFile={selectedFile}
            onNavigate={navigateTo}
            onSelectFile={setSelectedFile}
          />
        </div>
        <FileViewer projectId={projectId} filePath={selectedFile} />
      </div>
    </div>
  )
}
