"""เทรนโมเดลตรวจจับป้ายทะเบียน (YOLO11n) แล้วติดตั้งเป็น engine/models/plate.pt

ใช้ได้ 2 แบบ
1) dataset จาก Roboflow Universe (ค้นหา "thai license plate" แล้วเลือก export แบบ YOLOv11):
     export ROBOFLOW_API_KEY=xxxx
     python training/train_plate.py --roboflow <workspace>/<project>/<version>

2) dataset ในเครื่อง (รูปแบบ YOLO มี data.yaml):
     python training/train_plate.py --data path/to/data.yaml

บน Google Colab (GPU T4) ใช้เวลาประมาณ 1–2 ชม. สำหรับ ~100 epochs
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "engine" / "models" / "plate.pt"


def download_roboflow(spec: str, dest: Path) -> Path:
    try:
        from roboflow import Roboflow
    except ImportError as e:
        raise SystemExit("ติดตั้งก่อน: pip install roboflow") from e
    key = os.getenv("ROBOFLOW_API_KEY")
    if not key:
        raise SystemExit("กรุณาตั้งค่า ROBOFLOW_API_KEY")
    workspace, project, version = spec.split("/")
    ds = Roboflow(api_key=key).workspace(workspace).project(project).version(int(version))
    out = ds.download("yolov11", location=str(dest / f"{project}-v{version}"))
    return Path(out.location) / "data.yaml"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", help="path ของ data.yaml")
    src.add_argument("--roboflow", help="workspace/project/version")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default=None, help="0 / mps / cpu (ค่าเริ่มต้น: อัตโนมัติ)")
    ap.add_argument("--no-install", action="store_true", help="ไม่ต้องคัดลอกไปที่ engine/models/plate.pt")
    args = ap.parse_args()

    from ultralytics import YOLO

    data = Path(args.data) if args.data else download_roboflow(args.roboflow, ROOT / "training" / "datasets")
    model = YOLO(args.model)
    model.train(
        data=str(data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        single_cls=True,           # รวมทุก class ให้เป็น "plate" คลาสเดียว
        project=str(ROOT / "training" / "runs"),
        name="plate",
        exist_ok=True,
        patience=25,
        # ป้ายเป็นตัวอักษร ห้ามพลิกซ้าย-ขวา
        fliplr=0.0,
        degrees=5.0,
        perspective=0.0005,
        hsv_v=0.5,                 # จำลองแสงกลางวัน/กลางคืน
    )
    best = Path(model.trainer.best)
    metrics = YOLO(str(best)).val(data=str(data), single_cls=True, verbose=False)
    print(f"\nmAP50 = {metrics.box.map50:.3f}   mAP50-95 = {metrics.box.map:.3f}")
    if not args.no_install:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(best, TARGET)
        print(f"ติดตั้งโมเดลแล้ว → {TARGET}  (รีสตาร์ท backend เพื่อใช้งาน)")


if __name__ == "__main__":
    main()
