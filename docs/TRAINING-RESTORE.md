# เทรน PlateNet ต่อบนเครื่องใหม่ (ไม่ต้องเริ่มเทรนจากศูนย์)

ใช้เมื่อย้ายเครื่องประมวลผล (เช่น RTX 3060 เครื่องเดิมหมดอายุ) — โค้ดอยู่ใน git ส่วนที่ **ไม่อยู่ใน git** และต้องเก็บไว้เอง:

| ของ | ที่อยู่ | ทำไมต้องเก็บ |
|---|---|---|
| `engine/models/platenet.pt` | โมเดลที่ใช้งานจริง (= `data/train/platenet-night1/best.pt`) | เทรนซ้ำหลายชั่วโมง ไม่มีที่ดาวน์โหลด |
| `engine/models/platenet-real1.pt` | รอบก่อนหน้า (ไม่มีกลางคืน) | ใช้เทียบ/ย้อนกลับ |
| `data/train/<รอบ>/{best,last}.pt`, `log.jsonl` | 4 รอบ: `platenet` → `platenet-ft1` → `platenet-real1` → `platenet-night1` | `last.pt` มี optimizer/step ใช้ `--resume` ต่อได้ตรงจุด |
| `data/datasets/real-plates/` | ภาพป้ายจริงที่ตัดแล้ว + `labels.csv` (สถานะ auto/human/review, split) | ป้ายจริงที่ใช้เทรนและวัดผล — ป้ายที่คนยืนยัน (`human`) สร้างใหม่ไม่ได้ |
| `data/corrections/` | ป้ายที่ผู้ใช้แก้ในหน้าเว็บ | ข้อมูลเทรนจากคน |
| `data/netra.db` | event + รายการที่แก้ไข | ประวัติการใช้งาน |

ของที่ดึงกลับมาเองได้: โมเดล yolo11s / plate / plate_ocr (`python -m engine.fetch_models` ตรวจ hash), thai-parking-100 (`benchmark.download()`), Typhoon, TensorRT engine, ฟอนต์สังเคราะห์ (`data/fonts` — ดู `training/plate_ocr/fonts.py`)

## สำรอง (ทำที่ Mac ขณะเครื่องเก่ายังอยู่)

ผลสำรองอยู่ที่ `data/backup-win/` (ไม่อยู่ใน git — `data/*` ถูก ignore) — ควรคัดลอกไปที่ที่ปลอดภัยอีกที่ (external drive / cloud) ด้วย เพราะ Mac ก็มีที่เดียว

```bash
# ดึงจากเครื่องประมวลผล (ต้องมี .deploy.env)
scp -r  $WIN_USER@$WIN_HOST:/C:/.../netra/data/train        data/backup-win/train
scp -r  $WIN_USER@$WIN_HOST:/C:/.../netra/data/corrections  data/backup-win/corrections
scp -r  $WIN_USER@$WIN_HOST:/C:/.../netra/data/datasets/real-plates data/backup-win/datasets/
# ฐานข้อมูล: อย่า scp ไฟล์ .db ตรงๆ ตอนระบบรันอยู่ (มี WAL) — ใช้ SQLite backup API ในคอนเทนเนอร์
docker exec netra-netra-1 python -c "import sqlite3;s=sqlite3.connect('/app/data/netra.db');d=sqlite3.connect('/app/data/netra-backup.db');s.backup(d)"
```

## กู้คืนบนเครื่องใหม่

1. ตั้งเครื่องตาม `docs/WINDOWS.md` (WSL, Docker, Git, Tailscale, `setup-remote.ps1`) แล้วแก้ `WIN_HOST` / `WIN_USER` / `WIN_DIR` ใน `.deploy.env` บน Mac → `make deploy` (image build + โหลดโมเดลมาตรฐานเอง)
2. ส่งไฟล์ที่สำรองไว้ไปเครื่องใหม่ (ทับไม่ได้ก็สร้างโฟลเดอร์ก่อน) — ใต้โฟลเดอร์โปรเจกต์:
   ```
   engine/models/platenet.pt  engine/models/platenet-real1.pt
   data/train/            (ทั้ง 4 รอบ)
   data/datasets/real-plates/
   data/corrections/
   data/netra.db          (ถ้าต้องการประวัติ event — หยุด container ก่อนวาง)
   ```
   ตัวอย่าง: `scp -r data/backup-win/train "$WIN_USER@$WIN_HOST:/C:/.../netra/data/"`
3. ตรวจ hash ของโมเดลที่ใช้งานจริงให้ตรงกับตอนสำรอง:
   `shasum -a 256 engine/models/platenet.pt` → ขึ้นต้น `31311f72cdce`
4. เทรนต่อ

## เทรนต่อ

ทั้ง 4 รอบเทรนจบครบแล้ว (`last.pt` อยู่ที่ step สุดท้ายของแต่ละรอบ: 60000 / 20000 / 30000 / 20000) — **ทางที่แนะนำคือเทรนรอบใหม่จากโมเดลที่ใช้อยู่ (fine-tune)** ด้านล่าง
`--resume` ใช้เฉพาะรอบที่เทรนค้างกลางทาง (ชื่อ `--run` เดิม + `--resume`; โหลด optimizer/step จาก `last.pt`) — `last.pt` ของ 4 รอบนี้เก็บไว้เผื่อดู/ต่อยอด ไม่ได้ทดสอบว่า resume แล้วเพิ่ม `--steps` เกินเดิมได้

**เทรนรอบใหม่จากโมเดลที่ใช้อยู่ (fine-tune)** — แนะนำเมื่อมีข้อมูล/ปรับ synth ใหม่: ตั้งชื่อรอบใหม่ + `--init`

```bash
make remote-train TRAIN_ARGS="--run platenet-v2 --init engine/models/platenet.pt \
  --real data/datasets/real-plates/thai-license-plate-character-recognition \
  --real data/datasets/real-plates/thai-license-plate-character-detect \
  --real data/datasets/real-plates/car-with-plate --real-ratio 0.6 --steps 20000 --lr 3e-4 --eval-every 2000"
make remote-train-status TRAIN_RUN=platenet-v2
make remote-train-fetch  TRAIN_RUN=platenet-v2      # ดึง best.pt มา Mac แล้วเทียบ: python -m training.plate_ocr.compare --model data/train/platenet-v2/best.pt
```

ข้อควรจำ (ดู README/memory ของโปรเจกต์): หยุด Live (`stop netra camsim`) ระหว่างเทรน แล้วเปิดกลับเมื่อจบ; ป้ายสถานะ `auto2` (Typhoon ตัดสิน) ไม่ใช้เทรนเป็นค่าเริ่มต้น เพราะผิด ~10% (`--real-status auto,human`)

## ประวัติ 4 รอบ (คำสั่งที่ใช้จริง)

| รอบ | คำสั่ง (ย่อ) |
|---|---|
| `platenet` | `--run platenet --steps 60000` (สังเคราะห์ล้วน) |
| `platenet-ft1` | `--init engine/models/platenet.pt --steps 20000 --lr 5e-4 --eval-every 1000` |
| `platenet-real1` | `--init platenet.pt` + `--real` 3 ชุด `--real-ratio 0.6 --steps 30000 --lr 5e-4` |
| `platenet-night1` ← **ใช้งานอยู่** | `--init platenet.pt` (= real1) + `--real` 3 ชุด `--real-ratio 0.6 --steps 20000 --lr 3e-4` + โหมดกลางคืนใน synth |
