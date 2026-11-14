"""Crawler: scansiona un intero sito partendo da un solo URL.

Scopre le pagine seguendo i link interni (BFS) e leggendo la sitemap XML,
poi analizza ogni pagina HTML (title, meta, heading, contenuto, link, immagini, schema...).
"""
from __future__ import annotations

import gzip
import html as htmllib
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; SeoAuditPersonale/1.0)"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

SKIP_EXT = re.compile(
    r"\.(jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff?|pdf|zip|rar|7z|gz|mp4|mov|avi|webm|mp3|wav|ogg|"
    r"css|js|json|woff2?|ttf|eot|xml|txt|docx?|xlsx?|pptx?|csv)$",
    re.I,
)
SKIP_PATH = re.compile(
    r"/(wp-admin|wp-login\.php|wp-json|xmlrpc\.php|cart|carrello|checkout|cassa|my-account|mio-account|"
    r"account|feed|cdn-cgi)(/|$)",
    re.I,
)


def normalize(url: str) -> str:
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    if (scheme == "http" and netloc.endswith(":80")) or (scheme == "https" and netloc.endswith(":443")):
        netloc = netloc.rsplit(":", 1)[0]
    path = p.path or "/"
    return f"{scheme}://{netloc}{path}" + (f"?{p.query}" if p.query else "")


def bare_host(netloc: str) -> str:
    netloc = netloc.lower().split("@")[-1]
    return netloc[4:] if netloc.startswith("www.") else netloc


@dataclass
class Page:
    url: str
    status: int = 0
    final_url: str = ""
    redirect_to: str = ""
    response_ms: int = 0
    content_type: str = ""
    size_kb: float = 0.0
    depth: int | None = None
    in_sitemap: bool = False
    error: str = ""
    # contenuto
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    x_robots: str = ""
    canonical: str = ""
    h1: list = field(default_factory=list)
    h2: list = field(default_factory=list)
    h3_count: int = 0
    lang: str = ""
    word_count: int = 0
    text: str = ""
    internal_links: list = field(default_factory=list)
    external_links: list = field(default_factory=list)
    nofollow_links: int = 0
    images: int = 0
    images_no_alt: int = 0
    schema_types: list = field(default_factory=list)
    has_viewport: bool = False
    has_og: bool = False
    hreflang_count: int = 0

    @property
    def is_html(self) -> bool:
        return "html" in (self.content_type or "")

    @property
    def noindex(self) -> bool:
        return "noindex" in (self.meta_robots + " " + self.x_robots).lower()

    @property
    def canonical_other(self) -> bool:
        return bool(self.canonical) and normalize(self.canonical) != normalize(self.url)

    @property
    def indexable(self) -> bool:
        return self.status == 200 and self.is_html and not self.noindex and not self.canonical_other


# ----------------------------------------------------------------------------- sitemap / robots

def _get(session: requests.Session, url: str, timeout: int = 20) -> requests.Response | None:
    try:
        return session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None


def read_robots(session, root: str):
    r = _get(session, root + "/robots.txt")
    text = r.text if (r is not None and r.status_code == 200 and "<html" not in r.text[:500].lower()) else ""
    rp = robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)
    return text, rp, sitemaps


def read_sitemaps(session, root: str, declared: list[str], limit_files: int = 60, limit_urls: int = 50000) -> set[str]:
    candidates = list(declared) or [
        root + "/sitemap.xml",
        root + "/sitemap_index.xml",
        root + "/wp-sitemap.xml",
        root + "/sitemap-index.xml",
    ]
    urls: set[str] = set()
    done: set[str] = set()
    while candidates and len(done) < limit_files and len(urls) < limit_urls:
        sm = candidates.pop(0)
        if sm in done:
            continue
        done.add(sm)
        r = _get(session, sm, timeout=30)
        if r is None or r.status_code != 200:
            continue
        content = r.content
        if sm.endswith(".gz") or content[:2] == b"\x1f\x8b":
            try:
                content = gzip.decompress(content)
            except OSError:
                pass
        text = content.decode("utf-8", errors="ignore")
        locs = [htmllib.unescape(x) for x in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.S | re.I)]
        if "<sitemapindex" in text.lower():
            candidates.extend(locs)
        else:
            for u in locs:
                urls.add(normalize(u))
        if declared == [] and urls:  # trovata una sitemap valida tra i candidati standard
            candidates = [c for c in candidates if not c.startswith(root + "/sitemap") and "wp-sitemap" not in c]
    return urls


# ----------------------------------------------------------------------------- parsing pagina

def _schema_types(soup) -> list[str]:
    types: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.add(t)
            elif isinstance(t, list):
                types.update(str(x) for x in t)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for s in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            walk(json.loads(s.string or s.get_text() or "{}"))
        except (ValueError, TypeError):
            continue
    for tag in soup.find_all(attrs={"itemtype": True}):
        types.add(str(tag["itemtype"]).rstrip("/").rsplit("/", 1)[-1])
    return sorted(types)


def _has_rel(tag_rel, value: str) -> bool:
    if not tag_rel:
        return False
    vals = tag_rel if isinstance(tag_rel, list) else str(tag_rel).split()
    return value in [v.lower() for v in vals]


def parse_html(page: Page, content: bytes, base_url: str, root_host: str) -> None:
    try:
        soup = BeautifulSoup(content, "lxml")
    except Exception:  # noqa: BLE001
        soup = BeautifulSoup(content, "html.parser")

    page.title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:300]
    md = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    page.meta_description = (md.get("content") or "").strip() if md else ""
    mr = soup.find("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)})
    page.meta_robots = (mr.get("content") or "").strip().lower() if mr else ""
    can = soup.find("link", rel=lambda v: _has_rel(v, "canonical"))
    page.canonical = urljoin(base_url, can.get("href", "").strip()) if can and can.get("href") else ""
    page.h1 = [t for t in (h.get_text(" ", strip=True) for h in soup.find_all("h1")) if t]
    page.h2 = [t for t in (h.get_text(" ", strip=True) for h in soup.find_all("h2")) if t][:40]
    page.h3_count = len(soup.find_all("h3"))
    page.lang = (soup.html.get("lang") or "") if soup.html else ""
    page.has_viewport = bool(soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}))
    page.has_og = bool(soup.find("meta", attrs={"property": re.compile("^og:", re.I)}))
    page.hreflang_count = len(soup.find_all("link", hreflang=True))
    page.schema_types = _schema_types(soup)

    imgs = soup.find_all("img")
    page.images = len(imgs)
    page.images_no_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())

    base_tag = soup.find("base", href=True)
    link_base = urljoin(base_url, base_tag["href"]) if base_tag else base_url
    internal, external, seen = [], [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "whatsapp:", "sms:")):
            continue
        absu = urljoin(link_base, href)
        if not absu.startswith(("http://", "https://")):
            continue
        absu = normalize(absu)
        if _has_rel(a.get("rel"), "nofollow"):
            page.nofollow_links += 1
        if absu in seen:
            continue
        seen.add(absu)
        if bare_host(urlparse(absu).netloc) == root_host:
            internal.append(absu)
        else:
            external.append(absu)
    page.internal_links = internal
    page.external_links = external

    for t in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        t.decompose()
    for t in soup.find_all(["nav", "header", "footer", "aside", "form"]):
        t.decompose()
    for t in soup.find_all(attrs={"class": re.compile(r"(cookie|gdpr|menu|breadcrumb|footer|header|navbar)", re.I)}):
        t.decompose()
    body = soup.body or soup
    text = body.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    page.word_count = len(re.findall(r"\w+", text))
    page.text = text[:30000]


# ----------------------------------------------------------------------------- crawl

class Crawler:
    def __init__(
        self,
        start_url: str,
        max_pages: int = 300,
        workers: int = 6,
        respect_robots: bool = True,
        ignore_query: bool = True,
        use_sitemap: bool = True,
        delay: float = 0.0,
        progress=None,
    ):
        if not start_url.startswith(("http://", "https://")):
            start_url = "https://" + start_url
        self.start_url = normalize(start_url)
        self.max_pages = max_pages
        self.workers = workers
        self.respect_robots = respect_robots
        self.ignore_query = ignore_query
        self.use_sitemap = use_sitemap
        self.delay = delay
        self.progress = progress or (lambda *a, **k: None)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        adapter = requests.adapters.HTTPAdapter(pool_connections=workers * 2, pool_maxsize=workers * 2)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.pages: dict[str, Page] = {}
        self.inlinks: dict[str, set] = defaultdict(set)
        self.seen: set[str] = set()
        self.robots_txt = ""
        self.rp = None
        self.sitemap_urls: set[str] = set()
        self.blocked_by_robots: set[str] = set()

    # -- filtri
    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        if bare_host(p.netloc) != self.root_host:
            return False
        if SKIP_EXT.search(p.path) or SKIP_PATH.search(p.path):
            return False
        if self.ignore_query and p.query:
            return False
        if self.respect_robots and self.rp is not None and not self.rp.can_fetch(UA, url):
            self.blocked_by_robots.add(url)
            return False
        return True

    # -- download singola pagina
    def fetch(self, url: str) -> list[Page]:
        if self.delay:
            time.sleep(self.delay)
        page = Page(url=url)
        t0 = time.time()
        try:
            r = self.session.get(url, timeout=25, allow_redirects=True, stream=True)
            content = r.raw.read(6 * 1024 * 1024, decode_content=True) if r.raw else r.content
            r.close()
        except requests.RequestException as e:
            page.error = type(e).__name__
            page.response_ms = int((time.time() - t0) * 1000)
            return [page]
        page.response_ms = int((time.time() - t0) * 1000)
        final = normalize(r.url)
        out = [page]
        target = page
        if r.history:
            page.status = r.history[0].status_code
            page.redirect_to = final
            page.final_url = final
            if bare_host(urlparse(final).netloc) != self.root_host or final in self.seen:
                return out  # redirect verso esterno o pagina già vista
            self.seen.add(final)
            target = Page(url=final)
            target.response_ms = page.response_ms
            out.append(target)
        target.status = r.status_code
        target.final_url = final
        target.content_type = (r.headers.get("Content-Type") or "").lower()
        target.x_robots = (r.headers.get("X-Robots-Tag") or "").lower()
        target.size_kb = round(len(content) / 1024, 1)
        if target.status == 200 and target.is_html:
            try:
                parse_html(target, content, final, self.root_host)
            except Exception as e:  # noqa: BLE001
                target.error = f"parse: {type(e).__name__}"
        return out

    def run(self) -> dict:
        self.progress(0, self.max_pages, "Verifico l'URL di partenza…")
        r = _get(self.session, self.start_url)
        if r is None:
            raise RuntimeError(f"Il sito {self.start_url} non risponde.")
        resolved = normalize(r.url)
        rp_ = urlparse(resolved)
        self.root = f"{rp_.scheme}://{rp_.netloc}"
        self.root_host = bare_host(rp_.netloc)

        self.progress(0, self.max_pages, "Leggo robots.txt e sitemap…")
        self.robots_txt, rp, declared = read_robots(self.session, self.root)
        self.rp = rp
        if self.use_sitemap:
            self.sitemap_urls = read_sitemaps(self.session, self.root, declared)

        start = self.start_url if self.start_url == resolved else self.start_url
        frontier = [start]
        self.seen.add(start)
        depth = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            while frontier and len(self.pages) < self.max_pages:
                batch = frontier[: max(0, self.max_pages - len(self.pages))]
                next_frontier: list[str] = []
                for results in pool.map(self.fetch, batch):
                    for pg in results:
                        if len(self.pages) >= self.max_pages and pg.url not in self.pages:
                            break
                        pg.depth = depth
                        self.pages[pg.url] = pg
                        for link in pg.internal_links:
                            self.inlinks[link].add(pg.url)
                            if link not in self.seen and self.allowed(link):
                                self.seen.add(link)
                                next_frontier.append(link)
                    self.progress(len(self.pages), self.max_pages, results[-1].url)
                frontier = next_frontier
                depth += 1

            # pagine presenti solo in sitemap (potenziali orfane)
            extra = [u for u in sorted(self.sitemap_urls) if u not in self.seen and self.allowed(u)]
            extra = extra[: max(0, self.max_pages - len(self.pages))]
            for u in extra:
                self.seen.add(u)
            for results in pool.map(self.fetch, extra):
                for pg in results:
                    pg.depth = None
                    self.pages[pg.url] = pg
                    for link in pg.internal_links:
                        self.inlinks[link].add(pg.url)
                self.progress(len(self.pages), self.max_pages, results[-1].url)

        for u, pg in self.pages.items():
            pg.in_sitemap = u in self.sitemap_urls
        return {
            "start_url": self.start_url,
            "root": self.root,
            "host": self.root_host,
            "pages": list(self.pages.values()),
            "inlinks": {k: sorted(v) for k, v in self.inlinks.items()},
            "sitemap_urls": sorted(self.sitemap_urls),
            "robots_txt": self.robots_txt,
            "blocked_by_robots": sorted(self.blocked_by_robots),
            "limit_reached": len(self.pages) >= self.max_pages,
        }


def check_external_links(urls: list[str], workers: int = 10, limit: int = 300) -> dict[str, int]:
    """Controlla lo stato HTTP dei link esterni (0 = irraggiungibile)."""
    s = requests.Session()
    s.headers.update(HEADERS)

    def one(u):
        try:
            r = s.head(u, timeout=12, allow_redirects=True)
            if r.status_code in (403, 405, 400, 501) or r.status_code >= 500:
                r = s.get(u, timeout=15, allow_redirects=True, stream=True)
                r.close()
            return u, r.status_code
        except requests.RequestException:
            return u, 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, urls[:limit]))
