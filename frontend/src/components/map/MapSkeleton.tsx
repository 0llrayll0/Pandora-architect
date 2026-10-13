import { cn } from '@/lib/utils'

/**
 * Placeholder do mapa enquanto o grafo carrega: silhueta de containers e
 * nós no lugar do spinner — sem inventar dados.
 */
export function MapSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn('map-surface relative h-full w-full overflow-hidden p-6', className)}
      role="status"
      aria-label="Carregando grafo de arquitetura"
    >
      <div className="flex h-full items-center justify-center gap-6 lg:gap-10">
        {/* linha 1: containers de diretório com filhos */}
        <div className="flex flex-col gap-4">
          <div className="h-[150px] w-[248px] animate-pulse rounded-2xl border border-dashed border-violet-500/30 bg-violet-500/10" />
          <div className="h-[110px] w-[196px] animate-pulse rounded-2xl border border-dashed border-violet-500/25 bg-violet-500/10" />
        </div>

        {/* coluna central: nós independentes */}
        <div className="flex flex-col gap-4">
          <div className="h-[78px] w-[208px] animate-pulse rounded-xl border border-cyan-500/30 bg-cyan-500/10" />
          <div className="h-[78px] w-[232px] animate-pulse rounded-xl border border-cyan-500/25 bg-cyan-500/10" />
          <div className="h-[78px] w-[208px] animate-pulse rounded-xl border border-zinc-700 bg-zinc-800/60" />
        </div>

        <div className="flex flex-col gap-4">
          <div className="h-[78px] w-[208px] animate-pulse rounded-xl border border-amber-500/30 bg-amber-500/10" />
          <div className="h-[78px] w-[208px] animate-pulse rounded-xl border border-zinc-700 bg-zinc-800/60" />
        </div>
      </div>

      <p className="absolute right-0 bottom-4 left-0 text-center text-xs text-zinc-500">
        Montando o mapa de arquitetura…
      </p>
    </div>
  )
}
