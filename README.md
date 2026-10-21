# OffTrack, dati per il calcolo percorso

Questo repository prepara i dati offline del motore Valhalla per l'app OffTrack. Non contiene il codice dell'app.

L'azione **Dati Valhalla** gira il 2 di ogni mese. Scarica l'estratto OpenStreetMap dell'Italia da Geofabrik e costruisce i tile con Valhalla 3.6.3. Poi li divide in pacchetti da 1°×1° e li pubblica come release. Dalla scheda Actions si può anche avviare a mano, scegliendo l'area `nord-ovest` per una prova più piccola.

Ogni release contiene:

- un file `.tar` per ogni quadrato da 1°, chiamato con il suo angolo sud-ovest (per esempio `N44E008.tar`). Ogni pacchetto contiene i tile di livello 0, 1 e 2 che servono a quel quadrato;
- `index.json`, con la data, la versione di Valhalla e l'elenco dei pacchetti con dimensione e sha256.

L'app legge `releases/latest/download/index.json` e scarica i pacchetti dei quadrati che toccano l'area scelta. Poi li estrae tutti nella stessa cartella dei tile.

Dati © OpenStreetMap contributors, licenza [ODbL](https://opendatacommons.org/licenses/odbl/).

## Mappa difficoltà

L'azione **Mappa difficoltà** gira il 3 di ogni mese. Scarica da Geofabrik gli estratti di Nord-Ovest, Nord-Est, Sardegna, Provenza-Alpi-Costa Azzurra, Rodano-Alpi e Corsica, tiene sterrati e sentieri e dà a ciascuno un livello da 1 a 5. Le regole sono quelle di `Levels.kt` nell'app, riportate in `tools/difficulty_layer.py`: vanno cambiate insieme. Il risultato è un solo file `difficolta.pmtiles` (zoom 11-14, strato `difficolta`), pubblicato come release `difficolta-<area>-<data>` con il suo `index.json`.

Ogni via porta `lvl` (livello), `why` (il tag che l'ha deciso), `guess` se il livello è una stima per mancanza di tag, `banned` con il tag che la chiude alle moto, `minz` (lo zoom da cui si vede) e i suoi tag OpenStreetMap: `highway`, `name`, `tracktype`, `surface`, `smoothness`, `sac_scale`, `mtb:scale` e gli altri.

## Curve di livello

L'azione **Curve di livello** si avvia a mano, perché il terreno non cambia. Prende le quote dai Terrain Tiles pubblici su AWS (circa 30 m per pixel) per le stesse zone e traccia le curve ogni 10 m con `gdal_contour`. Il risultato è `curve.pmtiles` (zoom 10-12, strato `curve`, attributo `ele`), pubblicato come release `curve-<area>-<data>`.

Le release di queste due azioni non sono mai segnate come "latest", che resta quella di Valhalla.

Una pull request che cambia una delle due azioni costruisce solo il Nord-Ovest e lascia il file tra gli artifact dell'esecuzione.
