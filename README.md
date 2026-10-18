# OffTrack, dati per il calcolo percorso

Questo repository prepara i dati offline del motore Valhalla per l'app OffTrack. Non contiene il codice dell'app.

L'azione **Dati Valhalla** gira il 2 di ogni mese. Scarica l'estratto OpenStreetMap dell'Italia da Geofabrik e costruisce i tile con Valhalla 3.6.3. Poi li divide in pacchetti da 1°×1° e li pubblica come release. Dalla scheda Actions si può anche avviare a mano, scegliendo l'area `nord-ovest` per una prova più piccola.

Ogni release contiene:

- un file `.tar` per ogni quadrato da 1°, chiamato con il suo angolo sud-ovest (per esempio `N44E008.tar`). Ogni pacchetto contiene i tile di livello 0, 1 e 2 che servono a quel quadrato;
- `index.json`, con la data, la versione di Valhalla e l'elenco dei pacchetti con dimensione e sha256.

L'app legge `releases/latest/download/index.json` e scarica i pacchetti dei quadrati che toccano l'area scelta. Poi li estrae tutti nella stessa cartella dei tile.

Dati © OpenStreetMap contributors, licenza [ODbL](https://opendatacommons.org/licenses/odbl/).
