"""사진 판독 교차 검증 — 설치 사례 사진 전체를 Claude 와 Gemini 가 따로 읽고, 설치 형태가 일치하는지 코드가 비교합니다.

    python crosscheck.py

결과: data/photo_check.json (사진별 두 모델의 판독, 일치 여부, 홈페이지 표기와의 일치 여부)
"""
from __future__ import annotations

import sys
import time

from kit import analysis, config, content, llm

sys.stdout.reconfigure(encoding="utf-8")


def run() -> dict:
    t0 = time.time()
    photos = content.load_photos(config.ROOT)
    site = config.ROOT / "input" / "site"
    infos = llm.ask_many(photos, lambda p: content.read_photo(site / p["파일"], p), workers=5, label="사진 판독")
    rows = []
    for p, info in zip(photos, infos):
        if isinstance(info, Exception):
            rows.append({"사진": p["파일"], "구분": p["구분"], "오류": str(info)[:80]})
            continue
        g = info.get("Gemini판독") or {}
        rows.append({"사진": p["파일"], "구분": p["구분"], "업종": p.get("업종", ""), "Claude": info["판독"]["설치형태"],
                     "Claude확신": info["판독"]["확신"], "Gemini": g.get("설치형태", ""), "Gemini확신": g.get("확신", ""),
                     "교차검증": info["교차검증"], "홈페이지표기": p.get("설치형태_홈페이지", ""), "홈페이지표기와": info.get("홈페이지표기와", "")})
    done = [r for r in rows if "오류" not in r and r["Gemini"]]
    agree = sum(r["교차검증"] == "일치" for r in done)
    labeled = [r for r in done if r["홈페이지표기"]]
    summary = {"사진": len(rows), "두모델판독": len(done), "일치": agree, "불일치": len(done) - agree,
               "홈페이지표기있는사진": len(labeled), "Claude가표기와일치": sum(r["홈페이지표기와"] == "일치" for r in labeled),
               "Gemini가표기와일치": sum(r["Gemini"].replace(" ", "") == r["홈페이지표기"].replace(" ", "") for r in labeled)}
    for r in rows:
        if "오류" in r:
            print(f"✗ {r['사진']}: {r['오류']}")
        else:
            print(f"{'✓' if r['교차검증'] == '일치' else '△'} {r['사진']} [{r['구분']}] Claude {r['Claude']}({r['Claude확신']}) · Gemini {r['Gemini']}({r['Gemini확신']})"
                  + (f" · 홈페이지 표기 {r['홈페이지표기']}" if r["홈페이지표기"] else ""))
    print(f"\n두 모델이 모두 읽은 사진 {len(done)}장 중 설치 형태 일치 {agree}장, 불일치 {len(done) - agree}장 (불일치는 사람 확인으로 넘김)")
    if labeled:
        print(f"홈페이지에 설치 형태가 적힌 {len(labeled)}장: Claude {summary['Claude가표기와일치']}장, Gemini {summary['Gemini가표기와일치']}장이 표기와 일치")
    out = {"요약": summary, "표": rows}
    analysis.save("photo_check", out)
    print(f"완료 {time.time() - t0:.0f}초 · " + llm.usage_text())
    return out


if __name__ == "__main__":
    run()
