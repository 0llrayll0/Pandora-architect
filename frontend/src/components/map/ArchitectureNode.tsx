import { memo, type CSSProperties } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  Braces,
  Boxes,
  CircleDashed,
  FileCode,
  FolderTree,
  Languages,
  type LucideIcon,
} from 'lucide-react'
import {
  GROUP_HEADER_H,
  KIND_LABEL,
  KIND_STYLE,
  nodeSize,
  type MapNode,
  type MapNodeData,
  type MapNodeKind,
} from '@/lib/graphTransform'
import { cn } from '@/lib/utils'

/** Ícone por tipo — cor + ícone + texto (nunca só cor). */
const KIND_ICON: Record<MapNodeKind, LucideIcon> = {
  directory: FolderTree,
  file: FileCode,
  module: Boxes,
  symbol: Braces,
  external: Languages,
  unresolved: CircleDashed,
}

/** Linha de métricas discreta, só com campos reais do payload. */
function statsOf(data: MapNodeData): string {
  const parts: string[] = []
  if (data.lines !== null) parts.push(`${data.lines} lin`)
  if (data.fileCount > 0) parts.push(`${data.fileCount} arq`)
  const degree = data.inDegree + data.outDegree
  if (degree > 0) parts.push(`${degree} lig`)
  return parts.join(' · ')
}

const CARD_SHADOW =
  'shadow-[0_10px_28px_-12px_rgba(0,0,0,0.95),0_2px_8px_-4px_rgba(0,0,0,0.8)]'

/**
 * Nó customizado do mapa de arquitetura.
 *
 * Dois formatos: **card** (módulo/arquivo/externo/…) e **container** de
 * diretório (borda tracejada + cabeçalho) que hospeda os arquivos-filho.
 * A orientação dos handles segue a direção do layout (LR/TB).
 */
export const ArchitectureNode = memo(function ArchitectureNode({
  data,
  selected,
  width,
  height,
  parentId,
}: NodeProps<MapNode>) {
  const style = KIND_STYLE[data.kind]
  const vertical = data.dir === 'TB'
  const size = nodeSize(data)
  const shownChildren = data.shownChildren ?? 0
  const isContainer = data.kind === 'directory' && shownChildren > 0

  const targetPosition = vertical ? Position.Top : Position.Left
  const sourcePosition = vertical ? Position.Bottom : Position.Right

  const handles = (
    <>
      <Handle
        type="target"
        position={targetPosition}
        className="!h-1.5 !w-1.5 !rounded-full !border-0 !bg-transparent"
        style={{ background: style.dot }}
      />
      <Handle
        type="source"
        position={sourcePosition}
        className="!h-1.5 !w-1.5 !rounded-full !border-0 !bg-transparent"
        style={{ background: style.dot }}
      />
    </>
  )

  // -----------------------------------------------------------------------
  // Container de diretório (nó-pai do React Flow)
  // -----------------------------------------------------------------------
  if (isContainer) {
    const overflow = data.fileCount - shownChildren
    return (
      <div
        className={cn(
          'arch-node arch-node--group relative h-full w-full overflow-hidden rounded-2xl border border-dashed backdrop-blur-[2px]',
          data.dimmed && 'opacity-25',
          data.matched && 'ring-2 ring-cyan-400/70',
          selected && 'ring-2 ring-violet-400',
        )}
        style={
          {
            width: width ?? undefined,
            height: height ?? undefined,
            borderColor: selected
              ? 'rgba(167,139,250,0.75)'
              : data.inCycle
                ? 'rgba(244,63,94,0.55)'
                : 'rgba(139,92,246,0.38)',
            background:
              'linear-gradient(180deg, rgba(124,58,237,0.14) 0%, rgba(124,58,237,0.04) 55%, rgba(34,211,238,0.03) 100%)',
            boxShadow: selected
              ? '0 0 0 1px rgba(167,139,250,0.35), 0 0 32px -8px rgba(167,139,250,0.55)'
              : undefined,
          } as CSSProperties
        }
        title={data.path || data.label}
      >
        {handles}

        <header
          className="flex items-center gap-2 border-b border-violet-400/15 px-3.5"
          style={{ height: GROUP_HEADER_H }}
        >
          <FolderTree className="h-3.5 w-3.5 shrink-0 text-violet-300" aria-hidden="true" />
          <span className="truncate text-[12px] font-semibold tracking-wide text-violet-50">
            {data.label}
          </span>
          <span
            className="ml-auto shrink-0 rounded-full border border-violet-400/25 bg-violet-500/15 px-1.5 py-px font-mono text-[10px] text-violet-100"
            title={`${data.fileCount} arquivos${data.lines !== null ? ` · ${data.lines} linhas` : ''}`}
          >
            {data.fileCount} arq
            {data.lines !== null && ` · ${data.lines} lin`}
          </span>
        </header>

        {overflow > 0 && (
          <p className="absolute right-3.5 bottom-1.5 left-3.5 truncate text-[10px] text-zinc-500">
            + {overflow} arquivo{overflow === 1 ? '' : 's'} fora da grade · veja no painel
          </p>
        )}
      </div>
    )
  }

  // -----------------------------------------------------------------------
  // Card (filho de container, módulo, símbolo, externo, não-resolvido…)
  // -----------------------------------------------------------------------
  const Icon = KIND_ICON[data.kind]
  const compact = Boolean(parentId)
  const stats = statsOf(data)

  return (
    <div
      className={cn(
        'arch-node flex h-full w-full flex-col justify-center gap-0.5 overflow-hidden rounded-xl border px-2.5 py-1.5',
        CARD_SHADOW,
        'backdrop-blur-sm',
        data.dimmed && 'opacity-25',
        data.matched && 'ring-2 ring-cyan-400/80',
        selected && 'ring-2 ring-violet-400',
      )}
      style={{
        borderColor: data.inCycle ? '#f43f5e' : style.stroke,
        backgroundColor: data.inCycle ? 'rgba(244,63,94,0.10)' : style.fill,
        boxShadow: selected
          ? '0 0 28px -6px rgba(167,139,250,0.6), 0 10px 28px -12px rgba(0,0,0,0.95)'
          : undefined,
        width: width ?? size.width,
        height: height ?? size.height,
      }}
      title={data.path || data.label}
    >
      {handles}

      <div className="flex min-w-0 items-center gap-1.5">
        <Icon
          className="h-3.5 w-3.5 shrink-0"
          style={{ color: style.dot }}
          aria-hidden="true"
        />
        <span className="truncate text-[12px] font-semibold text-zinc-50">{data.label}</span>
      </div>

      {data.sublabel && !compact && (
        <p className="truncate font-mono text-[10px] text-zinc-400">{data.sublabel}</p>
      )}

      <div
        className={cn(
          'flex min-w-0 items-center gap-1.5 text-[10px] text-zinc-400',
          compact && 'font-mono',
        )}
      >
        {compact ? (
          <span className="truncate" title={data.sublabel || stats}>
            {data.sublabel || stats}
          </span>
        ) : (
          <>
            <span
              className="shrink-0 rounded px-1 py-px font-medium"
              style={{ color: style.stroke, backgroundColor: style.fill }}
            >
              {KIND_LABEL[data.kind]}
            </span>
            {stats && (
              <span className="truncate font-mono" title={stats}>
                {stats}
              </span>
            )}
            {data.inCycle && (
              <span className="shrink-0 font-semibold text-rose-400">ciclo</span>
            )}
          </>
        )}
      </div>
    </div>
  )
})
