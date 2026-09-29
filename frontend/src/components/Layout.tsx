import { Cpu, Radio, Search, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path d="M3 16s5-9 13-9 13 9 13 9-5 9-13 9S3 16 3 16Z" fill="none" stroke="var(--color-accent)" strokeWidth="2.2" />
      <circle cx="16" cy="16" r="4.6" fill="var(--color-plate)" />
      <circle cx="16" cy="16" r="1.6" fill="var(--color-bg)" />
    </svg>
  )
}

function EngineStatus() {
  const [h, setH] = useState<Awaited<ReturnType<typeof api.health>> | null>(null)
  const [down, setDown] = useState(false)
  useEffect(() => {
    let alive = true
    const tick = () =>
      api.health().then((r) => { if (alive) { setH(r); setDown(false) } }).catch(() => alive && setDown(true))
    tick()
    const t = setInterval(tick, 5000)
    return () => { alive = false; clearInterval(t) }
  }, [])
  const label = down ? 'API ออฟไลน์' : !h ? '...' : h.engine_loaded ? `AI พร้อม · ${h.device?.toUpperCase()}${h.typhoon_loaded ? ' · Typhoon' : ''}` : 'กำลังโหลด AI'
  return (
    <div className="hidden items-center gap-2 rounded-full border border-line bg-panel px-3 py-1 text-[11px] text-muted sm:flex"
      title={h?.engine_loaded ? [
        h.plate_model ? 'ตรวจจับป้าย: plate.pt' : 'ไม่มี plate.pt — ใช้โหมดสำรอง EasyOCR',
        h.plate_ocr_model ? 'อ่านป้าย: plate_ocr.pt + EasyOCR' : 'อ่านป้าย: EasyOCR อย่างเดียว',
        h.typhoon_available ? `Typhoon OCR 3B: พร้อมใช้${h.typhoon_loaded ? ' (กำลังใช้งาน)' : ''}` : 'Typhoon OCR 3B: ยังไม่ได้ติดตั้ง (make typhoon)',
      ].join('\n') : undefined}>
      <span className={cn('size-1.5 rounded-full', down ? 'bg-danger' : !h?.engine_loaded ? 'bg-plate' : h.plate_model && h.plate_ocr_model ? 'bg-ok animate-pulse' : 'bg-plate animate-pulse')} />
      <Cpu className="size-3" />
      {label}
      {h?.busy_job != null && <span className="text-accent">· งาน #{h.busy_job}</span>}
    </div>
  )
}

export function Layout() {
  const link = ({ isActive }: { isActive: boolean }) =>
    cn('inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors',
      isActive ? 'bg-panel-2 text-fg' : 'text-muted hover:text-fg')
  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4">
          <NavLink to="/" className="flex items-center gap-2">
            <Logo className="size-7" />
            <span className="font-mono text-lg font-medium tracking-[0.2em]">NETRA</span>
          </NavLink>
          <nav className="flex items-center gap-1">
            <NavLink to="/live" className={link}><Radio className="size-4" />Live</NavLink>
            <NavLink to="/" end className={link}><Upload className="size-4" />อัปโหลด</NavLink>
            <NavLink to="/search" className={link}><Search className="size-4" />ค้นหาป้าย</NavLink>
          </nav>
          <div className="ml-auto"><EngineStatus /></div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
