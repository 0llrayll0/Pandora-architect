import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderGit2, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { BrandMark } from '@/components/BrandMark'
import { EmptyState } from '@/components/EmptyState'
import { ProjectStatusBadge } from '@/components/ProjectStatusBadge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { formatDateTime, formatNumber } from '@/lib/format'
import type { Project } from '@/lib/types'
import { useCreateProject, useDeleteProject, useProjects } from '@/store/api'
import { useAppStore } from '@/store/app'

/** Card individual do projeto na lista. */
function ProjectCard({
  project,
  onOpen,
  onDelete,
}: {
  project: Project
  onOpen: () => void
  onDelete: () => void
}) {
  return (
    <Card className="group transition-colors hover:border-zinc-700">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900">
              <FolderGit2 className="h-4 w-4 text-violet-400" />
            </div>
            <div className="min-w-0">
              <CardTitle className="truncate">{project.name}</CardTitle>
              <CardDescription className="truncate font-mono text-[11px]">
                {project.path}
              </CardDescription>
            </div>
          </div>
          <ProjectStatusBadge state={project.last_run?.state ?? null} />
        </div>
      </CardHeader>
      <CardContent className="flex items-end justify-between gap-3">
        <div className="grid grid-cols-3 gap-4 text-xs">
          <div>
            <p className="text-zinc-500">Análises</p>
            <p className="font-mono text-zinc-200">{formatNumber(project.run_count)}</p>
          </div>
          <div>
            <p className="text-zinc-500">Última</p>
            <p className="font-mono text-zinc-200">
              {project.last_run ? formatDateTime(project.last_run.created_at) : '—'}
            </p>
          </div>
          <div>
            <p className="text-zinc-500">Adicionado</p>
            <p className="font-mono text-zinc-200">{formatDateTime(project.created_at)}</p>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" onClick={onOpen}>
            Abrir
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="text-zinc-500 hover:text-rose-400"
            onClick={onDelete}
            aria-label={`Remover ${project.name} do Pandora`}
            title="Remove só do Pandora (não apaga arquivos)"
          >
            <Trash2 />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/** Formulário "Adicionar repositório". */
function AddProjectForm() {
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const create = useCreateProject()
  const navigate = useNavigate()
  const setActiveProject = useAppStore((s) => s.setActiveProject)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const trimmed = path.trim()
    if (!trimmed || create.isPending) return
    create.mutate(
      { path: trimmed, name: name.trim() || undefined },
      {
        onSuccess: (project) => {
          setPath('')
          setName('')
          setActiveProject(project.id)
          navigate(`/projects/${project.id}`)
        },
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Plus className="h-4 w-4 text-cyan-400" />
          Adicionar repositório
        </CardTitle>
        <CardDescription>
          Aponte para um caminho local de um repositório. Nada é enviado — a análise roda
          inteiramente na sua máquina.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row">
          <Input
            placeholder="/home/usuario/projetos/meu-repo"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            className="flex-1 font-mono text-xs"
            aria-label="Caminho do repositório"
            required
          />
          <Input
            placeholder="Nome (opcional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="sm:w-48"
            aria-label="Nome do projeto"
          />
          <Button type="submit" disabled={create.isPending || path.trim() === ''}>
            {create.isPending ? <RefreshCw className="animate-spin" /> : null}
            Adicionar
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

export function ProjectsPage() {
  const { data: projects, isLoading, error, refetch, isRefetching } = useProjects()
  const deleteProject = useDeleteProject()
  const [toDelete, setToDelete] = useState<Project | null>(null)
  const navigate = useNavigate()
  const setActiveProject = useAppStore((s) => s.setActiveProject)

  const openProject = (project: Project) => {
    setActiveProject(project.id)
    navigate(`/projects/${project.id}`)
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2.5 text-lg font-semibold text-zinc-100">
            <BrandMark className="h-6 w-6" />
            Painel de Projetos
          </h1>
          <p className="text-sm text-zinc-500">
            Repositórios locais registrados no Pandora Architect.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isRefetching}
          aria-label="Atualizar lista"
        >
          <RefreshCw className={isRefetching ? 'animate-spin' : undefined} />
        </Button>
      </div>

      <AddProjectForm />

      {isLoading && (
        <p className="text-sm text-zinc-500">Carregando projetos…</p>
      )}

      {error && (
        <EmptyState
          title="Não foi possível falar com a API"
          description={
            error instanceof Error
              ? error.message
              : 'Verifique se o backend está rodando (scripts/run.sh).'
          }
          action={
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Tentar de novo
            </Button>
          }
        />
      )}

      {!isLoading && !error && (projects?.length ?? 0) === 0 && (
        <EmptyState
          title="Nenhum repositório ainda"
          description="Adicione um caminho local acima para começar. O Pandora lê os arquivos do disco — nada sai da sua máquina."
        />
      )}

      {!isLoading && (projects?.length ?? 0) > 0 && (
        <div className="grid gap-4">
          {projects?.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onOpen={() => openProject(project)}
              onDelete={() => setToDelete(project)}
            />
          ))}
        </div>
      )}

      <Dialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remover "{toDelete?.name}" do Pandora?</DialogTitle>
            <DialogDescription>
              Isso apaga apenas o registro e os dados analisados deste projeto — nenhum
              arquivo do repositório é tocado.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setToDelete(null)}>
              Cancelar
            </Button>
            <Button
              variant="destructive"
              disabled={deleteProject.isPending}
              onClick={() => {
                if (!toDelete) return
                deleteProject.mutate(toDelete.id, { onSuccess: () => setToDelete(null) })
              }}
            >
              Remover
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
