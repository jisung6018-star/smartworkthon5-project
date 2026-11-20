"""카드뉴스 4장 — HTML/CSS 템플릿을 브라우저로 찍어 만드는 고품질 렌더러.

    from kit import cardnews
    files = cardnews.render_cards(photo, cards, role, out_dir, meta=사진정보, cards_by_id=사실카드)

글은 모두 카드 데이터(제목·본문)에서 옵니다. 코드가 붙이는 것은 고정 표기뿐입니다
(실제 설치 현장, 출처, 상담 문의, 넘겨 보기, 광고, 쪽 번호, 브랜드 이름).
3장의 큰 숫자는 그 장이 인용한 사실 카드의 수치 중 문구에 실제로 적힌 것만 코드가 골라 넣습니다.
사진 위에 글을 직접 올리지 않고, 사진은 액자 안에 넣어 "실제 설치 현장" 표기와 함께 보여 줍니다.

브라우저는 별도 프로세스(kit/_cardnews_worker.py)로 띄웁니다. 실패하면 kit.content.render_cards 로 대신 그립니다.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "assets" / "fonts" / "PretendardVariable.woff2"
WORKER = Path(__file__).resolve().parent / "_cardnews_worker.py"
SIZE = (1080, 1350)

NAVY, BLUE, YELLOW, PAPER, INK, WHITE = "#0B1B3F", "#1F4FE0", "#FFC93C", "#F6F3EC", "#0E1730", "#FFFFFF"
ROLE_STYLE = {      # 역할별 포인트 색 (밝은 바탕용 진한 색, 어두운 바탕용 밝은 색)
    "경영진": {"key": "exec", "accent": "#FFC93C", "deep": "#A86A00", "chip": "경영진께"},
    "영업 관리자": {"key": "sales", "accent": "#3DDCB9", "deep": "#0B7F69", "chip": "영업 관리자께"},
    "전산·총무 담당": {"key": "it", "accent": "#7CC0FF", "deep": "#1D4ED8", "chip": "전산·총무 담당자께"},
}
DEFAULT_STYLE = {"key": "etc", "accent": "#FFC93C", "deep": "#A86A00", "chip": ""}

# 선으로만 그린 아이콘 (24×24, 외부 자료 없이 직접 그림)
ICONS = {
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/><path d="M12 17.5V21"/><path d="M8.5 21h7"/>',
    "phone": '<path d="M6.6 3.5h2.6l1.3 4-1.9 1.4a12 12 0 0 0 6.5 6.5l1.4-1.9 4 1.3v2.6a2 2 0 0 1-2.2 2A17 17 0 0 1 4.6 5.7a2 2 0 0 1 2-2.2z"/>',
    "chart": '<path d="M4 20h16"/><rect x="6" y="11" width="3" height="6" rx="1"/><rect x="11" y="7" width="3" height="10" rx="1"/><rect x="16" y="4" width="3" height="13" rx="1"/>',
    "shield": '<path d="M12 3l7.5 3v5.5c0 4.4-3 8-7.5 9.5-4.5-1.5-7.5-5.1-7.5-9.5V6z"/><path d="M8.8 12.2l2.3 2.3 4.2-4.6"/>',
    "spark": '<path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z"/><path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "coin": '<circle cx="12" cy="12" r="8.5"/><path d="M8.2 9l1.6 6 2.2-5.2 2.2 5.2 1.6-6"/><path d="M7.5 11.6h9"/>',
    "server": '<rect x="4" y="4" width="16" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="16" height="6.5" rx="1.6"/><path d="M7.5 7.3h.01M7.5 16.8h.01"/><path d="M11 7.3h5.5M11 16.8h5.5"/>',
    "doc": '<path d="M7 3.5h7.5L19 8v12.5H7z"/><path d="M14.5 3.5V8H19"/><path d="M10 12.5h6M10 16h6"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1.2-1.2"/>',
    "check": '<circle cx="12" cy="12" r="8.5"/><path d="M8.3 12.3l2.6 2.6 4.8-5.2"/>',
    "people": '<circle cx="9" cy="8.5" r="3.2"/><path d="M3 19.5c.6-3.2 3-5 6-5s5.4 1.8 6 5"/><circle cx="17" cy="9.5" r="2.4"/><path d="M16.5 14.6c2.2.2 3.9 1.7 4.5 4.4"/>',
    "camera": '<path d="M4 8h3.2l1.5-2.5h6.6L16.8 8H20v11.5H4z"/><circle cx="12" cy="13.5" r="3.6"/>',
    "arrow": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
}
CHECK_FILL = ('<svg viewBox="0 0 24 24" width="{s}" height="{s}"><circle cx="12" cy="12" r="10.5" fill="currentColor"/>'
              '<path d="M7.6 12.4l2.9 2.9 5.6-6" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
ICON_RULES = [      # 문구의 낱말로 아이콘을 고름
    ("shield", r"암호|보안|AES|SHA|권한|유출|접근|학내망|사유|이력 조회"),
    ("coin", r"원\b|비용|요금|견적|가격|VAT|약정|만원"),
    ("chart", r"리포트|대시보드|통계|현황|역량|별점|통화량|성과|평가"),
    ("spark", r"AI|요약|STT|자동 기록|자동 요약|키워드"),
    ("camera", r"사진"),
    ("server", r"서버|랙|설치|스위치|미러링|단자함|벽걸이|허브|구축"),
    ("link", r"호환|회선|KT|SK|LG|연동|연결|라우터"),
    ("mic", r"녹취|녹음"),
    ("people", r"상담원|선생님|직원|담당자|고객별|개인 ID"),
    ("doc", r"기록|이력|보고서|원문|근거|보관"),
    ("phone", r"전화|통화|상담|문의"),
]
NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(만|억)?")


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _svg(name: str, size: int = 44) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


def _icon_for(line: str, used: set[str] | None = None) -> str:
    """문구에 맞는 아이콘. 같은 장에서 이미 쓴 아이콘은 건너뜁니다."""
    used = used if used is not None else set()
    name = next((n for n, pat in ICON_RULES if n not in used and re.search(pat, line)), None)
    name = name or next((n for n in ("check", "spark", "doc", "link") if n not in used), "check")
    used.add(name)
    return name


def _tokens(text: str) -> set[float]:
    """문구에 적힌 숫자 값 (만·억 단위는 풀어서)."""
    out = set()
    for m in NUM.finditer(text or ""):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.add(round(v * (1e4 if m.group(2) == "만" else 1e8 if m.group(2) == "억" else 1), 2))
    return out


def _rich(line: str) -> str:
    """본문 한 줄 → HTML. '[확인 필요]' 는 작은 표시로 바꿔 그대로 보이게 합니다."""
    out = _esc(line)
    return re.sub(r"\s*\[확인 필요[^\]]*\]", ' <span class="need">확인 필요</span>', out)


def _headline(title: str, mark: bool) -> str:
    """제목 → HTML. 쉼표 뒤(없으면 물음표가 붙은 마지막 낱말)를 강조색으로 칠합니다. 글자는 바꾸지 않습니다."""
    t = str(title or "").strip()
    if not mark:
        return _esc(t)
    m = re.match(r"^(.*?[,，])\s*(.+)$", t)
    if m:
        return f"{_esc(m.group(1))} <em>{_esc(m.group(2))}</em>"
    m = re.match(r"^(.*\s)(\S+[?？])$", t)
    if m:
        return f"{_esc(m.group(1))}<em>{_esc(m.group(2))}</em>"
    return _esc(t)


def _caption(meta: dict | None) -> tuple[str, str]:
    """사진 설명: ("실제 설치 현장", "윌** · 교육"). 고객명은 가려진 이름 그대로 씁니다."""
    meta = meta or {}
    parts = [str(meta.get("가린고객명") or "").strip(), re.sub(r"\s*·\s*", "·", str(meta.get("업종") or "").strip())]
    return "실제 설치 현장", " · ".join(p for p in parts if p)


def _split_value(value: str) -> tuple[str, str, str]:
    m = re.match(r"^(\D*?)(\d[\d,.]*)(.*)$", str(value or "").strip())
    return (m.group(1).strip(), m.group(2), m.group(3).strip()) if m else ("", str(value or ""), "")


def pick_stats(card: dict, cards_by_id: dict | None, limit: int = 2) -> list[dict]:
    """3장의 큰 숫자: 이 장이 인용한 사실 카드의 수치 가운데, 문구(제목·본문)에 실제로 적힌 숫자만 고릅니다 (코드 판정)."""
    lines = [str(x) for x in (card.get("본문") or [])]
    text_tokens = _tokens(" ".join([str(card.get("제목") or ""), *lines]))
    found, seen = [], set()
    for cid in card.get("근거카드") or []:
        fact = (cards_by_id or {}).get(cid) or {}
        for v in fact.get("수치") or []:
            try:
                num = round(float(v.get("숫자")), 2)
            except (TypeError, ValueError):
                continue
            value = str(v.get("값") or "")
            if num in seen or num not in text_tokens or not re.search(r"\d", value) or len(value) > 14:
                continue
            if v.get("항목") == "기타" and num < 13:           # '3회', '5자' 같은 작은 개수는 큰 숫자로 내세우지 않음
                continue
            line_no = next((i for i, ln in enumerate(lines) if num in _tokens(ln)), None)
            seen.add(num)
            qual = str(v.get("한정어") or "").strip()
            found.append({"값": value, "항목": "" if v.get("항목") in (None, "기타") else str(v["항목"]),
                          "한정어": "" if re.search(r"없음|확인 ?필요|미기재", qual) else qual, "출처": str(fact.get("출처") or ""),
                          "줄": line_no, "확인필요": line_no is not None and "[확인 필요" in lines[line_no], "카드": cid})
    found.sort(key=lambda s: (s["항목"] == "", s["줄"] if s["줄"] is not None else 99))
    return found[:limit]


def _bigrams(s: str) -> set[str]:
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", s or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _source_for(line: str, card: dict, cards_by_id: dict | None) -> str:
    """이 줄과 가장 겹치는 인용 카드의 출처 (겹침이 적으면 붙이지 않음)."""
    grams, best, score = _bigrams(line), "", 0
    for cid in card.get("근거카드") or []:
        fact = (cards_by_id or {}).get(cid) or {}
        s = len(grams & _bigrams(f"{fact.get('내용', '')} {fact.get('원문', '')}"))
        if s > score:
            best, score = str(fact.get("출처") or ""), s
    return best if score >= 3 else ""


def _luminance(hex_color: str) -> float:
    c = hex_color.lstrip("#")
    ch = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return round((a + 0.05) / (b + 0.05), 1)


# ───────────────────────── 화면 틀 ─────────────────────────
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1350px;overflow:hidden;background:#fff}
body{font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:var(--ink);word-break:keep-all;overflow-wrap:break-word;
  -webkit-font-smoothing:antialiased;letter-spacing:-0.02em}
.page{position:relative;width:1080px;height:1350px;overflow:hidden;padding:76px 80px 0}
.top{position:relative;z-index:3;display:flex;align-items:center;justify-content:space-between;height:64px}
.brand{display:flex;align-items:center;gap:14px;font-size:30px;font-weight:700;letter-spacing:-0.03em}
.brand i{width:22px;height:22px;border-radius:7px;background:var(--yellow);box-shadow:10px 10px 0 -3px var(--blue)}
.chips{display:flex;gap:12px;align-items:center}
.role{font-size:30px;font-weight:800;padding:13px 28px;border-radius:999px;letter-spacing:-0.03em}
.mark{font-size:28px;font-weight:800;padding:12px 24px;border-radius:999px;background:var(--yellow);color:var(--navy)}
.main{position:absolute;z-index:2;left:80px;right:80px}
.inner{transform-origin:top left}
.foot{position:absolute;z-index:3;left:80px;right:80px;bottom:60px;height:44px;display:flex;align-items:center;justify-content:space-between}
.dots{display:flex;gap:11px;align-items:center}
.dots b{width:13px;height:13px;border-radius:50%;background:currentColor;opacity:.28}
.dots b.on{width:46px;border-radius:999px;opacity:1;background:var(--yellow)}
.pgno{font-size:27px;font-weight:700;opacity:.6;letter-spacing:.02em}
h1{font-weight:850;letter-spacing:-0.045em;text-wrap:balance}
.need{display:inline-block;font-size:.58em;font-weight:800;padding:.16em .55em;border-radius:.5em;background:#FFE8A3;color:#6B4A00;vertical-align:.18em;letter-spacing:-0.02em;white-space:nowrap}
figure.shot{position:relative;background:#fff;padding:14px 14px 0;border-radius:30px;box-shadow:0 34px 70px -18px rgba(3,10,32,.55),0 6px 16px rgba(3,10,32,.18)}
figure.shot img{display:block;width:100%;border-radius:20px;object-fit:cover;background:#dfe3ea}
figure.shot figcaption{display:flex;align-items:center;gap:12px;height:74px;padding:0 10px;font-size:27px;font-weight:800;color:var(--navy);white-space:nowrap}
figure.shot figcaption .tag{font-size:23px;font-weight:800;color:#fff;background:var(--blue);padding:7px 15px;border-radius:999px}

/* 1장: 문제 */
.p1{background:radial-gradient(1200px 900px at 105% -10%,#1C3F9C 0%,rgba(28,63,156,0) 58%),linear-gradient(160deg,#0B1B3F 0%,#081430 100%);color:#fff}
.p1 .grid{position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.085) 2px,transparent 2.4px);background-size:38px 38px;
  -webkit-mask-image:linear-gradient(200deg,#000 0%,transparent 55%);mask-image:linear-gradient(200deg,#000 0%,transparent 55%)}
.p1 .ring{position:absolute;right:-190px;bottom:120px;width:640px;height:640px;border-radius:50%;border:74px solid rgba(255,255,255,.045)}
.p1 .role{background:var(--accent);color:var(--navy)}
.p1 .main{top:196px;height:640px}
.p1 h1{font-size:112px;line-height:1.14;color:#fff}
.p1 h1 em{font-style:normal;color:var(--yellow)}
.p1 .lines{list-style:none;margin-top:44px;padding-left:30px;border-left:8px solid var(--accent)}
.p1 .lines li{font-size:41px;line-height:1.5;font-weight:500;color:#D5DDF3;letter-spacing:-0.03em}
.p1 .stage{position:absolute;z-index:2;left:80px;right:80px;bottom:128px;display:flex;align-items:flex-end;justify-content:space-between}
.p1 figure.shot{transform:rotate(-2.2deg);transform-origin:bottom left}
.p1 .swipe{display:flex;flex-direction:column;align-items:flex-end;gap:18px;font-size:31px;font-weight:700;color:#C9D3EE;padding-bottom:6px}
.p1 .swipe span{display:flex;align-items:center;justify-content:center;width:112px;height:112px;border-radius:50%;background:var(--yellow);color:var(--navy);
  box-shadow:0 18px 40px -10px rgba(255,201,60,.55)}

/* 2장: 해결 */
.p2{background:var(--paper)}
.p2::before{content:"";position:absolute;right:-220px;top:-240px;width:700px;height:700px;border-radius:50%;background:radial-gradient(circle,#DCE6FF 0%,rgba(220,230,255,0) 70%)}
.p2 .role,.p3 .role{background:var(--navy);color:#fff}
.p2 .main{top:186px;height:1012px}
.p2 .pg,.p3 .pg{display:inline-block;font-size:30px;font-weight:800;color:var(--deep);letter-spacing:.06em;margin-bottom:14px}
.p2 .inner{display:flex;flex-direction:column;min-height:100%}
.p2 h1{font-size:92px;line-height:1.16;color:var(--navy)}
.p2 h1 em,.p3 h1 em{font-style:normal;background:linear-gradient(transparent 58%,#FFD966 58%,#FFD966 92%,transparent 92%);padding:0 .06em}
.p2 .bar,.p3 .bar{width:120px;height:12px;border-radius:999px;background:var(--yellow);margin:30px 0 40px}
.p2 .points{list-style:none;display:flex;flex-direction:column;gap:26px;flex:1}
.p2 .points li{display:flex;align-items:center;gap:34px;background:#fff;border-radius:38px;padding:34px 40px;min-height:196px;flex:1;max-height:268px;
  box-shadow:0 22px 46px -22px rgba(11,27,63,.30),0 2px 6px rgba(11,27,63,.06)}
.p2 .ic{flex:none;display:flex;align-items:center;justify-content:center;width:124px;height:124px;border-radius:36px;background:var(--blue);color:#fff;
  box-shadow:0 16px 30px -14px rgba(31,79,224,.7)}
.p2 .points li:nth-child(2) .ic{background:var(--navy);box-shadow:0 16px 30px -14px rgba(11,27,63,.7)}
.p2 .points li:nth-child(3) .ic{background:var(--yellow);color:var(--navy);box-shadow:0 16px 30px -14px rgba(255,201,60,.9)}
.p2 .tx span{display:block;font-size:26px;font-weight:800;color:var(--deep);letter-spacing:.08em;margin-bottom:8px}
.p2 .tx p{font-size:46px;line-height:1.3;font-weight:750;color:var(--navy);letter-spacing:-0.04em;text-wrap:balance}

/* 3장: 근거 */
.p3{background:#fff}
.p3::before{content:"";position:absolute;left:0;right:0;top:0;height:560px;background:linear-gradient(180deg,#EEF3FF 0%,rgba(238,243,255,0) 100%)}
.p3 .main{top:186px;height:1024px}
.p3 .inner{display:flex;flex-direction:column;min-height:100%}
.p3 h1{font-size:84px;line-height:1.16;color:var(--navy)}
.p3 .bar{margin:26px 0 34px}
.p3 .stats{display:grid;gap:24px}
.p3 .stats.n2{grid-template-columns:1fr 1fr}
.p3 .stat{position:relative;display:flex;flex-direction:column;background:var(--navy);color:#fff;border-radius:36px;padding:34px 38px 30px;overflow:hidden;
  box-shadow:0 26px 54px -24px rgba(11,27,63,.6)}
.p3 .stat::after{content:"";position:absolute;right:-70px;top:-70px;width:220px;height:220px;border-radius:50%;background:rgba(255,255,255,.06)}
.p3 .stat .over{font-size:27px;font-weight:700;color:#AFC0EC;margin-bottom:4px}
.p3 .stat .val{display:inline-flex;align-items:baseline;white-space:nowrap;color:var(--yellow);font-weight:880;letter-spacing:-0.05em;line-height:1.05}
.p3 .stat .val .num{font-size:150px}
.p3 .stat .val .unit{font-size:60px;margin-left:8px;letter-spacing:-0.03em}
.p3 .stat .val .pre{font-size:50px;margin-right:12px}
.p3 .stats.n2 .stat .val .num{font-size:118px}
.p3 .stats.n2 .stat .val .unit{font-size:48px}
.p3 .stat .desc{font-size:35px;line-height:1.34;font-weight:650;margin-top:8px;letter-spacing:-0.035em;text-wrap:balance}
.p3 .stat .meta{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:auto;padding-top:18px}
.p3 .stat .qual{font-size:24px;font-weight:750;color:var(--navy);background:#fff;padding:6px 14px;border-radius:999px}
.p3 .stat .src{font-size:23px;font-weight:600;color:#9FB1E0}
.p3 .stat .need{font-size:24px;vertical-align:0}
.p3 .stats.n1 .stat{display:grid;grid-template-columns:auto 1fr;column-gap:44px;align-items:center;padding:40px 44px}
.p3 .stats.n1 .stat .right{display:flex;flex-direction:column;align-self:stretch;justify-content:center}
.p3 .stats.n1 .stat .meta{margin-top:0}
.p3 .stats.n1 .stat .left{min-width:0}
.p3 .ev{list-style:none;display:flex;flex-direction:column;gap:20px;margin-top:30px}
.p3 .ev.solo{margin-top:0;gap:22px}
.p3 .ev li{display:flex;gap:22px;align-items:flex-start;background:#F4F6FB;border-radius:28px;padding:26px 30px}
.p3 .ev.solo li{position:relative;padding:34px 36px 34px 44px;background:#fff;box-shadow:0 20px 44px -24px rgba(11,27,63,.32),0 0 0 2px #E7ECF8 inset;overflow:hidden}
.p3 .ev.solo li::before{content:"";position:absolute;left:0;top:0;bottom:0;width:12px;background:var(--blue)}
.p3 .ev.solo li:nth-child(2)::before{background:var(--navy)}
.p3 .ev.solo li:nth-child(3)::before{background:var(--yellow)}
.p3 .ev .ck{flex:none;color:var(--blue);margin-top:2px}
.p3 .ev p{font-size:38px;line-height:1.34;font-weight:700;color:var(--navy);letter-spacing:-0.04em;text-wrap:balance}
.p3 .ev.solo p{font-size:44px}
.p3 .ev .src{display:inline-block;margin-top:10px;font-size:23px;font-weight:650;color:#51607F;background:#E4EAF8;padding:5px 14px;border-radius:999px}
.p3 .case{margin-top:auto;padding-top:30px}
.p3 .case .band{display:flex;align-items:center;gap:30px;background:var(--paper);border-radius:34px;padding:20px 30px 20px 20px}
.p3 .case img{flex:none;width:200px;height:200px;border-radius:24px;object-fit:cover;box-shadow:0 14px 30px -12px rgba(11,27,63,.45);border:6px solid #fff}
.p3 .case.wide img{width:290px}
.p3 .case .tag{display:inline-block;font-size:25px;font-weight:800;color:#fff;background:var(--blue);padding:8px 18px;border-radius:999px}
.p3 .case .who{font-size:44px;font-weight:850;color:var(--navy);margin-top:14px;letter-spacing:-0.045em}

/* 4장: 제안 */
.p4{background:radial-gradient(900px 700px at -5% 105%,#0B1B3F 0%,rgba(11,27,63,0) 62%),linear-gradient(150deg,#2458F0 0%,#1A44C8 100%);color:#fff}
.p4 .ring{position:absolute;right:-230px;top:-230px;width:700px;height:700px;border-radius:50%;border:80px solid rgba(255,255,255,.07)}
.p4 .role{background:#fff;color:var(--navy)}
.p4 .main{top:206px;height:640px}
.p4 h1{font-size:100px;line-height:1.16;color:#fff}
.p4 h1 em{font-style:normal;color:var(--yellow)}
.p4 .float{position:absolute;z-index:2;right:80px;display:none;transform:rotate(2.4deg);transform-origin:center}
.p4 .bar{width:120px;height:12px;border-radius:999px;background:var(--yellow);margin:34px 0 36px}
.p4 .lines{list-style:none;display:flex;flex-direction:column;gap:16px}
.p4 .lines li{display:flex;gap:18px;align-items:flex-start;font-size:41px;line-height:1.36;font-weight:600;color:#EAF0FF;letter-spacing:-0.035em}
.p4 .lines li svg{flex:none;margin-top:6px;color:var(--yellow)}
.p4 .cta{position:absolute;z-index:2;left:80px;right:80px;bottom:150px}
.p4 .btn{display:flex;align-items:center;justify-content:center;gap:22px;height:148px;border-radius:999px;background:var(--yellow);color:var(--navy);
  font-size:50px;font-weight:800;letter-spacing:-0.04em;box-shadow:0 30px 60px -20px rgba(4,12,40,.7)}
.p4 .btn b{font-size:66px;font-weight:880;letter-spacing:-0.03em}
.p4 .url{margin-top:26px;text-align:center;font-size:36px;font-weight:650;color:#DCE6FF;letter-spacing:0}
.p4 .ad{font-size:22px;font-weight:700;padding:5px 12px;border-radius:8px;border:2px solid rgba(255,255,255,.55);color:rgba(255,255,255,.85)}
"""

FIT_JS = """
window.__fit = () => {
  document.querySelectorAll('[data-fit]').forEach(el => {
    const max = parseFloat(el.dataset.fit), min = parseFloat(el.dataset.min || 56);
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (el.offsetHeight > max && size > min) { size -= 2; el.style.fontSize = size + 'px'; }
  });
  document.querySelectorAll('[data-fitw]').forEach(el => {
    const box = el.parentElement, max = box.clientWidth - parseFloat(getComputedStyle(box).paddingLeft) - parseFloat(getComputedStyle(box).paddingRight);
    let scale = 1;
    while (el.offsetWidth * scale > Math.min(max, parseFloat(el.dataset.fitw) || max) && scale > 0.4) { scale -= 0.03; }
    if (scale < 1) { el.style.zoom = scale; }
  });
  const main = document.querySelector('.main'), inner = document.querySelector('.inner');
  const capfit = () => document.querySelectorAll('figcaption').forEach(c => {       // 사진 설명: 액자 폭에 맞춰 글자를 줄임 (이름을 자르지 않음)
    let s = 1;
    while (c.scrollWidth > c.clientWidth + 1 && s > 0.55) { s -= 0.04; c.style.fontSize = (27 * s) + 'px'; c.querySelectorAll('.tag').forEach(x => x.style.fontSize = (23 * s) + 'px'); }
  });
  capfit();
  const stage = document.querySelector('.stage');
  if (stage) {          // 1장: 글 영역이 사진 액자와 겹치지 않도록 높이를 사진 위쪽까지로 제한
    main.style.height = (stage.getBoundingClientRect().top - main.getBoundingClientRect().top - 30) + 'px';
  }
  let zoom = 1;
  const over = () => inner.getBoundingClientRect().height > main.getBoundingClientRect().height + 1;
  while (over() && zoom > 0.7) { zoom -= 0.02; inner.style.zoom = zoom; }
  const fl = document.querySelector('.float'), cta = document.querySelector('.cta');
  if (fl && cta) {      // 4장: 글과 버튼 사이가 넉넉하면 그 자리에 현장 사진 액자를 놓음
    const last = inner.lastElementChild.getBoundingClientRect().bottom, top = cta.getBoundingClientRect().top, gap = top - last;
    const h = Math.min(gap - 152, 320);
    if (h >= 224) {       // 너무 작게 들어갈 자리면 넣지 않음
      const img = fl.querySelector('img'), ratio = parseFloat(fl.dataset.ratio || '1');
      const w = Math.round(h * ratio);
      img.style.height = h + 'px'; fl.style.width = (w + 28) + 'px'; fl.style.top = (last + (gap - h - 88) / 2 - 8) + 'px'; fl.style.display = 'block';
      capfit();
    }
  }
  return {overflow: over(), zoom: Math.round(zoom * 100) / 100};
};
"""


def _doc(body: str, style: dict) -> str:
    font = f"@font-face{{font-family:'Pretendard';src:url('{FONT.resolve().as_uri()}') format('woff2');font-weight:100 900;font-display:block}}" if FONT.exists() else ""
    root = (f":root{{--navy:{NAVY};--blue:{BLUE};--yellow:{YELLOW};--paper:{PAPER};--ink:{INK};"
            f"--accent:{style['accent']};--deep:{style['deep']}}}")
    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>{font}{root}{CSS}</style></head>"
            f"<body>{body}<script>{FIT_JS}</script></body></html>")


def _top(brand: str, style: dict, role: str, mark: str = "") -> str:
    chip = style["chip"] or f"{role}께"
    extra = f'<span class="mark">{_esc(mark)}</span>' if mark else ""
    return f'<div class="top"><div class="brand"><i></i>{_esc(brand)}</div><div class="chips">{extra}<span class="role">{_esc(chip)}</span></div></div>'


def _foot(idx: int, total: int, right: str) -> str:
    dots = "".join(f'<b class="{"on" if i == idx else ""}"></b>' for i in range(1, total + 1))
    return f'<div class="foot"><div class="dots">{dots}</div>{right}</div>'


def _shot(photo_uri: str, meta: dict | None, wide: bool, width: int) -> str:
    tag, who = _caption(meta)
    height = round(width * 0.66) if wide else width - 28
    cap = f'<span class="tag">{tag}</span>{_esc(who)}' if who else f'<span class="tag">{tag}</span>'
    return (f'<figure class="shot" style="width:{width}px"><img src="{photo_uri}" style="height:{height}px" alt="">'
            f'<figcaption>{cap}</figcaption></figure>')


def page_html(idx: int, total: int, card: dict, role: str, brand: str, photo_uri: str, photo_size: tuple[int, int],
              meta: dict | None, cards_by_id: dict | None, market_mark: str) -> str:
    style = ROLE_STYLE.get(role, DEFAULT_STYLE)
    lines = [str(x) for x in (card.get("본문") or []) if str(x).strip()][:3]
    wide = photo_size[0] / max(1, photo_size[1]) > 1.2
    pg = f'<span class="pgno">{idx:02d} / {total:02d}</span>'
    if idx == 1:        # 문제
        shot_w = 560 if wide and photo_size[0] >= 900 else 372
        body = (f'<div class="page p1"><div class="grid"></div><div class="ring"></div>{_top(brand, style, role, market_mark)}'
                f'<div class="main"><div class="inner"><h1 data-fit="{390 if len(lines) <= 2 else 262}" data-min="74">{_headline(card.get("제목"), True)}</h1>'
                f'<ul class="lines">{"".join(f"<li>{_rich(x)}</li>" for x in lines)}</ul></div></div>'
                f'<div class="stage">{_shot(photo_uri, meta, wide, shot_w)}'
                f'<div class="swipe"><span>{_svg("arrow", 58)}</span>넘겨 보기</div></div>{_foot(idx, total, pg)}</div>')
    elif idx == 2:      # 해결
        used_icons: set[str] = set()
        pts = "".join(f'<li><div class="ic">{_svg(_icon_for(x, used_icons), 66)}</div><div class="tx"><span>{i:02d}</span><p>{_rich(x)}</p></div></li>'
                      for i, x in enumerate(lines, 1))
        body = (f'<div class="page p2">{_top(brand, style, role, market_mark)}<div class="main"><div class="inner">'
                f'<h1 data-fit="216" data-min="62">{_headline(card.get("제목"), True)}</h1><div class="bar"></div>'
                f'<ol class="points">{pts}</ol></div></div>{_foot(idx, total, pg)}</div>')
    elif idx == 3:      # 근거
        stats = pick_stats(card, cards_by_id)
        used = {s["줄"] for s in stats if s["줄"] is not None}
        blocks = ""
        if stats:
            cells = ""
            for s in stats:
                pre, num, unit = _split_value(s["값"])
                desc = _rich(re.sub(r"\s*\[확인 필요[^\]]*\]", "", lines[s["줄"]])) if s["줄"] is not None else ""
                meta_row = "".join([f'<span class="qual">{_esc(s["한정어"])}</span>' if s["한정어"] else "",
                                    '<span class="need">확인 필요</span>' if s["확인필요"] else "",
                                    f'<span class="src">출처: {_esc(s["출처"])}</span>' if s["출처"] else ""])
                val = (f'<div class="val" data-fitw="{430 if len(stats) == 2 else 520}">{f"<span class=pre>{_esc(pre)}</span>" if pre else ""}'
                       f'<span class="num">{_esc(num)}</span><span class="unit">{_esc(unit)}</span></div>')
                over = f'<div class="over">{_esc(s["항목"])}</div>' if s["항목"] else ""
                if len(stats) == 1:
                    cells += (f'<div class="stat"><div class="left">{over}{val}</div><div class="right"><p class="desc">{desc}</p>'
                              f'<div class="meta">{meta_row}</div></div></div>')
                else:
                    cells += f'<div class="stat">{over}{val}<p class="desc">{desc}</p><div class="meta">{meta_row}</div></div>'
            blocks += f'<div class="stats n{len(stats)}">{cells}</div>'
        rest = [(i, x) for i, x in enumerate(lines) if i not in used]
        if rest:
            items = ""
            for _, x in rest:
                src = _source_for(x, card, cards_by_id)
                items += (f'<li><span class="ck">{CHECK_FILL.format(s=46)}</span><div><p>{_rich(x)}</p>'
                          + (f'<span class="src">출처: {_esc(src)}</span>' if src else "") + "</div></li>")
            blocks += f'<ul class="ev{"" if stats else " solo"}">{items}</ul>'
        tag, who = _caption(meta)
        case = (f'<div class="case{" wide" if wide else ""}"><div class="band"><img src="{photo_uri}" alt=""><div>'
                f'<span class="tag">{tag}</span>' + (f'<div class="who">{_esc(who)}</div>' if who else "") + "</div></div></div>")
        body = (f'<div class="page p3">{_top(brand, style, role, market_mark)}<div class="main"><div class="inner">'
                f'<h1 data-fit="200" data-min="58">{_headline(card.get("제목"), False)}</h1><div class="bar"></div>{blocks}{case}'
                f'</div></div>{_foot(idx, total, pg)}</div>')
    else:               # 제안
        keep = [x for x in lines if re.sub(r"1877-3836|상담|문의|맞춤|견적|전화|[\s:·,.\-]", "", x)]      # 전화번호만 적힌 줄은 아래 버튼과 겹치므로 뺌
        items = "".join(f'<li>{_svg("check", 44)}<span>{_rich(x)}</span></li>' for x in keep)
        tag, who = _caption(meta)
        ratio = 1.5 if wide else 1.0
        floating = (f'<figure class="shot float" data-ratio="{ratio}"><img src="{photo_uri}" alt=""><figcaption><span class="tag">{tag}</span>'
                    f'{_esc(who)}</figcaption></figure>')
        body = (f'<div class="page p4"><div class="ring"></div>{_top(brand, style, role, market_mark)}<div class="main"><div class="inner">'
                f'<h1 data-fit="{360 if len(keep) <= 2 else 240}" data-min="66">{_headline(card.get("제목"), True)}</h1><div class="bar"></div>'
                f'<ul class="lines">{items}</ul></div></div>{floating}'
                f'<div class="cta"><div class="btn">{_svg("phone", 58)}<span>상담 문의</span><b>1877-3836</b></div>'
                f'<div class="url">www.tlinkcrm.com</div></div>{_foot(idx, total, f"<span class=ad>광고</span>")}</div>')
    return _doc(body, style)


PAGE_COLORS = {1: (WHITE, "#1C3F9C"), 2: (NAVY, PAPER), 3: (NAVY, "#EEF3FF"), 4: (WHITE, "#2458F0")}   # (제목 글자색, 그 뒤의 가장 불리한 바탕색)


def _fallback(photo, cards, role, out_dir, why: str) -> list[dict]:
    """브라우저로 못 찍었을 때: 기존 합성(kit.content.render_cards)으로 대신 그립니다. 그것도 안 되면 빈 파일 경로로 사유만 돌려줍니다."""
    try:
        from . import content
        files = content.render_cards(photo, cards, role, out_dir)
        for f in files:
            f["방식"] = f"기본 합성 (브라우저 렌더 실패: {why[:80]})"
        return files
    except Exception as e:  # noqa: BLE001 — 어떤 경우에도 예외를 올리지 않음
        return [{"역할": role, "장": i, "제목": c.get("제목", ""), "파일": "", "대비": 0.0,
                 "방식": f"실패: {why[:60]} / 기본 합성도 실패: {str(e)[:60]}"} for i, c in enumerate(cards, 1)]


def _prepare(photo, cards: list[dict], role: str, out_dir: Path, meta, cards_by_id, market_mark: str, brand: str) -> tuple[list[dict], list[dict]]:
    """한 역할의 쪽별 HTML 을 쓰고 (찍을 목록, 결과 목록)을 돌려줍니다."""
    from PIL import Image
    with Image.open(photo) as im:
        size = im.size
    safe = re.sub(r"[^\w가-힣]+", "_", role)
    work = out_dir / "_html"
    work.mkdir(parents=True, exist_ok=True)
    uri = Path(photo).resolve().as_uri()
    pages, result = [], []
    for i, card in enumerate(cards, 1):
        page_no = min(i, 4) if len(cards) >= 4 or i < len(cards) else 4       # 마지막 장은 항상 제안 틀
        f = work / f"{safe}_{i}.html"
        f.write_text(page_html(page_no, len(cards), card, role, brand, uri, size, meta, cards_by_id, market_mark), encoding="utf-8")
        target = out_dir / f"{safe}_{i}.jpg"
        pages.append({"html": str(f), "out": str(target)})
        fg, bg = PAGE_COLORS[page_no]
        result.append({"역할": role, "장": i, "제목": card.get("제목", ""), "파일": str(target.resolve()), "대비": contrast(fg, bg)})
    return pages, result


def _shoot(pages: list[dict], result: list[dict], job: Path) -> None:
    """별도 프로세스에서 브라우저로 찍습니다. 실패하면 예외."""
    job.write_text(json.dumps({"width": SIZE[0], "height": SIZE[1], "scale": 2, "pages": pages}, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(WORKER), str(job)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=180, cwd=str(ROOT))
    last = (proc.stdout or "").strip().splitlines()[-1:] or ["{}"]
    info = json.loads(last[0])
    if not info.get("ok"):
        raise RuntimeError(info.get("error") or (proc.stderr or "")[-200:] or "작업자 응답 없음")
    for r, p in zip(result, info["pages"]):
        r["넘침"] = p.get("overflow", False)
        r["축소"] = p.get("zoom", 1)
    if not all(Path(r["파일"]).exists() for r in result):
        raise RuntimeError("이미지 파일이 만들어지지 않음")


def render_cards(photo, cards: list[dict], role: str, out_dir, meta: dict | None = None, cards_by_id: dict | None = None,
                 market_mark: str = "", brand: str = "티링크 비즈레코딩") -> list[dict]:
    """카드뉴스 이미지(1080×1350)를 만듭니다. 반환: [{"역할","장","제목","파일","대비"}]. 실패하면 기본 합성으로 대신 그립니다(예외 없음)."""
    out_dir = Path(out_dir)
    try:
        pages, result = _prepare(photo, cards, role, out_dir, meta, cards_by_id, market_mark, brand)
        _shoot(pages, result, out_dir / "_html" / (re.sub(r"[^\w가-힣]+", "_", role) + "_job.json"))
        return result
    except Exception as e:  # noqa: BLE001 — 브라우저가 없거나 실패해도 카드뉴스는 나와야 함
        return _fallback(photo, cards, role, out_dir, f"{type(e).__name__}: {e}")


def render_sets(photo, sets: dict[str, list[dict]], out_dir, meta: dict | None = None, cards_by_id: dict | None = None,
                market_mark: str = "", brand: str = "티링크 비즈레코딩") -> dict[str, list[dict]]:
    """여러 역할의 카드뉴스를 브라우저 한 번으로 찍습니다 (역할마다 render_cards 를 부르는 것보다 빠름). 반환: {역할: [...]}. 예외 없음."""
    out_dir = Path(out_dir)
    try:
        pages, results = [], {}
        for role, cards in sets.items():
            pg, res = _prepare(photo, cards, role, out_dir, meta, cards_by_id, market_mark, brand)
            pages += pg
            results[role] = res
        _shoot(pages, [r for res in results.values() for r in res], out_dir / "_html" / "_all_job.json")
        return results
    except Exception as e:  # noqa: BLE001
        return {role: _fallback(photo, cards, role, out_dir, f"{type(e).__name__}: {e}") for role, cards in sets.items()}


def pages_html(cards: list[dict], role: str, photo_url: str, photo_size: tuple[int, int] = (1200, 900), meta: dict | None = None,
               cards_by_id: dict | None = None, market_mark: str = "", brand: str = "티링크 비즈레코딩", font_url: str | None = None,
               **kwargs) -> list[str]:
    """브라우저가 직접 그릴 카드 HTML 을 쪽마다 돌려줍니다 (각각 완성된 1080×1350 문서).
    서버에 Chrome 이 없는 곳(Vercel 등)에서 화면이 iframe 으로 보여 주는 용도입니다. photo_url·font_url 은 웹 주소이고,
    문서가 열리면 글자 맞춤(__fit)을 스스로 실행합니다. 그 밖의 인자(**kwargs)는 page_html 로 그대로 넘깁니다."""
    total = len(cards)
    auto = ("<script>(document.fonts&&document.fonts.ready?document.fonts.ready:Promise.resolve())"
            ".then(function(){if(window.__fit)window.__fit();});</script></body>")
    out = []
    for i, card in enumerate(cards, 1):
        page_no = min(i, 4) if total >= 4 or i < total else 4       # 마지막 장은 항상 제안 틀
        doc = page_html(page_no, total, card, role, brand, photo_url, photo_size, meta, cards_by_id, market_mark, **kwargs)
        if font_url:
            if FONT.exists():
                doc = doc.replace(FONT.resolve().as_uri(), font_url)
            else:
                face = f"@font-face{{font-family:'Pretendard';src:url('{font_url}') format('woff2');font-weight:100 900;font-display:block}}"
                doc = doc.replace("<style>", "<style>" + face, 1)
        out.append(doc.replace("</body>", auto, 1))
    return out
