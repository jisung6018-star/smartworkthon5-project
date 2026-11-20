"""홍보 이미지 자동 생성 부품 — 제품 자료와 실제 사진만으로 고객 유형별 홍보 이미지를 만듭니다.

    from kit import promo
    photos = promo.list_photos("input")                       # input/product, input/site 의 사진
    a = promo.analyze(material_text, photos)                  # AI: 기술 포인트·차별점(근거 포함), 사진별 분석, 고객 유형
    ads = promo.write_copy(a)                                 # AI: 고객 유형별 헤드라인·문구, 쓸 사진 선택
    report = promo.check(ads, a, material_text)               # 코드: 글자 수, 근거 대조
    files = promo.render_all(ads, a, photos, "output/ads")    # 코드: 실제 사진을 규격별로 잘라 문구 배치

원칙: 제품과 현장은 '실제 사진 그대로' 씁니다 (AI 가 새로 그리지 않음 → 제품이 왜곡되지 않고 한글이 깨지지 않음).
      AI 는 읽고(자료·사진 분석) 쓰는 일(문구)만 하고, 사진 자르기·글자 배치·대비 검사·근거 대조는 코드가 합니다.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import llm

def _first_font(*paths: str) -> str:
    return next((p for p in paths if Path(p).exists()), paths[0])


# Windows 는 맑은 고딕, Linux(배포 서버)는 나눔고딕(fonts-nanum)
FONT_BOLD = _first_font("C:/Windows/Fonts/malgunbd.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                        "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc")
FONT_REG = _first_font("C:/Windows/Fonts/malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                       "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc")
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
FORMATS = {"정사각 1080x1080": (1080, 1080), "세로 1080x1350": (1080, 1350),
           "스토리 1080x1920": (1080, 1920), "가로 1200x628": (1200, 628)}

ANALYZE_SCHEMA = {
    "제품명": "str",
    "한줄정의": "str: 무엇을 하는 제품인지 한 문장",
    "기술포인트": [{"이름": "str", "고객이점": "str: 이 기술로 고객이 얻는 것",
                "근거": "str: 제품 자료에서 글자 그대로 복사한 구절(60자 이내). 사진에서만 확인되면 '사진: 파일명'"}],
    "차별점": [{"내용": "str", "비교대상": "str: 기존 방식 또는 일반 제품", "근거": "str: 자료 구절 그대로 또는 '사진: 파일명'"}],
    "고객유형": [{"이름": "str: 구체적인 직함·상황", "관심사": "str: 이 고객이 가장 신경 쓰는 것", "설득포인트": "str: 위 기술포인트·차별점 중 무엇을 내세울지"}],
    "사진": [{"파일": "str: 파일 이름 그대로", "종류": "제품|현장", "장면": "str: 무엇이 찍혔는지",
            "광고가치": "str: 광고에서 이 사진으로 보여줄 수 있는 것", "피사체위치": "좌|중앙|우",
            "글자영역": "상단|하단: 피사체를 가리지 않고 글자를 놓을 수 있는 쪽", "품질": "int: 1~5 (선명도·구도)"}],
}
ANALYZE_PROMPT = """제품 자료와 사진들을 보고 마케팅 분석을 하세요.
- 기술포인트 3~5개, 차별점 2~4개. 자료에 적혀 있거나 사진에서 확인되는 것만 쓰고, 성능 수치·인증·수상은 자료에 없으면 쓰지 마세요.
- 근거는 자료의 구절을 그대로 복사하세요 (바꿔 쓰기 금지). 사진에서만 확인되면 '사진: 파일명'.
- 고객유형은 정확히 3개. "모든 사람"이 아니라 구매를 결정하는 구체적인 사람으로.
- 사진은 주어진 모든 파일을 순서대로 분석하세요. 파일 이름은 각 사진 앞에 적혀 있습니다."""

COPY_SCHEMA = {"광고": [{
    "고객유형": "str: 분석의 고객유형 이름 그대로",
    "사진": "str: 쓸 사진의 파일 이름 그대로",
    "헤드라인": "str: 16자 이내. 고객의 관심사를 건드리는 한 줄",
    "서브": "str: 30자 이내. 헤드라인을 뒷받침하는 사실",
    "포인트": ["str: 12자 이내 (정확히 3개)"],
    "행동유도": "str: 10자 이내 (예: 도입 상담 받기)",
    "근거": ["str: 이 광고가 기대는 기술포인트·차별점의 이름"],
    "게시글": "str: 이 이미지와 함께 올릴 SNS 글 3~4문장. 첫 문장은 고객의 상황으로 시작",
    "해시태그": ["str: # 포함, 5개"],
}]}
COPY_PROMPT = """아래 제품 분석으로 고객유형마다 홍보 이미지 문구를 하나씩 쓰세요 (고객유형 3개 → 광고 3개).
- 고객유형마다 그 고객의 관심사에 맞는 기술포인트·차별점만 골라 내세우세요. 세 광고의 헤드라인이 서로 달라야 합니다.
- 사진은 그 고객에게 가장 설득력 있는 것을 고르세요 (현장을 아는 고객에겐 현장 사진, 제품을 비교하는 고객에겐 제품 사진). 품질이 낮은 사진은 피하세요.
- 분석에 없는 성능 수치·인증·'최초'·'1위' 같은 표현은 쓰지 마세요. 과장 금지.
- 글자 수 제한을 지키세요. 이미지에 들어가는 글이라 짧아야 합니다."""


# ───────────────────────── 사진 목록 ─────────────────────────
def list_photos(folder) -> list[Path]:
    """folder 와 그 아래(product, site 등)의 사진 파일."""
    root = Path(folder)
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in PHOTO_EXT)


def _kind_hint(p: Path) -> str:
    name = p.parent.name.lower()
    return "제품 사진" if "product" in name or "제품" in name else "현장 사진" if "site" in name or "현장" in name else "사진"


# ───────────────────────── AI: 분석과 문구 ─────────────────────────
def analyze(material: str, photos: list[Path], max_photos: int = 12) -> dict:
    """제품 자료 + 사진 → 기술 포인트, 차별점, 고객 유형, 사진별 분석 (AI 1회 호출)."""
    photos = list(photos)[:max_photos]
    names = "\n".join(f"{i + 1}. {p.name} ({_kind_hint(p)})" for i, p in enumerate(photos))
    text = f"[제품 자료]\n{material.strip() or '(자료 없음 — 사진만으로 분석)'}\n\n[사진 파일 순서]\n{names}"
    return llm.ask_json(ANALYZE_PROMPT, ANALYZE_SCHEMA, text=text, files=photos, effort="medium")


def write_copy(analysis: dict) -> list[dict]:
    """고객 유형별 광고 문구 (AI 1회 호출)."""
    import json
    return llm.ask_json(COPY_PROMPT, COPY_SCHEMA, text=json.dumps(analysis, ensure_ascii=False, indent=1), effort="medium")["광고"]


# ───────────────────────── 코드: 검증 ─────────────────────────
LIMITS = {"헤드라인": 16, "서브": 30, "행동유도": 10}
RISKY = re.compile(r"최초|유일|1위|최고|완벽|100%|무조건|보장")


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def evidence_status(quote: str, material: str, photo_names: list[str]) -> str:
    """근거가 자료에 글자 그대로 있는지, 또는 실제로 있는 사진을 가리키는지."""
    q = (quote or "").strip()
    if q.startswith("사진"):
        return "사진 확인" if any(n in q for n in photo_names) else "근거 미확인"
    return "자료 일치" if len(_squash(q)) >= 4 and _squash(q) in _squash(material) else "근거 미확인"


def check(ads: list[dict], analysis: dict, material: str) -> dict:
    """문구 검사: 글자 수, 과장 표현, 근거. 반환: {"근거표": [...], "문구": [...]}"""
    names = [p["파일"] for p in analysis.get("사진", [])]
    ev = []
    for kind in ("기술포인트", "차별점"):
        for item in analysis.get(kind, []):
            label = item.get("이름") or item.get("내용")
            ev.append({"구분": kind, "항목": label, "근거": item.get("근거", ""),
                       "확인": evidence_status(item.get("근거", ""), material, names)})
    known = {e["항목"] for e in ev}
    rows = []
    for ad in ads:
        issues = []
        for key, lim in LIMITS.items():
            if len(ad.get(key, "")) > lim:
                issues.append(f"{key} {len(ad[key])}자 (제한 {lim}자)")
        for i, pt in enumerate(ad.get("포인트", [])):
            if len(pt) > 12:
                issues.append(f"포인트{i + 1} {len(pt)}자 (제한 12자)")
        text = " ".join([ad.get("헤드라인", ""), ad.get("서브", ""), *ad.get("포인트", [])])
        m = RISKY.search(text)
        if m:
            issues.append(f"과장 표현 '{m.group()}'")
        if ad.get("사진") not in names:
            issues.append("사진 파일 이름 불일치")
        unknown = [g for g in ad.get("근거", []) if g not in known]
        if unknown:
            issues.append("분석에 없는 근거: " + ", ".join(unknown))
        rows.append({"고객유형": ad.get("고객유형"), "헤드라인": ad.get("헤드라인"), "사진": ad.get("사진"),
                     "검사": "통과" if not issues else "확인 필요", "문제": " / ".join(issues)})
    return {"근거표": ev, "문구": rows}


# ───────────────────────── 코드: 이미지 합성 ─────────────────────────
def _font(bold: bool, size: int):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default(size)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in str(text).split(" "):
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:
            if draw.textlength(cur + ch, font=font) > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
    lines.append(cur)
    return [ln for ln in lines if ln]


def _fit(draw, text, bold, start, min_size, max_w, max_lines):
    size = start
    while True:
        font = _font(bold, size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines or size <= min_size:
            return font, lines[:max_lines]
        size -= 4


def _lum(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    """WCAG 명도 대비 (1~21). 4.5 이상이면 본문도 읽기 좋음."""
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def accent_color(img: Image.Image) -> tuple[int, int, int]:
    """사진에서 가장 눈에 띄는 선명한 색 (버튼·강조에 사용). 없으면 남색."""
    import colorsys
    small = img.convert("RGB").resize((64, 64)).quantize(8).convert("RGB")
    best, score = (31, 78, 121), 0.0
    for count, rgb in small.getcolors(4096) or []:
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        sc = s * (1 - abs(l - 0.5) * 1.6) * (count ** 0.3)
        if s > 0.35 and 0.25 < l < 0.7 and sc > score:
            best, score = rgb, sc
    return best


def _cover(img: Image.Image, w: int, h: int, focus_x: float, focus_y: float = 0.5) -> Image.Image:
    """비율을 유지하며 w×h 를 채우도록 자릅니다. focus 는 살릴 지점(0~1)."""
    scale = max(w / img.width, h / img.height)
    nw, nh = round(img.width * scale), round(img.height * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = min(max(round(nw * focus_x - w / 2), 0), nw - w)
    top = min(max(round(nh * focus_y - h / 2), 0), nh - h)
    return img.crop((left, top, left + w, top + h))


def _gradient(size, side: str, strength: float) -> Image.Image:
    """글자 영역 쪽이 어두운 반투명 막."""
    w, h = size
    g = Image.new("L", (1, 256))
    for i in range(256):
        t = i / 255
        g.putpixel((0, i), round(255 * strength * (t ** 1.6)))
    g = g.resize((w, h))
    if side == "상단":
        g = ImageOps.flip(g)
    elif side in ("좌측", "우측"):       # 가로형: 옆으로 어두워지는 막
        g = g.resize((h, w)).rotate(90, expand=True)     # 왼쪽이 밝고 오른쪽이 어두움
        if side == "좌측":
            g = ImageOps.mirror(g)
        g = g.resize((w, h))
    black = Image.new("RGBA", (w, h), (8, 12, 20, 0))
    black.putalpha(g)
    return black


def compose(photo, ad: dict, size=(1080, 1080), text_side: str = "하단", focus: str = "중앙", brand: str = "",
            color: tuple | None = None, path=None) -> tuple[Image.Image, dict]:
    """실제 사진 위에 문구를 배치한 홍보 이미지. 반환: (이미지, 검사 결과)"""
    w, h = size
    src = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    fx = {"좌": 0.3, "중앙": 0.5, "우": 0.7}.get(focus, 0.5)
    fy = 0.42 if text_side == "하단" else 0.58        # 글자 반대쪽으로 피사체를 살림
    wide = w / h > 1.5
    if wide:                                          # 가로형: 피사체 반대쪽 옆에 글자
        text_side = "우측" if focus == "좌" else "좌측"
        fy = 0.5
    base = _cover(src, w, h, fx, fy).filter(ImageFilter.UnsharpMask(radius=1.2, percent=40))
    accent = color or accent_color(base)
    pad = round(w * 0.065) if not wide else round(h * 0.11)
    tw = (w - 2 * pad) if not wide else round(w * 0.50)
    x0 = pad if text_side != "우측" else w - pad - tw   # 글자 블록의 왼쪽 끝

    d0 = ImageDraw.Draw(base)
    head_start = round(min(w, h) * (0.092 if not wide else 0.105))
    hf, hl = _fit(d0, ad.get("헤드라인", ""), True, head_start, 40, tw, 2 if not wide else 2)
    sf, sl = _fit(d0, ad.get("서브", ""), False, round(head_start * 0.46), 24, tw, 2)
    pts = [p for p in ad.get("포인트", [])][:3]
    pf = _font(True, round(head_start * 0.36))
    cta = ad.get("행동유도", "")
    cf = _font(True, round(head_start * 0.40))
    gap = round(head_start * 0.34)
    chip_h = round(pf.size * 2.1)
    cta_h = round(cf.size * 2.3)
    block_h = (len(hl) * hf.size * 1.22 + gap * 0.5 + len(sl) * sf.size * 1.35 + (gap + chip_h if pts else 0)
               + (gap + cta_h if cta else 0))
    y = pad * 1.4 if text_side == "상단" else (h - block_h) / 2 if wide else h - pad * 1.5 - block_h
    # 글자 영역이 충분히 어두워질 때까지 막을 짙게 (대비 4.5 이상)
    strength, img = 0.72, None
    for _ in range(5):
        img = Image.alpha_composite(base.convert("RGBA"), _gradient((w, h), text_side, strength)).convert("RGB")
        region = img.crop((x0, int(max(0, y)), x0 + tw, int(min(h, y + block_h)))).resize((1, 1))
        ratio = contrast((255, 255, 255), region.getpixel((0, 0)))
        if ratio >= 4.5 or strength >= 0.97:
            break
        strength += 0.07
    d = ImageDraw.Draw(img)
    overflow = False
    for ln in hl:
        d.text((x0, y), ln, font=hf, fill=(255, 255, 255))
        overflow |= d.textlength(ln, font=hf) > tw + 2
        y += hf.size * 1.22
    y += gap * 0.5
    for ln in sl:
        d.text((x0, y), ln, font=sf, fill=(236, 240, 245))
        y += sf.size * 1.35
    if pts:
        y += gap
        x = x0
        for p in pts:
            cw = round(d.textlength(p, font=pf) + pf.size * 1.4)
            if x + cw > x0 + tw:       # 줄이 넘치면 다음 줄로
                x, y = x0, y + chip_h + round(gap * 0.4)
            d.rounded_rectangle([x, y, x + cw, y + chip_h], radius=chip_h // 2, fill=(255, 255, 255))
            d.text((x + pf.size * 0.7, y + (chip_h - pf.size) / 2 - pf.size * 0.12), p, font=pf, fill=(20, 28, 40))
            x += cw + round(pf.size * 0.6)
        y += chip_h
    if cta:
        y += gap
        cw = round(d.textlength(cta, font=cf) + cf.size * 2.2)
        txt = (255, 255, 255) if contrast((255, 255, 255), accent) >= 3 else (20, 28, 40)
        d.rounded_rectangle([x0, y, x0 + cw, y + cta_h], radius=round(cta_h * 0.28), fill=accent)
        d.text((x0 + cf.size * 1.1, y + (cta_h - cf.size) / 2 - cf.size * 0.12), cta, font=cf, fill=txt)
    if brand:
        bf = _font(True, round(head_start * 0.34))
        bw = d.textlength(brand, font=bf)
        by = h - pad - bf.size if text_side == "상단" else pad
        bx = pad if text_side == "우측" else w - pad - bw
        d.text((bx + 2, by + 2), brand, font=bf, fill=(0, 0, 0))          # 옅은 그림자
        d.text((bx, by), brand, font=bf, fill=(255, 255, 255))
    report = {"대비": round(ratio, 1), "대비통과": ratio >= 4.5, "글자넘침": bool(overflow), "막농도": round(strength, 2),
              "강조색": "#%02X%02X%02X" % tuple(accent)}
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path, quality=92)
    return img, report


def render_all(ads: list[dict], analysis: dict, photos: list[Path], out_dir, formats: dict | None = None,
               brand: str = "") -> list[dict]:
    """광고 문구 × 규격 → 이미지 파일. 반환: [{"고객유형","규격","파일","대비",...}]"""
    by_name = {p.name: p for p in photos}
    info = {p["파일"]: p for p in analysis.get("사진", [])}
    out = Path(out_dir)
    rows = []
    for i, ad in enumerate(ads, 1):
        photo = by_name.get(ad.get("사진")) or (photos[0] if photos else None)
        if photo is None:
            continue
        meta = info.get(photo.name, {})
        for label, size in (formats or FORMATS).items():
            safe = re.sub(r'[\\/:*?"<>|\s]+', "_", ad.get("고객유형", f"ad{i}"))[:20]
            f = out / f"{i:02d}_{safe}_{size[0]}x{size[1]}.jpg"
            _, rep = compose(photo, ad, size, meta.get("글자영역", "하단"), meta.get("피사체위치", "중앙"),
                             brand or analysis.get("제품명", ""), path=f)
            rows.append({"고객유형": ad.get("고객유형"), "규격": label, "사진": photo.name, "파일": str(f), **rep})
    return rows


def contact_sheet(files: list, path, cols: int = 4, height: int = 420, gap: int = 14) -> Path:
    ims = [Image.open(f) for f in files]
    thumbs = [im.resize((round(im.width * height / im.height), height)) for im in ims]
    rows = [thumbs[i:i + cols] for i in range(0, len(thumbs), cols)]
    W = max(sum(t.width for t in r) + gap * (len(r) + 1) for r in rows)
    sheet = Image.new("RGB", (W, len(rows) * (height + gap) + gap), (238, 238, 238))
    y = gap
    for r in rows:
        x = gap
        for t in r:
            sheet.paste(t, (x, y))
            x += t.width + gap
        y += height + gap
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
