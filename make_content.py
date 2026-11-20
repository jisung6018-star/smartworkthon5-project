"""콘텐츠 생성 실행 — 현장 사진 1장 → 결정자 3역할 카드뉴스(4장씩) + 블로그 원고 → 코드 검수 → 주입 시험.

    python make_content.py                 # 대표 사례 사진 (photo_04.jpg)
    python make_content.py photo_08.jpg    # 다른 사진

결과: data/content.json, output/cards/<사진>/…jpg
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from kit import analysis, config, content, llm, verify

sys.stdout.reconfigure(encoding="utf-8")


def run(photo_name: str = "photo_04.jpg") -> dict:
    t0 = time.time()
    cards, conflicts, report = analysis.load("cards"), analysis.load("conflicts"), analysis.load("strategy")
    photos = content.load_photos(config.ROOT)
    meta = next(p for p in photos if p["파일"] == photo_name)
    photo = config.ROOT / "input" / "site" / photo_name
    guideline = next(p["글"] for p in analysis.load_pages() if p["파일"] == "가이드라인")
    rules = verify.load_rules()
    info = content.read_photo(photo, meta)
    print(f"① 사진 판독 ({photo_name}): {info['판독']['설치형태']} · 확신 {info['판독']['확신']} · 교차 검증 {info['교차검증']}"
          + (f" · 홈페이지 표기와 {info['홈페이지표기와']}" if info.get("홈페이지표기와") else ""))
    print(f"   장비: {', '.join(info['판독']['보이는장비'])} / 고객(코드가 붙임): {meta['가린고객명']} · {meta['업종']}")
    deciders = {d["역할"]: d for d in report["결정자"]}
    roles = [r for r in analysis.ROLES if r in deciders]
    outs = llm.ask_many(roles, lambda r: content.make_for_role(r, deciders[r], info, cards, conflicts, guideline, rules),
                        workers=3, label="결정자별 콘텐츠")
    ledger = verify.build_ledger(cards, conflicts, photos)
    valid = {c["id"] for c in cards if c["원문확인"]}
    result = {"사진": photo_name, "판독": info, "역할": {}}
    for role, out in zip(roles, outs):
        if isinstance(out, Exception):
            print(f"   ✗ {role}: {out}")
            continue
        imgs = content.render_cards(photo, out["카드뉴스"], role, config.OUT / "cards" / photo_name.split(".")[0])
        imgs = [{**i, "파일": Path(i["파일"]).relative_to(config.ROOT).as_posix()} for i in imgs]   # 저장소에는 상대 경로만
        blog = content.assemble_blog(out["블로그"])
        chk = verify.check(blog["제목"], blog["본문"], ledger, rules)
        blog["문장"] = verify.label_sentences(blog["문장"], chk, valid)
        labels = {k: sum(1 for s in blog["문장"] if s["표시"] == k) for k in ("확인된 사실", "AI 추론", "확인 필요")}
        result["역할"][role] = {"카드뉴스": out["카드뉴스"], "이미지": imgs, "블로그": blog, "검수": chk}
        print(f"② {role}: 카드 {len(imgs)}장 · 블로그 {len(blog['문장'])}문장 {labels} · 검수 {chk['점수']}점 "
              f"(미션 {sum(m['결과'] == '통과' for m in chk['미션'])}/11, 문제 {len(chk['문제'])}건)")
        print(f"   제목: {blog['제목']}")
        print(f"   표지: {out['카드뉴스'][0]['제목']} / {' · '.join(out['카드뉴스'][0]['본문'])}")
        for i in chk["문제"][:6]:
            print(f"   - [{i['종류']}] {i['설명']} | {i['문장'][:50]}")
    first = next(iter(result["역할"].values()), None)
    if first:
        test = verify.injection_test(first["블로그"]["제목"], first["블로그"]["본문"], ledger, rules)
        result["주입시험"] = test
        print(f"③ 주입 시험: 일부러 넣은 오류 {test['주입']}개 중 {test['검출']}개 검출")
        for r in test["표"]:
            print(f"   {'✓' if r['결과'] == '검출' else '✗'} {r['일부러 넣은 오류']} → {r['검출 내용'][:70]}")
    analysis.save("content", result)
    print(f"\n완료 {time.time() - t0:.0f}초 · " + llm.usage_text())
    return result


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(args[0] if args else "photo_04.jpg")
