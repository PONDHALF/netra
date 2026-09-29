import { CheckCircle2, CircleDashed, Loader2, XCircle, Ban } from 'lucide-react'
import type { JobStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

const MAP: Record<JobStatus, { label: string; cls: string; Icon: typeof Loader2 }> = {
  queued: { label: 'รอคิว', cls: 'text-muted border-line', Icon: CircleDashed },
  processing: { label: 'กำลังประมวลผล', cls: 'text-accent border-accent/30 bg-accent/10', Icon: Loader2 },
  done: { label: 'เสร็จแล้ว', cls: 'text-ok border-ok/30 bg-ok/10', Icon: CheckCircle2 },
  failed: { label: 'ผิดพลาด', cls: 'text-danger border-danger/30 bg-danger/10', Icon: XCircle },
  cancelled: { label: 'ยกเลิกแล้ว', cls: 'text-muted border-line', Icon: Ban },
}

export function StatusBadge({ status, className }: { status: JobStatus; className?: string }) {
  const { label, cls, Icon } = MAP[status]
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', cls, className)}>
      <Icon className={cn('size-3', status === 'processing' && 'animate-spin')} />
      {label}
    </span>
  )
}

export const STAGE_TH: Record<string, string> = {
  loading: 'กำลังโหลดโมเดล AI',
  analyzing: 'กำลังวิเคราะห์วิดีโอ',
  refining: 'Typhoon กำลังอ่านป้ายซ้ำ',
  rendering: 'กำลังสร้างวิดีโอผลลัพธ์',
  done: 'เสร็จสิ้น',
}
