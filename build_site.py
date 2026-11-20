"""소개용 정적 사이트 만들기 (빌드 도구 없이 HTML/CSS 만) → site/index.html, site/results.html, site/assets/

    python build_site.py                       # site/ 폴더에 만듭니다
    python build_site.py --video https://youtu.be/...   # 시연 영상 주소 넣기

results.html 은 data/ 에 저장된 실제 실행 결과를 그대로 보여 주는 쪽입니다. 생성 시각을 함께 적어 실시간 생성처럼 보이지 않게 합니다.
수치는 이 스크립트가 실행될 때 코드로 다시 잰 값만 씁니다. API 키, 원본 문서, 원본 사진 파일은 넣지 않습니다(카드뉴스 이미지만).
"""
from __future__ import annotations

import hashlib
import html
import inspect
import json
import shutil
import sys
from pathlib import Path

from kit import config, content, verify

try:
    from kit import cardnews
except Exception:  # noqa: BLE001
    cardnews = None

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
DATA, SITE_IN, OUT = ROOT / "data", ROOT / "input" / "site", ROOT / "site"
REPO_URL = "https://github.com/jisung6018-star/smartworkthon5-project"
ROLE_LABEL = {"경영진": "경영진", "영업 관리자": "실무 관리자", "전산·총무 담당": "전산 담당자"}
ROLE_SLUG = {"경영진": "exec", "영업 관리자": "manager", "전산·총무 담당": "it"}
MARKET_LABEL = {"공통": "시장 공통", "의료기관": "의료", "교육기관": "교육기관", "콜센터": "콜센터", "무역·물류": "무역·물류"}
MARKET_SLUG = {"공통": "common", "의료기관": "medical", "교육기관": "education", "콜센터": "callcenter", "무역·물류": "trade"}
MARKET_ORDER = ["콜센터", "교육기관", "의료기관", "무역·물류", "공통"]
DOCS = [("블로그", "블로그"), ("도입 사례", "도입사례"), ("영업 이메일", "이메일")]

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:"Pretendard","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;background:#F5F7FB;color:#0F172A;line-height:1.7;word-break:keep-all}
a{color:#1D4ED8;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px}
nav{background:#fff;border-bottom:1px solid #E3E9F2;position:sticky;top:0;z-index:5}
nav .wrap{display:flex;align-items:center;gap:22px;height:60px}
.logo{font-weight:800;font-size:21px;letter-spacing:-.03em;color:#0B1F3A}.for{background:#1D4ED8;color:#fff;border-radius:99px;padding:2px 11px;font-size:12px;font-weight:700;margin-left:8px}
nav .sp{margin-left:auto;display:flex;gap:20px;font-weight:600;font-size:15px}
.hero{background:linear-gradient(135deg,#0B1F3A 0%,#12306B 60%,#1D4ED8 100%);color:#fff;padding:72px 0 64px}
.hero h1{font-size:46px;line-height:1.25;letter-spacing:-.035em;margin:0 0 16px}.hero h1 em{font-style:normal;color:#FFC400}
.hero p{font-size:19px;color:#D7E1F5;margin:0 0 26px;max-width:720px}
.btn{display:inline-block;background:#FFC400;color:#0B1F3A;font-weight:800;border-radius:12px;padding:12px 22px;margin-right:10px}.btn.ghost{background:transparent;color:#fff;border:1.5px solid rgba(255,255,255,.6)}
.btn:hover{text-decoration:none;filter:brightness(1.05)}
section{padding:54px 0}h2{font-size:28px;letter-spacing:-.03em;margin:0 0 6px;color:#0B1F3A}.lead{color:#475569;margin:0 0 24px;font-size:16.5px}
.grid{display:grid;gap:16px}.g2{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
.card{background:#fff;border:1px solid #E3E9F2;border-radius:16px;padding:22px 24px}.card h3{margin:0 0 6px;font-size:18px;letter-spacing:-.02em;color:#0B1F3A}.card p{margin:0;color:#475569;font-size:15px}
.step{color:#1D4ED8;font-weight:800;font-size:13px;letter-spacing:.04em}
.kpi b{display:block;font-size:34px;letter-spacing:-.03em;color:#0B1F3A;line-height:1.2}.kpi span{color:#64748B;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0}.cards img{width:100%;border-radius:12px;display:block;box-shadow:0 6px 20px rgba(15,23,42,.10)}
.chip{display:inline-block;border-radius:99px;padding:2px 10px;font-size:12px;font-weight:700;margin-right:6px;white-space:nowrap}
.ok{background:#DCFCE7;color:#166534}.warn{background:#FEF3C7;color:#92400E}.bad{background:#FEE2E2;color:#991B1B}.mute{background:#E2E8F0;color:#475569}.info{background:#DBEAFE;color:#1E40AF}
.video{background:#0B1F3A;color:#fff;border-radius:16px;padding:44px;text-align:center}.video a{color:#FFC400;font-weight:800;font-size:20px}
.note{color:#64748B;font-size:14px}.saved{background:#FFFBEB;border:1px solid #FDE68A;border-radius:12px;padding:10px 16px;color:#92400E;font-size:14.5px;margin:0 0 18px}
.res{background:#fff;border:1px solid #E3E9F2;border-radius:20px;padding:28px 30px;margin-bottom:26px}.res h2{font-size:24px}.role{margin-top:26px;border-top:1px solid #E3E9F2;padding-top:20px}.role h3{margin:0 0 4px;font-size:19px;color:#0B1F3A}
details{border:1px solid #E3E9F2;border-radius:12px;margin-top:10px;background:#FBFCFE}summary{cursor:pointer;padding:12px 16px;font-weight:700;color:#0B1F3A}
.doc{padding:4px 22px 20px;font-size:15.5px;line-height:1.9;color:#1E293B}.doc h4{font-size:19px;margin:6px 0 10px;line-height:1.45}.doc h6{font-size:15.5px;margin:16px 0 4px;color:#0B1F3A}
.doc .rev{background:#FEF9C3;border-bottom:2px solid #EAB308;border-radius:3px;padding:1px 2px}.doc .fix{color:#64748B;font-size:13px;border-top:1px dashed #CBD5E1;margin-top:12px;padding-top:8px;line-height:1.6}
.src{background:#F1F5F9;border-radius:10px;padding:8px 12px;margin:6px 22px 0;color:#475569;font-size:13px}.src b{color:#0B1F3A}
footer{padding:36px 0 60px;color:#64748B;font-size:14px}
@media(max-width:860px){.g2,.g3,.g4,.cards{grid-template-columns:repeat(2,1fr)}.hero h1{font-size:34px}}
"""


def esc(t) -> str:
    return html.escape(str(t or ""))


def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def supports(func, name: str) -> bool:
    return name in inspect.signature(func).parameters


def chip(label: str, tone: str) -> str:
    return f'<span class="chip {tone}">{esc(label)}</span>'


def page(title: str, body: str, active: str) -> str:
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="티링크 전용 마케팅 솔루션 팩트마케터: 현장 사진 한 장과 제품 자료로 고객별 홍보 콘텐츠를 만들고 게시 전에 사실을 확인합니다.">
<style>{CSS}</style></head><body>
<nav><div class="wrap"><a href="index.html" class="logo">팩트마케터<span class="for">for 티링크</span></a>
<div class="sp"><a href="index.html"{' style="color:#0B1F3A"' if active == 'index' else ''}>소개</a><a href="results.html"{' style="color:#0B1F3A"' if active == 'results' else ''}>실행 결과</a><a href="{REPO_URL}">GitHub</a></div></div></nav>
{body}
<footer><div class="wrap">제5회 AI 스마트워크톤(2026-11-20) 트랙 A 출품작 · 팀 류지몬<br>이 사이트의 콘텐츠 예시는 티링크로부터 제품 정보를 제공받아 만든 광고성 콘텐츠의 시연입니다.</div></footer>
</body></html>"""


def main():
    video = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--video" and i + 1 < len(sys.argv)), "")
    demo = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--demo" and i + 1 < len(sys.argv)), "")
    cards = jload(DATA / "cards.json", [])
    by_id = {c["id"]: c for c in cards}
    conflicts = jload(DATA / "conflicts.json", [])
    photos = jload(SITE_IN / "photos.json", [])
    summary = jload(DATA / "summary.json", {})
    industry = jload(DATA / "industry.json", {"산업": []})
    photo_check = (jload(DATA / "photo_check.json") or {}).get("요약", {})
    valid = {c["id"] for c in cards if c.get("원문확인")}
    ledger = verify.build_ledger(cards, conflicts, photos)
    results = [r for f in sorted((DATA / "content").glob("*.json")) if (r := jload(f)) and r.get("역할")]
    results.sort(key=lambda r: MARKET_ORDER.index(r.get("산업") or "공통") if (r.get("산업") or "공통") in MARKET_ORDER else 9)
    # 시장마다 대표 결과 하나만 싣습니다 (네 가지 콘텐츠가 모두 있는 것을 먼저)
    best = {}
    for r in results:
        m = r.get("산업") or "공통"
        full = sum(1 for x in r["역할"].values() for k in ("카드뉴스", "블로그", "도입사례", "이메일") if x.get(k))
        if m != "공통" and (m not in best or full > best[m][0]):
            best[m] = (full, r)
    results = [best[m][1] for m in MARKET_ORDER if m in best]

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)

    def meta_of(name: str) -> dict:
        return next((p for p in photos if p["파일"] == name), {})

    def review(doc: dict, kind: str, market: str | None) -> dict:
        kw = {}
        if supports(verify.review, "kind"):
            kw["kind"] = kind
        if supports(verify.review, "market"):
            kw["market"] = market
        return verify.review(doc["제목"], doc["본문"], doc["문장"], ledger, [], valid, by_id, **kw)

    def inject(doc: dict, kind: str, market: str | None) -> dict:
        kw = {}
        if supports(verify.injection_test, "kind"):
            kw["kind"] = kind
        if supports(verify.injection_test, "market"):
            kw["market"] = market
        return verify.injection_test(doc["제목"], doc["본문"], ledger, [], **kw)

    def doc_html(doc: dict, kind: str, rv: dict) -> str:
        status = {s["글"]: s["상태"] for s in rv["문장"]}
        parts = [f"<h4>{esc(doc['제목'])}</h4>"]
        para, fixed = [], []
        for u in verify.units(doc["본문"]):
            if u["종류"] == "소제목":
                if para:
                    parts.append("<p>" + " ".join(para) + "</p>")
                    para = []
                parts.append(f"<h6>{esc(u['글'].lstrip('■ ').strip())}</h6>")
            elif u["종류"] == "고정 문구":
                fixed.append(esc(u["글"]))
            else:
                para.append(f'<span class="{"rev" if status.get(u["글"]) == "검토 필요" else ""}">{esc(u["글"])}</span>')
        if para:
            parts.append("<p>" + " ".join(para) + "</p>")
        if fixed:
            parts.append('<div class="fix">' + "<br>".join(fixed) + "</div>")
        return '<div class="doc">' + "".join(parts) + "</div>"

    def card_files(result: dict, role: str) -> list[str]:
        r = result["역할"][role]
        if not r.get("카드뉴스"):
            return []
        market = result.get("산업") or "공통"
        slug = f"{Path(result['사진']).stem}-{MARKET_SLUG.get(market, 'm')}"
        tmp = config.OUT / "site_cards" / slug
        photo = SITE_IN / result["사진"]
        mark = result.get("시장표시") or next((x.get("시장표시", "") for x in industry["산업"] if x["산업"] == market), "")
        made = None
        if cardnews is not None and photo.exists():
            try:
                made = cardnews.render_cards(photo, r["카드뉴스"], role, tmp, meta=meta_of(result["사진"]), cards_by_id=by_id, market_mark=mark)
            except Exception:  # noqa: BLE001
                made = None
        if not made and photo.exists():
            made = content.render_cards(photo, r["카드뉴스"], role, tmp)
        out = []
        for i, m in enumerate(made or [], 1):
            dst = OUT / "assets" / "cards" / slug / f"{ROLE_SLUG.get(role, 'role')}_{i}.jpg"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(m["파일"], dst)
            out.append(dst.relative_to(OUT).as_posix())
        return out

    # ── 실행 결과 쪽 ──
    blocks, n_docs, n_cards, inj_total, inj_hit, sent_total, sent_fact, scores = [], 0, 0, 0, 0, 0, 0, []
    hero_cards: list[str] = []
    for result in results:
        market = result.get("산업") or "공통"
        mk = None if market == "공통" else market
        meta = meta_of(result["사진"])
        who = meta.get("가린고객명") or meta.get("설치형태_홈페이지") or "설치 현장"
        p = (result.get("판독") or {}).get("판독") or {}
        mark = result.get("시장표시") or next((x.get("시장표시", "") for x in industry["산업"] if x["산업"] == market), "")
        head = (f'<h2>{esc(MARKET_LABEL.get(market, market))} {chip(mark, "warn") if mark else ""}</h2>'
                f'<p class="lead">현장 사진: {esc(who)} · {esc(meta.get("업종") or meta.get("구분") or "")} · 사진에서 읽은 설치 형태 {esc(p.get("설치형태", "-"))} '
                f'(두 모델 판독 {esc((result.get("판독") or {}).get("교차검증", "-"))})</p>'
                f'<div class="saved">저장된 실행 결과입니다 · 생성 시각 {esc(result.get("생성시각") or "2026-11-20")} · 이 쪽에서 새로 생성하지 않습니다.</div>')
        roles_html = []
        for role, r in result["역할"].items():
            imgs = card_files(result, role)
            n_cards += len(imgs)
            if not hero_cards and market == "교육기관" and imgs:
                hero_cards = imgs
            inner = [f'<h3>{esc(ROLE_LABEL.get(role, role))}에게</h3>']
            if imgs:
                inner.append('<div class="cards">' + "".join(f'<img src="{esc(i)}" alt="카드뉴스 {n}장" loading="lazy">' for n, i in enumerate(imgs, 1)) + "</div>")
            for kind, key in DOCS:
                doc = r.get(key)
                if not doc:
                    continue
                rv = review(doc, kind, mk)
                chk = rv["검수"]
                if not chk:
                    continue
                t = inject(doc, kind, mk)
                n_docs += 1
                inj_total += t["주입"]
                inj_hit += t["검출"]
                sent_total += len(rv["문장"])
                sent_fact += sum(1 for s in rv["문장"] if s["표시"] == "확인된 사실")
                scores.append(chk["점수"])
                tone = "bad" if chk["차단"] else "warn" if chk["문장통계"]["검토 필요"] else "ok"
                state = "차단" if chk["차단"] else "통과 · 확인할 문장 있음" if chk["문장통계"]["검토 필요"] else "통과"
                ms = chk.get("미션") or []
                badge = (chip(state, tone) + chip(f"검수 {chk['점수']}점", "mute")
                         + (chip(f"가이드라인 미션 {sum(x['결과'] == '통과' for x in ms)}/{len(ms)}", "mute") if ms else "")
                         + chip(f"근거 있는 문장 {chk['문장통계']['통과']}/{len(rv['문장'])}", "mute"))
                used = []
                for s in rv["문장"]:
                    for c in s.get("근거카드", []):
                        if c in by_id and c not in used:
                            used.append(c)
                src = "".join(f'<div class="src"><b>{esc(by_id[c]["출처"])}</b> · 원문 “{esc(by_id[c].get("원문", ""))}”</div>' for c in used[:5])
                inner.append(f'<details><summary>{esc(kind)} &nbsp;{badge}</summary>{doc_html(doc, kind, rv)}'
                             f'<p class="note" style="margin:10px 22px 0">이 원고가 근거로 삼은 자료 {len(used)}건 중 일부</p>{src}<div style="height:16px"></div></details>')
            roles_html.append('<div class="role">' + "".join(inner) + "</div>")
        blocks.append(f'<div class="res" id="{MARKET_SLUG.get(market, "m")}">{head}{"".join(roles_html)}</div>')

    fp = verify.false_positive_test(cards, conflicts, ledger)
    vt = verify.variant_test(cards, conflicts, ledger)
    anchors = " · ".join(f'<a href="#{MARKET_SLUG.get(r.get("산업") or "공통", "m")}">{esc(MARKET_LABEL.get(r.get("산업") or "공통", ""))}</a>' for r in results)
    body = f"""<section><div class="wrap"><h2>실제 실행 결과</h2>
<p class="lead">티링크의 제품 자료와 설치 현장 사진으로 실제로 만든 콘텐츠와 검수 결과입니다. 노란 밑줄은 자료 근거 없이 쓴 문장이라 담당자가 읽어 봐야 하는 곳입니다.<br>바로 가기: {anchors}</p>
{"".join(blocks)}</div></section>"""
    (OUT / "results.html").write_text(page("팩트마케터 · 실행 결과", body, "results"), encoding="utf-8")

    # ── 소개 쪽 ──
    n_files = summary.get("자료") or len({c["파일"] for c in cards})
    kpis = [
        (f"{len(cards)}개", f"자료 {n_files}개 {summary.get('쪽', '')}쪽에서 확인한 사실 (원문 일치 {len(valid)}개)"),
        (f"{len(conflicts)}건", "자료마다 값이나 조건이 다른 항목을 찾아 표시"),
        (f"{inj_hit} / {inj_total}", f"일부러 넣은 오류를 잡은 수 (원고 {n_docs}편)"),
        (f"{fp['오탐률']}%", f"맞는 문장 {fp['정상 문장']}개 중 잘못 잡은 비율"),
        (f"{vt['잘못 걸림']}건", f"표현을 바꿔 쓴 수치 {vt['변형 문장']}문장 중 잘못 잡은 수"),
        (f"{n_cards}장 · {n_docs}편", "만들어 둔 카드뉴스와 원고 (블로그 · 도입 사례 · 영업 이메일)"),
        (f"{sent_fact} / {sent_total}", "원고 문장 중 자료 근거가 붙은 문장"),
        (f"{photo_check.get('일치', '-')} / {photo_check.get('두모델판독', '-')}", "현장 사진을 두 AI 모델이 따로 읽어 설치 형태가 일치한 수"),
    ]
    hero_img = ('<div class="cards" style="margin-top:34px">' + "".join(f'<img src="{esc(i)}" alt="카드뉴스 예시">' for i in hero_cards) + "</div>") if hero_cards else ""
    video_html = (f'<a href="{esc(video)}">시연 영상 보기 →</a><p class="note" style="color:#B8C4DD;margin:8px 0 0">유튜브에서 3분 시연을 볼 수 있습니다.</p>' if video
                  else '<span style="font-size:20px;font-weight:800">시연 영상 준비 중</span><p class="note" style="color:#B8C4DD;margin:8px 0 0">업로드가 끝나면 이 자리에 링크가 들어갑니다.</p>')
    demo_html = f'<a class="btn ghost" href="{esc(demo)}">라이브 데모</a>' if demo else ""
    body = f"""<div class="hero"><div class="wrap"><h1>현장 사진 한 장으로,<br><em>고객마다 다른</em> 홍보 콘텐츠를</h1>
<p>티링크의 제품 자료와 설치 현장 사진만 넣으면, AI가 제품과 기술적 차별점을 분석해 시장과 구매 결정자에 맞는 카드뉴스·블로그·도입 사례·영업 이메일을 만들고, 게시 전에 모든 문장을 원문 근거로 확인합니다.</p>
<a class="btn" href="results.html">실행 결과 보기</a><a class="btn ghost" href="{REPO_URL}">GitHub 저장소</a>{demo_html}{hero_img}</div></div>
<section><div class="wrap"><h2>풀려는 문제</h2><p class="lead">홍보 글을 AI에게 맡기면 빠르지만, 그대로 게시하기는 어렵습니다.</p>
<div class="grid g3"><div class="card"><h3>없는 숫자가 섞입니다</h3><p>자료에 없는 수치와 고객 후기가 그럴듯하게 들어갑니다. 확인하는 데 쓰는 시간이 쓰는 시간보다 길어집니다.</p></div>
<div class="card"><h3>조건이 빠집니다</h3><p>“99%”는 자료에서 ‘인터넷 전화’ 기준입니다. 조건을 빼고 쓰면 과장 광고가 됩니다. 자료끼리 숫자가 다른 경우도 있습니다.</p></div>
<div class="card"><h3>누구에게나 같은 말을 합니다</h3><p>경영진, 실무 관리자, 전산 담당자는 궁금한 것이 다릅니다. 시장마다 내세울 근거도 다릅니다.</p></div></div></div></section>
<section style="background:#fff;border-top:1px solid #E3E9F2;border-bottom:1px solid #E3E9F2"><div class="wrap"><h2>이렇게 작동합니다</h2><p class="lead">AI가 쓰고, 프로그램이 사실을 판정하고, 사람이 승인합니다.</p>
<div class="grid g4"><div class="card"><span class="step">STEP 1</span><h3>사실 정리</h3><p>제안서·매뉴얼·회사소개서·홈페이지에서 사실을 뽑고, 출처 쪽과 원문 구절을 붙입니다. 자료끼리 다른 값도 찾습니다.</p></div>
<div class="card"><span class="step">STEP 2</span><h3>시장과 결정자 전략</h3><p>콜센터·교육기관·의료·무역물류 중 어디에 근거가 충분한지 비교하고, 결정자마다 다른 설득 전략을 세웁니다. 근거가 없으면 판단을 보류합니다.</p></div>
<div class="card"><span class="step">STEP 3</span><h3>콘텐츠 4종</h3><p>현장 사진 한 장으로 카드뉴스, 블로그, 도입 사례, 영업 이메일을 만듭니다. 도입 사례가 없는 시장은 기능만 근거로 씁니다.</p></div>
<div class="card"><span class="step">STEP 4</span><h3>검수와 승인</h3><p>숫자, 조건, 고객명, 티링크 블로그 가이드라인을 프로그램이 검사합니다. 막힌 곳이 있으면 승인할 수 없습니다.</p></div></div></div></section>
<section><div class="wrap"><h2>측정한 값</h2><p class="lead">이 쪽을 만들 때 프로그램이 다시 잰 값만 적었습니다. 측정하지 않은 개선율은 쓰지 않습니다.</p>
<div class="grid g4">{"".join(f'<div class="card kpi"><b>{esc(v)}</b><span>{esc(t)}</span></div>' for v, t in kpis)}</div>
<p class="note" style="margin-top:16px">한계: 검수 통과는 ‘자료와 어긋나지 않음’을 뜻합니다. 자료 자체가 맞는지는 사람이 확인해야 합니다. 콘텐츠가 실제로 고객의 관심을 얼마나 끄는지는 측정하지 못했습니다.</p></div></section>
<section style="padding-top:0"><div class="wrap"><div class="video">{video_html}</div></div></section>"""
    (OUT / "index.html").write_text(page("팩트마케터 for 티링크", body, "index"), encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"site/ 완성: 결과 {len(results)}묶음 · 카드뉴스 {n_cards}장 · 원고 {n_docs}편 · 주입 {inj_hit}/{inj_total} · 오탐률 {fp['오탐률']}% · 변형 {vt['잘못 걸림']}/{vt['변형 문장']} · "
          f"근거 문장 {sent_fact}/{sent_total} · 점수 최저 {min(scores) if scores else '-'} · {size:.1f}MB")


if __name__ == "__main__":
    main()
