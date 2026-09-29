import { Clock, FileVideo, Film, MapPin, RotateCcw, Sparkles, Trash2, UploadCloud, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Label } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { api, type Job, type Source, uploadVideo } from '@/lib/api'
import { cn, fmtDateTime, fmtDuration, pct, toLocalInput, TYPE_SHORT } from '@/lib/utils'

const ACCEPT = '.mp4,.avi,.mkv,.mov,.m4v,.ts'

function fmtSize(b: number) {
  return b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`
}

function Dropzone({ file, onFile }: { file: File | null; onFile: (f: File | null) => void }) {
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        const f = e.dataTransfer.files?.[0]
        if (f) onFile(f)
      }}
      onClick={() => input.current?.click()}
      className={cn(
        'relative flex min-h-56 cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-6 text-center transition-colors',
        over ? 'border-accent bg-accent/5' : 'border-line hover:border-accent/50 hover:bg-panel-2/40',
      )}
    >
      <input ref={input} type="file" accept={ACCEPT} className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      {file ? (
        <>
          <FileVideo className="size-10 text-accent" />
          <div>
            <div className="font-medium">{file.name}</div>
            <div className="text-xs text-muted">{fmtSize(file.size)}</div>
          </div>
          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); onFile(null) }}>
            <X />เปลี่ยนไฟล์
          </Button>
        </>
      ) : (
        <>
          <div className="rounded-full border border-line bg-panel-2 p-4"><UploadCloud className="size-8 text-accent" /></div>
          <div>
            <div className="font-medium">ลากไฟล์วิดีโอมาวางที่นี่ หรือคลิกเพื่อเลือกไฟล์</div>
            <div className="mt-1 text-xs text-muted">MP4 · AVI · MKV · MOV — จากกล้องวงจรปิดที่มีอยู่</div>
          </div>
        </>
      )}
    </div>
  )
}

function JobCard({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const s = job.stats
  const del = async (e: React.MouseEvent) => {
    e.preventDefault()
    if (!confirm(`ลบวิดีโอ "${job.original_name}" และผลลัพธ์ทั้งหมด?`)) return
    await api.deleteJob(job.id).catch((err) => alert(err.message))
    onChanged()
  }
  const retry = async (e: React.MouseEvent) => {
    e.preventDefault()
    await api.retryJob(job.id).catch((err) => alert(err.message))
    onChanged()
  }
  return (
    <Link to={`/jobs/${job.id}`} className="group block">
      <Card className="overflow-hidden transition-colors group-hover:border-accent/40">
        <div className="relative aspect-video bg-black">
          {job.thumb_url ? (
            <img src={job.thumb_url} alt="" className="h-full w-full object-cover opacity-80 transition-opacity group-hover:opacity-100" />
          ) : (
            <div className="flex h-full items-center justify-center text-muted"><Film className="size-8" /></div>
          )}
          <StatusBadge status={job.status} className="absolute left-2 top-2 bg-bg/80 backdrop-blur" />
          {job.use_typhoon && (
            <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full border border-violet-400/40 bg-bg/80 px-2 py-0.5 text-[11px] text-violet-300 backdrop-blur">
              <Sparkles className="size-3" />Typhoon
            </span>
          )}
          {job.duration_sec != null && (
            <span className="absolute bottom-2 right-2 rounded bg-bg/80 px-1.5 py-0.5 font-mono text-[11px]">{fmtDuration(job.duration_sec)}</span>
          )}
          {(job.status === 'processing' || job.status === 'queued') && (
            <Progress value={job.progress} className="absolute inset-x-0 bottom-0 h-1 rounded-none" />
          )}
        </div>
        <div className="space-y-1.5 p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-medium">{job.source.name}</div>
              <div className="truncate text-xs text-muted">{job.original_name}</div>
            </div>
            <div className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100">
              {(job.status === 'failed' || job.status === 'cancelled') && (
                <Button variant="ghost" size="icon" className="h-7 w-7" title="ประมวลผลใหม่" onClick={retry}><RotateCcw /></Button>
              )}
              {job.status !== 'processing' && (
                <Button variant="ghost" size="icon" className="h-7 w-7 hover:text-danger" title="ลบ" onClick={del}><Trash2 /></Button>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            {job.source.location && <span className="inline-flex items-center gap-1"><MapPin className="size-3" />{job.source.location}</span>}
            <span className="inline-flex items-center gap-1"><Clock className="size-3" />{fmtDateTime(job.video_start ?? job.created_at)}</span>
          </div>
          {s && s.total > 0 && (
            <div className="flex flex-wrap gap-x-3 text-xs">
              <span><b className="text-fg">{s.total}</b> <span className="text-muted">คัน</span></span>
              {Object.entries(s.by_type).map(([t, n]) => (
                <span key={t} className="text-muted">{TYPE_SHORT[t as keyof typeof TYPE_SHORT] ?? t} {n}</span>
              ))}
              <span className="text-muted">อ่านป้ายได้ <b className="text-ok">{pct(s.plates_read / s.total)}</b></span>
            </div>
          )}
          {job.status === 'failed' && <div className="line-clamp-2 text-xs text-danger">{job.error}</div>}
        </div>
      </Card>
    </Link>
  )
}

export default function UploadPage() {
  const nav = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [sourceName, setSourceName] = useState('')
  const [location, setLocation] = useState('')
  const [start, setStart] = useState(() => toLocalInput(new Date()))
  const [uploading, setUploading] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const abortRef = useRef<() => void>(undefined)
  const [typhoon, setTyphoon] = useState(false)
  const [typhoonReady, setTyphoonReady] = useState<boolean | null>(null)

  useEffect(() => {
    api.health().then((h) => { setTyphoonReady(h.typhoon_available); setTyphoon(h.typhoon_available && h.typhoon_default) })
      .catch(() => setTyphoonReady(false))
  }, [])

  const refresh = useCallback(() => {
    api.jobs().then(setJobs).catch(() => setJobs([]))
    api.sources().then(setSources).catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh])

  const pickFile = (f: File | null) => {
    setFile(f)
    setError(null)
    if (f && !sourceName) setSourceName(f.name.replace(/\.[^.]+$/, ''))
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    setError(null)
    setUploading(0)
    const { promise, abort } = uploadVideo(file, { source_name: sourceName, location, video_start: start, use_typhoon: typhoon }, setUploading)
    abortRef.current = abort
    try {
      const job = await promise
      nav(`/jobs/${job.id}`)
    } catch (err) {
      setError((err as Error).message)
      setUploading(null)
    }
  }

  return (
    <div className="space-y-10">
      <section className="grid gap-6 lg:grid-cols-[1fr_1.3fr] lg:items-center">
        <div className="space-y-4">
          <div className="inline-flex items-center gap-2 rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-xs text-accent">
            Phase 1 · Mockup
          </div>
          <h1 className="text-3xl font-bold leading-tight md:text-4xl">
            ตรวจจับรถ อ่านป้ายทะเบียนไทย<br />
            <span className="text-muted">จากวิดีโอกล้องวงจรปิด</span>
          </h1>
          <p className="max-w-lg text-muted">
            อัปโหลดวิดีโอ ระบบจะหารถทุกคัน เลือกภาพที่ชัดที่สุด อ่านเลขทะเบียนและจังหวัด
            แล้วสรุปเป็นรายการที่คลิกกระโดดไปดูในวิดีโอได้ทันที
          </p>
          <ol className="grid max-w-lg grid-cols-3 gap-2 text-xs text-muted">
            {['ตรวจจับ + ติดตามรถ', 'เลือกภาพชัดที่สุด', 'อ่านป้าย (OCR)'].map((s, i) => (
              <li key={s} className="rounded-lg border border-line bg-panel/60 p-2">
                <span className="font-mono text-accent">0{i + 1}</span> {s}
              </li>
            ))}
          </ol>
        </div>

        <Card>
          <form onSubmit={submit}>
            <CardContent className="space-y-4">
              <Dropzone file={file} onFile={pickFile} />
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <Label htmlFor="src">ชื่อกล้อง</Label>
                  <Input id="src" list="sources" value={sourceName} onChange={(e) => setSourceName(e.target.value)} placeholder="เช่น กล้องประตูหน้า" />
                  <datalist id="sources">{sources.map((s) => <option key={s.id} value={s.name} />)}</datalist>
                </div>
                <div>
                  <Label htmlFor="loc">สถานที่</Label>
                  <Input id="loc" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="เช่น ถ.พหลโยธิน ขาเข้า" />
                </div>
                <div>
                  <Label htmlFor="start">วันเวลาเริ่มของวิดีโอ</Label>
                  <Input id="start" type="datetime-local" step={1} value={start} onChange={(e) => setStart(e.target.value)} />
                </div>
              </div>
              <label className={cn('flex items-start gap-3 rounded-lg border p-3 transition-colors',
                typhoonReady ? 'cursor-pointer' : 'cursor-not-allowed opacity-60',
                typhoon ? 'border-violet-400/50 bg-violet-400/10' : 'border-line bg-bg/40 hover:border-violet-400/30')}>
                <input type="checkbox" className="mt-1 accent-violet-400" checked={typhoon} disabled={!typhoonReady}
                  onChange={(e) => setTyphoon(e.target.checked)} />
                <div className="text-sm">
                  <div className="flex items-center gap-1.5 font-medium">
                    <Sparkles className="size-4 text-violet-300" />อ่านป้ายซ้ำด้วย Typhoon OCR 3B
                  </div>
                  <div className="mt-0.5 text-xs leading-relaxed text-muted">
                    {typhoonReady === false
                      ? <>ยังไม่ได้ติดตั้ง — รัน <code className="font-mono">make typhoon</code> (~7.5 GB) แล้วรีเฟรชหน้านี้</>
                      : <>หลังวิเคราะห์เสร็จ จะให้ Typhoon อ่านป้ายซ้ำทีละคัน — แม่นขึ้นมากกับป้ายเล็ก/เบลอ และช่วยอ่านจังหวัด
                        แต่ช้าลง ~2 วินาทีต่อคัน และใช้แรม ~8 GB ระหว่างอ่าน</>}
                  </div>
                </div>
              </label>
              {error && <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>}
              {uploading != null ? (
                <div className="space-y-2">
                  <div className="flex justify-between text-xs text-muted">
                    <span>{uploading < 1 ? 'กำลังอัปโหลด…' : 'กำลังสร้างงาน…'}</span>
                    <span className="font-mono">{pct(uploading)}</span>
                  </div>
                  <Progress value={uploading} />
                  <Button type="button" variant="ghost" size="sm" onClick={() => abortRef.current?.()}>ยกเลิก</Button>
                </div>
              ) : (
                <Button type="submit" size="lg" className="w-full" disabled={!file}>
                  <UploadCloud />อัปโหลดและเริ่มประมวลผล
                </Button>
              )}
            </CardContent>
          </form>
        </Card>
      </section>

      <section>
        <Card className="border-none bg-transparent">
          <CardHeader className="border-none px-0">
            <CardTitle className="text-base">วิดีโอที่เคยอัปโหลด</CardTitle>
            {jobs && <span className="text-xs text-muted">{jobs.length} รายการ</span>}
          </CardHeader>
          {jobs && jobs.length === 0 && (
            <div className="rounded-xl border border-dashed border-line p-10 text-center text-sm text-muted">ยังไม่มีวิดีโอ</div>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {jobs?.map((j) => <JobCard key={j.id} job={j} onChanged={refresh} />)}
          </div>
        </Card>
      </section>
    </div>
  )
}
