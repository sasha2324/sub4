# Sub4

Il mio tracker per preparare una maratona sotto le 4 ore (passo 5:41 al km).
Scritto in Python con l'aiuto di Claude Code.

## L'idea

```
API Strava / Garmin  ──(una volta per corsa)──>  dati/  ──(sempre)──>  analisi
                                                  ↑
                                         archivio locale, offline
```

L'API serve solo a riempire l'archivio: ogni corsa si scarica **una volta sola**
dentro `dati/`, e da lì tutte le analisi leggono da disco. Funziona offline e
non dipende da un abbonamento.

## Cosa fa

- **Sincronizza** le corse da Strava (login OAuth 2.0) e da Garmin Connect.
- **Passo equivalente in piano**: corregge il passo per la pendenza con il
  modello di Minetti (2002), così corse con dislivelli diversi si confrontano.
- **Checkup dei dati**: completezza, coerenza, salti del GPS e del sensore
  cardio. Ha trovato due bug veri, tra cui un salto del GPS che falsava il
  record sui 5 km e quindi tutte le proiezioni di gara.
- **Piano a cancelli**: si passa alla fase successiva quando si raggiungono i
  criteri (volume, lunghi, tempo in zona facile), non a data fissa.
- **Pagina web del piano** e **report Excel**.

## Comandi

| Comando | Cosa fa |
|---|---|
| `python3 strava_sync.py` | scarica le corse nuove e aggiorna il CSV |
| `python3 strava_sync.py --offline` | ricostruisce il CSV senza internet |
| `python3 garmin_sync.py` | archivia le corse nuove da Garmin Connect |
| `python3 strava_controllo.py` | checkup completo dell'archivio |
| `python3 strava_piano.py` | a che punto sono nel piano |
| `python3 strava_piano.py --settimana` | le uscite di questa settimana |
| `python3 strava_piano.py --html` | rigenera la pagina web del piano |
| `python3 strava_pendenza.py` | prova il modello del passo corretto per la pendenza |
| `python3 strava_report.py` | report Excel |

Dopo ogni corsa:

```
python3 strava_sync.py && python3 strava_piano.py && python3 strava_piano.py --html
```

## Installazione

Serve Python 3.12 o più recente.

```
pip install requests openpyxl garminconnect
cp .env.example .env    # poi metti i tuoi valori
```

- Crea un'app Strava su <https://www.strava.com/settings/api> e copia Client ID
  e Client Secret nel `.env`.
- Al primo `strava_sync.py` si apre il browser per il login; il token resta in
  `strava_token.json`.
- Garmin chiede email e password **dal terminale** e non le salva: su disco
  restano solo i token di sessione, in `~/.garminconnect`.

## Privacy

Il repository contiene **solo il codice**. Restano fuori da git (vedi
`.gitignore`):

- credenziali e token (`.env`, `strava_token.json`);
- l'archivio delle corse, le tracce GPS e il CSV;
- il piano personale (`piano.json`) e la pagina generata;
- ogni dato di salute.

## File superati

`strava_tracker.py` e `strava_import_export.py` sono le prime versioni,
sostituite da `strava_sync.py`. `strava_import_export.py` resta come ripiego:
legge l'archivio ZIP che Strava manda su richiesta.
