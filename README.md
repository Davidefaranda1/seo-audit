# 📡 SEO Radar

Tool SEO personale: posizioni **reali** su Google (SERP lette in tempo reale con Serper.dev), competitor, quota di visibilità, keyword gap, quick win, idee keyword e audit tecnico del sito.

## Come funziona
1. **Nuova analisi**: inserisci il sito, scegli il mercato (Italia o città) e la profondità (top 10 o top 100).
2. **Trova keyword (gratis)**: l'app scansiona il sito, estrae le keyword dalle pagine e le allarga con i suggerimenti di Google. Puoi aggiungerne a mano.
3. **Controlla posizioni su Google**: scegli le keyword da verificare e vedi prima quanti crediti costano. L'app legge la SERP vera di ogni keyword.
4. Esplora **Dashboard, Posizioni, Competitor (con testa a testa), Keyword gap, Idee keyword, Audit tecnico**.
5. Da **Progetto** salvi l'analisi in .json, per riaprirla senza spendere crediti o confrontarla con un'analisi futura (colonna Variazione ▲▼), e scarichi l'Excel.

## Costi
- Serper.dev: 2.500 ricerche gratuite alla registrazione, poi circa 1 $ ogni 1.000 ricerche.
- 1 keyword in top 10 = 1 credito; in top 100 = 2 crediti.
- Un'analisi da 150 keyword in top 100 consuma circa 300 crediti.

## Visibilità %
È una stima: per ogni keyword si assegna il CTR medio della posizione (1ª ≈ 28%, 2ª ≈ 15%, … 10ª ≈ 2%). Il risultato si confronta con il massimo possibile, cioè essere primi su tutte le keyword analizzate. Le keyword hanno tutte lo stesso peso perché i volumi di ricerca non sono inclusi.

## Secrets (Streamlit Cloud → Settings → Secrets)
```
APP_PASSWORD = "la-tua-password"
SERPER_API_KEY = "la-tua-chiave-serper"
```

## Tema
Il file `.streamlit/config.toml` forza il tema chiaro:
```
[theme]
base = "light"
primaryColor = "#6366f1"
```

## Avvio in locale
```
pip install -r requirements.txt
streamlit run app.py
```
