import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn('inline-flex items-center gap-1 rounded-md border border-line bg-panel-2 px-1.5 py-0.5 text-[11px] font-medium leading-none text-muted', className)}
      {...props}
    />
  )
}
