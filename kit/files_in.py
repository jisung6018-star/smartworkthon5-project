"""파일 읽기 부품 — 무엇이 오든 read_text() 한 줄로 텍스트, read_table() 로 표.

    from kit.files_in import read_text, read_table, read_email, list_files, df_to_text
    read_text("견적요청.pdf")      # PDF(표 포함)·docx·hwp·hwpx·eml·txt·md·json·xlsx·csv·이미지(OCR)
    read_table("매출.csv")          # CSV 인코딩(utf-8/cp949) 자동 판별, xlsx/xls
    read_email("발주.eml")          # {"from","to","date","subject","body","attachments"}
"""
from __future__ import annotations

import email
import re
import struct
import zipfile
import zlib
from email import policy
from pathlib import Path

import pandas as pd

TEXT_EXT = {".txt", ".md", ".json", ".log", ".xml", ".html", ".htm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}  # llm.IMAGE_TYPES 와 같아야 함


def list_files(folder, *exts: str) -> list[Path]:
    """폴더 안 파일 목록 (확장자 필터, 이름순). list_files("samples/orders", ".eml")"""
    exts_l = {e.lower() if e.startswith(".") else "." + e.lower() for e in exts}
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and (not exts_l or p.suffix.lower() in exts_l))


# ───────────────────────── 표 ─────────────────────────
def _read_bytes_text(p: Path) -> str:
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_table(path, sheet=0, header: int = 0) -> pd.DataFrame:
    """엑셀/CSV → DataFrame. 한국 공공데이터 CSV(cp949)도 그대로 읽힙니다."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(p, sheet_name=sheet, header=header)
    if ext in (".csv", ".tsv", ".txt"):
        from io import StringIO
        text = _read_bytes_text(p)
        sep = "\t" if ext == ".tsv" else None
        return pd.read_csv(StringIO(text), sep=sep, engine="python", header=header)
    if ext == ".json":
        return pd.read_json(p)
    raise ValueError(f"표로 읽을 수 없는 형식: {p.name}")


def read_all_sheets(path) -> dict[str, pd.DataFrame]:
    return pd.read_excel(path, sheet_name=None)


def _cell(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) >= 1000):
        return f"{int(v):,}"
    if isinstance(v, float):
        return f"{v:,.4g}" if abs(v) < 1 else f"{v:,.2f}".rstrip("0").rstrip(".")
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return str(v).replace("\n", " ").replace("|", "/")


def df_to_text(df: pd.DataFrame, max_rows: int = 300) -> str:
    """DataFrame → 마크다운 표 문자열 (AI 에게 넘길 때·보고서 표). 숫자는 천 단위 콤마."""
    d = df.head(max_rows).astype(object).where(df.head(max_rows).notna(), "")
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in d.itertuples(index=False):
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    if len(df) > max_rows:
        lines.append(f"... (총 {len(df)}행 중 {max_rows}행만 표시)")
    return "\n".join(lines)


# ───────────────────────── PDF ─────────────────────────
def _pdf_text(p: Path) -> str:
    import pdfplumber
    out = []
    with pdfplumber.open(p) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            txt = page.extract_text() or ""
            out.append(f"--- {i}쪽 ---\n{txt}")
            for t in page.extract_tables() or []:
                if t and len(t) > 1:
                    df = pd.DataFrame(t[1:], columns=[c or f"열{j}" for j, c in enumerate(t[0])])
                    out.append("[표]\n" + df_to_text(df))
    text = "\n".join(out)
    if len(re.sub(r"--- \d+쪽 ---|\s", "", text)) < 20:
        text += "\n[⚠ 텍스트가 거의 없습니다. 스캔 PDF일 수 있어요 → llm.ask(..., files=[pdf]) 로 AI가 직접 읽게 하세요]"
    return text


def pdf_tables(path) -> list[pd.DataFrame]:
    """PDF 안의 표들을 DataFrame 목록으로."""
    import pdfplumber
    dfs = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables() or []:
                if t and len(t) > 1:
                    dfs.append(pd.DataFrame(t[1:], columns=[c or f"열{j}" for j, c in enumerate(t[0])]))
    return dfs


# ───────────────────────── Word ─────────────────────────
def _docx_text(p: Path) -> str:
    import docx
    d = docx.Document(str(p))
    out = [para.text for para in d.paragraphs if para.text.strip()]
    for t in d.tables:
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        if rows:
            out.append("[표]\n" + df_to_text(pd.DataFrame(rows[1:], columns=rows[0])))
    return "\n".join(out)


# ───────────────────────── 한글 ─────────────────────────
def _hwpx_text(p: Path) -> str:
    """HWPX = zip+XML. 한글 프로그램 없이 읽습니다."""
    out = []
    with zipfile.ZipFile(p) as z:
        secs = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n)),
                      key=lambda n: int(re.findall(r"\d+", n)[-1]))
        for n in secs:
            xml = z.read(n).decode("utf-8", errors="replace")
            for para in re.findall(r"<hp:p\b.*?</hp:p>", xml, re.S):
                ts = re.findall(r"<hp:t\b[^>]*>(.*?)</hp:t>", para, re.S)
                line = "".join(re.sub(r"<[^>]+>", "", t) for t in ts)
                if line.strip():
                    out.append(_unescape(line))
    return "\n".join(out)


def _unescape(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def _hwp_text(p: Path) -> str:
    """HWP 5.x 바이너리 본문을 한글 프로그램 없이 읽습니다 (배포용 문서는 COM 사용)."""
    import olefile
    with olefile.OleFileIO(str(p)) as ole:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack("<I", header[36:40])[0]
        compressed, distributed = bool(flags & 1), bool(flags & 4)
        if distributed:
            raise ValueError("배포용(암호화) HWP")
        sections = sorted((e for e in ole.listdir() if e[0] == "BodyText"), key=lambda e: int(e[1][7:]))
        out = []
        for sec in sections:
            data = ole.openstream(sec).read()
            if compressed:
                data = zlib.decompress(data, -15)
            i = 0
            while i + 4 <= len(data):
                h = struct.unpack("<I", data[i:i + 4])[0]
                tag, size = h & 0x3FF, (h >> 20) & 0xFFF
                i += 4
                if size == 0xFFF:
                    size = struct.unpack("<I", data[i:i + 4])[0]
                    i += 4
                if tag == 67:  # HWPTAG_PARA_TEXT
                    out.append(_para_text(data[i:i + size]))
                i += size
        return "\n".join(t for t in out if t.strip())


def _para_text(b: bytes) -> str:
    chars = struct.unpack(f"<{len(b) // 2}H", b[: len(b) // 2 * 2])
    s, k = [], 0
    while k < len(chars):
        c = chars[k]
        if c >= 32:
            s.append(chr(c)); k += 1
        elif c in (10, 13):
            s.append("\n" if c == 10 else ""); k += 1
        elif c in (24, 25, 26, 27, 28, 29, 30, 31):
            s.append(" " if c in (30, 31) else ("-" if c == 24 else "")); k += 1
        else:  # 표·그림 등 확장/인라인 컨트롤 = 8글자 분량
            if c == 9:
                s.append("\t")
            k += 8
    return "".join(s)


# ───────────────────────── 이메일 ─────────────────────────
def read_email(path) -> dict:
    """.eml → dict. 첨부파일은 output/attachments/ 에 저장하고 경로 목록을 돌려줍니다."""
    from .config import out_path
    p = Path(path)
    msg = email.message_from_bytes(p.read_bytes(), policy=policy.default)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""
    if body_part is not None and body_part.get_content_type() == "text/html":
        body = _html_to_text(body)
    atts = []
    for part in msg.iter_attachments():
        name = part.get_filename()
        if name:
            dst = out_path(f"{p.stem}__{name}", "attachments")
            dst.write_bytes(part.get_payload(decode=True) or b"")
            atts.append(str(dst))
    return {"file": p.name, "from": str(msg.get("From", "")), "to": str(msg.get("To", "")),
            "date": str(msg.get("Date", "")), "subject": str(msg.get("Subject", "")),
            "body": body.strip(), "attachments": atts}


def email_to_text(d: dict) -> str:
    return (f"보낸사람: {d['from']}\n받는사람: {d['to']}\n날짜: {d['date']}\n제목: {d['subject']}\n"
            f"첨부: {', '.join(Path(a).name for a in d['attachments']) or '없음'}\n\n{d['body']}")


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()


# ───────────────────────── 통합 ─────────────────────────
def read_text(path) -> str:
    """어떤 파일이든 텍스트로. (이미지는 AI OCR 을 사용하므로 API 키 필요)"""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _pdf_text(p)
    if ext == ".docx":
        return _docx_text(p)
    if ext == ".hwpx":
        return _hwpx_text(p)
    if ext == ".hwp":
        try:
            return _hwp_text(p)
        except Exception:
            from . import hwp
            return hwp.extract_text(p)
    if ext == ".eml":
        return email_to_text(read_email(p))
    if ext in (".xlsx", ".xlsm", ".xls"):
        return "\n\n".join(f"[시트: {n}]\n{df_to_text(df)}" for n, df in read_all_sheets(p).items())
    if ext in (".csv", ".tsv"):
        return df_to_text(read_table(p))
    if ext in (".html", ".htm"):
        return _html_to_text(_read_bytes_text(p))
    if ext in IMAGE_EXT:
        from .llm import ask
        return ask("이 이미지에 있는 글자를 빠짐없이 그대로 옮겨 적으세요. 표는 마크다운 표로. 설명은 붙이지 마세요.",
                   files=[p], system="", effort="low")
    if ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"):
        from .llm import transcribe
        return transcribe(p)
    if ext in TEXT_EXT or not ext:
        return _read_bytes_text(p)
    raise ValueError(f"지원하지 않는 형식: {p.name}")
