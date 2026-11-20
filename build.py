"""분석 실행 — 자료 정리 → 사실 카드 → 충돌 → 마케팅 분석. 결과는 data/ 에 저장되고 웹 화면이 읽어 씁니다.

    python build.py            # 저장된 결과가 있으면 그대로 사용
    python build.py --refresh  # 사실 카드부터 다시 추출
"""
from __future__ import annotations

import sys
import time

import ingest
from kit import analysis, llm

sys.stdout.reconfigure(encoding="utf-8")


def main():
    t0 = time.time()
    ingest.main()
    pages = analysis.load_pages()
    skipped = [p["id"] for p in pages if p.get("지시문의심")]
    cards = analysis.extract_cards(pages, refresh="--refresh" in sys.argv)
    ok = [c for c in cards if c["원문확인"]]
    print(f"\n① 사실 카드 {len(cards)}개 · 원문 일치 {len(ok)}개 · 불일치 {len(cards) - len(ok)}개 (지시문 의심으로 제외한 쪽 {len(skipped)}개)")
    conflicts = analysis.find_conflicts(cards)
    try:
        conflicts += analysis.find_condition_conflicts(cards)
    except Exception as e:  # noqa: BLE001 — 조건 충돌 후보는 실패해도 수치 충돌은 남김
        print(f"   (조건 충돌 후보 찾기 실패: {e})")
    analysis.save("conflicts", conflicts)
    print(f"② 자료 간 충돌 {len(conflicts)}건")
    for x in conflicts:
        print(f"   · [{x['종류']}] {x['항목']}: {x['내용'][:150]}")
    report = analysis.strategy(cards, conflicts)
    analysis.save("strategy", report)
    counts = {}
    for it in report["항목"]:
        counts[it["표시"]] = counts.get(it["표시"], 0) + 1
    print(f"③ 마케팅 분석 {len(report['항목'])}항목 {counts} · 결정자 {len(report['결정자'])}명")
    for d in report["결정자"]:
        print(f"   · {d['역할']}: {d['관심사'][:60]} → {d['현장사진활용'][:70]}")
    print(f"\n완료 {time.time() - t0:.0f}초 · " + llm.usage_text())


if __name__ == "__main__":
    main()
