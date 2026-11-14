"""SEO Audit personale — interfaccia web (Streamlit).

Avvio locale:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import hmac
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

import analysis as an
from crawler import Crawler, check_external_links

st.set_page_config(page_title="SEO Audit", page_icon="🔎", layout="wide")


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # noqa: BLE001  (nessun secrets.toml)
        return default


# ----------------------------------------------------------------------------- accesso
def check_password() -> bool:
    pwd = secret("APP_PASSWORD")
    if not pwd:
        st.sidebar.warning("Nessuna password impostata (APP_PASSWORD): l'app è aperta a chiunque abbia il link.")
        return True
    if st.session_state.get("auth_ok"):
        return True
    st.title("🔎 SEO Audit")
    p = st.text_input("Password", type="password")
    if p:
        if hmac.compare_digest(p, pwd):
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Password errata")
    return False


if not check_password():
    st.stop()

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Impostazioni scansione")
    max_pages = st.slider("Pagine massime", 10, 3000, 500, step=10)
    workers = st.slider("Richieste in parallelo", 1, 16, 6, help="Più alto = più veloce, ma pesa di più sul sito.")
    respect_robots = st.checkbox("Rispetta robots.txt", True)
    ignore_query = st.checkbox("Ignora URL con parametri (?…)", True)
    use_sitemap = st.checkbox("Leggi la sitemap (trova pagine orfane)", True)
    check_ext = st.checkbox("Controlla link esterni rotti (più lento)", False)

    st.header("Chiavi API (facoltative)")
    serper_key = st.text_input("Serper.dev API key", secret("SERPER_API_KEY"), type="password",
                               help="Per competitor e posizionamenti su Google. serper.dev ha crediti gratuiti iniziali.")
    dfs_login = st.text_input("DataForSEO login", secret("DATAFORSEO_LOGIN"))
    dfs_pwd = st.text_input("DataForSEO password API", secret("DATAFORSEO_PASSWORD"), type="password",
                            help="Per volumi di ricerca (dati Google Ads) e, in alternativa a Serper, SERP.")
    psi_key = st.text_input("PageSpeed API key", secret("PAGESPEED_API_KEY"), type="password",
                            help="Facoltativa: senza chiave funziona ma con limiti più bassi.")

st.title("🔎 SEO Audit — analisi completa del sito")
c1, c2 = st.columns([4, 1])
url = c1.text_input("URL del sito", placeholder="https://www.esempio.it", label_visibility="collapsed")
go = c2.button("Analizza sito", type="primary", width="stretch")


# ----------------------------------------------------------------------------- scansione
def run_crawl(u: str, limit: int) -> dict:
    bar = st.progress(0.0, text="Avvio…")

    def prog(done, total, msg):
        bar.progress(min(1.0, done / max(1, total)), text=f"{done} pagine · {msg[:90]}")

    data = Crawler(u, max_pages=limit, workers=workers, respect_robots=respect_robots,
                   ignore_query=ignore_query, use_sitemap=use_sitemap, progress=prog).run()
    bar.progress(1.0, text=f"Scansione completata: {len(data['pages'])} URL")
    return data


if go and url:
    for k in ("ideas", "comp", "psi", "gap", "volumes", "ext"):
        st.session_state.pop(k, None)
    try:
        crawl = run_crawl(url, max_pages)
    except Exception as e:  # noqa: BLE001
        st.error(f"Impossibile analizzare il sito: {e}")
        st.stop()
    with st.spinner("Analizzo problemi e keyword…"):
        issues = an.find_issues(crawl)
        kw = an.keyword_analysis(crawl)
        st.session_state["res"] = {
            "crawl": crawl,
            "pages_df": an.pages_dataframe(crawl),
            "issues": issues,
            "summary": an.issues_summary(issues),
            "score": an.health_score(crawl, issues),
            "kw": kw,
            "when": dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
    if check_ext:
        ext = sorted({l for p in crawl["pages"] for l in p.external_links})
        with st.spinner(f"Controllo {min(len(ext), 300)} link esterni…"):
            st.session_state["ext"] = check_external_links(ext)

res = st.session_state.get("res")
if not res:
    st.info("Inserisci l'URL di un sito e premi **Analizza sito**. Verranno scansionate tutte le pagine raggiungibili "
            "(link interni + sitemap).")
    st.stop()

crawl, pages_df, issues, summary, kw = res["crawl"], res["pages_df"], res["issues"], res["summary"], res["kw"]
pages = crawl["pages"]
host = crawl["host"]
st.caption(f"Sito: **{host}** · analisi del {res['when']}"
           + (" · ⚠️ raggiunto il limite di pagine: aumentalo per una scansione completa." if crawl["limit_reached"] else ""))

tabs = st.tabs(["📊 Panoramica", "🚨 Problemi", "📄 Pagine", "🔑 Keyword", "💡 Idee keyword",
                "🥊 Competitor", "🆚 Confronta sito", "⚡ Velocità", "🔗 Link", "⬇️ Esporta"])

# ----------------------------------------------------------------------------- panoramica
with tabs[0]:
    n_html = sum(1 for p in pages if p.status == 200 and p.is_html)
    n_idx = sum(1 for p in pages if p.indexable)
    n_err = sum(1 for p in pages if p.status >= 400 or (p.error and not p.status))
    n_red = sum(1 for p in pages if 300 <= p.status < 400)
    m = st.columns(6)
    m[0].metric("Punteggio salute", f"{res['score']}/100")
    m[1].metric("URL scansionati", len(pages))
    m[2].metric("Pagine indicizzabili", n_idx)
    m[3].metric("Errori 4xx/5xx", n_err)
    m[4].metric("Redirect", n_red)
    m[5].metric("URL in sitemap", len(crawl["sitemap_urls"]))
    sev = issues["Gravità"].value_counts() if not issues.empty else pd.Series(dtype=int)
    s = st.columns(3)
    s[0].metric("🔴 Critici", int(sev.get("Critico", 0)))
    s[1].metric("🟠 Avvisi", int(sev.get("Avviso", 0)))
    s[2].metric("🔵 Info", int(sev.get("Info", 0)))
    st.subheader("Cosa sistemare, in ordine di priorità")
    st.dataframe(summary, width="stretch", hide_index=True)
    left, right = st.columns(2)
    with left:
        st.subheader("Profondità dei clic")
        dep = pages_df[pages_df["Indicizzabile"] == "Sì"]["Profondità"].value_counts().sort_index()
        st.bar_chart(dep)
    with right:
        st.subheader("Codici di stato")
        st.bar_chart(pages_df["Stato"].astype(str).value_counts())
    if not kw["site"].empty:
        st.subheader("Le keyword principali del sito")
        st.dataframe(kw["site"].head(20)[["Keyword", "Rilevanza", "Pagine che la usano", "Pagina più forte"]],
                     width="stretch", hide_index=True)

# ----------------------------------------------------------------------------- problemi
with tabs[1]:
    if issues.empty:
        st.success("Nessun problema rilevato 🎉")
    else:
        f1, f2 = st.columns(2)
        sev_sel = f1.multiselect("Gravità", ["Critico", "Avviso", "Info"], ["Critico", "Avviso"])
        prob_sel = f2.multiselect("Tipo di problema", sorted(issues["Problema"].unique()))
        view = issues[issues["Gravità"].isin(sev_sel)]
        if prob_sel:
            view = view[view["Problema"].isin(prob_sel)]
        st.caption(f"{len(view)} segnalazioni")
        st.dataframe(view.drop(columns="_code"), width="stretch", hide_index=True,
                     column_config={"URL": st.column_config.LinkColumn()})
    ext = st.session_state.get("ext")
    if ext:
        broken = {u: s for u, s in ext.items() if s == 0 or s >= 400}
        st.subheader(f"Link esterni rotti: {len(broken)}")
        if broken:
            srcs = {l: p.url for p in pages for l in p.external_links}
            st.dataframe(pd.DataFrame([{"Link esterno": u, "Stato": s or "irraggiungibile", "Trovato in": srcs.get(u, "")}
                                       for u, s in broken.items()]), width="stretch", hide_index=True)

# ----------------------------------------------------------------------------- pagine
with tabs[2]:
    q = st.text_input("Filtra per URL o title")
    v = pages_df
    if q:
        v = v[v["URL"].str.contains(q, case=False, na=False) | v["Title"].str.contains(q, case=False, na=False)]
    st.dataframe(v, width="stretch", hide_index=True, column_config={"URL": st.column_config.LinkColumn()})

# ----------------------------------------------------------------------------- keyword
with tabs[3]:
    st.caption("Keyword estratte dai contenuti del sito (title, H1, H2, meta e testo), pesate per importanza. "
               "Sono i temi su cui il sito sta lavorando, non posizionamenti: per quelli usa la scheda Competitor.")
    if kw["site"].empty:
        st.warning("Nessuna pagina indicizzabile da cui estrarre keyword.")
    else:
        st.subheader("Keyword del sito")
        st.dataframe(kw["site"], width="stretch", hide_index=True,
                     column_config={"Pagina più forte": st.column_config.LinkColumn()})
        st.subheader("Keyword per pagina")
        st.dataframe(kw["per_page"], width="stretch", hide_index=True,
                     column_config={"URL": st.column_config.LinkColumn()})
        st.subheader(f"Possibili cannibalizzazioni: {len(kw['cannibal'])}")
        if kw["cannibal"].empty:
            st.success("Nessuna cannibalizzazione evidente.")
        else:
            st.dataframe(kw["cannibal"], width="stretch", hide_index=True)

        if dfs_login and dfs_pwd:
            st.subheader("Volumi di ricerca (Google Ads via DataForSEO)")
            n_vol = st.number_input("Quante keyword del sito", 10, 500, 100, step=10)
            if st.button("Recupera volumi"):
                with st.spinner("Chiedo i volumi…"):
                    try:
                        st.session_state["volumes"] = an.dataforseo_volumes(kw["site"]["Keyword"].head(int(n_vol)).tolist(), dfs_login, dfs_pwd)
                    except Exception as e:  # noqa: BLE001
                        st.error(str(e))
            if st.session_state.get("volumes") is not None:
                st.dataframe(st.session_state["volumes"].sort_values("Volume mensile", ascending=False, na_position="last"),
                             width="stretch", hide_index=True)
        else:
            st.info("Per i volumi di ricerca inserisci le credenziali DataForSEO nella barra laterale.")

# ----------------------------------------------------------------------------- idee keyword
with tabs[4]:
    st.caption("Suggerimenti reali dall'autocompletamento di Google a partire dalle keyword del sito (gratis, senza chiave).")
    default_seeds = [k for k in kw["site"]["Keyword"].tolist() if " " in k][:8] if not kw["site"].empty else []
    seeds_txt = st.text_area("Keyword di partenza (una per riga)", "\n".join(default_seeds), height=150)
    if st.button("Genera idee"):
        seeds = [s.strip() for s in seeds_txt.splitlines() if s.strip()]
        bar = st.progress(0.0)
        ideas = an.keyword_ideas(seeds, progress=lambda i, t, q: bar.progress(i / t, text=q))
        if ideas.empty:
            st.warning("Google non ha restituito suggerimenti (riprova più tardi o cambia keyword).")
        st.session_state["ideas"] = ideas
    ideas = st.session_state.get("ideas")
    if ideas is not None and not ideas.empty:
        st.write(f"**{len(ideas)} idee** ({(ideas['Tipo'] == 'domanda').sum()} domande)")
        st.dataframe(ideas, width="stretch", hide_index=True)
        if dfs_login and dfs_pwd and st.button("Aggiungi volumi alle idee"):
            try:
                vol = an.dataforseo_volumes(ideas["Idea keyword"].tolist(), dfs_login, dfs_pwd)
                st.session_state["ideas"] = ideas.merge(vol.rename(columns={"Keyword": "Idea keyword"}), on="Idea keyword", how="left")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(str(e))

# ----------------------------------------------------------------------------- competitor
with tabs[5]:
    provider = "serper" if serper_key else ("dataforseo" if dfs_login and dfs_pwd else None)
    if not provider:
        st.info("Per scoprire i competitor serve una chiave SERP: **Serper.dev** (crediti gratuiti iniziali) "
                "oppure **DataForSEO**. Inseriscila nella barra laterale.")
    else:
        st.caption("Cerco su Google.it le keyword del sito e vedo chi si posiziona: i domini che compaiono più spesso sono i tuoi competitor SEO reali.")
        base = [k for k in kw["site"]["Keyword"].tolist() if " " in k] if not kw["site"].empty else []
        kws_txt = st.text_area("Keyword da verificare su Google (una per riga)", "\n".join(base[:20]), height=200)
        st.caption("Ogni keyword = 1 ricerca API.")
        if st.button("Trova competitor"):
            kws = [k.strip() for k in kws_txt.splitlines() if k.strip()]
            bar = st.progress(0.0)
            st.session_state["comp"] = an.competitor_analysis(
                kws, host, provider,
                {"serper_key": serper_key, "dfs_login": dfs_login, "dfs_password": dfs_pwd},
                progress=lambda i, t, q: bar.progress(i / t, text=q))
        comp = st.session_state.get("comp")
        if comp:
            rk = comp["rankings"]
            if not rk.empty:
                top10 = rk["Tua posizione"].astype(str).str.isdigit().sum()
                st.metric("Keyword in cui sei in prima pagina", f"{top10} / {len(rk)}")
            st.subheader("Competitor")
            only_real = st.checkbox("Nascondi portali e social", True)
            cdf = comp["competitors"]
            if only_real and not cdf.empty:
                cdf = cdf[cdf["Tipo"] == "competitor"]
            st.dataframe(cdf, width="stretch", hide_index=True)
            st.subheader("I tuoi posizionamenti")
            st.dataframe(rk, width="stretch", hide_index=True)
            if not comp["related"].empty:
                st.subheader("Ricerche correlate e domande (People Also Ask)")
                st.dataframe(comp["related"], width="stretch", hide_index=True)
            with st.expander("Tutti i risultati SERP"):
                st.dataframe(comp["serp"], width="stretch", hide_index=True)

# ----------------------------------------------------------------------------- confronto
with tabs[6]:
    st.caption("Scansiona il sito di un competitor e confronta i contenuti: trovi i temi che lui tratta e tu no (keyword gap).")
    cu = st.text_input("URL del competitor", placeholder="https://www.competitor.it")
    climit = st.slider("Pagine massime del competitor", 10, 1000, 200, step=10)
    if st.button("Confronta") and cu:
        try:
            ccrawl = run_crawl(cu, climit)
            ckw = an.keyword_analysis(ccrawl)
            gap, shared = an.keyword_gap(kw, ckw)
            st.session_state["gap"] = {"host": ccrawl["host"], "gap": gap, "shared": shared,
                                       "n": len(ccrawl["pages"]), "score": an.health_score(ccrawl, an.find_issues(ccrawl))}
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    g = st.session_state.get("gap")
    if g:
        a, b, c = st.columns(3)
        a.metric(f"Punteggio {host}", f"{res['score']}/100")
        b.metric(f"Punteggio {g['host']}", f"{g['score']}/100")
        c.metric("Pagine competitor", g["n"])
        st.subheader(f"Temi che {g['host']} tratta e tu no ({len(g['gap'])})")
        st.dataframe(g["gap"], width="stretch", hide_index=True)
        st.subheader(f"Temi in comune ({len(g['shared'])})")
        st.dataframe(g["shared"], width="stretch", hide_index=True)

# ----------------------------------------------------------------------------- velocità
with tabs[7]:
    st.caption("Google PageSpeed Insights: punteggi Lighthouse e, se disponibili, dati Core Web Vitals degli utenti reali.")
    idx = [p for p in pages if p.indexable]
    top = sorted(idx, key=lambda p: -len(crawl["inlinks"].get(p.url, [])))
    opts = [p.url for p in top[:50]]
    sel = st.multiselect("Pagine da testare", opts, opts[:3])
    strat = st.radio("Dispositivo", ["mobile", "desktop"], horizontal=True)
    if st.button("Testa velocità"):
        out = []
        with st.spinner("Test in corso (circa 20-40 secondi per pagina)…"):
            for u in sel:
                try:
                    out.append(an.pagespeed(u, strat, psi_key or None))
                except Exception as e:  # noqa: BLE001
                    out.append({"URL": u, "Dispositivo": strat, "Performance": f"errore: {e}"[:100], "_opps": []})
        st.session_state["psi"] = out
    psi = st.session_state.get("psi")
    if psi:
        st.dataframe(pd.DataFrame([{k: v for k, v in r.items() if k != "_opps"} for r in psi]),
                     width="stretch", hide_index=True)
        for r in psi:
            if r.get("_opps"):
                with st.expander(f"Ottimizzazioni consigliate — {r['URL']}"):
                    st.dataframe(pd.DataFrame(r["_opps"]), width="stretch", hide_index=True)

# ----------------------------------------------------------------------------- link
with tabs[8]:
    inl = crawl["inlinks"]
    idx = [p for p in pages if p.indexable]
    st.subheader("Pagine più linkate internamente")
    st.dataframe(pd.DataFrame(sorted(({"URL": p.url, "Link in entrata": len(inl.get(p.url, []))} for p in idx),
                                     key=lambda r: -r["Link in entrata"]))[:50], width="stretch", hide_index=True)
    orphans = [p.url for p in idx if p.depth is None]
    st.subheader(f"Pagine orfane (solo in sitemap): {len(orphans)}")
    if orphans:
        st.dataframe(pd.DataFrame({"URL": orphans}), width="stretch", hide_index=True)
    not_in_sm = [p.url for p in idx if not p.in_sitemap] if crawl["sitemap_urls"] else []
    st.subheader(f"Pagine indicizzabili assenti dalla sitemap: {len(not_in_sm)}")
    if not crawl["sitemap_urls"]:
        st.warning("Sitemap non trovata: creala e dichiarala in robots.txt e in Google Search Console.")
    elif not_in_sm:
        st.dataframe(pd.DataFrame({"URL": not_in_sm}), width="stretch", hide_index=True)
    with st.expander("robots.txt"):
        st.code(crawl["robots_txt"] or "(non trovato)")
    if crawl["blocked_by_robots"]:
        with st.expander(f"URL bloccati da robots.txt ({len(crawl['blocked_by_robots'])})"):
            st.write(crawl["blocked_by_robots"][:500])

# ----------------------------------------------------------------------------- export
with tabs[9]:
    comp = st.session_state.get("comp") or {}
    gap = st.session_state.get("gap") or {}
    sheets = {
        "Riepilogo": pd.DataFrame([
            {"Voce": "Sito", "Valore": host},
            {"Voce": "Data analisi", "Valore": res["when"]},
            {"Voce": "Punteggio salute", "Valore": res["score"]},
            {"Voce": "URL scansionati", "Valore": len(pages)},
            {"Voce": "Pagine indicizzabili", "Valore": sum(1 for p in pages if p.indexable)},
        ]),
        "Priorità": summary,
        "Problemi": issues,
        "Pagine": pages_df,
        "Keyword sito": kw["site"],
        "Keyword per pagina": kw["per_page"],
        "Cannibalizzazioni": kw["cannibal"],
        "Volumi": st.session_state.get("volumes"),
        "Idee keyword": st.session_state.get("ideas"),
        "Competitor": comp.get("competitors"),
        "Posizionamenti": comp.get("rankings"),
        "Keyword gap": gap.get("gap"),
        "PageSpeed": pd.DataFrame([{k: v for k, v in r.items() if k != "_opps"} for r in st.session_state.get("psi") or []]),
    }
    fname = f"audit-seo-{host}-{dt.date.today():%Y%m%d}.xlsx"
    st.download_button("Scarica report Excel completo", an.to_excel(sheets), file_name=fname,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    st.caption("Il report include tutte le schede che hai generato (idee, competitor, velocità… se le hai lanciate).")
