"""한글(HWP) 부품 — 공공·중소기업 문서 자동화의 핵심.

    from kit import hwp
    hwp.available()                                   # 한컴오피스 설치 여부
    hwp.markdown_to_hwp(md, "output/보고서.hwp", pdf=True)   # 마크다운 → HWP (+PDF)
    hwp.html_to_hwp(html, "output/공문.hwp")
    hwp.fill("samples/templates/주문확인서.hwpx", {"거래처": "가산정밀"}, "output/확인서_가산정밀.hwp", pdf=True)
        # 양식 안의 {{거래처}} 글자와 '거래처' 누름틀을 모두 채웁니다
    hwp.fill_hwpx(template.hwpx, values, out.hwpx)   # 한글 프로그램 없이 HWPX 채우기 (빠름)
    hwp.convert("a.hwp", "a.pdf")                     # hwp/hwpx/docx/html → hwp/hwpx/pdf/docx
    hwp.fields("양식.hwp")                            # 누름틀 이름 목록
    hwp.extract_text("a.hwp")
    hwp.pdf_preview("a.pdf", "a.png")                 # PDF 첫 쪽 PNG (화면 미리보기용)

한컴 COM 은 별도 프로세스에서 timeout 과 함께 실행하고, 끝나면 새로 뜬 Hwp.exe 만 정리합니다.
"""
from __future__ import annotations

import html as _html
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from .config import OUT

SAVE_FORMAT = {".hwp": "HWP", ".hwpx": "HWPX", ".pdf": "PDF", ".docx": "OOXML",
               ".html": "HTML", ".htm": "HTML", ".txt": "UNICODE"}
_WORKER = Path(__file__).with_name("_hwp_worker.py")


class HwpError(RuntimeError):
    pass


def available() -> bool:
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "HWPFrame.HwpObject"))
        return True
    except Exception:
        return False


def _hwp_pids() -> set[int]:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout
        return {int(m) for m in re.findall(r'"Hwp\.exe","(\d+)"', out, re.I)}
    except Exception:
        return set()


def security_module_registered() -> bool:
    """한컴 보안 모듈(FilePathCheckerModule)이 등록돼 있는지. 등록돼 있으면 '파일 접근 허용' 창이 뜨지 않는다."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\HNC\HwpAutomation\Modules") as k:
            path, _ = winreg.QueryValueEx(k, "FilePathCheckerModule")
        return Path(path).exists()
    except Exception:
        return False


def _security_dialog(pids: set[int]) -> int | None:
    """한글의 '파일 접근 허용' 보안 창(제목 '한글', 화면에 보이는 창)을 찾아 핸들을 돌려준다."""
    if not pids:
        return None
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found: list[int] = []
    proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _l):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(64)
            u.GetWindowTextW(h, b, 64)
            if len(b.value) <= 3 and b.value.endswith("글"):   # 제목이 '한글' (첫 글자는 한컴 전용 문자)
                found.append(h)
        return True

    u.EnumWindows(proc_t(cb), 0)
    if found:
        try:
            u.SetForegroundWindow(found[0])       # 다른 창 뒤에 숨지 않게 앞으로
        except Exception:
            pass
    return found[0] if found else None


SECURITY_HELP = ("한글이 '파일 접근 허용' 보안 창을 띄웠습니다. 화면의 '한글' 창에서 [모두 허용]을 눌러 주세요. "
                 "(매번 뜨지 않게 하려면 보안 모듈 등록이 필요합니다 — README '한글 보안 창')")


def _run(ops: list[dict], timeout: int = 120) -> list[dict]:
    if not available():
        raise HwpError("한컴오피스(HWPFrame.HwpObject)가 없습니다. HWPX 는 fill_hwpx() 를 쓰세요.")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"ops": ops}, f, ensure_ascii=False)
        job = f.name
    short = min(timeout, max(45, timeout // 2))   # 창도 없이 응답이 없으면 이만큼만 기다리고 한 번 재시도
    res, why = None, ""
    try:
        for attempt in (1, 2):
            before = _hwp_pids()
            proc = subprocess.Popen([sys.executable, str(_WORKER), job], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            t0, prompted = time.time(), False
            try:
                while True:
                    try:
                        out, err = proc.communicate(timeout=2.0)
                        lines = out.decode("utf-8", errors="replace").strip().splitlines()
                        if not lines:
                            raise HwpError(f"한글 작업 결과 없음: {err.decode('utf-8', errors='replace')[-500:]}")
                        res = json.loads(lines[-1])
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    waited = time.time() - t0
                    if not prompted and waited > 4 and _security_dialog(_hwp_pids() - before):
                        prompted = True
                        print("  ⚠ " + SECURITY_HELP)
                    if waited > (timeout if prompted else short):
                        why = "보안 창에 응답이 없었습니다" if prompted else "응답이 없었습니다"
                        break
            finally:
                if proc.poll() is None:
                    proc.kill()
                for pid in _hwp_pids() - before:  # Quit 해도 남는 Hwp.exe 정리 (원래 열려 있던 한글은 건드리지 않음)
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            if res is not None or prompted:        # 보안 창 때문이면 재시도해도 또 뜨므로 그만둔다
                break
            if attempt == 1:
                print(f"  (한글이 {short}초 동안 응답하지 않아 다시 시도합니다)")
    finally:
        Path(job).unlink(missing_ok=True)
    if res is None:
        raise HwpError(f"한글 작업 실패: {why}. " + (SECURITY_HELP if "보안" in why else "한글을 직접 열어 창이 떠 있지 않은지 확인하세요."))
    if not res.get("ok"):
        raise HwpError(res.get("error", "알 수 없는 오류"))
    return res["results"]


def _fmt(path: Path) -> str:
    try:
        return SAVE_FORMAT[path.suffix.lower()]
    except KeyError:
        raise HwpError(f"저장 형식을 모르는 확장자: {path.suffix}") from None


def _saves(dst: Path, pdf: bool) -> list[dict]:
    ops = [{"op": "save", "path": str(dst), "format": _fmt(dst)}]
    if pdf and dst.suffix.lower() != ".pdf":
        ops.append({"op": "save", "path": str(dst.with_suffix(".pdf")), "format": "PDF"})
    return ops


def _abs(p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (Path.cwd() / p).resolve()


# ───────────────────────── 공개 함수 ─────────────────────────
def convert(src, dst, pdf: bool = False, timeout: int = 120) -> Path:
    """hwp/hwpx/docx/html → hwp/hwpx/pdf/docx (dst 확장자로 결정)."""
    src, dst = _abs(src), _abs(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([{"op": "open", "path": str(src)}] + _saves(dst, pdf), timeout)
    return dst


def html_to_hwp(html: str, dst, pdf: bool = False, timeout: int = 120) -> Path:
    """HTML 문자열 → HWP/HWPX/PDF. 표·굵게·제목이 유지됩니다."""
    dst = _abs(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp"
    tmp.mkdir(exist_ok=True)
    src = tmp / (dst.stem + ".html")
    if "<html" not in html.lower():
        html = f'<html><head><meta charset="utf-8"></head><body>{html}</body></html>'
    src.write_text(html, encoding="utf-8")
    _run([{"op": "open", "path": str(src), "format": "HTML"}] + _saves(dst, pdf), timeout)
    return dst


def markdown_many_to_hwp(jobs: list[tuple[str, str | Path]], pdf: bool = False, timeout: int | None = None) -> list[Path]:
    """마크다운 여러 개를 한 번에 — 한글을 한 번만 띄워서 빠릅니다. jobs=[(md, dst), ...]"""
    from .docs_out import markdown_to_html
    tmp = OUT / "_tmp"
    tmp.mkdir(exist_ok=True)
    ops, outs = [], []
    for i, (md, dst) in enumerate(jobs):
        dst = _abs(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src = tmp / f"{i:03d}_{dst.stem}.html"
        src.write_text(markdown_to_html(md, for_hwp=True), encoding="utf-8")
        ops += [{"op": "open", "path": str(src), "format": "HTML"}] + _saves(dst, pdf)
        outs.append(dst)
    _run(ops, timeout or 60 + 15 * len(jobs))
    return outs


def markdown_to_hwp(md: str, dst, title: str | None = None, pdf: bool = False, timeout: int = 120) -> Path:
    """마크다운(제목 #, 목록 -, 표 |, **굵게**) → HWP. AI 가 쓴 보고서를 바로 한글 문서로."""
    from .docs_out import markdown_to_html
    return html_to_hwp(markdown_to_html(md, title=title, for_hwp=True), dst, pdf=pdf, timeout=timeout)


def _with_blanks(template, values: dict, blank_missing: bool) -> dict:
    vals = {str(k): "" if v is None else str(v) for k, v in values.items()}
    if blank_missing:
        try:
            for k in placeholders(template):
                vals.setdefault(k, "")
        except Exception:
            pass
    return vals


def fill(template, values: dict, dst, pdf: bool = False, blank_missing: bool = True, timeout: int = 120) -> Path:
    """양식 채우기: 누름틀(이름=키) + 본문의 {{키}} 글자를 values 로 바꿔 저장.
    blank_missing=True 면 값을 안 준 {{자리표시}} 는 빈칸으로 지웁니다."""
    template, dst = _abs(template), _abs(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    vals = _with_blanks(template, values, blank_missing)
    ops = [{"op": "open", "path": str(template)},
           {"op": "put_fields", "values": vals},
           {"op": "replace_all", "values": {"{{" + k + "}}": v for k, v in vals.items()}}]
    _run(ops + _saves(dst, pdf), timeout)
    return dst


def fill_many(template, jobs: list[tuple[dict, str | Path]], pdf: bool = False, blank_missing: bool = True,
              timeout: int | None = None) -> list[Path]:
    """같은 양식으로 여러 장 — 한글을 한 번만 띄워서 빠릅니다. jobs=[(values, dst), ...]"""
    template = _abs(template)
    ops, outs = [], []
    for values, dst in jobs:
        dst = _abs(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        vals = _with_blanks(template, values, blank_missing)
        ops += [{"op": "open", "path": str(template)},
                {"op": "put_fields", "values": vals},
                {"op": "replace_all", "values": {"{{" + k + "}}": v for k, v in vals.items()}}]
        ops += _saves(dst, pdf)
        outs.append(dst)
    _run(ops, timeout or 60 + 15 * len(jobs))
    return outs


def fields(path, timeout: int = 60) -> list[str]:
    return _run([{"op": "open", "path": str(_abs(path))}, {"op": "fields"}], timeout)[-1]["fields"]


def extract_text(path, timeout: int = 60) -> str:
    return _run([{"op": "open", "path": str(_abs(path))}, {"op": "get_text"}], timeout)[-1]["text"]


def fill_hwpx(template, values: dict, dst, blank_missing: bool = True) -> Path:
    """한글 프로그램 없이 HWPX 양식의 {{키}} 를 채웁니다 (한 번에 입력한 자리표시만 인식, 줄바꿈은 공백으로)."""
    template, dst = Path(template), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    vals = _with_blanks(template, values, blank_missing)
    rep = {"{{" + k + "}}": _html.escape(v.replace("\n", " "), quote=False) for k, v in vals.items()}
    with zipfile.ZipFile(template) as zin, zipfile.ZipFile(dst, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("Contents/") and item.filename.endswith(".xml"):
                text = data.decode("utf-8")
                for k, v in rep.items():
                    text = text.replace(k, v)
                data = text.encode("utf-8")
            # mimetype 은 압축 없이 첫 항목이어야 함 → 원본 압축 방식 유지
            zout.writestr(item, data, compress_type=item.compress_type)
    return dst


def placeholders(path) -> list[str]:
    """양식 안의 {{자리표시}} 목록 (hwpx 는 직접, hwp 는 텍스트 추출로)."""
    from .files_in import read_text
    return sorted(set(re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", read_text(path))))


def pdf_preview(pdf, png=None, page: int = 0, scale: float = 1.5) -> Path:
    import pypdfium2 as pdfium
    pdf = Path(pdf)
    png = Path(png) if png else pdf.with_suffix(".png")
    doc = pdfium.PdfDocument(str(pdf))
    doc[page].render(scale=scale).to_pil().save(png)
    doc.close()
    return png
