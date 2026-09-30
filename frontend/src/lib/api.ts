export type VehicleType = 'car' | 'motorcycle' | 'bus' | 'truck'
export type JobStatus = 'queued' | 'processing' | 'done' | 'failed' | 'cancelled'

export interface Source {
  id: number
  name: string
  type: 'video' | 'camera'
  location: string | null
  created_at: string
}

export interface JobStats {
  total: number
  by_type: Partial<Record<VehicleType, number>>
  plates_read: number
  corrected: number
}

export interface Job {
  id: number
  source: Source
  original_name: string
  status: JobStatus
  progress: number
  stage: string | null
  eta_sec: number | null
  error: string | null
  video_start: string | null
  duration_sec: number | null
  summary: {
    fps: number; width: number; height: number; total_frames: number; duration_sec: number
    events: number; elapsed_sec: number; device: string; plate_model: boolean; plate_ocr_model?: boolean; typhoon?: boolean; typhoon_refined?: number
  } | null
  use_typhoon: boolean
  created_at: string
  started_at: string | null
  finished_at: string | null
  stats: JobStats | null
  video_url: string | null
  source_video_url: string | null
  thumb_url: string | null
}

export interface VehicleEvent {
  id: number
  source_id: number
  job_id: number | null
  track_id: number
  ts: string
  video_offset_sec: number | null
  first_seen_sec: number | null
  last_seen_sec: number | null
  vehicle_type: VehicleType
  vehicle_conf: number
  plate_text: string | null
  plate_province: string | null
  plate_conf: number
  plate_valid: boolean
  ocr_raw: string | null
  ocr_engine: 'platenet+char' | 'platenet' | 'char-ocr' | 'easyocr' | 'typhoon' | null
  is_corrected: boolean
  original_plate_text: string | null
  original_plate_province: string | null
  corrected_at: string | null
  source_name: string | null
  car_img_url: string | null
  plate_img_url: string | null
}

export type CameraState = 'starting' | 'connecting' | 'online' | 'reconnecting' | 'stopped' | 'error'

export interface CameraStatus {
  state: CameraState
  fps: number
  error: string | null
  width: number | null
  height: number | null
  events: number
  started_at?: number
  hls?: string | null  // path ของวิดีโอ LL-HLS ใน MediaMTX (ถ้ามี) — ไม่มี = ใช้ MJPEG
}

export interface Camera {
  id: number
  name: string
  location: string | null
  url: string
  enabled: boolean
  events_today: number
  status: CameraStatus
}

export type LiveMessage =
  | { type: 'cameras'; cameras: Record<string, CameraStatus> }
  | { type: 'event' | 'event_update'; camera_id: number; event: VehicleEvent }
  | { type: 'ping' }

export interface EventFilters {
  q?: string
  type?: VehicleType[]
  from?: string
  to?: string
  job_id?: number
  source_id?: number
  min_conf?: number
  offset_from?: number
  offset_to?: number
  plate?: 'read' | 'unread' | 'corrected'
}

export type WsMessage =
  | { type: 'status'; status: JobStatus; progress: number; stage: string | null; error: string | null }
  | { type: 'progress'; progress: number; stage: string; eta_sec: number | null; fps: number; frame: number; total_frames: number; events: number }
  | { type: 'event'; event: VehicleEvent }
  | { type: 'event_update'; event: VehicleEvent }
  | { type: 'ping' }
  | { type: 'error'; message: string }

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export function filterParams(f: EventFilters, extra: Record<string, string | number | undefined> = {}): string {
  const p = new URLSearchParams()
  const add = (k: string, v: unknown) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  add('q', f.q?.trim())
  if (f.type?.length) add('type', f.type.join(','))
  add('from', f.from)
  add('to', f.to)
  add('job_id', f.job_id)
  add('source_id', f.source_id)
  add('min_conf', f.min_conf || undefined)
  add('offset_from', f.offset_from)
  add('offset_to', f.offset_to)
  add('plate', f.plate)
  for (const [k, v] of Object.entries(extra)) add(k, v)
  return p.toString()
}

export const api = {
  health: () => req<{ ok: boolean; engine_loaded: boolean; device: string | null; plate_model: boolean | null; plate_ocr_model: boolean | null; typhoon_available: boolean; typhoon_default: boolean; typhoon_loaded: boolean; busy_job: number | null }>('/api/health'),
  meta: () => req<{ provinces: string[]; vehicle_types: Record<VehicleType, string> }>('/api/meta'),
  sources: () => req<Source[]>('/api/sources'),
  jobs: () => req<Job[]>('/api/jobs'),
  job: (id: number) => req<Job>(`/api/jobs/${id}`),
  cancelJob: (id: number) => req<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: number) => req<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  deleteJob: (id: number) => req<void>(`/api/jobs/${id}`, { method: 'DELETE' }),
  events: (f: EventFilters, opts: { sort?: 'ts' | 'offset' | 'conf'; limit?: number; offset?: number } = {}) =>
    req<{ items: VehicleEvent[]; total: number }>(`/api/events?${filterParams(f, opts)}`),
  event: (id: number) => req<VehicleEvent>(`/api/events/${id}`),
  patchEvent: (id: number, body: Partial<Pick<VehicleEvent, 'plate_text' | 'plate_province' | 'vehicle_type'>>) =>
    req<VehicleEvent>(`/api/events/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }),
  cameras: () => req<Camera[]>('/api/cameras'),
  addCamera: (body: { name: string; url: string; location?: string }) =>
    req<Camera>('/api/cameras', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  startCamera: (id: number) => req<Camera>(`/api/cameras/${id}/start`, { method: 'POST' }),
  stopCamera: (id: number) => req<Camera>(`/api/cameras/${id}/stop`, { method: 'POST' }),
  deleteCamera: (id: number) => req<void>(`/api/cameras/${id}`, { method: 'DELETE' }),
  mjpegUrl: (id: number, bust: string | number = '') => `/api/cameras/${id}/mjpeg?k=${bust}`,
  exportUrl: (f: EventFilters, format: 'xlsx' | 'csv', sort: 'ts' | 'offset' = 'ts') =>
    `/api/events/export?${filterParams(f, { format, sort })}`,
  imagesZipUrl: (jobId: number) => `/api/jobs/${jobId}/images.zip`,
}

/** อัปโหลดด้วย XHR เพื่อให้แสดงเปอร์เซ็นต์การอัปโหลดได้ */
export function uploadVideo(
  file: File,
  fields: { source_name: string; location: string; video_start: string; use_typhoon: boolean },
  onProgress: (frac: number) => void,
): { promise: Promise<Job>; abort: () => void } {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<Job>((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    for (const [k, v] of Object.entries(fields)) if (v) form.append(k, String(v))
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText))
      else {
        let msg = `อัปโหลดไม่สำเร็จ (${xhr.status})`
        try { msg = JSON.parse(xhr.responseText).detail ?? msg } catch { /* ignore */ }
        reject(new Error(msg))
      }
    }
    xhr.onerror = () => reject(new Error('เชื่อมต่อเซิร์ฟเวอร์ไม่ได้'))
    xhr.onabort = () => reject(new Error('ยกเลิกการอัปโหลด'))
    xhr.open('POST', '/api/videos')
    xhr.send(form)
  })
  return { promise, abort: () => xhr.abort() }
}

export function liveSocketUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/live`
}

export function jobSocketUrl(id: number) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/jobs/${id}`
}
