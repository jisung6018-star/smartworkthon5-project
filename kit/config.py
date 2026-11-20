"""공통 설정: .env 로드, 출력 폴더, 콘솔 한글 출력."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
SAMPLES = ROOT / "samples"
try:
    OUT.mkdir(exist_ok=True)
except OSError:      # 읽기 전용 파일 시스템(서버리스 배포 등)에서는 임시 폴더를 씁니다
    import tempfile

    OUT = Path(tempfile.gettempdir()) / "factmarketer_output"
    OUT.mkdir(parents=True, exist_ok=True)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # python-dotenv 없으면 환경변수만 사용
    pass

# 파이프로 출력할 때 cp949 때문에 한글/이모지가 깨지는 것 방지
for _s in (sys.stdout, sys.stderr):
    try:
        if _s and (_s.encoding or "").lower() not in ("utf-8", "utf8"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def out_path(name: str, sub: str | None = None) -> Path:
    """output/(sub/)name 경로를 만들어 돌려줍니다."""
    d = OUT / sub if sub else OUT
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()
