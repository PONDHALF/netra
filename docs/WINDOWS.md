# ติดตั้ง NETRA ตั้งแต่เริ่ม — Mac (พัฒนา) + Windows (ประมวลผล)

```
 Mac (พัฒนา)                                   Windows + RTX 3060 (ประมวลผล)
 แก้โค้ด → make deploy ──── Tailscale (VPN ส่วนตัว) ────► git pull + Docker build + รีสตาร์ท
 เบราว์เซอร์ → make remote-open ─────────────────────────► http://<WIN_HOST>:8000
                    โค้ดอยู่ที่ GitHub (private) PONDHALF/netra
```

ทำตามลำดับ — **ส่วน A ทำบนเครื่อง Windows** (ผ่าน AnyDesk หรือนั่งหน้าเครื่อง), **ส่วน B ทำบน Mac**
หลังเสร็จครบ ไม่ต้องใช้ AnyDesk อีก

---

## ส่วน A — เครื่อง Windows

### A1. เปิด virtualization และ WSL
1. Task Manager → Performance → CPU → ต้องขึ้น **Virtualization: Enabled**
   (ถ้า Disabled: เข้า BIOS เปิด Intel VT-x / AMD SVM)
2. เปิด **PowerShell แบบ Administrator** (คลิกขวาปุ่ม Start → Terminal (Admin)) แล้ววาง:
   ```powershell
   dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
   dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   bcdedit /set hypervisorlaunchtype auto
   ```
3. **รีสตาร์ทเครื่อง** แล้วเปิด PowerShell (Admin) อีกครั้ง: `wsl --update`

### A2. ติดตั้งโปรแกรม 4 ตัว
| โปรแกรม | ดาวน์โหลด | ระหว่างติดตั้ง |
|---|---|---|
| NVIDIA driver | https://www.nvidia.com/Download/index.aspx | GeForce RTX 30 → RTX 3060 → Windows |
| Docker Desktop | https://www.docker.com/products/docker-desktop/ | เลือก **Use WSL 2** |
| Git for Windows | https://git-scm.com/download/win | ค่าเริ่มต้นทั้งหมด |
| Tailscale | https://tailscale.com/download | ล็อกอินด้วยบัญชีที่จะใช้บน Mac ด้วย |

### A3. ตั้งค่าให้เครื่องพร้อมทำงานตลอด
- Docker Desktop → Settings → General → ติ๊ก **Start Docker Desktop when you sign in**
- Settings → System → Power → Screen and sleep → **Sleep: Never** (ตอนเสียบปลั๊ก)
- เปิด Docker Desktop ให้มุมล่างซ้ายขึ้น **Engine running**

### A4. ดึงโค้ด
เปิด PowerShell (ธรรมดา):
```powershell
cd C:\
git clone https://github.com/PONDHALF/netra.git
```
ครั้งแรกจะมีหน้าต่างให้ล็อกอิน GitHub

### A5. ตรวจการ์ดจอ
ดับเบิลคลิก `C:\netra\windows\check-gpu.bat` → ต้องเห็น **NVIDIA GeForce RTX 3060 / 12288MiB** และ `OK - GPU is visible`

### A6. เปิดให้ Mac สั่งงานได้ (SSH ผ่าน Tailscale)
1. บน Mac สั่ง `make ssh-key` → คัดลอกบรรทัด `powershell -ExecutionPolicy Bypass -File C:/netra/windows/setup-remote.ps1 ...`
2. บน Windows เปิด **PowerShell แบบ Administrator** แล้ววางบรรทัดนั้น
3. จดค่า 2 บรรทัดสุดท้ายที่แสดง: **`WIN_HOST = 100.x.y.z`** และ **`WIN_USER = ...`**

สคริปต์นี้: เปิด OpenSSH Server, เปิดพอร์ต 22/8000 **เฉพาะเครื่องใน Tailscale**, สร้าง deploy key (อ่านอย่างเดียว) ให้ git pull ได้, เปิด Typhoon ไว้ใน `C:\netra\.env`

### A7. เปิดระบบครั้งแรก
ดับเบิลคลิก `C:\netra\windows\start-typhoon.bat`
- build ครั้งแรก ~10–15 นาที (ขั้น *exporting to image* นานที่สุด — อย่าปิดหน้าต่าง)
- จากนั้นระบบดาวน์โหลดโมเดล + Typhoon 7.5 GB — ดูได้จาก `windows\logs.bat` จนเห็น `Uvicorn running on http://0.0.0.0:8000`
- เปิด http://localhost:8000 → มุมขวาบนต้องขึ้น **AI พร้อม · CUDA:0**

---

## ส่วน B — Mac

### B1. Tailscale
เปิดแอป **Tailscale** → ล็อกอินบัญชีเดียวกับ Windows → ในเมนูต้องเห็นเครื่อง Windows

### B2. โปรเจกต์ (ถ้ายังไม่มี)
```bash
git clone https://github.com/PONDHALF/netra.git && cd netra
make setup          # Python 3.12 venv + npm + โมเดล (ต้องมี uv และ node)
make ssh-key        # ใช้ในข้อ A6
```

### B3. บอก Mac ว่าเครื่อง Windows อยู่ที่ไหน
สร้างไฟล์ `.deploy.env` ในโฟลเดอร์ netra (ไม่อยู่ใน git) ด้วยค่าจากข้อ A6:
```
WIN_HOST=100.x.y.z
WIN_USER=ชื่อผู้ใช้windows
```

### B4. เชื่อมและทดสอบ
```bash
make remote-setup   # ทดสอบ SSH + เพิ่ม deploy key ของ Windows ใน GitHub + ทดสอบ git บน Windows
make remote-status  # ต้องเห็น container netra (running) และ RTX 3060
make remote-open    # เปิดเว็บ NETRA ของเครื่อง Windows ในเบราว์เซอร์ Mac
```

---

## ใช้งานประจำ (ทั้งหมดจาก Mac)
| คำสั่ง | ทำอะไร |
|---|---|
| `make remote-open` | เปิดเว็บ NETRA → อัปโหลดวิดีโอจาก Mac ได้เลย ประมวลผลบน RTX 3060 |
| `make deploy` | push โค้ด → Windows git pull + build ใหม่ + รีสตาร์ท (แก้แค่โค้ด ~1–3 นาที) |
| `make remote-status` | สถานะ container, commit ล่าสุด, การใช้การ์ดจอ |
| `make remote-logs` | log ล่าสุด 200 บรรทัด |

ไฟล์ใน `C:\netra\windows\` ยังใช้ได้ถ้านั่งหน้าเครื่อง Windows:
`start.bat` (ไม่ใช้ Typhoon) · `start-typhoon.bat` · `update.bat` · `stop.bat` · `logs.bat` · `check-gpu.bat`

## ข้อมูลอยู่ที่ไหน
`C:\netra\data\` — วิดีโอที่อัปโหลด, ผลลัพธ์, ฐานข้อมูล `netra.db`, ภาพป้ายที่แก้ไข (`corrections\`), cache โมเดล
**ไม่อยู่ใน git — สำรองโฟลเดอร์นี้เอง**

## แก้ปัญหา
| อาการ | วิธีแก้ |
|---|---|
| Docker Desktop: *Virtualization support not detected* | ทำข้อ A1 ให้ครบ แล้วรีสตาร์ท |
| `failed to connect to the docker API ... docker_engine` | เปิด Docker Desktop รอ *Engine running* |
| `check-gpu.bat` ไม่เห็นการ์ดจอ | อัปเดต NVIDIA driver, Docker Desktop → Settings → General → *Use the WSL 2 based engine* |
| log: `KeyError: 'storages'` (โมเดลเสีย) | `update.bat` — ระบบตรวจ hash แล้วโหลดโมเดลใหม่เอง |
| เว็บขึ้น "API ออฟไลน์" | รอ 1–2 นาทีหลังเริ่ม (กำลังโหลดโมเดล) หรือดู `make remote-logs` |
| `make remote-*` ขึ้น *Connection timed out* | Tailscale ทั้ง 2 เครื่องต้องเปิดอยู่, เครื่อง Windows ต้องไม่ sleep |
| `make deploy` ขึ้น error เรื่อง docker | ต้องล็อกอิน Windows ค้างไว้ และ Docker Desktop ต้องเปิดอยู่ |
