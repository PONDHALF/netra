PY := .venv/bin/python
FFMPEG = $(shell $(PY) -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
SAMPLE_URL := https://www.youtube.com/watch?v=QRdEHt5Uk54
SAMPLE := data/samples/yt_1min.mp4

# เครื่องประมวลผล Windows (ผ่าน Tailscale) — ตั้งค่าใน .deploy.env (ไม่อยู่ใน git)
-include .deploy.env
WIN_DIR ?= C:\netra
SSH = ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 $(WIN_USER)@$(WIN_HOST)
COMPOSE_GPU := docker compose -f docker-compose.yml -f docker-compose.gpu.yml

.DEFAULT_GOAL := help
.PHONY: help setup models sample api web build try bench clean typhoon api-typhoon bench-typhoon docker \
	ssh-key remote-setup deploy remote-status remote-logs remote-open _need-remote

help:             ## แสดงคำสั่งทั้งหมด
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

# ── ติดตั้ง ─────────────────────────────────────────────────────────────
setup:            ## ติดตั้งทั้งหมดสำหรับเครื่องพัฒนา (ต้องมี uv และ node)
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements-dev.txt
	cd frontend && npm install
	$(PY) -m engine.fetch_models

models:           ## ดาวน์โหลด/ซ่อมโมเดล (yolo11s, plate, plate_ocr) — ตรวจ hash ทุกไฟล์
	$(PY) -m engine.fetch_models

sample:           ## ดาวน์โหลดคลิปทดสอบ 1 นาที (ถนนใต้รถไฟฟ้า กทม.) → data/samples/yt_1min.mp4
	@mkdir -p data/samples
	$(PY) -m yt_dlp --no-warnings -f 137 --download-sections "*280-340" --force-keyframes-at-cuts \
		--ffmpeg-location "$(FFMPEG)" -o "$(SAMPLE)" "$(SAMPLE_URL)"

# ── พัฒนา ──────────────────────────────────────────────────────────────
api:              ## รัน backend + เว็บที่ build แล้ว (http://localhost:8000)
	$(PY) -m uvicorn backend.app.main:app --reload --reload-dir backend --reload-dir engine --port 8000

web:              ## รันหน้าเว็บแบบ hot reload (http://localhost:5173) — ใช้คู่กับ make api
	cd frontend && npm run dev

build:            ## build หน้าเว็บ ให้ backend เสิร์ฟที่ :8000
	cd frontend && npm run build

try:              ## ทดสอบ engine กับคลิป 1 นาทีผ่านคำสั่ง (ไม่ต้องเปิดเว็บ) → data/outputs/try
	@test -f $(SAMPLE) || $(MAKE) sample
	$(PY) -m engine.cli $(SAMPLE) --out data/outputs/try

bench:            ## วัดความแม่นยำบนชุดทดสอบ 100 ภาพ (เทียบกับครั้งก่อนอัตโนมัติ)
	$(PY) -u training/benchmark.py

clean:            ## ล้างข้อมูลที่ทดสอบ (วิดีโอที่อัปโหลด, ผลลัพธ์, ฐานข้อมูล) — เก็บคลิปทดสอบและชุด benchmark ไว้
	rm -rf data/uploads data/outputs data/corrections data/screens data/api.log
	rm -f data/netra.db data/netra.db-wal data/netra.db-shm
	find . -name __pycache__ -not -path "./.venv/*" -not -path "./frontend/node_modules/*" -prune -exec rm -rf {} +

# ── Typhoon OCR 3B (ต้องการแรม/VRAM ≥ 12 GB — ใช้บนเครื่องประมวลผล ไม่แนะนำบน Mac 16 GB) ──
typhoon:          ## ดาวน์โหลด Typhoon OCR 3B (~7.5 GB)
	$(PY) -m engine.fetch_models --typhoon

api-typhoon:      ## รัน backend โดยเปิด Typhoon เป็นค่าเริ่มต้น
	NETRA_TYPHOON=1 $(PY) -m uvicorn backend.app.main:app --reload --reload-dir backend --reload-dir engine --port 8000

bench-typhoon:    ## benchmark โดยเปิด Typhoon
	NETRA_TYPHOON=1 $(PY) -u training/benchmark.py

# ── Docker (เครื่องประมวลผล Windows ใช้ windows\*.bat แทน) ───────────────
docker:           ## รันด้วย Docker (CPU)
	docker compose up --build

# ── เครื่องประมวลผล Windows (ระยะไกลผ่าน Tailscale + SSH) — ดู docs/WINDOWS.md ──
ssh-key:          ## สร้าง SSH key ของ Mac (ครั้งเดียว) และแสดงคำสั่งที่ต้องรันบน Windows
	@test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N "" -q -C "netra-mac"
	@echo "รันบน Windows (PowerShell แบบ Administrator):"
	@echo ""
	@printf '%s\n' "powershell -ExecutionPolicy Bypass -File C:/netra/windows/setup-remote.ps1 -PublicKey \"$$(cat ~/.ssh/id_ed25519.pub)\""

remote-setup: _need-remote ## เชื่อม Mac กับ Windows: ทดสอบ SSH + เพิ่ม deploy key ของ Windows ใน GitHub
	@echo "== ทดสอบ SSH ==" && $(SSH) "echo ok %COMPUTERNAME%"
	@echo "== เพิ่ม deploy key (อ่านอย่างเดียว) ของ Windows ใน GitHub =="
	@$(SSH) "type %USERPROFILE%\\.ssh\\netra_deploy.pub" > /tmp/netra_deploy.pub
	@gh repo deploy-key list | grep -q netra-windows || gh repo deploy-key add /tmp/netra_deploy.pub --title netra-windows
	@rm -f /tmp/netra_deploy.pub
	@echo "== ทดสอบ git บน Windows ==" && $(SSH) "cd /d $(WIN_DIR) && git fetch && git status -sb"

deploy: _need-remote ## push โค้ดแล้วสั่ง Windows ให้ git pull + build ใหม่ + รีสตาร์ท
	git push
	$(SSH) "cd /d $(WIN_DIR) && git pull --ff-only && $(COMPOSE_GPU) up -d --build"
	@echo "✓ deploy เสร็จ → http://$(WIN_HOST):8000"

remote-status: _need-remote ## ดูสถานะ container และ GPU บน Windows
	$(SSH) "cd /d $(WIN_DIR) && git log --oneline -1 && $(COMPOSE_GPU) ps && nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv"

remote-logs:  _need-remote ## ดู log ล่าสุดบน Windows (200 บรรทัด)
	$(SSH) "cd /d $(WIN_DIR) && $(COMPOSE_GPU) logs --tail 200"

remote-open:  _need-remote ## เปิดหน้าเว็บ NETRA บนเครื่อง Windows ในเบราว์เซอร์ของ Mac
	open http://$(WIN_HOST):8000

_need-remote:
	@test -n "$(WIN_HOST)" -a -n "$(WIN_USER)" || { echo "ยังไม่ได้ตั้งค่า: สร้างไฟล์ .deploy.env ที่มี"; echo "  WIN_HOST=<Tailscale IP ของ Windows>"; echo "  WIN_USER=<ชื่อผู้ใช้ Windows>"; exit 1; }
