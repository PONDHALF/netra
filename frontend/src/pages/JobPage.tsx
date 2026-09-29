import { ArrowLeft, Clock, Cpu, MapPin, RotateCcw, Timer } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ProcessingView } from '@/components/ProcessingView'
import { ResultsView } from '@/components/ResultsView'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { api, type Job } from '@/lib/api'
import { fmtDateTime, fmtDuration } from '@/lib/utils'

export default function JobPage() {
  const id = Number(useParams().id)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => api.job(id).then(setJob).catch((e) => setError(e.message)), [id])
  useEffect(() => { load() }, [load])

  if (error) return <div className="py-20 text-center text-danger">{error}</div>
  if (!job) return <div className="py-20 text-center text-muted">กำลังโหลด…</div>

  const active = job.status === 'queued' || job.status === 'processing'
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link to="/" className="text-muted hover:text-fg"><ArrowLeft className="size-5" /></Link>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-xl font-semibold">{job.source.name}</h1>
            <StatusBadge status={job.status} />
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
            <span>{job.original_name}</span>
            {job.source.location && <span className="inline-flex items-center gap-1"><MapPin className="size-3" />{job.source.location}</span>}
            <span className="inline-flex items-center gap-1"><Clock className="size-3" />เริ่ม {fmtDateTime(job.video_start ?? job.created_at)}</span>
            {job.duration_sec != null && <span className="inline-flex items-center gap-1"><Timer className="size-3" />ยาว {fmtDuration(job.duration_sec)}</span>}
            {job.summary && (
              <span className="inline-flex items-center gap-1">
                <Cpu className="size-3" />ประมวลผล {fmtDuration(job.summary.elapsed_sec)} บน {job.summary.device.toUpperCase()}
              </span>
            )}
          </div>
        </div>
        {(job.status === 'failed' || job.status === 'cancelled') && (
          <Button variant="secondary" size="sm" className="ml-auto" onClick={() => api.retryJob(id).then(setJob)}>
            <RotateCcw />ประมวลผลใหม่
          </Button>
        )}
      </div>

      {job.status === 'failed' && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          ประมวลผลไม่สำเร็จ: {job.error}
        </div>
      )}

      {active ? (
        <ProcessingView job={job} onFinished={load} />
      ) : job.status === 'done' ? (
        <ResultsView job={job} />
      ) : (
        <ResultsView job={job} partial />
      )}
    </div>
  )
}
