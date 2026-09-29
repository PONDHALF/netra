"""แปลงผลของโมเดลอ่านป้ายรายตัวอักษร (tanawichsingpae/thai-license-plate-ocr) เป็นเลขทะเบียน

ชื่อ class ของโมเดลเป็นรหัส (ตรวจสอบโดยเทียบกับเฉลยของชุดทดสอบ thai-parking-100)
  "0"–"9"      ตัวเลข
  "A01"–"A44"  พยัญชนะไทยเรียงตามลำดับ ก(A01) … ฮ(A44)
  "BKK", "KKN" … ตัวย่อจังหวัด 3 ตัวอักษร (76 class — ไม่มี นราธิวาส และ สตูล, มี เบตง)
"""
from __future__ import annotations

from .plate_format import OcrToken, PlateReading, parse_tokens

THAI_ALPHABET = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"
assert len(THAI_ALPHABET) == 44

PROVINCE_CODES: dict[str, str] = {
    "ACR": "อำนาจเจริญ", "ATG": "อ่างทอง", "AYA": "พระนครศรีอยุธยา", "BKK": "กรุงเทพมหานคร", "BKN": "บึงกาฬ",
    "BRM": "บุรีรัมย์", "BTG": "เบตง", "CBI": "ชลบุรี", "CCO": "ฉะเชิงเทรา", "CMI": "เชียงใหม่", "CNT": "ชัยนาท",
    "CPM": "ชัยภูมิ", "CPN": "ชุมพร", "CRI": "เชียงราย", "CTI": "จันทบุรี", "KBI": "กระบี่", "KKN": "ขอนแก่น",
    "KPT": "กำแพงเพชร", "KRI": "กาญจนบุรี", "KSN": "กาฬสินธุ์", "LEI": "เลย", "LPG": "ลำปาง", "LPN": "ลำพูน",
    "LRI": "ลพบุรี", "MDH": "มุกดาหาร", "MKM": "มหาสารคาม", "MSN": "แม่ฮ่องสอน", "NAN": "น่าน", "NBI": "นนทบุรี",
    "NBP": "หนองบัวลำภู", "NKI": "หนองคาย", "NMA": "นครราชสีมา", "NPM": "นครพนม", "NPT": "นครปฐม",
    "NSN": "นครสวรรค์", "NST": "นครศรีธรรมราช", "NYK": "นครนายก", "PBI": "เพชรบุรี", "PCT": "พิจิตร",
    "PKN": "ประจวบคีรีขันธ์", "PKT": "ภูเก็ต", "PLG": "พัทลุง", "PLK": "พิษณุโลก", "PNA": "พังงา",
    "PNB": "เพชรบูรณ์", "PRE": "แพร่", "PRI": "ปราจีนบุรี", "PTE": "ปทุมธานี", "PTN": "ปัตตานี", "PYO": "พะเยา",
    "RBR": "ราชบุรี", "RET": "ร้อยเอ็ด", "RNG": "ระนอง", "RYG": "ระยอง", "SBR": "สิงห์บุรี", "SKA": "สงขลา",
    "SKM": "สมุทรสงคราม", "SKN": "สมุทรสาคร", "SKW": "สระแก้ว", "SNI": "สุราษฎร์ธานี", "SNK": "สกลนคร",
    "SPB": "สุพรรณบุรี", "SPK": "สมุทรปราการ", "SRI": "สระบุรี", "SRN": "สุรินทร์", "SSK": "ศรีสะเกษ",
    "STI": "สุโขทัย", "TAK": "ตาก", "TRG": "ตรัง", "TRT": "ตราด", "UBN": "อุบลราชธานี", "UDN": "อุดรธานี",
    "UTI": "อุทัยธานี", "UTT": "อุตรดิตถ์", "YLA": "ยะลา", "YST": "ยโสธร",
}


def class_to_char(name: str) -> str | None:
    if name.isdigit() and len(name) == 1:
        return name
    if len(name) == 3 and name[0] == "A" and name[1:].isdigit() and 1 <= int(name[1:]) <= 44:
        return THAI_ALPHABET[int(name[1:]) - 1]
    return None


def decode(detections: list[tuple[str, float, tuple[float, float, float, float]]]) -> PlateReading:
    """detections: [(ชื่อ class, conf, (x1, y1, x2, y2))] จากโมเดลรายตัวอักษร."""
    tokens: list[OcrToken] = []
    provinces: list[tuple[str, float]] = []
    for name, conf, (x1, y1, x2, y2) in detections:
        ch = class_to_char(name)
        if ch is not None:
            tokens.append(OcrToken(ch, conf, y=(y1 + y2) / 2, x=(x1 + x2) / 2, h=y2 - y1))
        elif name in PROVINCE_CODES:
            provinces.append((PROVINCE_CODES[name], conf))

    reading = parse_tokens(tokens)
    province, prov_conf = max(provinces, key=lambda p: p[1]) if provinces else (None, 0.0)
    reading.province = province
    if reading.text:
        used = [t.conf for t in tokens]
        conf = sum(used) / len(used)
        reading.conf = round(conf if reading.valid else conf * 0.6, 4)
    reading.extras = {"source": "char-ocr", "province_conf": round(prov_conf, 4)}
    reading.raw = " ".join(t.text for t in sorted(tokens, key=lambda t: (t.y // max(t.h, 1), t.x)))
    if province:
        reading.raw += f" | {province}"
    return reading
