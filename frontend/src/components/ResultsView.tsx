import { Download, ExternalLink, FileArchive, FileSpreadsheet, Filter, Search, SlidersHorizontal, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type EventFilters, type Job, type VehicleEvent, type VehicleType } from '@/lib/api'
import { cn, fmtOffset, parseOffset, pct, TYPE_COLOR, TYPE_SHORT, VEHICLE_TYPES } from '@/lib/utils'
import { EventRow } from './EventRow'
import { Button, buttonVariants } from './ui/button'
import { Card } from './ui/card'
import { Input, Select } from './ui/input'

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** แถบเวลาใต้วิดีโอ: จุดแต่ละจุด = รถ 1 คัน คลิกเพื่อกระโดด */
function Timeline({ events, duration, current, activeId, onSeek }: {
  events: VehicleEvent[]; duration: number; current: number; activeId: number | null; onSeek: (e: VehicleEvent) => void
}) {
  if (!duration) return null
  return (
    <div className="relative h-8 border-t border-line bg-bg/60">
      <div className="absolute inset-y-0 left-0 bg-accent/10" style={{ width: `${(current / duration) * 100}%` }} />
      {events.map((e) => (
        <button
          key={e.id}
          title={`${fmtOffset(e.video_offset_sec)} · ${e.plate_text ?? 'อ่านป้ายไม่ได้'}`}
          onClick={() => onSeek(e)}
          className={cn('absolute top-1.5 h-5 w-1 -translate-x-1/2 cursor-pointer rounded-full transition-transform hover:scale-y-125',
            activeId === e.id && 'ring-2 ring-fg', !e.plate_text && 'opacity-40')}
          style={{ left: `${((e.video_offset_sec ?? 0) / duration) * 100}%`, background: TYPE_COLOR[e.vehicle_type] }}
        />
      ))}
      <div className="pointer-events-none absolute inset-y-0 w-px bg-fg" style={{ left: `${(current / duration) * 100}%` }} />
    </div>
  )
}

function SummaryPanel({ job, shown }: { job: Job; shown: number }) {
  const s = job.stats
  if (!s) return null
  return (
    <Card className="grid grid-cols-2 divide-line sm:grid-cols-4 sm:divide-x">
      <div className="p-4">
        <div className="text-xs text-muted">รถทั้งหมด</div>
        <div className="font-mono text-3xl">{s.total}<span className="ml-1 text-sm text-muted">คัน</span></div>
        {shown !== s.total && <div className="text-[11px] text-muted">แสดง {shown} ตามตัวกรอง</div>}
      </div>
      <div className="col-span-2 p-4">
        <div className="mb-2 text-xs text-muted">แยกตามประเภท</div>
        <div className="flex h-2 overflow-hidden rounded-full bg-line">
          {VEHICLE_TYPES.map((t) => (s.by_type[t] ? (
            <div key={t} style={{ width: `${(s.by_type[t]! / s.total) * 100}%`, background: TYPE_COLOR[t] }} />
          ) : null))}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {VEHICLE_TYPES.filter((t) => s.by_type[t]).map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: TYPE_COLOR[t] }} />
              {TYPE_SHORT[t]} <b className="font-mono">{s.by_type[t]}</b>
            </span>
          ))}
        </div>
      </div>
      <div className="p-4">
        <div className="text-xs text-muted">อ่านป้ายได้</div>
        <div className="font-mono text-3xl text-ok">{s.total ? pct(s.plates_read / s.total) : '-'}</div>
        <div className="text-[11px] text-muted">{s.plates_read} คัน{s.corrected ? ` · แก้ไขแล้ว ${s.corrected}` : ''}</div>
      </div>
    </Card>
  )
}

export function ResultsView({ job, partial }: { job: Job; partial?: boolean }) {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const video = useRef<HTMLVideoElement>(null)
  const rowRefs = useRef(new Map<number, HTMLDivElement>())

  const [q, setQ] = useState('')
  const [types, setTypes] = useState<VehicleType[]>([])
  const [minConf, setMinConf] = useState(0)
  const [plate, setPlate] = useState<EventFilters['plate'] | ''>('')
  const [rangeFrom, setRangeFrom] = useState('')
  const [rangeTo, setRangeTo] = useState('')
  const [showAdv, setShowAdv] = useState(false)
  const [events, setEvents] = useState<VehicleEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(job.duration_sec ?? 0)
  const [follow, setFollow] = useState(true)
  const [selected, setSelected] = useState<number | null>(null)

  const dq = useDebounced(q)
  const filters: EventFilters = useMemo(() => ({
    job_id: job.id, q: dq, type: types, min_conf: minConf || undefined, plate: plate || undefined,
    offset_from: parseOffset(rangeFrom) ?? undefined, offset_to: parseOffset(rangeTo) ?? undefined,
  }), [job.id, dq, types, minConf, plate, rangeFrom, rangeTo])

  useEffect(() => {
    setLoading(true)
    api.events(filters, { sort: 'offset', limit: 5000 }).then((r) => setEvents(r.items)).finally(() => setLoading(false))
  }, [filters])

  // ?t=123 → กระโดดไปวินาทีนั้น (มาจากหน้ารายละเอียด/ค้นหา)
  const initialT = Number(params.get('t'))
  const initialE = Number(params.get('e')) || null
  useEffect(() => { if (initialE) setSelected(initialE) }, [initialE])

  // รถที่อยู่ในภาพ ณ เวลาปัจจุบัน
  const activeId = useMemo(() => {
    let best: VehicleEvent | null = null
    for (const e of events) {
      const a = (e.first_seen_sec ?? e.video_offset_sec ?? 0) - 0.3
      const b = (e.last_seen_sec ?? e.video_offset_sec ?? 0) + 0.3
      if (current >= a && current <= b && (!best || Math.abs((e.video_offset_sec ?? 0) - current) < Math.abs((best.video_offset_sec ?? 0) - current))) best = e
    }
    return best?.id ?? null
  }, [events, current])

  const highlight = selected ?? activeId
  useEffect(() => {
    if (!follow || highlight == null) return
    rowRefs.current.get(highlight)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [highlight, follow])

  const seek = (e: VehicleEvent) => {
    setSelected(e.id)
    const v = video.current
    if (!v || e.video_offset_sec == null) return
    v.currentTime = e.video_offset_sec
    v.pause()
    v.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  const toggleType = (t: VehicleType) => setTypes((ts) => (ts.includes(t) ? ts.filter((x) => x !== t) : [...ts, t]))
  const hasFilters = !!(q || types.length || minConf || plate || rangeFrom || rangeTo)
  const clear = () => { setQ(''); setTypes([]); setMinConf(0); setPlate(''); setRangeFrom(''); setRangeTo('') }
  const src = job.video_url ?? job.source_video_url

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {partial && <span className="mr-auto text-sm text-muted">แสดงผลบางส่วนที่ประมวลผลได้ก่อนหยุด</span>}
        {!partial && job.summary?.typhoon && (
          <span className="mr-auto inline-flex items-center gap-1.5 text-sm text-violet-300">
            <Sparkles className="size-4" />Typhoon อ่านซ้ำแล้ว — แก้ผล {job.summary.typhoon_refined ?? 0} คัน
          </span>
        )}
        <a className={buttonVariants({ variant: 'secondary', size: 'sm' })} href={api.exportUrl(filters, 'xlsx', 'offset')}>
          <FileSpreadsheet />Excel
        </a>
        <a className={buttonVariants({ variant: 'secondary', size: 'sm' })} href={api.exportUrl(filters, 'csv', 'offset')}>
          <Download />CSV
        </a>
        <a className={buttonVariants({ variant: 'secondary', size: 'sm' })} href={api.imagesZipUrl(job.id)}>
          <FileArchive />รูปทั้งหมด (ZIP)
        </a>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.65fr)_minmax(360px,1fr)]">
        {/* ซ้าย: วิดีโอ + สรุป */}
        <div className="space-y-4">
          <Card className="overflow-hidden">
            {src ? (
              <video
                ref={video}
                src={src}
                controls
                playsInline
                preload="auto"
                className="aspect-video w-full bg-black"
                onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
                onSeeked={(e) => setCurrent(e.currentTarget.currentTime)}
                onPlay={() => setSelected(null)}
                onLoadedMetadata={(e) => {
                  setDuration(e.currentTarget.duration)
                  if (initialT) { e.currentTarget.currentTime = initialT; setCurrent(initialT) }
                }}
              />
            ) : (
              <div className="flex aspect-video items-center justify-center text-muted">ไม่มีวิดีโอผลลัพธ์</div>
            )}
            <Timeline events={events} duration={duration} current={current} activeId={highlight} onSeek={seek} />
          </Card>
          <SummaryPanel job={job} shown={events.length} />
          {job.summary && (!job.summary.plate_model || !job.summary.plate_ocr_model) && (
            <p className="text-xs text-muted">
              หมายเหตุ: วิดีโอนี้ประมวลผลโดยไม่มีโมเดลป้ายไทยครบ ({!job.summary.plate_model && 'plate.pt '}{!job.summary.plate_ocr_model && 'plate_ocr.pt'})
              — รัน <code className="font-mono">make models</code> แล้วกด “ประมวลผลใหม่” เพื่อให้อ่านป้ายได้แม่นขึ้น
            </p>
          )}
        </div>

        {/* ขวา: ค้นหา + รายการ */}
        <Card className="flex max-h-[calc(100vh-10rem)] min-h-[480px] flex-col lg:sticky lg:top-20">
          <div className="space-y-2 border-b border-line p-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ค้นหาเลขทะเบียน เช่น 1234 หรือ กข" className="pl-9" />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {VEHICLE_TYPES.map((t) => (
                <button key={t} onClick={() => toggleType(t)}
                  className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors',
                    types.includes(t) ? 'border-accent/50 bg-accent/15 text-fg' : 'border-line text-muted hover:text-fg')}>
                  <span className="size-2 rounded-full" style={{ background: TYPE_COLOR[t] }} />{TYPE_SHORT[t]}
                </button>
              ))}
              <Button variant="ghost" size="sm" className={cn('ml-auto h-7', showAdv && 'text-accent')} onClick={() => setShowAdv((s) => !s)}>
                <SlidersHorizontal />ตัวกรอง
              </Button>
            </div>
            {showAdv && (
              <div className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-bg/40 p-2.5 text-xs">
                <label className="space-y-1">
                  <span className="text-muted">ช่วงเวลาในวิดีโอ (ตั้งแต่)</span>
                  <Input value={rangeFrom} onChange={(e) => setRangeFrom(e.target.value)} placeholder="00:00" className="h-8 font-mono" />
                </label>
                <label className="space-y-1">
                  <span className="text-muted">ถึง</span>
                  <Input value={rangeTo} onChange={(e) => setRangeTo(e.target.value)} placeholder={fmtOffset(duration)} className="h-8 font-mono" />
                </label>
                <label className="space-y-1">
                  <span className="text-muted">ความมั่นใจขั้นต่ำ <b className="font-mono text-fg">{pct(minConf)}</b></span>
                  <input type="range" min={0} max={1} step={0.05} value={minConf} onChange={(e) => setMinConf(Number(e.target.value))} className="w-full" />
                </label>
                <label className="space-y-1">
                  <span className="text-muted">สถานะป้าย</span>
                  <Select value={plate} onChange={(e) => setPlate(e.target.value as EventFilters['plate'] | '')} className="h-8 text-xs">
                    <option value="">ทั้งหมด</option>
                    <option value="read">อ่านได้</option>
                    <option value="unread">อ่านไม่ได้</option>
                    <option value="corrected">แก้ไขแล้ว</option>
                  </Select>
                </label>
              </div>
            )}
            <div className="flex items-center justify-between text-[11px] text-muted">
              <span className="inline-flex items-center gap-1"><Filter className="size-3" />{loading ? 'กำลังโหลด…' : `${events.length} รายการ`}</span>
              <div className="flex items-center gap-3">
                {hasFilters && <button onClick={clear} className="inline-flex items-center gap-0.5 hover:text-fg"><X className="size-3" />ล้างตัวกรอง</button>}
                <label className="inline-flex cursor-pointer items-center gap-1">
                  <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-[var(--color-accent)]" />
                  เลื่อนตามวิดีโอ
                </label>
              </div>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {!loading && events.length === 0 && (
              <div className="p-10 text-center text-sm text-muted">{hasFilters ? 'ไม่พบรายการที่ตรงกับตัวกรอง' : 'ไม่พบรถในวิดีโอนี้'}</div>
            )}
            {events.map((e) => (
              <EventRow
                key={e.id}
                ref={(el) => { if (el) rowRefs.current.set(e.id, el); else rowRefs.current.delete(e.id) }}
                event={e}
                active={highlight === e.id}
                onClick={() => seek(e)}
                onDoubleClick={() => nav(`/events/${e.id}`)}
                action={
                  <Link to={`/events/${e.id}`} onClick={(ev) => ev.stopPropagation()} title="รายละเอียด / แก้ไข"
                    className="self-center rounded-md p-1.5 text-muted opacity-0 transition-opacity hover:bg-panel-2 hover:text-fg group-hover:opacity-100">
                    <ExternalLink className="size-4" />
                  </Link>
                }
              />
            ))}
          </div>
          <div className="border-t border-line px-3 py-2 text-[11px] text-muted">
            คลิกรายการเพื่อกระโดดไปวินาทีนั้น · ดับเบิลคลิกดูรายละเอียด
          </div>
        </Card>
      </div>
    </div>
  )
}

