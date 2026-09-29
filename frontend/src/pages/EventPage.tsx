import { ArrowLeft, Check, PencilLine, PlayCircle, RotateCcw, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Thumb, TypeDot } from '@/components/EventRow'
import { PlateChip } from '@/components/Plate'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Label, Select } from '@/components/ui/input'
import { api, type VehicleEvent, type VehicleType } from '@/lib/api'
import { cn, confTone, fmtDateTime, fmtOffset, pct, TYPE_TH, VEHICLE_TYPES } from '@/lib/utils'

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line/60 py-2 text-sm last:border-0">
      <span className="text-muted">{k}</span>
      <span className="text-right">{children}</span>
    </div>
  )
}

export default function EventPage() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const [e, setE] = useState<VehicleEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [provinces, setProvinces] = useState<string[]>([])
  const [text, setText] = useState('')
  const [prov, setProv] = useState('')
  const [vtype, setVtype] = useState<VehicleType>('car')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.event(id).then((ev) => {
      setE(ev)
      setText(ev.plate_text ?? '')
      setProv(ev.plate_province ?? '')
      setVtype(ev.vehicle_type)
    }).catch((err) => setError(err.message))
    api.meta().then((m) => setProvinces(m.provinces)).catch(() => {})
  }, [id])

  if (error) return <div className="py-20 text-center text-danger">{error}</div>
  if (!e) return <div className="py-20 text-center text-muted">กำลังโหลด…</div>

  const dirty = text.trim() !== (e.plate_text ?? '') || prov !== (e.plate_province ?? '') || vtype !== e.vehicle_type
  const save = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setSaving(true)
    try {
      const updated = await api.patchEvent(e.id, { plate_text: text, plate_province: prov, vehicle_type: vtype })
      setE(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      alert((err as Error).message)
    } finally {
      setSaving(false)
    }
  }
  const restore = () => {
    setText(e.original_plate_text ?? '')
    setProv(e.original_plate_province ?? '')
  }
  const videoLink = e.job_id ? `/jobs/${e.job_id}?t=${e.video_offset_sec ?? 0}&e=${e.id}` : null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => nav(-1)} className="text-muted hover:text-fg"><ArrowLeft className="size-5" /></button>
        <h1 className="text-xl font-semibold">รายละเอียดรถ <span className="font-mono text-muted">#{e.id}</span></h1>
        {e.is_corrected && (
          <span className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs text-accent">
            <PencilLine className="size-3" />แก้ไขด้วยมือแล้ว
          </span>
        )}
        {videoLink && (
          <Link to={videoLink} className={cn(buttonVariants({ variant: 'secondary', size: 'sm' }), 'ml-auto')}>
            <PlayCircle />ดูในวิดีโอ ({fmtOffset(e.video_offset_sec)})
          </Link>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr] lg:items-start">
        <Card className="overflow-hidden">
          <div className="flex items-center justify-center bg-black/60">
            <Thumb src={e.car_img_url} alt="รูปรถ" className="max-h-[75vh] min-h-64 w-full rounded-none object-contain" />
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>ป้ายทะเบียน</CardTitle>
              <span className={cn('font-mono text-sm', e.is_corrected ? 'text-accent' : confTone(e.plate_conf))}>
                {e.is_corrected ? 'ยืนยันแล้ว' : `ความมั่นใจ ${pct(e.plate_conf)}`}
              </span>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex min-h-28 items-center justify-center rounded-lg border border-line bg-black/50 p-3">
                {e.plate_img_url ? (
                  <img src={e.plate_img_url} alt="รูปป้าย" className="max-h-32 w-auto rounded [image-rendering:auto]" />
                ) : (
                  <span className="text-sm text-muted">ไม่พบภาพป้าย</span>
                )}
              </div>
              <div className="flex justify-center">
                <PlateChip text={e.plate_text} province={e.plate_province} size="lg" />
              </div>
              {e.is_corrected && (
                <div className="text-center text-xs text-muted">
                  AI อ่านได้เดิม: <span className="font-medium text-fg/80">{e.original_plate_text ?? '(อ่านไม่ได้)'} {e.original_plate_province ?? ''}</span>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>แก้ไขเลขทะเบียน</CardTitle></CardHeader>
            <form onSubmit={save}>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-[1fr_1.2fr] gap-2">
                  <div>
                    <Label htmlFor="pt">เลขทะเบียน</Label>
                    <Input id="pt" value={text} onChange={(ev) => setText(ev.target.value)} placeholder="เช่น 1กข 1234" className="font-semibold" />
                  </div>
                  <div>
                    <Label htmlFor="pv">จังหวัด</Label>
                    <Input id="pv" list="provinces" value={prov} onChange={(ev) => setProv(ev.target.value)} placeholder="พิมพ์เพื่อค้นหา" />
                    <datalist id="provinces">{provinces.map((p) => <option key={p} value={p} />)}</datalist>
                  </div>
                </div>
                <div>
                  <Label htmlFor="vt">ประเภทรถ</Label>
                  <Select id="vt" value={vtype} onChange={(ev) => setVtype(ev.target.value as VehicleType)}>
                    {VEHICLE_TYPES.map((t) => <option key={t} value={t}>{TYPE_TH[t]}</option>)}
                  </Select>
                </div>
                <div className="flex items-center gap-2">
                  <Button type="submit" disabled={!dirty || saving}>
                    {saved ? <><Check />บันทึกแล้ว</> : <><Save />บันทึก</>}
                  </Button>
                  {e.is_corrected && (
                    <Button type="button" variant="ghost" size="sm" onClick={restore}><RotateCcw />ค่าที่ AI อ่าน</Button>
                  )}
                </div>
                <p className="text-[11px] leading-relaxed text-muted">
                  ข้อมูลที่แก้ไขจะถูกเก็บพร้อมภาพป้ายใน <code className="font-mono">data/corrections/</code> เพื่อใช้เทรน AI รอบถัดไป
                </p>
              </CardContent>
            </form>
          </Card>

          <Card>
            <CardContent className="py-2">
              <Row k="ประเภทรถ"><span className="inline-flex items-center gap-1.5"><TypeDot type={e.vehicle_type} />{TYPE_TH[e.vehicle_type]} <span className="font-mono text-xs text-muted">({pct(e.vehicle_conf)})</span></span></Row>
              <Row k="วันเวลา">{fmtDateTime(e.ts)}</Row>
              <Row k="เวลาในวิดีโอ"><span className="font-mono">{fmtOffset(e.video_offset_sec, true)}</span> <span className="text-xs text-muted">(อยู่ในภาพ {fmtOffset(e.first_seen_sec)}–{fmtOffset(e.last_seen_sec)})</span></Row>
              <Row k="กล้อง">{e.source_name}</Row>
              <Row k="Track ID"><span className="font-mono">{e.track_id}</span></Row>
              {e.ocr_engine && <Row k="ตัวอ่านที่ให้เลขทะเบียน">{({ 'platenet+char': 'PlateNet + char-OCR (อ่านตรงกัน)', platenet: 'PlateNet (โมเดลที่เทรนเอง)', 'char-ocr': 'โมเดลรายตัวอักษร (plate_ocr.pt)', easyocr: 'EasyOCR', typhoon: 'Typhoon OCR 3B' } as Record<string, string>)[e.ocr_engine] ?? e.ocr_engine}</Row>}
              {e.ocr_raw && <Row k="OCR ดิบ"><span className="font-mono text-xs text-muted">{e.ocr_raw}</span></Row>}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
