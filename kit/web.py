"""웹 수집 부품 — 공고·뉴스·가격표 같은 페이지에서 글/링크/표 가져오기.

    from kit.web import fetch_text, get_links, get_tables
    fetch_text("https://example.com/notice/123")              # 본문 텍스트 (euc-kr 사이트도 OK)
    get_links("https://example.com/notice", contains="view")  # [(제목, 절대URL), ...]
    get_tables("https://example.com/price")                   # [DataFrame, ...]

※ 로그인·자바스크립트로 그리는 페이지는 안 됩니다. 수집 전 사이트 이용약관/robots.txt 확인.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36"}


def fetch_html(url: str, timeout: int = 15) -> str:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


def soup(url_or_html: str) -> BeautifulSoup:
    html = fetch_html(url_or_html) if url_or_html.startswith("http") else url_or_html
    return BeautifulSoup(html, "html.parser")


def fetch_text(url: str, max_chars: int = 30000) -> str:
    s = soup(url)
    for t in s(["script", "style", "nav", "header", "footer", "aside", "noscript", "form"]):
        t.decompose()
    main = s.find("main") or s.find("article") or s.body or s
    text = re.sub(r"\n\s*\n+", "\n\n", main.get_text("\n")).strip()
    return text[:max_chars]


def get_links(url: str, contains: str | None = None, min_text: int = 2) -> list[tuple[str, str]]:
    s = soup(url)
    out, seen = [], set()
    for a in s.find_all("a", href=True):
        href = urljoin(url, a["href"])
        title = " ".join(a.get_text(" ").split())
        if len(title) < min_text or href in seen or href.startswith("javascript"):
            continue
        if contains and contains not in href and contains not in title:
            continue
        seen.add(href)
        out.append((title, href))
    return out


def get_tables(url_or_html: str) -> list[pd.DataFrame]:
    s = soup(url_or_html)
    dfs = []
    for t in s.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in t.find_all("tr")]
        rows = [r for r in rows if r]
        if len(rows) < 2:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        dfs.append(pd.DataFrame(rows[1:], columns=[c or f"열{i}" for i, c in enumerate(rows[0])]))
    return dfs
