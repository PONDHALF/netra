"""ส่งภาพสดที่วาดกรอบแล้วเป็นวิดีโอ H.264 เข้า MediaMTX ให้เบราว์เซอร์เล่นแบบ LL-HLS

ทำไมไม่ใช้ MJPEG อย่างเดียว: JPEG ทีละเฟรมกินเน็ต ~55 KB × 10 fps ≈ 4.5 Mbps และต้องจำกัด fps —
H.264 ที่ 30 fps ใช้ ~1–2 Mbps และกรอบตรงกับเฟรมเสมอ (กรอบถูกวาดลงภาพก่อนเข้ารหัส) แลกกับดีเลย์ ~1–2 วินาที

เปิดใช้เมื่อกำหนด NETRA_HLS_RTSP (เช่น rtsp://camsim:8554 — MediaMTX ใน docker-compose) ถ้าไม่กำหนดหรือ ffmpeg ใช้ไม่ได้
หน้าเว็บจะใช้ MJPEG ตามเดิม
"""
from __future__ import annotations

import logging
import os
import queue
import socket
import subprocess
import threading
from urllib.parse import urlsplit, urlunsplit

import numpy as np

log = logging.getLogger("netra.hls")

HLS_RTSP = os.getenv("NETRA_HLS_RTSP", "").strip().rstrip("/")
OUT_FPS = 30


def enabled() -> bool:
    return bool(HLS_RTSP)


def _ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        import shutil

        return shutil.which("ffmpeg")


def _resolve(url: str) -> str:
    """แปลงชื่อโฮสต์ใน URL เป็น IP ก่อนส่งให้ ffmpeg — ffmpeg แบบ static (imageio-ffmpeg) พัง (segfault) ตอนหาชื่อโฮสต์ใน Docker."""
    u = urlsplit(url)
    ip = socket.gethostbyname(u.hostname)
    return urlunsplit(u._replace(netloc=f"{ip}:{u.port}" if u.port else ip))


class VideoPublisher:
    """เขียนเฟรม BGR ลง ffmpeg (stdin) → H.264 → RTSP (MediaMTX). เขียนใน thread แยก และทิ้งเฟรมเมื่อ ffmpeg ตามไม่ทัน
    เพื่อไม่ให้ลูปประมวลผลค้าง"""

    def __init__(self, path: str, width: int, height: int):
        self.path, self.w, self.h = path, width - width % 2, height - height % 2  # H.264 ต้องมีขนาดเป็นเลขคู่
        self.alive = False
        self._q: queue.Queue = queue.Queue(maxsize=3)
        self._proc: subprocess.Popen | None = None
        exe = _ffmpeg()
        if not enabled() or exe is None:
            return
        try:
            base = _resolve(HLS_RTSP)
        except OSError as e:
            log.warning("หา MediaMTX (%s) ไม่พบ: %s — ใช้ MJPEG แทน", HLS_RTSP, e)
            return
        cmd = [exe, "-hide_banner", "-loglevel", "error",
               # เวลาของเฟรม = เวลาที่ได้รับ (ประมวลผลไม่เท่ากันทุกเฟรม) แล้วแปลงเป็น 30 fps คงที่
               "-use_wallclock_as_timestamps", "1", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{self.w}x{self.h}", "-i", "-",
               "-vf", f"fps={OUT_FPS}", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
               "-pix_fmt", "yuv420p", "-threads", "4", "-b:v", "3M", "-maxrate", "3M", "-bufsize", "3M",
               # keyframe ทุก 1 วินาที = ขอบ segment ของ HLS
               "-g", str(OUT_FPS), "-keyint_min", str(OUT_FPS), "-sc_threshold", "0",
               "-f", "rtsp", "-rtsp_transport", "tcp", f"{base}/{path}"]
        try:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception as e:  # noqa: BLE001
            log.warning("เปิด ffmpeg สำหรับ HLS ไม่สำเร็จ: %s", e)
            return
        self.alive = True
        threading.Thread(target=self._write_loop, daemon=True, name=f"netra-hls-{path}").start()
        threading.Thread(target=self._watch_stderr, daemon=True, name=f"netra-hls-{path}-log").start()
        log.info("ส่งภาพสดเข้า MediaMTX: %s (%dx%d)", path, self.w, self.h)

    def write(self, frame: np.ndarray) -> None:
        if not self.alive:
            return
        if frame.shape[1] != self.w or frame.shape[0] != self.h:
            frame = frame[: self.h, : self.w]
        try:
            self._q.put_nowait(frame.tobytes())
        except queue.Full:
            pass  # ffmpeg ตามไม่ทัน — ทิ้งเฟรมนี้

    def _write_loop(self) -> None:
        proc = self._proc
        try:
            while self.alive:
                data = self._q.get()
                if data is None:
                    break
                proc.stdin.write(data)
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            self.alive = False

    def _watch_stderr(self) -> None:
        try:
            for line in self._proc.stderr:
                log.warning("ffmpeg(%s): %s", self.path, line.decode(errors="replace").strip())
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        was_alive, self.alive = self.alive, False
        if self._proc is None:
            return
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        try:
            if was_alive:
                self._proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            self._proc.kill()
