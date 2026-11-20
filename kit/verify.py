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
from pathlib import Path

from .config import ROOT

RULES_FILE = ROOT / "data" / "rules.json"
REQUIRED = ["통화요약", "콜센터 프로그램", "업무자동화"]
TITLE_KEYS = ["티링크 비즈레코딩", "영업사원 통화관리", "휴대폰 통화녹음", "인터넷전화 자동녹취"]
IMAGE_SLOTS = ["휴대폰 통화 화면", "인터넷전화 녹취 목록", "AI 통화요약", "직원별 통계", "종합 리포트 화면"]
FOOTER_ITEMS = ["www.tlinkcrm.com", "blog.naver.com/mobilecrm", "1877-3836", "tlinkcrm.com/center.php"]
EXAGGERATION = re.compile(r"업계\s*(최초|유일|1위|최고|선두)|국내\s*(최초|유일|1위|최고)|세계\s*최초|완벽(한|하게)|100\s*%\s*(보장|정확|녹취|녹음)|무조건|"
                          r"최고의|가장\s*뛰어난|1\s*위|1\s*등|유일(한|의|하게|무이)|독보적|압도적|No\.?\s*1|넘버\s*원|평생\s*무료", re.I)
IF_CLAUSE = re.compile(r"다면|라면|더라도|(줄었|늘었|늘어났|줄어들었|높아졌|빨라졌)(으면|는지|거나|을\s*때|던)")       # '늘었다면'은 독자의 상황을 가정한 말
REG_CLAIM = re.compile(r"의료법|개인정보\s*보호법|법규|법령|법적\s*(요건|기준)|컴플라이언스|HIPAA|ISMS|ISO\s?\d{4,5}|규정(을|를)?\s*(모두\s*)?(준수|충족|만족)", re.I)   # 어느 시장에서도 자료에 없는 주장
COUNT_ITEMS = {"학교 도입 수", "특허 수", "통역 지원 언어 수"}      # 항목이 없는 숫자에 대해서도 '다른 항목' 판정을 하는 항목 (개수를 세는 항목)
MAGNITUDE = re.compile(r"(절반|두\s*배|세\s*배|몇\s*배|수\s*배|눈에\s*띄게|획기적으로|대폭|크게)[^.\n]{0,14}(줄|빨라|늘|높아|절감|단축|향상|개선)")   # 크기를 말하는 효과 주장
VAGUE_COUNT = re.compile(r"수\s?(십|백|천|만)\s*(여\s*)?(개|곳|건|명|석)")                                                         # '수백 곳' 같은 어림수
ALIASES = {"아이폰": ["아이폰", "iPhone", "아이 폰", "iOS"]}                                                                       # 같은 대상을 가리키는 다른 표기
PERSONAL = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}|[\w.+-]+@(?!tlinkcrm\.com)[\w-]+\.[a-z]{2,}", re.I)
EXPERIENCE_FAKE = re.compile(r"(직접|실제로)\s*(써|사용해|녹음해|통화해)\s*(보니|봤더니|보았더니|본 결과)|제가\s*(써|사용해)\s*본")
QUAL_WORDS = {"녹취 성공률": ["인터넷 전화", "인터넷전화"], "통역 지원 언어 수": ["부가서비스", "신청", "설정에 따라"]}
KEY_CONTEXT = {"학교 도입 수": ["학교", "초·중·고", "초.중.고", "초중고", "교육"], "특허 수": ["특허"], "도입 기업 수": ["기업", "곳"],
               "최대 구축 규모": ["석", "규모", "구축"], "월 이용료": ["월", "이용료", "요금"], "설정비": ["설정비", "구축 비용", "구축비"],
               "녹취 성공률": ["성공률", "녹취"], "통역 지원 언어 수": ["언어", "통역", "번역"]}
STRICT_UNITS = {"%", "원", "곳", "석", "건", "명", "배", "개국", "USER"}
STRONG_ITEMS = {"학교 도입 수", "특허 수", "설정비", "녹취 성공률", "통역 지원 언어 수"}   # 문맥 말이 분명해서 '다른 항목의 수치' 판정에 쓰는 항목      # 이 단위가 붙은 숫자는 자료에 같은 단위로 있어야 함


def _uclass(unit: str) -> str:
    """단위를 같은 뜻끼리 묶습니다 (만원·억원 → 원, 개·곳 → 곳, 퍼센트 → %)."""
    u = (unit or "").replace(" ", "")
    if u in ("%", "퍼센트"):
        return "%"
    if u in ("원", "만원", "억원", "만", "억"):
        return "원"
    if u in ("개", "곳", "개사"):
        return "곳"
    if u in ("USER", "유저"):
        return "USER"
    if u in ("시간", "분", "초"):
        return "시간"
    return u


def _scaled(num: float, unit: str) -> float:
    return round(num * 1e4, 2) if unit.startswith("만") else round(num * 1e8, 2) if unit.startswith("억") else num
STRIP = re.compile(r"https?://\S+|www\.\S+|1877-3836|AES\s?256|SHA\s?256|\b070\b|\[이미지:[^\]]*\]|\[직접 사용 후 작성[^\]]*\]|#\S+")
NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(%|퍼센트|석|개국|개사|개|곳|건|명|만\s?원|억\s?원|만|억|원|배|시간|분|초|USER|유저)?")
MONEY_UNITS = ("%", "퍼센트", "배", "만원", "억원", "만", "억", "원")
NAME_SUFFIX = re.compile(r"[가-힣A-Za-z]{2,10}(병원|의원|은행|학원|복지관|요양원|클럽|저축은행|캐피탈|센터)")
NAME_SLOT = re.compile(r"([가-힣A-Za-z0-9*]{2,16})\s(?:설치|도입|구축)\s?(?:사례|현장)")
NAME_CONTEXT = re.compile(r"설치|도입|구축|사례|고객")
COMMON_WORDS = ("이번 실제 현장 고객 고객사 대표 주요 다양한 해당 최근 기존 우리 자사 업종별 벽걸이 스탠드형 렉거치형 허브 장비 서버 녹취 제품 시스템 솔루션 티링크 비즈레코딩 콜센터 고객센터 상담센터 "
                "교육기관 의료기관 무역 물류 학교 학원 병원 의원 기업 기관 공공기관 금융권 업종 산업 시장 동종 유사 비슷한 다른 "
                "분야 업계 부문 영역 방식 형태 유형 종류 관련 일반 여러 타사 같은 규모 지역 사무실 매장 지점 본사 센터")   # 시장·업종을 가리키는 말은 고객명이 아님


KINDS = ("블로그", "도입 사례", "영업 이메일", "카드뉴스")
NEW_MARKET_TAG = "[신규 시장 제안]"
NEW_MARKET_LINE = NEW_MARKET_TAG + " 이 시장은 아직 도입 사례 자료가 없어 제품 기능을 근거로 작성했습니다."
UNSUBSCRIBE_LINE = "※ 수신을 원하지 않으시면 #{수신거부링크} 를 눌러 주세요."
RECIPIENT = "#{수신자}"
# 도입 사례: 도입 효과 자료가 없으므로 '이미 얻은 성과'를 말하는 문장은 차단 ('줄일 수 있습니다' 같은 기능 설명은 해당 없음)
OUTCOME = re.compile(r"줄었|줄어들었|늘었|늘어났|절감(했|됐|되었)|개선(됐|되었|했)|향상(됐|되었|했)|단축(됐|되었|했)|감소했|증가했|높아졌|빨라졌|"
                     r"효과를\s*(봤|보았|보고|거뒀|거두었|거두고|체감)|성과를\s*(냈|내고|거뒀|거두었|거두고|올렸)|만족(했|하고\s*있|하며|스러워|도가\s*(높|올))|"
                     r"(도입|설치|구축|적용)\s*(후|이후|한\s*뒤|하고\s*나서)[^.\n]{0,40}(해결(됐|되었|했)|사라졌|없어졌|편해졌|수월해졌)")
# 의료기관: 의료법·환자정보 보호·규정 준수·인증 관련 주장은 자료에 없음
MEDICAL_CLAIM = re.compile(r"의료법|환자\s*(개인)?\s*정보[^.\n]{0,14}(보호|안전|보안|지킵|지켜|유출|암호화)|개인정보\s*보호법|"
                           r"개인정보[^.\n]{0,10}(규정|요건|의무|법)[^.\n]{0,10}(준수|충족|만족|대응)|규정(을|를)?\s*(준수|충족)|법규|"
                           r"법적\s*(요건|기준)|컴플라이언스|인증(을|를)?\s*(받|획득|취득|보유)|HIPAA|ISMS", re.I)
NOT_A_CLAIM = re.compile(r"확인\s*(이|이\s)?\s*필요|확인해야|확인하(세요|시기|셔야)|검토(가)?\s*필요|자료(가|는)?\s*없|자료에\s*없|별도\s*확인")
# 무역·물류: 도입 사례가 없으므로 '무역·물류 회사가 쓰고 있다', 사례·후기 문장은 차단
TRADE_WORD = r"(무역|물류|수출입|수출|운송|포워딩|해운|통관)"
TRADE_CLAIM = re.compile(TRADE_WORD + r"[^.\n]{0,30}(회사|기업|업체|고객|고객사|현장|업계)[^.\n]{0,30}"
                         r"(사용하고|사용했|사용한|사용\s*중|쓰고\s*있|도입했|도입한|도입하고|도입\s*중|이용하고|이용\s*중|이용한|선택했|선택한|운영\s*중|운영하고)|"
                         + TRADE_WORD + r"[^.\n]{0,24}(도입\s*사례|구축\s*사례|설치\s*사례|고객\s*후기|이용\s*후기|후기|사례가|사례를|사례도|사례입니다)")
TRADE_NOT = "없|않|아닙|아니|아닌|다른 ?(업종|산업|분야|시장)|[와과]는 ?다른"      # 사례가 없다, 다른 업종의 사례다 → 주장이 아님
INTERPRET = re.compile(r"통역|통화\s*번역|통화번역|실시간\s*번역")
INTERPRET_QUAL = re.compile(r"별도|신청|부가\s*서비스|설정에\s*따라|제한")
INDUSTRY_FILE = ROOT / "data" / "industry.json"


def new_markets() -> set[str]:
    """도입 실적 카드가 없어 '신규 시장 제안' 표시가 붙는 시장 (data/industry.json 의 시장표시)."""
    try:
        data = json.loads(INDUSTRY_FILE.read_text(encoding="utf-8"))
        return {i["산업"] for i in data.get("산업", []) if i.get("시장표시")}
    except (OSError, ValueError, KeyError):
        return set()


def _n(s) -> str:
    return re.sub(r"\s+", "", s or "")


THOUSAND = re.compile(r"(\d+)\s*천\s*(여\s*)?(?=석|개|곳|명|원|건)")


KOR_DIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
KOR_UNIT = {"십": 10, "백": 100, "천": 1000}
KOR_NUM = re.compile(r"(?<![가-힣\d])(?<!\d\s)([일이삼사오육칠팔구십백천만]*[십백천만][일이삼사오육칠팔구십백천만]*)\s*(여\s*)?(?=\s*(석|개|곳|건|명|퍼센트|%|원))")


def _kor_value(word: str) -> int | None:
    total = section = 0
    digit = 0
    for ch in word:
        if ch in KOR_DIGIT:
            digit = KOR_DIGIT[ch]
        elif ch in KOR_UNIT:
            section += (digit or 1) * KOR_UNIT[ch]
            digit = 0
        elif ch == "만":
            total += (section + digit or 1) * 10000
            section = digit = 0
        else:
            return None
    return total + section + digit


def _thousand(text: str) -> str:
    """'3천 석', '1천여 곳', '오천 석', '이백여 개'를 숫자 표기로 바꿔 같은 값으로 비교합니다."""
    text = THOUSAND.sub(lambda m: str(int(m.group(1)) * 1000) + (m.group(2) or ""), text)

    def kor(m):
        v = _kor_value(m.group(1))
        return m.group(0) if not v else str(v) + (m.group(2) or "")
    return KOR_NUM.sub(kor, text)


# ───────────────────────── 기준 만들기 ─────────────────────────
CONFIRMED_FILE = ROOT / "data" / "confirmed.json"


def load_confirmed() -> dict:
    """담당자가 확정한 값 {충돌 항목: 채택 숫자}. 파일이 없으면 빈 dict."""
    try:
        raw = json.loads(CONFIRMED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (raw or {}).items():
        val = v.get("값") if isinstance(v, dict) else v
        try:
            out[k] = round(float(val), 2)
        except (TypeError, ValueError):
            continue
    return out


def apply_confirmed(conflicts: list[dict], confirmed: dict | None) -> list[dict]:
    """확정한 값이 있는 충돌 항목에 '채택'을 붙이고, 처리 방법을 '확정한 값만 쓰고 [확인 필요]를 붙이지 않음'으로 바꿉니다."""
    if not confirmed:
        return conflicts
    out = []
    for x in conflicts:
        if x.get("항목") in confirmed and x["종류"].startswith("값이 다름"):
            v = confirmed[x["항목"]]
            x = {**x, "채택": v, "처리": f"담당자가 확정한 값({v:g})만 쓰고 [확인 필요]를 붙이지 않음. 다른 값은 쓰지 않음"}
        out.append(x)
    return out


def build_ledger(cards: list[dict], conflicts: list[dict], photos: list[dict], confirmed: dict | None = None) -> dict:
    conflicts = apply_confirmed(conflicts, confirmed)
    allowed, examples, quals, quoted = {}, {}, {}, {}
    classes: dict[float, set] = {}       # 숫자 → 자료에서 함께 쓰인 단위 묶음
    items: dict[float, set] = {}         # 숫자 → 그 숫자가 속한 항목 (기타 제외)
    item_classes: dict[str, set] = {}    # 항목 → 그 항목의 값에 쓰인 단위 묶음
    for c in cards:
        if not c.get("원문확인"):
            continue
        for v in c.get("수치") or []:
            if v.get("숫자") is None:
                continue
            num = round(float(v["숫자"]), 2)
            (examples if c.get("유형") == "화면 예시 값" else allowed).setdefault(num, []).append(c["id"])
            if c.get("유형") == "화면 예시 값":
                continue
            found = set()
            for src in (str(v.get("값") or ""), c.get("내용") or "", c.get("원문") or ""):
                for m in NUMBER.finditer(_thousand(src)):
                    try:
                        raw = round(float(m.group(1).replace(",", "")), 2)
                    except ValueError:
                        continue
                    unit = (m.group(2) or "").replace(" ", "")
                    if raw == num or _scaled(raw, unit) == num:
                        found.add(_uclass(unit))
            classes.setdefault(num, set()).update((found - {""}) or {""})
            if v.get("항목") and v["항목"] != "기타":
                items.setdefault(num, set()).add(v["항목"])
                item_classes.setdefault(v["항목"], set()).update((found - {""}) or {""})
        # 원문 구절(코드가 원문과 대조해 확인한 글자)에 적힌 숫자도 자료에 있는 숫자로 인정
        if c.get("유형") == "화면 예시 값":
            continue
        for m in NUMBER.finditer(c.get("원문") or ""):
            try:
                num = round(float(m.group(1).replace(",", "")), 2)
            except ValueError:
                continue
            quoted.setdefault(num, set()).add((m.group(2) or "").replace(" ", ""))   # 숫자 → 원문에서 함께 쓰인 단위
    for x in conflicts:
        if x["종류"] == "조건이 한쪽에만 있음":
            nums = [round(float(v["숫자"]), 2) for cid in x["카드"] for c in cards if c["id"] == cid
                    for v in (c.get("수치") or []) if v.get("항목") == x["항목"] and v.get("숫자") is not None]
            words = QUAL_WORDS.get(x["항목"]) or [x.get("필수한정어", "")]
            for n in set(nums):
                quals[n] = {"항목": x["항목"], "단어": words}
    confirm = []      # 자료마다 값이 달라서 [확인 필요] 없이 쓰면 안 되는 것
    adopted = []      # 담당자가 값을 확정한 항목 → 그 값만 쓰고, 버린 값은 차단
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
        if x.get("채택") is not None:
            keep = round(float(x["채택"]), 2)
            adopted.append({"항목": x["항목"], "값": keep, "버림": sorted({n for n, _ in entries} - {keep}), "문맥": KEY_CONTEXT.get(x["항목"], [])})
        elif x["종류"] == "값이 다름" or not total_vs_subset:     # '전체 수치 대 일부 범위 수치'는 충돌로 보지 않음
            confirm.append({"항목": x["항목"], "숫자": sorted({n for n, _ in entries}), "문맥": KEY_CONTEXT.get(x["항목"], [])})
    masked = sorted({p["가린고객명"] for p in photos if p.get("가린고객명")})
    limits = []       # 자료에 '○○은 사용할 수 없다'고 적힌 대상 → 되는 것처럼 쓰면 차단
    for c in cards:
        m = LIMIT.search(c.get("내용", "")) if c.get("원문확인") else None
        if m:
            limits.append({"대상": m.group(1), "카드": c["id"], "출처": c["출처"]})
    # 자료에 실제로 나오는 말 (자료에 공개된 구축 사례 이름은 써도 되고, 자료에 없는 이름은 고객명 후보로 봄)
    corpus = _n(" ".join(f"{c.get('내용', '')} {c.get('원문', '')}" for c in cards if c.get("원문확인"))
                + " ".join(f"{p.get('업종', '')} {p.get('홈페이지설명', '')}" for p in photos) + COMMON_WORDS)
    return {"허용숫자": allowed, "예시숫자": examples, "조건": quals, "확인필요": confirm, "가린고객명": masked, "자료어휘": corpus, "원문숫자": quoted, "제약": limits, "채택": adopted,
            "단위": classes, "항목": items, "항목단위": item_classes}


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
    body = re.sub(r"^\s*\[신규 시장 제안\][^\n]*\n+", "", body)      # 코드가 붙인 표시 줄은 본문 첫 문단이 아님
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
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[가-힣A-Za-z0-9\[\"'(])", line) if s.strip()]
    return out


def check(title: str, body: str, ledger: dict, rules: list[dict] | None = None, doc_level: bool = True,
          kind: str = "블로그", market: str | None = None) -> dict:
    """doc_level=False 이면 문장 단위 검사(숫자·조건·충돌·과장·연락처·고객명·금지 표현)만 합니다.
    kind: 블로그(필수 키워드·미션 11개·하단·광고) / 도입 사례(하단·광고·성과 문구 금지) / 영업 이메일((광고)·수신거부·수신자 자리표시·하단) / 카드뉴스(문장 단위만)
    market: 대상 시장을 주면 시장별 증거 규칙을 더합니다 (의료 규정 주장, 무역·물류 사례, 통역 조건, 신규 시장 표시)."""
    issues = []

    def add(kind, text, detail, weight):
        issues.append({"종류": kind, "문장": text[:90], "설명": detail, "감점": weight,
                       "상태": "차단" if weight >= BLOCK_AT else "검토 필요"})

    full = title + "\n" + body
    ms = []
    if doc_level and kind == "도입 사례":
        for item in FOOTER_ITEMS:
            if item not in body:
                add("하단 정보", "(하단)", f"'{item}' 없음", 3)
        if not re.search(r"광고|경제적\s*이해관계|제공받아", body):
            add("광고 표기", "(하단)", "광고임을 밝히는 문구가 없음", 10)
    elif doc_level and kind == "영업 이메일":
        if "(광고)" not in title:
            add("광고 표기", title or "(제목)", "제목에 '(광고)' 표기가 없음", 10)
        if not re.search(r"수신\s*거부|수신을\s*원하지", body):
            add("수신거부 안내", "(하단)", "수신거부 방법을 알리는 문구가 없음", 10)
        if RECIPIENT not in body:
            add("수신자 자리표시", "(본문)", f"받는 사람 자리에 '{RECIPIENT}' 자리표시가 없음 (실제 이름·연락처를 넣지 않음)", 8)
        for item in FOOTER_ITEMS:
            if item not in body:
                add("하단 정보", "(하단)", f"'{item}' 없음", 8)
    if doc_level and kind in ("블로그", "도입 사례", "영업 이메일") and market and market in new_markets() and NEW_MARKET_TAG not in body:
        add("신규 시장 표시", "(머리말)", f"{market}은 도입 사례 자료가 없는 시장이라 '{NEW_MARKET_TAG}' 표시가 있어야 함", 8)
    if doc_level and kind == "블로그":
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
        plain = _thousand(STRIP.sub(" ", s))
        has_fact_number = False
        for m in NUMBER.finditer(plain):
            raw, unit = m.group(1), (m.group(2) or "").replace(" ", "")
            try:
                num = round(float(raw.replace(",", "")), 2)
            except ValueError:
                continue
            uc = _uclass(unit)
            if num < 13 and uc not in STRICT_UNITS:
                continue                                   # '3가지', '5단계', '4장' 같은 순서·개수는 검사하지 않음
            if num < 3 and uc not in ("%", "원", "배"):
                continue                                   # '1곳', '2명' 같은 말은 검사하지 않음
            if num in (float(date.today().year), float(date.today().year + 1)) and not unit:
                continue                                   # 올해·내년 연도
            if num == 24 and unit == "시간":
                continue                                   # '24시간'은 관용 표현
            num = _scaled(num, unit)                       # '30만원'은 300,000 으로 봄 (환산값이 없으면 원래 숫자로 되돌아가지 않음)
            q_units = {_uclass(u) for u in ledger.get("원문숫자", {}).get(num, ())}
            in_quote = num not in ledger["예시숫자"] and (uc in q_units)   # 원문 구절에 같은 단위로 적힌 숫자
            known = set(ledger.get("단위", {}).get(num, ())) | q_units
            mine = ledger.get("항목", {}).get(num, set())
            ctx_ok = any(w in s for it in mine for w in KEY_CONTEXT.get(it, []))
            if num in ledger["허용숫자"] and "단위" in ledger and uc in STRICT_UNITS and uc not in known and not ("" in known and (ctx_ok or not mine)):
                add("근거 없는 수치", s, f"{raw}{unit}: 자료에는 이 숫자가 다른 단위({', '.join(sorted(k or '단위 없음' for k in known))})로만 나옴", 8)
            elif num in ledger["허용숫자"] or in_quote:
                usable = True
                if not ctx_ok and uc in STRICT_UNITS:   # 이 숫자의 항목 말은 없는데, 같은 단위를 쓰는 다른 항목 이야기를 하고 있으면 → 다른 항목의 수치
                    others = [it for it, words in KEY_CONTEXT.items() if it in (STRONG_ITEMS if mine else COUNT_ITEMS) and it not in mine and any(w in s for w in words if len(w) > 1)
                              and uc in ledger.get("항목단위", {}).get(it, ())]
                    if others or (mine and uc == "%" and all(KEY_CONTEXT.get(it) for it in mine)):
                        add("다른 항목의 수치", s, f"{raw}{unit}는 자료에서 '{', '.join(sorted(mine)) or '다른 내용'}'의 값인데 '{', '.join(others) or '다른 내용'}'에 쓰임", 8)
                        usable = False
                has_fact_number = has_fact_number or usable
                q = ledger["조건"].get(num)
                if q and unit in ("%", "퍼센트", "개", "개국") and not any(_n(w) in _n(s) for w in q["단어"]):
                    add("조건 누락", s, f"{raw}{unit}에는 '{q['단어'][0]}' 조건을 함께 써야 함 ({q['항목']})", 8)
                for c in ledger["확인필요"]:
                    shown = {round(float(x.group(1).replace(",", "")), 2) for x in NUMBER.finditer(plain) if x.group(1).replace(",", "").replace(".", "").isdigit()}
                    if num in c["숫자"] and any(w in s for w in c["문맥"]) and "[확인 필요" not in s and not set(c["숫자"]) <= shown:
                        add("충돌 수치", s, f"{c['항목']}은 자료마다 값이 다름 ({', '.join(f'{x:g}' for x in c['숫자'])}) → [확인 필요] 표시 필요", 8)
                for a in ledger.get("채택", []):
                    if num in a["버림"] and any(w in s for w in a["문맥"]):
                        add("채택하지 않은 값", s, f"{a['항목']}은 담당자가 {a['값']:g}(으)로 확정함 → {num:g}은(는) 쓰지 않음", 8)
            elif num in ledger["예시숫자"]:
                add("예시 값 사용", s, f"{raw}{unit}는 리포트 화면 예시에 나온 값이라 성능처럼 쓸 수 없음", 8)
            else:
                add("근거 없는 수치", s, f"{raw}{unit}는 사실 카드에 없는 숫자", 5 if uc == "시간" else 8)
        if EXAGGERATION.search(s):
            add("과장 표현", s, f"'{EXAGGERATION.search(s).group()}'", 6)
        if VAGUE_COUNT.search(s):
            add("근거 없는 수치", s, f"'{VAGUE_COUNT.search(s).group()}' 같은 어림수는 자료에 없음", 8)
        if MAGNITUDE.search(s) and not has_fact_number:
            add("성과 문구", s, f"효과의 크기를 말하는 문장에 자료 수치가 없음 ('{MAGNITUDE.search(s).group()}')", 8)
        if PERSONAL.search(s):
            add("개인 연락처", s, "대표번호·공식 메일이 아닌 연락처", 10)
        for lim in ledger.get("제약", []):
            if any(a.lower() in s.lower() for a in ALIASES.get(lim["대상"], [lim["대상"]])) and CLAIM_YES.search(s) and not CLAIM_NO.search(s):
                add("제약 위반", s, f"자료에는 '{lim['대상']}'은(는) 사용할 수 없다고 적혀 있음 ({lim['카드']} {lim['출처']})", 8)
        if OUTCOME.search(s) and not IF_CLAUSE.search(s) and (kind == "도입 사례" or not has_fact_number):      # 다른 종류는 자료 수치가 함께 있으면 허용 (통화료 절감 사례 등)
            add("성과 문구", s, f"성과 문구: 도입 효과 자료가 없음 ('{OUTCOME.search(s).group()}')", 8)
        if market:        # 시장별 증거 규칙
            if (INTERPRET.search(s) and not INTERPRET_QUAL.search(s) and "특허" not in s and not s.startswith(NEW_MARKET_TAG)
                    and not any(i["종류"] == "조건 누락" and i["문장"] == s[:90] for i in issues)):
                add("조건 누락", s, "통역 기능에는 '별도 부가서비스 신청' 또는 '계정 설정에 따라 제한' 조건을 함께 써야 함", 8)
            if market == "의료기관" and MEDICAL_CLAIM.search(s) and not NOT_A_CLAIM.search(s):
                add("의료 규정", s, f"의료 규정 관련 주장은 자료에 없음 ('{MEDICAL_CLAIM.search(s).group()}')", 8)
            if market == "무역·물류" and TRADE_CLAIM.search(s) and not re.search(TRADE_NOT, s):   # '~사례는 아닙니다'는 주장이 아님
                add("도입 사례 없음", s, "무역·물류 도입 사례 자료가 없음 (이 시장의 고객·사례·후기는 쓸 수 없음)", 8)
        if REG_CLAIM.search(s) and not NOT_A_CLAIM.search(s) and not any(i["종류"] == "의료 규정" and i["문장"] == s[:90] for i in issues):
            add("규정 주장", s, f"법규·규정 준수 주장은 자료에 없음 ('{REG_CLAIM.search(s).group()}')", 8)
        for r in rules or []:
            if r["금지"] and r["금지"] in s:
                add("금지 표현", s, f"담당자가 금지한 '{r['금지']}'" + (f" → '{r['대체']}'" if r.get("대체") else ""), 5)
    for name, ctx in _unmasked_names(full, ledger):
        line = next((ln.strip() for ln in full.splitlines() if name in ln), ctx)
        add("고객명", line, f"'{name}'은 가린 이름이 아님 (설치 사례 고객명은 가린 이름만 사용)", 10)
    score = max(0, 100 - sum(i["감점"] for i in issues))
    blocks = sum(1 for i in issues if i["감점"] >= BLOCK_AT)
    state = "차단" if blocks else "검토 필요" if issues else "통과"
    return {"점수": score, "상태": state, "차단": blocks, "검토": len(issues) - blocks,
            "통과": score >= 90 and not blocks, "문제": issues, "미션": ms, "종류": kind, "시장": market}


LIMIT = re.compile(r"([가-힣A-Za-z0-9]{2,12})(?:은|는|에서는)\s*(?:사용할 수 없|지원하지 않|지원되지 않|이용할 수 없|사용이 불가)")
CLAIM_YES = re.compile(r"지원|가능|사용할 수 있|됩니다|녹음|녹취|호환")
CLAIM_NO = re.compile(r"없|불가|않|미지원|제외|안 됩|안됩")
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
        bare = re.sub(r"(들의|의|인|한|형|용|된|적|들|별|와|과|및|은|는|도|을|를|이|가|에|로)$", "", m.group(1))      # '업종의 설치 사례', '벽걸이형 설치 사례'처럼 조사·접미사가 붙은 보통 말
        if len(bare) >= 2 and corpus and _n(bare) in corpus:
            continue
        consider(m.group(1), m.start(1), m.end(), need_context=False)
    return list(found.items())


def label_sentences(sentences: list[dict], result: dict, valid_cards: set[str]) -> list[dict]:
    """블로그 문장마다 [확인된 사실] / [AI 추론] / [확인 필요]. 표시는 코드가 정합니다."""
    out = []
    for s in sentences:
        cited = [c for c in s.get("근거카드", []) if c in valid_cards]
        mine = _issues_of(s["글"], result)
        if any(i["감점"] >= 5 for i in mine) or "[확인 필요" in s["글"]:
            lab = "확인 필요"
        elif cited:
            lab = "확인된 사실"
        else:
            lab = "AI 추론"
        out.append({**s, "근거카드": cited, "표시": lab, "상태": _state(lab, mine), "문제": [i["설명"] for i in mine]})
    return out


STATES = ("통과", "검토 필요", "차단", "미검사")


def _issues_of(text: str, result: dict) -> list[dict]:
    t = text.strip()
    return [i for i in result["문제"] if i["문장"] and not i["문장"].startswith("(") and (i["문장"] in t or t[:60] in i["문장"])]


def _state(label: str, mine: list[dict]) -> str:
    """문장별 검수 상태. 차단: 수치·조건·고객명·연락처 위반 / 검토 필요: 가벼운 위반, 근거 카드가 없는 문장, [확인 필요] 표시 문장."""
    if any(i["감점"] >= BLOCK_AT for i in mine):
        return "차단"
    if mine or label in ("AI 추론", "확인 필요"):
        return "검토 필요"
    return "통과"


def units(body: str) -> list[dict]:
    """본문을 줄 단위로 나눕니다 (원고는 한 줄에 한 문장). 종류: 소제목 / 문장 / 고정 문구(태그·하단 정보·광고 표기)."""
    out = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("■"):
            kind = "소제목"
        elif (s.startswith("#") and not s.startswith("#{")) or s.startswith("※") or s.startswith(NEW_MARKET_TAG) or any(f in s for f in FOOTER_ITEMS):
            kind = "고정 문구"
        else:
            kind = "문장"
        out.append({"글": s, "종류": kind})
    return out


def _numbers(text: str) -> list[tuple[float, str, str]]:
    """문장에서 검사 대상 숫자 (값, 단위, 원래 표기). '3가지' 같은 작은 개수는 뺍니다."""
    out = []
    for m in NUMBER.finditer(_thousand(STRIP.sub(" ", text))):
        unit = (m.group(2) or "").replace(" ", "")
        try:
            num = round(float(m.group(1).replace(",", "")), 2)
        except ValueError:
            continue
        if num < 13 and _uclass(unit) not in STRICT_UNITS:
            continue
        if num < 3 and _uclass(unit) not in ("%", "원", "배"):
            continue
        out.append((_scaled(num, unit), unit, m.group(0).strip()))
    return out


def citation_check(sentences: list[dict], cards_by_id: dict) -> dict:
    """출처 연결 확인: 문장에 쓴 수치가 그 문장이 인용한 사실 카드 안에 실제로 있는지 봅니다.
    없으면 그 문장을 '검토 필요'로 내립니다 (수치는 자료에 있지만 엉뚱한 카드를 근거로 댄 경우)."""
    total = hit = 0
    for s in sentences:
        if not s.get("근거카드"):
            continue
        pool = set()
        for cid in s["근거카드"]:
            c = cards_by_id.get(cid) or {}
            pool |= {round(float(v["숫자"]), 2) for v in (c.get("수치") or []) if v.get("숫자") is not None}
            pool |= {n for n, _, _ in _numbers(f"{c.get('원문', '')} {c.get('내용', '')}")}
            pool |= {round(float(m.group(1).replace(",", "")), 2) for m in NUMBER.finditer(f"{c.get('원문', '')} {c.get('내용', '')}")}
        for num, unit, raw in _numbers(s["글"]):
            total += 1
            plain = round(num / 1e4, 2) if unit.startswith("만") else round(num / 1e8, 2) if unit.startswith("억") else num
            if num in pool or plain in pool:
                hit += 1
            else:
                s["문제"] = [*s.get("문제", []), f"인용한 사실 카드에 '{raw}'가 없음 (다른 카드의 수치일 수 있음)"]
                if s["상태"] == "통과":
                    s["상태"] = "검토 필요"
    return {"수치": total, "카드에 있음": hit}


def variant_test(cards: list[dict], conflicts: list[dict], ledger: dict) -> dict:
    """표현 변형 시험: 같은 수치를 '약 200개', '200여 개', '200 개 이상'처럼 바꿔 써도 잘못 걸리지 않는지 봅니다."""
    in_conflict = {cid for x in conflicts for cid in x["카드"]}
    seen, rows, total = set(), [], 0
    for c in cards:
        if not c.get("원문확인") or c["id"] in in_conflict or c.get("유형") == "화면 예시 값":
            continue
        for v in c.get("수치") or []:
            m = NUMBER.search(str(v.get("값") or ""))
            if not m or v.get("숫자") is None:
                continue
            unit = (m.group(2) or "").replace(" ", "")
            num = float(m.group(1).replace(",", ""))
            if unit not in ("석", "개", "곳", "명", "원", "건", "USER") or num < 13 or num != int(num) or (num, unit) in seen:
                continue
            seen.add((num, unit))
            n = int(num)
            forms = [f"{n:,}{unit}", f"{n}{unit}", f"약 {n:,}{unit}", f"{n:,}여 {unit}", f"{n:,} {unit} 이상", f"{n:,}{unit} 규모"]
            if n >= 1000 and n % 1000 == 0:
                forms.append(f"{n // 1000}천 {unit}")
            for f in forms:
                total += 1
                lead = (KEY_CONTEXT.get(v.get("항목"), ["구축 사례"]) or ["구축 사례"])[-1 if v.get("항목") == "최대 구축 규모" else 0]
                r = check("", f"{lead}는 {f}입니다.", ledger, None, doc_level=False)
                bad = [i for i in r["문제"] if i["종류"] in ("근거 없는 수치", "예시 값 사용", "다른 항목의 수치")]
                if bad:
                    rows.append({"카드": c["id"], "자료 표기": v.get("값"), "바꿔 쓴 표현": f, "잘못 걸린 이유": bad[0]["설명"]})
    return {"수치": len(seen), "변형 문장": total, "잘못 걸림": len(rows), "표": rows}


def review(title: str, body: str, original: list[dict], ledger: dict | None, rules: list[dict] | None, valid_cards: set[str],
           cards_by_id: dict | None = None, kind: str = "블로그", market: str | None = None) -> dict:
    """화면의 재검증: 지금 원고(담당자가 고쳤을 수 있음)를 검사하고 문장마다 표시·상태·근거 카드를 붙입니다.
    AI 가 쓴 문장과 글자가 같으면 그 문장의 근거 카드를 이어받고, 담당자가 고치거나 새로 쓴 문장은 근거 없는 문장으로 봅니다.
    기준(ledger)이 없거나 검사가 실패하면 모든 문장이 '미검사'입니다."""
    by_text = {s["글"].strip(): s for s in original}
    rows = [u for u in units(body) if u["종류"] == "문장"]
    try:
        if ledger is None:
            raise ValueError("검수 기준(사실 카드)이 없음")
        result = check(title, body, ledger, rules, kind=kind, market=market)
    except Exception as e:  # noqa: BLE001 — 검사 실패는 화면을 멈추지 않고 '미검사'로 표시
        return {"검수": None, "오류": str(e)[:120],
                "문장": [{"글": u["글"], "근거카드": [], "표시": "미검사", "상태": "미검사", "문제": [], "수정됨": u["글"] not in by_text} for u in rows]}
    sentences = [{"글": u["글"], "근거카드": by_text.get(u["글"], {}).get("근거카드", []), "소제목": by_text.get(u["글"], {}).get("소제목", "")} for u in rows]
    labeled = label_sentences(sentences, result, valid_cards)
    for s in labeled:
        s["수정됨"] = s["글"] not in by_text
    result["수치인용"] = citation_check(labeled, cards_by_id) if cards_by_id else None
    n = len(labeled) or 1
    result["문장통계"] = {k: sum(1 for s in labeled if s["상태"] == k) for k in STATES}
    result["통과율"] = round(100 * result["문장통계"]["통과"] / n)
    return {"검수": result, "오류": "", "문장": labeled}


def false_positive_test(cards: list[dict], conflicts: list[dict], ledger: dict) -> dict:
    """오탐률: 원문 일치가 확인된 사실 카드의 문장(맞는 문장)을 그대로 검사했을 때 잘못 걸리는 비율.
    자료 간 충돌에 걸린 카드와 화면 예시 값 카드는 원래 경고가 나와야 하므로 제외합니다."""
    in_conflict = {cid for x in conflicts for cid in x["카드"]}
    pool = [c for c in cards if c.get("원문확인") and c["id"] not in in_conflict and c.get("유형") != "화면 예시 값"]
    rows = []
    for c in pool:
        r = check("", c["내용"], ledger, None, doc_level=False)
        if r["문제"]:
            rows.append({"카드": c["id"], "출처": c["출처"], "문장": c["내용"][:80], "잘못 걸린 이유": " / ".join(f"{i['종류']}: {i['설명']}" for i in r["문제"])[:160]})
    n = len(pool) or 1
    with_num = sum(1 for c in pool if _numbers(c["내용"]))
    return {"정상 문장": len(pool), "잘못 걸림": len(rows), "오탐률": round(100 * len(rows) / n, 1), "표": rows,
            "숫자 문장": with_num, "숫자 문장 오탐률": round(100 * len(rows) / (with_num or 1), 1)}


def holdout_test(ledger: dict, path=None) -> dict:
    """독립 작성 오류 세트: 검수 규칙을 만든 사람이 아닌 심사 역할이 따로 쓴 문장으로 잽니다.
    각 항목 {"문장","틀린 이유","작성","정상","종류"?,"시장"?}. 정상=True 인 문장은 걸리면 오탐입니다."""
    path = path or (ROOT / "tests" / "holdout.json")
    try:
        items = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"오류": 0, "검출": 0, "정상": 0, "오탐": 0, "놓침": [], "오탐목록": []}
    miss, fps, bad, ok = [], [], 0, 0
    for it in items:
        r = check("", it["문장"], ledger, None, doc_level=False, kind=it.get("종류") or "블로그", market=it.get("시장"))
        caught = bool(r["문제"])
        if it.get("정상"):
            ok += 1
            if caught:
                fps.append({"문장": it["문장"], "잡은 이유": r["문제"][0]["설명"]})
        else:
            bad += 1
            if not caught:
                miss.append({"문장": it["문장"], "틀린 이유": it.get("틀린 이유", ""), "작성": it.get("작성", "")})
    return {"오류": bad, "검출": bad - len(miss), "정상": ok, "오탐": len(fps), "놓침": miss, "오탐목록": fps}


# ───────────────────────── 주입 시험 ─────────────────────────
def injection_test(title: str, body: str, ledger: dict, rules: list[dict] | None = None,
                   kind: str = "블로그", market: str | None = None) -> dict:
    """정상 원고를 일부러 틀리게 고친 뒤, 검수가 그 변경을 잡아내는지 셉니다.
    kind·market 을 주면 그 종류·시장의 규칙을 시험하는 오류를 더합니다 (기본값은 블로그용 14가지 그대로)."""
    base = check(title, body, ledger, rules, kind=kind, market=market)
    base_count: dict = {}
    for i in base["문제"]:            # 원래 원고에 같은 문제가 이미 있어도, 넣은 오류로 그 수가 늘면 '검출'로 셉니다
        base_count[(i["종류"], i["설명"])] = base_count.get((i["종류"], i["설명"]), 0) + 1
    masked = ledger["가린고객명"][0] if ledger["가린고객명"] else ""
    no_ad = re.sub(r"※[^\n]*광고[^\n]*", "", body).replace("제공받아", "")
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
    ]
    if kind == "블로그":
        muts += [
            ("광고 표기 삭제", "광고 표기", title, no_ad),
            ("필수 키워드 삭제 (제목)", "필수 키워드", title.replace("업무자동화", "").replace("통화요약", ""), body),
            ("지어낸 사용 후기", "미션", title, body.replace("[직접 사용 후 작성", "직접 써 보니 정말 편했습니다. [삭제됨") if "[직접 사용 후 작성" in body else body + "\n직접 써 보니 정말 편했습니다."),
            ("하단 상담 번호 삭제", "하단 정보", title, body.replace("1877-3836", "")),
        ]
    elif kind == "도입 사례":
        muts += [
            ("지어낸 도입 성과", "성과 문구", title, body + "\n도입 후 상담 누락이 크게 줄었습니다."),
            ("광고 표기 삭제", "광고 표기", title, no_ad),
            ("하단 상담 번호 삭제", "하단 정보", title, body.replace("1877-3836", "")),
        ]
    elif kind == "영업 이메일":
        muts += [
            ("제목의 (광고) 표기 삭제", "광고 표기", title.replace("(광고)", "").strip(), body),
            ("수신거부 안내 삭제", "수신거부 안내", title, re.sub(r"[^\n]*(수신\s*거부|수신을\s*원하지)[^\n]*", "", body)),
            ("받는 사람 자리표시를 실제 이름으로 바꿈", "수신자 자리표시", title, body.replace(RECIPIENT, "김민수 부장")),
            ("하단 상담 번호 삭제", "하단 정보", title, body.replace("1877-3836", "")),
        ]
    if ledger.get("제약"):
        muts.append(("자료에서 안 된다고 한 것을 된다고 씀", "제약 위반", title, body + f"\n{ledger['제약'][0]['대상']} 통화도 자동으로 녹음됩니다."))
    if market:
        muts.append(("조건 없는 통역 기능", "조건 누락", title, body + "\n외국어 통화는 실시간 통역으로 바로 해결됩니다."))
    if market == "의료기관":
        muts.append(("자료에 없는 의료 규정 주장", "의료 규정", title, body + "\n의료법과 환자 개인정보 보호 규정을 준수합니다."))
    if market == "무역·물류":
        muts.append(("지어낸 무역 고객 사례", "도입 사례 없음", title, body + "\n이미 많은 무역회사들이 쓰고 있습니다."))
    if market and market in new_markets() and kind in ("블로그", "도입 사례", "영업 이메일") and NEW_MARKET_TAG in body:
        muts.append(("신규 시장 표시 삭제", "신규 시장 표시", title, re.sub(r"[^\n]*\[신규 시장 제안\][^\n]*\n?", "", body)))
    rows = []
    for name, expect, t_, b in muts:
        r = check(t_, b, ledger, rules, kind=kind, market=market)
        seen: dict = {}
        new = []
        for i in r["문제"]:
            k = (i["종류"], i["설명"])
            seen[k] = seen.get(k, 0) + 1
            if seen[k] > base_count.get(k, 0):
                new.append(i)
        hit = any(i["종류"] == expect for i in new)
        rows.append({"일부러 넣은 오류": name, "기대한 검출": expect, "결과": "검출" if hit else "놓침",
                     "검출 내용": next((i["설명"] for i in new if i["종류"] == expect), ""), "점수": r["점수"]})
    return {"원고 점수": base["점수"], "주입": len(rows), "검출": sum(r["결과"] == "검출" for r in rows), "표": rows, "종류": kind, "시장": market}
