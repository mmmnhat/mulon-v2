"""Tìm kiếm web + đọc trang cho collector (1.4.0, spec Feed 1.4).

Mulon trước 1.4 KHÔNG có năng lực tìm kiếm tự do: chỉ có
`web_fetch` (đọc 1 URL đã biết) và `web_read` (render JS). Module
này bổ sung search mà KHÔNG phụ thuộc API key trả phí:

- Nguồn chính: DuckDuckGo HTML (html.duckduckgo.com/html/) —
  trang kết quả server-side, parse bằng regex thuần.
- Dự phòng: DuckDuckGo Lite (lite.duckduckgo.com) rồi Bing HTML.
- Mọi nguồn chết/timeout -> trả [] sạch (collector coi như không
  có tư liệu search, KHÔNG lỗi hệ thống).

`fetch_page_text` là bản đọc trang dùng chung của collector
(httpx, gọt HTML -> text, giữ raw + content-type để nhận diện
RSS/Atom). Tool `web_search` của agent và collector của Feed gọi
CHUNG các hàm ở đây — một năng lực, hai bề mặt.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger("mulon.websearch")

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " \
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 MulonAgent/1.4"

# Host rút gọn link: kết quả trỏ vào đây không bao giờ là URL
# đích trích dẫn được (spec Feed mục 7.2).
SHORTENER_HOSTS = {
    "bit.ly", "t.co", "tinyurl.com", "goo.gl", "rb.gy",
    "shorturl.at", "cutt.ly", "is.gd", "buff.ly", "ow.ly",
}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html_lib.unescape(re.sub(r"\s+", " ", text)).strip()


def unwrap_result_url(raw: str) -> str:
    """Giải URL kết quả bị bọc qua redirect của máy tìm kiếm
    (DuckDuckGo /l/?uddg=...) về URL đích thật."""
    url = html_lib.unescape((raw or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    host = (parsed.hostname or "").lower()
    if "duckduckgo.com" in host and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        target = (qs.get("uddg") or [""])[0]
        if target:
            return unquote(target)
    if host.endswith("bing.com") and parsed.path.startswith("/ck/"):
        qs = parse_qs(parsed.query)
        target = (qs.get("u") or [""])[0]
        if target.startswith("a1"):
            import base64

            try:
                padded = target[2:] + "=" * (-len(target[2:]) % 4)
                return base64.urlsafe_b64decode(padded).decode(
                    "utf-8", "replace")
            except Exception:
                pass
    return url


def domain_of(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:
        return ""


def is_shortener(url: str) -> bool:
    return domain_of(url) in SHORTENER_HOSTS


# ---------------------------------------------------------------------------
# Parser kết quả tìm kiếm (hàm thuần — test bằng fixture HTML)
# ---------------------------------------------------------------------------

def parse_ddg_html(raw: str, limit: int = 5) -> list[dict]:
    """Parse trang kết quả DuckDuckGo HTML (bản /html/).

    Mỗi kết quả: thẻ <a class="result__a" href=...>tiêu đề</a>
    và đoạn trích <a class="result__snippet">...</a> đi sau.
    """
    results: list[dict] = []
    blocks = re.split(r'class="result[ "]', raw or "")[1:]
    for block in blocks:
        m = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block, re.DOTALL)
        if not m:
            continue
        url = unwrap_result_url(m.group(1))
        title = _clean(m.group(2))
        s = re.search(
            r'class="result__snippet"[^>]*>(.*?)</a>', block,
            re.DOTALL)
        snippet = _clean(s.group(1)) if s else ""
        if url and title and url.startswith(("http://", "https://")):
            results.append({"title": title, "url": url,
                            "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def parse_ddg_lite(raw: str, limit: int = 5) -> list[dict]:
    """Parse DuckDuckGo Lite: link kết quả là <a rel="nofollow"
    class="result-link">, snippet ở <td class="result-snippet">."""
    results: list[dict] = []
    links = re.findall(
        r'<a[^>]*class=[\'"]result-link[\'"][^>]*href="([^"]+)"[^>]*>'
        r"(.*?)</a>", raw or "", re.DOTALL)
    snippets = re.findall(
        r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>',
        raw or "", re.DOTALL)
    for i, (href, title_html) in enumerate(links):
        url = unwrap_result_url(href)
        title = _clean(title_html)
        snippet = _clean(snippets[i]) if i < len(snippets) else ""
        if url and title and url.startswith(("http://", "https://")):
            results.append({"title": title, "url": url,
                            "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def parse_bing_html(raw: str, limit: int = 5) -> list[dict]:
    """Parse trang kết quả Bing: mỗi kết quả trong <li class=
    "b_algo">, tiêu đề ở <h2><a href>, trích ở <p>."""
    results: list[dict] = []
    blocks = re.split(r'class="b_algo"', raw or "")[1:]
    for block in blocks:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>'
                      r"(.*?)</a>", block, re.DOTALL)
        if not m:
            continue
        url = unwrap_result_url(m.group(1))
        title = _clean(m.group(2))
        s = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
        snippet = _clean(s.group(1)) if s else ""
        if url and title and url.startswith(("http://", "https://")):
            results.append({"title": title, "url": url,
                            "snippet": snippet})
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------------------
# Search thật (mạng) — lỗi mọi kiểu đều degrade về []
# ---------------------------------------------------------------------------

async def _get_text(url: str, timeout: float, params=None) -> str:
    # Sửa 1.6.3: cùng SSRF guard như web_fetch (tools.http_get_public:
    # kiểm tra mỗi hop redirect, trust_env=False để HTTP_PROXY của
    # môi trường không chuyển hướng request qua nơi khác).
    # Lưu ý: params (query của máy tìm kiếm) chỉ dùng ở hop đầu;
    # redirect sau đó theo Location thuần, không mang theo params.
    from .tools import http_get_public

    import httpx

    async with httpx.AsyncClient(
        follow_redirects=False, timeout=timeout, trust_env=False,
        headers={"User-Agent": _UA},
    ) as client:
        if params:
            from urllib.parse import urlencode

            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode(params)}"
        resp = await http_get_public(client, url)
        resp.raise_for_status()
        return resp.text or ""


async def search_web(query: str, limit: int = 5,
                     timeout: float = 12.0) -> list[dict]:
    """Tìm web theo từ khóa. Trả [{title, url, snippet}] — URL
    đã giải redirect của máy tìm kiếm. Mọi lỗi -> []."""
    query = (query or "").strip()
    if not query:
        return []
    attempts = [
        ("https://html.duckduckgo.com/html/", {"q": query},
         parse_ddg_html),
        ("https://lite.duckduckgo.com/lite/", {"q": query},
         parse_ddg_lite),
        ("https://www.bing.com/search", {"q": query},
         parse_bing_html),
    ]
    for url, params, parser in attempts:
        try:
            raw = await _get_text(url, timeout, params=params)
        except Exception as exc:
            logger.info("search qua %s lỗi (thử nguồn sau): %s",
                        url, exc)
            continue
        try:
            results = parser(raw, limit=limit)
        except Exception as exc:
            logger.info("parse kết quả %s lỗi: %s", url, exc)
            results = []
        if results:
            return results
    return []


# ---------------------------------------------------------------------------
# Đọc trang cho collector
# ---------------------------------------------------------------------------

def strip_html_text(raw: str, max_chars: int = 12_000) -> str:
    """Gọt HTML -> text (cùng kỷ luật với tool web_fetch)."""
    text = re.sub(
        r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ",
        raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return html_lib.unescape(re.sub(r"\s+", " ", text)).strip()[
        :max_chars]


def looks_like_feed(raw: str, content_type: str = "") -> bool:
    ct = (content_type or "").lower()
    if "rss" in ct or "atom" in ct or "xml" in ct:
        head = (raw or "")[:2000].lower()
        return "<rss" in head or "<feed" in head
    head = (raw or "")[:500].lstrip().lower()
    return head.startswith("<?xml") and (
        "<rss" in (raw or "")[:2000].lower()
        or "<feed" in (raw or "")[:2000].lower())


def parse_feed_items(raw: str, limit: int = 5) -> list[dict]:
    """Tách item từ RSS/Atom: [{title, url, snippet}] — URL trích
    dẫn là URL của item, không phải URL của feed."""
    items: list[dict] = []
    blocks = re.findall(r"<item[\s>][\s\S]*?</item>", raw or "")
    if not blocks:
        blocks = re.findall(r"<entry[\s>][\s\S]*?</entry>", raw or "")
    for block in blocks:
        t = re.search(r"<title[^>]*>([\s\S]*?)</title>", block)
        title = _clean(
            (t.group(1) if t else "").replace("<![CDATA[", "")
            .replace("]]>", ""))
        link = ""
        m = re.search(r"<link[^>]*>([\s\S]*?)</link>", block)
        if m:
            link = _clean(m.group(1))
        if not link:
            m = re.search(r'<link[^>]*href="([^"]+)"', block)
            if m:
                link = html_lib.unescape(m.group(1))
        d = re.search(
            r"<description[^>]*>([\s\S]*?)</description>", block)
        if not d:
            d = re.search(r"<summary[^>]*>([\s\S]*?)</summary>",
                          block)
        snippet = _clean(
            (d.group(1) if d else "").replace("<![CDATA[", "")
            .replace("]]>", ""))[:500]
        if title and link.startswith(("http://", "https://")):
            items.append({"title": title, "url": link,
                          "snippet": snippet})
        if len(items) >= limit:
            break
    return items


def register_search_tool(registry) -> None:
    """Đăng ký tool `web_search` (chỉ đọc) cho agent — đăng ký
    RIÊNG ngoài build_default_registry như các họ tool khác
    (browser/planning/media), để contract registry lõi giữ
    nguyên. Collector của Feed dùng thẳng search_web, không
    qua tool này."""
    from .tools import ToolSpec

    async def web_search(query: str, limit: int = 5):
        results = await search_web(
            query, limit=max(1, min(10, int(limit))))
        if not results:
            return {"ok": False,
                    "error": "không có kết quả hoặc nguồn tìm "
                             "kiếm không trả lời",
                    "results": []}
        return {"ok": True, "query": query, "results": results}

    registry.register(ToolSpec(
        "web_search",
        "Tìm kiếm web theo từ khóa (chỉ đọc). Trả danh sách kết "
        "quả {title, url, snippet} — URL đã giải redirect. Dùng "
        "để TÌM trang trước khi đọc bằng web_fetch/web_read. "
        "Không có API key trả phí; nguồn tìm kiếm chết thì trả "
        "danh sách rỗng kèm ok=false.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        "web", 45, web_search))


async def fetch_page_text(url: str, timeout: float = 12.0,
                          max_chars: int = 12_000) -> dict:
    """Đọc 1 URL cho collector. Trả {ok, url (sau redirect),
    status, content (text đã gọt), raw_head, content_type}.
    Lỗi -> {ok: False, error} — không bao giờ raise."""
    # Sửa 1.6.3: SSRF guard như web_fetch (xem _get_text).
    from .tools import http_get_public

    import httpx

    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=timeout, trust_env=False,
            headers={"User-Agent": _UA},
        ) as client:
            resp = await http_get_public(client, url)
        raw = resp.text or ""
        return {
            "ok": True,
            "url": str(resp.url),
            "status": int(resp.status_code),
            "content": strip_html_text(raw, max_chars),
            "raw": raw[:200_000],
            "content_type": resp.headers.get("content-type", ""),
        }
    except Exception as exc:  # noqa: BLE001 - collector nuốt lỗi
        return {"ok": False, "url": url,
                "error": f"{type(exc).__name__}: {exc}"}
