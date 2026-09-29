import { cn } from '@/lib/utils'

export function Progress({ value, className, indeterminate }: { value: number; className?: string; indeterminate?: boolean }) {
  return (
    <div className={cn('relative h-2 w-full overflow-hidden rounded-full bg-line/70', className)}>
      <div
        className={cn('h-full rounded-full bg-gradient-to-r from-accent to-cyan-300 transition-[width] duration-500 ease-out',
          indeterminate && 'w-1/3 animate-pulse')}
        style={indeterminate ? undefined : { width: `${Math.min(100, Math.max(0, value * 100))}%` }}
      />
    </div>
  )
}
