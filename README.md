# SEO Audit personale

Inserisci il link di un sito e l'app scansiona **tutte le pagine** (link interni + sitemap) e ti dà:

| Scheda | Cosa trovi |
|---|---|
| 📊 Panoramica | Punteggio di salute, priorità da sistemare, keyword principali |
| 🚨 Problemi | 27 controlli tecnici e on-page (404, redirect, title/meta duplicati o mancanti, H1, contenuti scarsi, orfane, noindex, canonical, alt, schema, Open Graph, profondità, velocità server…) con **come risolvere** e da quali pagine sono linkati |
| 📄 Pagine | Tabella completa di ogni URL |
| 🔑 Keyword | Keyword del sito, keyword principale/secondarie per pagina, **cannibalizzazioni**, volumi (con DataForSEO) |
| 💡 Idee keyword | Suggerimenti e domande reali dall'autocompletamento di Google (gratis) |
| 🥊 Competitor | Chi si posiziona su Google per le tue keyword, tue posizioni, ricerche correlate e "Le persone hanno chiesto anche" (serve Serper o DataForSEO) |
| 🆚 Confronta sito | Scansiona un competitor e mostra i temi che lui tratta e tu no (**keyword gap**) |
| ⚡ Velocità | PageSpeed Insights: Lighthouse + Core Web Vitals reali |
| 🔗 Link | Pagine più linkate, orfane, pagine fuori sitemap, robots.txt |
| ⬇️ Esporta | Report Excel con tutte le schede |

## Chiavi API (tutte facoltative)

Senza chiavi funzionano già: scansione completa, problemi, keyword del sito, cannibalizzazioni, idee keyword, confronto competitor, velocità.

- **Serper.dev** → competitor e posizionamenti. Registrati su serper.dev: ci sono crediti gratuiti iniziali, poi si paga a consumo (1 keyword = 1 ricerca).
- **DataForSEO** → volumi di ricerca mensili, concorrenza e CPC (dati Google Ads) e, in alternativa a Serper, SERP. Pagamento a consumo con deposito minimo; costi per singola richiesta molto bassi.
- **PageSpeed API key** → solo se fai molti test (Google Cloud Console → abilita "PageSpeed Insights API" → crea chiave). Gratuita.

Verifica sempre prezzi e quote aggiornati sui siti dei fornitori.

## Metterla online gratis (Streamlit Community Cloud)

1. Crea un account su **github.com** e un **repository privato** (es. `seo-audit`).
2. Carica nel repository tutti i file di questa cartella (`app.py`, `crawler.py`, `analysis.py`, `requirements.txt`, la cartella `.streamlit` **senza** `secrets.toml`).
3. Vai su **share.streamlit.io**, accedi con GitHub e crea una nuova app: repository `seo-audit`, file principale `app.py`.
4. Nelle impostazioni avanzate, nella sezione **Secrets**, incolla il contenuto di `.streamlit/secrets.toml.example` compilato con la tua password e le chiavi.
5. Deploy. Avrai un indirizzo tipo `https://tuonome-seo-audit.streamlit.app` protetto da password.

Le chiavi messe nei Secrets restano sul server e non finiscono nel codice. Per cambiarle basta modificare i Secrets dall'app.

## Usarla sul tuo computer

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # e compila
streamlit run app.py
```
Si apre su http://localhost:8501.

## Note

- **Siti grandi**: il piano gratuito di Streamlit ha poca memoria; fino a 2-3.000 pagine va bene. Per e-commerce enormi usa la versione locale.
- **Siti che bloccano i bot** (Cloudflare "Under attack" o simili) possono restituire errori 403: abbassa le richieste in parallelo o lancia l'analisi in locale.
- **Siti costruiti solo in JavaScript** (alcuni Wix/React): il crawler legge l'HTML che arriva dal server, quindi potrebbe vedere poco contenuto.
- Le keyword del sito sono **estratte dai contenuti**, non sono posizionamenti: le posizioni reali le dà la scheda Competitor.
- Il punteggio di salute è indicativo e serve a confrontare il sito prima/dopo gli interventi.
