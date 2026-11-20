"""한컴 COM 작업 실행기 (kit.hwp 가 별도 프로세스로 실행). 직접 쓰지 마세요.

인자: job.json 경로. job = {"ops": [{"op": ..., ...}, ...]}
결과: 마지막 줄에 JSON {"ok": bool, "results": [...], "error": str?}
"""
import json
import sys


def main(job_path: str) -> None:
    job = json.load(open(job_path, encoding="utf-8"))
    import pythoncom
    import win32com.client as win32

    pythoncom.CoInitialize()
    hwp = win32.Dispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception:
        pass
    try:
        hwp.XHwpWindows.Item(0).Visible = False
    except Exception:
        pass
    results = []
    try:
        for op in job["ops"]:
            kind = op["op"]
            if kind == "open":
                ok = False
                for fmt in ([op.get("format")] if op.get("format") is not None else ["", "HWP", "HWPX", "OOXML", "HTML"]):
                    ok = bool(hwp.Open(op["path"], fmt, "forceopen:true"))
                    if ok:
                        break
                if not ok:
                    raise RuntimeError(f"열기 실패: {op['path']}")
                results.append({"op": "open", "pages": hwp.PageCount})
            elif kind == "save":
                ok = bool(hwp.SaveAs(op["path"], op["format"], ""))
                if not ok:
                    raise RuntimeError(f"저장 실패: {op['path']} ({op['format']})")
                results.append({"op": "save", "path": op["path"]})
            elif kind == "fields":
                raw = hwp.GetFieldList(0, 0) or ""
                results.append({"op": "fields", "fields": [f for f in raw.split("\x02") if f]})
            elif kind == "put_fields":
                existing = set((hwp.GetFieldList(0, 0) or "").split("\x02"))
                done = []
                for k, v in op["values"].items():
                    if k in existing:
                        hwp.PutFieldText(k, str(v))
                        done.append(k)
                results.append({"op": "put_fields", "filled": done})
            elif kind == "replace_all":
                n = 0
                for k, v in op["values"].items():
                    pset = hwp.HParameterSet.HFindReplace
                    hwp.HAction.GetDefault("AllReplace", pset.HSet)
                    pset.FindString = k
                    pset.ReplaceString = str(v).replace("\r\n", "\n").replace("\n", "\r")
                    pset.IgnoreMessage = 1
                    try:
                        pset.Direction = hwp.FindDir("AllDoc")
                    except Exception:
                        pass
                    if hwp.HAction.Execute("AllReplace", pset.HSet):
                        n += 1
                results.append({"op": "replace_all", "executed": n})
            elif kind == "get_text":
                results.append({"op": "get_text", "text": hwp.GetTextFile("UNICODE", "") or ""})
            else:
                raise RuntimeError(f"모르는 작업: {kind}")
        print(json.dumps({"ok": True, "results": results}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "results": results, "error": str(e)}, ensure_ascii=False))
    finally:
        try:
            hwp.Clear(1)
            hwp.Quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1])
