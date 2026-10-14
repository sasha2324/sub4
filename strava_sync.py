# ============================================
# STRAVA SYNC — API → ARCHIVIO LOCALE → CSV
# ============================================
# Questo script sostituisce strava_tracker.py e strava_import_export.py.
#
# IDEA DI FONDO (importante):
#   L'abbonamento premium è una prova gratuita e scade.
#   Quindi NON analizziamo mai "in diretta" dall'API: scarichiamo
#   tutto una volta sola dentro la cartella 'dati/' e da lì in poi
#   lavoriamo sull'archivio locale, che resta tuo per sempre.
#
#   API  ──(una volta)──>  dati/  ──(sempre)──>  strava_corse.csv ──> analisi
#
# COME SI USA:
#   python3 strava_sync.py               scarica il nuovo e aggiorna il CSV
#   python3 strava_sync.py --offline     ricostruisce il CSV senza internet
#   python3 strava_sync.py --riautorizza rifà il login (per le zone FC personali)
#   python3 strava_sync.py --rileggi     riscarica anche ciò che è già in archivio
#
#   python3 strava_sync.py --corsa <id|url> [--data AAAA-MM-GG] [--ora HH:MM] [--nome "..."]
#       archivia UNA corsa dai soli streams. Da usare da quando l'API
#       risponde 403 "Application / Status / Inactive" su tutto tranne
#       '/activities/{id}/streams': l'elenco delle corse non si può più
#       chiedere, quindi l'id va preso dall'URL della corsa su Strava.
# ============================================

import requests
import json
import csv
import os
import sys
import time
import glob
import webbrowser
import threading
import strava_pendenza
import impostazioni
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# --- CREDENZIALI DELL'APP STRAVA (dal file .env, mai nel codice) ---
CLIENT_ID     = impostazioni.leggi("STRAVA_CLIENT_ID", "INSERISCI_QUI")
CLIENT_SECRET = impostazioni.leggi("STRAVA_CLIENT_SECRET", "INSERISCI_QUI")

TOKEN_FILE = "strava_token.json"
OUTPUT_CSV = "strava_corse.csv"

# --- L'ARCHIVIO LOCALE: il cuore di tutto ---
CARTELLA_DATI     = "dati"
CARTELLA_ATTIVITA = os.path.join(CARTELLA_DATI, "attivita")   # dettaglio + zone
CARTELLA_STREAMS  = os.path.join(CARTELLA_DATI, "streams")    # dati secondo per secondo
FILE_ATLETA       = os.path.join(CARTELLA_DATI, "atleta.json")
FILE_SOGLIE       = os.path.join(CARTELLA_DATI, "soglie_zone.json")

# Frequenza cardiaca massima di riferimento: è un dato personale, sta nel .env.
HR_MASSIMA = int(impostazioni.leggi("HR_MASSIMA", "190"))

# Percentuali di HR max che Strava usa per separare le 5 zone.
# Ricavate dalle soglie vere archiviate mentre il premium era attivo.
PERCENTUALI_ZONE = [0.0, 0.673, 0.837, 0.918, 1.0]

# Chiediamo tutti i permessi utili. 'profile:read_all' serve solo per
# leggere le TUE zone cardiache personalizzate (/athlete/zones).
SCOPE_COMPLETO = "activity:read_all,profile:read_all,read"

# Tipi di attività che consideriamo "corsa".
TIPI_CORSA = {"Run", "TrailRun", "VirtualRun"}

# Quali dati secondo-per-secondo scaricare per ogni corsa.
STREAMS_VOLUTI = "time,distance,heartrate,velocity_smooth,altitude,cadence,latlng,grade_smooth,moving"

# Strava consente 100 richieste ogni 15 minuti. Ogni corsa ne costa 3,
# quindi ci fermiamo prima di sbattere contro il muro.
PAUSA_TRA_CHIAMATE = 0.3


# ============================================
# PARTE 1 — AUTENTICAZIONE
# ============================================

codice_autorizzazione = None


class StravaCatcher(BaseHTTPRequestHandler):
    """Server locale che cattura il codice che Strava manda dopo l'autorizzazione."""

    def do_GET(self):
        global codice_autorizzazione
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            codice_autorizzazione = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("""
                <html><body style='font-family:Arial;text-align:center;padding:50px'>
                <h2>&#10003; Autorizzazione completata!</h2>
                <p>Puoi chiudere questa scheda e tornare al terminale.</p>
                </body></html>
            """.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def salva_token(nuovo, precedente=None):
    """
    Salva il token su disco. Il rinnovo non restituisce i dati dell'atleta:
    li recuperiamo da quelli vecchi così non li perdiamo.
    """
    if precedente and "athlete" not in nuovo:
        nuovo["athlete"] = precedente.get("athlete", {})
    with open(TOKEN_FILE, "w") as f:
        json.dump(nuovo, f, indent=2)


def autorizza(scope=SCOPE_COMPLETO):
    """Flusso OAuth completo: apre il browser e ottiene un token nuovo."""
    global codice_autorizzazione
    codice_autorizzazione = None

    url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        "&redirect_uri=http://localhost:8080"
        "&response_type=code"
        "&approval_prompt=force"
        f"&scope={scope}"
    )

    print("\n--- Autorizzazione Strava ---")
    print("Apro il browser. Autorizza l'app e torna qui.\n")
    print(f"Se non si apre, incolla questo URL:\n{url}\n")

    server = HTTPServer(("localhost", 8080), StravaCatcher)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    webbrowser.open(url)
    thread.join(timeout=180)

    if not codice_autorizzazione:
        print("✗ Timeout: autorizzazione non completata.")
        return None

    risposta = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          codice_autorizzazione,
        "grant_type":    "authorization_code",
    })
    if risposta.status_code != 200:
        print(f"✗ Errore nello scambio del codice: {risposta.status_code} — {risposta.text}")
        return None

    dati = risposta.json()
    salva_token(dati)
    print(f"✓ Token ottenuto. Permessi: {dati.get('scope', '?')}")
    return dati["access_token"]


def ottieni_token(forza_riautorizzazione=False):
    """
    Restituisce un access_token valido:
    riusa quello salvato, lo rinnova se scaduto, o rifà il login.
    """
    if forza_riautorizzazione:
        return autorizza()

    if not os.path.exists(TOKEN_FILE):
        return autorizza()

    with open(TOKEN_FILE) as f:
        token = json.load(f)

    # Ancora valido? (60 secondi di margine)
    if token.get("expires_at", 0) > time.time() + 60:
        return token["access_token"]

    print("• Token scaduto — lo rinnovo...")
    risposta = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": token.get("refresh_token"),
        "grant_type":    "refresh_token",
    })
    if risposta.status_code != 200:
        print(f"✗ Rinnovo fallito: {risposta.status_code}. Rifaccio il login.")
        return autorizza()

    nuovo = risposta.json()
    salva_token(nuovo, precedente=token)
    print("✓ Token rinnovato.")
    return nuovo["access_token"]


def permessi_attuali():
    """Legge dal token salvato quali permessi abbiamo concesso."""
    if not os.path.exists(TOKEN_FILE):
        return ""
    with open(TOKEN_FILE) as f:
        return json.load(f).get("scope", "")


# ============================================
# PARTE 2 — CHIAMATE ALL'API
# ============================================

class LimiteRaggiunto(Exception):
    """Strava ci ha bloccato per troppe richieste: ci fermiamo e salviamo."""


def chiama(token, percorso, parametri=None):
    """
    Una GET all'API di Strava.
    Restituisce (dati, None) se va bene, (None, motivo) se fallisce.
    Non solleva eccezioni tranne quando finiamo il limite di richieste.
    """
    try:
        risposta = requests.get(
            "https://www.strava.com/api/v3" + percorso,
            headers={"Authorization": f"Bearer {token}"},
            params=parametri or {},
            timeout=30,
        )
    except requests.RequestException as e:
        return None, f"rete: {e}"

    if risposta.status_code == 200:
        return risposta.json(), None
    if risposta.status_code == 429:
        raise LimiteRaggiunto()
    if risposta.status_code in (401, 403):
        return None, f"{risposta.status_code} accesso negato"
    if risposta.status_code == 404:
        return None, "404 non trovata"
    return None, f"{risposta.status_code}"


def stato_account(token):
    """Chi siamo e, soprattutto, se il premium è ancora attivo."""
    atleta, errore = chiama(token, "/athlete")
    if errore:
        return None, errore
    os.makedirs(CARTELLA_DATI, exist_ok=True)
    with open(FILE_ATLETA, "w", encoding="utf-8") as f:
        json.dump(atleta, f, indent=2, ensure_ascii=False)
    return atleta, None


def elenca_corse(token):
    """Scorre tutte le pagine di /athlete/activities e tiene solo le corse."""
    corse = []
    pagina = 1
    while True:
        dati, errore = chiama(token, "/athlete/activities",
                              {"per_page": 100, "page": pagina})
        if errore:
            print(f"✗ Errore nell'elenco attività: {errore}")
            break
        if not dati:
            break
        corse.extend(a for a in dati if a.get("type") in TIPI_CORSA)
        if len(dati) < 100:
            break
        pagina += 1
        time.sleep(PAUSA_TRA_CHIAMATE)
    return corse


# ============================================
# PARTE 2-bis — RIPIEGO: UNA CORSA DAI SOLI STREAMS
# ============================================
# Dal 18/09/2026 l'API risponde 403 "Application / Status / Inactive" su
# TUTTO tranne '/activities/{id}/streams'. Non si può più nemmeno elencare
# le corse, quindi l'id va fornito a mano (sta nell'URL della corsa su
# Strava: strava.com/activities/NUMERO).
#
# Dagli streams si ricostruisce quasi tutto il dettaglio. Si perde solo
# quello che Strava calcola da sé: calorie, sforzo relativo, nome, attrezzo
# e i suoi best effort — che però ricalcoliamo noi dalla traccia.

# Su quanti campioni lisciare la quota prima di sommare le salite. Sommare
# i dislivelli grezzi conta il rumore dell'altimetro: su una corsa piana da
# 19 m di D+ vero dava 32 m (+71%). Calibrato sulle 18 corse 2026 di cui
# conosciamo il valore vero di Strava: con 61 campioni l'errore medio scende
# al 4% e il massimo al 9%, e funziona sia sul piano sia sul trail da 608 m.
# Finestre più corte (31) o più lunghe (101) peggiorano entrambe.
FINESTRA_QUOTA = 61


def _salita(quote):
    """Il dislivello positivo, lisciando prima la quota."""
    if not quote:
        return 0.0
    if len(quote) < FINESTRA_QUOTA:
        return sum(max(0.0, quote[i] - quote[i - 1]) for i in range(1, len(quote)))

    meta = FINESTRA_QUOTA // 2
    lisce = []
    for i in range(len(quote)):
        finestra = quote[max(0, i - meta):i + meta + 1]
        lisce.append(sum(finestra) / len(finestra))
    return sum(max(0.0, lisce[i] - lisce[i - 1]) for i in range(1, len(lisce)))


def dettaglio_da_streams(id_corsa, streams, data=None, nome=None, ora=None):
    """
    Ricostruisce un dettaglio di attività dai soli streams.

    'moving_time' si deriva dalla velocità e non dal flag 'moving', per la
    stessa ragione documentata in zone_da_streams(): quel flag si spegne a
    ogni passo lento in salita e su un trail sbaglia di 17 minuti.
    """
    tempi = streams.get("time") or []
    distanze = streams.get("distance") or []
    if not tempi or not distanze:
        return None

    quote = streams.get("altitude") or []
    battiti = [b for b in (streams.get("heartrate") or []) if b]
    velocita = streams.get("velocity_smooth") or []
    # L'Apple Watch SE non manda la cadenza: su 20 corse è sempre stata vuota.
    # Il Garmin sì, quindi da qui in poi c'è da calcolarla. Strava la dà come
    # passi di UNA gamba, e il resto della pipeline raddoppia: qui si tiene la
    # stessa convenzione, così riga_csv() non deve sapere da dove arriva.
    passi = [c for c in (streams.get("cadence") or []) if c]

    movimento = 0.0
    for i in range(1, min(len(tempi), len(distanze))):
        if i < len(velocita) and velocita[i] is not None \
                and velocita[i] < VELOCITA_FERMO:
            continue
        movimento += tempi[i] - tempi[i - 1]

    salita = _salita(quote)

    return {
        "id":                   id_corsa,
        "name":                 nome or "Corsa (ricostruita dagli streams)",
        "type":                 "Run",
        # L'ora NON è negli streams: contengono i secondi dalla partenza, non
        # la data assoluta. Va passata a mano, e serve davvero:
        # d'estate l'afa costa battiti misurabili, e confrontare due
        # corse a ore diverse senza saperlo porta a conclusioni sbagliate.
        "start_date_local":     f"{data or time.strftime('%Y-%m-%d')}T{ora or '00:00'}:00Z",
        "ora_dichiarata":       bool(ora),
        "distance":             distanze[-1],
        "moving_time":          round(movimento),
        "elapsed_time":         tempi[-1] - tempi[0],
        "total_elevation_gain": round(salita, 1),
        "average_heartrate":    round(sum(battiti) / len(battiti), 1) if battiti else None,
        "max_heartrate":        float(max(battiti)) if battiti else None,
        # Questi Strava li calcola da sé e senza l'API non arrivano. Restano
        # vuoti invece di essere stimati: una colonna vuota è onesta.
        "suffer_score":         None,
        "calories":             None,
        "average_cadence":      round(sum(passi) / len(passi), 1) if passi else None,
        "device_name":          None,
        "best_efforts":         [],
        "splits_metric":        [],
        "ricostruita":          True,
    }


def archivia_da_streams(token, id_corsa, data=None, nome=None, ora=None):
    """Archivia una corsa quando l'unico endpoint vivo sono gli streams."""
    print(f"• Corsa {id_corsa}: provo con i soli streams...")
    streams, errore = chiama(token, f"/activities/{id_corsa}/streams",
                             {"keys": STREAMS_VOLUTI, "key_by_type": "true"})
    if not streams:
        print(f"  ✗ Niente da fare: {errore}")
        return False

    essenziale = {k: v.get("data") for k, v in streams.items() if isinstance(v, dict)}
    dettaglio = dettaglio_da_streams(id_corsa, essenziale, data, nome, ora)
    if not dettaglio:
        print("  ✗ Gli streams non hanno tempo e distanza: non basta.")
        return False

    os.makedirs(CARTELLA_ATTIVITA, exist_ok=True)
    os.makedirs(CARTELLA_STREAMS, exist_ok=True)
    with open(percorso_streams(id_corsa), "w", encoding="utf-8") as f:
        json.dump(essenziale, f)
    with open(percorso_attivita(id_corsa), "w", encoding="utf-8") as f:
        json.dump({
            "dettaglio":    dettaglio,
            "zone":         [],          # premium: non arrivano più
            "ricostruita":  True,
            "scaricato_il": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2, ensure_ascii=False)

    km = dettaglio["distance"] / 1000
    sec = dettaglio["moving_time"]
    cadenza = dettaglio.get("average_cadence")
    print(f"  ✓ {km:.2f} km · {sec // 60}:{sec % 60:02d} in movimento · "
          f"D+ {dettaglio['total_elevation_gain']:.0f} m · "
          f"FC {dettaglio['average_heartrate'] or '—'} · "
          f"{'cadenza ' + str(round(cadenza * 2)) + ' · ' if cadenza else ''}"
          f"{len(essenziale.get('time') or [])} punti")
    print("    (zone ricalcolate dagli streams, sforzo relativo non disponibile)")
    if not ora:
        print("    ⚠ senza --ora il timbro resta 00:00: il confronto fra corse a")
        print("      ore diverse perde il pezzo che spiega il caldo.")
    return True


# ============================================
# PARTE 3 — L'ARCHIVIO LOCALE
# ============================================

def percorso_attivita(id_corsa):
    return os.path.join(CARTELLA_ATTIVITA, f"{id_corsa}.json")


def percorso_streams(id_corsa):
    return os.path.join(CARTELLA_STREAMS, f"{id_corsa}.json")


def gia_in_archivio(id_corsa):
    return os.path.exists(percorso_attivita(id_corsa))


def archivia_corsa(token, riepilogo):
    """
    Scarica TUTTO il possibile su una corsa e lo salva su disco:
      - dettaglio completo (calorie, sforzo relativo, best effort, splits)
      - distribuzione zone cardiache  ← funzione premium
      - streams secondo per secondo   ← il dato più prezioso
    Restituisce True se ha scaricato qualcosa.
    """
    id_corsa = riepilogo["id"]

    dettaglio, errore = chiama(token, f"/activities/{id_corsa}",
                               {"include_all_efforts": "true"})
    if errore:
        print(f"    ✗ dettaglio non scaricato ({errore})")
        return False
    time.sleep(PAUSA_TRA_CHIAMATE)

    # Le zone possono mancare (nessun cardio, o premium scaduto): non è un errore.
    zone, errore_zone = chiama(token, f"/activities/{id_corsa}/zones")
    time.sleep(PAUSA_TRA_CHIAMATE)

    streams, errore_streams = chiama(token, f"/activities/{id_corsa}/streams",
                                     {"keys": STREAMS_VOLUTI, "key_by_type": "true"})
    time.sleep(PAUSA_TRA_CHIAMATE)

    os.makedirs(CARTELLA_ATTIVITA, exist_ok=True)
    with open(percorso_attivita(id_corsa), "w", encoding="utf-8") as f:
        json.dump({
            "dettaglio":    dettaglio,
            "zone":         zone or [],
            "scaricato_il": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2, ensure_ascii=False)

    if streams:
        os.makedirs(CARTELLA_STREAMS, exist_ok=True)
        # Teniamo solo i valori: le altre chiavi dell'API sono ripetitive.
        essenziale = {k: v.get("data") for k, v in streams.items() if isinstance(v, dict)}
        with open(percorso_streams(id_corsa), "w", encoding="utf-8") as f:
            json.dump(essenziale, f)

    etichette = []
    if zone:
        etichette.append("zone")
    if streams:
        etichette.append(f"{len(next(iter(streams.values()))['data'])} punti")
    if dettaglio.get("suffer_score") is not None:
        etichette.append(f"RE {dettaglio['suffer_score']:.0f}")
    print(f"    ✓ {' · '.join(etichette) if etichette else 'solo dettaglio'}")
    return True


def leggi_archivio():
    """Rilegge dal disco tutte le corse archiviate. Non tocca internet."""
    corse = []
    for percorso in glob.glob(os.path.join(CARTELLA_ATTIVITA, "*.json")):
        try:
            with open(percorso, encoding="utf-8") as f:
                corse.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            print(f"  ⚠ file illeggibile, lo salto: {percorso}")
    return corse


# ============================================
# PARTE 3-bis — RICALCOLO DELLE ZONE (rete di sicurezza)
# ============================================
# Le zone cardiache sono una funzione premium: quando la prova scade,
# /activities/{id}/zones smette di rispondere sulle corse NUOVE.
# Gli streams cardio invece restano gratuiti — e dagli streams le zone
# si ricalcolano. Verificato su 15 corse: 13 combaciano con Strava entro
# 20 secondi (scarto mediano 8s). Il segreto è escludere il tempo fermo.

def aggiorna_soglie_riferimento(archivio):
    """
    Mentre il premium è attivo, Strava ci dice quali soglie usa.
    Le salviamo su disco: sono la chiave per ricalcolare le zone dopo.
    """
    piu_recente = None
    for voce in archivio:
        cardio = next((z for z in voce.get("zone") or []
                       if z.get("type") == "heartrate"), None)
        if not cardio:
            continue
        data = (voce.get("dettaglio") or {}).get("start_date_local", "")
        if piu_recente is None or data > piu_recente[0]:
            piu_recente = (data, [b["min"] for b in cardio["distribution_buckets"]])

    if not piu_recente:
        return None
    os.makedirs(CARTELLA_DATI, exist_ok=True)
    with open(FILE_SOGLIE, "w") as f:
        json.dump({"soglie": piu_recente[1], "dalla_corsa_del": piu_recente[0][:10]}, f, indent=2)
    return piu_recente[1]


def carica_soglie():
    """Le soglie salvate da Strava; se non ci sono, le stimiamo da HR_MASSIMA."""
    if os.path.exists(FILE_SOGLIE):
        with open(FILE_SOGLIE) as f:
            return json.load(f)["soglie"]
    return [round(p * HR_MASSIMA) for p in PERCENTUALI_ZONE]


# Sotto questa velocità si è fermi, non lenti. È la stessa soglia calibrata
# in strava_piano.py sui dati reali: le soste vere stanno tutte fra 0,00 e
# 0,06 m/s, mentre una registrazione persa mentre si correva sta sopra 1,7.
VELOCITA_FERMO = 0.5


def zone_da_streams(id_corsa, soglie, moving_time=None):
    """
    Ricostruisce i secondi passati in ogni zona dal battito secondo per secondo.

    COME, e perché così (il primo tentativo sbagliava di 19 minuti).

    Gli streams servono solo a dare la FORMA della distribuzione: quanti
    campioni cadono in ogni zona. Il TOTALE arriva da 'moving_time', che
    Strava dichiara nel dettaglio dell'attività e non è coperto dal premium.

    Il primo tentativo sommava le durate dei campioni escludendo quelli col
    flag 'moving' spento. Funzionava sulle corse in città (scarto mediano
    21s) e crollava sul trail del 30/08: il flag si spegne a ogni passo lento
    in salita e faceva sparire **19 minuti** da una zona sola. Distribuendo
    invece il moving_time ufficiale, e usando la velocità — non il flag — per
    riconoscere le soste vere, lo scarto massimo su una zona passa da 1157s
    a 93s, e quel trail da 1157s a 10s. Mediana 12s su 17 corse.

    Restituisce i secondi per zona, oppure None se mancano streams o cardio.
    """
    percorso = percorso_streams(id_corsa)
    if not os.path.exists(percorso):
        return None
    try:
        with open(percorso) as f:
            s = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    tempi = s.get("time")
    battiti = s.get("heartrate")
    if not tempi or not battiti:
        return None
    velocita = s.get("velocity_smooth") or []

    campioni = [0] * len(soglie)
    for i in range(len(tempi)):
        battito = battiti[i] if i < len(battiti) else None
        if battito is None:
            continue
        # Fermo: il campione non descrive la corsa e non deve pesare.
        if i < len(velocita) and velocita[i] is not None \
                and velocita[i] < VELOCITA_FERMO:
            continue
        campioni[max(j for j, soglia in enumerate(soglie) if battito >= soglia)] += 1

    totale = sum(campioni)
    if not totale:
        return None

    # Senza moving_time si ripiega sulla durata coperta dagli streams: meno
    # preciso, ma è il caso delle attività più vecchie.
    durata = moving_time or (tempi[-1] - tempi[0])
    return [c / totale * durata for c in campioni]


# ============================================
# PARTE 4 — DALL'ARCHIVIO AL CSV
# ============================================

def passo_leggibile(secondi_totali, km):
    """Passo medio in min:sec al km."""
    if not km:
        return "N/D"
    secondi_al_km = secondi_totali / km
    return f"{int(secondi_al_km // 60)}:{int(secondi_al_km % 60):02d}"


def tempo_leggibile(secondi):
    """Un tempo in mm:ss (usato per i best effort)."""
    if secondi is None:
        return ""
    return f"{int(secondi // 60)}:{int(secondi % 60):02d}"


def minuti_per_zona(zone):
    """
    Dalla risposta /activities/{id}/zones estrae i minuti passati
    in ciascuna delle 5 zone cardiache. Lista vuota se non c'è il cardio.
    """
    cardio = next((z for z in zone if z.get("type") == "heartrate"), None)
    if not cardio:
        return ["", "", "", "", ""]
    minuti = [round(b.get("time", 0) / 60) for b in cardio.get("distribution_buckets", [])]
    # Se Strava restituisse un numero diverso di zone, normalizziamo a 5.
    minuti = (minuti + ["", "", "", "", ""])[:5]
    return minuti


def best_effort(dettaglio, nome):
    """Il tempo del miglior tratto di una certa distanza in questa corsa."""
    for b in dettaglio.get("best_efforts") or []:
        if b.get("name") == nome:
            return tempo_leggibile(b.get("elapsed_time"))
    return ""


def riga_csv(voce, soglie):
    """Trasforma una corsa archiviata in una riga del CSV."""
    d = voce["dettaglio"]
    km = round(d.get("distance", 0) / 1000, 2)
    secondi = d.get("moving_time", 0)

    # Prima scelta: le zone che ci ha dato Strava (premium attivo).
    z1, z2, z3, z4, z5 = minuti_per_zona(voce.get("zone") or [])
    fonte_zone = "strava" if z1 != "" else ""

    # Ripiego: le ricalcoliamo noi dagli streams, che restano gratuiti.
    if fonte_zone == "":
        ricalcolate = zone_da_streams(d.get("id"), soglie, d.get("moving_time"))
        if ricalcolate:
            z1, z2, z3, z4, z5 = [round(x / 60) for x in (ricalcolate + [0] * 5)[:5]]
            fonte_zone = "calcolata"

    # Strava dà la cadenza come passi di una gamba: raddoppiamo per avere i passi/min.
    cadenza = d.get("average_cadence")
    cadenza = round(cadenza * 2) if cadenza else ""

    fc_media = d.get("average_heartrate")
    fc_max   = d.get("max_heartrate")

    # Il passo che questa corsa avrebbe avuto in piano, a parità di energia.
    # Serve per confrontare un trail con una corsa in città: vedi
    # strava_pendenza.py. Vuoto se non abbiamo gli streams.
    terreno = strava_pendenza.analizza(d)

    return {
        # --- colonne storiche: gli script di analisi già le usano ---
        "data":       d.get("start_date_local", "")[:10],
        "nome":       d.get("name", "Corsa"),
        "km":         km,
        "minuti":     round(secondi / 60),
        "passo":      passo_leggibile(secondi, km),
        "dislivello": round(d.get("total_elevation_gain", 0) or 0),
        "bpm_media":  round(fc_media) if fc_media else "N/D",
        # --- colonne nuove, sbloccate dall'API ---
        "bpm_max":          round(fc_max) if fc_max else "",
        "sforzo_relativo":  round(d["suffer_score"]) if d.get("suffer_score") is not None else "",
        "calorie":          round(d["calories"]) if d.get("calories") else "",
        "cadenza":          cadenza,
        "z1_min": z1, "z2_min": z2, "z3_min": z3, "z4_min": z4, "z5_min": z5,
        "best_1k":   best_effort(d, "1K"),
        "best_5k":   best_effort(d, "5K"),
        "best_10k":  best_effort(d, "10K"),
        "zone_fonte": fonte_zone,
        "km_equiv":    round(terreno["km_equiv"], 2) if terreno else "",
        "passo_equiv": strava_pendenza.passo_leggibile(terreno["passo_equiv"]) if terreno else "",
        "attrezzo":  d.get("device_name") or "",
        "id":        d.get("id", ""),
    }


COLONNE = ["data", "nome", "km", "minuti", "passo", "dislivello", "bpm_media",
           "bpm_max", "sforzo_relativo", "calorie", "cadenza",
           "z1_min", "z2_min", "z3_min", "z4_min", "z5_min",
           "best_1k", "best_5k", "best_10k", "zone_fonte",
           "km_equiv", "passo_equiv", "attrezzo", "id"]


def costruisci_csv():
    """
    Ricostruisce strava_corse.csv leggendo SOLO l'archivio locale.
    Funziona anche senza internet e anche dopo la scadenza del premium.
    """
    archivio = leggi_archivio()
    if not archivio:
        print("✗ Archivio vuoto: esegui prima 'python3 strava_sync.py' con internet.")
        return []

    # Le soglie vere valgono oro: aggiorniamole finché Strava ce le passa.
    aggiorna_soglie_riferimento(archivio)
    soglie = carica_soglie()

    righe = [riga_csv(v, soglie) for v in archivio if v.get("dettaglio")]
    righe.sort(key=lambda r: r["data"], reverse=True)

    calcolate = sum(1 for r in righe if r["zone_fonte"] == "calcolata")
    if calcolate:
        print(f"  ({calcolate} corse con zone ricalcolate dagli streams, "
              f"soglie {soglie})")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNE)
        writer.writeheader()
        writer.writerows(righe)

    print(f"✓ '{OUTPUT_CSV}' ricostruito: {len(righe)} corse, {len(COLONNE)} colonne.")
    return righe


# ============================================
# PARTE 5 — RIEPILOGO A SCHERMO
# ============================================

def sep(n=64):
    print("─" * n)


def riepilogo(righe, anno="2026"):
    """Mostra la stagione corrente con i dati nuovi."""
    stagione = [r for r in righe if r["data"] >= f"{anno}-01-01"]
    if not stagione:
        print(f"\nNessuna corsa nel {anno}.")
        return

    print()
    sep()
    print(f"   STAGIONE {anno} — {len(stagione)} corse")
    sep()
    print(f"{'data':<11}{'km':>6}{'passo':>8}{'FC':>5}{'RE':>5}{'kcal':>6}   zone Z1→Z5")
    sep()
    for r in sorted(stagione, key=lambda x: x["data"]):
        zone = " ".join(f"{str(r[f'z{i}_min'] or 0):>3}" for i in range(1, 6))
        if not any(r[f"z{i}_min"] != "" for i in range(1, 6)):
            zone = "  — niente cardio —"
        elif r["zone_fonte"] == "calcolata":
            zone += "  (ricalcolate)"
        print(f"{r['data']:<11}{r['km']:>6.2f}{r['passo']:>8}"
              f"{str(r['bpm_media']).replace('N/D', '—'):>5}"
              f"{str(r['sforzo_relativo'] or '—'):>5}{str(r['calorie'] or '—'):>6}   {zone}")
    sep()

    km = sum(r["km"] for r in stagione)
    minuti = sum(r["minuti"] for r in stagione)
    sforzi = [r["sforzo_relativo"] for r in stagione if r["sforzo_relativo"] != ""]
    print(f"  Totale: {km:.1f} km in {minuti // 60}h {minuti % 60}min")
    if sforzi:
        print(f"  Sforzo relativo accumulato: {sum(sforzi)}  (media {sum(sforzi) / len(sforzi):.0f} a uscita)")
    sep()


# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

def _argomento(nome):
    """Il valore che segue una bandiera, se c'è."""
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return None


def main():
    solo_offline  = "--offline" in sys.argv
    riautorizza   = "--riautorizza" in sys.argv
    rileggi_tutto = "--rileggi" in sys.argv
    id_corsa      = _argomento("--corsa")

    print()
    sep()
    print("   STRAVA SYNC — API → archivio locale → CSV")
    sep()

    # --- Una corsa sola, per id, dai soli streams ---
    # Serve da quando l'API risponde 403 su tutto tranne gli streams: l'elenco
    # delle corse non si può più chiedere, quindi l'id lo si dà a mano.
    if id_corsa:
        token = ottieni_token(forza_riautorizzazione=riautorizza)
        if not token:
            print("✗ Autenticazione fallita.")
            return
        ok = archivia_da_streams(token, id_corsa.strip().rstrip("/").split("/")[-1],
                                 data=_argomento("--data"),
                                 nome=_argomento("--nome"),
                                 ora=_argomento("--ora"))
        if ok:
            print()
            righe = costruisci_csv()
            riepilogo(righe)
        return

    # --- Modalità offline: nessuna rete, si rilegge solo il disco ---
    if solo_offline:
        print("Modalità offline: uso solo l'archivio in 'dati/'.\n")
        righe = costruisci_csv()
        riepilogo(righe)
        return

    token = ottieni_token(forza_riautorizzazione=riautorizza)
    if not token:
        print("✗ Autenticazione fallita. Puoi comunque usare --offline.")
        return

    # --- L'API risponde? Il premium è ancora attivo? ---
    atleta, errore = stato_account(token)
    if errore:
        print(f"✗ L'API non risponde ({errore}).")
        print("  Nessun problema: l'archivio locale resta valido.")
        righe = costruisci_csv()
        riepilogo(righe)
        return

    premium = atleta.get("premium") or atleta.get("summit")
    print(f"Ciao {atleta.get('firstname', '')} — abbonamento: "
          f"{'PREMIUM attivo' if premium else 'gratuito (scaduto)'}")
    if not premium:
        print("  ⚠ Senza premium mancheranno sforzo relativo e zone cardiache")
        print("    sulle corse NUOVE. Quelle già in 'dati/' restano complete.")

    if "profile:read_all" not in permessi_attuali():
        print("  • Le tue zone FC personalizzate non sono leggibili "
              "(manca il permesso profile:read_all).")
        print("    Se le vuoi: python3 strava_sync.py --riautorizza")

    # --- Elenco delle corse su Strava ---
    print("\n• Chiedo a Strava l'elenco delle corse...")
    try:
        corse = elenca_corse(token)
    except LimiteRaggiunto:
        print("✗ Limite di richieste raggiunto. Riprova tra 15 minuti.")
        return
    print(f"✓ {len(corse)} corse sul tuo profilo.")

    da_scaricare = corse if rileggi_tutto else [c for c in corse if not gia_in_archivio(c["id"])]
    gia_presenti = len(corse) - len(da_scaricare)
    if gia_presenti:
        print(f"  ({gia_presenti} già in archivio, le salto)")

    # --- Il download vero e proprio ---
    if da_scaricare:
        print(f"\n• Archivio {len(da_scaricare)} corse (3 chiamate ciascuna)...")
        scaricate = 0
        try:
            for i, corsa in enumerate(da_scaricare, 1):
                print(f"  [{i}/{len(da_scaricare)}] {corsa['start_date_local'][:10]} "
                      f"{corsa['name'][:32]}")
                if archivia_corsa(token, corsa):
                    scaricate += 1
        except LimiteRaggiunto:
            print("\n  ⚠ Limite di richieste Strava raggiunto.")
            print("    Quello scaricato finora è già salvato: "
                  "riesegui lo script tra 15 minuti per continuare.")
        print(f"\n✓ {scaricate} corse aggiunte all'archivio.")
    else:
        print("\n✓ Archivio già aggiornato, niente da scaricare.")

    # --- Le zone cardiache personali, se abbiamo il permesso ---
    if "profile:read_all" in permessi_attuali():
        zone_atleta, errore = chiama(token, "/athlete/zones")
        if zone_atleta:
            with open(os.path.join(CARTELLA_DATI, "zone_atleta.json"), "w") as f:
                json.dump(zone_atleta, f, indent=2)
            print("✓ Zone cardiache personali salvate in 'dati/zone_atleta.json'.")

    # --- Dall'archivio al CSV ---
    print()
    righe = costruisci_csv()

    n_streams = len(glob.glob(os.path.join(CARTELLA_STREAMS, "*.json")))
    dimensione = sum(os.path.getsize(p) for p in
                     glob.glob(os.path.join(CARTELLA_DATI, "**", "*.json"), recursive=True))
    print(f"✓ Archivio: {len(leggi_archivio())} corse · {n_streams} con streams "
          f"· {dimensione / 1_000_000:.1f} MB in '{CARTELLA_DATI}/'")

    riepilogo(righe)

    print("\nDa adesso in poi, anche senza premium e senza internet:")
    print("  python3 strava_sync.py --offline\n")


if __name__ == "__main__":
    main()
