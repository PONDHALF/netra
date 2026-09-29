import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { VehicleType } from './api'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const TYPE_TH: Record<VehicleType, string> = {
  car: 'รถยนต์',
  motorcycle: 'จักรยานยนต์',
  bus: 'รถบัส',
  truck: 'รถบรรทุก',
}
export const TYPE_SHORT: Record<VehicleType, string> = {
  car: 'รถยนต์',
  motorcycle: 'จยย.',
  bus: 'รถบัส',
  truck: 'บรรทุก',
}
export const TYPE_COLOR: Record<VehicleType, string> = {
  car: 'var(--color-car)',
  motorcycle: 'var(--color-motorcycle)',
  bus: 'var(--color-bus)',
  truck: 'var(--color-truck)',
}
export const VEHICLE_TYPES: VehicleType[] = ['car', 'motorcycle', 'bus', 'truck']

/** backend ส่งเวลาแบบไม่มี timezone (เวลาท้องถิ่น) และมีทศนิยม 6 หลัก */
export function parseDate(s: string | null | undefined): Date | null {
  if (!s) return null
  return new Date(s.replace(/(\.\d{3})\d+/, '$1'))
}

export function fmtOffset(sec: number | null | undefined, withHours = false): string {
  if (sec == null || Number.isNaN(sec)) return '--:--'
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(r).padStart(2, '0')
  return h || withHours ? `${String(h).padStart(2, '0')}:${mm}:${ss}` : `${mm}:${ss}`
}

export function parseOffset(s: string): number | null {
  const parts = s.trim().split(':').map(Number)
  if (!s.trim() || parts.some(Number.isNaN)) return null
  return parts.reduce((acc, p) => acc * 60 + p, 0)
}

const dtf = new Intl.DateTimeFormat('th-TH', {
  day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
})
const tf = new Intl.DateTimeFormat('th-TH', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export function fmtDateTime(s: string | null | undefined): string {
  const d = parseDate(s)
  return d ? dtf.format(d) : '-'
}
export function fmtTime(s: string | null | undefined): string {
  const d = parseDate(s)
  return d ? tf.format(d) : '-'
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return '-'
  if (sec < 60) return `${Math.round(sec)} วินาที`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return s ? `${m} นาที ${s} วินาที` : `${m} นาที`
}

export const pct = (v: number, digits = 0) => `${(v * 100).toFixed(digits)}%`

/** ค่าเริ่มต้นของ <input type="datetime-local"> */
export function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

export function confTone(conf: number): string {
  if (conf >= 0.8) return 'text-ok'
  if (conf >= 0.5) return 'text-plate'
  return 'text-danger'
}
