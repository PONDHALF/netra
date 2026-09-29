import { ImageOff, PencilLine, Sparkles } from 'lucide-react'
import { forwardRef } from 'react'
import type { VehicleEvent } from '@/lib/api'
import { cn, confTone, fmtOffset, fmtTime, pct, TYPE_COLOR, TYPE_SHORT } from '@/lib/utils'
import { PlateChip } from './Plate'

export function Thumb({ src, className, alt }: { src: string | null; className?: string; alt: string }) {
  if (!src) {
    return (
      <div className={cn('flex items-center justify-center rounded-md bg-panel-2 text-muted', className)}>
        <ImageOff className="size-4" />
      </div>
    )
  }
  return <img src={src} alt={alt} loading="lazy" className={cn('rounded-md bg-black object-cover', className)} />
}

/** แสดงว่าเลขทะเบียนมาจาก Typhoon OCR (อ่านซ้ำหลังวิเคราะห์) */
export function TyphoonTag({ className }: { className?: string }) {
  return (
    <span title="อ่านป้ายซ้ำด้วย Typhoon OCR 3B"
      className={cn('inline-flex items-center gap-0.5 rounded border border-violet-400/40 bg-violet-400/10 px-1 text-[10px] font-medium text-violet-300', className)}>
      <Sparkles className="size-2.5" />Typhoon
    </span>
  )
}

export function TypeDot({ type }: { type: VehicleEvent['vehicle_type'] }) {
  return <span className="inline-block size-2 rounded-full" style={{ background: TYPE_COLOR[type] }} />
}

export const EventRow = forwardRef<HTMLDivElement, {
  event: VehicleEvent
  active?: boolean
  fresh?: boolean
  updated?: boolean
  showSource?: boolean
  onClick?: () => void
  onDoubleClick?: () => void
  action?: React.ReactNode
}>(function EventRow({ event: e, active, fresh, updated, showSource, onClick, onDoubleClick, action }, ref) {
  return (
    <div
      ref={ref}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      className={cn(
        'group relative flex gap-3 border-b border-line/70 px-3 py-2.5 transition-colors',
        onClick && 'cursor-pointer hover:bg-panel-2/70',
        active && 'bg-accent/10 before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-accent',
        fresh && 'animate-pop',
        updated && 'animate-pop bg-violet-400/10',
      )}
    >
      <Thumb src={e.car_img_url} alt="รถ" className="h-16 w-24 shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col justify-between gap-1">
        <div className="flex items-start justify-between gap-2">
          <PlateChip text={e.plate_text} province={e.plate_province} size="sm" />
          {e.plate_img_url && (
            <img src={e.plate_img_url} alt="ป้าย" loading="lazy" className="h-9 max-w-24 rounded border border-line object-contain" />
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted">
          <span className="font-mono text-fg/90">{fmtOffset(e.video_offset_sec)}</span>
          <span>·</span>
          <span className="inline-flex items-center gap-1"><TypeDot type={e.vehicle_type} />{TYPE_SHORT[e.vehicle_type]}</span>
          {e.plate_text && (
            <>
              <span>·</span>
              {e.is_corrected ? (
                <span className="inline-flex items-center gap-0.5 text-accent"><PencilLine className="size-3" />แก้ไขแล้ว</span>
              ) : (
                <span className={cn('font-mono', confTone(e.plate_conf))}>{pct(e.plate_conf)}</span>
              )}
              {e.ocr_engine === 'typhoon' && !e.is_corrected && <TyphoonTag />}
            </>
          )}
          {showSource && <span className="truncate">· {e.source_name} · {fmtTime(e.ts)}</span>}
        </div>
      </div>
      {action}
    </div>
  )
})
