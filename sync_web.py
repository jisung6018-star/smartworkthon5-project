"""웹 사이트(Vercel) 저장소로 엔진과 데이터를 보냅니다 — 엔진을 고친 뒤 이 명령 하나로 다시 맞춥니다.

    python build_site.py                          # 소개 쪽(index.html, results.html)을 먼저 새로 만들고
    python sync_web.py C:\\Users\\PCuser\\factmarketer-web     # 엔진 · 데이터 · 사진 · 카드 이미지 · 소개 쪽을 웹 저장소로 복사

보내는 것: kit/ 중 웹 함수가 쓰는 모듈, data/ 의 분석 결과와 저장된 생성 결과, 카드뉴스 이미지, 설치 사례 사진(중립 이름), 글꼴, 결과 쪽(results.html).
소개 쪽(index.html)은 웹 저장소에서 팀원이 직접 관리하므로 건드리지 않습니다.
보내지 않는 것: .env, 대회에서 받은 원본 문서와 그 전문(data/pages.json), 원본 사진 파일명, output/.
사진 판독은 저장해 둔 결과(응답 캐시)를 그대로 싣습니다. 웹에서는 사진을 다시 읽지 않습니다.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from kit import content, llm, verify

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
DATA, SITE_IN = ROOT / "data", ROOT / "input" / "site"
MODULES = ["__init__.py", "config.py", "llm.py", "verify.py", "content.py", "promo.py", "cardnews.py", "revise.py"]
ENGINE_DATA = ["cards.json", "conflicts.json", "strategy.json", "industry.json", "photo_check.json", "summary.json"]
ROLE_SLUG = {"경영진": "exec", "영업 관리자": "manager", "전산·총무 담당": "it"}
MARKET_SLUG = {"공통": "common", "의료기관": "medical", "교육기관": "education", "콜센터": "callcenter", "무역·물류": "trade"}
CONFLICT_CLASS = {"값이 다름": "확정적 충돌", "값이 다름 (적용 범위가 다를 수 있음 · 사람 확인)": "범위·조건 불명확",
                  "조건이 한쪽에만 있음": "범위·조건 불명확", "조건이 어긋남 (AI 추론 · 사람 확인)": "추가 확인 필요"}
SECTIONS = ["1. 기존 영업관리의 문제", "2. 휴대폰·인터넷전화 동시 녹음", "3. AI 자동 기록과 요약", "4. 영업사원 관리", "5. 경영진 종합 리포트"]


def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def jdump(p: Path, obj, indent=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":")), encoding="utf-8")


def slug_of(result: dict) -> str:
    return f"{Path(result['사진']).stem}-{MARKET_SLUG.get(result.get('산업') or '공통', 'm')}"


def guideline_text(cards: list[dict]) -> str:
    """블로그 지시문에 넣는 가이드라인 요약. 대회에서 받은 가이드라인 파일은 싣지 않고, 저장소에 이미 공개된 규칙과 사실 카드로만 만듭니다."""
    ms = verify.missions("", "")
    facts = [c["내용"] for c in cards if c.get("파일") == "가이드라인" and c.get("원문확인")]
    return "\n".join([
        "[티링크 블로그 가이드라인 요약]",
        f"- 필수 키워드 (제목과 본문에 모두): {', '.join(verify.REQUIRED)}",
        f"- 제목과 첫 문단에 넣을 핵심 키워드: {', '.join(verify.TITLE_KEYS)}",
        "- 리뷰 미션 11개:",
        *[f"  {m['미션']}. {m['내용']}" for m in ms],
        f"- 화면 이미지 5종(이 순서대로 한 문장씩): {', '.join(verify.IMAGE_SLOTS)}",
        "- 추천 본문 구성 5단계 (이 순서대로 소제목): " + " → ".join(SECTIONS),
        f"- 하단에 들어갈 정보(프로그램이 붙임): {', '.join(verify.FOOTER_ITEMS)}",
        "- 가이드라인에 적힌 사실:",
        *[f"  · {f}" for f in facts],
    ])


def main(web: Path, readings_from_ai: bool = True):
    if not (web / ".git").exists():
        raise SystemExit(f"웹 저장소가 아닙니다: {web}")
    cards = jload(DATA / "cards.json", [])
    by_id = {c["id"]: c for c in cards}
    conflicts = jload(DATA / "conflicts.json", [])
    strategy = jload(DATA / "strategy.json", {"항목": [], "결정자": []})
    industry = jload(DATA / "industry.json", {"산업": [], "기준": []})
    summary = jload(DATA / "summary.json", {})
    photo_check = jload(DATA / "photo_check.json", {})
    photos = jload(SITE_IN / "photos.json", [])

    # ── 엔진 ──
    eng = web / "engine"
    for sub in ("kit", "data"):
        if (eng / sub).exists():
            shutil.rmtree(eng / sub)
    (eng / "kit").mkdir(parents=True)
    for m in MODULES:
        shutil.copyfile(ROOT / "kit" / m, eng / "kit" / m)
    for name in ENGINE_DATA:
        if (DATA / name).exists():
            (eng / "data").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(DATA / name, eng / "data" / name)
    (eng / "data" / "guideline.txt").write_text(guideline_text(cards), encoding="utf-8")

    # ── 사진 (중립 이름) · 판독 (저장된 결과) ──
    pdir = web / "assets" / "photos"
    pdir.mkdir(parents=True, exist_ok=True)
    saved = {}
    for f in sorted((DATA / "content").glob("*.json")):
        r = jload(f)
        if r and r.get("판독"):
            saved.setdefault(r["사진"], r["판독"])
    check_rows = {r["사진"]: r for r in (photo_check.get("표") or [])}
    before = llm.usage()["calls"]
    photo_out, readings = [], {}
    for p in photos:
        src = SITE_IN / p["파일"]
        if not re.fullmatch(r"photo_\d\d\.jpg", p["파일"]) or not src.exists():
            continue
        shutil.copyfile(src, pdir / p["파일"])
        with Image.open(src) as im:
            w, h = im.size
        info = saved.get(p["파일"])
        if not info and readings_from_ai:
            info = content.read_photo(src, p)                 # 응답 캐시에 있으면 AI 를 부르지 않음
        if not info:
            row = check_rows.get(p["파일"], {})
            info = {"판독": {"설치형태": row.get("Claude", "판독 불가"), "보이는장비": [], "현장특징": "", "확신": row.get("Claude확신", "")},
                    "교차검증": row.get("교차검증", "미실행"), "Gemini판독": None,
                    "사진정보": {"파일": p["파일"], "업종": p.get("업종", ""), "가린고객명": p.get("가린고객명", ""), "홈페이지설명": p.get("홈페이지설명", "")}}
        readings[p["파일"]] = info
        photo_out.append({**p, "w": w, "h": h, "판독": {**info["판독"], "교차검증": info.get("교차검증", "")}})
    jdump(eng / "data" / "photos.json", photo_out)
    jdump(eng / "data" / "readings.json", readings)
    print(f"사진 {len(photo_out)}장 · 판독에 쓴 AI 호출 {llm.usage()['calls'] - before}회 (0이면 모두 저장된 결과)")

    # ── 저장된 생성 결과 + 카드 이미지 ──
    rdir = web / "d" / "results"
    if rdir.exists():
        shutil.rmtree(rdir)
    index = []
    for f in sorted((DATA / "content").glob("*.json")):
        r = jload(f)
        if not r or not r.get("역할"):
            continue
        slug = slug_of(r)
        key = f"{Path(r['사진']).stem}__{re.sub(r'[·/ ]+', '_', r.get('산업') or '공통')}"
        roles = {}
        for role, d in r["역할"].items():
            entry = {"전략": d.get("전략"), "생성시각": d.get("생성시각") or {}, "카드뉴스": d.get("카드뉴스") or [], "카드이미지": []}
            safe = re.sub(r"[^\w가-힣]+", "_", role)
            for i in range(1, len(entry["카드뉴스"]) + 1):
                src = DATA / "cardnews" / key / f"{safe}_{i}.jpg"
                if src.exists():
                    dst = web / "assets" / "cards" / slug / f"{ROLE_SLUG.get(role, 'role')}_{i}.jpg"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    entry["카드이미지"].append(dst.relative_to(web).as_posix())
            for k in ("블로그", "도입사례", "이메일"):
                if d.get(k):
                    entry[k] = {"제목": d[k]["제목"], "본문": d[k]["본문"],
                                "문장": [{"글": s["글"], "근거카드": s.get("근거카드", []), "소제목": s.get("소제목", "")} for s in d[k]["문장"]]}
            roles[role] = entry
        out = {"키": slug, "사진": r["사진"], "산업": r.get("산업") or "공통", "시장표시": r.get("시장표시", ""),
               "생성시각": r.get("생성시각") or "2026-11-20", "판독": r.get("판독"), "역할": roles}
        jdump(rdir / f"{slug}.json", out)
        kinds = sorted({k for e in roles.values() for k in ("카드뉴스", "블로그", "도입사례", "이메일") if e.get(k)})
        index.append({"키": slug, "사진": r["사진"], "산업": out["산업"], "생성시각": out["생성시각"], "역할": list(roles), "종류": kinds})

    # ── 화면이 읽는 기본 자료 ──
    conf_out = []
    for x in conflicts:
        values = []
        for cid in x.get("카드", []):
            for v in (by_id.get(cid, {}).get("수치") or []):
                if v.get("항목") == x["항목"] and v.get("숫자") is not None:
                    item = {"숫자": v["숫자"], "값": v.get("값"), "출처": by_id[cid]["출처"], "한정어": v.get("한정어") or ""}
                    if item not in values:
                        values.append(item)
        conf_out.append({**x, "분류": CONFLICT_CLASS.get(x["종류"], "추가 확인 필요"),
                         "값들": values if x["종류"].startswith("값이 다름") and len({v["숫자"] for v in values}) > 1 else []})
    files = {}
    for c in cards:
        files[c["파일"]] = files.get(c["파일"], 0) + 1
    base = {
        "만든시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "요약": {"자료": summary.get("자료") or len(files), "쪽": summary.get("쪽"), "사실": len(cards), "원문일치": sum(1 for c in cards if c.get("원문확인")),
               "차별점": sum(1 for c in cards if c.get("유형") == "차별점" and c.get("원문확인")), "불일치": len(conflicts),
               "지시문의심쪽": summary.get("지시문의심쪽", 0)},
        "자료": files,
        "차별점": [it for it in strategy["항목"] if it["틀"] == "USP"],
        "고객분석": [it for it in strategy["항목"] if it["틀"] != "USP"],
        "결정자": strategy["결정자"],
        "기준": industry.get("기준", []),
        "시장": industry.get("산업", []),
        "불일치": conf_out,
        "암호화": [c["id"] for c in cards if c.get("원문확인") and ("AES" in c["내용"] + c.get("원문", "") or "SHA" in c["내용"] + c.get("원문", ""))][:6],
        "사진": photo_out,
        "사진요약": photo_check.get("요약") or {},
        "저장결과": index,
        "제약": [{"대상": m.group(1), "카드": c["id"]} for c in cards if c.get("원문확인") and (m := verify.LIMIT.search(c.get("내용", "")))],
    }
    jdump(web / "d" / "base.json", base)
    jdump(web / "d" / "cards.json", [{"id": c["id"], "유형": c.get("유형", ""), "파일": c["파일"], "출처": c["출처"], "내용": c["내용"],
                                      "원문": c.get("원문", ""), "확인": bool(c.get("원문확인"))} for c in cards])

    # ── 글꼴 · 소개 쪽 ──
    fdir = web / "assets" / "fonts"
    fdir.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "assets" / "fonts").glob("*"):
        shutil.copyfile(f, fdir / f.name)
    site = ROOT / "site"
    # 소개 쪽(index.html)은 팀원이 웹 저장소에서 직접 고치므로 덮어쓰지 않습니다. 결과 쪽(results.html)만 새로 보냅니다.
    if (site / "results.html").exists():
        t = (site / "results.html").read_text(encoding="utf-8")
        t = t.replace('<div class="sp"><a href="index.html"', '<div class="sp"><a href="app.html" style="color:#1D4ED8;font-weight:800">직접 사용해 보기</a><a href="index.html"')
        (web / "results.html").write_text(t, encoding="utf-8")
    if (site / "assets" / "cards").exists():
        shutil.copytree(site / "assets" / "cards", web / "assets" / "cards", dirs_exist_ok=True)
    total = sum(f.stat().st_size for f in web.rglob("*") if f.is_file() and ".git" not in f.parts) / 1e6
    print(f"완료: 저장 결과 {len(index)}묶음 · 사실 {len(cards)}개 · 웹 저장소 {total:.1f}MB → {web}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("사용법: python sync_web.py <웹 저장소 폴더> [--no-ai]")
    main(Path(args[0]).resolve(), readings_from_ai="--no-ai" not in sys.argv)
