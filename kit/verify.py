"""사실 검증 — 원고를 코드가 검사합니다 (AI 를 쓰지 않으므로 같은 원고에는 항상 같은 결과).

    from kit import verify
    ledger = verify.build_ledger(cards, conflicts, photos)        # 써도 되는 숫자, 조건, 가린 고객명
    result = verify.check(title, body, ledger, rules)              # {"점수", "문제": [...], "미션": [...]}
    test = verify.injection_test(title, body, ledger, rules)       # 일부러 틀리게 고친 원고를 몇 개 잡는지

검사 항목: 본문의 숫자가 사실 카드에 있는지, 조건(한정어)을 함께 썼는지, 자료 간 충돌 항목에 [확인 필요]가 있는지,
가린 고객명만 썼는지, 개인 연락처·과장 표현이 없는지, 필수 키워드·미션 11개·하단 정보·광고 표기, 담당자가 금지한 표현.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .config import ROOT

RULES_FILE = ROOT / "data" / "rules.json"
REQUIRED = ["통화요약", "콜센터 프로그램", "업무자동화"]
TITLE_KEYS = ["티링크 비즈레코딩", "영업사원 통화관리", "휴대폰 통화녹음", "인터넷전화 자동녹취"]
IMAGE_SLOTS = ["휴대폰 통화 화면", "인터넷전화 녹취 목록", "AI 통화요약", "직원별 통계", "종합 리포트 화면"]
FOOTER_ITEMS = ["www.tlinkcrm.com", "blog.naver.com/mobilecrm", "1877-3836", "tlinkcrm.com/center.php"]
EXAGGERATION = re.compile(r"업계\s*(최초|유일|1위|최고)|국내\s*(최초|유일|1위)|세계\s*최초|완벽(한|하게)|100\s*%\s*(보장|정확)|무조건")
PERSONAL = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}|[\w.+-]+@(?!tlinkcrm\.com)[\w-]+\.[a-z]{2,}", re.I)
EXPERIENCE_FAKE = re.compile(r"(직접|실제로)\s*(써|사용해|녹음해|통화해)\s*(보니|봤더니|보았더니|본 결과)|제가\s*(써|사용해)\s*본")
QUAL_WORDS = {"녹취 성공률": ["인터넷 전화", "인터넷전화"], "통역 지원 언어 수": ["부가서비스", "신청", "설정에 따라"]}
KEY_CONTEXT = {"학교 도입 수": ["학교", "초·중·고", "초.중.고", "초중고"], "특허 수": ["특허"], "도입 기업 수": ["기업", "곳"]}
STRIP = re.compile(r"https?://\S+|www\.\S+|1877-3836|AES\s?256|SHA\s?256|\b070\b|\[이미지:[^\]]*\]|\[직접 사용 후 작성[^\]]*\]|#\S+")
NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(%|퍼센트|석|개국|개사|개|곳|건|명|만\s?원|억\s?원|만|억|원|배|시간|분|초|USER|유저)?")
MONEY_UNITS = ("%", "퍼센트", "배", "만원", "억원", "만", "억", "원")
NAME_SUFFIX = re.compile(r"[가-힣A-Za-z]{2,10}(병원|의원|은행|학원|복지관|요양원|클럽|저축은행|캐피탈|센터)")
NAME_SLOT = re.compile(r"([가-힣A-Za-z0-9*]{2,16})\s(?:설치|도입|구축)\s?(?:사례|현장)")
NAME_CONTEXT = re.compile(r"설치|도입|구축|사례|고객")
COMMON_WORDS = "이번 실제 현장 고객 고객사 대표 주요 다양한 해당 최근 기존 우리 자사 업종별 벽걸이 스탠드형 렉거치형 허브 장비 서버 녹취 제품 시스템 솔루션 티링크 비즈레코딩 콜센터 고객센터 상담센터"


def _n(s) -> str:
    return re.sub(r"\s+", "", s or "")


# ───────────────────────── 기준 만들기 ─────────────────────────
def build_ledger(cards: list[dict], conflicts: list[dict], photos: list[dict]) -> dict:
    allowed, examples, quals = {}, {}, {}
    for c in cards:
        if not c.get("원문확인"):
            continue
        for v in c.get("수치") or []:
            if v.get("숫자") is None:
                continue
            num = round(float(v["숫자"]), 2)
            (examples if c.get("유형") == "화면 예시 값" else allowed).setdefault(num, []).append(c["id"])
    for x in conflicts:
        if x["종류"] == "조건이 한쪽에만 있음":
            nums = [round(float(v["숫자"]), 2) for cid in x["카드"] for c in cards if c["id"] == cid
                    for v in (c.get("수치") or []) if v.get("항목") == x["항목"] and v.get("숫자") is not None]
            words = QUAL_WORDS.get(x["항목"]) or [x.get("필수한정어", "")]
            for n in set(nums):
                quals[n] = {"항목": x["항목"], "단어": words}
    confirm = []      # 자료마다 값이 달라서 [확인 필요] 없이 쓰면 안 되는 것
    for x in conflicts:
        if not x["종류"].startswith("값이 다름"):
            continue
        entries = [(round(float(v["숫자"]), 2), bool(_n(v.get("한정어")) and not re.search(r"없음|확인필요", _n(v.get("한정어")))))
                   for cid in x["카드"] for c in cards if c["id"] == cid
                   for v in (c.get("수치") or []) if v.get("항목") == x["항목"] and v.get("숫자") is not None]
        if not entries:
            continue
        top = max(n for n, _ in entries)
        total_vs_subset = any(n == top and not q for n, q in entries) and all(q for n, q in entries if n != top)
        if x["종류"] == "값이 다름" or not total_vs_subset:     # '전체 수치 대 일부 범위 수치'는 충돌로 보지 않음
            confirm.append({"항목": x["항목"], "숫자": sorted({n for n, _ in entries}), "문맥": KEY_CONTEXT.get(x["항목"], [])})
    masked = sorted({p["가린고객명"] for p in photos if p.get("가린고객명")})
    # 자료에 실제로 나오는 말 (자료에 공개된 구축 사례 이름은 써도 되고, 자료에 없는 이름은 고객명 후보로 봄)
    corpus = _n(" ".join(f"{c.get('내용', '')} {c.get('원문', '')}" for c in cards if c.get("원문확인"))
                + " ".join(f"{p.get('업종', '')} {p.get('홈페이지설명', '')}" for p in photos) + COMMON_WORDS)
    return {"허용숫자": allowed, "예시숫자": examples, "조건": quals, "확인필요": confirm, "가린고객명": masked, "자료어휘": corpus}


def load_rules() -> list[dict]:
    return json.loads(RULES_FILE.read_text(encoding="utf-8")) if RULES_FILE.exists() else []


def add_rule(banned: str, replace: str = "", reason: str = "") -> list[dict]:
    """담당자가 고친 표현을 규칙으로 저장 → 다음 생성의 지시문과 검수에 모두 적용됩니다."""
    rules = [r for r in load_rules() if r["금지"] != banned]
    rules.append({"금지": banned.strip(), "대체": replace.strip(), "사유": reason.strip(), "추가일": date.today().isoformat()})
    RULES_FILE.parent.mkdir(exist_ok=True)
    RULES_FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8")
    return rules


# ───────────────────────── 미션 11개 (가이드라인 원문을 규칙으로 옮김) ─────────────────────────
def _has(text: str, *groups) -> bool:
    """groups 의 각 묶음에서 하나 이상이 들어 있어야 통과."""
    t = _n(text)
    return all(any(_n(w) in t for w in (g if isinstance(g, (list, tuple)) else [g])) for g in groups)


def missions(title: str, body: str) -> list[dict]:
    paras = [p for p in re.split(r"\n\s*■", body) if p.strip()]
    first = title + " " + (paras[0] if paras else body[:400])
    last = paras[-1] if paras else body
    slots = [body.find(f"[이미지: {s}") for s in IMAGE_SLOTS]
    rows = [
        (1, "제목과 첫 문단에 핵심 키워드 4개", all(_has(first, k) for k in TITLE_KEYS)),
        (2, "휴대폰·인터넷전화·PC폰 동시 녹음, KT·SK·LG 모두 사용", _has(body, "휴대폰", "인터넷전화", ["PC폰", "PC 폰"], "KT", "SK", "LG")),
        (3, "STT 문자변환, AI 통화요약, 키워드, 후속 조치 자동 기록", _has(body, "STT", ["통화요약", "AI 요약", "요약"], "키워드", ["후속 조치", "후속조치"])),
        (4, "영업사원별 통화량, 평균 통화시간, 미결 상담, 후속 연락", _has(body, "통화량", ["평균 통화시간", "평균통화시간"], "미결", ["후속 연락", "후속연락"])),
        (5, "CRM 연결, 담당자가 바뀌어도 이전 이력 확인", _has(body, "CRM", "담당자", "이력")),
        (6, "종합 리포트와 경영 대시보드에서 한눈에 (이탈 위험 포함)", _has(body, ["종합 리포트", "종합리포트"], ["경영 대시보드", "경영대시보드"], "이탈")),
        (7, "보고서 작성 시간 절감, 데이터 기반 코칭과 성과관리", _has(body, ["일일 보고서", "보고서"], "코칭", ["성과관리", "성과 관리"])),
        (8, "사용 후기는 지어내지 않고 직접 작성할 자리로 남김", "[직접 사용 후 작성" in body and not EXPERIENCE_FAKE.search(body)),
        (9, "화면 이미지 5종을 순서대로 소개", all(s >= 0 for s in slots) and slots == sorted(slots)),
        (10, "결론에서 '기업용 영업관리 솔루션'임을 강조", _has(last, ["영업관리 솔루션", "영업 관리 솔루션"])),
        (11, "AES256·SHA256 암호화와 사용자별 접근권한 소개", _has(body, "AES256", "SHA256", ["접근권한", "접근 권한", "권한"])),
    ]
    return [{"미션": i, "내용": name, "결과": "통과" if ok else "미달"} for i, name, ok in rows]


# ───────────────────────── 검사 ─────────────────────────
def _sentences(body: str) -> list[str]:
    out = []
    for line in body.splitlines():
        out += [s.strip() for s in re.split(r"(?<=[.!?다요])\s+(?=[가-힣A-Z\[\"'])", line) if s.strip()]
    return out


def check(title: str, body: str, ledger: dict, rules: list[dict] | None = None) -> dict:
    issues = []

    def add(kind, text, detail, weight):
        issues.append({"종류": kind, "문장": text[:90], "설명": detail, "감점": weight})

    full = title + "\n" + body
    for kw in REQUIRED:
        if _n(kw) not in _n(title):
            add("필수 키워드", title, f"제목에 '{kw}' 없음", 4)
        if _n(kw) not in _n(body):
            add("필수 키워드", "(본문)", f"본문에 '{kw}' 없음", 4)
    ms = missions(title, body)
    for m in ms:
        if m["결과"] != "통과":
            add("미션", f"미션 {m['미션']}", m["내용"], 4)
    for item in FOOTER_ITEMS:
        if item not in body:
            add("하단 정보", "(하단)", f"'{item}' 없음", 3)
    if not re.search(r"광고|경제적\s*이해관계|제공받아", body):
        add("광고 표기", "(하단)", "광고임을 밝히는 문구가 없음", 10)
    for s in _sentences(full):
        plain = STRIP.sub(" ", s)
        for m in NUMBER.finditer(plain):
            raw, unit = m.group(1), (m.group(2) or "").replace(" ", "")
            try:
                num = round(float(raw.replace(",", "")), 2)
            except ValueError:
                continue
            if num < 13 and unit not in MONEY_UNITS:
                continue                                   # '3가지', '5단계' 같은 순서·개수는 검사하지 않음
            scaled = round(num * 1e4, 2) if unit.startswith("만") else round(num * 1e8, 2) if unit.startswith("억") else num
            if scaled in ledger["허용숫자"]:                 # '30만원'은 사실 카드의 300,000 과 같은 값
                num = scaled
            if num in ledger["허용숫자"]:
                q = ledger["조건"].get(num)
                if q and unit in ("%", "퍼센트", "개", "개국") and not any(_n(w) in _n(s) for w in q["단어"]):
                    add("조건 누락", s, f"{raw}{unit}에는 '{q['단어'][0]}' 조건을 함께 써야 함 ({q['항목']})", 8)
                for c in ledger["확인필요"]:
                    if num in c["숫자"] and any(w in s for w in c["문맥"]) and "[확인 필요" not in s:
                        add("충돌 수치", s, f"{c['항목']}은 자료마다 값이 다름 ({', '.join(f'{x:g}' for x in c['숫자'])}) → [확인 필요] 표시 필요", 8)
            elif num in ledger["예시숫자"]:
                add("예시 값 사용", s, f"{raw}{unit}는 리포트 화면 예시에 나온 값이라 성능처럼 쓸 수 없음", 8)
            else:
                add("근거 없는 수치", s, f"{raw}{unit}는 사실 카드에 없는 숫자", 8)
        if EXAGGERATION.search(s):
            add("과장 표현", s, f"'{EXAGGERATION.search(s).group()}'", 6)
        if PERSONAL.search(s):
            add("개인 연락처", s, "대표번호·공식 메일이 아닌 연락처", 10)
        for r in rules or []:
            if r["금지"] and r["금지"] in s:
                add("금지 표현", s, f"담당자가 금지한 '{r['금지']}'" + (f" → '{r['대체']}'" if r.get("대체") else ""), 5)
    for name, ctx in _unmasked_names(full, ledger):
        add("고객명", ctx, f"'{name}'은 가린 이름이 아님 (설치 사례 고객명은 가린 이름만 사용)", 10)
    score = max(0, 100 - sum(i["감점"] for i in issues))
    blocks = sum(1 for i in issues if i["감점"] >= BLOCK_AT)
    state = "차단" if blocks else "검토 필요" if issues else "통과"
    return {"점수": score, "상태": state, "차단": blocks, "검토": len(issues) - blocks,
            "통과": score >= 90 and not blocks, "문제": issues, "미션": ms}


BLOCK_AT = 8      # 감점 8 이상(수치·조건·고객명·개인 연락처·광고 표기)은 고치기 전에는 승인할 수 없음


def _unmasked_names(full: str, ledger: dict) -> list[tuple[str, str]]:
    """가리지 않은 설치 사례 고객명 찾기. 자료에 공개된 이름(자료어휘)은 제외합니다.
    ① 업종 말(병원·은행·센터…)로 끝나는 이름  ② 가린 이름의 별표 자리를 채운 이름  ③ '○○ 설치 사례' 자리에 온 낯선 이름"""
    corpus = ledger.get("자료어휘", "")
    found: dict[str, str] = {}

    def consider(name: str, start: int, end: int, need_context: bool = True):
        ctx = full[max(0, start - 12): end + 10].replace("\n", " ")
        if "*" in name or name in found or (corpus and _n(name) in corpus):
            return
        if need_context and not NAME_CONTEXT.search(ctx):
            return
        found[name] = ctx

    for m in NAME_SUFFIX.finditer(full):
        consider(m.group(), m.start(), m.end())
    for g in ledger["가린고객명"]:
        parts = re.split(r"\*+", g)
        pre, suf = parts[0], parts[-1] if len(parts) > 1 else ""
        if len(pre) + len(suf) >= 2:
            for m in re.finditer(re.escape(pre) + r"[가-힣A-Za-z0-9]{1,12}" + re.escape(suf), full):
                consider(m.group(), m.start(), m.end())
    for m in NAME_SLOT.finditer(full):
        consider(m.group(1), m.start(1), m.end(), need_context=False)
    return list(found.items())


def label_sentences(sentences: list[dict], result: dict, valid_cards: set[str]) -> list[dict]:
    """블로그 문장마다 [확인된 사실] / [AI 추론] / [확인 필요]. 표시는 코드가 정합니다."""
    flagged = [i["문장"] for i in result["문제"] if i["감점"] >= 5]
    out = []
    for s in sentences:
        cited = [c for c in s.get("근거카드", []) if c in valid_cards]
        if any(f and (f in s["글"] or s["글"][:60] in f) for f in flagged) or "[확인 필요" in s["글"]:
            lab = "확인 필요"
        elif cited:
            lab = "확인된 사실"
        else:
            lab = "AI 추론"
        out.append({**s, "근거카드": cited, "표시": lab})
    return out


# ───────────────────────── 주입 시험 ─────────────────────────
def injection_test(title: str, body: str, ledger: dict, rules: list[dict] | None = None) -> dict:
    """정상 원고를 일부러 틀리게 고친 뒤, 검수가 그 변경을 잡아내는지 셉니다."""
    base = check(title, body, ledger, rules)
    base_keys = {(i["종류"], i["설명"]) for i in base["문제"]}
    masked = ledger["가린고객명"][0] if ledger["가린고객명"] else ""
    muts = [
        ("없는 수치 추가", "근거 없는 수치", title, body + "\n도입 기업의 통화 누락률이 87% 줄었습니다."),
        ("없는 수치로 바꿈 (3,000석 → 5,000석)", "근거 없는 수치", title, body.replace("3,000석", "5,000석") if "3,000석" in body else body + "\n최대 5,000석 규모까지 구축했습니다."),
        ("조건 없는 99%", "조건 누락", title, body + "\n녹취 성공률은 99%입니다."),
        ("충돌 수치를 확인 표시 없이 사용", "충돌 수치", title, body + "\n전국 200여 개 학교가 도입했습니다."),
        ("리포트 예시 값을 성능처럼 사용", "예시 값 사용", title, body + "\n도입 후 영업기회를 115건 찾아냈습니다."),
        ("과장 표현 추가", "과장 표현", title, body + "\n업계 1위 솔루션입니다."),
        ("개인 휴대폰 번호 추가", "개인 연락처", title, body + "\n문의는 010-1234-5678로 주세요."),
        ("가린 고객명의 별표를 채움", "고객명", title, body + f"\n{re.sub(r'[*]+', '행복', masked) if masked else '행복복지관'} 설치 사례입니다."),
        ("자료에 없는 고객명 추가", "고객명", title, body + "\n새봄물산 도입 사례도 있습니다."),
        ("광고 표기 삭제", "광고 표기", title, re.sub(r"※[^\n]*광고[^\n]*", "", body).replace("제공받아", "")),
        ("필수 키워드 삭제 (제목)", "필수 키워드", title.replace("업무자동화", "").replace("통화요약", ""), body),
        ("지어낸 사용 후기", "미션", title, body.replace("[직접 사용 후 작성", "직접 써 보니 정말 편했습니다. [삭제됨") if "[직접 사용 후 작성" in body else body + "\n직접 써 보니 정말 편했습니다."),
        ("하단 상담 번호 삭제", "하단 정보", title, body.replace("1877-3836", "")),
    ]
    rows = []
    for name, expect, t, b in muts:
        r = check(t, b, ledger, rules)
        new = [i for i in r["문제"] if (i["종류"], i["설명"]) not in base_keys]
        hit = any(i["종류"] == expect for i in new)
        rows.append({"일부러 넣은 오류": name, "기대한 검출": expect, "결과": "검출" if hit else "놓침",
                     "검출 내용": next((i["설명"] for i in new if i["종류"] == expect), ""), "점수": r["점수"]})
    return {"원고 점수": base["점수"], "주입": len(rows), "검출": sum(r["결과"] == "검출" for r in rows), "표": rows}
