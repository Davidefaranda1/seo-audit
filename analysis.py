"""Analisi SEO: problemi tecnici, punteggio, keyword, cannibalizzazioni, competitor, PageSpeed, export."""
from __future__ import annotations

import io
import json
import math
import re
import time
from collections import Counter, defaultdict
from urllib.parse import urlparse

import pandas as pd
import requests

from crawler import HEADERS, Page, bare_host

# ============================================================================ PROBLEMI

ISSUES = {
    # codice: (gravità, descrizione, come risolvere)
    "http_error": ("Critico", "Pagina in errore (4xx/5xx)", "Ripristina la pagina o imposta un redirect 301 verso una pagina pertinente; rimuovi i link interni che puntano qui."),
    "unreachable": ("Critico", "Pagina irraggiungibile (timeout/errore connessione)", "Verifica server, firewall e tempi di risposta."),
    "no_https": ("Critico", "Pagina non in HTTPS", "Installa il certificato SSL e reindirizza tutto l'HTTP verso HTTPS."),
    "no_title": ("Critico", "Title mancante", "Scrivi un title unico con la keyword principale (50-60 caratteri)."),
    "redirect": ("Avviso", "URL interno che fa redirect", "Aggiorna i link interni puntando direttamente all'URL finale."),
    "dup_title": ("Avviso", "Title duplicato", "Rendi ogni title unico: due pagine con lo stesso title si fanno concorrenza."),
    "title_long": ("Avviso", "Title troppo lungo (>60 caratteri)", "Accorcia: Google tronca oltre ~580px (circa 60 caratteri)."),
    "title_short": ("Avviso", "Title troppo corto (<30 caratteri)", "Allunga includendo keyword e beneficio/brand."),
    "no_meta": ("Avviso", "Meta description mancante", "Scrivi una description persuasiva di 120-155 caratteri con la keyword."),
    "dup_meta": ("Avviso", "Meta description duplicata", "Scrivi description uniche per ogni pagina."),
    "no_h1": ("Avviso", "H1 mancante", "Aggiungi un H1 che descriva il contenuto con la keyword principale."),
    "thin": ("Avviso", "Contenuto scarso (<300 parole)", "Arricchisci il testo o accorpa la pagina ad altre simili."),
    "orphan": ("Avviso", "Pagina orfana (in sitemap ma senza link interni)", "Aggiungi link interni da pagine correlate o dal menu."),
    "no_viewport": ("Avviso", "Meta viewport mancante (non mobile-friendly)", "Aggiungi <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">."),
    "noindex_sitemap": ("Avviso", "Pagina noindex presente in sitemap", "Togli la pagina dalla sitemap o rimuovi il noindex se deve posizionarsi."),
    "slow": ("Avviso", "Risposta lenta del server (>1,5 s)", "Attiva cache, ottimizza hosting/database, usa un CDN."),
    "multi_h1": ("Info", "Più di un H1", "Meglio un solo H1 per pagina; gli altri trasformali in H2."),
    "meta_long": ("Info", "Meta description lunga (>160 caratteri)", "Accorcia a 120-155 caratteri per evitare il troncamento."),
    "meta_short": ("Info", "Meta description corta (<70 caratteri)", "Allunga con beneficio e call to action."),
    "noindex": ("Info", "Pagina in noindex", "Verifica che sia voluto: non comparirà su Google."),
    "canonical_other": ("Info", "Canonical verso altro URL", "Verifica che il canonical sia corretto."),
    "img_alt": ("Info", "Immagini senza attributo alt", "Aggiungi testi alternativi descrittivi alle immagini."),
    "deep": ("Info", "Pagina profonda (>3 clic dalla home)", "Avvicinala alla home con link da menu, categorie o pagine forti."),
    "no_lang": ("Info", "Attributo lang mancante", "Aggiungi <html lang=\"it\">."),
    "no_schema": ("Info", "Nessun dato strutturato (schema.org)", "Aggiungi schema adatti (Organization, LocalBusiness, Product, Article, FAQ…)."),
    "no_og": ("Info", "Tag Open Graph mancanti", "Aggiungi og:title, og:description, og:image per le condivisioni social."),
    "few_inlinks": ("Info", "Solo 1 link interno in entrata", "Rafforza la pagina con altri link interni contestuali."),
}
SEVERITY_ORDER = {"Critico": 0, "Avviso": 1, "Info": 2}
SEVERITY_WEIGHT = {"Critico": 30, "Avviso": 12, "Info": 3}


def pages_dataframe(crawl: dict) -> pd.DataFrame:
    inl = crawl["inlinks"]
    rows = []
    for p in crawl["pages"]:
        rows.append({
            "URL": p.url,
            "Stato": p.status if p.status else (p.error or "errore"),
            "Indicizzabile": "Sì" if p.indexable else "No",
            "Title": p.title,
            "Lung. title": len(p.title),
            "Meta description": p.meta_description,
            "Lung. meta": len(p.meta_description),
            "H1": " | ".join(p.h1),
            "N. H1": len(p.h1),
            "N. H2": len(p.h2),
            "Parole": p.word_count,
            "Profondità": p.depth if p.depth is not None else "solo sitemap",
            "Link in entrata": len(inl.get(p.url, [])),
            "Link interni in uscita": len(p.internal_links),
            "Link esterni": len(p.external_links),
            "Immagini": p.images,
            "Img senza alt": p.images_no_alt,
            "Schema": ", ".join(p.schema_types),
            "Canonical": p.canonical,
            "Robots": " ".join(x for x in (p.meta_robots, p.x_robots) if x),
            "In sitemap": "Sì" if p.in_sitemap else "No",
            "Tempo (ms)": p.response_ms,
            "Peso (KB)": p.size_kb,
            "Redirect verso": p.redirect_to,
            "Lang": p.lang,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        for col in ("Stato", "Profondità"):
            df[col] = df[col].astype(str)
    return df


def find_issues(crawl: dict) -> pd.DataFrame:
    pages: list[Page] = crawl["pages"]
    inl = crawl["inlinks"]
    html_ok = [p for p in pages if p.status == 200 and p.is_html]
    out = []

    def add(code, p, detail=""):
        sev, label, fix = ISSUES[code]
        sources = inl.get(p.url, [])
        out.append({
            "Gravità": sev, "Problema": label, "URL": p.url, "Dettaglio": detail,
            "Linkata da": ", ".join(sources[:3]) + (f" (+{len(sources) - 3})" if len(sources) > 3 else ""),
            "Come risolvere": fix, "_code": code,
        })

    titles = Counter(p.title.strip().lower() for p in html_ok if p.indexable and p.title.strip())
    metas = Counter(p.meta_description.strip().lower() for p in html_ok if p.indexable and p.meta_description.strip())

    for p in pages:
        if p.error and not p.status:
            add("unreachable", p, p.error)
            continue
        if p.status >= 400:
            add("http_error", p, f"HTTP {p.status}")
            continue
        if 300 <= p.status < 400:
            if inl.get(p.url):
                add("redirect", p, f"{p.status} → {p.redirect_to}")
            continue
        if p.url.startswith("http://"):
            add("no_https", p)
        if not (p.status == 200 and p.is_html):
            continue
        if p.noindex:
            add("noindex_sitemap" if p.in_sitemap else "noindex", p, p.meta_robots or p.x_robots)
        if p.canonical_other:
            add("canonical_other", p, p.canonical)
        if p.response_ms > 1500:
            add("slow", p, f"{p.response_ms} ms")
        if not p.has_viewport:
            add("no_viewport", p)
        if p.depth is None and p.in_sitemap and not inl.get(p.url):
            add("orphan", p)
        if not p.indexable:
            continue  # i controlli on-page servono solo per le pagine che devono posizionarsi
        t = p.title.strip()
        if not t:
            add("no_title", p)
        else:
            if titles[t.lower()] > 1:
                add("dup_title", p, f"{titles[t.lower()]} pagine: «{t[:80]}»")
            if len(t) > 60:
                add("title_long", p, f"{len(t)} caratteri")
            elif len(t) < 30:
                add("title_short", p, f"{len(t)} caratteri: «{t}»")
        m = p.meta_description.strip()
        if not m:
            add("no_meta", p)
        else:
            if metas[m.lower()] > 1:
                add("dup_meta", p, f"{metas[m.lower()]} pagine")
            if len(m) > 160:
                add("meta_long", p, f"{len(m)} caratteri")
            elif len(m) < 70:
                add("meta_short", p, f"{len(m)} caratteri")
        if not p.h1:
            add("no_h1", p)
        elif len(p.h1) > 1:
            add("multi_h1", p, f"{len(p.h1)} H1")
        if p.word_count < 300:
            add("thin", p, f"{p.word_count} parole")
        if p.images_no_alt:
            add("img_alt", p, f"{p.images_no_alt} su {p.images}")
        if p.depth is not None and p.depth > 3:
            add("deep", p, f"{p.depth} clic")
        if not p.lang:
            add("no_lang", p)
        if not p.schema_types:
            add("no_schema", p)
        if not p.has_og:
            add("no_og", p)
        if p.depth not in (None, 0) and len(inl.get(p.url, [])) == 1:
            add("few_inlinks", p)

    df = pd.DataFrame(out, columns=["Gravità", "Problema", "URL", "Dettaglio", "Linkata da", "Come risolvere", "_code"])
    if not df.empty:
        df["_o"] = df["Gravità"].map(SEVERITY_ORDER)
        df = df.sort_values(["_o", "Problema", "URL"]).drop(columns="_o").reset_index(drop=True)
    return df


def issues_summary(issues: pd.DataFrame) -> pd.DataFrame:
    if issues.empty:
        return pd.DataFrame(columns=["Gravità", "Problema", "Pagine", "Come risolvere"])
    g = issues.groupby(["Gravità", "Problema", "Come risolvere"]).size().reset_index(name="Pagine")
    g["_o"] = g["Gravità"].map(SEVERITY_ORDER)
    return g.sort_values(["_o", "Pagine"], ascending=[True, False]).drop(columns="_o")[["Gravità", "Problema", "Pagine", "Come risolvere"]]


def health_score(crawl: dict, issues: pd.DataFrame) -> int:
    n = max(1, sum(1 for p in crawl["pages"] if p.status))
    if issues.empty:
        return 100
    penalty = 0.0
    for (sev, _code), grp in issues.groupby(["Gravità", "_code"]):
        share = grp["URL"].nunique() / n
        penalty += SEVERITY_WEIGHT[sev] * math.sqrt(min(1.0, share))
    return max(0, round(100 - penalty * 0.6))


# ============================================================================ KEYWORD

STOP_IT = """a ad al allo ai agli all agl alla alle con col coi da dal dallo dai dagli dall dagl dalla dalle di del dello dei
degli dell degl della delle in nel nello nei negli nell negl nella nelle su sul sullo sui sugli sull sugl sulla sulle per tra
fra il lo la i gli le l un uno una un' e ed o od ma se che chi cui non più piu quale quali quanto quanta quanti quante quello
quella quelli quelle questo questa questi queste quest quell si sì no anche come dove quando perché perche poi già gia ancora
molto molti molta molte poco tutto tutti tutta tutte ogni altro altri altra altre stesso stessa essere è e' sono sei siamo siete
era erano sarà sara saranno stato stata stati state ha hanno ho hai abbiamo avete aveva avere fare fa fatto può puo possono
mio mia miei mie tuo tua tuoi tue suo sua suoi sue nostro nostra nostri nostre vostro vostra loro lui lei noi voi io tu
ci vi ne mi ti c d s m t n qui qua là lì li cosa cose ecc etc oppure ovvero sia invece circa verso senza sopra sotto dopo prima
mentre durante oltre presso contro secondo tramite via ora oggi sempre mai solo solamente proprio così cosi tanto tanta
tanti tante nostro nostra scopri leggi clicca qui home pagina menu cookie privacy policy contatti accedi login carrello""".split()
STOP_EN = """the a an and or but if of to in on at by for with from as is are was were be been being it its this that these
those you your we our they their he she his her them i me my not no yes do does did have has had will would can could should
about into over under more most other some such than too very just also how what when where which who why all any each few
read more click here home page cookie cookies privacy policy terms login cart""".split()
STOPWORDS = set(STOP_IT) | set(STOP_EN)

TOKEN_RE = re.compile(r"[a-zà-öø-ÿ0-9]+", re.I)
SPLIT_RE = re.compile(r"[.!?;:|•·»«\"“”()\[\]{}\n\r\t–—/\\,]+")
FIELD_WEIGHTS = {"title": 3.0, "h1": 3.0, "h2": 1.6, "meta": 1.4, "body": 1.0}


def _ngrams_from_text(text: str, nmax: int = 4) -> Counter:
    c: Counter = Counter()
    for seg in SPLIT_RE.split(text.lower().replace("’", " ").replace("'", " ")):
        toks = TOKEN_RE.findall(seg)
        L = len(toks)
        for i in range(L):
            for n in range(1, nmax + 1):
                if i + n > L:
                    break
                gram = toks[i:i + n]
                first, last = gram[0], gram[-1]
                if first in STOPWORDS or last in STOPWORDS:
                    continue
                if any(t.isdigit() for t in gram):
                    continue
                if n == 1 and len(first) < 4:
                    continue
                if any(len(t) > 25 for t in gram):
                    continue
                c[" ".join(gram)] += 1
    return c


def page_terms(p: Page) -> Counter:
    total: Counter = Counter()
    fields = {
        "title": p.title, "h1": " . ".join(p.h1), "h2": " . ".join(p.h2),
        "meta": p.meta_description, "body": p.text,
    }
    for f, txt in fields.items():
        if not txt:
            continue
        for g, cnt in _ngrams_from_text(txt).items():
            total[g] += cnt * FIELD_WEIGHTS[f]
    return _drop_fragments(total)


def _drop_fragments(c: Counter) -> Counter:
    """Toglie i frammenti: 'digital' se compare quasi sempre dentro 'digital marketing'."""
    longer = defaultdict(float)
    for g, w in c.items():
        toks = g.split()
        if len(toks) < 2:
            continue
        # sotto-sequenze ottenute togliendo la prima o l'ultima parola
        for sub in (" ".join(toks[1:]), " ".join(toks[:-1])):
            if sub in c:
                longer[sub] = max(longer[sub], w)
    return Counter({g: w for g, w in c.items() if longer.get(g, 0) < 0.8 * w})


def _overlaps(g: str, picked: list[str]) -> bool:
    gs = set(g.split()) - STOPWORDS
    for x in picked:
        if g in x or x in g:
            return True
        xs = set(x.split()) - STOPWORDS
        if len(gs & xs) >= 2 and len(gs & xs) >= min(len(gs), len(xs)) - 1:
            return True
    return False


def keyword_analysis(crawl: dict, top_n: int = 150) -> dict:
    pages = [p for p in crawl["pages"] if p.indexable]
    N = len(pages)
    if not N:
        empty = pd.DataFrame()
        return {"site": empty, "per_page": empty, "cannibal": empty, "vocab": set()}
    terms = {p.url: page_terms(p) for p in pages}
    titles = {p.url: (p.title + " " + " ".join(p.h1)).lower() for p in pages}
    df_count: Counter = Counter()
    tf_total: Counter = Counter()
    for t in terms.values():
        for g, w in t.items():
            df_count[g] += 1
            tf_total[g] += w

    def idf(g):
        return math.log(1 + N / df_count[g])

    # keyword per pagina
    per_page_rows, top_by_page = [], {}
    for p in pages:
        t = terms[p.url]
        scored = []
        for g, w in t.items():
            n_words = g.count(" ") + 1
            if w < 2 and g not in titles[p.url]:
                continue
            boiler = N >= 5 and df_count[g] / N > 0.6
            if boiler:
                continue
            s = (1 + math.log(w)) * idf(g) * (1 + 0.35 * (n_words - 1))
            if g in titles[p.url]:
                s *= 1.8
            scored.append((s, g))
        scored.sort(reverse=True)
        picked = []
        for s, g in scored:
            if _overlaps(g, picked):
                continue
            picked.append(g)
            if len(picked) == 6:
                break
        top_by_page[p.url] = picked
        per_page_rows.append({
            "URL": p.url,
            "Title": p.title,
            "Keyword principale": picked[0] if picked else "",
            "Keyword secondarie": ", ".join(picked[1:]),
            "Keyword nel title": "Sì" if picked and picked[0] in p.title.lower() else "No",
            "Keyword nell'H1": "Sì" if picked and any(picked[0] in h.lower() for h in p.h1) else "No",
            "Keyword nella meta": "Sì" if picked and picked[0] in p.meta_description.lower() else "No",
        })

    # keyword del sito
    site_rows = []
    for g, w in tf_total.items():
        n_words = g.count(" ") + 1
        if w < 3:
            continue
        in_title_pages = sum(1 for u in titles if g in titles[u])
        score = (1 + math.log(w)) * (1 + 0.4 * (n_words - 1)) * (1 + in_title_pages)
        if n_words == 1:
            score *= 0.6
        site_rows.append((score, g, w, df_count[g], in_title_pages))
    site_rows.sort(reverse=True)
    chosen, site = [], []
    for score, g, w, dfc, tp in site_rows:
        if _overlaps(g, chosen):
            continue
        chosen.append(g)
        best = max(pages, key=lambda p: terms[p.url].get(g, 0))
        site.append({
            "Keyword": g, "Parole": g.count(" ") + 1, "Rilevanza": round(score, 1),
            "Pagine che la usano": dfc, "In title/H1 di": tp,
            "Pagina più forte": best.url,
            "Tipo": "brand/ricorrente" if N >= 5 and dfc / N > 0.6 else "",
        })
        if len(site) >= top_n:
            break

    # cannibalizzazioni: stessa keyword (2+ parole) tra le prime 3 di più pagine
    owner = defaultdict(list)
    for u, kws in top_by_page.items():
        for g in kws[:3]:
            if " " in g:
                owner[g].append(u)
    cannibal = [
        {"Keyword": g, "N. pagine": len(us), "Pagine in concorrenza": "\n".join(us),
         "Suggerimento": "Scegli una pagina principale per questa keyword: differenzia le altre (title/H1/contenuto) o accorpale con redirect 301 e link interni verso la principale."}
        for g, us in owner.items() if len(us) > 1
    ]
    cannibal.sort(key=lambda r: -r["N. pagine"])
    return {
        "site": pd.DataFrame(site),
        "per_page": pd.DataFrame(per_page_rows),
        "cannibal": pd.DataFrame(cannibal),
        "vocab": set(tf_total.keys()),
        "tf_total": tf_total,
    }


def keyword_gap(mine: dict, theirs: dict, top_n: int = 150) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keyword che il competitor tratta e tu no / che trattate entrambi."""
    if theirs["site"].empty:
        return pd.DataFrame(), pd.DataFrame()
    my_vocab = mine.get("vocab", set())
    gap, shared = [], []
    for _, r in theirs["site"].head(top_n).iterrows():
        kw = r["Keyword"]
        row = {"Keyword": kw, "Rilevanza nel competitor": r["Rilevanza"], "Pagina competitor": r["Pagina più forte"]}
        if kw in my_vocab:
            row["Menzioni sul tuo sito"] = round(mine["tf_total"].get(kw, 0), 1)
            shared.append(row)
        else:
            gap.append(row)
    return pd.DataFrame(gap), pd.DataFrame(shared)


# ============================================================================ FONTI ESTERNE

def google_suggest(q: str, hl: str = "it", gl: str = "it") -> list[str]:
    r = requests.get(
        "https://suggestqueries.google.com/complete/search",
        params={"client": "firefox", "hl": hl, "gl": gl, "q": q},
        headers=HEADERS, timeout=10,
    )
    raw = r.content
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("latin-1")
    data = json.loads(txt)
    return [s for s in data[1] if isinstance(s, str)]


SUGGEST_PATTERNS = ["{kw}", "{kw} ", "come {kw}", "{kw} per", "{kw} migliore", "{kw} prezzi", "{kw} vicino a me"]


def keyword_ideas(seeds: list[str], hl="it", gl="it", progress=None) -> pd.DataFrame:
    rows, seen = [], set()
    total = len(seeds) * len(SUGGEST_PATTERNS)
    i = 0
    for seed in seeds:
        for pat in SUGGEST_PATTERNS:
            i += 1
            q = pat.format(kw=seed)
            try:
                sugg = google_suggest(q, hl, gl)
            except Exception:  # noqa: BLE001
                sugg = []
            for s in sugg:
                s = s.strip().lower()
                if s and s not in seen:
                    seen.add(s)
                    rows.append({"Idea keyword": s, "Da seed": seed, "Tipo": "domanda" if re.match(r"^(come|cosa|perch|quanto|quando|dove|chi|qual)", s) else "correlata"})
            if progress:
                progress(i, total, q)
            time.sleep(0.15)
    return pd.DataFrame(rows)


# -- DataForSEO (volumi Google Ads + SERP) -------------------------------------------------

def dataforseo_volumes(keywords: list[str], login: str, password: str, location_code: int = 2380, language_code: str = "it") -> pd.DataFrame:
    kws = [k for k in dict.fromkeys(keywords) if 0 < len(k) <= 80 and len(k.split()) <= 10][:1000]
    if not kws:
        return pd.DataFrame()
    r = requests.post(
        "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
        auth=(login, password),
        json=[{"keywords": kws, "location_code": location_code, "language_code": language_code}],
        timeout=180,
    )
    data = r.json()
    task = (data.get("tasks") or [{}])[0]
    if task.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO: {task.get('status_message') or data.get('status_message')}")
    rows = []
    for it in task.get("result") or []:
        rows.append({
            "Keyword": it.get("keyword"),
            "Volume mensile": it.get("search_volume"),
            "Concorrenza": it.get("competition"),
            "CPC (€)": it.get("cpc"),
        })
    return pd.DataFrame(rows)


def dataforseo_serp(q: str, login: str, password: str, location_code: int = 2380, language_code: str = "it") -> list[dict]:
    r = requests.post(
        "https://api.dataforseo.com/v3/serp/google/organic/live/regular",
        auth=(login, password),
        json=[{"keyword": q, "location_code": location_code, "language_code": language_code, "depth": 10}],
        timeout=90,
    )
    data = r.json()
    task = (data.get("tasks") or [{}])[0]
    if task.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO: {task.get('status_message')}")
    items = ((task.get("result") or [{}])[0] or {}).get("items") or []
    return [
        {"position": it.get("rank_group"), "link": it.get("url"), "title": it.get("title")}
        for it in items if it.get("type") == "organic"
    ]


# -- Serper.dev (SERP Google) --------------------------------------------------------------

def serper_serp(q: str, api_key: str, gl: str = "it", hl: str = "it") -> tuple[list[dict], list[str]]:
    r = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": q, "gl": gl, "hl": hl, "num": 10},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Serper: HTTP {r.status_code} {r.text[:200]}")
    data = r.json()
    organic = [{"position": o.get("position"), "link": o.get("link"), "title": o.get("title")} for o in data.get("organic", [])]
    extra = [x.get("query", "") for x in data.get("relatedSearches", [])] + [x.get("question", "") for x in data.get("peopleAlsoAsk", [])]
    return organic, [e for e in extra if e]


PORTALS = {
    "wikipedia.org", "youtube.com", "facebook.com", "instagram.com", "linkedin.com", "amazon.it", "amazon.com",
    "tripadvisor.it", "paginegialle.it", "paginebianche.it", "tiktok.com", "reddit.com", "pinterest.it", "pinterest.com",
    "subito.it", "ebay.it", "trustpilot.com", "x.com", "twitter.com", "google.com", "quora.com", "booking.com",
}


def _domain(url: str) -> str:
    return bare_host(urlparse(url).netloc)


def _is_portal(d: str) -> bool:
    return any(d == p or d.endswith("." + p) or d.endswith(p) for p in PORTALS)


def competitor_analysis(keywords: list[str], my_host: str, provider: str, creds: dict, progress=None) -> dict:
    serp_rows, rank_rows, related = [], [], []
    for i, kw in enumerate(keywords, 1):
        try:
            if provider == "serper":
                organic, extra = serper_serp(kw, creds["serper_key"])
                related.extend((kw, e) for e in extra)
            else:
                organic = dataforseo_serp(kw, creds["dfs_login"], creds["dfs_password"])
        except Exception as e:  # noqa: BLE001
            rank_rows.append({"Keyword": kw, "Tua posizione": "errore", "Tuo URL": str(e)[:120], "Primo risultato": ""})
            continue
        mine = next((o for o in organic if _domain(o["link"] or "") == my_host), None)
        rank_rows.append({
            "Keyword": kw,
            "Tua posizione": str(mine["position"]) if mine else "oltre 10",
            "Tuo URL": mine["link"] if mine else "",
            "Primo risultato": organic[0]["link"] if organic else "",
        })
        for o in organic:
            d = _domain(o["link"] or "")
            if d and d != my_host:
                serp_rows.append({"Dominio": d, "Keyword": kw, "Posizione": o["position"], "URL": o["link"], "Title": o["title"]})
        if progress:
            progress(i, len(keywords), kw)
    serp = pd.DataFrame(serp_rows)
    comp = pd.DataFrame()
    if not serp.empty:
        g = serp.groupby("Dominio")
        comp = pd.DataFrame({
            "Keyword in comune": g["Keyword"].nunique(),
            "Posizione media": g["Posizione"].mean().round(1),
            "Visibilità": g["Posizione"].apply(lambda s: round(sum(11 - min(10, x or 10) for x in s), 0)),
            "Esempi keyword": g["Keyword"].apply(lambda s: ", ".join(list(dict.fromkeys(s))[:5])),
        }).reset_index()
        comp["Tipo"] = comp["Dominio"].apply(lambda d: "portale/social" if _is_portal(d) else "competitor")
        comp = comp.sort_values(["Visibilità", "Keyword in comune"], ascending=False).reset_index(drop=True)
    rel = pd.DataFrame(related, columns=["Da keyword", "Ricerca correlata / domanda"]).drop_duplicates() if related else pd.DataFrame()
    return {"competitors": comp, "rankings": pd.DataFrame(rank_rows), "serp": serp, "related": rel}


# -- PageSpeed Insights --------------------------------------------------------------------

def pagespeed(url: str, strategy: str = "mobile", api_key: str | None = None) -> dict:
    params = [("url", url), ("strategy", strategy)] + [("category", c) for c in ("performance", "seo", "accessibility", "best-practices")]
    if api_key:
        params.append(("key", api_key))
    r = requests.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params=params, timeout=120)
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "errore PageSpeed"))
    lh = data.get("lighthouseResult", {})
    cats = lh.get("categories", {})
    audits = lh.get("audits", {})
    field = (data.get("loadingExperience") or {}).get("metrics", {})

    def fv(k):
        m = field.get(k)
        return f"{m.get('percentile')} ({m.get('category', '').lower()})" if m else "n.d."

    opps = []
    for a in audits.values():
        det = a.get("details") or {}
        if det.get("type") == "opportunity" and (a.get("score") is not None and a["score"] < 0.9):
            opps.append({"Ottimizzazione": a.get("title"), "Risparmio stimato": a.get("displayValue", "")})
    return {
        "URL": url,
        "Dispositivo": strategy,
        "Performance": round((cats.get("performance", {}).get("score") or 0) * 100),
        "SEO": round((cats.get("seo", {}).get("score") or 0) * 100),
        "Accessibilità": round((cats.get("accessibility", {}).get("score") or 0) * 100),
        "Best practice": round((cats.get("best-practices", {}).get("score") or 0) * 100),
        "LCP (lab)": audits.get("largest-contentful-paint", {}).get("displayValue", ""),
        "CLS (lab)": audits.get("cumulative-layout-shift", {}).get("displayValue", ""),
        "TBT (lab)": audits.get("total-blocking-time", {}).get("displayValue", ""),
        "LCP utenti reali (ms)": fv("LARGEST_CONTENTFUL_PAINT_MS"),
        "INP utenti reali (ms)": fv("INTERACTION_TO_NEXT_PAINT"),
        "CLS utenti reali": fv("CUMULATIVE_LAYOUT_SHIFT_SCORE"),
        "_opps": opps,
    }


# ============================================================================ EXPORT

def to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            if df is None or df.empty:
                continue
            d = df.drop(columns=[c for c in df.columns if str(c).startswith("_")], errors="ignore")
            d.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for i, col in enumerate(d.columns, 1):
                width = min(60, max(10, int(d[col].astype(str).str.len().quantile(0.9) if len(d) else 10), len(str(col)) + 2))
                ws.column_dimensions[ws.cell(1, i).column_letter].width = width
    return buf.getvalue()
