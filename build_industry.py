"""산업별 시장 전략 실행 — 사실 카드 → 산업 4종의 시장 적합성(교육기관·콜센터 중심)과 산업 × 결정자 설득 전략.

    python build_industry.py

AI 는 기준별 판단과 근거 카드만 냅니다. 근거 카드가 없는 기준은 코드가 '판단 보류'로 바꾸고, 가중합과 순위도 코드가 계산합니다.
결과: data/industry.json
"""
from __future__ import annotations

import sys
import time

from kit import analysis, config, content, llm

sys.stdout.reconfigure(encoding="utf-8")


def run() -> dict:
    t0 = time.time()
    cards, conflicts = analysis.load("cards"), analysis.load("conflicts")
    photos = content.load_photos(config.ROOT)
    report = analysis.industries(cards, conflicts, photos)
    analysis.save("industry", report)
    print("\n산업 | 추천 | 가중점수 | 근거비중 | 점수 매긴 기준 | 도입 실적 카드 | 전용 자료 카드 | 설치 사진 | 부족한 정보 | 설득 전략")
    for i in report["산업"]:
        scored = [e for e in i["평가"] if e["점수"] is not None]
        print(f"{i['산업']} | {i['추천']} | {i['가중점수'] if i['가중점수'] is not None else '-'} | {i['근거비중']}% | {len(scored)}/{len(i['평가'])} | "
              f"{len(i['도입실적카드'])} | {i['전용자료카드수']} | {i['설치사례사진']} | {len(i['부족한정보'])} | {len(i['설득전략'])}")
    for i in report["산업"]:
        print(f"\n■ {i['산업']} — {i['추천']}" + (f" · 충돌 항목: {', '.join(i['충돌항목'])}" if i["충돌항목"] else ""))
        for e in i["평가"]:
            score = f"{e['점수']}점" if e["점수"] is not None else "보류"
            print(f"  [{e['표시']}] {e['기준']}({e['가중치']}%) {score} · 근거 {', '.join(e['근거카드']) or '-'} · {e['이유'][:90]}")
        print(f"  추천 이유: {i['추천이유'][:200]}")
        for d in i["설득전략"]:
            labels = " ".join(f"{k}:{d[k]['표시']}" for k in analysis.STRATEGY_ITEMS)
            print(f"  ▷ {d['결정자']} — {labels}")
    print(f"\n완료 {time.time() - t0:.0f}초 · " + llm.usage_text())
    return report


if __name__ == "__main__":
    run()
