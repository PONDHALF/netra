import { useEffect, useRef } from 'react'
import { jobSocketUrl, type WsMessage } from '@/lib/api'

/** เชื่อม WebSocket ของงาน และต่อใหม่อัตโนมัติถ้าหลุด (จนกว่า enabled = false) */
export function useJobSocket(jobId: number, enabled: boolean, onMessage: (m: WsMessage) => void) {
  const handler = useRef(onMessage)
  handler.current = onMessage

  useEffect(() => {
    if (!enabled) return
    let ws: WebSocket | null = null
    let closed = false
    let retry: ReturnType<typeof setTimeout>
    const connect = () => {
      ws = new WebSocket(jobSocketUrl(jobId))
      ws.onmessage = (e) => handler.current(JSON.parse(e.data))
      ws.onclose = () => { if (!closed) retry = setTimeout(connect, 1500) }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [jobId, enabled])
}
