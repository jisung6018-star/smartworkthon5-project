"""현장 사진 홍보 콘텐츠 생성기 — 웹 화면

    python -m streamlit run app.py

핵심 기능 3개 (1단계 기획서와 같은 이름):
  ① 제품 정보와 현장 사진을 분석해 기술 포인트·차별점을 근거와 함께 정리        (AI 가 분석, 코드가 근거 대조)
  ② 고객 유형별 맞춤 문구 작성, 사람이 확인·수정                                (AI 가 작성, 코드가 글자 수·과장 표현 검사)
  ③ 실제 현장 사진으로 규격별 홍보 이미지와 SNS 게시글 자동 생성                (코드가 합성, 대비 검사)
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from kit import config, excel_out, files_in, llm, promo, web

TITLE = "현장 사진 홍보 콘텐츠 생성기"
INPUT = config.ROOT / "input"
OUT = config.OUT / "ads"
COLORS = {"자료 일치": "#C6E0B4", "사진 확인": "#C6E0B4", "근거 미확인": "#F4CCCC", "통과": "#C6E0B4", "확인 필요": "#FFEB9C"}

st.set_page_config(page_title=TITLE, page_icon="📣", layout="wide")
ss = st.session_state


def paint(df: pd.DataFrame, cols: list[str]):
    def style(v):
        c = COLORS.get(str(v))
        return f"background-color: {c}; color: #111" if c else ""
    return df.style.map(style, subset=[c for c in cols if c in df.columns])


def read_material_file(name: str, data: bytes) -> str:
    tmp = config.OUT / "uploads"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / name).write_bytes(data)
    return files_in.read_text(tmp / name)


# ───────────────────────── 사이드바 ─────────────────────────
with st.sidebar:
    st.header("설정")
    brand = st.text_input("이미지에 넣을 브랜드 이름", ss.get("brand", ""), placeholder="예: 회사 이름")
    labels = st.multiselect("만들 규격", list(promo.FORMATS), default=list(promo.FORMATS)[:3])
    st.divider()
    st.caption(f"AI: {llm.status()}")
    st.caption("💳 " + llm.usage_text())
    st.caption("제품과 현장은 실제 사진을 그대로 씁니다. AI 는 읽고 쓰는 일만 하고, 사진 자르기·글자 배치·검사는 코드가 합니다.")

st.title("📣 " + TITLE)
st.caption("제품 정보와 현장 사진만 넣으면, AI 가 기술 포인트와 차별점을 분석하고 고객 유형별 홍보 이미지와 SNS 게시글을 만들어 줍니다.")

# ───────────────────────── 입력 ─────────────────────────
st.subheader("입력: 제품 정보와 현장 사진")
c1, c2 = st.columns(2)
with c1:
    default_text = ""
    for f in sorted(INPUT.glob("*")) if INPUT.exists() else []:
        if f.is_file() and f.suffix.lower() in (".txt", ".md", ".pdf", ".hwp", ".hwpx", ".docx"):
            try:
                default_text += files_in.read_text(f) + "\n\n"
            except Exception:  # noqa: BLE001 — 못 읽는 파일은 건너뜀
                pass
    material = st.text_area("제품 정보 (소개서 내용을 붙여 넣거나 아래에서 파일·주소로 불러오기)", ss.get("material", default_text.strip()), height=230)
    u1, u2 = st.columns(2)
    doc = u1.file_uploader("제품 자료 파일", type=["pdf", "hwp", "hwpx", "docx", "txt", "md"])
    url = u2.text_input("제품 페이지 주소", placeholder="https://")
    if doc and st.button("파일 내용 불러오기"):
        ss.material = (material + "\n\n" + read_material_file(doc.name, doc.getvalue())).strip()
        st.rerun()
    if url and u2.button("주소에서 불러오기"):
        try:
            ss.material = (material + "\n\n" + web.fetch_text(url, max_chars=12000)).strip()
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"불러오기 실패: {e}")
with c2:
    ups = st.file_uploader("현장 사진 · 제품 사진 (여러 장)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    if ups:
        d = INPUT / "uploaded"
        d.mkdir(parents=True, exist_ok=True)
        for u in ups:
            (d / u.name).write_bytes(u.getvalue())
    photos = promo.list_photos(INPUT) if INPUT.exists() else []
    st.caption(f"사진 {len(photos)}장 (input 폴더)")
    if photos:
        st.image([str(p) for p in photos[:8]], width=110, caption=[p.name[:14] for p in photos[:8]])

ready = bool(photos) and bool(material.strip())
if not ready:
    st.info("제품 정보와 사진을 넣으면 시작할 수 있습니다.")

tab1, tab2, tab3 = st.tabs(["① 제품·기술 차별점 분석", "② 고객 유형별 맞춤 문구", "③ 홍보 콘텐츠 자동 생성"])

# ───────────────────────── ① 분석 ─────────────────────────
with tab1:
    if st.button("🔍 제품 정보와 사진 분석", type="primary", disabled=not ready):
        t0 = time.time()
        with st.spinner("AI 가 제품 자료를 읽고 사진을 보는 중…"):
            try:
                ss.analysis = promo.analyze(material, photos)
                ss.analysis_sec = time.time() - t0
                ss.material_used = material
                ss.pop("ads", None)
                ss.pop("files", None)
            except Exception as e:  # noqa: BLE001
                st.error(f"분석 실패: {e}")
    a = ss.get("analysis")
    if a:
        rep = promo.check([], a, ss.get("material_used", material))
        ev = pd.DataFrame(rep["근거표"])
        n_ok = int((ev["확인"] != "근거 미확인").sum()) if len(ev) else 0
        m = st.columns(4)
        m[0].metric("제품", a["제품명"])
        m[1].metric("기술 포인트 · 차별점", f"{len(a['기술포인트'])} · {len(a['차별점'])}")
        m[2].metric("근거 확인", f"{n_ok} / {len(ev)}", help="AI 가 댄 근거 구절이 제품 자료에 글자 그대로 있는지 코드가 대조")
        m[3].metric("분석 시간", f"{ss.get('analysis_sec', 0):.0f}초")
        st.markdown(f"**{a['한줄정의']}**")
        l, r = st.columns(2)
        with l:
            st.markdown("**기술 포인트** — 고객이 얻는 것과 근거")
            tp = pd.DataFrame(a["기술포인트"]).merge(ev[ev["구분"] == "기술포인트"][["항목", "확인"]], left_on="이름", right_on="항목", how="left").drop(columns="항목")
            st.dataframe(paint(tp, ["확인"]), hide_index=True, width="stretch")
            st.markdown("**차별점**")
            df = pd.DataFrame(a["차별점"]).merge(ev[ev["구분"] == "차별점"][["항목", "확인"]], left_on="내용", right_on="항목", how="left").drop(columns="항목")
            st.dataframe(paint(df, ["확인"]), hide_index=True, width="stretch")
        with r:
            st.markdown("**고객 유형 3가지** — 누구에게 무엇을 내세울지")
            for c in a["고객유형"]:
                st.markdown(f"- **{c['이름']}** — 관심사: {c['관심사']} → {c['설득포인트']}")
            st.markdown("**사진 분석** — 무엇이 찍혔고 광고에 어떻게 쓸지")
            st.dataframe(pd.DataFrame(a["사진"]), hide_index=True, width="stretch")
        if n_ok < len(ev):
            st.warning("'근거 미확인' 항목은 제품 자료에서 근거를 찾지 못했습니다. 문구에 쓰기 전에 사람이 확인하세요.")

# ───────────────────────── ② 문구 ─────────────────────────
with tab2:
    a = ss.get("analysis")
    if not a:
        st.info("먼저 ① 에서 분석을 실행하세요.")
    else:
        if st.button("✍️ 고객 유형별 문구 작성", type="primary"):
            with st.spinner("AI 가 고객 유형마다 다른 문구를 쓰는 중…"):
                try:
                    ss.ads = promo.write_copy(a)
                    ss.pop("files", None)
                except Exception as e:  # noqa: BLE001
                    st.error(f"작성 실패: {e}")
        ads = ss.get("ads")
        if ads:
            st.caption("칸을 더블클릭해 고칠 수 있습니다. 고친 문구가 그대로 이미지에 들어갑니다.")
            flat = pd.DataFrame([{"고객유형": x["고객유형"], "사진": x["사진"], "헤드라인": x["헤드라인"], "서브": x["서브"],
                                  "포인트1": (x["포인트"] + ["", "", ""])[0], "포인트2": (x["포인트"] + ["", "", ""])[1],
                                  "포인트3": (x["포인트"] + ["", "", ""])[2], "행동유도": x["행동유도"]} for x in ads])
            names = [p["파일"] for p in a["사진"]]
            edited = st.data_editor(flat, hide_index=True, width="stretch", key="ed_ads",
                                    column_config={"사진": st.column_config.SelectboxColumn(options=names),
                                                   "고객유형": st.column_config.TextColumn(disabled=True)})
            final = []
            for x, row in zip(ads, edited.to_dict("records")):
                final.append({**x, "사진": row["사진"], "헤드라인": row["헤드라인"], "서브": row["서브"],
                              "포인트": [p for p in (row["포인트1"], row["포인트2"], row["포인트3"]) if p], "행동유도": row["행동유도"]})
            ss.final_ads = final
            rep = promo.check(final, a, ss.get("material_used", material))
            st.markdown("**코드 검사** — 글자 수, 과장 표현, 근거")
            st.dataframe(paint(pd.DataFrame(rep["문구"]), ["검사"]), hide_index=True, width="stretch")
            for x in final:
                with st.expander(f"{x['고객유형']} — 내세운 근거와 SNS 게시글"):
                    st.markdown("근거: " + ", ".join(x.get("근거", [])))
                    st.markdown(x.get("게시글", ""))
                    st.markdown(" ".join(x.get("해시태그", [])))

# ───────────────────────── ③ 생성 ─────────────────────────
with tab3:
    a, final = ss.get("analysis"), ss.get("final_ads")
    if not (a and final):
        st.info("먼저 ② 에서 문구를 작성하세요.")
    else:
        if st.button("🖼 홍보 이미지 만들기", type="primary", disabled=not labels):
            t0 = time.time()
            with st.spinner("실제 사진을 규격별로 자르고 문구를 배치하는 중…"):
                formats = {k: promo.FORMATS[k] for k in labels}
                ss.files = promo.render_all(final, a, photos, OUT, formats, brand=brand or a["제품명"])
                ss.render_sec = time.time() - t0
        rows = ss.get("files")
        if rows:
            df = pd.DataFrame(rows)
            m = st.columns(4)
            m[0].metric("만든 이미지", f"{len(df)}장")
            m[1].metric("만드는 데 걸린 시간", f"{ss.get('render_sec', 0):.1f}초")
            m[2].metric("글자 대비 검사 통과", f"{int(df['대비통과'].sum())} / {len(df)}", help="흰 글자와 배경의 명도 대비 4.5 이상")
            m[3].metric("글자 넘침", f"{int(df['글자넘침'].sum())}건")
            for x in final:
                st.markdown(f"### {x['고객유형']}")
                mine = df[df["고객유형"] == x["고객유형"]]
                cols = st.columns(max(len(mine), 1))
                for col, r_ in zip(cols, mine.to_dict("records")):
                    col.image(r_["파일"], caption=f"{r_['규격']} · 대비 {r_['대비']}")
                with st.expander("함께 올릴 SNS 게시글"):
                    st.markdown(x.get("게시글", ""))
                    st.markdown(" ".join(x.get("해시태그", [])))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for r_ in rows:
                    z.write(r_["파일"], Path(r_["파일"]).name)
                z.writestr("SNS_게시글.txt", "\n\n".join(f"[{x['고객유형']}]\n{x.get('게시글', '')}\n{' '.join(x.get('해시태그', []))}" for x in final))
                rep = promo.check(final, a, ss.get("material_used", material))
                z.writestr("분석과_검사.xlsx", excel_out.to_bytes({
                    "기술포인트": pd.DataFrame(a["기술포인트"]), "차별점": pd.DataFrame(a["차별점"]), "고객유형": pd.DataFrame(a["고객유형"]),
                    "근거 대조": pd.DataFrame(rep["근거표"]), "문구 검사": pd.DataFrame(rep["문구"]),
                    "이미지 검사": df.drop(columns=["파일"])}, title="홍보 콘텐츠 분석과 검사"))
            st.download_button("⬇️ 이미지 · 게시글 · 분석표 한꺼번에 받기 (zip)", buf.getvalue(), file_name="홍보콘텐츠.zip", type="primary")
