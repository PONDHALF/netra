# ติดตั้งและรัน NETRA บน Windows (การ์ดจอ NVIDIA)

พัฒนาบน Mac → push ขึ้น GitHub → เครื่อง Windows ดึงโค้ดไปรันผ่าน Docker (ใช้ GPU)

```
 Mac (พัฒนา)                GitHub (private)            Windows + RTX (รันจริง)
 แก้โค้ด → git push  ───►   PONDHALF/netra   ───►   update.bat → http://localhost:8000
```

## 1. ติดตั้งครั้งเดียว

1. **NVIDIA driver** รุ่นล่าสุด — https://www.nvidia.com/Download/index.aspx
2. **Docker Desktop** — https://www.docker.com/products/docker-desktop/
   - ตอนติดตั้งเลือก **Use WSL 2** (ค่าเริ่มต้น) แล้วรีสตาร์ทเครื่อง
   - เปิด Docker Desktop ให้ขึ้นว่า *Engine running*
3. **Git for Windows** — https://git-scm.com/download/win (ค่าเริ่มต้นทั้งหมด)

### (ถ้าจะใช้ Typhoon) เพิ่มแรมให้ WSL
> เครื่องที่มีแรม ≥ 32 GB **ข้ามข้อนี้ได้** (เครื่องที่ใช้ตอนนี้: RAM 128 GB + RTX 3060 12 GB — ไม่ต้องทำ)

WSL ใช้แรมได้แค่ครึ่งหนึ่งของเครื่องเป็นค่าเริ่มต้น — Typhoon ต้องการ ~8 GB
สร้างไฟล์ `C:\Users\<ชื่อผู้ใช้>\.wslconfig`:
```ini
[wsl2]
memory=16GB
```
แล้วเปิด PowerShell สั่ง `wsl --shutdown` และเปิด Docker Desktop ใหม่

## 2. ดึงโค้ด
เปิด PowerShell:
```powershell
cd C:\
git clone https://github.com/PONDHALF/netra.git
```
ครั้งแรกจะมีหน้าต่างให้ล็อกอิน GitHub (repo เป็น private)

## 3. ตรวจว่า Docker เห็นการ์ดจอ
ดับเบิลคลิก `C:\netra\windows\check-gpu.bat` — ต้องเห็นตารางชื่อการ์ดจอ (nvidia-smi)

## 4. เริ่มระบบ
ดับเบิลคลิก `windows\start-typhoon.bat` (แนะนำสำหรับการ์ดจอ VRAM ≥ 12 GB เช่น RTX 3060 12 GB)
หรือ `windows\start.bat` (ไม่ใช้ Typhoon) แล้วเปิด **http://localhost:8000**

> **RTX 3060 12 GB**: Typhoon (~7.5 GB) + YOLO/โมเดลป้าย (~1.5 GB) พอดีกับ VRAM และ Typhoon ทำงานหลังวิเคราะห์วิดีโอเสร็จ
> จึงไม่แย่งหน่วยความจำกัน — ในหน้าอัปโหลดจะติ๊ก "อ่านป้ายซ้ำด้วย Typhoon" ไว้ให้เป็นค่าเริ่มต้น

- ครั้งแรกใช้เวลานาน (~10–20 นาที): build image ~8 GB + ดาวน์โหลดโมเดล
- ครั้งต่อไปเริ่มในไม่กี่วินาที และระบบเปิดเองหลังรีสตาร์ทเครื่อง (ถ้า Docker Desktop ตั้งให้เปิดตอนบูต)
- มุมขวาบนของเว็บต้องขึ้น **AI พร้อม · CUDA:0** — ถ้าขึ้น CPU แปลว่าไม่ได้ใช้การ์ดจอ

| ไฟล์ใน `windows\` | ใช้ทำอะไร |
|---|---|
| `start.bat` | เริ่มระบบ (ใช้ GPU) |
| `start-typhoon.bat` | เริ่มระบบ + ดาวน์โหลด Typhoon OCR 3B (ติ๊กเลือกใช้ได้ในหน้าอัปโหลด) |
| `update.bat` | ดึงโค้ดล่าสุดจาก GitHub แล้ว build ใหม่ |
| `stop.bat` | หยุดระบบ |
| `logs.bat` | ดู log (ใช้ตอนมีปัญหา) |
| `check-gpu.bat` | ตรวจว่า Docker เห็นการ์ดจอ |

## 5. อัปเดตเมื่อแก้โค้ดบน Mac
บน Mac: `git add -A && git commit -m "..." && git push`
บน Windows: ดับเบิลคลิก `windows\update.bat`

## ทำงานจาก Mac ระยะไกล (ไม่ต้องใช้ AnyDesk)

ใช้ **Tailscale** (VPN ส่วนตัว ฟรี) เชื่อม 2 เครื่อง — เปิดเว็บ NETRA จาก Mac และสั่ง deploy ได้ด้วยคำสั่งเดียว
พอร์ต 22 (SSH) และ 8000 (เว็บ) เปิดให้เฉพาะเครื่องใน Tailscale ของคุณ ไม่เปิดสู่อินเทอร์เน็ต

**ติดตั้งครั้งเดียว**
1. ติดตั้ง Tailscale ทั้ง 2 เครื่อง (https://tailscale.com/download) ล็อกอินบัญชีเดียวกัน
2. บน Mac: `make ssh-key` → คัดลอกคำสั่งที่แสดง
3. บน Windows (ผ่าน AnyDesk ครั้งสุดท้าย): `cd C:\netra` → `git pull` → เปิด PowerShell **แบบ Administrator** แล้ววางคำสั่งจากข้อ 2
   สคริปต์จะเปิด OpenSSH Server, ตั้ง firewall, สร้าง deploy key สำหรับ GitHub และแสดง `WIN_HOST` / `WIN_USER`
4. บน Mac สร้างไฟล์ `.deploy.env` ในโฟลเดอร์โปรเจกต์:
   ```
   WIN_HOST=100.x.y.z
   WIN_USER=ชื่อผู้ใช้windows
   ```
5. บน Mac: `make remote-setup` (ทดสอบ SSH + เพิ่ม deploy key ใน GitHub)

**ใช้งานประจำ (บน Mac)**
| คำสั่ง | ทำอะไร |
|---|---|
| `make deploy` | push โค้ด → Windows git pull + build ใหม่ + รีสตาร์ท |
| `make remote-open` | เปิดเว็บ NETRA บน Windows (อัปโหลดวิดีโอจาก Mac ได้เลย) |
| `make remote-status` | ดูสถานะ container, commit ล่าสุด และการใช้การ์ดจอ |
| `make remote-logs` | ดู log ล่าสุด |

**เงื่อนไขฝั่ง Windows**: ต้องล็อกอินค้างไว้, Docker Desktop ตั้งให้เปิดตอนล็อกอิน, และตั้งไม่ให้เครื่อง sleep
การเปิด/ปิด Typhoon เก็บในไฟล์ `C:\netra\.env` (`NETRA_TYPHOON=1` หรือ `0`) — deploy แล้วค่าไม่หาย

## ข้อมูลอยู่ที่ไหน
ทุกอย่างอยู่ใน `C:\netra\data\` — วิดีโอที่อัปโหลด, ผลลัพธ์, ฐานข้อมูล `netra.db`, ภาพป้ายที่แก้ไข (`corrections\`)
และ cache โมเดล — **ไม่อยู่ใน git** (สำรองโฟลเดอร์นี้เอง)

## เปิดจากเครื่องอื่นในวงแลนเดียวกัน
เปิด `http://<IP ของเครื่อง Windows>:8000` — ถ้าเข้าไม่ได้ ให้อนุญาตพอร์ต 8000 ใน Windows Firewall
(ระบบยังไม่มีการล็อกอิน — อย่าเปิดออกอินเทอร์เน็ต)

## แก้ปัญหา
| อาการ | วิธีแก้ |
|---|---|
| `start.bat` ขึ้น error ทันที | เปิด Docker Desktop ให้ขึ้น *Engine running* ก่อน |
| `check-gpu.bat` ไม่เห็นการ์ดจอ | อัปเดต NVIDIA driver, ใน Docker Desktop → Settings → General ติ๊ก *Use the WSL 2 based engine* |
| เว็บขึ้น "API ออฟไลน์" หลังเริ่มใหม่ | รอ 1–2 นาที (กำลังโหลดโมเดล) หรือดู `logs.bat` |
| Typhoon โหลดไม่ขึ้น / ช้ามาก | เพิ่มแรม WSL (ดูข้อ 1) — ถ้าการ์ดจอมี VRAM ≥ 8 GB Typhoon จะรันบน GPU |
