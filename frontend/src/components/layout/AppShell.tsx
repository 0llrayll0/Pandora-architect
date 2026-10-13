import { useEffect, useState } from 'react'
import { Outlet, useParams } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { LiveRunProgress } from '@/components/LiveRunProgress'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useRunProgress } from '@/hooks/useRunProgress'
import { useActiveRun } from '@/hooks/useActiveRun'
import { useAppStore } from '@/store/app'

/**
 * Shell da aplicação: sidebar fixa (desktop) / sheet (mobile),
 * topbar com run ativa + botão Analisar, barra de progresso ao vivo
 * e o conteúdo da rota corrente.
 */
export function AppShell() {
  const params = useParams()
  const [menuOpen, setMenuOpen] = useState(false)

  const projectIdParam = params.projectId
  const projectId = projectIdParam ? Number(projectIdParam) : null
  const validProjectId = projectId !== null && !Number.isNaN(projectId) ? projectId : null

  // mantém o projeto ativo em sincronia com a rota (e o store)
  const setActiveProject = useAppStore((s) => s.setActiveProject)
  const storedProjectId = useAppStore((s) => s.activeProjectId)
  useEffect(() => {
    if (validProjectId !== null && storedProjectId !== validProjectId) {
      setActiveProject(validProjectId)
    }
  }, [validProjectId, storedProjectId, setActiveProject])

  // assina o SSE da run ativa (se houver)
  const { runId } = useActiveRun(validProjectId)
  useRunProgress(runId, validProjectId)

  return (
    <div className="flex h-screen overflow-hidden bg-[#0a0e14] text-zinc-100">
      {/* Sidebar desktop */}
      <div className="hidden lg:block">
        <Sidebar projectId={validProjectId} />
      </div>

      {/* Sidebar mobile (sheet, aberta via botão do topbar) */}
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-60 p-0">
          <SheetTitle className="sr-only">Navegação</SheetTitle>
          <Sidebar projectId={validProjectId} onNavigate={() => setMenuOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar projectId={validProjectId} onOpenMenu={() => setMenuOpen(true)} />

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl space-y-4 p-4 sm:p-6">
            <LiveRunProgress />
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
