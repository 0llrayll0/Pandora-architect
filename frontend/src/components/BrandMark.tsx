import { cn } from '@/lib/utils'

interface BrandMarkProps {
  className?: string
  /** `lockup` = logo completa (símbolo + wordmark); `mark` = só o símbolo hexagonal. */
  variant?: 'lockup' | 'mark'
}

/**
 * Marca oficial do Pandora Architect (assets derivados da logo real em
 * `public/logo.png` / `public/logo-mark.png`). O `mark` é quadrado e serve
 * em contexts inline; o `lockup` é largo e vai no topo da sidebar.
 */
export function BrandMark({ className, variant = 'mark' }: BrandMarkProps) {
  const src = variant === 'lockup' ? '/logo.png' : '/logo-mark.png'
  return (
    <img
      src={src}
      alt="Pandora Architect"
      className={cn('block object-contain', className)}
      draggable={false}
    />
  )
}
