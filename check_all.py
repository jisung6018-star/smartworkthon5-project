"""저장된 모든 콘텐츠를 지금의 검수기로 다시 검사합니다 (AI 호출 없음).

    python check_all.py

data/content/*.json 의 모든 결정자 × 콘텐츠 종류(블로그 · 도입 사례 · 영업 이메일 · 카드뉴스)에 대해
점수·상태·문제와, 종류·시장에 맞는 주입 시험의 검출 수를 출력합니다. 끝에 오탐률과 표현 변형 시험 결과를 붙입니다.
"""
from __future__ import annotations

import json
import sys

from kit import analysis, config, content, verify

sys.stdout.reconfigure(encoding="utf-8")
DOCS = [("블로그", "블로그"), ("도입 사례", "도입사례"), ("영업 이메일", "이메일")]


def run() -> dict:
    cards, conflicts = analysis.load("cards"), analysis.load("conflicts")
    ledger = verify.build_ledger(cards, conflicts, content.load_photos(config.ROOT))
    rules = verify.load_rules()
    total = {"문서": 0, "통과": 0, "검토 필요": 0, "차단": 0, "주입": 0, "검출": 0, "카드": 0, "카드통과": 0}
    per_kind: dict[str, dict] = {}
    for f in sorted((analysis.DATA / "content").glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        market = None if r.get("산업", "공통") == "공통" else r["산업"]
        print(f"\n■ {f.name} · 시장 {market or '공통'}" + (f" · {r['시장표시']}" if r.get("시장표시") else "") + (f" · 생성 {r['생성시각']}" if r.get("생성시각") else ""))
        for role, e in r["역할"].items():
            for kind, key in DOCS:
                d = e.get(key)
                if not d:
                    continue
                chk = verify.check(d["제목"], d["본문"], ledger, rules, kind=kind, market=market)
                inj = verify.injection_test(d["제목"], d["본문"], ledger, rules, kind=kind, market=market)
                miss = [m["일부러 넣은 오류"] for m in inj["표"] if m["결과"] != "검출"]
                total["문서"] += 1
                total[chk["상태"]] += 1
                total["주입"] += inj["주입"]
                total["검출"] += inj["검출"]
                k = per_kind.setdefault(kind, {"문서": 0, "통과": 0, "주입": 0, "검출": 0})
                k["문서"] += 1
                k["통과"] += chk["상태"] == "통과"
                k["주입"] += inj["주입"]
                k["검출"] += inj["검출"]
                print(f"  {role} · {kind}: {chk['점수']}점 {chk['상태']} · 주입 {inj['검출']}/{inj['주입']}" + (f" · 놓침 {miss}" if miss else ""))
                for i in chk["문제"]:
                    print(f"     - [{i['종류']}·{i['상태']}] {i['설명']} | {i['문장'][:70]}")
            for n, c in enumerate(e.get("카드뉴스") or [], 1):
                ck = verify.check("", "\n".join([c.get("제목", ""), *c.get("본문", [])]), ledger, rules, doc_level=False, kind="카드뉴스", market=market)
                total["카드"] += 1
                total["카드통과"] += ck["상태"] == "통과"
                for i in ck["문제"]:
                    print(f"  {role} · 카드뉴스 {n}장: [{i['종류']}·{i['상태']}] {i['설명']} | {i['문장'][:60]}")
    fp = verify.false_positive_test(cards, conflicts, ledger)
    vt = verify.variant_test(cards, conflicts, ledger)
    print(f"\n합계: 문서 {total['문서']}편 (통과 {total['통과']} · 검토 필요 {total['검토 필요']} · 차단 {total['차단']}) · "
          f"주입 {total['검출']}/{total['주입']} · 카드뉴스 {total['카드통과']}/{total['카드']}장 통과")
    for kind, k in per_kind.items():
        print(f"  {kind}: {k['문서']}편 중 통과 {k['통과']} · 주입 {k['검출']}/{k['주입']}")
    print(f"오탐률 {fp['오탐률']}% (정상 문장 {fp['정상 문장']}개 중 {fp['잘못 걸림']}개) · 표현 변형 {vt['변형 문장']}문장 중 잘못 걸림 {vt['잘못 걸림']}건")
    return {"합계": total, "종류별": per_kind, "오탐률": fp["오탐률"], "표현변형오탐": vt["잘못 걸림"]}


if __name__ == "__main__":
    run()
