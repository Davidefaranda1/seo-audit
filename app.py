"""SEO Radar — posizioni reali su Google, competitor, keyword gap e audit tecnico.

Avvio locale:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import hmac
import io
import json
from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analysis as an
import serp as sp
from crawler import Crawler, bare_host, normalize

st.set_page_config(page_title="SEO Radar", page_icon="📡", layout="wide", initial_sidebar_state="expanded")

# ============================================================================ STILE
INDIGO, GREEN, AMBER, ORANGE, SLATE, LIGHT = "#6366f1", "#10b981", "#f59e0b", "#fb923c", "#94a3b8", "#e2e8f0"
BUCKET_COLORS = {"Top 3": GREEN, "4-10": INDIGO, "11-20": AMBER, "21-50": ORANGE, "51-100": SLATE, "Non posizionato": LIGHT}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, .stApp, .stMarkdown, .stMarkdown p, h1, h2, h3, h4, h5, button, input, textarea, select, label { font-family: 'Inter', sans-serif !important; }
div[data-testid="stVerticalBlockBorderWrapper"] h4 { font-size:1.05rem; font-weight:700; }
div[data-testid="stVerticalBlockBorderWrapper"] { background:#fff; border-radius:16px; }
.stApp { background: #f5f6fa; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.6rem; max-width: 1400px; }
h1, h2, h3 { letter-spacing: -0.02em; color: #0f172a; }

/* sidebar */
section[data-testid="stSidebar"] { background: #0f172a; }
section[data-testid="stSidebar"] * { color: #cbd5e1; }
section[data-testid="stSidebar"] input { color: #0f172a !important; }
.brand { display:flex; align-items:center; gap:.6rem; font-size:1.35rem; font-weight:800; color:#fff !important; margin:.2rem 0 1.4rem; }
.brand span.dot { width:34px; height:34px; border-radius:10px; display:inline-flex; align-items:center; justify-content:center;
  background: linear-gradient(135deg,#6366f1,#22d3ee); color:#fff !important; font-size:1.1rem; }
section[data-testid="stSidebar"] div[role="radiogroup"] { gap: 2px; }
section[data-testid="stSidebar"] div[role="radiogroup"] label { padding:.55rem .8rem; border-radius:10px; width:100%; margin:0; cursor:pointer; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background:#1e293b; }
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:first-child { display:none; }
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] { background:#6366f1; }
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p { color:#fff !important; font-weight:600; }
.side-proj { background:#1e293b; border-radius:12px; padding:.8rem .9rem; font-size:.82rem; margin-top:1rem; line-height:1.5; }
.side-proj b { color:#fff !important; }

/* hero */
.hero { background: linear-gradient(120deg,#4f46e5 0%,#6366f1 45%,#06b6d4 100%); border-radius:20px; padding:1.6rem 1.8rem;
  color:#fff; margin-bottom:1.3rem; box-shadow: 0 10px 30px -12px rgba(79,70,229,.55); }
.hero h1 { color:#fff; margin:0; font-size:1.75rem; font-weight:800; }
.hero p { color:#e0e7ff; margin:.3rem 0 0; font-size:.95rem; }

/* card KPI */
.kpi { background:#fff; border:1px solid #e8eaf2; border-radius:16px; padding:1rem 1.1rem; height:100%;
  box-shadow: 0 1px 2px rgba(16,24,40,.04); }
.kpi .l { color:#64748b; font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
.kpi .v { color:#0f172a; font-size:1.9rem; font-weight:800; margin-top:.25rem; line-height:1.1; }
.kpi .s { color:#94a3b8; font-size:.8rem; margin-top:.25rem; }
.kpi .up { color:#059669; font-weight:600; } .kpi .down { color:#dc2626; font-weight:600; }
.card { background:#fff; border:1px solid #e8eaf2; border-radius:16px; padding:1.1rem 1.2rem; margin-bottom:1rem; }
.card h4 { margin:0 0 .6rem; font-size:1rem; color:#0f172a; }
.pill { display:inline-block; padding:.15rem .6rem; border-radius:999px; font-size:.75rem; font-weight:600; background:#eef2ff; color:#4338ca; }
.muted { color:#64748b; font-size:.88rem; }
.step { display:inline-flex; width:28px; height:28px; border-radius:50%; background:#6366f1; color:#fff; align-items:center;
  justify-content:center; font-weight:700; margin-right:.5rem; }

/* componenti */
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] { border-radius:12px; overflow:hidden; border:1px solid #e8eaf2; }
.stButton > button, .stDownloadButton > button { border-radius:10px; font-weight:600; padding:.5rem 1.1rem; }
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background:#6366f1; border-color:#6366f1; }
.stButton > button[kind="primary"]:hover { background:#4f46e5; border-color:#4f46e5; }
div[data-testid="stTabs"] button p { font-weight:600; }
</style>
""", unsafe_allow_html=True)


def kpi(col, label, value, sub=""):
    col.markdown(f'<div class="kpi"><div class="l">{label}</div><div class="v">{value}</div><div class="s">{sub}</div></div>',
                 unsafe_allow_html=True)


def hero(title, subtitle):
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def plot_layout(fig, h=330):
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter", color="#334155"),
                      legend=dict(orientation="h", y=-0.12))
    return fig


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # noqa: BLE001
        return default


# ============================================================================ ACCESSO
def check_password() -> bool:
    pwd = secret("APP_PASSWORD")
    if not pwd or st.session_state.get("auth_ok"):
        return True
    c = st.columns([1, 1.2, 1])[1]
    with c:
        st.markdown('<div style="height:12vh"></div>', unsafe_allow_html=True)
        st.markdown('<div class="brand" style="color:#0f172a !important;justify-content:center">'
                    '<span class="dot">📡</span><span style="color:#0f172a">SEO Radar</span></div>', unsafe_allow_html=True)
        p = st.text_input("Password", type="password")
        if st.button("Entra", type="primary", width="stretch") or p:
            if hmac.compare_digest(p, pwd):
                st.session_state["auth_ok"] = True
                st.rerun()
            elif p:
                st.error("Password errata")
    return False


if not check_password():
    st.stop()

ss = st.session_state
ss.setdefault("proj", None)
ss.setdefault("nav", "Nuova analisi")
if "_goto" in ss:
    ss["nav"] = ss.pop("_goto")
SERPER_KEY = secret("SERPER_API_KEY")

# ============================================================================ SIDEBAR
PAGES = ["Nuova analisi", "Dashboard", "Posizioni", "Competitor", "Keyword gap", "Idee keyword", "Audit tecnico", "Progetto"]
ICONS = {"Nuova analisi": "✨", "Dashboard": "📊", "Posizioni": "🏁", "Competitor": "🥊", "Keyword gap": "🎯",
         "Idee keyword": "💡", "Audit tecnico": "🛠️", "Progetto": "💾"}
with st.sidebar:
    st.markdown('<div class="brand"><span class="dot">📡</span>SEO Radar</div>', unsafe_allow_html=True)
    nav = st.radio("Menu", PAGES, key="nav", format_func=lambda p: f"{ICONS[p]}  {p}", label_visibility="collapsed")
    if not SERPER_KEY:
        SERPER_KEY = st.text_input("Serper API key", type="password", help="Mettila nei Secrets come SERPER_API_KEY per non reinserirla.")
    proj = ss["proj"]
    if proj:
        st.markdown(f'<div class="side-proj"><b>{proj["host"]}</b><br>{proj["location_label"]} · top {proj["depth"]}<br>'
                    f'{len(proj["serp"])} keyword analizzate<br>Crediti Serper usati: {proj.get("credits", 0)}<br>'
                    f'<span style="opacity:.7">{proj["date"]}</span></div>', unsafe_allow_html=True)


# ============================================================================ DATI DERIVATI
def derived(proj) -> dict:
    serp, host = proj["serp"], proj["host"]
    rk = sp.rankings(serp, host)
    if not rk.empty:
        rk["Fascia"] = rk["Posizione"].apply(sp.bucket)
        prev = proj.get("prev")
        if prev:
            prev_rk = sp.rankings(prev, host).set_index("Keyword")["Posizione"]
            def delta(r):
                if r["Keyword"] not in prev_rk.index:
                    return "nuova keyword"
                a, b = prev_rk[r["Keyword"]], r["Posizione"]
                if pd.isna(a) and pd.isna(b):
                    return ""
                if pd.isna(a):
                    return "▲ entrata"
                if pd.isna(b):
                    return "▼ uscita"
                d = int(a) - int(b)
                return f"▲ {d}" if d > 0 else (f"▼ {abs(d)}" if d < 0 else "=")
            rk["Variazione"] = rk.apply(delta, axis=1)
    return {"rk": rk, "comp": sp.competitors(serp, host), "vis": sp.my_visibility(serp, host)}


def run_serp_for(keywords: list[str]):
    proj = ss["proj"]
    todo = [k for k in keywords if k not in proj["serp"]]
    if not todo:
        st.info("Queste keyword sono già state analizzate.")
        return
    if not SERPER_KEY:
        st.error("Inserisci la API key di Serper nella barra laterale (o nei Secrets come SERPER_API_KEY).")
        return
    bar = st.progress(0.0, text="Leggo Google…")
    res, errs = sp.run_serp(todo, SERPER_KEY, sp.LOCATIONS[proj["location_label"]], proj["depth"],
                            progress=lambda i, t, k: bar.progress(i / t, text=f"SERP {i}/{t} · {k}"))
    proj["serp"].update(res)
    proj["credits"] = proj.get("credits", 0) + sum(int(r.get("credits") or (1 if proj["depth"] <= 10 else 2)) for r in res.values())
    bar.empty()
    if errs:
        st.warning(f"{len(errs)} ricerche non riuscite. Primo errore: {errs[0]}")
    return res


# ============================================================================ NUOVA ANALISI
if nav == "Nuova analisi":
    hero("Nuova analisi", "Scopri le keyword del sito, verifica le posizioni reali su Google e trova i competitor.")
    with st.container(border=True):
        st.markdown('<span class="step">1</span>**Sito e impostazioni**', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2.2, 1, 1])
        url = c1.text_input("Sito da analizzare", placeholder="www.esempio.it")
        loc = c2.selectbox("Mercato / città", list(sp.LOCATIONS))
        depth = c3.selectbox("Profondità SERP", [100, 10],
                             format_func=lambda d: "Top 100 · 2 crediti/kw" if d == 100 else "Top 10 · 1 credito/kw")
        c4, c5, c6 = st.columns([2.2, 1, 1])
        manual = c4.text_area("Keyword da includere sempre (una per riga, facoltativo)", height=110,
                              placeholder="corso meta ads catania\nagenzia marketing catania")
        crawl_on = c5.toggle("Scansiona il sito", True, help="Estrae le keyword dalle pagine del sito")
        suggest_on = c5.toggle("Suggerimenti Google", True, help="Allarga la lista con l'autocompletamento di Google")
        brand_on = c5.toggle("Ricerca del brand", True)
        max_pages = c6.slider("Pagine da scansionare", 20, 1000, 150, step=10)
        audit_on = c6.toggle("Audit tecnico", True, help="Controlla anche errori tecnici e on-page")
        go_discover = st.button("Trova keyword (gratis)", type="primary")

    if go_discover:
        if not url.strip():
            st.error("Inserisci il sito.")
            st.stop()
        start = normalize(url if url.startswith("http") else "https://" + url)
        host = bare_host(urlparse(start).netloc)
        kw_an, crawl = None, None
        if crawl_on:
            bar = st.progress(0.0, text="Scansiono il sito…")
            try:
                crawl = Crawler(start, max_pages=max_pages, workers=6,
                                progress=lambda d, t, m: bar.progress(min(1.0, d / max(1, t)), text=f"{d} pagine · {m[:80]}")).run()
                host = crawl["host"]
                kw_an = an.keyword_analysis(crawl)
            except Exception as e:  # noqa: BLE001
                st.warning(f"Scansione non riuscita ({e}). Continuo con le keyword manuali.")
            bar.empty()
        brand = host.split(".")[0].replace("-", " ") if brand_on and not host.split(".")[0].isdigit() else ""
        with st.spinner("Raccolgo le keyword…"):
            cand = sp.candidate_keywords(kw_an, [l for l in manual.splitlines() if l.strip()], brand, suggest_on)
        order = {"manuale": 0, "brand": 1, "dal sito (principale)": 2, "dal sito (tema)": 3, "dal sito (secondaria)": 4}
        if not cand.empty:
            cand["_o"] = cand["Origine"].map(lambda o: order.get(o, 5))
            cand = cand.sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
            cand.insert(0, "Verifica", cand.index < 150)
        ss["proj"] = {"host": host, "start": start, "location_label": loc, "depth": depth,
                      "date": dt.datetime.now().strftime("%d/%m/%Y %H:%M"), "serp": {}, "credits": 0,
                      "candidates": cand}
        ss["crawl"] = crawl if (crawl and audit_on) else None
        if crawl and audit_on:
            issues = an.find_issues(crawl)
            ss["audit"] = {"issues": issues, "summary": an.issues_summary(issues), "score": an.health_score(crawl, issues),
                           "pages": an.pages_dataframe(crawl), "kw": kw_an}
        else:
            ss["audit"] = None
        st.rerun()

    proj = ss["proj"]
    if proj and not proj["serp"] and proj.get("candidates") is not None:
        cand = proj["candidates"]
        with st.container(border=True):
            st.markdown(f'<span class="step">2</span>**Scegli le keyword da verificare su Google** '
                        f'<span class="pill">{len(cand)} trovate per {proj["host"]}</span>', unsafe_allow_html=True)
            if cand.empty:
                st.warning("Nessuna keyword trovata: aggiungine qualcuna a mano al passo 1.")
            else:
                st.caption("Spunta quelle da controllare. Puoi modificare il testo o aggiungere righe in fondo.")
                edited = st.data_editor(cand, num_rows="dynamic", width="stretch", height=420, hide_index=True,
                                        column_config={"Verifica": st.column_config.CheckboxColumn(width="small"),
                                                       "Pagina del sito": st.column_config.LinkColumn()})
                sel = [k.strip().lower() for k in edited.loc[edited["Verifica"] == True, "Keyword"].dropna() if k.strip()]  # noqa: E712
                sel = list(dict.fromkeys(sel))
                cost = len(sel) * (1 if proj["depth"] <= 10 else 2)
                a, b = st.columns([3, 1])
                a.markdown(f'<p class="muted">Selezionate <b>{len(sel)}</b> keyword · costo stimato <b>{cost} crediti Serper</b> '
                           f'(ne hai 2.500 gratis alla registrazione)</p>', unsafe_allow_html=True)
                if b.button("Controlla posizioni su Google", type="primary", width="stretch", disabled=not sel):
                    proj["candidates"] = edited
                    if run_serp_for(sel) is not None and proj["serp"]:
                        ss["_goto"] = "Dashboard"
                        st.rerun()
    elif proj and proj["serp"]:
        st.success(f"Analisi di **{proj['host']}** pronta: apri la **Dashboard** dal menu. "
                   "Per analizzare un altro sito compila di nuovo il passo 1.")

# ============================================================================ GUARD
elif not ss["proj"] or not ss["proj"]["serp"]:
    hero(nav, "Prima avvia un'analisi.")
    st.info("Vai su **✨ Nuova analisi** oppure carica un progetto salvato da **💾 Progetto**.")
    if nav == "Progetto":
        up = st.file_uploader("Carica un progetto (.json)", type="json")
        if up:
            d = json.load(up)
            d["candidates"] = pd.DataFrame(d.get("candidates", []))
            ss["proj"], ss["audit"], ss["_goto"] = d, None, "Dashboard"
            st.rerun()

else:
    proj = ss["proj"]
    host = proj["host"]
    D = derived(proj)
    rk, comp = D["rk"], D["comp"]
    N = len(rk)
    ranked = rk["Posizione"].notna()
    top3 = int((rk["Posizione"] <= 3).sum())
    top10 = int((rk["Posizione"] <= 10).sum())
    qw = sp.quick_wins(rk)

    # ------------------------------------------------------------------ DASHBOARD
    if nav == "Dashboard":
        hero(f"{host}", f"{proj['location_label']} · SERP top {proj['depth']} · {N} keyword analizzate · {proj['date']}")
        k = st.columns(5)
        kpi(k[0], "Visibilità", f"{D['vis']}%", "quota stimata dei clic sulla nicchia")
        kpi(k[1], "Keyword in top 10", f"{top10}", f"su {N} analizzate")
        kpi(k[2], "Keyword in top 3", f"{top3}", "le più redditizie")
        kpi(k[3], "Posizione media", f"{rk.loc[ranked, 'Posizione'].mean():.1f}" if ranked.any() else "—", "tra quelle posizionate")
        kpi(k[4], "Quick win", f"{len(qw)}", "in posizione 4-20")
        st.write("")
        l, r = st.columns([1, 1.5])
        with l, st.container(border=True):
            st.markdown("#### Distribuzione posizioni")
            cnt = rk["Fascia"].value_counts().reindex(sp.BUCKET_ORDER).fillna(0)
            fig = go.Figure(go.Pie(labels=cnt.index, values=cnt.values, hole=.62, sort=False,
                                   marker=dict(colors=[BUCKET_COLORS[b] for b in cnt.index]), textinfo="value"))
            fig.add_annotation(text=f"<b>{top10}</b><br>top 10", showarrow=False, font=dict(size=20, color="#0f172a"))
            st.plotly_chart(plot_layout(fig), width="stretch", config={"displayModeBar": False})
        with r, st.container(border=True):
            st.markdown("#### Quota di visibilità: tu vs competitor")
            c = comp[comp["Tipo"] == "Competitor"].head(9) if not comp.empty else pd.DataFrame(columns=["Dominio", "Visibilità %"])
            bars = pd.concat([pd.DataFrame([{"Dominio": f"{host} (tu)", "Visibilità %": D["vis"]}]), c[["Dominio", "Visibilità %"]]])
            bars = bars.sort_values("Visibilità %")
            fig = go.Figure(go.Bar(x=bars["Visibilità %"], y=bars["Dominio"], orientation="h",
                                   marker_color=[INDIGO if "(tu)" in d else "#c7d2fe" for d in bars["Dominio"]],
                                   text=[f"{v}%" for v in bars["Visibilità %"]], textposition="outside", cliponaxis=False))
            fig.update_xaxes(range=[0, float(bars["Visibilità %"].max() or 1) * 1.18], showgrid=False)
            st.plotly_chart(plot_layout(fig), width="stretch", config={"displayModeBar": False})
        l, r = st.columns(2)
        with l, st.container(border=True):
            st.markdown("#### 🏆 Le tue keyword migliori")
            st.dataframe(rk[ranked].head(12)[["Keyword", "Posizione", "URL posizionato"]], hide_index=True, width="stretch",
                         column_config={"URL posizionato": st.column_config.LinkColumn()})
        with r, st.container(border=True):
            st.markdown("#### ⚡ Quick win: a un passo dalla prima pagina / dal podio")
            if qw.empty:
                st.caption("Nessuna keyword in posizione 4-20.")
            else:
                st.dataframe(qw.head(12)[["Keyword", "Posizione", "URL posizionato"]], hide_index=True, width="stretch",
                             column_config={"URL posizionato": st.column_config.LinkColumn()})
        if ss.get("audit"):
            a = ss["audit"]
            st.markdown(f'<div class="card"><h4>🛠️ Salute tecnica del sito: {a["score"]}/100</h4>'
                        f'<span class="muted">{(a["issues"]["Gravità"] == "Critico").sum()} problemi critici · '
                        f'{(a["issues"]["Gravità"] == "Avviso").sum()} avvisi — dettagli in Audit tecnico.</span></div>',
                        unsafe_allow_html=True)

    # ------------------------------------------------------------------ POSIZIONI
    elif nav == "Posizioni":
        hero("Posizioni su Google", f"Dove compare {host} per ogni keyword · {proj['location_label']}")
        f1, f2, f3 = st.columns([2, 2, 1])
        q = f1.text_input("Cerca keyword", placeholder="es. corso")
        fasce = f2.multiselect("Fascia", sp.BUCKET_ORDER, default=[b for b in sp.BUCKET_ORDER if b != "Non posizionato"])
        v = rk[rk["Fascia"].isin(fasce)] if fasce else rk
        if q:
            v = v[v["Keyword"].str.contains(q, case=False)]
        f3.metric("Risultati", len(v))
        cols = ["Keyword", "Posizione"] + (["Variazione"] if "Variazione" in v else []) + \
               ["URL posizionato", "1° risultato", "Elementi SERP", "Local pack", "Fascia"]
        st.dataframe(v[cols], hide_index=True, width="stretch", height=560,
                     column_config={"URL posizionato": st.column_config.LinkColumn(),
                                    "Posizione": st.column_config.NumberColumn(format="%d")})
        can = sp.cannibalization(proj["serp"], host)
        if not can.empty:
            with st.expander(f"⚠️ {len(can)} keyword con più pagine tue in SERP (possibile cannibalizzazione)"):
                st.dataframe(can, hide_index=True, width="stretch")
        new_k = st.text_area("Aggiungi keyword da monitorare (una per riga)", height=90)
        if st.button("Controlla queste keyword", type="primary") and new_k.strip():
            run_serp_for(list(dict.fromkeys(x.strip().lower() for x in new_k.splitlines() if x.strip())))
            st.rerun()

    # ------------------------------------------------------------------ COMPETITOR
    elif nav == "Competitor":
        hero("Competitor", "Chi si posiziona sulle stesse keyword, quanto è visibile e dove ti batte.")
        if comp.empty:
            st.info("Nessun competitor trovato nelle SERP analizzate.")
        else:
            only = st.toggle("Nascondi portali, social e directory", True)
            cv = comp[comp["Tipo"] == "Competitor"] if only else comp
            st.dataframe(cv, hide_index=True, width="stretch", height=380,
                         column_config={"Visibilità %": st.column_config.ProgressColumn(
                             format="%.2f%%", min_value=0, max_value=float(max(cv["Visibilità %"].max(), D["vis"], 1)))})
            st.markdown("### Testa a testa")
            who = st.selectbox("Confronta con", cv["Dominio"].tolist())
            h2h = sp.head_to_head(proj["serp"], host, who)
            if not h2h.empty:
                k = st.columns(4)
                vis_c = float(comp.loc[comp["Dominio"] == who, "Visibilità %"].iloc[0])
                kpi(k[0], "Tua visibilità", f"{D['vis']}%")
                kpi(k[1], f"Visibilità {who}", f"{vis_c}%")
                kpi(k[2], "Keyword dove vinci", int((h2h["Esito"] == "Vinci tu").sum()))
                kpi(k[3], "Keyword dove vince lui", int((h2h["Esito"] == "Vince lui").sum()))
                st.write("")
                esito = st.segmented_control("Mostra", ["Tutte", "Vince lui", "Vinci tu"], default="Vince lui")
                hv = h2h if esito in (None, "Tutte") else h2h[h2h["Esito"] == esito]
                st.dataframe(hv, hide_index=True, width="stretch",
                             column_config={f"URL {who}": st.column_config.LinkColumn()})

    # ------------------------------------------------------------------ GAP
    elif nav == "Keyword gap":
        hero("Keyword gap", "Keyword dove i competitor sono in prima pagina e tu no: le tue opportunità.")
        gap = sp.keyword_gap(proj["serp"], host)
        if gap.empty:
            st.success("Nessun gap: sei in top 10 ovunque ci siano competitor.")
        else:
            doms = sorted({d.split(" (")[0] for s in gap["Chi c'è"] for d in s.split(", ")})
            pick = st.multiselect("Filtra per competitor", doms)
            gv = gap[gap["Chi c'è"].apply(lambda s: any(p in s for p in pick))] if pick else gap
            k = st.columns(3)
            kpi(k[0], "Opportunità", len(gv))
            kpi(k[1], "Dove non compari proprio", int(gv["Tua posizione"].isna().sum()))
            kpi(k[2], "Dove sei 11-100", int(gv["Tua posizione"].notna().sum()))
            st.write("")
            st.dataframe(gv, hide_index=True, width="stretch", height=520,
                         column_config={"Pagina da battere": st.column_config.LinkColumn(),
                                        "Tua posizione": st.column_config.NumberColumn(format="%d")})

    # ------------------------------------------------------------------ IDEE
    elif nav == "Idee keyword":
        hero("Idee keyword", "Domande e ricerche correlate prese direttamente dalle SERP analizzate.")
        ideas = sp.new_ideas(proj["serp"])
        if ideas.empty:
            st.info("Nessuna idea trovata nelle SERP.")
        else:
            ideas.insert(0, "Verifica", False)
            ed = st.data_editor(ideas, hide_index=True, width="stretch", height=480,
                                column_config={"Verifica": st.column_config.CheckboxColumn(width="small")},
                                disabled=["Idea", "Tipo", "Da keyword"])
            sel = ed.loc[ed["Verifica"] == True, "Idea"].str.lower().tolist()  # noqa: E712
            if st.button(f"Controlla posizioni per {len(sel)} idee selezionate", type="primary", disabled=not sel):
                run_serp_for(sel)
                st.rerun()

    # ------------------------------------------------------------------ AUDIT
    elif nav == "Audit tecnico":
        hero("Audit tecnico", f"Scansione delle pagine di {host}")
        a = ss.get("audit")
        if not a:
            st.info("L'audit non è stato eseguito per questa analisi: rilancia una nuova analisi con «Audit tecnico» attivo.")
        else:
            iss = a["issues"]
            k = st.columns(4)
            kpi(k[0], "Salute", f"{a['score']}/100")
            kpi(k[1], "Pagine", len(a["pages"]))
            kpi(k[2], "Critici", int((iss["Gravità"] == "Critico").sum()) if not iss.empty else 0)
            kpi(k[3], "Avvisi", int((iss["Gravità"] == "Avviso").sum()) if not iss.empty else 0)
            st.write("")
            t1, t2, t3, t4 = st.tabs(["Priorità", "Tutti i problemi", "Pagine", "Keyword per pagina"])
            with t1:
                st.dataframe(a["summary"], hide_index=True, width="stretch")
            with t2:
                sev = st.multiselect("Gravità", ["Critico", "Avviso", "Info"], ["Critico", "Avviso"])
                st.dataframe(iss[iss["Gravità"].isin(sev)].drop(columns="_code"), hide_index=True, width="stretch",
                             column_config={"URL": st.column_config.LinkColumn()})
            with t3:
                st.dataframe(a["pages"], hide_index=True, width="stretch", column_config={"URL": st.column_config.LinkColumn()})
            with t4:
                if a["kw"] is not None and not a["kw"]["per_page"].empty:
                    st.dataframe(a["kw"]["per_page"], hide_index=True, width="stretch")
                    if not a["kw"]["cannibal"].empty:
                        st.markdown("**Possibili cannibalizzazioni nei contenuti**")
                        st.dataframe(a["kw"]["cannibal"], hide_index=True, width="stretch")

    # ------------------------------------------------------------------ PROGETTO
    elif nav == "Progetto":
        hero("Progetto", "Salva l'analisi per riaprirla senza spendere crediti e confrontarla nel tempo.")
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            st.markdown("#### 💾 Salva")
            data = {k: v for k, v in proj.items() if k not in ("candidates", "prev")}
            data["candidates"] = proj["candidates"].to_dict("records") if isinstance(proj.get("candidates"), pd.DataFrame) else []
            st.download_button("Scarica progetto (.json)", json.dumps(data, ensure_ascii=False).encode(),
                               file_name=f"seoradar-{host}-{dt.date.today():%Y%m%d}.json", width="stretch")
            gap = sp.keyword_gap(proj["serp"], host)
            sheets = {"Posizioni": rk, "Competitor": comp, "Keyword gap": gap, "Quick win": qw,
                      "Idee": sp.new_ideas(proj["serp"])}
            if ss.get("audit"):
                sheets.update({"Audit priorità": ss["audit"]["summary"], "Audit problemi": ss["audit"]["issues"],
                               "Pagine": ss["audit"]["pages"]})
            sheets = {k: (v.astype(object).where(v.notna(), None) if isinstance(v, pd.DataFrame) else v) for k, v in sheets.items()}
            st.download_button("Scarica report Excel", an.to_excel(sheets), type="primary", width="stretch",
                               file_name=f"seoradar-{host}-{dt.date.today():%Y%m%d}.xlsx")
        with c2, st.container(border=True):
            st.markdown("#### 📈 Confronta con un'analisi precedente")
            st.caption("Carica il .json di un'analisi passata dello stesso sito: in Posizioni comparirà la colonna Variazione.")
            old = st.file_uploader("Progetto precedente", type="json", key="prev_up")
            if old:
                od = json.load(old)
                if od.get("host") != host:
                    st.error(f"Il file è di {od.get('host')}, non di {host}.")
                else:
                    proj["prev"] = od["serp"]
                    st.success(f"Confronto attivo con l'analisi del {od.get('date')}.")
            st.markdown("#### 📂 Apri un altro progetto")
            up = st.file_uploader("Progetto (.json)", type="json", key="open_up")
            if up and st.button("Apri"):
                d = json.load(up)
                d["candidates"] = pd.DataFrame(d.get("candidates", []))
                ss["proj"], ss["audit"], ss["_goto"] = d, None, "Dashboard"
                st.rerun()
