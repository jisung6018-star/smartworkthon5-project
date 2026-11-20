"""콘텐츠 생성 실행 — 현장 사진 1장 × 목표시장 × 결정자 × 콘텐츠 종류 → 생성 → 코드 검수 → 주입 시험.

    python make_content.py                                   # 대표 사례 사진 (photo_04.jpg), 시장 선택 없음, 카드뉴스 + 블로그
    python make_content.py photo_10.jpg --industry 교육기관   # 시장을 고르면 그 시장 × 결정자의 설득 전략 카드와 증거 규칙으로 씀
    python make_content.py photo_06.jpg --industry 무역·물류 --kinds 카드뉴스,블로그,도입사례,이메일 --roles 경영진,전산·총무 담당

콘텐츠 종류: 카드뉴스 · 블로그 · 도입 사례 · 영업 이메일 (기본: 카드뉴스, 블로그). 같은 사진·시장의 결과가 이미 있으면 요청한 종류·결정자만 다시 만들고 나머지는 그대로 둡니다.
결과: data/content/<사진>__<시장 또는 공통>.json (기본 실행은 data/content.json 에도 저장), output/cards/<사진>__<시장 또는 공통>/…jpg
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from kit import analysis, config, content, llm, verify

sys.stdout.reconfigure(encoding="utf-8")
DEFAULT_PHOTO = "photo_04.jpg"
KINDS = ["카드뉴스", "블로그", "도입 사례", "영업 이메일"]
KIND_ALIAS = {"카드뉴스": "카드뉴스", "블로그": "블로그", "도입 사례": "도입 사례", "도입사례": "도입 사례",
              "영업 이메일": "영업 이메일", "영업이메일": "영업 이메일", "이메일": "영업 이메일"}
EXTRA = {"도입 사례": ("도입사례", "검수_도입사례"), "영업 이메일": ("이메일", "검수_이메일")}     # 종류 → (저장 키, 검수 키)


def result_key(photo_name: str, industry: str | None = None) -> str:
    """결과 파일과 카드 폴더 이름: photo_04__공통, photo_10__교육기관, photo_04__무역_물류"""
    return f"{Path(photo_name).stem}__{re.sub(r'[·/\\ ]+', '_', industry or '공통')}"


def result_path(photo_name: str, industry: str | None = None) -> Path:
    return analysis.DATA / "content" / f"{result_key(photo_name, industry)}.json"


def load_result(photo_name: str, industry: str | None = None) -> dict | None:
    f = result_path(photo_name, industry)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _kinds(kinds) -> list[str]:
    if not kinds:
        return ["카드뉴스", "블로그"]
    out = []
    for k in kinds:
        name = KIND_ALIAS.get(str(k).strip())
        if not name:
            raise SystemExit(f"콘텐츠 종류 '{k}' 는 없습니다. 가능한 값: {', '.join(KINDS)}")
        if name not in out:
            out.append(name)
    return out


def run(photo_name: str = DEFAULT_PHOTO, industry: str | None = None, roles: list[str] | None = None, kinds: list[str] | None = None) -> dict:
    t0 = time.time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kinds = _kinds(kinds)
    need_main = any(k in kinds for k in ("카드뉴스", "블로그"))
    extra_kinds = [k for k in kinds if k in EXTRA]
    cards, conflicts, report = analysis.load("cards"), analysis.load("conflicts"), analysis.load("strategy")
    photos = content.load_photos(config.ROOT)
    meta = next(p for p in photos if p["파일"] == photo_name)
    photo = config.ROOT / "input" / "site" / photo_name
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
    mark = (profile or {}).get("시장표시", "")
    print(f"◎ 대상 시장: {industry or '공통(선택 없음)'}" + (f" ({profile['추천']})" if profile else "") + (f" · 표시: {mark}" if mark else "")
          + f" · 콘텐츠: {', '.join(kinds)}")
    info = content.read_photo(photo, meta)
    print(f"① 사진 판독 ({photo_name}): {info['판독']['설치형태']} · 확신 {info['판독']['확신']} · 교차 검증 {info['교차검증']}"
          + (f" · 홈페이지 표기와 {info['홈페이지표기와']}" if info.get("홈페이지표기와") else ""))
    print(f"   고객(코드가 붙임): {meta['가린고객명'] or '-'} · {meta['업종'] or '-'}")
    deciders = {d["역할"]: d for d in report["결정자"]}
    todo = [r for r in analysis.ROLES if r in deciders and (not roles or r in roles)]
    if roles and not todo:
        raise SystemExit(f"결정자 {roles} 가 없습니다. 가능한 값: {', '.join(analysis.ROLES)}")
    guideline = next(p["글"] for p in analysis.load_pages() if p["파일"] == "가이드라인") if need_main else ""

    def job(task):
        role, part = task
        if part == "main":
            return content.make_for_role(role, deciders[role], info, cards, conflicts, guideline, rules, industry=profile, playbook=playbooks.get(role))
        return content.make_extra(role, deciders[role], info, cards, conflicts, rules, industry=profile, playbook=playbooks.get(role), kinds=extra_kinds)

    tasks = [(r, "main") for r in todo if need_main] + [(r, "extra") for r in todo if extra_kinds]
    outs = dict(zip(tasks, llm.ask_many(tasks, job, workers=6, label="결정자별 콘텐츠")))
    ledger = verify.build_ledger(cards, conflicts, photos)
    valid = {c["id"] for c in cards if c["원문확인"]}
    key = result_key(photo_name, industry)
    result = load_result(photo_name, industry) or {"사진": photo_name, "산업": industry or "공통", "역할": {}}
    result.update({"사진": photo_name, "산업": industry or "공통", "판독": info, "시장표시": mark, "생성시각": now})
    result.setdefault("역할", {})
    for role in todo:
        entry = result["역할"].setdefault(role, {})
        stamps = entry.setdefault("생성시각", {})
        entry["전략"] = playbooks.get(role)
        out = outs.get((role, "main"))
        if isinstance(out, Exception):
            print(f"   ✗ {role} 카드뉴스·블로그: {out}")
        elif out:
            if "카드뉴스" in kinds or "카드뉴스" not in entry:        # 한 번의 호출로 둘 다 나오므로, 아직 없는 쪽은 함께 저장
                imgs = content.render_cards(photo, out["카드뉴스"], role, config.OUT / "cards" / key)
                entry["카드뉴스"] = out["카드뉴스"]
                entry["이미지"] = [{**i, "파일": Path(i["파일"]).relative_to(config.ROOT).as_posix()} for i in imgs]   # 저장소에는 상대 경로만
                stamps["카드뉴스"] = now
                for n, c in enumerate(out["카드뉴스"], 1):
                    print(f"   카드 {n}: {c['제목']} / {' · '.join(c['본문'])}  ← {c.get('가치', '')} · 근거 {', '.join(c.get('근거카드', [])) or '-'}")
            if "블로그" in kinds or "블로그" not in entry:
                blog = content.assemble_blog(out["블로그"], market_mark=mark)
                chk = verify.check(blog["제목"], blog["본문"], ledger, rules, kind="블로그", market=industry)
                blog["문장"] = verify.label_sentences(blog["문장"], chk, valid)
                entry["블로그"], entry["검수"] = blog, chk
                stamps["블로그"] = now
                print(f"② {role} 블로그: {len(blog['문장'])}문장 · 검수 {chk['점수']}점 {chk['상태']} "
                      f"(미션 {sum(m['결과'] == '통과' for m in chk['미션'])}/11, 문제 {len(chk['문제'])}건) · {blog['제목']}")
                for i in chk["문제"]:
                    print(f"   - [{i['종류']}·{i['상태']}] {i['설명']} | {i['문장'][:60]}")
        raw = outs.get((role, "extra"))
        if isinstance(raw, Exception):
            print(f"   ✗ {role} 도입 사례·이메일: {raw}")
        elif raw:
            for kind in extra_kinds:
                dkey, ckey = EXTRA[kind]
                if not raw.get(dkey):
                    print(f"   ✗ {role} {kind}: 생성 결과 없음")
                    continue
                doc = content.assemble_doc(raw[dkey], kind, market_mark=mark)
                chk = verify.check(doc["제목"], doc["본문"], ledger, rules, kind=kind, market=industry)
                doc["문장"] = verify.label_sentences(doc["문장"], chk, valid)
                entry[dkey], entry[ckey] = doc, chk
                stamps[kind] = now
                print(f"③ {role} {kind}: {len(doc['문장'])}문장 · 검수 {chk['점수']}점 {chk['상태']} (문제 {len(chk['문제'])}건) · {doc['제목']}")
                for i in chk["문제"]:
                    print(f"   - [{i['종류']}·{i['상태']}] {i['설명']} | {i['문장'][:60]}")
    first = next((e for e in result["역할"].values() if e.get("블로그")), None)
    if first:
        test = verify.injection_test(first["블로그"]["제목"], first["블로그"]["본문"], ledger, rules, kind="블로그", market=industry)
        result["주입시험"] = test
        print(f"④ 주입 시험(블로그): 일부러 넣은 오류 {test['주입']}개 중 {test['검출']}개 검출"
              + "".join(f"\n   ✗ 놓침: {r['일부러 넣은 오류']}" for r in test["표"] if r["결과"] != "검출"))
    by_kind = result.setdefault("주입시험_종류별", {})
    for kind, (dkey, _) in EXTRA.items():
        e = next((e for e in result["역할"].values() if e.get(dkey)), None)
        if e:
            by_kind[kind] = verify.injection_test(e[dkey]["제목"], e[dkey]["본문"], ledger, rules, kind=kind, market=industry)
            print(f"④ 주입 시험({kind}): {by_kind[kind]['주입']}개 중 {by_kind[kind]['검출']}개 검출"
                  + "".join(f"\n   ✗ 놓침: {r['일부러 넣은 오류']}" for r in by_kind[kind]["표"] if r["결과"] != "검출"))
    out_file = result_path(photo_name, industry)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if photo_name == DEFAULT_PHOTO and not industry:
        analysis.save("content", result)                     # 기본 실행 결과는 data/content.json 에도 둠
    print(f"\n저장: {out_file.relative_to(config.ROOT).as_posix()}")
    print(f"완료 {time.time() - t0:.0f}초 · " + llm.usage_text())
    return result


def _opt(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    at = argv.index(name)
    value = argv[at + 1] if at + 1 < len(argv) else None
    del argv[at:at + 2]
    return value


if __name__ == "__main__":
    argv = sys.argv[1:]
    chosen = _opt(argv, "--industry")
    kind_arg = _opt(argv, "--kinds")
    role_arg = _opt(argv, "--roles")
    args = [a for a in argv if not a.startswith("--")]
    run(args[0] if args else DEFAULT_PHOTO, chosen,
        roles=[r.strip() for r in role_arg.split(",")] if role_arg else None,
        kinds=[k.strip() for k in kind_arg.split(",")] if kind_arg else None)
