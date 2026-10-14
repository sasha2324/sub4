# ============================================
# PIANO MARATONA — TRACKER
# ============================================
# Confronta quello che corri davvero con quello che il piano
# prevede, e dice se il cancello per la fase successiva è aperto.
#
# IDEA DI FONDO:
#   Il piano non va a calendario ma A CANCELLI: si cambia fase
#   quando i criteri sono soddisfatti, non quando lo dice il foglio.
#   I criteri sono tutti misurabili sull'archivio locale.
#
# ATTENZIONE (voluto): questo script non usa MAI 'sforzo_relativo'.
#   La prova premium scade il 2026-09-18 e quella colonna smette di
#   arrivare. Le zone cardiache invece la pipeline le ricalcola dagli
#   streams, che restano gratuiti: il tracker funziona identico dopo.
#
# COME SI USA:
#   python3 strava_piano.py             report della settimana
#   python3 strava_piano.py --cancelli  solo lo stato dei cancelli
#   python3 strava_piano.py --settimana la settimana da fare adesso
#   python3 strava_piano.py --soglie    cosa dicono i dati delle tue zone
#   python3 strava_piano.py --storico   tutte le settimane, una riga each
#   python3 strava_piano.py --html      rigenera la pagina web
#   python3 strava_piano.py --avanza    passa alla fase successiva
# ============================================

import csv
import json
import math
from collections import namedtuple
import os
import sys
from datetime import datetime, date, timedelta

import impostazioni

# Frequenza cardiaca massima (dato personale, nel .env) e percentuali con cui
# Strava separa le 5 zone: servono solo se mancano le soglie vere archiviate.
HR_MASSIMA = int(impostazioni.leggi("HR_MASSIMA", "190"))
PERCENTUALI_ZONE = [0.0, 0.673, 0.837, 0.918, 1.0]

FILE_CSV    = "strava_corse.csv"
FILE_PIANO  = "piano.json"
FILE_SOGLIE = os.path.join("dati", "soglie_zone.json")
CARTELLA_STREAMS = os.path.join("dati", "streams")

# Sopra questo buco nella registrazione l'orologio era in pausa: è una sosta.
# Il flag 'moving' di Strava NON va bene — si spegne a ogni micro-esitazione
# e spezzerebbe corse che sono state continue.
PAUSA_SEC = 20

# ...ma un buco lungo non basta a dire "si è fermato": va guardato se nel
# frattempo si è mosso. Il 18/08/2026 c'è un buco di 21 secondi in cui però
# sono stati percorsi 37 metri (1,78 m/s): è una registrazione persa dal
# telefono, non una sosta. Sui dati reali la separazione è netta — le soste
# vere stanno tutte fra 0,00 e 0,06 m/s.
VELOCITA_FERMO = 0.5        # m/s: sotto questa, durante il buco era fermo

# Camminare non è fermarsi: la traccia non si interrompe e VELOCITA_FERMO non
# lo vede. Ma per un lungo è un'interruzione lo stesso — quattro minuti di
# camminata in salita spezzano la corsa continua quanto una sosta. Sotto
# 1,8 m/s (9:15/km) per almeno mezzo minuto DI FILA si sta camminando, non
# correndo piano; il vincolo sulla durata evita che un rallentamento in curva
# diventi una camminata. Verificato sulle 13 corse del 2026: zero tratti
# trovati, cioè zero falsi positivi. La soglia però NON è ancora stata provata
# su una camminata vera — il primo banco di prova è il trail del 30/08/2026.
VELOCITA_CAMMINATA = 1.8
CAMMINATA_SEC = 30
FILE_HTML   = "piano_maratona.html"

# Lo storico parte dalla ripresa: tutto ciò che viene prima è archivio.
DAL = "2026-08-08"

# Il piano parte dalla settimana del 17 agosto, cominciata a metà: Sasha ha
# scelto di non aspettare il lunedì successivo. Il tracker sa gestirlo — vedi
# sedute_rimanenti().
INIZIO_PIANO = "2026-08-17"

# Obiettivo: maratona sotto le 4 ore = 5:41/km su 42,195 km.
RITMO_GARA_SEC = 341        # 5:41 al km
MEZZA_OBIETTIVO_MIN = 112   # 1:52 — proietta 3:55 con Riegel

# Quante settimane dura il blocco maratona. NON è un numero fisso: dipende da
# quanto dista la gara dalla mezza. Lo scarico finale si conta a ritroso da
# QUI, non da una settimana fissa — altrimenti con un blocco più corto di 16
# settimane non scatta mai e si arriva alla gara al massimo del carico.
DURATA_FASE2 = 16
SCARICO_FINALE = 3          # settimane di scarico prima della gara

# ============================================
# LE TRE FASI
# ============================================
# 'ratio' è come si spezza il volume settimanale sulle 4 uscite.
# L'ultima voce è sempre il lungo.

# Soglie del cancello della fase 0. Stanno qui e non dentro FASI perché sia il
# testo della scheda sia valuta_cancello() le leggono da questa unica fonte:
# il 30/08/2026 la scheda diceva 38 km e 16 km di lungo mentre il controllo
# verificava 30 e 13, e nessuno dei due si accorgeva dell'altro. Sasha ha
# scelto di tenere la versione più corta.
CANCELLO0_SETT_KM = 30
CANCELLO0_LUNGO_KM = 13
CANCELLO0_FACILE_PERC = 85

FASI = [
    {
        "numero": 0,
        "nome": "Consolidamento",
        "durata": "5 settimane",
        "scopo": "Far recuperare a tendini e ossa il ritardo che hanno sul cuore.",
        "sedute": ["Facile", "Qualità", "Facile", "Lungo"],
        "ratio":  [0.20, 0.25, 0.20, 0.35],
        "cancello": (f"4 settimane di fila ≥{CANCELLO0_SETT_KM} km · "
                     f"un lungo ≥{CANCELLO0_LUNGO_KM} km corsi · "
                     f"≥{CANCELLO0_FACILE_PERC}% del tempo in Z1-Z2 · "
                     f"nessun dolore oltre 48h"),
    },
    {
        "numero": 1,
        "nome": "Base",
        "durata": "12-14 settimane",
        "scopo": "Costruire il volume e introdurre la soglia. Chiude con una mezza di verifica.",
        "sedute": ["Facile", "Soglia", "Facile", "Lungo"],
        "ratio":  [0.19, 0.22, 0.19, 0.40],
        "cancello": "mezza maratona sotto 1:52 · 8 settimane ≥52 km · due lunghi ≥21 km",
    },
    {
        "numero": 2,
        "nome": "Blocco maratona",
        "durata": "16 settimane",
        "scopo": "Ritmo gara nelle gambe e lunghi fino a 32 km. Ultime 3 settimane in scarico.",
        "sedute": ["Facile", "Soglia", "Ritmo maratona", "Lungo"],
        "ratio":  [0.17, 0.20, 0.18, 0.45],
        "cancello": "— è la gara",
    },
]

# ============================================
# CARICAMENTO
# ============================================

def carica_piano():
    """Legge piano.json, creandolo alla prima esecuzione."""
    if os.path.exists(FILE_PIANO):
        with open(FILE_PIANO, "r", encoding="utf-8") as f:
            return json.load(f)
    piano = {
        "obiettivo":        "Maratona sotto le 4 ore",
        "ritmo_gara":       "5:41",
        "giorni_settimana": 4,
        "fase":             0,
        "fase_inizio":      INIZIO_PIANO,
        "gara":             None,
    }
    salva_piano(piano)
    print(f"✓ Creato '{FILE_PIANO}' — fase 0, si parte.\n")
    return piano

def durata_fase2(piano):
    """Settimane fra la mezza di verifica e la gara, se sono fissate entrambe."""
    gara, mezza = piano.get("gara"), piano.get("mezza")
    if gara and mezza:
        try:
            g = datetime.strptime(gara["data"], "%Y-%m-%d").date()
            m = datetime.strptime(mezza["data"], "%Y-%m-%d").date()
            settimane = (g - m).days // 7
            if 10 <= settimane <= 20:
                return settimane
        except (KeyError, ValueError):
            pass
    return 16

def salva_piano(piano):
    with open(FILE_PIANO, "w", encoding="utf-8") as f:
        json.dump(piano, f, indent=2, ensure_ascii=False)

def carica_soglie():
    """Le soglie vere di Strava, se archiviate; altrimenti stimate da HR_MASSIMA."""
    if os.path.exists(FILE_SOGLIE):
        with open(FILE_SOGLIE, "r", encoding="utf-8") as f:
            return json.load(f)["soglie"], True
    return [round(p * HR_MASSIMA) for p in PERCENTUALI_ZONE], False

# Una namedtuple e non un dizionario: cont[0], cont[1], cont[2] continuano a
# funzionare dove erano già usati, ma i campi nuovi hanno un nome leggibile.
Continuita = namedtuple("Continuita",
                        "km minuti pezzi fermo camminato forzato")

def continuita(id_corsa):
    """Il tratto più lungo corso senza fermarsi, dagli streams secondo per secondo.

    È IL numero che conta per la maratona: 10 km fatti in otto pezzi non
    allenano la resistenza che serve a correrne 42 di fila.
    Restituisce (km, minuti, pezzi, minuti_fermo) oppure None."""
    percorso = os.path.join(CARTELLA_STREAMS, f"{id_corsa}.json")
    if not os.path.exists(percorso):
        return None
    try:
        with open(percorso, "r", encoding="utf-8") as f:
            s = json.load(f)
        dist, tempo = s["distance"], s["time"]
    except (KeyError, ValueError, OSError):
        return None
    if not dist or not tempo:
        return None

    velocita = s.get("velocity_smooth")
    camminate = _camminate(tempo, velocita)
    soste     = _soste_registrate(tempo, velocita)

    # Le soste forzate contano nei minuti fermi ma NON spezzano la corsa:
    # una coda in gara non dice niente su quanto sai correre di fila.
    forzate_km = [x["km"] for x in
                  carica_soste_forzate().get(str(id_corsa), {}).get("soste", [])]

    def e_forzata(a):
        return any(abs(dist[a] / 1000 - k) <= TOLLERANZA_SOSTA_KM
                   for k in forzate_km)

    forzate = [(a, b) for a, b in soste if e_forzata(a)]
    soste = [x for x in soste if x not in forzate]
    # Anche una camminata può essere forzata: sessanta metri al 10% si
    # camminano per scelta, non per cedimento, e spezzare lì la corsa
    # continua misurerebbe il profilo del percorso invece della resistenza.
    camminate_forzate = [(a, b) for a, b in camminate if e_forzata(a)]
    camminate = [x for x in camminate if x not in camminate_forzate]
    min_forzati = sum(tempo[b] - tempo[a]
                      for a, b in forzate + camminate_forzate) / 60
    # Camminare e stare fermi spezzano il tratto allo stesso modo: quello che
    # conta è dove finisce la CORSA. Restano contati a parte perché dicono
    # cose diverse — 15 minuti camminati in salita non sono 6 minuti di ristoro.
    dopo_camminata = {a: b for a, b in camminate + soste}
    min_camminati = sum(tempo[b] - tempo[a] for a, b in camminate) / 60
    min_sosta     = sum(tempo[b] - tempo[a] for a, b in soste) / 60

    best_m = best_s = 0.0
    pezzi, fermo = 1, 0.0
    # Se la corsa comincia camminando, il primo tratto parte dove si comincia
    # a correre davvero.
    partenza = dopo_camminata.get(0, 0)
    inizio_d, inizio_t = dist[partenza], tempo[partenza]

    def chiudi(fine):
        """Il tratto finito a 'fine' è il più lungo finora?"""
        nonlocal best_m, best_s
        if dist[fine] - inizio_d > best_m:
            best_m = dist[fine] - inizio_d
            best_s = tempo[fine] - inizio_t

    i = partenza + 1
    while i < len(dist):
        fine_camminata = dopo_camminata.get(i)
        if fine_camminata is not None:
            # Si è messo a camminare: il tratto corso finisce qui.
            chiudi(i - 1)
            inizio_d, inizio_t = dist[fine_camminata], tempo[fine_camminata]
            pezzi += 1
            i = fine_camminata + 1
            continue
        dt = tempo[i] - tempo[i-1]
        # Buco lungo: era fermo, o è solo registrazione persa?
        if dt > PAUSA_SEC and (dist[i] - dist[i-1]) / dt < VELOCITA_FERMO:
            chiudi(i - 1)
            inizio_d, inizio_t = dist[i], tempo[i]
            pezzi += 1
            fermo += dt
        i += 1
    chiudi(len(dist) - 1)
    return Continuita(round(best_m / 1000, 2), round(best_s / 60), pezzi,
                      round(fermo / 60 + min_sosta + min_forzati),
                      round(min_camminati), round(min_forzati))

FILE_SOSTE_FORZATE = os.path.join("dati", "soste_forzate.json")

# Quanto può scostarsi il km dichiarato da quello misurato perché la sosta
# venga riconosciuta. 150 m: abbastanza per un "al quarto chilometro" detto a
# memoria, troppo poco per beccare per sbaglio la sosta sbagliata.
TOLLERANZA_SOSTA_KM = 0.15

def carica_soste_forzate():
    """Le interruzioni che NON misurano la resistenza di chi corre.

    Il tracker vede CHE ci si è fermati, non PERCHÉ. Due categorie, entrambe
    legittime e verificate sui dati prima di essere accettate:

    - soste vere per cause esterne: code, semafori, attraversamenti, o
      togliersi una maglietta (27/09/2026, km 7,72: 45 secondi a 0,02 m/s);
    - tratti camminati su pendenze ripide, dove camminare è la scelta giusta
      e non un cedimento (27/09/2026, km 11,63: 60 metri al 10,4%).

    Il criterio per accettarle: il racconto di chi ha corso deve combaciare
    con quello che dicono gli streams. Se uno dice "mi sono fermato a
    cambiarmi" e lì ci sono 45 secondi a velocità zero, è quello."""
    if not os.path.exists(FILE_SOSTE_FORZATE):
        return {}
    try:
        with open(FILE_SOSTE_FORZATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}

def salva_sosta_forzata(id_corsa, km, perche):
    """Segna una sosta come forzata. Torna False se lì non c'era nessuna sosta."""
    dati = carica_soste_forzate()
    voce = dati.setdefault(str(id_corsa), {"soste": []})
    voce["soste"].append({"km": round(float(km), 2), "perche": perche})
    os.makedirs(os.path.dirname(FILE_SOSTE_FORZATE), exist_ok=True)
    with open(FILE_SOSTE_FORZATE, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    return True

def _senza_buchi(velocita, quanti):
    """La velocità con i valori mancanti riempiti dal precedente.

    Gli streams di Strava non avevano mai valori nulli; quelli di Garmin sì —
    il primo campione di ogni metrica e qualche sparso in mezzo. Confrontare
    None con un numero solleva, e scartare i campioni sfaserebbe gli indici
    rispetto al tempo. Si tiene l'ultimo valore noto, che su un secondo di
    corsa è l'ipotesi più innocua.
    """
    if not velocita:
        return []
    fuori, ultimo = [], 0.0
    for i in range(quanti):
        v = velocita[i] if i < len(velocita) else None
        if v is not None:
            ultimo = v
        fuori.append(ultimo)
    return fuori


def _soste_registrate(tempo, velocita):
    """Le soste in cui l'orologio ha continuato a registrare, come (inizio, fine).

    Il rilevamento delle soste basato sui BUCHI nella traccia vede solo le pause
    automatiche dell'orologio. Al Martani Trail del 30/08/2026 l'Apple Watch ha
    registrato senza interruzioni anche stando fermi: tre soste da 207, 107 e
    25 secondi — quasi sei minuti — risultavano corsa continua."""
    if not velocita:
        return []
    velocita = _senza_buchi(velocita, len(tempo))
    tratti, i, n = [], 0, len(velocita)
    while i < n:
        if velocita[i] <= VELOCITA_FERMO:
            j = i
            while j < n and velocita[j] <= VELOCITA_FERMO:
                j += 1
            if tempo[j-1] - tempo[i] >= PAUSA_SEC:
                tratti.append((i, j - 1))
            i = j
        else:
            i += 1
    return tratti

def _camminate(tempo, velocita):
    """I tratti percorsi a passo di camminata, come coppie (inizio, fine).

    Serve un tratto continuo di almeno CAMMINATA_SEC: un calo di un attimo in
    curva o a un semaforo non è una camminata."""
    if not velocita:
        return []
    velocita = _senza_buchi(velocita, len(tempo))
    tratti, i, n = [], 0, len(velocita)
    while i < n:
        if VELOCITA_FERMO < velocita[i] < VELOCITA_CAMMINATA:
            j = i
            while j < n and VELOCITA_FERMO < velocita[j] < VELOCITA_CAMMINATA:
                j += 1
            if tempo[j-1] - tempo[i] >= CAMMINATA_SEC:
                tratti.append((i, j - 1))
            i = j
        else:
            i += 1
    return tratti

# Le distanze su cui teniamo i record, in metri.
DISTANZE_RECORD = [(400, "400 m"), (1000, "1 km"), (1609, "1 miglio"),
                   (2000, "2 km"), (3000, "3 km"), (5000, "5 km"), (10000, "10 km")]

def _tratti_continui(dist, tempo):
    """Spezza la traccia nei tratti corsi senza fermarsi."""
    tratti, inizio = [], 0
    for i in range(1, len(dist)):
        dt = tempo[i] - tempo[i-1]
        if dt > PAUSA_SEC and (dist[i] - dist[i-1]) / dt < VELOCITA_FERMO:
            if i - inizio > 1:
                tratti.append((inizio, i))
            inizio = i
    if len(dist) - inizio > 1:
        tratti.append((inizio, len(dist)))
    return tratti

def passi_per_zona(corse):
    """A che passo si corre in ciascuna zona, secondo per secondo.

    Le zone dicono quanti minuti, non a che andatura: sapere che la Z2 sta a
    6:45/km trasforma una soglia di battiti in un passo da tenere davvero.
    I campioni troppo distanziati (buchi di registrazione) si scartano, e le
    zone con meno di MIN_MIN_ZONA minuti non producono un passo: i 6 minuti in
    Z4 di agosto 2026, sparsi a fine corsa e in salita, davano 5:53/km — più
    lento della Z3, cioè un numero peggiore del niente."""
    soglie, _ = carica_soglie()
    limiti = list(soglie) + [999]
    sec = [0.0] * 5
    metri = [0.0] * 5

    for c in corse:
        percorso = os.path.join(CARTELLA_STREAMS, f"{c['id']}.json")
        if not os.path.exists(percorso):
            continue
        try:
            with open(percorso, "r", encoding="utf-8") as f:
                s = json.load(f)
            hr, dist, tempo = s["heartrate"], s["distance"], s["time"]
        except (KeyError, ValueError, OSError):
            continue
        if not hr:
            continue
        for i in range(1, len(hr)):
            dt = tempo[i] - tempo[i-1]
            if dt <= 0 or dt > PAUSA_SEC:
                continue
            for z in range(5):
                if limiti[z] <= hr[i] < limiti[z+1]:
                    sec[z]   += dt
                    metri[z] += dist[i] - dist[i-1]
                    break

    fasce = []
    for z in range(5):
        passo = None
        if sec[z] >= MIN_MIN_ZONA * 60 and metri[z] > 300:
            passo = sec[z] / (metri[z] / 1000)
        fasce.append({
            "nome":   NOMI_ZONE[z],
            "da":     limiti[z],
            "a":      limiti[z+1] - 1 if z < 4 else None,
            "passo":  passo,
            "minuti": sec[z] / 60,
        })
    return fasce

NOMI_ZONE = ["Recupero", "Fondo facile", "Medio", "Soglia", "Massimale"]

# Sotto questi minuti in una zona il passo medio non significa niente.
MIN_MIN_ZONA = 10

# Velocità istantanea oltre la quale il GPS ha teletrasportato, non hai
# corso: 8 m/s sono 2:05/km. Il 18/08/2026 c'è un campione da 38 metri in un
# secondo, e cadeva dentro la finestra del record sui 5 km — cioè dentro la
# base di TUTTE le proiezioni di gara. Un record gonfiato da un salto del
# GPS è peggio di un record mancante: sembra vero.
VELOCITA_IMPOSSIBILE = 8.0


def _distanza_ripulita(dist, tempo):
    """La traccia con i salti del GPS ricondotti al massimo plausibile.

    Non si butta il campione — si taglia l'avanzamento a quello che si poteva
    percorrere davvero in quel secondo. Il risultato è una distanza un po'
    più corta e quindi un record un po' più lento: nella direzione giusta,
    perché su questi numeri si costruiscono le previsioni."""
    pulita = [dist[0]]
    tolti = 0.0
    for i in range(1, len(dist)):
        avanzato = dist[i] - dist[i - 1]
        dt = tempo[i] - tempo[i - 1]
        tetto = VELOCITA_IMPOSSIBILE * dt if dt > 0 else avanzato
        if avanzato > tetto:
            tolti += avanzato - tetto
            avanzato = tetto
        pulita.append(pulita[-1] + avanzato)
    return pulita, tolti


def record_distanze(corse):
    """Il miglior tempo su ogni distanza, cercato SOLO dentro i tratti continui.

    Un 'miglior 5 km' che comprendesse quattro minuti fermi a bere non
    vorrebbe dire niente. E nemmeno uno che comprendesse un salto del GPS:
    la traccia viene ripulita prima di cercare le finestre."""
    migliori = {}
    for corsa in corse:
        percorso = os.path.join(CARTELLA_STREAMS, f"{corsa['id']}.json")
        if not os.path.exists(percorso):
            continue
        try:
            with open(percorso, "r", encoding="utf-8") as f:
                s = json.load(f)
            dist, tempo = s["distance"], s["time"]
        except (KeyError, ValueError, OSError):
            continue
        dist, _ = _distanza_ripulita(dist, tempo)

        for a, b in _tratti_continui(dist, tempo):
            for metri, nome in DISTANZE_RECORD:
                if dist[b-1] - dist[a] < metri:
                    continue
                # Due indici che scorrono: la finestra più stretta che copre 'metri'.
                j = a
                for i in range(a, b):
                    while j < b and dist[j] - dist[i] < metri:
                        j += 1
                    if j >= b:
                        break
                    t = tempo[j] - tempo[i]
                    if nome not in migliori or t < migliori[nome][0]:
                        migliori[nome] = (t, corsa["data"])
    return migliori

# Esponente della formula di Riegel. 1.06 è il valore classico: presume che
# si sia ALLENATI per la distanza d'arrivo, il che per una maratona quando il
# lungo è di 10 km non è vero. Per questo la previsione va sempre pubblicata
# accanto al record di corsa continua, che dice quanto è ipotetica.
RIEGEL = 1.06

# Da quale record si parte. Il 5 km è la base standard: abbastanza lungo da
# non essere uno sprint, abbastanza corto da essere corso quasi al massimo.
# Il 10 km NON va bene come base finché il suo record viene da un lento —
# darebbe una maratona di un'ora più lenta, che non è pessimismo ma un errore.
BASE_PREVISIONI = "5 km"

# Le distanze proiettate. Sotto i 5 km la formula estrapola all'indietro da
# una base di resistenza e diventa ottimista: su quelle righe il record vero,
# quando c'è, vale più della proiezione — la tabella li mette accanto.
GARE_PREVISTE = [("1 km", 1.0), ("1 miglio", 1.609), ("5 km", 5.0),
                 ("10 km", 10.0), ("Mezza maratona", 21.0975), ("Maratona", 42.195)]

def obiettivo_attivo(piano):
    """Il gradino della scala su cui stiamo lavorando adesso.

    È il primo che non è ancora scaduto: quando dicembre passa, marzo prende
    il suo posto da solo — un obiettivo con una data che nessuno aggiorna è
    un obiettivo che si può solo mancare."""
    ob = piano.get("obiettivi") or {}
    scala = sorted(ob.get("scala") or [], key=lambda g: g["entro"])
    oggi = date.today().isoformat()
    for gradino in scala:
        if gradino["entro"] >= oggi:
            return gradino
    return scala[-1] if scala else None


def obiettivi_derivati(piano):
    """Gli obiettivi su ogni distanza, derivati dall'ancora con Riegel.

    Restituisce {nome: secondi}. Così i sei numeri dicono tutti la stessa
    cosa, e cambiarne uno li muove tutti insieme."""
    ob = piano.get("obiettivi") or {}
    gradino = obiettivo_attivo(piano)
    if not gradino:
        return {}
    km_ancora = dict(DISTANZE_RECORD_KM).get(ob.get("ancora", "5 km"), 5.0)

    fuori = {}
    for nome, km in DISTANZE_RECORD_KM:
        # Sotto i tre minuti Riegel esce dal suo campo di validità: meglio
        # nessun obiettivo che uno inventato.
        stimato = gradino["secondi"] * (km / km_ancora) ** RIEGEL
        if stimato >= 180:
            fuori[nome] = stimato

    # Gli obiettivi pluriennali vincono su quelli derivati: sono una scelta,
    # non un calcolo, e vanno mostrati per quello che sono.
    for nome, voce in (ob.get("pluriennale") or {}).items():
        fuori[nome] = voce["secondi"]
    return fuori


def previsioni(corse, piano):
    """I tempi di gara proiettati dal miglior 5 km, con lo scarto dagli obiettivi.

    Restituisce None se il record di base non c'è ancora."""
    record = record_distanze(corse)
    # L'ancora va presa in piano: vedi record_in_piano(). Il resto della
    # tabella continua a mostrare i tempi reali.
    piano_eq = record_in_piano(corse)
    base = piano_eq.get(BASE_PREVISIONI) or record.get(BASE_PREVISIONI)
    if not base:
        return None
    t_base, data_base = base[0], base[1]
    km_base = dict(DISTANZE_RECORD_KM)[BASE_PREVISIONI]

    obiettivi = {"Mezza maratona": piano.get("mezza", {}).get("obiettivo_secondi"),
                 "Maratona":       piano.get("gara", {}).get("obiettivo_secondi")}

    righe = []
    for nome, km in GARE_PREVISTE:
        previsto = t_base * (km / km_base) ** RIEGEL
        obiettivo = obiettivi.get(nome)
        vero = record.get(nome)
        righe.append({
            "nome":      nome,
            "km":        km,
            "previsto":  previsto,
            "obiettivo": obiettivo,
            "scarto":    previsto - obiettivo if obiettivo else None,
            "record":    vero[0] if vero else None,
            "record_il": vero[1] if vero else None,
        })
    return {"base": BASE_PREVISIONI, "tempo_base": t_base, "data_base": data_base,
            "km_base": km_base, "righe": righe}

# Quanto può essere pendente una finestra per servire da ANCORA. Dentro il
# 3% la correzione di Minetti è una rifinitura; fuori diventa il termine
# principale, e un modello di laboratorio finisce a reggere da solo la
# previsione di una maratona. Il 04/10 la finestra di 5 km più veloce in
# equivalente era in salita del 9%: riportata in piano dava 25:38, meglio di
# qualunque cosa avesse mai corso in piano. Non è un record, è il modello.
BANDA_ANCORA = 0.03


def record_in_piano(corse, banda=BANDA_ANCORA):
    """Il miglior tempo su ogni distanza, RIPORTATO IN PIANO.

    Perché esiste, in una riga: il 04/10/2026 il miglior 5 km cade fra il km
    8,1 e il 13,1 del percorso di gara, perdendo 73 metri di quota. Reale fa
    24:57, cioè 1:29 meglio del record di agosto. In piano fa 26:55, cioè 34
    secondi PEGGIO. Usato come ancora così com'era, portava la maratona
    prevista a 3:59:18 — sotto l'obiettivo — per via di una discesa.

    Il record vero resta quello reale: è il tempo che ha corso, e va mostrato.
    Ma un'ancora di Riegel deve essere una distanza in piano, altrimenti
    proietta il profilo di quel giorno su tutte le gare future.

    Cerca la finestra che minimizza il tempo EQUIVALENTE fra quelle già
    piatte entro il 3% (vedi BANDA_ANCORA): non è la stessa finestra di
    quella più veloce. Restituisce
    {nome: (secondi_in_piano, data, secondi_reali, moltiplicatore)}.
    """
    import strava_pendenza as pendenza
    migliori = {}
    for corsa in corse:
        percorso = os.path.join(CARTELLA_STREAMS, f"{corsa['id']}.json")
        if not os.path.exists(percorso):
            continue
        try:
            with open(percorso, "r", encoding="utf-8") as f:
                s = json.load(f)
            dist, tempo = s["distance"], s["time"]
        except (KeyError, ValueError, OSError):
            continue
        dist, _ = _distanza_ripulita(dist, tempo)
        pz = pendenza._pendenze(s, len(dist))
        if pz is None:
            continue

        # Metri ed energia cumulati: così il costo di una finestra è una
        # sottrazione invece di un ciclo, e si possono provare tutte.
        cum_m = [0.0] * len(dist)
        cum_e = [0.0] * len(dist)
        for i in range(1, len(dist)):
            av = dist[i] - dist[i-1]
            av = av if av > 0 else 0.0
            cum_m[i] = cum_m[i-1] + av
            cum_e[i] = cum_e[i-1] + av * pendenza.fattore(pz[i])

        for a, b in _tratti_continui(dist, tempo):
            for metri, nome in DISTANZE_RECORD:
                if dist[b-1] - dist[a] < metri:
                    continue
                j = a
                for i in range(a, b):
                    while j < b and dist[j] - dist[i] < metri:
                        j += 1
                    if j >= b:
                        break
                    m = cum_m[j] - cum_m[i]
                    if m <= 0:
                        continue
                    molt = (cum_e[j] - cum_e[i]) / m
                    if molt <= 0 or abs(molt - 1.0) > banda:
                        continue
                    reale = tempo[j] - tempo[i]
                    in_piano = reale / molt
                    if nome not in migliori or in_piano < migliori[nome][0]:
                        migliori[nome] = (in_piano, corsa["data"], reale, molt)
    return migliori


def esponente_personale(record):
    """L'esponente di Riegel che descrive i SUOI record, invece dell'1,06.

    L'1,06 è il valore classico e presume di essere allenati su tutte le
    distanze. Un esponente più alto vuol dire che il passo cala più in
    fretta quando la distanza sale: più velocità che resistenza.

    Si adatta t = a·d^b in scala logaritmica. Due esclusioni, entrambe
    necessarie:

      · niente sotto i 1000 m — a 400 metri comanda un altro sistema
        energetico e la formula non lo descrive;
      · niente OLTRE l'ancora. Il record sui 10 km viene da dentro il lungo
        del 27/09 corso a 6:08/km: infilarlo nella regressione inventerebbe
        un crollo di resistenza che è solo un giorno andato piano, e
        l'esponente passerebbe da 1,12 a 1,3.

    Restituisce None con meno di tre punti: con due la retta passa per
    entrambi e non misura niente.
    """
    km = dict(DISTANZE_RECORD_KM)
    km_ancora = km.get(BASE_PREVISIONI)
    if not km_ancora:
        return None
    punti = [(km[n] * 1000, v[0]) for n, v in record.items()
             if n in km and 1000 <= km[n] * 1000 <= km_ancora * 1000 + 1]
    if len(punti) < 3:
        return None
    xs = [math.log(d) for d, _ in punti]
    ys = [math.log(s) for _, s in punti]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var


def stime_oggi(corse, piano=None):
    """Quanto potrebbe correre OGGI ogni distanza, se la corresse per davvero.

    Serve perché la colonna dei record non risponde a quella domanda. Sette
    record su nove vengono dal 18/08/2026, settimane
    prima, e nessuno da una prova: erano finestre dentro un allenamento con
    quattro allunghi. Il 10 km è peggio — viene da dentro il lungo del 27/09
    a 6:08/km, quindi dice quanto è andato piano quel giorno, non quanto vale.

    Il metodo è una riga: **il più veloce fra la proiezione dal 5 km e il
    record vero.** I due errori vanno in direzioni opposte e si annullano.

      · Verso le distanze CORTE Riegel lo sottovaluta: proiettato dal 5 km
        darebbe 4:48 sul chilometro, dove il record è 4:23. È perché ha più
        velocità che resistenza — l'esponente che descrive i suoi record è
        1,117, non l'1,06 standard. Lì vince il record.
      · Verso le LUNGHE è il record a sottovalutarlo, perché non le ha mai
        corse al massimo. Lì vince la proiezione: sul 10 km sono 55:07
        contro 1:00:45, cioè cinque minuti e mezzo che la tabella nascondeva.

    L'esponente resta 1,06 e non 1,117 di proposito: quell'1,117 è ricavato
    da finestre annidate nella stessa corsa, quindi il calo che misura è in
    parte la struttura di quella seduta e non la sua fisiologia. Il numero
    vero sta in mezzo, e lo dirà la prova sui 5 km.

    Restituisce {nome: {"secondi", "fonte"}}, con fonte 'record' o
    'proiezione'.
    """
    record = record_distanze(corse)
    piano_eq = record_in_piano(corse)
    base = piano_eq.get(BASE_PREVISIONI) or record.get(BASE_PREVISIONI)
    if not base:
        return {}
    t_base = base[0]
    km_base = dict(DISTANZE_RECORD_KM)[BASE_PREVISIONI]

    distanze = dict(DISTANZE_RECORD_KM)
    distanze.update(dict(GARE_PREVISTE))

    # L'altro estremo della forchetta. Vale solo OLTRE l'ancora: più corto
    # di così vince comunque il record, e sull'ancora i due esponenti danno
    # per costruzione lo stesso numero.
    # L'esponente dai record IN PIANO: con quelli reali misurerebbe la
    # pendenza dei percorsi invece del calo di resistenza.
    b = esponente_personale({k: (v[0],) for k, v in piano_eq.items()} or record)

    fuori = {}
    for nome, km in distanze.items():
        proiezione = t_base * (km / km_base) ** RIEGEL
        vero = record.get(nome)
        if vero and vero[0] <= proiezione:
            fuori[nome] = {"secondi": vero[0], "fonte": "record"}
            continue
        voce = {"secondi": proiezione, "fonte": "proiezione"}
        if b is not None and km > km_base:
            altro = t_base * (km / km_base) ** b
            if abs(altro - proiezione) > 30:
                voce["da"] = min(proiezione, altro)
                voce["a"] = max(proiezione, altro)
                voce["esponente"] = b
        fuori[nome] = voce
    return fuori


DISTANZE_RECORD_KM = [(nome, metri / 1000) for metri, nome in DISTANZE_RECORD]

def mmss(secondi):
    return f"{int(secondi // 60)}:{int(round(secondi % 60)):02d}"

def hms(secondi):
    """Come mmss, ma con le ore: una maratona in 252:15 non si legge."""
    secondi = int(round(secondi))
    ore, resto = divmod(secondi, 3600)
    minuti, sec = divmod(resto, 60)
    return f"{ore}:{minuti:02d}:{sec:02d}" if ore else f"{minuti}:{sec:02d}"

def num(valore, default=0):
    """Le colonne del CSV sono spesso vuote o 'N/D'."""
    try:
        return float(valore)
    except (TypeError, ValueError):
        return default

def carica_corse(dal=DAL):
    """Legge il CSV. Restituisce le corse dalla ripresa in poi."""
    if not os.path.exists(FILE_CSV):
        print(f"✗ File '{FILE_CSV}' non trovato.")
        print("  Esegui prima: python3 strava_sync.py")
        sys.exit(1)

    corse = []
    with open(FILE_CSV, "r", encoding="utf-8") as f:
        for riga in csv.DictReader(f):
            if riga["data"] < dal:
                continue
            zone = [num(riga.get(f"z{i}_min")) for i in range(1, 6)]
            cont = continuita(riga.get("id", ""))
            corse.append({
                "continua":   cont[0] if cont else None,
                "cont_min":   cont[1] if cont else None,
                "pezzi":      cont[2] if cont else None,
                "id":       riga.get("id", ""),
                "data":     riga["data"],
                "data_dt":  datetime.strptime(riga["data"], "%Y-%m-%d").date(),
                "nome":     riga["nome"],
                "km":       num(riga["km"]),
                "minuti":   int(num(riga["minuti"])),
                "passo":    riga["passo"],
                # Il terreno: dislivello e passo equivalente in piano, da
                # strava_pendenza.py. Senza questi, un trail e una corsa in
                # città finiscono nella stessa colonna come se fossero uguali.
                "dislivello":  num(riga.get("dislivello")),
                "km_equiv":    num(riga.get("km_equiv")),
                "passo_equiv": riga.get("passo_equiv") or "",
                "bpm":      num(riga.get("bpm_media")),
                "bpm_max":  num(riga.get("bpm_max")),
                "zone":     zone,
                "ha_zone":  sum(zone) > 0,
            })
            corse[-1]["salita_per_km"] = (corse[-1]["dislivello"] / corse[-1]["km"]
                                          if corse[-1]["km"] else 0)

    if not corse:
        print(f"✗ Nessuna corsa dal {dal} in poi.")
        sys.exit(1)

    corse.sort(key=lambda c: c["data_dt"])
    return corse

# ============================================
# SETTIMANE
# ============================================

def lunedi_di(giorno):
    return giorno - timedelta(days=giorno.weekday())

def raggruppa_settimane(corse):
    """Una voce per settimana, dal lunedì. Le settimane senza corse ci sono lo stesso:
    uno zero è un dato, non un buco."""
    primo  = lunedi_di(corse[0]["data_dt"])
    ultimo = lunedi_di(max(corse[-1]["data_dt"], date.today()))

    settimane = []
    lun = primo
    while lun <= ultimo:
        della_settimana = [c for c in corse if lunedi_di(c["data_dt"]) == lun]
        zone_tot = [0.0] * 5
        min_con_zone = 0
        for c in della_settimana:
            if c["ha_zone"]:
                for i in range(5):
                    zone_tot[i] += c["zone"][i]
                min_con_zone += sum(c["zone"])
        settimane.append({
            "lunedi":       lun,
            "etichetta":    lun.strftime("%d/%m"),
            "corse":        della_settimana,
            "n":            len(della_settimana),
            "km":           round(sum(c["km"] for c in della_settimana), 1),
            "minuti":       sum(c["minuti"] for c in della_settimana),
            "lungo":        round(max((c["km"] for c in della_settimana), default=0), 1),
            "continua":     round(max((c["continua"] or 0 for c in della_settimana), default=0), 2),
            "zone":         zone_tot,
            "min_con_zone": min_con_zone,
            "in_corso":     lun == lunedi_di(date.today()),
        })
        lun += timedelta(days=7)
    return settimane

def perc_facile(settimana):
    """Percentuale di minuti in Z1-Z2. None se nessuna corsa ha dati cardio."""
    if not settimana["min_con_zone"]:
        return None
    facili = settimana["zone"][0] + settimana["zone"][1]
    return facili / settimana["min_con_zone"] * 100

# ============================================
# COSA PREVEDE IL PIANO
# ============================================

def volume_previsto(fase, sett_nella_fase):
    """Dalla fase 1 si sale del 10% ogni 4 settimane, con la quarta in scarico.

    Fase 0 sale piano da 30 a 40 km. I 40 km della settimana del 10 agosto
    erano possibili solo grazie alle soste: correndo di fila, con un record
    di 6,5 km ininterrotti, il volume vero di partenza è 30."""
    if fase == 0:
        return float(min(30 + sett_nella_fase * 2, 40))

    if fase == 1:
        blocco = sett_nella_fase // 4
        base   = min(42.0 * (1.10 ** blocco), 58.0)
        return round(base * (0.75 if sett_nella_fase % 4 == 3 else 1.0), 1)

    # Fase 2: si costruisce fino a 3 settimane dalla gara, poi si scarica.
    scarico_da = DURATA_FASE2 - SCARICO_FINALE
    if sett_nella_fase >= scarico_da:
        return round(62.0 * [0.75, 0.60, 0.40][min(sett_nella_fase - scarico_da, 2)], 1)
    blocco = sett_nella_fase // 4
    base   = min(52.0 * (1.08 ** blocco), 62.0)
    return round(base * (0.75 if sett_nella_fase % 4 == 3 else 1.0), 1)

# Quanto può pesare il lungo sul volume della settimana. Oltre questa quota
# la settimana diventa "un lungo e tre passeggiate": è il profilo che produce
# infortuni. Nel blocco maratona il tetto è più alto per forza di cose —
# vedi la nota sulla quinta uscita in PIANO_MARATONA.md.
TETTO_LUNGO = {0: 0.40, 1: 0.42, 2: 0.52}

def lungo_previsto(fase, sett_nella_fase):
    """Il lungo cresce, ma nelle settimane di scarico cala insieme al volume:
    scaricare tutto tranne il lungo non è scaricare."""
    # Nella fase 2 le settimane dalla 14 in poi escono prima (scarico gara),
    # quindi qui basta la regola del quarto di ciclo.
    scarico = fase >= 1 and sett_nella_fase % 4 == 3

    if fase == 0:
        # Ritarato il 2026-08-19 sera: il record di corsa ininterrotta è passato
        # da 6,49 a 7,52 km (54 minuti, zero soste). Partire da 8
        # sarebbe stato un +6%, troppo poco. Da 9 il primo salto è +20%, il
        # limite alto della progressione sana per un lungo.
        lungo = min(9 + sett_nella_fase * 1.0, 13.0)
    elif fase == 1:
        lungo = min(13 + sett_nella_fase * 0.8, 24.0)
    elif sett_nella_fase >= DURATA_FASE2 - SCARICO_FINALE:
        # Scarico verso la gara: qui il lungo cala e basta.
        return [20.0, 14.0, 8.0][min(sett_nella_fase - (DURATA_FASE2 - SCARICO_FINALE), 2)]
    else:
        # Da 24 a 32 km distribuiti sulle settimane di costruzione disponibili.
        costruzione = max(DURATA_FASE2 - SCARICO_FINALE - 1, 1)
        lungo = min(24 + sett_nella_fase * (8.0 / costruzione), 32.0)

    if scarico:
        lungo *= 0.70

    # Il tetto ha sempre l'ultima parola.
    tetto = volume_previsto(fase, sett_nella_fase) * TETTO_LUNGO[fase]
    return round(min(lungo, tetto), 1)

def settimana_tipo(fase, sett_nella_fase, giorni=4):
    """Le uscite della settimana, con i km di ciascuna.

    Con 5 giorni il volume NON aumenta: lo stesso totale si spalma su una
    corsa in più, quindi ogni singola uscita è più corta. È il modo più
    sicuro che esista di correre di più — si aggiungono giorni di corsa,
    non carico."""
    f       = FASI[fase]
    volume  = volume_previsto(fase, sett_nella_fase)
    lungo   = lungo_previsto(fase, sett_nella_fase)
    # Il lungo lo fissiamo, il resto si divide quello che avanza.
    resto   = volume - lungo
    nomi    = list(f["sedute"][:-1])
    pesi    = list(f["ratio"][:-1])

    if giorni >= 5:
        nomi.append("Facile corto")
        pesi.append(min(pesi) * 0.60)

    tot    = sum(pesi)
    sedute = [(nome, round(resto * p / tot, 1)) for nome, p in zip(nomi, pesi)]

    # Nessuna uscita infrasettimanale può superare il lungo: se succede, il
    # "lungo" non è più il lungo. Meglio una settimana che chiude sotto il
    # volume previsto che tre lunghi travestiti da facili.
    tetto = round(lungo * 0.85, 1)
    sedute = [(nome, min(km, tetto)) for nome, km in sedute]

    sedute.append((f["sedute"][-1], lungo))
    return sedute, round(sum(km for _, km in sedute), 1)

def etichetta_rientro(rientro):
    """«STOP» o «RIENTRO»: un blocco senza sedute non è un rientro graduale,
    è uno stop, e chiamarlo col nome giusto cambia come lo si legge."""
    return "STOP" if rientro.get("tipo") == "stop" or not rientro.get("sedute") else "RIENTRO"


def stampa_rientro(rientro, indent="  "):
    """Il cartello della sospensione, uguale in tutti i comandi."""
    fine = f"{rientro['al'][8:10]}/{rientro['al'][5:7]}"
    etichetta = etichetta_rientro(rientro)
    coda = "da rivedere il" if rientro.get("condizione") else "fino al"
    print(f"{indent}{etichetta} — {coda} {fine}, la settimana normale è sospesa")
    print(f"{indent}{rientro['perche']}")
    if rientro.get("prima"):
        print(f"{indent}PRIMA: {rientro['prima']}")
    print(f"{indent}Vietato: {rientro['vietato']}")
    if rientro.get("si_puo"):
        print(f"{indent}Si può: {rientro['si_puo']}")
    print(f"{indent}{rientro['regola']}")
    if rientro.get("condizione"):
        print(f"{indent}{rientro['condizione']}")


def rientro_attivo(piano, settimana):
    """La settimana ridotta dopo un fastidio, se è questa e non è scaduta.

    Un rientro ha SEMPRE una data di fine. Senza, resterebbe a limitare il
    piano per sempre: il modo più facile di trasformare dieci giorni di
    prudenza in un mese perso è dimenticarsi di toglierlo.

    Con 'per_settimana' il rientro copre più settimane, ognuna col proprio
    volume e le proprie sedute: è la rampa di risalita. Serve perché il piano
    da solo, dopo una settimana da 17 km, prescriverebbe 36 — e il tracker
    stamperebbe il suo allarme sul +10% contro il piano stesso.

    Restituisce il dizionario del rientro (fuso con la voce della settimana,
    se c'è), oppure None."""
    r = piano.get("rientro")
    if not r:
        return None
    try:
        dal = datetime.strptime(r["dal"], "%Y-%m-%d").date()
        al  = datetime.strptime(r["al"], "%Y-%m-%d").date()
    except (KeyError, ValueError):
        return None
    if date.today() > al:
        return None
    # Vale per le settimane che il rientro attraversa, non per quelle dopo.
    if not (lunedi_di(dal) <= settimana["lunedi"] <= lunedi_di(al)):
        return None

    calendario = r.get("per_settimana")
    if not calendario:
        return r
    # Una settimana dentro l'intervallo ma senza voce nel calendario NON è
    # coperta: la rampa è finita e il piano normale riprende, anche se la
    # data di fine non è ancora passata.
    voce = calendario.get(settimana["lunedi"].isoformat())
    return {**r, **voce} if voce else None


def evento_in_sospeso(piano, settimana):
    """L'evento di questa settimana, se c'è ed è ancora da correre.

    Un evento è una data fissa che occupa una delle uscite: una gara, un
    trail, un test. Restituisce il dizionario — comodo da stampare — o None."""
    ev = piano.get("evento") or piano.get("test")
    if not ev:
        return None
    try:
        d = datetime.strptime(ev["data"], "%Y-%m-%d").date()
    except (KeyError, ValueError):
        return None
    if lunedi_di(d) != settimana["lunedi"] or d < date.today():
        return None
    # Un evento è "in sospeso" finché non c'è una corsa in quella data. Il solo
    # confronto con oggi non basta: la mattina della gara la data è ancora >=
    # oggi, e la sera il trail risulterebbe da fare dopo averlo corso.
    if any(c["data"] == ev["data"] for c in settimana.get("corse", [])):
        return None
    return ev

def evento_sostituisce_lungo(evento, lungo):
    """Un evento abbastanza lungo È il lungo della settimana, non si aggiunge.

    Correre 14 km di trail la domenica e poi anche il lungo previsto è il modo
    più rapido per trasformare una settimana buona in un infortunio."""
    if not evento:
        return False
    if "sostituisce" in evento:
        return evento["sostituisce"] == "Lungo"
    return evento.get("km", 0) >= lungo - 0.3

def sedute_rimanenti(piano, settimana, fase, n_sett, evento=None):
    """Le uscite che restano in una settimana già cominciata.

    Non ridistribuisce il piano: toglie sedute, tagliando la qualità per prima.
    Il lungo si toglie solo se è GIÀ STATO FATTO — cosa che va controllata sui
    dati, non data per scontata: chi corre il lungo di mercoledì non se lo
    ritrova da fare anche domenica.

    Il totale restituito è SEMPRE quello pieno della settimana, evento
    compreso. I due rami davano due cose diverse — col rientro il volume
    dichiarato (che la gara la contiene già), senza rientro una somma che non
    la conteneva — e chi chiamava aggiungeva i km dell'evento a entrambi: la
    settimana della gara risultava da 45 km invece che da 30."""
    # Un rientro sostituisce la settimana, non la corregge: le sedute previste
    # non valgono più, e non si tenta di recuperarle. Restano quelle del
    # rientro che non hai ancora fatto.
    km_evento = (evento or {}).get("km", 0) or 0

    rientro = rientro_attivo(piano, settimana)
    if rientro:
        # Si scalano solo le corse fatte DA QUANDO il rientro è cominciato:
        # quella che ha fatto male è nella stessa settimana ma viene prima,
        # e non è una seduta del rientro.
        gia_fatte = sum(1 for c in settimana.get("corse", [])
                        if c["data"] >= rientro["dal"])
        rimaste = [(s["nome"], s["km"]) for s in rientro["sedute"]][gia_fatte:]
        # Il volume del rientro è un programma, non un tetto: se ha già corso
        # più di quanto prevedeva, il totale della settimana è quello vero.
        # Altrimenti la settimana in cui allunga di un chilometro continua a
        # dichiarare il numero del foglio e sembra che manchi meno di quanto manca.
        programmato = settimana["km"] + sum(k for _, k in rimaste) + km_evento
        return rimaste, max(rientro.get("volume", programmato), programmato)

    sedute, vol_previsto = settimana_tipo(fase, n_sett, piano["giorni_settimana"])
    lungo     = lungo_previsto(fase, n_sett)

    # Il lungo conta come fatto se una corsa della settimana ha coperto la
    # distanza prevista SENZA fermarsi: è quello che il lungo allena.
    lungo_fatto = settimana["continua"] >= lungo - 0.3

    # L'evento della settimana può ESSERE il lungo: in quel caso il lungo non
    # resta da fare, altrimenti finisce in calendario due volte.
    lungo_coperto = lungo_fatto or evento_sostituisce_lungo(evento, lungo)

    rimaste = [s for s in sedute if not (lungo_coperto and s[0] == "Lungo")]

    # Un evento programmato occupa una delle uscite della settimana.
    restano_n = max(piano["giorni_settimana"] - settimana["n"] - (1 if evento else 0), 0)

    if restano_n <= 0:
        return [], settimana["km"] + km_evento
    if restano_n >= len(rimaste):
        return rimaste, settimana["km"] + sum(km for _, km in rimaste) + km_evento

    for _ in range(len(rimaste) - restano_n):
        tagliabili = [i for i, (nome, _) in enumerate(rimaste)
                      if nome in ("Qualità", "Soglia", "Ritmo maratona")]
        i = tagliabili[0] if tagliabili else next(
            (j for j, (nome, _) in enumerate(rimaste) if nome != "Lungo"), 0)
        rimaste.pop(i)

    # Un evento che sostituisce il lungo può essere più lungo del lungo: se il
    # totale sfonda il volume della settimana si toglie una seduta. Il carico
    # della settimana non si allarga per fare spazio a una gara.
    if evento:
        km_evento = evento.get("km", 0)
        while rimaste and (settimana["km"] + km_evento
                           + sum(km for _, km in rimaste)) > vol_previsto:
            tagliabili = [i for i, (nome, _) in enumerate(rimaste)
                          if nome in ("Qualità", "Soglia", "Ritmo maratona")]
            i = tagliabili[0] if tagliabili else next(
                (j for j, (nome, _) in enumerate(rimaste) if nome != "Lungo"), 0)
            rimaste.pop(i)

    return rimaste, settimana["km"] + sum(km for _, km in rimaste) + km_evento

def settimane_nella_fase(piano, settimane):
    """Quante settimane piene sono passate dall'inizio della fase corrente."""
    inizio = lunedi_di(datetime.strptime(piano["fase_inizio"], "%Y-%m-%d").date())
    return max(0, sum(1 for s in settimane if s["lunedi"] >= inizio and not s["in_corso"]))

# ============================================
# I CANCELLI
# ============================================

def valuta_cancello(fase, settimane, corse):
    """Restituisce (lista di criteri, aperto). Ogni criterio: (fatto, testo, dettaglio)."""
    chiuse = [s for s in settimane if not s["in_corso"]]
    criteri = []

    if fase == 0:
        ultime4 = chiuse[-4:]
        n_ok = sum(1 for s in ultime4 if s["km"] >= CANCELLO0_SETT_KM)
        # Elencarle: senza, non si capisce QUALI settimane stiano contando —
        # e quelle prima dell'inizio del piano contano eccome.
        elenco = " · ".join(f"{'✓' if s['km'] >= CANCELLO0_SETT_KM else '✗'}"
                            f"{s['etichetta']} {s['km']:.0f}"
                            for s in ultime4)
        criteri.append((len(ultime4) == 4 and n_ok == 4,
                        f"4 settimane di fila ≥ {CANCELLO0_SETT_KM} km",
                        f"{n_ok}/4 — {elenco}"))

        cont_max = max((s["continua"] for s in settimane), default=0)
        criteri.append((cont_max >= CANCELLO0_LUNGO_KM,
                        f"Un lungo ≥ {CANCELLO0_LUNGO_KM} km CORRENDO, senza soste né camminate",
                        f"record di corsa ininterrotta: {cont_max} km"))

        recenti    = settimane[-4:]          # inclusa quella in corso
        min_tot    = sum(s["min_con_zone"] for s in recenti)
        min_facili = sum(s["zone"][0] + s["zone"][1] for s in recenti)
        con_dati   = sum(1 for s in recenti if s["min_con_zone"])
        media      = (min_facili / min_tot * 100) if min_tot else None
        criteri.append((media is not None and media >= CANCELLO0_FACILE_PERC,
                        f"≥ {CANCELLO0_FACILE_PERC}% del tempo in Z1-Z2",
                        f"{media:.0f}% su {min_tot:.0f} min misurati in {con_dati} settimane"
                        if media is not None else "nessun dato cardio"))

        criteri.append((None,
                        "Nessun dolore che dura oltre 48h",
                        "questo lo sai solo tu — i dati non lo vedono"))

    elif fase == 1:
        mezze = [c for c in corse if c["km"] >= 21.0 and c["minuti"] <= MEZZA_OBIETTIVO_MIN]
        migliore = min((c["minuti"] for c in corse if c["km"] >= 21.0), default=None)
        criteri.append((len(mezze) > 0,
                        "Mezza maratona sotto 1:52",
                        f"migliore: {migliore} min" if migliore else "nessuna mezza ancora"))

        n52 = sum(1 for s in chiuse if s["km"] >= 52)
        criteri.append((n52 >= 8, "8 settimane ≥ 52 km", f"{n52}/8 finora"))

        n21 = sum(1 for s in chiuse if s["continua"] >= 21)
        criteri.append((n21 >= 2, "Due lunghi ≥ 21 km corsi, senza soste né camminate", f"{n21}/2 finora"))

    else:
        criteri.append((None, "Il cancello della fase 2 è la gara stessa", ""))

    veri = [c[0] for c in criteri if c[0] is not None]
    return criteri, bool(veri) and all(veri)

# ============================================
# STAMPA
# ============================================

LARGH = 60

def sep(carattere="─"):
    print(carattere * LARGH)

def titolo(testo):
    print()
    sep("═")
    print(f"  {testo}")
    sep("═")

def barra(fatto, previsto, larghezza=24):
    if previsto <= 0:
        return " " * larghezza
    quota = min(fatto / previsto, 1.4)
    pieni = int(round(quota * larghezza))
    return "█" * min(pieni, larghezza) + "▓" * max(0, pieni - larghezza)

# Finestre su cui cercare la media cardiaca più alta sostenuta. La 30 minuti
# è quella che conta: la frequenza che si tiene per mezz'ora È la soglia, o
# pochissimo sopra. È l'unica misura di soglia ricavabile senza un test.
FINESTRE_SOGLIA = [(60, "1 min"), (300, "5 min"), (600, "10 min"),
                   (1200, "20 min"), (1800, "30 min")]


def cardio_sostenuto(corse):
    """La media cardiaca più alta tenuta per ogni finestra, su tutto l'archivio.

    Serve a stimare la soglia dai dati che ci sono, invece di assumerla da una
    frequenza massima teorica: una massima ipotizzata sposta tutti i confini,
    mentre trenta minuti sostenuti sono un fatto."""
    migliori = {nome: (0.0, None) for _, nome in FINESTRE_SOGLIA}
    for corsa in corse:
        percorso = os.path.join(CARTELLA_STREAMS, f"{corsa['id']}.json")
        if not os.path.exists(percorso):
            continue
        try:
            with open(percorso, "r", encoding="utf-8") as f:
                s = json.load(f)
            tempo, hr = s["time"], s["heartrate"]
        except (KeyError, ValueError, OSError, TypeError):
            continue
        if not hr:
            continue

        validi = [(tempo[i], hr[i]) for i in range(min(len(tempo), len(hr))) if hr[i]]
        if len(validi) < 60:
            continue
        tt = [v[0] for v in validi]
        # Somme cumulative: la media di una finestra è una sottrazione, non un
        # ciclo dentro il ciclo. Su 2500 campioni per corsa la differenza conta.
        cum = [0]
        for _, b in validi:
            cum.append(cum[-1] + b)

        for secondi, nome in FINESTRE_SOGLIA:
            j = 0
            for i in range(len(tt)):
                while j < len(tt) and tt[j] - tt[i] < secondi:
                    j += 1
                if j >= len(tt):
                    break
                media = (cum[j] - cum[i]) / (j - i)
                if media > migliori[nome][0]:
                    migliori[nome] = (media, corsa["data"])
    return migliori


def stampa_soglie(corse):
    """Cosa i dati dicono delle zone, senza assumere la frequenza massima."""
    titolo("LE TUE ZONE — cosa dicono i dati")
    print(f"  Su {len(corse)} corse, tutte le stagioni: massima e soglia non")
    print("  scadono, quindi qui il filtro della stagione in corso non si applica.")
    print()
    soglie, vere = carica_soglie()
    massima = max((c["bpm_max"] for c in corse if c.get("bpm_max")), default=0)

    sostenuto = cardio_sostenuto(corse)
    print("  La media più alta che hai tenuto:")
    for _, nome in FINESTRE_SOGLIA:
        v, quando = sostenuto[nome]
        if v:
            print(f"    {nome:8} {v:5.1f} bpm   ({quando})")

    soglia30 = sostenuto["30 min"][0]
    print()
    print(f"  Soglie in uso: {soglie}  ({'vere di Strava' if vere else 'stimate'})")
    print(f"  Confine Z3/Z4 (la soglia, secondo le zone): {soglie[3]}")
    if soglia30:
        print(f"  Soglia misurata (30 min sostenuti):         {soglia30:.0f}")
        print(f"  Scarto fra le due strade: {abs(soglie[3] - soglia30):.0f} battiti")
        print()
        print("  Massima che una soglia così implica (88-92% della massima):")
        print(f"    fra {soglia30/0.92:.0f} e {soglia30/0.88:.0f} bpm")
        print(f"  Massima mai osservata: {massima:.0f} (è un minimo, non un test)")
    print()
    print("  Per stringere serve un 5 km corso davvero al massimo: dà un picco")
    print("  vicino al vero e una media sostenuta su ~25 minuti. Gli streams")
    print("  sono su disco, quindi ricalibrare ricalcola tutto l'archivio.")


def stampa_report(piano, corse, settimane):
    fase   = piano["fase"]
    f      = FASI[fase]
    n_sett = settimane_nella_fase(piano, settimane)
    corrente = settimane[-1]
    precedenti = [s for s in settimane if not s["in_corso"]]

    titolo(f"FASE {fase} · {f['nome'].upper()}")
    print(f"  {f['scopo']}")
    print(f"  Durata indicativa: {f['durata']} — sei alla settimana {n_sett + 1}")
    print(f"  Obiettivo: {piano['obiettivo']} ({piano['ritmo_gara']}/km)")

    # ── SETTIMANA IN CORSO ────────────────────────
    sedute, vol_previsto = settimana_tipo(fase, n_sett, piano["giorni_settimana"])
    lungo_obiettivo = lungo_previsto(fase, n_sett)

    # Un rientro sostituisce gli obiettivi della settimana: mostrarne altri
    # qui vorrebbe dire dare due istruzioni contraddittorie nella stessa pagina.
    rientro = rientro_attivo(piano, corrente)
    if rientro:
        vol_previsto = rientro.get("volume", vol_previsto)

    titolo(f"SETTIMANA IN CORSO — dal {corrente['etichetta']}")
    if rientro:
        stampa_rientro(rientro)
        print()
    print(f"  Volume    {corrente['km']:5.1f} / {vol_previsto:4.1f} km  {barra(corrente['km'], vol_previsto)}")
    if rientro:
        print(f"  Uscite    {corrente['n']:5d} /    ?   (dipende da come va la prova)")
        print("  Lungo         —       nessuno, questa settimana")
    else:
        print(f"  Uscite    {corrente['n']:5d} / {piano['giorni_settimana']:4d}")
        print(f"  Lungo     {corrente['lungo']:5.1f} / {lungo_obiettivo:4.1f} km")
    print(f"  Continua  {corrente['continua']:5.2f} km  ← il numero che conta")

    p = perc_facile(corrente)
    if p is not None:
        stato = "✓" if p >= 85 else "⚠"
        print(f"  In Z1-Z2  {p:5.0f} %   (obiettivo ≥ 85%)  {stato}")
    else:
        print("  In Z1-Z2      —   (nessun dato cardio questa settimana)")

    # ── ALLARME VOLUME ────────────────────────────
    inizio_fase = lunedi_di(datetime.strptime(piano["fase_inizio"], "%Y-%m-%d").date())
    precedenti = [s for s in precedenti if s["lunedi"] >= inizio_fase]
    if len(precedenti) >= 2:
        ultima, penultima = precedenti[-1], precedenti[-2]
        if penultima["km"] > 0:
            delta = (ultima["km"] - penultima["km"]) / penultima["km"] * 100
            fra = (f"dal {penultima['etichetta']} ({penultima['km']:.0f} km) "
                   f"al {ultima['etichetta']} ({ultima['km']:.0f} km)")
            print()
            if delta > 10:
                print(f"  ⚠  Volume +{delta:.0f}% {fra}")
                print("     Oltre il 10% è la strada per lo stress da carico.")
            elif delta < -25:
                print(f"  ·  Volume {delta:.0f}% {fra}: scarico o stop")
            else:
                print(f"  ✓  Progressione del volume {delta:+.0f}% {fra}  (sotto il 10%)")

    # ── LE SEDUTE DA FARE ─────────────────────────
    # Niente `corrente["n"] and ...`: con zero corse fatte la sezione spariva,
    # cioè proprio il lunedì, il giorno in cui serve sapere cosa c'è davanti.
    if corrente["n"] <= piano["giorni_settimana"]:
        evento = evento_in_sospeso(piano, corrente)
        rimanenti, totale = sedute_rimanenti(piano, corrente, fase, n_sett, evento)

        titolo("COSA RESTA DA FARE QUESTA SETTIMANA")
        if corrente["n"]:
            print(f"  Già fatto: {corrente['n']} uscita/e, {corrente['km']:.1f} km")
        else:
            print("  Settimana ancora da cominciare.")

        lungo_fatto = corrente["continua"] >= lungo_obiettivo - 0.3
        if lungo_fatto:
            print(f"  Lungo: ✓ fatto ({corrente['continua']:.2f} km di fila, "
                  f"previsto {lungo_obiettivo:.1f})")
        print()

        for nome, km in rimanenti:
            print(f"  {nome:<16} {km:5.1f} km   {ritmo_di(nome, rientro)}")
        if evento:
            km_ev = evento.get("km", 6.0)
            etichetta = evento.get("etichetta", "Evento").capitalize()
            print(f"  {etichetta:<16} {km_ev:5.1f} km   {evento['nome']} — "
                  f"{evento['data'][8:10]}/{evento['data'][5:7]}")
        if not rimanenti and not evento:
            print("  Niente da correre."
                  if rientro else
                  "  Niente: le uscite della settimana sono tutte fatte.")
        print(f"  {'':<16} {totale:5.1f} km  totale settimana")

        if rientro:
            print(f"\n  {rientro['regola']}")
            print("  Chiudere sotto il volume, questa settimana, è l'obiettivo —")
            print("  non un ritardo da recuperare.")
        elif totale < vol_previsto - 1:
            print(f"\n  Chiude sotto i {vol_previsto:.0f} km previsti: la settimana è")
            print("  cominciata a metà. Va bene — il cancello lo apre il lungo,")
            print("  non il totale settimanale.")
    else:
        titolo("LA SETTIMANA CHE IL PIANO PREVEDE")
        for nome, km in sedute:
            print(f"  {nome:<16} {km:5.1f} km   {ritmo_di(nome, rientro)}")
        print(f"  {'':<16} {vol_previsto:5.1f} km  totale")

    # ── CANCELLO ──────────────────────────────────
    stampa_cancello(fase, settimane, corse)

def ritmo_di(nome_seduta, rientro=None):
    """Come si corre questa seduta.

    Le sedute di un rientro portano il proprio testo: sono istruzioni per una
    situazione, non un tipo di allenamento che esiste sempre. Si passa il
    rientro GIÀ RISOLTO per la settimana in corso, non il piano intero —
    nella rampa il nome «Facile» compare in tre settimane diverse con
    chilometri e istruzioni diverse, e cercare per nome nel piano intero
    pescherebbe la voce sbagliata."""
    if rientro:
        for s in rientro.get("sedute", []):
            if s["nome"] == nome_seduta:
                return s.get("come", "")
    return {
        "Facile":         "FC sotto 150 · il passo lo decide il cuore",
        "Facile corto":   "FC sotto 145 · il più lento della settimana",
        "Lungo":          "FC sotto 150, fino a 155 sul finale",
        "Qualità":        "10' scaldare + 4×3' a 5:30 rec 2' + defaticare",
        "Soglia":         "15' scaldare + 20-30' a ~5:00/km + defaticare",
        "Ritmo maratona": "blocchi a 5:41/km dentro il medio",
    }.get(nome_seduta, "")

def stampa_cancello(fase, settimane, corse):
    criteri, aperto = valuta_cancello(fase, settimane, corse)
    titolo(f"CANCELLO PER LA FASE {fase + 1}" if fase < 2 else "TRAGUARDO")
    for fatto, testo, dettaglio in criteri:
        simbolo = "✓" if fatto else ("·" if fatto is None else "✗")
        print(f"  {simbolo}  {testo}")
        if dettaglio:
            print(f"     {dettaglio}")
    print()
    if fase >= 2:
        print("  Sei nel blocco finale. Il cancello è il traguardo.")
    elif aperto:
        print(f"  ✓  Cancello APERTO — puoi passare alla fase {fase + 1}.")
        print("     python3 strava_piano.py --avanza")
    else:
        print("  Cancello ancora chiuso. Nessuna fretta: è il punto del piano.")

def stampa_storico(settimane, piano):
    titolo("STORICO SETTIMANALE")
    print(f"  {'sett':<8}{'km':>6}{'prev':>7}{'usc':>5}{'lungo':>7}{'Z1-Z2':>7}   andamento")
    sep()
    fase   = piano["fase"]
    inizio = lunedi_di(datetime.strptime(piano["fase_inizio"], "%Y-%m-%d").date())
    for s in settimane:
        dentro = s["lunedi"] >= inizio
        prev   = volume_previsto(fase, (s["lunedi"] - inizio).days // 7) if dentro else 0.0
        p      = perc_facile(s)
        pt     = f"{p:.0f}%" if p is not None else "—"
        nota   = " (in corso)" if s["in_corso"] else ""
        pv     = f"{prev:7.1f}" if dentro else f"{'—':>7}"
        print(f"  {s['etichetta']:<8}{s['km']:6.1f}{pv}{s['n']:5d}"
              f"{s['lungo']:7.1f}{pt:>7}   {barra(s['km'], prev, 16)}{nota}")

def avanza_fase(piano, settimane, corse):
    fase = piano["fase"]
    if fase >= 2:
        print("✗ Sei già nell'ultima fase.")
        return
    criteri, aperto = valuta_cancello(fase, settimane, corse)
    if not aperto:
        print(f"✗ Il cancello per la fase {fase + 1} è ancora chiuso.")
        stampa_cancello(fase, settimane, corse)
        print("\n  Se vuoi passare lo stesso, modifica 'fase' a mano in piano.json.")
        return
    piano["fase"] = fase + 1
    piano["fase_inizio"] = lunedi_di(date.today()).isoformat()
    salva_piano(piano)
    print(f"✓ Passato alla fase {fase + 1} · {FASI[fase + 1]['nome']}")
    print(f"  Inizio: {piano['fase_inizio']}")

# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

if __name__ == "__main__":
    piano     = carica_piano()
    DURATA_FASE2 = durata_fase2(piano)   # noqa: F811 — la gara decide il blocco
    corse     = carica_corse()
    settimane = raggruppa_settimane(corse)
    soglie, vere = carica_soglie()

    if "--avanza" in sys.argv:
        avanza_fase(piano, settimane, corse)
    elif "--cancelli" in sys.argv:
        stampa_cancello(piano["fase"], settimane, corse)
    elif "--record" in sys.argv:
        titolo("RECORD PERSONALI")
        print("  Cercati solo dentro i tratti corsi senza fermarsi.\n")
        migliori = record_distanze(corse)
        for metri, nome in DISTANZE_RECORD:
            if nome in migliori:
                t, data = migliori[nome]
                passo = mmss(t / (metri / 1000))
                print(f"  {nome:<10} {mmss(t):>8}   {passo}/km   {data}")
            else:
                print(f"  {nome:<10} {'—':>8}   da conquistare")
    elif "--sosta-forzata" in sys.argv:
        # uso: --sosta-forzata AAAA-MM-GG KM "motivo"
        i = sys.argv.index("--sosta-forzata")
        args = sys.argv[i+1:i+4]
        if len(args) < 2:
            print("  uso: --sosta-forzata AAAA-MM-GG KM [\"motivo\"]")
            sys.exit(1)
        data_c, km = args[0], float(args[1])
        perche = args[2] if len(args) > 2 else "sosta forzata"
        scelte = [c for c in corse if c["data"] == data_c]
        if not scelte:
            print(f"  Nessuna corsa il {data_c}.")
            sys.exit(1)
        c = scelte[0]
        prima = continuita(c["id"])
        salva_sosta_forzata(c["id"], km, perche)
        dopo = continuita(c["id"])
        titolo("SOSTA SEGNATA COME FORZATA")
        print(f"  {data_c} · {c['nome']} · al km {km:.2f} — {perche}\n")
        if dopo.km == prima.km:
            print(f"  ⚠ La corsa continua non cambia ({dopo.km:.2f} km).")
            print("     Al km indicato non risulta nessuna sosta: controlla la")
            print(f"     distanza (tolleranza ±{TOLLERANZA_SOSTA_KM*1000:.0f} m).")
        else:
            print(f"  Corsa continua   {prima.km:.2f} km  →  {dopo.km:.2f} km")
            print(f"  Pezzi            {prima.pezzi}  →  {dopo.pezzi}")
        print(f"  Fermo {dopo.fermo}′, di cui {dopo.forzato}′ non dipesi da te.")
    elif "--soglie" in sys.argv:
        # Qui si guarda tutto l'archivio, 2025 compreso: la massima e la
        # soglia sono ancore fisiologiche e non scadono con la stagione. Per
        # il resto del tracker vale il filtro da DAL in poi.
        stampa_soglie(carica_corse(dal="2000-01-01"))
    elif "--storico" in sys.argv:
        stampa_storico(settimane, piano)
    elif "--settimana" in sys.argv:
        n = settimane_nella_fase(piano, settimane)
        rientro = rientro_attivo(piano, settimane[-1])
        if rientro:
            sedute = [(s["nome"], s["km"]) for s in rientro["sedute"]]
            vol = rientro.get("volume", sum(k for _, k in sedute))
        else:
            sedute, vol = settimana_tipo(piano["fase"], n, piano["giorni_settimana"])
        titolo(f"SETTIMANA {n + 1} — FASE {piano['fase']} · {FASI[piano['fase']]['nome']}")
        if rientro:
            stampa_rientro(rientro)
            print()
            if not sedute:
                print("  Nessuna seduta: questa settimana non si corre.")
        for nome, km in sedute:
            print(f"  {nome:<16} {km:5.1f} km   {ritmo_di(nome, rientro)}")
        print(f"  {'':<16} {vol:5.1f} km  totale")
    elif "--html" in sys.argv:
        import piano_html
        piano_html.genera(FILE_HTML, piano, corse, settimane, FASI)
        print(f"✓ Pagina scritta in '{FILE_HTML}'")
    else:
        stampa_report(piano, corse, settimane)
        if not vere:
            print(f"\n  ⚠ Soglie zone stimate da HRmax {HR_MASSIMA} (dati/soglie_zone.json assente).")
        print()
