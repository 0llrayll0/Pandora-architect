import type { ReactNode } from 'react'
import { EmptyState } from '@/components/EmptyState'

interface PhaseSoonProps {
  phase: number
  title: string
  description: string
  icon?: ReactNode
}

/**
 * Placeholder honesto de roadmap: mostra a fase e o que a tela fará.
 * Nunca exibe dados simulados.
 */
export function PhaseSoon({ phase, title, description, icon }: PhaseSoonProps) {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">{title}</h1>
        <p className="text-sm text-zinc-500">{description}</p>
      </div>
      <EmptyState
        icon={icon}
        title={`Fase ${phase} — em breve`}
        description="Este módulo ainda não está implementado. Ele aparecerá aqui assim que o backend correspondente entrar no ar; nada é exibido enquanto não houver dados reais."
      />
    </div>
  )
}
