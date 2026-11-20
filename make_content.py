"""콘텐츠 생성 실행 — 현장 사진 1장 → 결정자 3역할 카드뉴스(4장씩) + 블로그 원고 → 코드 검수 → 주입 시험.

    python make_content.py                                   # 대표 사례 사진 (photo_04.jpg), 산업 선택 없음
    python make_content.py photo_08.jpg                      # 다른 사진
    python make_content.py photo_10.jpg --industry 교육기관   # 산업을 고르면 그 산업 × 결정자의 설득 전략 카드로 씀

결과: data/content/<사진>__<산업 또는 공통>.json (기본 실행은 data/content.json 에도 저장), output/cards/<사진>__<산업 또는 공통>/…jpg
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from kit import analysis, config, content, llm, verify

sys.stdout.reconfigure(encoding="utf-8")
DEFAULT_PHOTO = "photo_04.jpg"


def result_key(photo_name: str, industry: str | None = None) -> str:
    """결과 파일과 카드 폴더 이름: photo_04__공통, photo_10__교육기관, photo_04__무역_물류"""
    return f"{Path(photo_name).stem}__{re.sub(r'[·/\\ ]+', '_', industry or '공통')}"


def result_path(photo_name: str, industry: str | None = None) -> Path:
    return analysis.DATA / "content" / f"{result_key(photo_name, industry)}.json"


def load_result(photo_name: str, industry: str | None = None) -> dict | None:
    f = result_path(photo_name, industry)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def run(photo_name: str = DEFAULT_PHOTO, industry: str | None = None) -> dict:
    t0 = time.time()
    cards, conflicts, report = analysis.load("cards"), analysis.load("conflicts"), analysis.load("strategy")
    photos = content.load_photos(config.ROOT)
    meta = next(p for p in photos if p["파일"] == photo_name)
    photo = config.ROOT / "input" / "site" / photo_name
    guideline = next(p["글"] for p in analysis.load_pages() if p["파일"] == "가이드라인")
    rules = verify.load_rules()
    profile, playbooks = None, {}
    if industry:
        data = analysis.load("industry")
        if not data:
            raise SystemExit("data/industry.json 이 없습니다. 먼저 python build_industry.py 를 실행하세요.")
        profile = next((i for i in data["산업"] if i["산업"] == industry), None)
        if not profile:
            raise SystemExit(f"'{industry}' 산업이 없습니다. 가능한 값: {', '.join(i['산업'] for i in data['산업'])}")
        playbooks = {d["결정자"]: d for d in profile.get("설득전략", [])}
        print(f"◎ 대상 산업: {industry} ({profile['추천']}) · 설득 전략 카드 {len(playbooks)}개"
              + ("" if playbooks else " — 이 산업은 설득 전략 카드가 없어 산업 정보만 반영합니다"))
    info = content.read_photo(photo, meta)
    print(f"① 사진 판독 ({photo_name}): {info['판독']['설치형태']} · 확신 {info['판독']['확신']} · 교차 검증 {info['교차검증']}"
          + (f" · 홈페이지 표기와 {info['홈페이지표기와']}" if info.get("홈페이지표기와") else ""))
    print(f"   장비: {', '.join(info['판독']['보이는장비'])} / 고객(코드가 붙임): {meta['가린고객명']} · {meta['업종']}")
    deciders = {d["역할"]: d for d in report["결정자"]}
    roles = [r for r in analysis.ROLES if r in deciders]
    outs = llm.ask_many(roles, lambda r: content.make_for_role(r, deciders[r], info, cards, conflicts, guideline, rules,
                                                               industry=profile, playbook=playbooks.get(r)),
                        workers=3, label="결정자별 콘텐츠")
    ledger = verify.build_ledger(cards, conflicts, photos)
    valid = {c["id"] for c in cards if c["원문확인"]}
    key = result_key(photo_name, industry)
    result = {"사진": photo_name, "산업": industry or "공통", "판독": info, "역할": {}}
    for role, out in zip(roles, outs):
        if isinstance(out, Exception):
            print(f"   ✗ {role}: {out}")
            continue
        imgs = content.render_cards(photo, out["카드뉴스"], role, config.OUT / "cards" / key)
        imgs = [{**i, "파일": Path(i["파일"]).relative_to(config.ROOT).as_posix()} for i in imgs]   # 저장소에는 상대 경로만
        blog = content.assemble_blog(out["블로그"])
        chk = verify.check(blog["제목"], blog["본문"], ledger, rules)
        blog["문장"] = verify.label_sentences(blog["문장"], chk, valid)
        labels = {k: sum(1 for s in blog["문장"] if s.get("표시") == k) for k in ("확인된 사실", "AI 추론", "확인 필요")}
        result["역할"][role] = {"카드뉴스": out["카드뉴스"], "이미지": imgs, "블로그": blog, "검수": chk, "전략": playbooks.get(role)}
        print(f"② {role}: 카드 {len(imgs)}장 · 블로그 {len(blog['문장'])}문장 {labels} · 검수 {chk['점수']}점 "
              f"(미션 {sum(m['결과'] == '통과' for m in chk['미션'])}/11, 문제 {len(chk['문제'])}건)")
        print(f"   제목: {blog['제목']}")
        for n, c in enumerate(out["카드뉴스"], 1):
            print(f"   카드 {n}: {c['제목']} / {' · '.join(c['본문'])}  ← {c.get('가치', '')} · 근거 {', '.join(c.get('근거카드', [])) or '-'}")
        for i in chk["문제"]:
            print(f"   - [{i['종류']}] {i['설명']} | {i['문장'][:60]}")
    first = next(iter(result["역할"].values()), None)
    if first:
        test = verify.injection_test(first["블로그"]["제목"], first["블로그"]["본문"], ledger, rules)
        result["주입시험"] = test
        print(f"③ 주입 시험: 일부러 넣은 오류 {test['주입']}개 중 {test['검출']}개 검출")
        for r in test["표"]:
            print(f"   {'✓' if r['결과'] == '검출' else '✗'} {r['일부러 넣은 오류']} → {r['검출 내용'][:70]}")
    out_file = result_path(photo_name, industry)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if photo_name == DEFAULT_PHOTO and not industry:
        analysis.save("content", result)                     # 기본 실행 결과는 data/content.json 에도 둠
    print(f"\n저장: {out_file.relative_to(config.ROOT).as_posix()}")
    print(f"완료 {time.time() - t0:.0f}초 · " + llm.usage_text())
    return result


if __name__ == "__main__":
    argv = sys.argv[1:]
    chosen = None
    if "--industry" in argv:
        at = argv.index("--industry")
        chosen = argv[at + 1] if at + 1 < len(argv) else None
        del argv[at:at + 2]
    args = [a for a in argv if not a.startswith("--")]
    run(args[0] if args else DEFAULT_PHOTO, chosen)
