import { Badge } from '@/components/ui/badge'
import { runStateLabel } from '@/lib/format'
import { cn } from '@/lib/utils'

const STATE_VARIANT: Record<string, 'success' | 'danger' | 'warning' | 'secondary' | 'cyan'> = {
  completed: 'success',
  failed: 'danger',
  cancelled: 'secondary',
  running: 'cyan',
  pending: 'warning',
}

interface ProjectStatusBadgeProps {
  state: string | null | undefined
  className?: string
}

/** Badge de estado da análise mais recente do projeto. */
export function ProjectStatusBadge({ state, className }: ProjectStatusBadgeProps) {
  if (!state) {
    return (
      <Badge variant="outline" className={className}>
        Sem análise
      </Badge>
    )
  }
  return (
    <Badge variant={STATE_VARIANT[state] ?? 'secondary'} className={className}>
      {state === 'running' && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse',
          )}
          aria-hidden="true"
        />
      )}
      {runStateLabel(state)}
    </Badge>
  )
}
