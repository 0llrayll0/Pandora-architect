import type { ComponentType } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { ArchitectureMapPage } from '@/pages/ArchitectureMapPage'
import { CyclesPage } from '@/pages/CyclesPage'
import { DependenciesPage } from '@/pages/DependenciesPage'
import { ExplorerPage } from '@/pages/ExplorerPage'
import { HistoryPage } from '@/pages/HistoryPage'
import { HotspotsPage } from '@/pages/HotspotsPage'
import { OverviewPage } from '@/pages/OverviewPage'
import { PhaseSoon } from '@/pages/PhaseSoon'
import { ProjectsPage } from '@/pages/ProjectsPage'
import { SettingsPage } from '@/pages/SettingsPage'

/** Lê :projectId da URL e repassa à página; redireciona se inválido. */
function projectRoute(Page: ComponentType<{ projectId: number }>) {
  return function ProjectRoute() {
    const { projectId } = useParams()
    const id = Number(projectId)
    if (!projectId || Number.isNaN(id)) return <Navigate to="/" replace />
    return <Page projectId={id} />
  }
}

const OverviewRoute = projectRoute(OverviewPage)
const DependenciesRoute = projectRoute(DependenciesPage)
const CyclesRoute = projectRoute(CyclesPage)
const ExplorerRoute = projectRoute(ExplorerPage)
const MapRoute = projectRoute(ArchitectureMapPage)
const HotspotsRoute = projectRoute(HotspotsPage)
const HistoryRoute = projectRoute(HistoryPage)

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ProjectsPage />} />
        <Route path="settings" element={<SettingsPage />} />

        <Route path="projects/:projectId">
          <Route index element={<OverviewRoute />} />
          <Route path="dependencies" element={<DependenciesRoute />} />
          <Route path="cycles" element={<CyclesRoute />} />
          <Route path="explorer" element={<ExplorerRoute />} />
          <Route path="map" element={<MapRoute />} />
          <Route path="hotspots" element={<HotspotsRoute />} />
          <Route path="history" element={<HistoryRoute />} />
          <Route
            path="ai"
            element={
              <PhaseSoon
                phase={6}
                title="Arquiteto IA"
                description="Sugestões de refatoração geradas a partir do grafo real do código."
                icon={<Sparkles className="h-8 w-8" />}
              />
            }
          />
        </Route>

        <Route path="projects" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
