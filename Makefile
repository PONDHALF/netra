PY := .venv/bin/python

.PHONY: setup models typhoon api api-typhoon web build cli bench bench-typhoon docker

setup:            ## ติดตั้ง dependency ทั้งหมด (ต้องมี uv และ node)
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements.txt
	cd frontend && npm install
	$(PY) -m engine.fetch_models

models:           ## ดาวน์โหลดโมเดลป้ายไทยจาก Hugging Face (ตรวจ hash + สแกนความปลอดภัย)
	$(PY) -m engine.fetch_models

typhoon:          ## ดาวน์โหลด Typhoon OCR 3B (~7.5 GB)
	$(PY) -m engine.fetch_models --typhoon

api-typhoon:      ## รัน backend พร้อม Typhoon OCR (แรม ~8 GB)
	NETRA_TYPHOON=1 $(PY) -m uvicorn backend.app.main:app --reload --reload-dir backend --reload-dir engine --port 8000

api:              ## รัน backend (http://localhost:8000)
	$(PY) -m uvicorn backend.app.main:app --reload --reload-dir backend --reload-dir engine --port 8000

web:              ## รันหน้าเว็บโหมดพัฒนา (http://localhost:5173)
	cd frontend && npm run dev

build:            ## build หน้าเว็บ ให้ backend เสิร์ฟที่ :8000
	cd frontend && npm run build

cli:              ## ประมวลผลวิดีโอผ่านคำสั่ง: make cli VIDEO=path/to/video.mp4
	$(PY) -m engine.cli $(VIDEO)

bench:            ## วัดความแม่นยำบนชุดทดสอบ 100 ภาพ (เทียบกับครั้งก่อนอัตโนมัติ)
	$(PY) -u training/benchmark.py

bench-typhoon:    ## benchmark โดยเปิด Typhoon
	NETRA_TYPHOON=1 $(PY) -u training/benchmark.py

docker:
	docker compose up --build
