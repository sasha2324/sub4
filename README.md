# Sub4

Il mio tracker per preparare una maratona sotto le 4 ore (passo 5:41 al km).

**Cosa fa:** scarica le mie corse da Strava e Garmin Connect in un archivio locale (una volta
per corsa: poi le analisi funzionano offline) e le confronta con il piano di allenamento.

- **Passo equivalente in piano**: corregge il passo per la pendenza con il modello di
  Minetti (2002), così corse con dislivelli diversi si confrontano.
- **Checkup dei dati**: completezza, coerenza, salti del GPS e del sensore cardio.
- **Piano a cancelli**: si passa alla fase successiva quando si raggiungono i criteri
  (volume, lunghi, tempo in zona facile), non a data fissa.
- **Pagina web del piano** e **report Excel**.

**Con cosa è fatto:** Python 3.12+, API di Strava (OAuth 2.0), Garmin Connect, CSV e JSON,
openpyxl per l'Excel. Scritto con l'aiuto di Claude Code.

**Stato:** in uso durante la preparazione della maratona.

## Avviarlo

```
pip install requests openpyxl garminconnect
cp .env.example .env    # poi metti i tuoi valori
```

- Crea un'app Strava su <https://www.strava.com/settings/api> e copia Client ID e
  Client Secret nel `.env`. Al primo `strava_sync.py` si apre il browser per il login;
  il token resta in `strava_token.json`.
- Garmin chiede email e password **dal terminale** e non le salva: su disco restano solo
  i token di sessione, in `~/.garminconnect`.

Dopo ogni corsa:

```
python3 strava_sync.py && python3 strava_piano.py && python3 strava_piano.py --html
```

| Comando | Cosa fa |
|---|---|
| `python3 strava_sync.py` | scarica le corse nuove e aggiorna il CSV (`--offline`: senza internet) |
| `python3 garmin_sync.py` | archivia le corse nuove da Garmin Connect |
| `python3 strava_controllo.py` | checkup completo dell'archivio |
| `python3 strava_piano.py` | a che punto sono nel piano (`--settimana`, `--html`) |
| `python3 strava_pendenza.py` | prova il modello del passo corretto per la pendenza |
| `python3 strava_report.py` | report Excel |

`strava_tracker.py` e `strava_import_export.py` sono le prime versioni, sostituite da
`strava_sync.py`; la seconda resta come ripiego per l'archivio ZIP che Strava manda su richiesta.

## Privacy

Il repository contiene **solo il codice**. Restano fuori da git (vedi `.gitignore`)
credenziali e token, l'archivio delle corse, le tracce GPS e il CSV, il piano personale
e la pagina generata, ogni dato di salute.
