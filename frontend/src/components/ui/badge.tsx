import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-violet-500/15 text-violet-300 ring-1 ring-inset ring-violet-500/30',
        secondary: 'border-transparent bg-zinc-800 text-zinc-300',
        success:
          'border-transparent bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30',
        warning:
          'border-transparent bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30',
        danger:
          'border-transparent bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30',
        cyan: 'border-transparent bg-cyan-500/15 text-cyan-300 ring-1 ring-inset ring-cyan-500/30',
        outline: 'border-zinc-700 text-zinc-300',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
