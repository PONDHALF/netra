import { cn } from '@/lib/utils'

/** แสดงเลขทะเบียนให้หน้าตาคล้ายป้ายทะเบียนไทยจริง */
export function PlateChip({ text, province, size = 'md', className }: {
  text: string | null
  province?: string | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  if (!text) {
    return (
      <div className={cn('inline-flex flex-col items-center justify-center rounded-md border border-dashed border-line px-2 text-muted',
        size === 'lg' ? 'h-24 min-w-56 text-base' : size === 'md' ? 'h-12 min-w-28 text-xs' : 'h-9 min-w-20 text-[11px]', className)}>
        อ่านป้ายไม่ได้
        {province && <span className="text-[10px]">{province}</span>}
      </div>
    )
  }
  return (
    <div
      className={cn(
        'inline-flex flex-col items-center justify-center rounded-md border-2 border-neutral-800 bg-gradient-to-b from-white to-neutral-200 text-neutral-900 shadow-[inset_0_0_0_2px_#fff,0_2px_6px_rgba(0,0,0,.45)] ring-1 ring-black/30',
        size === 'lg' ? 'min-w-56 px-5 py-2' : size === 'md' ? 'min-w-28 px-2.5 py-1' : 'min-w-20 px-1.5 py-0.5',
        className,
      )}
    >
      <span className={cn('font-bold leading-tight tracking-wide',
        size === 'lg' ? 'text-4xl' : size === 'md' ? 'text-lg' : 'text-sm')}>{text}</span>
      {province && (
        <span className={cn('leading-tight text-neutral-700', size === 'lg' ? 'text-base' : size === 'md' ? 'text-[10px]' : 'text-[9px]')}>
          {province}
        </span>
      )}
    </div>
  )
}
