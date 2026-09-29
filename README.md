# NETRA — Phase 1 Mockup

**N**eural **E**ngine for **T**racking & **R**ecognition of **A**utomobiles
ระบบตรวจจับรถ อ่านป้ายทะเบียนไทย และบันทึกภาพรถอัตโนมัติ จากไฟล์วิดีโอกล้องวงจรปิด (ดูแผนเต็มใน [plan.md](plan.md))

## เครื่องที่ใช้

| เครื่อง | หน้าที่ | วิธีใช้ |
|---|---|---|
| **Mac** (Apple Silicon, RAM 16 GB) | **พัฒนา** — แก้โค้ด ทดสอบกับคลิปสั้น วัดความแม่นยำ | `make` (ดูด้านล่าง) → `git push` |
| **Windows** (RTX 3060 12 GB, RAM 128 GB) | **ประมวลผลจริง** — วิดีโอยาว, Typhoon OCR, สาธิต | Docker + `windows\*.bat` → คู่มือ [docs/WINDOWS.md](docs/WINDOWS.md) |

โค้ดอยู่ที่ GitHub (private) `PONDHALF/netra` — แก้บน Mac แล้ว `git push`, บน Windows ดับเบิลคลิก `windows\update.bat`

## พัฒนาบน Mac
```bash
make setup     # ครั้งแรก: .venv (Python 3.12) + npm install + ดาวน์โหลดโมเดล
make sample    # ดาวน์โหลดคลิปทดสอบ 1 นาที → data/samples/yt_1min.mp4
make api       # backend + เว็บ → http://localhost:8000   (make web = หน้าเว็บแบบ hot reload ที่ :5173)
make try       # ทดสอบ engine กับคลิป 1 นาทีโดยไม่ต้องเปิดเว็บ
make bench     # วัดความแม่นยำบนชุดทดสอบ 100 ภาพ
make clean     # ล้างข้อมูลทดสอบ (วิดีโอที่อัปโหลด ผลลัพธ์ ฐานข้อมูล)
make help      # ดูคำสั่งทั้งหมด
```
Typhoon OCR 3B (~7.5 GB) ไม่ได้ติดตั้งบน Mac เพราะแรม 16 GB ไม่พอรันคู่กับ YOLO — ทดสอบ Typhoon บนเครื่อง Windows

### ประมวลผลผ่านคำสั่ง (ไม่ต้องเปิดเว็บ)
```bash
.venv/bin/python -m engine.cli video.mp4 --out data/outputs/test
# → events.csv, events/*.jpg, annotated.mp4, summary.json
```

## Live (กล้อง real-time)
หน้า **Live** (`/live`) — ภาพสดพร้อมกรอบรถ/ป้าย + รายการรถที่ผ่านเด้งขึ้นทันที, Typhoon อ่านป้ายที่ไม่มั่นใจซ้ำเบื้องหลัง

| URL กล้อง | ตัวอย่าง |
|---|---|
| กล้อง IP (RTSP) | `rtsp://admin:รหัส@192.168.1.64:554/Streaming/Channels/101` (Hikvision) |
| กล้องจำลอง (Docker) | `rtsp://camsim:8554/cam1` — เล่น `data/samples/yt_1min.mp4` วน, สร้างให้อัตโนมัติ |
| Webcam | `0` |
| ไฟล์วิดีโอ (เล่นวน) | `data/samples/yt_1min.mp4` — ใช้บน Mac ที่ไม่มี Docker |

ภาพสดส่งแบบ MJPEG (`/api/cameras/{id}/mjpeg`), event ผ่าน WebSocket `/ws/live` — กล้องหลุดจะต่อใหม่เอง
เตรียมกล้องจำลองบน Windows จาก Mac: `make remote-sample`

## โครงสร้าง
```
engine/                 AI pipeline (ใช้ร่วมกันทั้ง Mac และ Windows)
  stream.py             ประมวลผลภาพสดทีละเฟรม (กล้อง real-time)
  locks.py              กันเรียกโมเดลพร้อมกันหลาย thread (MPS ต้อง serialize ทั้งหมด)
  pipeline.py           อ่านเฟรม → detect+track → หาป้าย → เลือกเฟรมชัดสุด → OCR+vote → (Typhoon อ่านซ้ำ) → วาดกรอบ → H.264
  detectors.py          YOLO11s + ByteTrack (รถ), ตรวจจับป้าย (plate.pt)
  ocr.py                อ่านป้าย: โมเดลรายตัวอักษร (plate_ocr.pt) → EasyOCR เติมส่วนที่ขาด
  typhoon.py            Typhoon OCR 3B — อ่านซ้ำหลังวิเคราะห์ (ทางเลือก)
  fetch_models.py       ดาวน์โหลดโมเดล: ตรึงเวอร์ชัน + ตรวจ SHA-256 + สแกน pickle
  postprocess/          รูปแบบป้ายไทย, 77 จังหวัด (fuzzy), แปลงรหัสตัวอักษร, vote หลายเฟรม
  models/               *.pt (ไม่อยู่ใน git — make models)
backend/app/            FastAPI + SQLAlchemy (SQLite) + WebSocket, cameras.py = ตัวจัดการกล้องสด
docker/                 entrypoint.sh (เริ่ม container), mediamtx.yml (กล้องจำลอง RTSP)
frontend/               React + Vite + TypeScript + Tailwind
training/               benchmark.py, eval_typhoon.py, eval_ocr.py, train_plate.py, make_demo_video.py
windows/                สคริปต์ .bat สำหรับเครื่องประมวลผล Windows (start / update / stop / logs / check-gpu)
docs/WINDOWS.md         คู่มือติดตั้งบน Windows + NVIDIA
data/                   (ไม่อยู่ใน git) uploads/, outputs/<job>/, corrections/, netra.db, samples/, benchmark/
requirements.txt        dependency ของระบบ (Docker ใช้ไฟล์นี้)
requirements-dev.txt    + เครื่องมือของเครื่องพัฒนา (yt-dlp)
```

## API
| Method | Path | หน้าที่ |
|---|---|---|
| POST | `/api/videos` | อัปโหลดวิดีโอ (multipart: `file`, `source_name`, `location`, `video_start`) และสร้าง job |
| GET | `/api/jobs`, `/api/jobs/{id}` | รายการงาน / สถานะงาน + สถิติ |
| POST | `/api/jobs/{id}/cancel`, `/api/jobs/{id}/retry` | ยกเลิก / ประมวลผลใหม่ |
| DELETE | `/api/jobs/{id}` | ลบวิดีโอและผลลัพธ์ |
| WS | `/ws/jobs/{id}` | `progress`, `event` (รถแต่ละคัน), `status` แบบสด |
| GET | `/api/events?q=&type=&from=&to=&job_id=&min_conf=&offset_from=&offset_to=&plate=` | ค้นหาและกรอง |
| GET/PATCH | `/api/events/{id}` | รายละเอียด / แก้ไขเลขทะเบียน |
| GET | `/api/events/export?format=xlsx\|csv` | export (Excel มีรูปป้ายฝังในไฟล์) |
| GET | `/api/jobs/{id}/images.zip` | ดาวน์โหลดรูปรถ + รูปป้ายทั้งหมด |

เอกสาร API แบบโต้ตอบ: http://localhost:8000/docs

## โมเดล
| ไฟล์ | หน้าที่ | ที่มา |
|---|---|---|
| `yolo11s.pt` | ตรวจจับรถ | Ultralytics (ดาวน์โหลดอัตโนมัติ) |
| `plate.pt` | ตรวจจับป้าย | [tanawichsingpae/thai-license-plate-detector](https://huggingface.co/tanawichsingpae/thai-license-plate-detector) (MIT) |
| `plate_ocr.pt` | อ่านป้ายรายตัวอักษร (เลข, ก–ฮ, 76 จังหวัด) | [tanawichsingpae/thai-license-plate-ocr](https://huggingface.co/tanawichsingpae/thai-license-plate-ocr) (MIT) |

```bash
make models    # = python -m engine.fetch_models — ตรึง revision, ตรวจ SHA-256 และสแกน pickle ก่อนติดตั้ง
```
ลำดับการอ่านป้าย: `plate_ocr.pt` ก่อน → ถ้าเลขไม่ครบรูปแบบหรือไม่มีจังหวัด ให้ EasyOCR เติมส่วนที่ขาด
→ (ถ้าเปิด Typhoon) Typhoon OCR 3B อ่านซ้ำ **ครั้งเดียวต่อรถหนึ่งคัน** บนเฟรมที่ชัดที่สุด เพื่อแก้จังหวัดและเติมเลขที่อ่านไม่ครบ

### Typhoon OCR 3B (ทางเลือก)
[typhoon-ai/typhoon-ocr-3b](https://huggingface.co/typhoon-ai/typhoon-ocr-3b) (Apache-2.0) — ปิดเป็นค่าเริ่มต้น เพราะใช้แรม ~7.5 GB และ ~2 วินาที/คันบน Apple M-series
```bash
make typhoon       # ดาวน์โหลดโมเดล (~7.5 GB)
make api-typhoon   # รัน backend โดยเปิด Typhoon (หรือตั้ง NETRA_TYPHOON=1)
```
ผลบนภาพป้าย 100 ภาพ: ถูกทั้งเลขและจังหวัด 36% → **56%** (จังหวัด 48% → 74%) — ใน Docker ใช้ `NETRA_TYPHOON=1 docker compose up`
ถ้าไม่มีไฟล์โมเดล ระบบยังทำงานได้ในโหมดสำรอง (EasyOCR ค้นหาป้ายในภาพรถเอง) แต่ช้าและแม่นน้อยกว่ามาก

เทรนโมเดลป้ายเอง (เช่นเมื่อได้ข้อมูลจากกล้องจริงมากพอ):
```bash
python training/train_plate.py --data path/to/data.yaml          # หรือ --roboflow <workspace>/<project>/<version>
```

## PlateNet — ตัวอ่านป้ายที่เทรนเอง
CRNN + CTC อ่านเลขทะเบียนทั้งแถว + หัวจำแนก 77 จังหวัด (2.35M พารามิเตอร์, ~5 ms/ป้าย) — เทรนด้วย**ป้ายจำลองล้วน**
(`training/plate_ocr/synth.py`: ป้ายหลายแบบ/สี, กรอบป้าย, พื้นที่รอบป้าย, เบลอ, ความละเอียดต่ำ, ฟอนต์ OFL จาก Google Fonts)

ใช้คู่กับ char-OCR: อ่านตรงกัน → มั่นใจสูง (ถูก 94%), ขัดแย้ง → เชื่อตัวที่มั่นใจกว่า (`NETRA_ENSEMBLE_TIE`), จังหวัดจาก PlateNet

เทรนด้วยป้ายจำลอง + ป้ายจริง ~21,500 ป้ายจาก Roboflow (CC BY 4.0, เฉลยจากคน — `training/plate_ocr/chardata.py`)

| ป้ายจริง thai-parking-100 (ไม่ได้ใช้เทรน) | ก่อนมี PlateNet | PlateNet (ป้ายจำลองล้วน) | **PlateNet + ป้ายจริง** |
|---|---|---|---|
| ภาพเต็ม (ตัวตรวจจับตัดเอง): เลข / จังหวัด / ทั้งคู่ | 51 / 53 / 34% | 47 / 72 / 39% | **60 / 74 / 53%** |
| ภาพป้ายที่ตัดไว้: เลข / จังหวัด / ทั้งคู่ | 73 / 63 / 50% | 81 / 83 / 68% | **90 / 91 / 82%** |
| ป้ายจริงชุดใหม่ 2,528 ป้าย (เฉลยจากคน, เลขไม่ซ้ำกับชุดเทรน): เลข | – | – | **95%** |

```bash
make remote-train TRAIN_ARGS="--run platenet --steps 60000"             # เทรนบน Windows (GPU) ~2.5 ชม.
make remote-train TRAIN_ARGS="--run ft2 --init engine/models/platenet.pt --steps 5000 --lr 5e-4"  # fine-tune
make remote-train-status TRAIN_RUN=ft2                                  # ดูผล
python -m training.plate_ocr.compare --model data/train/ft2/best.pt     # เทียบวิธีรวมผลกับ char-OCR
```
ไฟล์โมเดลอยู่ที่ `engine/models/platenet.pt` (ไม่อยู่ใน git) — ข้อควรรู้: เลือกโมเดลจากชุดป้ายจริงชุดเดียวกับที่วัดผล ตัวเลขจึงอาจสูงกว่าความจริงเล็กน้อย

## วัดความแม่นยำ
```bash
make bench     # ชุดทดสอบ thai-parking-100 (ภาพกล้องลานจอดจริง 100 ภาพพร้อมเฉลย) — ดาวน์โหลดอัตโนมัติ
```
แสดงผล 2 แบบ: **e2e** (ภาพเต็ม → รถ → ป้าย → OCR) และ **crops** (OCR บนป้ายที่ตัดไว้) พร้อมผลต่างจากครั้งก่อน
ผลแต่ละครั้งเก็บที่ `data/benchmark/results/` — ใช้ `--show` ดูรายการที่อ่านผิด
ชุดทดสอบนี้มาจากกล้องตัวเดียว ควรวัดกับกล้องของตัวเองด้วย `training/eval_ocr.py` (ใช้ข้อมูลที่แก้ไขด้วยมือ)

## การแก้ไขด้วยมือ → ข้อมูลเทรน
ทุกครั้งที่แก้เลขทะเบียนในหน้ารายละเอียด ระบบจะบันทึกภาพป้ายและค่าที่ถูกต้องไว้ที่ `data/corrections/` (`labels.csv` + `images/`)
ใช้วัดความแม่นยำได้ด้วย `python training/eval_ocr.py --show` และใช้เทรน OCR ไทย (PARSeq/LPRNet) ใน Phase 2

## ตั้งค่า (environment variables)
| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `NETRA_DEVICE` | อัตโนมัติ (cuda > mps > cpu) | อุปกรณ์ประมวลผล |
| `NETRA_FRAME_STRIDE` | อัตโนมัติ (~15 เฟรม/วินาที) | ประมวลผลทุกๆ N เฟรม — เพิ่มเพื่อให้เร็วขึ้นบน CPU |
| `NETRA_IMGSZ` | 640 | ขนาดภาพที่ส่งเข้า YOLO ตรวจจับรถ |
| `NETRA_MIN_VEHICLE_FRAC` | 0.06 | ไม่บันทึกรถที่เล็กกว่าสัดส่วนนี้ของความกว้างภาพตลอดเวลาที่อยู่ในภาพ (รถไกลเกินอ่านป้าย) |
| `NETRA_PLATE_IMGSZ` | 1280 | ขนาดภาพที่ใช้หาป้าย (ป้ายเล็ก ต้องใช้ภาพใหญ่) — ลดเหลือ 640 ถ้าป้ายใหญ่ เช่นกล้องที่ไม้กั้น |
| `NETRA_DATA` | `./data` | ที่เก็บข้อมูล |
| `NETRA_PLATE_MODEL` | `engine/models/plate.pt` | โมเดลตรวจจับป้าย |
| `NETRA_PLATE_OCR_MODEL` | `engine/models/plate_ocr.pt` | โมเดลอ่านป้ายรายตัวอักษร |
| `NETRA_PLATENET_MODEL` | `engine/models/platenet.pt` | ตัวอ่านป้ายที่เทรนเอง (ถ้ามีไฟล์จะใช้คู่กับ char-OCR) |
| `NETRA_ENSEMBLE_TIE` | `conf` | PlateNet กับ char-OCR อ่านไม่ตรงกัน → `conf` ตัวที่มั่นใจกว่า / `platenet` / `char` |
| `NETRA_OCR_GPU` | `auto` | EasyOCR ใช้ GPU หรือไม่ — auto: CPU บนการ์ด NVIDIA (ประหยัด VRAM), GPU บน Mac |
| `NETRA_TRT` | `auto` | ใช้ TensorRT กับ YOLO บนการ์ด NVIDIA (แปลงอัตโนมัติครั้งแรก) |
| `NETRA_THREADS` | min(8, cores) | จำนวน thread ของ PyTorch/OpenCV |
| `NETRA_TYPHOON` | `0` | `1` = ใช้ Typhoon OCR 3B ช่วยอ่านจังหวัด |
