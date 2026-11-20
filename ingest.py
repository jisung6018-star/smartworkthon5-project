"""자료 정리 — 제공 문서(input/docs)와 홈페이지 글(input/material)을 '파일·쪽' 단위로 나눠 data/pages.json 에 저장.

    python ingest.py

사실 카드의 출처(파일·쪽)는 여기서 나눈 단위를 그대로 씁니다.
- PDF: PyMuPDF 로 쪽마다 글자 추출
- PPT: python-pptx 로 장마다 글자 추출 (표·묶음 도형 포함)
- 엑셀: openpyxl 로 시트 글자 추출
- 사진 목록: 홈페이지 설치 사례 화면의 '가린 고객명'과 업종을 input/site/photos.json 으로 정리
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8")
DOCS, MATERIAL, DATA = ROOT / "input" / "docs", ROOT / "input" / "material", ROOT / "data"
SHORT = {"제안서": "제안서", "CRM매뉴얼": "CRM매뉴얼", "휴대폰버전": "휴대폰매뉴얼", "PC폰버전": "PC폰매뉴얼", "회사소개서": "회사소개서", "가이드라인": "가이드라인"}
INSTRUCTION = re.compile(r"AI\s*(에게|야|는\s*반드시)|이전\s*지시(를|는)?\s*(모두\s*)?무시|ignore (all |any )?(previous|prior)|system prompt|"
                         r"(점수|100점)을?\s*(주|달)|이\s*(문서|글)을\s*읽는\s*(AI|모델)", re.I)


def clean(t: str) -> str:
    return re.sub(r"[ \t ]+", " ", re.sub(r"\n\s*\n+", "\n", t or "")).strip()


def short_name(filename: str) -> str:
    return next((v for k, v in SHORT.items() if k in filename), Path(filename).stem)


def read_docs() -> list[dict]:
    import fitz  # PyMuPDF
    from openpyxl import load_workbook
    from pptx import Presentation
    pages = []
    for f in sorted(DOCS.iterdir()) if DOCS.exists() else []:
        ext, name = f.suffix.lower(), short_name(f.name)
        if ext == ".pdf":
            for i, pg in enumerate(fitz.open(f), 1):
                pages.append({"파일": name, "쪽": i, "단위": "쪽", "글": clean(pg.get_text())})
        elif ext == ".pptx":
            for i, sl in enumerate(Presentation(str(f)).slides, 1):
                parts = []

                def walk(shapes):
                    for sh in shapes:
                        if sh.has_text_frame:
                            parts.append(sh.text_frame.text)
                        if getattr(sh, "has_table", False) and sh.has_table:
                            parts.extend(" | ".join(c.text for c in row.cells) for row in sh.table.rows)
                        if sh.shape_type == 6:      # 묶음 도형
                            walk(sh.shapes)
                walk(sl.shapes)
                pages.append({"파일": name, "쪽": i, "단위": "장", "글": clean("\n".join(parts))})
        elif ext == ".xlsx":
            for ws in load_workbook(f, data_only=True).worksheets:
                rows = [" | ".join(str(c).strip() for c in row if c is not None and str(c).strip())
                        for row in ws.iter_rows(values_only=True)]
                pages.append({"파일": name, "쪽": 1, "단위": "시트", "글": clean("\n".join(r for r in rows if r))})
    return pages


def read_homepage() -> list[dict]:
    pages = []
    for f in sorted(MATERIAL.glob("홈페이지_*.txt")) if MATERIAL.exists() else []:
        body = f.read_text(encoding="utf-8").split("\n\n", 1)[-1]
        pages.append({"파일": f.stem.replace("홈페이지_", "홈페이지·"), "쪽": 1, "단위": "쪽", "글": clean(body)})
    return pages


def build_photos() -> list[dict]:
    """홈페이지 설치 사례 화면에 적힌 글로 사진 목록을 만듭니다. 고객명은 화면에 표시된 가린 이름만 씁니다."""
    raw_file = ROOT / "input" / "site" / "_raw.json"
    if not raw_file.exists():
        return []
    out = []
    for p in json.loads(raw_file.read_text(encoding="utf-8")):
        near, alt = p.get("주변글", ""), p.get("alt", "")
        item = {"파일": p["파일"], "구분": p["구분"], "가린고객명": "", "업종": "", "설치형태_홈페이지": "", "홈페이지설명": alt}
        if p["구분"] == "갤러리":
            m = re.match(r"(\S*\*+\S*)\s+(.+)", near)
            if m:
                item["가린고객명"], item["업종"] = m.group(1), m.group(2).strip()
        elif p["구분"] == "설치 형태":
            m = re.search(r"TYPE \d+\s+(\S+)\s+(.*)", near)
            if m:
                item["설치형태_홈페이지"], item["홈페이지설명"] = m.group(1), m.group(2).strip()
        else:  # 대표 사례
            m = re.search(r"CLIENT\s+(\S+)\s+(.*)", near)
            if m:
                item["가린고객명"], item["홈페이지설명"] = m.group(1), m.group(2).strip()
            item["업종"] = "공공 · 복지"
        out.append(item)
    (ROOT / "input" / "site" / "photos.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main():
    DATA.mkdir(exist_ok=True)
    pages = read_docs() + read_homepage()
    for p in pages:
        p["id"] = f"{p['파일']} {p['쪽']}{p['단위']}"
        p["지시문의심"] = bool(INSTRUCTION.search(p["글"]))    # 문서 속 'AI에게 …' 같은 문장은 지시가 아니라 데이터로만 취급
    pages = [p for p in pages if len(p["글"]) >= 20]
    (DATA / "pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    files = {}
    for p in pages:
        files.setdefault(p["파일"], []).append(p)
    print(f"자료 {len(files)}개 · {len(pages)}쪽 · {sum(len(p['글']) for p in pages):,}자 → data/pages.json")
    for name, ps in files.items():
        print(f"  {name}: {len(ps)}{ps[0]['단위']}, {sum(len(p['글']) for p in ps):,}자")
    photos = build_photos()
    print(f"사진 {len(photos)}장 → input/site/photos.json")
    for p in photos:
        print(f"  {p['파일']} | {p['구분']} | {p['가린고객명'] or p['설치형태_홈페이지']} | {p['업종']}")


if __name__ == "__main__":
    main()
