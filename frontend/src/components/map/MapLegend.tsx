import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Panel } from '@xyflow/react'
import {
  EDGE_STYLE,
  KIND_LABEL,
  KIND_STYLE,
  type MapNodeKind,
} from '@/lib/graphTransform'

const LEGEND_KINDS: MapNodeKind[] = [
  'directory',
  'file',
  'module',
  'symbol',
  'external',
  'unresolved',
]

const LEGEND_EDGES = [
  { key: 'imports', color: EDGE_STYLE.imports.stroke, label: 'importa' },
  { key: 'contains', color: EDGE_STYLE.contains.stroke, label: 'contém (tracejado)' },
  { key: 'external', color: EDGE_STYLE.external.stroke, label: 'externo' },
  { key: 'unresolved', color: EDGE_STYLE.unresolved.stroke, label: 'não resolvido' },
  { key: 'highlighted', color: EDGE_STYLE.highlighted.stroke, label: 'selecionado / busca' },
] as const

/** Legenda flutuante (nós + arestas), colapsável para não cobrir o grafo. */
export function MapLegend() {
  const [open, setOpen] = useState(false)

  return (
    <Panel position="bottom-left" className="!m-3 max-w-[240px]">
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/92 shadow-xl backdrop-blur-sm">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-medium text-zinc-300 transition-colors hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:outline-none"
        >
          Legenda
          {open ? (
            <ChevronDown className="ml-auto h-3 w-3" aria-hidden="true" />
          ) : (
            <ChevronUp className="ml-auto h-3 w-3" aria-hidden="true" />
          )}
        </button>

        {open && (
          <div className="space-y-2.5 border-t border-zinc-800/80 px-2.5 py-2">
            <ul className="space-y-1">
              {LEGEND_KINDS.map((kind) => (
                <li key={kind} className="flex items-center gap-2 text-[10px] text-zinc-400">
                  <span
                    className="h-2 w-2 shrink-0 rounded-sm border"
                    style={{
                      borderColor: KIND_STYLE[kind].stroke,
                      backgroundColor: KIND_STYLE[kind].fill,
                    }}
                    aria-hidden="true"
                  />
                  {KIND_LABEL[kind]}
                </li>
              ))}
            </ul>

            <ul className="space-y-1 border-t border-zinc-800/80 pt-2">
              {LEGEND_EDGES.map((edge) => (
                <li key={edge.key} className="flex items-center gap-2 text-[10px] text-zinc-400">
                  <span
                    className="h-0 w-5 shrink-0 border-t-2"
                    style={{
                      borderColor: edge.color,
                      borderStyle: edge.key === 'contains' ? 'dashed' : 'solid',
                    }}
                    aria-hidden="true"
                  />
                  {edge.label}
                </li>
              ))}
            </ul>

            <p className="border-t border-zinc-800/80 pt-2 text-[10px] leading-snug text-zinc-500">
              Nós em ciclo aparecem com borda vermelha; clique para ver detalhes e
              dependências.
            </p>
          </div>
        )}
      </div>
    </Panel>
  )
}
