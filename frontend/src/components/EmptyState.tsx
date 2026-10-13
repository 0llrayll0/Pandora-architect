import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description: string
  action?: ReactNode
  className?: string
}

/**
 * Estado vazio sem dados inventados: informa o que falta e a próxima ação.
 */
export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/40 px-6 py-12 text-center',
        className,
      )}
    >
      <div className="text-zinc-600">{icon}</div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-zinc-300">{title}</p>
        <p className="mx-auto max-w-md text-xs text-zinc-500">{description}</p>
      </div>
      {action}
    </div>
  )
}
