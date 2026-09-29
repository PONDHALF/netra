# NETRA — Phase 1 Mockup

**N**eural **E**ngine for **T**racking & **R**ecognition of **A**utomobiles
ระบบตรวจจับรถ อ่านป้ายทะเบียนไทย และบันทึกภาพรถอัตโนมัติ จากไฟล์วิดีโอกล้องวงจรปิด (ดูแผนเต็มใน [plan.md](plan.md))

## เริ่มใช้งาน

> **รันบน Windows + การ์ดจอ NVIDIA** → ดูคู่มือ [docs/WINDOWS.md](docs/WINDOWS.md) (ดับเบิลคลิก `windows\start.bat`)

### แบบ Docker (คำสั่งเดียว)
```bash
docker compose up --build                 # CPU
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build   # NVIDIA GPU
```
เปิด http://localhost:8000 — ครั้งแรกจะดาวน์โหลดโมเดล YOLO11s และ EasyOCR (~150 MB) อัตโนมัติ

### แบบพัฒนา (macOS / Linux)
```bash
make setup     # สร้าง .venv (Python 3.12) + npm install + ดาวน์โหลดโมเดลป้ายไทย
make api       # backend  → http://localhost:8000
make web       # frontend → http://localhost:5173 (hot reload, proxy ไป :8000)
```
หรือ `make build` แล้วเปิดที่ :8000 อย่างเดียว

### ประมวลผลผ่านคำสั่ง (ไม่ต้องเปิดเว็บ)
```bash
.venv/bin/python -m engine.cli video.mp4 --out data/outputs/test
# → events.csv, events/*.jpg, annotated.mp4, summary.json
```

## โครงสร้าง
```
engine/                 AI pipeline
  pipeline.py           อ่านเฟรม → detect+track → หาป้าย → เลือกเฟรมชัดสุด (top-3) → OCR+vote → วาดกรอบ → H.264
  detectors.py          YOLO11s + ByteTrack (รถ), YOLO11n (ป้าย — ถ้ามี plate.pt)
  ocr.py                อ่านป้าย: โมเดลรายตัวอักษร → EasyOCR เติมส่วนที่ขาด
  fetch_models.py       ดาวน์โหลดโมเดลจาก Hugging Face อย่างปลอดภัย
  postprocess/          รูปแบบป้ายไทย, แก้ตัวที่สับสน (ไ→1, O→0, เลขไทย), 77 จังหวัด (fuzzy), vote หลายเฟรม
  models/               yolo11s.pt (ดาวน์โหลดอัตโนมัติ), plate.pt (เทรนเอง)
backend/app/            FastAPI + SQLAlchemy (SQLite) + WebSocket
frontend/               React + Vite + TypeScript + Tailwind
training/               train_plate.py, benchmark.py (ชุดทดสอบมาตรฐาน), eval_ocr.py (ข้อมูลที่แก้ด้วยมือ)
data/                   uploads/, outputs/<job>/, corrections/, netra.db
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
| `NETRA_TYPHOON` | `0` | `1` = ใช้ Typhoon OCR 3B ช่วยอ่านจังหวัด |
