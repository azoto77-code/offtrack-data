# OffTrack, dati offline

Questo repository prepara i dati che l'app OffTrack scarica per funzionare senza rete: percorsi (Valhalla), mappa (Protomaps), sterrati con il livello di difficoltà, curve di livello, quote, punti di interesse e ricerca. Non contiene il codice dell'app.

Dati © OpenStreetMap contributors, licenza [ODbL](https://opendatacommons.org/licenses/odbl/). Quote: Terrain Tiles su AWS (SRTM, EU-DEM prodotto con dati Copernicus, Mapzen).

## Zone offline

L'azione **Zone offline** gira il 4 di gennaio, aprile, luglio e ottobre e costruisce le zone che l'app scarica per funzionare senza rete (meteo escluso). Le zone sono elencate in `zone/zone.json`, una riga ciascuna con il suo estratto Geofabrik: per aggiungerne una basta una riga, e la volta dopo l'azione la costruisce.

Le zone sono le regioni amministrative: le 20 italiane, le 13 francesi, le 17 comunità spagnole con le Canarie, il Portogallo e Andorra, più l'Oman. Una regione o un paese che Geofabrik non pubblica da solo, come il Piemonte dentro `europe/italy/nord-ovest` o l'Oman dentro `asia/gcc-states`, prende l'estratto grande e `boundary`, il suo codice ISO 3166-2 (`IT-21`, `FR-BRE`, `ES-CT`) oppure l'id della relazione del suo confine su OpenStreetMap: l'azione ricava il confine dall'estratto con `tools/boundary_poly.py`, scrive nel log il nome di quello che ha trovato e ritaglia lì. Per un paese tra le `sources` del suo blocco va la stessa fonte con lo stesso `boundary`. Le macro-aree di prima (Nord-Ovest, Nord-Est, Centro, Sud, Isole, Rodano-Alpi) restano finché l'app non porta i suoi utenti alle regioni.

Ogni zona diventa la release `zona-<id>-<edizione>`, con tutti i dati presi lo stesso giorno da OpenStreetMap:

- `valhalla.tar`, i tile per il calcolo dei percorsi. Valhalla è costruito una volta per **blocco** (`blocks` in `zone/zone.json`: Italia e Alpi, Penisola iberica, Francia, Oman) dagli estratti del blocco e poi tagliato zona per zona, così un percorso passa tra le zone dello stesso blocco senza fermarsi al confine; tra due blocchi si ferma. Ogni zona indica il suo `block`. Un blocco senza zone si costruisce solo in pull request, per misurarlo;
- `difficolta.pmtiles`, sterrati e sentieri con il livello 1-5 (zoom 11-14, strato `difficolta`). Le regole sono quelle di `Levels.kt` nell'app, riportate in `tools/difficulty_layer.py`: vanno cambiate insieme. Ogni via porta `lvl` (livello), `why` (il tag che l'ha deciso), `guess` se il livello è una stima per mancanza di tag, `banned` con il tag che la chiude alle moto, `minz` (lo zoom da cui si vede) e i suoi tag OpenStreetMap;
- `curve.pmtiles`, le curve di livello ogni 20 m dai Terrain Tiles pubblici su AWS (zoom 10-12, strato `curve`, attributo `ele`): quelle ogni 100 m dallo zoom 10, le altre dallo zoom 12;
- `quote.tar`, le quote a 90 m, un file `.hgt` per quadrato da 1°×1°;
- `poi.json.gz`, i punti di interesse delle categorie di `PoiCatalog.kt`, con le stesse colonne della tabella POI dell'app. Le categorie sono riportate in `tools/poi_zone.py`: vanno cambiate insieme. Gli autovelox ci sono in ogni zona: è l'app a lasciarli nascondere dove mostrarli è vietato;
- `mappa.pmtiles`, la mappa Protomaps della zona fino a zoom 15, ritagliata dal file mondiale del giorno;
- `ricerca.sqlite.gz`, l'indice per cercare una destinazione senza rete: località, vie per comune, civici e tutti i luoghi con un nome (hotel, ristoranti, rifugi, negozi, cime, passi, laghi). Il comune di ogni riga viene dai confini comunali di OpenStreetMap. Nelle zone francesi i civici vengono anche dalla Base Adresse Nationale, per i dipartimenti elencati in `ban` in `zone/zone.json`. Le parole sono normalizzate da `norm` in `tools/search_zone.py` (minuscole, senza accenti, solo lettere e cifre): l'app deve fare lo stesso con quello che si scrive. Le ricerche in `prove` finiscono nel log di ogni costruzione, per controllare l'indice a occhio;
- `zona.json`, il confine della zona, i quadrati di 1°×1° e i segmenti BRouter che le servono e per ogni file dimensione e sha256, così l'app riscarica solo i file cambiati.

Dopo le zone, l'azione copia i segmenti BRouter che servono a tutte le zone da brouter.de nella release `brouter-<edizione>`, così hanno la stessa data del resto e l'app non dipende da brouter.de: `indice.json` li indica in `brouter_url`, che torna a brouter.de se la copia fallisce. Costruisce poi il **terreno condiviso**: per ogni quadrato di 1°×1° toccato da una zona e non ancora pubblicato, `N44E008.hgt.gz` (le quote a 90 m) e `N44E008.curve.pmtiles` (le curve di livello), nella release della sua fascia `terreno-N44`, con il manifesto `terreno.json` che ne elenca dimensioni e sha256. Il terreno non cambia, quindi un quadrato si costruisce una volta sola, finché `CONTOURS` resta uguale. `indice.json` dà la base in `terrain_url`. Finché l'app non legge il terreno condiviso, `curve.pmtiles` e `quote.tar` restano anche dentro ogni zona.

Ogni file arriva 5 km oltre il confine della zona. Curve e quote della zona si copiano dall'edizione precedente finché `CONTOURS` nell'azione resta uguale.

La release `zone-indice` contiene `indice.json`, l'elenco delle zone con l'ultima edizione di ognuna: l'app lo legge da `https://github.com/azoto77-code/offtrack-data/releases/download/zone-indice/indice.json` e i file della zona da `<base_url>/<tag>/<file>`.
