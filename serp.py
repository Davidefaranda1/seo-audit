"""SERP in tempo reale via Serper.dev: posizioni, competitor, quota di visibilità, keyword gap."""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import pandas as pd
import requests

from analysis import STOPWORDS, google_suggest
from crawler import bare_host

SERPER_URL = os.environ.get("SERPER_URL", "https://google.serper.dev/search")

# CTR medio stimato per posizione organica (1..20) — serve per stimare la visibilità
CTR = {1: .28, 2: .15, 3: .11, 4: .08, 5: .06, 6: .045, 7: .035, 8: .03, 9: .025, 10: .02}
CTR.update({p: .01 for p in range(11, 21)})
CTR.update({p: .003 for p in range(21, 51)})

LOCATIONS = {
    "Italia (nazionale)": None,
    "Catania": "Catania, Sicily, Italy",
    "Palermo": "Palermo, Sicily, Italy",
    "Messina": "Messina, Sicily, Italy",
    "Siracusa": "Syracuse, Sicily, Italy",
    "Ragusa": "Ragusa, Sicily, Italy",
    "Roma": "Rome, Lazio, Italy",
    "Milano": "Milan, Lombardy, Italy",
    "Napoli": "Naples, Campania, Italy",
    "Torino": "Turin, Piedmont, Italy",
    "Bologna": "Bologna, Emilia-Romagna, Italy",
    "Firenze": "Florence, Tuscany, Italy",
    "Bari": "Bari, Apulia, Italy",
}

PORTALS = (
    "wikipedia.org", "youtube.com", "facebook.com", "instagram.com", "linkedin.com", "amazon.", "tripadvisor.",
    "paginegialle.it", "paginebianche.it", "tiktok.com", "reddit.com", "pinterest.", "subito.it", "ebay.",
    "trustpilot.", "x.com", "twitter.com", "google.", "quora.com", "booking.com", "indeed.", "glassdoor.",
    "infojobs.it", "yelp.", "virgilio.it", "prontopro.it", "groupon.", "treatwell.", "thefork.", "idealista.",
    "immobiliare.it", "casa.it", "aranzulla.it", "corriere.it", "repubblica.it", "ilsole24ore.com",
)


def domain_of(url: str) -> str:
    return bare_host(urlparse(url or "").netloc)


def same_site(domain: str, my: str) -> bool:
    return domain == my or domain.endswith("." + my)


def is_portal(d: str) -> bool:
    return any(p in d for p in PORTALS)


# ============================================================================ keyword candidate

def _clean_kw(k: str) -> str:
    k = re.sub(r"\s+", " ", (k or "").lower()).strip(" -–|:,.")
    return k


def _good_kw(k: str) -> bool:
    w = k.split()
    if not (2 <= len(w) <= 6) or len(k) > 70:
        return False
    if w[0] in STOPWORDS or w[-1] in STOPWORDS:
        return False
    if re.search(r"[^\w\sàèéìíòóùú'&-]", k):
        return False
    return True


def candidate_keywords(kw_analysis: dict | None, extra: list[str], brand: str = "",
                       expand_with_suggest: bool = True, n_seeds: int = 12, progress=None) -> pd.DataFrame:
    """Lista di keyword da verificare in SERP, con la loro origine."""
    rows: dict[str, dict] = {}

    def add(k, origin, page=""):
        k = _clean_kw(k)
        if k and (_good_kw(k) or origin in ("manuale", "brand")) and k not in rows:
            rows[k] = {"Keyword": k, "Origine": origin, "Pagina del sito": page}

    for k in extra:
        add(k, "manuale")
    if brand:
        add(brand, "brand")
    seeds: list[str] = []
    if kw_analysis and not kw_analysis["per_page"].empty:
        for _, r in kw_analysis["per_page"].iterrows():
            if r["Keyword principale"]:
                add(r["Keyword principale"], "dal sito (principale)", r["URL"])
                seeds.append(_clean_kw(r["Keyword principale"]))
            for s in [x.strip() for x in str(r["Keyword secondarie"]).split(",") if x.strip()][:2]:
                add(s, "dal sito (secondaria)", r["URL"])
        if not kw_analysis["site"].empty:
            for _, r in kw_analysis["site"].iterrows():
                if r.get("Tipo") != "brand/ricorrente":
                    add(r["Keyword"], "dal sito (tema)", r["Pagina più forte"])
    seeds = [s for s in dict.fromkeys(list(extra) + seeds) if _good_kw(_clean_kw(s))][:n_seeds]
    if expand_with_suggest and seeds:
        for i, s in enumerate(seeds, 1):
            try:
                for sug in google_suggest(s):
                    add(sug, f"suggerimento Google ({s})")
            except Exception:  # noqa: BLE001
                pass
            if progress:
                progress(i, len(seeds), s)
            time.sleep(0.1)
    return pd.DataFrame(list(rows.values()), columns=["Keyword", "Origine", "Pagina del sito"])


# ============================================================================ Serper

def serper_search(q: str, api_key: str, location: str | None = None, depth: int = 10) -> dict:
    payload = {"q": q, "gl": "it", "hl": "it", "num": depth}
    if location:
        payload["location"] = location
    last = None
    for attempt in range(3):
        try:
            r = requests.post(SERPER_URL, headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                              json=payload, timeout=40)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise PermissionError("Chiave Serper non valida o crediti esauriti.")
            last = f"HTTP {r.status_code}: {r.text[:150]}"
        except PermissionError:
            raise
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last or "errore Serper")


def parse_serp(data: dict) -> dict:
    organic = []
    for o in data.get("organic", []):
        organic.append({
            "position": int(o.get("position") or len(organic) + 1),
            "link": o.get("link", ""),
            "domain": domain_of(o.get("link", "")),
            "title": o.get("title", ""),
        })
    features = []
    if data.get("answerBox"):
        features.append("Featured snippet")
    if data.get("peopleAlsoAsk"):
        features.append("Le persone chiedono")
    if data.get("places"):
        features.append("Local pack (Maps)")
    if data.get("knowledgeGraph"):
        features.append("Knowledge panel")
    if data.get("videos"):
        features.append("Video")
    if data.get("shopping"):
        features.append("Shopping")
    if data.get("topStories"):
        features.append("Notizie")
    places = [p.get("title", "") for p in data.get("places", [])][:3]
    return {
        "organic": organic,
        "features": features,
        "paa": [x.get("question", "") for x in data.get("peopleAlsoAsk", []) if x.get("question")],
        "related": [x.get("query", "") for x in data.get("relatedSearches", []) if x.get("query")],
        "places": places,
        "credits": data.get("credits"),
    }


def run_serp(keywords: list[str], api_key: str, location: str | None, depth: int,
             workers: int = 6, progress=None) -> tuple[dict, list[str]]:
    results, errors = {}, []

    def one(k):
        try:
            return k, parse_serp(serper_search(k, api_key, location, depth)), None
        except PermissionError as e:
            return k, None, str(e)
        except Exception as e:  # noqa: BLE001
            return k, None, f"{k}: {e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for k, res, err in pool.map(one, keywords):
            done += 1
            if res is not None:
                results[k] = res
            elif err:
                errors.append(err)
                if "non valida" in err:
                    break
            if progress:
                progress(done, len(keywords), k)
    return results, errors


# ============================================================================ analisi

def _ctr(p):
    return CTR.get(p, 0.0) if p else 0.0


def rankings(serp: dict, my: str) -> pd.DataFrame:
    rows = []
    for k, r in serp.items():
        mine = [o for o in r["organic"] if same_site(o["domain"], my)]
        best = mine[0] if mine else None
        top = r["organic"][0] if r["organic"] else {}
        rows.append({
            "Keyword": k,
            "Posizione": best["position"] if best else None,
            "URL posizionato": best["link"] if best else "",
            "Più URL tuoi": len(mine) > 1,
            "1° risultato": top.get("domain", ""),
            "Elementi SERP": ", ".join(r["features"]),
            "Local pack": ", ".join(r.get("places", [])),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["Posizione"] = df["Posizione"].astype("Int64")
    return df.sort_values("Posizione", na_position="last").reset_index(drop=True)


def bucket(p) -> str:
    if p is None or pd.isna(p):
        return "Non posizionato"
    p = int(p)
    if p <= 3:
        return "Top 3"
    if p <= 10:
        return "4-10"
    if p <= 20:
        return "11-20"
    if p <= 50:
        return "21-50"
    return "51-100"


BUCKET_ORDER = ["Top 3", "4-10", "11-20", "21-50", "51-100", "Non posizionato"]


def domain_positions(serp: dict) -> dict[str, dict[str, int]]:
    """dominio -> {keyword: miglior posizione}"""
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for k, r in serp.items():
        for o in r["organic"]:
            d = o["domain"]
            if d and (k not in out[d] or o["position"] < out[d][k]):
                out[d][k] = o["position"]
    return out


def competitors(serp: dict, my: str, top_n: int = 50) -> pd.DataFrame:
    dp = domain_positions(serp)
    N = max(1, len(serp))
    mine = {k: p for d, kp in dp.items() if same_site(d, my) for k, p in kp.items()}
    rows = []
    for d, kp in dp.items():
        if same_site(d, my):
            continue
        top10 = {k: p for k, p in kp.items() if p <= 10}
        if not top10:
            continue
        common = [k for k in kp if k in mine]
        beats = sum(1 for k, p in kp.items() if p <= 10 and (k not in mine or p < mine[k]))
        rows.append({
            "Dominio": d,
            "Visibilità %": round(100 * sum(_ctr(p) for p in kp.values()) / (N * CTR[1]), 2),
            "Keyword in top 10": len(top10),
            "Keyword in top 3": sum(1 for p in kp.values() if p <= 3),
            "Posizione media": round(sum(top10.values()) / len(top10), 1),
            "Keyword in comune con te": len(common),
            "Ti supera su": beats,
            "Tipo": "Portale/social" if is_portal(d) else "Competitor",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["Visibilità %", "Keyword in top 10"], ascending=False).head(top_n).reset_index(drop=True)


def my_visibility(serp: dict, my: str) -> float:
    N = max(1, len(serp))
    best = {}
    for k, r in serp.items():
        for o in r["organic"]:
            if same_site(o["domain"], my):
                best[k] = min(best.get(k, 999), o["position"])
    return round(100 * sum(_ctr(p) for p in best.values()) / (N * CTR[1]), 2)


def head_to_head(serp: dict, my: str, comp: str) -> pd.DataFrame:
    dp = domain_positions(serp)
    mine = {k: p for d, kp in dp.items() if same_site(d, my) for k, p in kp.items()}
    theirs = dp.get(comp, {})
    rows = []
    for k in serp:
        a, b = mine.get(k), theirs.get(k)
        if a is None and b is None:
            continue
        if a is not None and (b is None or a < b):
            esito = "Vinci tu"
        elif b is not None and (a is None or b < a):
            esito = "Vince lui"
        else:
            esito = "Pari"
        url_b = next((o["link"] for o in serp[k]["organic"] if o["domain"] == comp), "")
        rows.append({"Keyword": k, "Tua posizione": a, f"Posizione {comp}": b, "Esito": esito, f"URL {comp}": url_b})
    df = pd.DataFrame(rows)
    if not df.empty:
        for c in ("Tua posizione", f"Posizione {comp}"):
            df[c] = df[c].astype("Int64")
    return df


def keyword_gap(serp: dict, my: str, comps: list[str] | None = None) -> pd.DataFrame:
    """Keyword dove almeno un competitor è in top 10 e tu sei fuori dalla top 10."""
    rows = []
    for k, r in serp.items():
        mine = min((o["position"] for o in r["organic"] if same_site(o["domain"], my)), default=None)
        if mine is not None and mine <= 10:
            continue
        rivals = [o for o in r["organic"] if o["position"] <= 10 and not same_site(o["domain"], my)
                  and not is_portal(o["domain"]) and (comps is None or o["domain"] in comps)]
        if not rivals:
            continue
        rows.append({
            "Keyword": k,
            "Tua posizione": mine,
            "Competitor in top 10": len(rivals),
            "Chi c'è": ", ".join(f"{o['domain']} ({o['position']})" for o in rivals[:4]),
            "Pagina da battere": rivals[0]["link"],
            "Elementi SERP": ", ".join(r["features"]),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Tua posizione"] = df["Tua posizione"].astype("Int64")
        df = df.sort_values(["Competitor in top 10", "Tua posizione"], ascending=[False, True], na_position="last")
    return df.reset_index(drop=True)


def quick_wins(rank_df: pd.DataFrame) -> pd.DataFrame:
    """Keyword in posizione 4-20: piccoli miglioramenti, grande resa."""
    if rank_df.empty:
        return rank_df
    m = rank_df["Posizione"].notna() & rank_df["Posizione"].between(4, 20)
    return rank_df[m].sort_values("Posizione").reset_index(drop=True)


def new_ideas(serp: dict) -> pd.DataFrame:
    rows, seen = [], set(serp)
    for k, r in serp.items():
        for q in r.get("paa", []):
            if q.lower() not in seen:
                seen.add(q.lower())
                rows.append({"Idea": q, "Tipo": "Domanda (Le persone chiedono)", "Da keyword": k})
        for q in r.get("related", []):
            if q.lower() not in seen:
                seen.add(q.lower())
                rows.append({"Idea": q, "Tipo": "Ricerca correlata", "Da keyword": k})
    return pd.DataFrame(rows)


def cannibalization(serp: dict, my: str) -> pd.DataFrame:
    rows = []
    for k, r in serp.items():
        mine = [o for o in r["organic"] if same_site(o["domain"], my)]
        if len(mine) > 1:
            rows.append({"Keyword": k, "URL in concorrenza": "\n".join(f"{o['position']}. {o['link']}" for o in mine)})
    return pd.DataFrame(rows)
