import { Pause, Play, Plus, Radio, Trash2, Video, VideoOff, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EventRow } from '@/components/EventRow'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Label } from '@/components/ui/input'
import { api, type Camera, type CameraStatus, liveSocketUrl, type LiveMessage, type VehicleEvent } from '@/lib/api'
import { cn } from '@/lib/utils'

const STATE_TH: Record<CameraStatus['state'], { label: string; cls: string }> = {
  online: { label: 'ออนไลน์', cls: 'bg-ok' },
  starting: { label: 'กำลังเริ่ม', cls: 'bg-plate animate-pulse' },
  connecting: { label: 'กำลังเชื่อมต่อ', cls: 'bg-plate animate-pulse' },
  reconnecting: { label: 'กำลังต่อใหม่', cls: 'bg-plate animate-pulse' },
  stopped: { label: 'หยุดอยู่', cls: 'bg-muted' },
  error: { label: 'ผิดพลาด', cls: 'bg-danger' },
}

const URL_EXAMPLES = [
  { label: 'กล้องจำลอง (Docker)', url: 'rtsp://camsim:8554/cam1' },
  { label: 'Hikvision', url: 'rtsp://admin:รหัส@192.168.1.64:554/Streaming/Channels/101' },
  { label: 'Dahua', url: 'rtsp://admin:รหัส@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0' },
  { label: 'Webcam', url: '0' },
  { label: 'ไฟล์วิดีโอ (เล่นวน)', url: 'data/samples/live.mp4' },
]

/** รักษาการเชื่อมต่อ WebSocket หน้า Live — ต่อใหม่เองถ้าหลุด */
function useLiveSocket(onMessage: (m: LiveMessage) => void) {
  const handler = useRef(onMessage)
  handler.current = onMessage
  useEffect(() => {
    let ws: WebSocket | null = null
    let closed = false
    let retry: ReturnType<typeof setTimeout>
    const connect = () => {
      ws = new WebSocket(liveSocketUrl())
      ws.onmessage = (e) => handler.current(JSON.parse(e.data))
      ws.onclose = () => { if (!closed) retry = setTimeout(connect, 1500) }
    }
    connect()
    return () => { closed = true; clearTimeout(retry); ws?.close() }
  }, [])
}

function AddCamera({ onAdded, onCancel }: { onAdded: () => void; onCancel?: () => void }) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [location, setLocation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.addCamera({ name, url, location: location || undefined })
      onAdded()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card className="p-4">
      <form onSubmit={submit} className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="font-semibold">เพิ่มกล้อง</div>
          {onCancel && <button type="button" onClick={onCancel} className="text-muted hover:text-fg"><X className="size-4" /></button>}
        </div>
        <div className="grid gap-3 sm:grid-cols-[1fr_2fr_1fr]">
          <div>
            <Label>ชื่อกล้อง</Label>
            <Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="เช่น ประตูหน้า" />
          </div>
          <div>
            <Label>URL ของกล้อง</Label>
            <Input required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="rtsp://user:pass@192.168.1.64:554/..." className="font-mono text-xs" />
          </div>
          <div>
            <Label>สถานที่</Label>
            <Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="ไม่บังคับ" />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
          ตัวอย่าง:
          {URL_EXAMPLES.map((x) => (
            <button type="button" key={x.label} onClick={() => { setUrl(x.url); if (!name) setName(x.label) }}
              className="rounded-md border border-line px-2 py-0.5 hover:border-accent/50 hover:text-fg">{x.label}</button>
          ))}
        </div>
        {error && <div className="text-sm text-danger">{error}</div>}
        <Button type="submit" disabled={busy}><Plus />เพิ่มและเริ่มกล้อง</Button>
      </form>
    </Card>
  )
}

function CameraTile({ cam, status, onChanged }: { cam: Camera; status: CameraStatus; onChanged: () => void }) {
  const [imgKey, setImgKey] = useState(0)
  const online = status.state === 'online'
  const st = STATE_TH[status.state] ?? STATE_TH.stopped
  // สตรีมหลุด (เช่นกล้องต่อใหม่) → ขอภาพใหม่อัตโนมัติ
  const onImgError = () => setTimeout(() => setImgKey((k) => k + 1), 2000)
  const toggle = async () => {
    await (cam.enabled ? api.stopCamera(cam.id) : api.startCamera(cam.id)).catch((e) => alert(e.message))
    onChanged()
  }
  const remove = async () => {
    if (!confirm(`ลบกล้อง "${cam.name}" และรายการรถทั้งหมดของกล้องนี้?`)) return
    await api.deleteCamera(cam.id).catch((e) => alert(e.message))
    onChanged()
  }
  return (
    <Card className="overflow-hidden">
      <div className="relative aspect-video bg-black">
        {online ? (
          <img key={`${status.started_at}-${imgKey}`} src={api.mjpegUrl(cam.id, `${status.started_at}-${imgKey}`)}
            onError={onImgError} alt={cam.name} className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-sm text-muted">
            {cam.enabled ? <Video className="size-8 animate-pulse" /> : <VideoOff className="size-8" />}
            <div>{st.label}</div>
            {status.error && <div className="max-w-md text-xs text-danger/90">{status.error}</div>}
          </div>
        )}
        <div className="absolute left-2 top-2 flex items-center gap-1.5 rounded-full bg-bg/80 px-2 py-0.5 text-[11px] backdrop-blur">
          <span className={cn('size-1.5 rounded-full', st.cls)} />
          {online && <span className="font-semibold text-danger">LIVE</span>}
          <span>{online ? `${status.fps} fps` : st.label}</span>
          {online && status.width && <span className="text-muted">· {status.width}×{status.height}</span>}
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{cam.name}</div>
          <div className="truncate text-xs text-muted">{cam.location || cam.url}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-xs text-muted">วันนี้ <b className="font-mono text-fg">{cam.events_today}</b> คัน</span>
          <Button variant="ghost" size="icon" className="h-8 w-8" title={cam.enabled ? 'หยุด' : 'เริ่ม'} onClick={toggle}>
            {cam.enabled ? <Pause /> : <Play />}
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8 hover:text-danger" title="ลบกล้อง" onClick={remove}><Trash2 /></Button>
        </div>
      </div>
    </Card>
  )
}

export default function LivePage() {
  const nav = useNavigate()
  const [cams, setCams] = useState<Camera[] | null>(null)
  const [statuses, setStatuses] = useState<Record<string, CameraStatus>>({})
  const [events, setEvents] = useState<VehicleEvent[]>([])
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  const [updated, setUpdated] = useState<Set<number>>(new Set())
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    const list = await api.cameras()
    setCams(list)
    // รายการล่าสุดของทุกกล้อง
    const pages = await Promise.all(list.map((c) => api.events({ source_id: c.id }, { limit: 40 })))
    setEvents(pages.flatMap((p) => p.items).sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 200))
  }, [])
  useEffect(() => { load() }, [load])
  // จำนวนรถวันนี้ต่อกล้อง — รีเฟรชเป็นระยะ
  useEffect(() => {
    const t = setInterval(() => api.cameras().then(setCams).catch(() => {}), 15000)
    return () => clearInterval(t)
  }, [])

  useLiveSocket((m) => {
    if (m.type === 'cameras') setStatuses(m.cameras)
    else if (m.type === 'event') {
      setEvents((prev) => [m.event, ...prev.filter((e) => e.id !== m.event.id)].slice(0, 200))
      setFresh((s) => new Set(s).add(m.event.id))
      setCams((cs) => cs?.map((c) => (c.id === m.camera_id ? { ...c, events_today: c.events_today + 1 } : c)) ?? cs)
    } else if (m.type === 'event_update') {
      setEvents((prev) => prev.map((e) => (e.id === m.event.id ? m.event : e)))
      setUpdated((s) => new Set(s).add(m.event.id))
    }
  })

  const online = cams?.filter((c) => (statuses[c.id]?.state ?? c.status.state) === 'online').length ?? 0

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="flex items-center gap-2 text-xl font-semibold"><Radio className="size-5 text-danger" />Live</h1>
        {cams && <span className="text-sm text-muted">ออนไลน์ {online}/{cams.length} กล้อง</span>}
        {cams && cams.length > 0 && !adding && (
          <Button size="sm" variant="secondary" className="ml-auto" onClick={() => setAdding(true)}><Plus />เพิ่มกล้อง</Button>
        )}
      </div>

      {cams && (cams.length === 0 || adding) && (
        <AddCamera onAdded={() => { setAdding(false); load() }} onCancel={cams.length ? () => setAdding(false) : undefined} />
      )}
      {cams && cams.length === 0 && (
        <p className="text-sm text-muted">
          ยังไม่มีกล้อง — ถ้ายังไม่มีกล้องจริง ใช้ "กล้องจำลอง (Docker)" ซึ่งเล่นวิดีโอวนผ่าน RTSP เหมือนกล้อง IP
          (บน Mac ใช้ "ไฟล์วิดีโอ (เล่นวน)")
        </p>
      )}

      {cams && cams.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className={cn('grid gap-4', cams.length > 1 && 'md:grid-cols-2')}>
            {cams.map((c) => (
              <CameraTile key={c.id} cam={c} status={statuses[c.id] ?? c.status} onChanged={load} />
            ))}
          </div>
          <Card className="flex max-h-[calc(100vh-9rem)] min-h-[420px] flex-col xl:sticky xl:top-20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-danger opacity-75" /><span className="relative inline-flex size-2 rounded-full bg-danger" /></span>
                รถที่ผ่าน (สด)
              </CardTitle>
              <span className="font-mono text-xs text-muted">{events.length}</span>
            </CardHeader>
            <div className="flex-1 overflow-y-auto">
              {events.length === 0 ? (
                <div className="p-10 text-center text-sm text-muted">รถแต่ละคันจะปรากฏที่นี่ทันทีที่ออกจากภาพ</div>
              ) : (
                events.map((e) => (
                  <EventRow key={e.id} event={e} showSource fresh={fresh.has(e.id)} updated={updated.has(e.id)}
                    onClick={() => nav(`/events/${e.id}`)} />
                ))
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
