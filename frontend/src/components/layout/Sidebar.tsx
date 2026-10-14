import { NavLink } from 'react-router-dom'
import {
  Boxes,
  GitBranch,
  LayoutDashboard,
  History,
  FolderTree,
  Map,
  Settings,
  Flame,
  Sparkles,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { BrandMark } from '@/components/BrandMark'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Marcador "Fase N" para features ainda não entregues. */
  phase?: number
}

interface SidebarProps {
  /** Projeto ativo (null = nenhum selecionado). */
  projectId: number | null
  onNavigate?: () => void
}

function itemClass({ isActive }: { isActive: boolean }): string {
  return cn(
    'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors',
    isActive
      ? 'bg-violet-500/12 text-violet-200 ring-1 ring-inset ring-violet-500/30'
      : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200',
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-3 pt-5 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
      {children}
    </p>
  )
}

export function Sidebar({ projectId, onNavigate }: SidebarProps) {
  const projectNav: NavItem[] =
    projectId === null
      ? []
      : [
          { to: `/projects/${projectId}`, label: 'Análise', icon: LayoutDashboard },
          { to: `/projects/${projectId}/dependencies`, label: 'Dependências', icon: Boxes },
          { to: `/projects/${projectId}/cycles`, label: 'Ciclos', icon: GitBranch },
          { to: `/projects/${projectId}/explorer`, label: 'Explorador', icon: FolderTree },
          { to: `/projects/${projectId}/map`, label: 'Mapa da Arquitetura', icon: Map },
          { to: `/projects/${projectId}/hotspots`, label: 'Hotspots', icon: Flame },
          { to: `/projects/${projectId}/history`, label: 'Histórico', icon: History },
          { to: `/projects/${projectId}/ai`, label: 'Arquiteto IA', icon: Sparkles },
        ]

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950/80">
      <div className="px-4 py-4 border-b border-zinc-800/80">
        <BrandMark variant="lockup" className="h-9 w-auto" />
        <p className="mt-1.5 text-[10px] tracking-wide text-zinc-500">
          Local Repository Intelligence
        </p>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        <SectionTitle>Geral</SectionTitle>
        <NavLink to="/" end className={itemClass} onClick={onNavigate}>
          <Boxes className="h-4 w-4" />
          Projetos
        </NavLink>

        {projectId !== null && (
          <>
            <SectionTitle>Projeto ativo</SectionTitle>
            {projectNav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === `/projects/${projectId}`}
                className={itemClass}
                onClick={onNavigate}
              >
                <item.icon className="h-4 w-4" />
                <span className="flex-1 truncate">{item.label}</span>
                {item.phase !== undefined && (
                  <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[9px] font-medium text-zinc-500">
                    Fase {item.phase}
                  </span>
                )}
              </NavLink>
            ))}
          </>
        )}

        <SectionTitle>Sistema</SectionTitle>
        <NavLink to="/settings" className={itemClass} onClick={onNavigate}>
          <Settings className="h-4 w-4" />
          Configurações
        </NavLink>
      </nav>

      <div className="border-t border-zinc-800/80 px-4 py-3 text-[10px] text-zinc-600">
        v0.1.0 · 100% local
      </div>
    </aside>
  )
}
