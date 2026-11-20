"""자료 수집 — 티링크 홈페이지의 공개 페이지(제품 정보)와 설치 사례 사진을 input/ 에 받아 둡니다.

    python collect.py

- 제품 정보: input/material/홈페이지_*.txt  (페이지 본문 텍스트, 첫 줄에 출처 주소)
- 현장 사진: input/site/photo_01.jpg …  + input/site/photos.json
  사진은 중립적인 이름으로 저장합니다. 홈페이지 원본 파일 이름에는 고객사 이름이 들어 있어서 그대로 쓰지 않고,
  홈페이지 화면에 표시된 '가린 이름'(예: 은평***클럽)과 업종만 photos.json 에 적습니다.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8")
BASE = "https://www.tlinkcrm.com/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
PAGES = {"설치사례": "case.php", "AI녹취": "recording.php", "티링크비즈": "bizsolution.php", "고객관리": "customer.php",
         "모바일": "mobile.php", "PC폰": "softphone.php", "학교용녹취": "school.php", "회사소개": "info.php", "콜백": "callback.php"}
MENU_END = "상담신청"       # 모든 페이지 위쪽에 반복되는 메뉴를 잘라내는 기준


def get(url: str) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=60)
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r


def page_text(html: str) -> str:
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in s.get_text("\n").splitlines()]
    lines = [ln for ln in lines if ln]
    out, prev = [], None
    for ln in lines:                      # 연달아 반복되는 줄 제거
        if ln != prev:
            out.append(ln)
        prev = ln
    return "\n".join(out)


def collect_pages() -> dict[str, str]:
    d = ROOT / "input" / "material"
    d.mkdir(parents=True, exist_ok=True)
    htmls = {}
    for name, path in PAGES.items():
        url = BASE + path
        try:
            r = get(url)
            if r.status_code != 200:
                print(f"  ✗ {name}: HTTP {r.status_code}")
                continue
            htmls[name] = r.text
            text = page_text(r.text)
            (d / f"홈페이지_{name}.txt").write_text(f"출처: {url} (수집 {time.strftime('%Y-%m-%d')})\n\n{text}", encoding="utf-8")
            print(f"  ✓ {name}: {len(text):,}자")
        except Exception as e:  # noqa: BLE001 — 한 페이지 실패해도 계속
            print(f"  ✗ {name}: {type(e).__name__}")
        time.sleep(0.3)
    return htmls


def collect_photos(case_html: str) -> list[dict]:
    d = ROOT / "input" / "site"
    d.mkdir(parents=True, exist_ok=True)
    s = BeautifulSoup(case_html, "html.parser")
    items = []
    for img in s.find_all("img"):
        src = img.get("src") or ""
        if "/detail/" not in src or src.endswith(".png"):
            continue
        # 사진을 감싼 가장 가까운 블록의 글자를 설명으로 사용
        box = img
        text = ""
        for _ in range(4):
            box = box.parent
            if box is None:
                break
            text = re.sub(r"\s+", " ", box.get_text(" ")).strip()
            if len(text) >= 6:
                break
        items.append({"src": urljoin(BASE, src), "alt": (img.get("alt") or "").strip(), "주변글": text[:200]})
    photos = []
    n = 0
    for it in items:
        try:
            r = requests.get(it["src"], headers=UA, timeout=90)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 사진 받기 실패: {type(e).__name__}")
            continue
        if r.status_code != 200 or len(r.content) < 2000:
            print(f"  ✗ 사진 없음 (HTTP {r.status_code})")
            continue
        n += 1
        name = f"photo_{n:02d}.jpg"
        (d / name).write_bytes(r.content)
        stem = it["src"].rsplit("/", 1)[-1]
        kind = "설치 형태" if stem.startswith("rec-install") else "대표 사례" if stem.startswith("rec-case") else "갤러리"
        photos.append({"파일": name, "구분": kind, "순번": int(re.search(r"(\d+)", stem).group(1)) if re.search(r"\d+", stem) else 0,
                       "alt": it["alt"], "주변글": it["주변글"]})
        print(f"  ✓ {name} ({len(r.content) // 1024}KB) {kind}")
        time.sleep(0.2)
    return photos


if __name__ == "__main__":
    print("① 제품 정보 페이지")
    htmls = collect_pages()
    if "설치사례" in htmls:
        print("② 설치 사례 사진")
        photos = collect_photos(htmls["설치사례"])
        (ROOT / "input" / "site" / "_raw.json").write_text(json.dumps(photos, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"   사진 {len(photos)}장")
