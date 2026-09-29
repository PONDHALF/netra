import { Download, FileSpreadsheet, PlayCircle, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Thumb, TypeDot } from '@/components/EventRow'
import { PlateChip } from '@/components/Plate'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, Label, Select } from '@/components/ui/input'
import { api, type EventFilters, type Source, type VehicleEvent, type VehicleType } from '@/lib/api'
import { cn, confTone, fmtDateTime, fmtOffset, pct, TYPE_COLOR, TYPE_SHORT, VEHICLE_TYPES } from '@/lib/utils'

const PAGE = 100

export default function SearchPage() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') ?? '')
  const [types, setTypes] = useState<VehicleType[]>([])
  const [sourceId, setSourceId] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [sources, setSources] = useState<Source[]>([])
  const [items, setItems] = useState<VehicleEvent[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [applied, setApplied] = useState<EventFilters>({ q: params.get('q') ?? '' })

  useEffect(() => { api.sources().then(setSources).catch(() => {}) }, [])

  const filters = useMemo(() => applied, [applied])
  useEffect(() => {
    setLoading(true)
    api.events(filters, { limit: PAGE }).then((r) => { setItems(r.items); setTotal(r.total) }).finally(() => setLoading(false))
  }, [filters])

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault()
    setApplied({ q, type: types, source_id: sourceId ? Number(sourceId) : undefined, from: from || undefined, to: to || undefined })
    setParams(q ? { q } : {}, { replace: true })
  }
  // เปลี่ยนตัวกรองแบบคลิกแล้วค้นหาทันที
  useEffect(() => { submit() }, [types, sourceId]) // eslint-disable-line react-hooks/exhaustive-deps

  const more = async () => {
    setLoading(true)
    const r = await api.events(filters, { limit: PAGE, offset: items.length })
    setItems((xs) => [...xs, ...r.items])
    setLoading(false)
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">ค้นหาป้ายทะเบียน</h1>
        <p className="text-sm text-muted">ค้นหาข้ามทุกวิดีโอ รองรับการค้นหาบางส่วน เช่น “1234” หรือ “กข”</p>
      </div>

      <Card className="p-4">
        <form onSubmit={submit} className="space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3.5 top-1/2 size-5 -translate-y-1/2 text-muted" />
              <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="เลขทะเบียน หรือ จังหวัด"
                className="h-12 pl-11 text-lg" />
            </div>
            <Button type="submit" size="lg" className="h-12">ค้นหา</Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <Label>ประเภทรถ</Label>
              <div className="flex flex-wrap gap-1.5">
                {VEHICLE_TYPES.map((t) => (
                  <button type="button" key={t} onClick={() => setTypes((ts) => (ts.includes(t) ? ts.filter((x) => x !== t) : [...ts, t]))}
                    className={cn('inline-flex h-9 items-center gap-1.5 rounded-lg border px-2.5 text-xs transition-colors',
                      types.includes(t) ? 'border-accent/50 bg-accent/15' : 'border-line text-muted hover:text-fg')}>
                    <span className="size-2 rounded-full" style={{ background: TYPE_COLOR[t] }} />{TYPE_SHORT[t]}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <Label>กล้อง</Label>
              <Select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                <option value="">ทุกกล้อง</option>
                {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            </div>
            <div>
              <Label>ตั้งแต่</Label>
              <Input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} onBlur={() => submit()} />
            </div>
            <div>
              <Label>ถึง</Label>
              <Input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} onBlur={() => submit()} />
            </div>
          </div>
        </form>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-muted">{loading && !items.length ? 'กำลังค้นหา…' : <>พบ <b className="text-fg">{total.toLocaleString()}</b> รายการ</>}</div>
        <div className="flex gap-2">
          <a className={buttonVariants({ variant: 'secondary', size: 'sm' })} href={api.exportUrl(filters, 'xlsx')}><FileSpreadsheet />Excel</a>
          <a className={buttonVariants({ variant: 'secondary', size: 'sm' })} href={api.exportUrl(filters, 'csv')}><Download />CSV</a>
        </div>
      </div>

      <Card className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">รูปรถ</th>
              <th className="px-2 py-2.5 font-medium">ป้าย</th>
              <th className="px-2 py-2.5 font-medium">เลขทะเบียน</th>
              <th className="px-2 py-2.5 font-medium">ประเภท</th>
              <th className="px-2 py-2.5 font-medium">วันเวลา</th>
              <th className="px-2 py-2.5 font-medium">กล้อง</th>
              <th className="px-2 py-2.5 text-right font-medium">มั่นใจ</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id} onClick={() => nav(`/events/${e.id}`)} className="cursor-pointer border-b border-line/60 transition-colors last:border-0 hover:bg-panel-2/60">
                <td className="px-4 py-2"><Thumb src={e.car_img_url} alt="รถ" className="h-14 w-20" /></td>
                <td className="px-2 py-2">{e.plate_img_url ? <img src={e.plate_img_url} alt="" className="h-10 max-w-28 rounded border border-line object-contain" /> : <span className="text-muted">-</span>}</td>
                <td className="px-2 py-2"><PlateChip text={e.plate_text} province={e.plate_province} size="sm" /></td>
                <td className="px-2 py-2"><span className="inline-flex items-center gap-1.5"><TypeDot type={e.vehicle_type} />{TYPE_SHORT[e.vehicle_type]}</span></td>
                <td className="px-2 py-2 whitespace-nowrap">{fmtDateTime(e.ts)}</td>
                <td className="px-2 py-2 text-muted">{e.source_name}</td>
                <td className={cn('px-2 py-2 text-right font-mono', e.is_corrected ? 'text-accent' : confTone(e.plate_conf))}>
                  {e.is_corrected ? 'แก้ไข' : e.plate_text ? pct(e.plate_conf) : '-'}
                </td>
                <td className="px-4 py-2 text-right">
                  {e.job_id && (
                    <Link to={`/jobs/${e.job_id}?t=${e.video_offset_sec ?? 0}&e=${e.id}`} onClick={(ev) => ev.stopPropagation()}
                      className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
                      <PlayCircle className="size-4" />{fmtOffset(e.video_offset_sec)}
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && items.length === 0 && <div className="p-12 text-center text-sm text-muted">ไม่พบรายการ</div>}
      </Card>
      {items.length < total && (
        <div className="text-center">
          <Button variant="secondary" onClick={more} disabled={loading}>โหลดเพิ่ม ({(total - items.length).toLocaleString()} รายการ)</Button>
        </div>
      )}
    </div>
  )
}
