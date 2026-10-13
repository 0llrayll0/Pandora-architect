import { Menu, PlayCircle, RefreshCw, Wifi, WifiOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { ProjectStatusBadge } from '@/components/ProjectStatusBadge'
import { useActiveRun } from '@/hooks/useActiveRun'
import { runStateLabel } from '@/lib/format'
import { useAnalyzeProject, useHealth, useProjects } from '@/store/api'

interface TopbarProps {
  projectId: number | null
  onOpenMenu: () => void
}

export function Topbar({ projectId, onOpenMenu }: TopbarProps) {
  const { data: projects } = useProjects()
  const { data: health } = useHealth()
  const analyze = useAnalyzeProject()
  const { runId, runs, run, selectRun } = useActiveRun(projectId)

  const project = projects?.find((p) => p.id === projectId) ?? null
  const analyzing = run?.state === 'running' || run?.state === 'pending'
  const online = health?.status === 'ok'

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-zinc-800/80 bg-zinc-950/70 px-4">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        onClick={onOpenMenu}
        aria-label="Abrir menu"
      >
        <Menu />
      </Button>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {project ? project.name : 'Pandora Architect'}
        </p>
        {project && (
          <p className="truncate text-[11px] font-mono text-zinc-500">{project.path}</p>
        )}
      </div>

      {/* Seletor de run — só quando há análises */}
      {projectId !== null && runs.length > 0 && (
        <div className="hidden sm:block">
          <Select
            className="h-8 w-56 text-xs"
            aria-label="Selecionar análise"
            value={runId !== null ? String(runId) : undefined}
            onChange={(event) => selectRun(Number(event.target.value))}
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} · {runStateLabel(r.state)} ·{' '}
                {new Date(r.created_at).toLocaleDateString('pt-BR')}
              </option>
            ))}
          </Select>
        </div>
      )}

      {run && <ProjectStatusBadge state={run.state} className="hidden md:flex" />}

      {projectId !== null && (
        <Button
          size="sm"
          disabled={analyzing || analyze.isPending}
          onClick={() => analyze.mutate(projectId)}
          title="Executar nova análise neste projeto"
        >
          {analyze.isPending ? (
            <RefreshCw className="animate-spin" />
          ) : (
            <PlayCircle />
          )}
          {analyzing ? 'Analisando…' : 'Analisar'}
        </Button>
      )}

      <span
        className={`flex items-center gap-1.5 text-[11px] ${online ? 'text-emerald-400' : 'text-zinc-500'}`}
        title={online ? 'API conectada' : 'API indisponível'}
      >
        {online ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
        <span className="hidden sm:inline">{online ? 'API ok' : 'offline'}</span>
      </span>
    </header>
  )
}
