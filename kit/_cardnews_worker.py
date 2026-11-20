"""카드뉴스 HTML 을 이미지로 찍는 작업자 — kit/cardnews.py 가 별도 프로세스로 실행합니다.

    python kit/_cardnews_worker.py job.json

job.json: {"width": 1080, "height": 1350, "scale": 2, "pages": [{"html": "…/p1.html", "out": "…/경영진_1.jpg"}]}
표준 출력의 마지막 줄에 결과 JSON 을 씁니다: {"ok": true, "pages": [{"out", "overflow", "zoom"}]}
(웹 서버 안에서 브라우저를 직접 띄우지 않도록 프로세스를 분리했습니다.)
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path


def main(job_path: str) -> dict:
    from PIL import Image
    from playwright.sync_api import sync_playwright

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    w, h, scale = job.get("width", 1080), job.get("height", 1350), job.get("scale", 2)
    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=["--hide-scrollbars", "--allow-file-access-from-files"])
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, locale="ko-KR")
        page = ctx.new_page()
        for p in job["pages"]:
            page.goto(Path(p["html"]).resolve().as_uri(), wait_until="load")
            page.evaluate("() => document.fonts.ready.then(() => true)")
            info = page.evaluate("() => window.__fit ? window.__fit() : {overflow: false, zoom: 1}")
            page.wait_for_timeout(60)
            png = page.screenshot(clip={"x": 0, "y": 0, "width": w, "height": h}, type="png")
            img = Image.open(io.BytesIO(png)).convert("RGB")
            if img.size != (w, h):
                img = img.resize((w, h), Image.LANCZOS)
            target = Path(p["out"])
            target.parent.mkdir(parents=True, exist_ok=True)
            img.save(target, quality=93, subsampling=0)
            out.append({"out": str(target), "overflow": bool(info.get("overflow")), "zoom": info.get("zoom", 1)})
        browser.close()
    return {"ok": True, "pages": out}


if __name__ == "__main__":
    try:
        result = main(sys.argv[1])
    except Exception as e:  # noqa: BLE001 — 실패 사유를 부모 프로세스에 그대로 알림
        result = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
