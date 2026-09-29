import { Activity, Ban, Car, Check, Gauge, Hourglass, ScanLine, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJobSocket } from '@/hooks/useJobSocket'
import { api, type Job, type VehicleEvent, type WsMessage } from '@/lib/api'
import { cn, fmtDuration, pct, TYPE_SHORT } from '@/lib/utils'
import { EventRow } from './EventRow'
import { STAGE_TH } from './StatusBadge'
import { Button } from './ui/button'
import { Card, CardHeader, CardTitle } from './ui/card'
import { Progress } from './ui/progress'

interface Live {
  progress: number
  stage: string | null
  eta: number | null
  fps: number | null
  frame: number
  total: number
}

function Stat({ icon: Icon, label, value }: { icon: typeof Car; label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-bg/40 p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted"><Icon className="size-3.5" />{label}</div>
      <div className="mt-1 font-mono text-xl">{value}</div>
    </div>
  )
}

const STEP_ORDER = ['loading', 'analyzing', 'refining', 'rendering', 'done']

/** แถบขั้นตอน: วิเคราะห์ → (Typhoon อ่านซ้ำ) → สร้างวิดีโอ */
function Steps({ stage, typhoon }: { stage: string | null; typhoon: boolean }) {
  const steps = [
    { key: 'analyzing', label: 'วิเคราะห์วิดีโอ', sub: 'ตรวจจับรถ + อ่านป้าย' },
    ...(typhoon ? [{ key: 'refining', label: 'Typhoon อ่านซ้ำ', sub: 'แก้เลข/จังหวัดที่อ่านไม่ครบ' }] : []),
    { key: 'rendering', label: 'สร้างวิดีโอผลลัพธ์', sub: 'วาดกรอบ + เลขทะเบียน' },
  ]
  const cur = STEP_ORDER.indexOf(stage ?? 'loading')
  return (
    <ol className="grid gap-2" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
      {steps.map((s, i) => {
        const idx = STEP_ORDER.indexOf(s.key)
        const done = cur > idx
        const active = cur === idx
        return (
          <li key={s.key} className={cn('rounded-lg border p-2.5 transition-colors',
            active ? (s.key === 'refining' ? 'border-violet-400/50 bg-violet-400/10' : 'border-accent/50 bg-accent/10')
              : done ? 'border-ok/30 bg-ok/5' : 'border-line bg-bg/40 opacity-60')}>
            <div className="flex items-center gap-1.5 text-xs font-semibold">
              <span className={cn('flex size-4 items-center justify-center rounded-full text-[10px]',
                done ? 'bg-ok text-bg' : active ? 'bg-fg text-bg' : 'bg-line text-muted')}>
                {done ? <Check className="size-3" /> : i + 1}
              </span>
              {s.key === 'refining' && <Sparkles className="size-3 text-violet-300" />}
              {s.label}
            </div>
            <div className="mt-0.5 pl-5.5 text-[11px] text-muted">{s.sub}</div>
          </li>
        )
      })}
    </ol>
  )
}

export function ProcessingView({ job, onFinished }: { job: Job; onFinished: () => void }) {
  const nav = useNavigate()
  const [live, setLive] = useState<Live>({ progress: job.progress, stage: job.stage, eta: job.eta_sec, fps: null, frame: 0, total: 0 })
  const [events, setEvents] = useState<VehicleEvent[]>([])
  const [freshIds, setFreshIds] = useState<Set<number>>(new Set())
  const [updatedIds, setUpdatedIds] = useState<Set<number>>(new Set())
  const seen = useRef(new Set<number>())

  // กรณีเปิดหน้านี้กลางคัน: โหลดรถที่เจอไปแล้ว
  useEffect(() => {
    api.events({ job_id: job.id }, { sort: 'offset', limit: 5000 }).then((r) => {
      setEvents((prev) => {
        const merged = [...prev]
        for (const e of r.items) if (!seen.current.has(e.id)) { seen.current.add(e.id); merged.push(e) }
        return merged.sort((a, b) => (b.video_offset_sec ?? 0) - (a.video_offset_sec ?? 0))
      })
    })
  }, [job.id])

  useJobSocket(job.id, true, (m: WsMessage) => {
    if (m.type === 'progress') {
      setLive({ progress: m.progress, stage: m.stage, eta: m.eta_sec, fps: m.fps, frame: m.frame, total: m.total_frames })
    } else if (m.type === 'status') {
      setLive((l) => ({ ...l, progress: m.progress, stage: m.stage }))
      if (m.status !== 'queued' && m.status !== 'processing') onFinished()
    } else if (m.type === 'event' && !seen.current.has(m.event.id)) {
      seen.current.add(m.event.id)
      setEvents((prev) => [m.event, ...prev])
      setFreshIds((s) => new Set(s).add(m.event.id))
    } else if (m.type === 'event_update') {
      // Typhoon อ่านซ้ำแล้วได้ผลต่างจากเดิม → แทนที่ในรายการ แล้วไฮไลต์
      setEvents((prev) => prev.map((e) => (e.id === m.event.id ? m.event : e)))
      setUpdatedIds((s) => new Set(s).add(m.event.id))
    }
  })

  const counts = events.reduce<Record<string, number>>((acc, e) => ({ ...acc, [e.vehicle_type]: (acc[e.vehicle_type] ?? 0) + 1 }), {})
  const read = events.filter((e) => e.plate_text).length
  const stage = job.status === 'queued' ? 'รอคิวประมวลผล' : STAGE_TH[live.stage ?? 'loading'] ?? live.stage
  const refining = live.stage === 'refining'
  const byTyphoon = events.filter((e) => e.ocr_engine === 'typhoon').length

  return (
    <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
      <Card className="relative overflow-hidden">
        {job.thumb_url && (
          <img src={job.thumb_url} alt="" className="absolute inset-0 h-full w-full object-cover opacity-[0.07] blur-sm" />
        )}
        <div className="relative space-y-6 p-6">
          <div className="flex items-center gap-4">
            <div className={cn('relative flex size-14 items-center justify-center rounded-xl border',
              refining ? 'border-violet-400/40 bg-violet-400/10' : 'border-accent/30 bg-accent/10')}>
              {refining ? <Sparkles className="size-7 text-violet-300" /> : <ScanLine className="size-7 text-accent" />}
              <span className={cn('absolute inset-0 animate-ping rounded-xl border', refining ? 'border-violet-400/30' : 'border-accent/30')} />
            </div>
            <div>
              <div className="text-lg font-semibold">{stage}</div>
              <div className="text-sm text-muted">
                {live.eta != null && live.eta > 0 ? `เหลือประมาณ ${fmtDuration(live.eta)}` : 'กำลังประมาณเวลา…'}
              </div>
            </div>
            <div className="ml-auto font-mono text-4xl font-medium text-accent">{pct(live.progress)}</div>
          </div>
          <Progress value={live.progress} className="h-3" />
          <Steps stage={job.status === 'queued' ? null : live.stage} typhoon={job.use_typhoon} />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat icon={Car} label="รถที่พบ" value={events.length} />
            <Stat icon={Activity} label="อ่านป้ายได้" value={events.length ? <>{pct(read / events.length)}{byTyphoon > 0 && <span className="ml-1 text-xs text-violet-300">({byTyphoon} จาก Typhoon)</span>}</> : '-'} />
            <Stat icon={Gauge} label="ความเร็ว" value={live.fps ? <>{live.fps}<span className="text-xs text-muted">{refining ? ' ป้าย/วิ' : ' fps'}</span></> : '-'} />
            <Stat icon={Hourglass} label={refining ? 'ป้ายที่อ่านซ้ำ' : 'เฟรม'} value={live.total ? <span className="text-base">{live.frame.toLocaleString()}<span className="text-muted">/{live.total.toLocaleString()}</span></span> : '-'} />
          </div>
          {events.length > 0 && (
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(counts).map(([t, n]) => (
                <span key={t} className="rounded-full border border-line bg-bg/50 px-2.5 py-1">
                  {TYPE_SHORT[t as keyof typeof TYPE_SHORT]} <b>{n}</b>
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="danger" size="sm" onClick={async () => { if (confirm('ยกเลิกการประมวลผล?')) { await api.cancelJob(job.id); onFinished() } }}>
              <Ban />ยกเลิก
            </Button>
            <Button variant="ghost" size="sm" onClick={() => nav('/')}>กลับหน้าแรก (งานยังทำต่อเบื้องหลัง)</Button>
          </div>
        </div>
      </Card>

      <Card className="flex max-h-[70vh] flex-col">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-danger opacity-75" /><span className="relative inline-flex size-2 rounded-full bg-danger" /></span>
            รถที่ตรวจพบ (สด)
          </CardTitle>
          <span className="font-mono text-xs text-muted">{events.length}</span>
        </CardHeader>
        <div className="flex-1 overflow-y-auto">
          {events.length === 0 ? (
            <div className="p-10 text-center text-sm text-muted">รถแต่ละคันจะปรากฏที่นี่ทันทีที่ออกจากภาพ</div>
          ) : (
            events.map((e) => <EventRow key={e.id} event={e} fresh={freshIds.has(e.id)} updated={updatedIds.has(e.id)} />)
          )}
        </div>
      </Card>
    </div>
  )
}
