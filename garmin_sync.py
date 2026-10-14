# ============================================
# GARMIN SYNC — DA GARMIN CONNECT ALL'ARCHIVIO
# ============================================
# PERCHÉ ESISTE
#   Dal 18/09/2026 l'API di Strava risponde 403 "Application / Status /
#   Inactive" su tutto tranne gli streams. Non si può più nemmeno chiedere
#   l'elenco delle corse, quindi ogni volta l'id va copiato a mano.
#   Garmin Connect quell'elenco ce l'ha, più cose che Strava non espone
#   affatto: lunghezza del passo, oscillazione verticale, sonno, HRV.
#
# LE CREDENZIALI
#   Il login lo fa l'utente, in questo terminale, con --login: la password
#   si digita e non viene mai scritta su disco né stampata. La libreria
#   salva solo i TOKEN di sessione in ~/.garminconnect, e tutti gli altri
#   comandi usano quelli. Se i token scadono, si rifà --login.
#
#   Questo script non legge password da file, da variabili d'ambiente o da
#   argomenti: è deliberato. Una password in un file è una password che
#   prima o poi finisce in un backup, in un log o in una chat.
#
# COME SI USA
#   python3 garmin_sync.py --login        una volta, e quando i token scadono
#   python3 garmin_sync.py --stato        controlla che la sessione sia viva
#   python3 garmin_sync.py --corse [n]    le ultime n attività, con gli id
#   python3 garmin_sync.py --esplora <id> cosa contiene davvero un'attività
#   python3 garmin_sync.py --tutto        corse nuove + salute (il comando
#                                         di tutti i giorni)
#   python3 garmin_sync.py --sync [n]     solo le corse nuove
#   python3 garmin_sync.py --archivia <id>  una corsa sola, anche se c'è già
#   python3 garmin_sync.py --salute [n]   sonno, recupero, battito a riposo
# ============================================

import json
import os
import sys
from datetime import date, datetime, timedelta

try:
    import garminconnect
except ImportError:
    print("✗ Manca la libreria. Installa con:")
    print("    python3 -m pip install garminconnect")
    sys.exit(1)

CARTELLA_TOKEN = os.path.expanduser("~/.garminconnect")
CARTELLA_DATI = "dati"


# ============================================
# PARTE 1 — SESSIONE
# ============================================

class _SenzaTerminale(Exception):
    """Nessun modo di far digitare la password a un essere umano."""


def _chiedi(domanda, nascosto=False):
    """Una domanda a chi sta davanti allo schermo.

    Prima si prova lo standard input; se è chiuso — come quando il comando
    parte da dentro un altro programma — si apre /dev/tty, che è il terminale
    vero e a volte resta leggibile anche quando stdin non lo è. Se non c'è
    nemmeno quello, non esiste nessuno a cui chiedere e si dice perché.
    """
    import getpass

    if sys.stdin and sys.stdin.isatty():
        # getpass spegne l'eco: la password non compare mai sullo schermo.
        return getpass.getpass(domanda) if nascosto else input(domanda).strip()

    try:
        tty = open("/dev/tty", "r+")
    except OSError as errore:
        raise _SenzaTerminale from errore

    with tty:
        if nascosto:
            return getpass.getpass(domanda, stream=tty)
        tty.write(domanda)
        tty.flush()
        risposta = tty.readline().strip()
        if not risposta:
            raise _SenzaTerminale
        return risposta


def _chiedi_credenziali():
    """Email e password, da chi sta al terminale e mai da un file."""
    return (_chiedi("Email Garmin: "),
            _chiedi("Password (non viene mostrata): ", nascosto=True))


def accedi(interattivo=False):
    """
    Restituisce un client autenticato.

    Prima prova i token salvati; solo con interattivo=True chiede le
    credenziali, e le chiede a chi sta al terminale — mai a un file.
    """
    # Senza token salvati non si tenta nemmeno: login() andrebbe in rete e
    # ogni tentativo a vuoto consuma il limite di Garmin, che blocca per IP.
    if os.path.isdir(CARTELLA_TOKEN) and os.listdir(CARTELLA_TOKEN):
        try:
            api = garminconnect.Garmin()
            api.login(CARTELLA_TOKEN)
            return api
        except Exception as errore:                      # noqa: BLE001
            if not interattivo:
                print(f"⚠ I token salvati non funzionano più: {errore}")
                return None
    elif not interattivo:
        return None

    print("\n--- Accesso a Garmin Connect ---")
    print("La password si digita qui e non viene salvata: sul disco finiscono")
    print(f"solo i token di sessione, in {CARTELLA_TOKEN}\n")

    try:
        email, password = _chiedi_credenziali()
    except _SenzaTerminale:
        print("✗ Questo comando ha bisogno di un terminale vero: qui lo standard")
        print("  input è chiuso, e la password non si può digitare.")
        print()
        print("  Apri Terminale (o iTerm) e lancia:")
        print(f"    cd {os.getcwd()}")
        print("    python3 garmin_sync.py --login")
        print()
        print("  Poi torna qui: i token restano salvati e li uso da solo.")
        return None

    # NIENTE return_on_mfa: con quel parametro la libreria esce appena ottenuto
    # il token e salta sia il salvataggio su disco sia il caricamento del
    # profilo (garminconnect/__init__.py, ramo alle righe 72-79). Il risultato
    # era un login riuscito che lasciava la cartella vuota e get_full_name() a
    # None. Il codice di verifica si chiede invece con prompt_mfa, che resta
    # dentro il percorso normale.
    #
    # retry_attempts=1 perché il default ne fa tre per strategia: con cinque
    # strategie sono quindici chiamate di login, ed è così che si finisce nel
    # limite di Garmin.
    os.makedirs(CARTELLA_TOKEN, exist_ok=True)
    api = garminconnect.Garmin(
        email=email, password=password, retry_attempts=1,
        prompt_mfa=lambda: _chiedi("Codice di verifica (app o SMS): "))
    try:
        # Il percorso si passa QUI: la libreria salva i token da sola dopo un
        # login riuscito. Non c'è nessun dump da fare a mano.
        risultato = api.login(CARTELLA_TOKEN)
    except Exception as errore:                          # noqa: BLE001
        testo = str(errore)
        if "429" in testo or "TooManyRequests" in testo:
            print("✗ TUTTE le strategie di accesso sono state limitate (429).")
            print("  NON è la password sbagliata: è un limite per indirizzo IP.")
            print("  Aspetta almeno un'ora. Ogni tentativo fa ripartire il")
            print("  contatore, quindi riprovare adesso allunga l'attesa.")
            print()
            print("  (i 429 sulle singole strategie sono normali: la libreria")
            print("   ne prova cinque e basta che una passi.)")
        else:
            print(f"✗ Accesso fallito: {type(errore).__name__}: {errore}")
        return None
    finally:
        del password                                     # non resta in giro

    # Non basta che login() non sollevi: con il limite di Garmin torna senza
    # errore e senza token, e stampare "✓ salvati" sarebbe una bugia. Si
    # verifica chiedendo davvero qualcosa all'API.
    try:
        nome = api.get_full_name()
        # None non è un successo: con il limite attivo la chiamata torna vuota
        # invece di sollevare, e "Sessione attiva — None" è una bugia.
        if not nome:
            raise RuntimeError("l'API non ha restituito il profilo")
    except Exception as errore:                          # noqa: BLE001
        testo = str(errore)
        print("✗ Il login non è andato a buon fine.")
        if "429" in testo or "TooManyRequests" in testo:
            print("  Garmin sta ancora limitando questo indirizzo (429).")
        else:
            print(f"  {type(errore).__name__}: {errore}")
        return None

    salvati = os.path.isdir(CARTELLA_TOKEN) and os.listdir(CARTELLA_TOKEN)
    if not salvati:
        print("⚠ Accesso riuscito ma nessun token su disco: la prossima volta")
        print("  dovrai rifare il login.")
    else:
        print(f"✓ Token salvati in {CARTELLA_TOKEN}")
    print(f"✓ Sessione attiva — {nome}")
    return api


def stato():
    api = accedi()
    if not api:
        print("✗ Nessuna sessione valida. Fai: python3 garmin_sync.py --login")
        return 1
    try:
        nome = api.get_full_name()
        print(f"✓ Sessione attiva — {nome}")
    except Exception as errore:                          # noqa: BLE001
        print(f"⚠ Sessione presente ma l'API non risponde: {errore}")
        return 1
    return 0


# ============================================
# PARTE 2 — LE ATTIVITÀ
# ============================================

def elenca(quante=10):
    """L'elenco che Strava non può più darmi: id, data, ora, distanza."""
    api = accedi()
    if not api:
        print("✗ Nessuna sessione. Fai prima: python3 garmin_sync.py --login")
        return 1

    attivita = api.get_activities(0, quante)
    print(f"\n{'id':14}{'data':12}{'ora':7}{'km':>7}{'durata':>9}  tipo")
    for a in attivita:
        inizio = a.get("startTimeLocal", "")
        km = (a.get("distance") or 0) / 1000
        sec = int(a.get("duration") or 0)
        print(f"{a.get('activityId'):<14}{inizio[:10]:12}{inizio[11:16]:7}"
              f"{km:7.2f}{sec // 60:6d}:{sec % 60:02d}  "
              f"{(a.get('activityType') or {}).get('typeKey', '?')}")
    return 0


def esplora(id_attivita):
    """
    Cosa contiene davvero un'attività: serve a sapere cosa si può archiviare
    prima di scrivere il codice che lo archivia.
    """
    api = accedi()
    if not api:
        print("✗ Nessuna sessione. Fai prima: python3 garmin_sync.py --login")
        return 1

    print(f"\n=== RIEPILOGO {id_attivita} ===")
    riepilogo = api.get_activity(id_attivita)
    interessanti = [
        "activityName", "startTimeLocal", "distance", "duration",
        "movingDuration", "elevationGain", "averageHR", "maxHR",
        "averageRunningCadenceInStepsPerMinute", "avgStrideLength",
        "avgVerticalOscillation", "avgVerticalRatio", "avgGroundContactTime",
        "calories", "vO2MaxValue", "aerobicTrainingEffect",
        "anaerobicTrainingEffect", "avgPower", "trainingStressScore",
    ]
    riassunto = riepilogo.get("summaryDTO", riepilogo)
    for chiave in interessanti:
        valore = riassunto.get(chiave, riepilogo.get(chiave))
        if valore is not None:
            print(f"  {chiave:42} {valore}")

    print(f"\n=== CAMPI PER CAMPIONE ===")
    try:
        dettagli = api.get_activity_details(id_attivita, maxchart=10, maxpoly=10)
        misure = dettagli.get("metricDescriptors") or []
        print(f"  {len(misure)} metriche disponibili secondo per secondo:")
        for m in misure:
            print(f"    {m.get('key')}")
        print(f"  campioni totali: {len((dettagli.get('activityDetailMetrics') or []))} "
              f"(limitati a 10 da questa chiamata di prova)")
    except Exception as errore:                          # noqa: BLE001
        print(f"  ✗ dettagli non disponibili: {errore}")
    return 0


# ============================================
# PARTE 3 — DALL'API ALL'ARCHIVIO
# ============================================
# I file prodotti qui hanno la STESSA FORMA di quelli che scriveva
# strava_sync.py: il resto della pipeline (CSV, piano, pendenza, controllo)
# non deve sapere da dove arrivano i dati. Le metriche che Strava non ha mai
# dato — lunghezza del passo, oscillazione verticale, potenza, temperatura —
# si aggiungono in più, senza togliere niente.

CARTELLA_ATTIVITA = os.path.join(CARTELLA_DATI, "attivita")
CARTELLA_STREAMS = os.path.join(CARTELLA_DATI, "streams")

# Garmin → nomi degli streams già usati nell'archivio. A sinistra la chiave
# dell'API, a destra come la chiama il resto del progetto.
STREAM_DA_GARMIN = {
    "directHeartRate":           "heartrate",
    "directSpeed":               "velocity_smooth",
    "directElevation":           "altitude",
    "sumDistance":               "distance",
    # Le nuove: nessuna di queste esisteva prima.
    "directStrideLength":        "stride_length",
    "directVerticalOscillation": "vertical_oscillation",
    "directVerticalRatio":       "vertical_ratio",
    "directGroundContactTime":   "ground_contact_time",
    "directPower":               "power",
    # ⚠ NON è la temperatura dell'aria, per quanto Garmin la chiami così.
    # È il sensore dell'orologio, che sta al polso contro la pelle: misura il
    # braccio. Misurato su due giorni in cui l'aria vera era nota, legge
    # +11 e +12 °C di troppo (11/10: sensore 27,4 con 15-17 di aria;
    # 14/10: sensore 19,2 con 6-8 di aria).
    #
    # Per settimane ho citato questi numeri come se fossero l'aria, e ci ho
    # costruito sopra dei ragionamenti («a 30 gradi tenere 135 di media vale
    # di più») che erano sbagliati: faceva 18. Se serve la temperatura vera
    # va chiesta a una previsione, non a questo campo. Qui si tiene perché
    # le VARIAZIONI dentro una stessa corsa restano informative — quando sale
    # di 7 gradi in salita, è il sole o la mancanza d'aria — ma il valore
    # assoluto no.
    "directAirTemperature":      "temperature",
}


def _tolleranza(a, b, quanto=0.02):
    return a and b and abs(a - b) <= max(a, b) * quanto


def _gia_archiviata(data, metri):
    """L'id del file che descrive già questa corsa, se c'è.

    Serve perché la stessa corsa ha id diversi su Garmin e su Strava: senza
    questo controllo la corsa del 22/09, già archiviata dagli streams di
    Strava, tornerebbe in archivio una seconda volta."""
    import glob
    for percorso in glob.glob(os.path.join(CARTELLA_ATTIVITA, "*.json")):
        try:
            with open(percorso) as f:
                det = (json.load(f).get("dettaglio") or {})
        except (json.JSONDecodeError, OSError):
            continue
        if det.get("start_date_local", "")[:10] != data:
            continue
        if _tolleranza(det.get("distance"), metri):
            return str(det.get("id"))
    return None


def archivia(id_attivita, sostituisci=True):
    """Scarica una corsa da Garmin e la scrive nell'archivio locale."""
    api = accedi()
    if not api:
        print("✗ Nessuna sessione. Fai prima: python3 garmin_sync.py --login")
        return None

    print(f"• Corsa {id_attivita} da Garmin Connect...")
    sommario = api.get_activity(id_attivita)
    riassunto = sommario.get("summaryDTO", sommario)
    dettagli = api.get_activity_details(id_attivita, maxchart=20000, maxpoly=0)

    indici = {m["key"]: m["metricsIndex"]
              for m in dettagli.get("metricDescriptors") or []}
    campioni = [r.get("metrics") or [] for r in
                dettagli.get("activityDetailMetrics") or []]
    if not campioni:
        print("  ✗ Nessun campione secondo per secondo.")
        return None

    def colonna(chiave):
        i = indici.get(chiave)
        if i is None:
            return None
        return [(c[i] if i < len(c) else None) for c in campioni]

    streams = {}
    for chiave_garmin, nome in STREAM_DA_GARMIN.items():
        valori = colonna(chiave_garmin)
        if valori and any(v is not None for v in valori):
            streams[nome] = valori

    # Il tempo: Strava lo dà in secondi dalla partenza, Garmin in millisecondi
    # assoluti. Si usa sumDuration quando c'è, che è già relativo.
    durata = colonna("sumDuration")
    if durata and durata[0] is not None:
        streams["time"] = [int(x) if x is not None else None for x in durata]
    else:
        ts = colonna("directTimestamp") or []
        base = next((x for x in ts if x), 0)
        streams["time"] = [int((x - base) / 1000) if x else None for x in ts]

    lat, lon = colonna("directLatitude"), colonna("directLongitude")
    if lat and lon:
        streams["latlng"] = [[a, b] if a is not None and b is not None else None
                             for a, b in zip(lat, lon)]

    # La cadenza di Garmin è a due gambe; l'archivio la tiene a una, come
    # Strava, e chi legge raddoppia. Meglio una convenzione sola.
    doppia = colonna("directDoubleCadence")
    if doppia:
        streams["cadence"] = [x / 2 if x else x for x in doppia]

    metri = riassunto.get("distance") or sommario.get("distance") or 0
    inizio = (riassunto.get("startTimeLocal") or
              sommario.get("startTimeLocal") or "")[:19].replace(" ", "T")
    cadenza = riassunto.get("averageRunningCadenceInStepsPerMinute")
    if not cadenza and streams.get("cadence"):
        # Il riepilogo non sempre la porta (assente sull'allenamento del
        # 23/09), ma negli streams c'è: la si media da lì. Gli streams la
        # tengono già a una gamba, quindi qui si raddoppia per restare nella
        # convenzione del riepilogo — che poi viene dimezzata sotto.
        passi = [c for c in streams["cadence"] if c]
        if passi:
            cadenza = sum(passi) / len(passi) * 2

    dettaglio = {
        "id": id_attivita,
        "name": sommario.get("activityName") or "Corsa",
        "type": "Run",
        "start_date_local": inizio + "Z" if inizio else "",
        "distance": metri,
        "moving_time": round(riassunto.get("movingDuration") or
                             riassunto.get("duration") or 0),
        "elapsed_time": round(riassunto.get("duration") or 0),
        "total_elevation_gain": riassunto.get("elevationGain") or 0,
        "average_heartrate": riassunto.get("averageHR"),
        "max_heartrate": riassunto.get("maxHR"),
        "calories": riassunto.get("calories"),
        # Garmin la dà a due gambe: si dimezza per la convenzione dell'archivio.
        "average_cadence": cadenza / 2 if cadenza else None,
        "device_name": "Garmin Forerunner 165",
        # Lo sforzo relativo è di Strava e non esiste qui. Resta vuoto invece
        # di essere sostituito da un indice Garmin che misura un'altra cosa.
        "suffer_score": None,
        "best_efforts": [],
        "splits_metric": [],
        "da_garmin": True,
    }

    vecchio = _gia_archiviata(dettaglio["start_date_local"][:10], metri)
    if vecchio and str(vecchio) != str(id_attivita):
        if not sostituisci:
            print(f"  · già in archivio come {vecchio}, non tocco niente")
            return None
        for cartella in (CARTELLA_ATTIVITA, CARTELLA_STREAMS):
            percorso = os.path.join(cartella, f"{vecchio}.json")
            if os.path.exists(percorso):
                os.remove(percorso)
        print(f"  · sostituisco la versione da Strava ({vecchio}): "
              f"quella di Garmin ha più dati")

    os.makedirs(CARTELLA_ATTIVITA, exist_ok=True)
    os.makedirs(CARTELLA_STREAMS, exist_ok=True)
    with open(os.path.join(CARTELLA_STREAMS, f"{id_attivita}.json"), "w") as f:
        json.dump(streams, f)
    with open(os.path.join(CARTELLA_ATTIVITA, f"{id_attivita}.json"),
              "w", encoding="utf-8") as f:
        json.dump({
            "dettaglio": dettaglio,
            "zone": [],                       # premium Strava: non esistono qui
            "fonte": "garmin",
            "scaricato_il": datetime.now().isoformat(timespec="seconds"),
        }, f, indent=2, ensure_ascii=False)

    km = metri / 1000
    sec = dettaglio["moving_time"]
    extra = [n for n in ("stride_length", "vertical_oscillation",
                         "ground_contact_time", "power", "temperature")
             if n in streams]
    print(f"  ✓ {km:.2f} km · {sec // 60}:{sec % 60:02d} · "
          f"FC {dettaglio['average_heartrate'] or '—'} · "
          f"{len(campioni)} campioni")
    print(f"    metriche nuove: {', '.join(extra)}")
    return id_attivita


def sincronizza(quante=10):
    """Archivia tutte le corse nuove, senza che nessuno copi id a mano."""
    api = accedi()
    if not api:
        print("✗ Nessuna sessione. Fai prima: python3 garmin_sync.py --login")
        return 1

    nuove = 0
    for a in api.get_activities(0, quante):
        if (a.get("activityType") or {}).get("typeKey") not in (
                "running", "trail_running", "treadmill_running"):
            continue
        idc = str(a.get("activityId"))
        if os.path.exists(os.path.join(CARTELLA_ATTIVITA, f"{idc}.json")):
            continue
        if archivia(idc):
            nuove += 1

    print(f"\n✓ {nuove} corse nuove in archivio." if nuove
          else "\n✓ Archivio già aggiornato.")
    if nuove:
        print("  Ora: python3 strava_sync.py --offline")
    return 0


# ============================================
# PARTE 4 — LA SALUTE, GIORNO PER GIORNO
# ============================================
# Scrive nello STESSO file che riempie l'import da Salute di Apple
# (dati/salute/giorni.json): due sorgenti, un archivio solo. Le chiavi sono
# quelle già usate da strava_salute.py, così il riepilogo e gli allarmi
# funzionano senza sapere chi ha scritto il dato.
#
# Garmin aggiunge quello che Apple non dava: stress, body battery, punteggio
# del sonno, frequenza respiratoria notturna.

FILE_SALUTE = os.path.join(CARTELLA_DATI, "salute", "giorni.json")


def _minuti(secondi):
    return round(secondi / 60) if secondi else None


def _giorno_di_salute(api, giorno):
    """Tutto quello che Garmin sa di una giornata, nei nomi dell'archivio."""
    voce = {}

    # --- sonno ---
    try:
        sonno = (api.get_sleep_data(giorno) or {}).get("dailySleepDTO") or {}
    except Exception:                                    # noqa: BLE001
        sonno = {}
    for chiave, nome in (("sleepTimeSeconds", "sonno_notte_min"),
                         ("deepSleepSeconds", "sonno_profondo_min"),
                         ("lightSleepSeconds", "sonno_leggero_min"),
                         ("remSleepSeconds", "sonno_rem_min"),
                         ("awakeSleepSeconds", "sveglio_min")):
        m = _minuti(sonno.get(chiave))
        if m:
            voce[nome] = m
    if voce.get("sonno_notte_min"):
        voce["sonno_min"] = voce["sonno_notte_min"]
    punteggi = sonno.get("sleepScores") or {}
    complessivo = (punteggi.get("overall") or {}).get("value")
    if complessivo:
        voce["punteggio_sonno"] = complessivo
    if sonno.get("averageRespirationValue"):
        voce["respiro_notte"] = sonno["averageRespirationValue"]
    if sonno.get("averageSpO2Value"):
        voce["ossigeno"] = sonno["averageSpO2Value"]

    # --- battito a riposo, passi, calorie ---
    try:
        stats = api.get_stats_and_body(giorno) or {}
    except Exception:                                    # noqa: BLE001
        stats = {}
    for chiave, nome in (("restingHeartRate", "fc_riposo"),
                         ("totalSteps", "passi"),
                         ("totalKilocalories", "calorie"),
                         ("minHeartRate", "fc_minima"),
                         ("maxHeartRate", "fc_massima_giorno"),
                         ("averageStressLevel", "stress"),
                         ("bodyBatteryMostRecentValue", "body_battery"),
                         ("bodyBatteryHighestValue", "body_battery_max"),
                         ("bodyBatteryLowestValue", "body_battery_min")):
        v = stats.get(chiave)
        if v is not None and v != -1:
            voce[nome] = v

    # --- HRV notturno: il dato di recupero che conta ---
    try:
        hrv = api.get_hrv_data(giorno) or {}
        riassunto = hrv.get("hrvSummary") or {}
        if riassunto.get("lastNightAvg"):
            voce["hrv"] = riassunto["lastNightAvg"]
        if riassunto.get("status"):
            voce["hrv_stato"] = riassunto["status"]
    except Exception:                                    # noqa: BLE001
        pass

    # Chi ha misurato, sempre. Apple e Garmin NON misurano allo stesso modo:
    # sullo stesso polso il battito a riposo può differire di molti battiti,
    # e l'HRV di Apple è SDNN mentre Garmin usa RMSSD — numeri diversi per
    # definizione. Senza questo campo la serie storica mostrerebbe un
    # miglioramento che è solo un cambio di sensore.
    if voce:
        voce["fonte"] = "garmin"
    return voce


def salute(giorni=7):
    """Archivia gli ultimi N giorni di dati di salute."""
    api = accedi()
    if not api:
        print("✗ Nessuna sessione. Fai prima: python3 garmin_sync.py --login")
        return 1

    archivio = {}
    if os.path.exists(FILE_SALUTE):
        try:
            with open(FILE_SALUTE) as f:
                archivio = json.load(f)
        except (json.JSONDecodeError, OSError):
            archivio = {}

    nuovi = aggiornati = 0
    for indietro in range(giorni):
        giorno = (date.today() - timedelta(days=indietro)).isoformat()
        voce = _giorno_di_salute(api, giorno)
        if not voce:
            continue
        if giorno in archivio:
            # I dati di Garmin vincono su quelli di Apple per lo stesso
            # giorno: misurano lo stesso polso con un sensore migliore, e
            # hanno campi che Apple non ha. Ma non si cancella nulla: le
            # chiavi che Garmin non fornisce restano quelle di prima.
            prima = dict(archivio[giorno])
            archivio[giorno] = {**prima, **voce}
            if archivio[giorno] != prima:
                aggiornati += 1
        else:
            archivio[giorno] = voce
            nuovi += 1

    os.makedirs(os.path.dirname(FILE_SALUTE), exist_ok=True)
    with open(FILE_SALUTE, "w") as f:
        json.dump(dict(sorted(archivio.items())), f, indent=2)

    print(f"✓ Salute: {nuovi} giorni nuovi, {aggiornati} aggiornati "
          f"· {len(archivio)} in archivio")
    print("  Vedi tutto con: python3 strava_salute.py")
    return 0


def tutto(giorni_salute=21):
    """Corse nuove + salute, in un colpo solo. È il comando di tutti i giorni.

    La salute si ripesca sempre a ritroso di tre settimane: Garmin conserva
    lo storico, quindi chiedere indietro non costa niente e copre i giorni in
    cui non ci siamo sentiti. Non serve passare di qui ogni giorno.
    """
    esito = sincronizza()
    print()
    salute(giorni_salute)
    return esito


# ============================================
# MAIN
# ============================================

def main():
    if "--login" in sys.argv:
        return 0 if accedi(interattivo=True) else 1
    if "--stato" in sys.argv:
        return stato()
    if "--esplora" in sys.argv:
        i = sys.argv.index("--esplora")
        if i + 1 >= len(sys.argv):
            print("✗ Manca l'id: --esplora <id>")
            return 1
        return esplora(sys.argv[i + 1])
    if "--archivia" in sys.argv:
        i = sys.argv.index("--archivia")
        if i + 1 >= len(sys.argv):
            print("✗ Manca l'id: --archivia <id>")
            return 1
        return 0 if archivia(sys.argv[i + 1]) else 1
    if "--tutto" in sys.argv:
        return tutto()
    if "--salute" in sys.argv:
        i = sys.argv.index("--salute")
        giorni = 7
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            giorni = int(sys.argv[i + 1])
        return salute(giorni)
    if "--sync" in sys.argv:
        i = sys.argv.index("--sync")
        quante = 10
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            quante = int(sys.argv[i + 1])
        return sincronizza(quante)
    if "--corse" in sys.argv:
        i = sys.argv.index("--corse")
        quante = 10
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            quante = int(sys.argv[i + 1])
        return elenca(quante)

    print(__doc__ or "")
    print("Comandi: --tutto · --login · --stato · --sync [n] · --corse [n] · "
          "--archivia <id> · --salute [n] · --esplora <id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
