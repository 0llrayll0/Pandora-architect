import * as React from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Select nativo estilizado (sem dependência de Radix Select). */
export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <div className="relative inline-flex items-center">
    <select
      ref={ref}
      className={cn(
        'h-9 appearance-none rounded-md border border-zinc-700 bg-zinc-950/60 pl-3 pr-8 text-sm text-zinc-100 shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/70 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-zinc-500" />
  </div>
))
Select.displayName = 'Select'
