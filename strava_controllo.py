# ============================================
# STRAVA CONTROLLO — CHECKUP DELL'ARCHIVIO
# ============================================
# Verifica tutto quello che si può verificare senza fidarsi di niente:
# completezza, zone cardiache, coerenza interna, qualità del segnale,
# e cosa resta in piedi quando il premium scade.
#
# PERCHÉ ESISTE
#   L'archivio in 'dati/' è la sola copia che resta dopo la scadenza della
#   prova premium (18/09/2026). Se ha un buco, lo si scopre quando non si
#   può più rimediare. Questo script lo cerca prima.
#
# COME SI USA
#   python3 strava_controllo.py            tutti i controlli, offline
#   python3 strava_controllo.py --online   aggiunge il confronto con Strava
#   python3 strava_controllo.py --tutto    include anche la stagione 2025
#
# Esce con codice 1 se trova almeno un problema grave (✗).
# ============================================

import csv
import glob
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta

import strava_pendenza
import strava_sync

DAL_2026 = "2026-01-01"

# Sopra questo scarto fra le zone di Strava e quelle che ricalcoliamo dagli
# streams il ripiego non è più affidabile. 60 secondi su una corsa da 40
# minuti è il 2,5%: sotto, la differenza non cambia nessuna decisione.
SCARTO_ZONE_SEC = 60

# Frequenza cardiaca oltre la quale il dato è dello strumento, non del cuore.
HR_IMPOSSIBILE = 210

# Un salto di battito così in un secondo è un artefatto del sensore ottico.
SALTO_HR = 30

# Velocità istantanea oltre la quale è un salto del GPS, non una corsa:
# 8 m/s sono 2:05/km, fuori portata umana su distanze non brevissime.
VELOCITA_IMPOSSIBILE = 8.0

# Quanto può scostarsi il moltiplicatore del terreno prima di insospettire.
# Sotto 1 significa percorso in netta discesa: possibile, ma da guardare.
MOLTIPLICATORE_MIN, MOLTIPLICATORE_MAX = 0.90, 1.60


class Esito:
    """Raccoglie i risultati e li stampa con lo stesso linguaggio del resto."""

    def __init__(self):
        self.gravi = 0
        self.avvisi = 0

    def ok(self, testo, dettaglio=""):
        print(f"  ✓  {testo}")
        if dettaglio:
            print(f"     {dettaglio}")

    def avviso(self, testo, dettaglio=""):
        self.avvisi += 1
        print(f"  ⚠  {testo}")
        if dettaglio:
            print(f"     {dettaglio}")

    def grave(self, testo, dettaglio=""):
        self.gravi += 1
        print(f"  ✗  {testo}")
        if dettaglio:
            print(f"     {dettaglio}")

    def nota(self, testo):
        print(f"  ·  {testo}")


def titolo(testo):
    print()
    print("=" * 64)
    print(f"  {testo}")
    print("=" * 64)


# ============================================
# CARICAMENTO
# ============================================

def carica_archivio(solo_2026=True):
    """Le voci dell'archivio, ordinate per data."""
    voci = []
    for percorso in glob.glob(os.path.join("dati", "attivita", "*.json")):
        try:
            with open(percorso) as f:
                voce = json.load(f)
        except (json.JSONDecodeError, OSError) as errore:
            print(f"  ✗  '{percorso}' illeggibile: {errore}")
            continue
        det = voce.get("dettaglio") or {}
        if solo_2026 and det.get("start_date_local", "") < DAL_2026:
            continue
        voci.append(voce)
    return sorted(voci, key=lambda v: v["dettaglio"].get("start_date_local", ""))


def carica_csv():
    if not os.path.exists(strava_sync.OUTPUT_CSV):
        return None
    with open(strava_sync.OUTPUT_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def data_di(voce):
    return voce["dettaglio"].get("start_date_local", "")[:10]


def streams_di(id_corsa):
    percorso = os.path.join("dati", "streams", f"{id_corsa}.json")
    if not os.path.exists(percorso):
        return None
    try:
        with open(percorso) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ============================================
# PARTE 1 — COMPLETEZZA
# ============================================

def controlla_completezza(e, archivio, righe, solo_2026):
    titolo("1. COMPLETEZZA — c'è tutto quello che dovrebbe esserci?")

    if not archivio:
        e.grave("Archivio vuoto.")
        return

    e.nota(f"{len(archivio)} corse in archivio"
           f"{' (stagione 2026)' if solo_2026 else ' (tutte le stagioni)'}, "
           f"dal {data_di(archivio[0])} al {data_di(archivio[-1])}")

    # --- ogni corsa ha gli streams? ---
    senza = [v for v in archivio if streams_di(v["dettaglio"].get("id")) is None]
    if senza:
        e.avviso(f"{len(senza)} corse senza streams secondo per secondo",
                 ", ".join(data_di(v) for v in senza[:8]))
        e.nota("senza streams non si ricalcolano zone né passo corretto per il terreno")
    else:
        e.ok("Tutte le corse hanno gli streams")

    # --- ogni corsa ha le zone archiviate? ---
    senza_zone = [v for v in archivio
                  if not any(z.get("type") == "heartrate" for z in v.get("zone") or [])
                  and v["dettaglio"].get("average_heartrate")]
    if senza_zone:
        e.avviso(f"{len(senza_zone)} corse con cardio ma senza zone di Strava",
                 ", ".join(data_di(v) for v in senza_zone[:8]))
    else:
        e.ok("Ogni corsa con cardio ha le zone di Strava archiviate")

    # --- campi che servono al resto della pipeline ---
    obbligatori = ["id", "start_date_local", "distance", "moving_time", "type"]
    mancanti = []
    for v in archivio:
        assenti = [c for c in obbligatori if v["dettaglio"].get(c) in (None, "")]
        if assenti:
            mancanti.append(f"{data_di(v)}: {', '.join(assenti)}")
    if mancanti:
        e.grave(f"{len(mancanti)} corse con campi essenziali mancanti", "; ".join(mancanti[:5]))
    else:
        e.ok("Nessun campo essenziale mancante")

    # --- archivio e CSV dicono la stessa cosa? ---
    if righe is None:
        e.grave(f"'{strava_sync.OUTPUT_CSV}' non esiste")
    else:
        id_arch = {str(v["dettaglio"].get("id")) for v in archivio}
        id_csv = {r["id"] for r in righe if r["data"] >= DAL_2026} if solo_2026 \
            else {r["id"] for r in righe}
        solo_archivio = id_arch - id_csv
        solo_csv = id_csv - id_arch
        if solo_archivio:
            e.grave(f"{len(solo_archivio)} corse in archivio ma non nel CSV",
                    "ricostruisci con: python3 strava_sync.py --offline")
        if solo_csv:
            e.grave(f"{len(solo_csv)} corse nel CSV ma non in archivio", str(list(solo_csv)[:5]))
        if not solo_archivio and not solo_csv:
            e.ok(f"Archivio e CSV coincidono ({len(id_arch)} corse)")

    # --- doppioni: stessa data e stessa distanza ---
    firme = Counter((data_di(v), round(v["dettaglio"].get("distance", 0)))
                    for v in archivio)
    doppi = [f for f, n in firme.items() if n > 1]
    if doppi:
        e.avviso(f"{len(doppi)} possibili doppioni (stessa data e distanza)",
                 "; ".join(f"{d} · {m/1000:.2f} km" for d, m in doppi[:5]))
        e.nota("succede se due app caricano la stessa corsa su Strava")
    else:
        e.ok("Nessun doppione")

    # --- buchi nel calendario ---
    date = sorted({data_di(v) for v in archivio})
    if len(date) >= 2:
        buchi = []
        for prima, dopo in zip(date, date[1:]):
            giorni = (datetime.strptime(dopo, "%Y-%m-%d")
                      - datetime.strptime(prima, "%Y-%m-%d")).days
            if giorni > 10:
                buchi.append((prima, dopo, giorni))
        if buchi:
            e.nota(f"{len(buchi)} pause di oltre 10 giorni (informativo, non un errore):")
            for prima, dopo, giorni in buchi:
                print(f"       {prima} → {dopo}   {giorni} giorni")
        else:
            e.ok("Nessuna pausa superiore a 10 giorni")


def controlla_contro_strava(e, archivio):
    """Confronto con l'elenco vero su Strava: serve a scoprire le corse
    cancellate dall'app che l'archivio ha conservato, e viceversa."""
    titolo("1-bis. CONFRONTO CON STRAVA (richiede internet)")
    try:
        token = strava_sync.ottieni_token()
        remote = strava_sync.elenca_corse(token)
    except Exception as errore:                      # noqa: BLE001
        e.avviso(f"Confronto saltato: {type(errore).__name__}: {errore}")
        return

    # Un elenco vuoto NON è «zero corse su Strava»: è una chiamata fallita.
    # Senza questa guardia, col 403 dell'API il confronto concludeva che tutte
    # le corse in archivio erano state cancellate — un falso allarme peggiore
    # del controllo mancante.
    if not remote:
        e.avviso("L'elenco delle corse è tornato vuoto: confronto saltato",
                 "senza elenco non si distingue «cancellata» da «API muta»")
        return

    id_remoti = {str(c.get("id")) for c in remote}
    id_locali = {str(v["dettaglio"].get("id")) for v in archivio}

    mancanti = id_remoti - id_locali
    # Le corse remote non archiviate possono essere di stagioni escluse:
    # si guardano le date prima di gridare al buco.
    da_scaricare = [c for c in remote if str(c.get("id")) in mancanti
                    and c.get("start_date_local", "") >= DAL_2026
                    and c.get("type") in strava_sync.TIPI_CORSA]
    if da_scaricare:
        e.grave(f"{len(da_scaricare)} corse su Strava non ancora in archivio",
                "scaricale con: python3 strava_sync.py")
        for c in da_scaricare[:5]:
            print(f"       {c.get('start_date_local','')[:10]}  {c.get('name','')}")
    else:
        e.ok("Nessuna corsa su Strava manca all'archivio")

    solo_locali = id_locali - id_remoti
    if solo_locali:
        e.nota(f"{len(solo_locali)} corse in archivio non più su Strava "
               f"(cancellate dall'app: l'archivio le ha salvate)")
        for v in archivio:
            if str(v["dettaglio"].get("id")) in solo_locali:
                d = v["dettaglio"]
                print(f"       {data_di(v)}  {d.get('name','')}  "
                      f"{d.get('distance',0)/1000:.2f} km")


# ============================================
# PARTE 2 — ZONE CARDIACHE
# ============================================

def controlla_zone(e, archivio):
    titolo("2. ZONE CARDIACHE — il ripiego regge quando il premium scade?")

    # --- le soglie ---
    if os.path.exists(strava_sync.FILE_SOGLIE):
        with open(strava_sync.FILE_SOGLIE) as f:
            dati = json.load(f)
        soglie = dati.get("soglie") or []
        if len(soglie) != 5:
            e.grave(f"Le soglie archiviate non sono 5 ma {len(soglie)}: {soglie}")
        elif soglie != sorted(soglie) or soglie[0] != 0:
            e.grave(f"Soglie non crescenti o che non partono da 0: {soglie}")
        else:
            e.ok(f"Soglie vere di Strava archiviate: {soglie}",
                 f"dalla corsa del {dati.get('dalla_corsa_del','?')}")
    else:
        soglie = strava_sync.carica_soglie()
        e.avviso("Soglie vere non archiviate: si usano quelle stimate da HRmax",
                 f"{soglie} — meno precise, e dopo la scadenza non si recuperano")

    # --- confronto zona per zona ---
    confrontabili = []
    for v in archivio:
        cardio = next((z for z in v.get("zone") or []
                       if z.get("type") == "heartrate"), None)
        if not cardio:
            continue
        s = streams_di(v["dettaglio"].get("id"))
        if not s or not s.get("heartrate"):
            continue
        vere = [b.get("time", 0) for b in cardio.get("distribution_buckets", [])]
        mie = strava_sync.zone_da_streams(v["dettaglio"].get("id"), soglie,
                                          v["dettaglio"].get("moving_time"))
        if not mie or len(vere) != 5:
            continue
        confrontabili.append((data_di(v), vere, mie))

    if not confrontabili:
        e.avviso("Nessuna corsa permette il confronto fra zone vere e ricalcolate")
        return

    print()
    print(f"     {'data':11}{'Strava (min)':>26}{'ricalcolate':>26}{'scarto':>9}")
    scarti = []
    peggiori = []
    for data, vere, mie in confrontabili:
        tot_v, tot_m = sum(vere), sum(mie)
        scarto = abs(tot_v - tot_m)
        scarti.append(scarto)
        v_txt = " ".join(f"{x/60:4.0f}" for x in vere)
        m_txt = " ".join(f"{x/60:4.0f}" for x in mie)
        segno = " " if scarto <= SCARTO_ZONE_SEC else "⚠"
        print(f"     {data:11}{v_txt:>26}{m_txt:>26}{scarto:7.0f}s {segno}")
        if scarto > SCARTO_ZONE_SEC:
            peggiori.append((data, scarto))

    print()
    dentro = sum(1 for s in scarti if s <= SCARTO_ZONE_SEC)
    mediano = statistics.median(scarti)
    testo = (f"{dentro}/{len(scarti)} corse entro {SCARTO_ZONE_SEC}s · "
             f"scarto mediano {mediano:.0f}s · massimo {max(scarti):.0f}s")
    if dentro == len(scarti):
        e.ok("Il ricalcolo dagli streams riproduce le zone di Strava", testo)
    elif dentro >= len(scarti) * 0.8:
        e.avviso("Il ricalcolo regge, con qualche scarto", testo)
        for data, s in peggiori:
            print(f"       {data}: {s:.0f}s di scarto")
    else:
        e.grave("Il ricalcolo NON riproduce le zone di Strava", testo)

    # --- le zone sommano al tempo in movimento? ---
    incoerenti = []
    for v in archivio:
        cardio = next((z for z in v.get("zone") or []
                       if z.get("type") == "heartrate"), None)
        if not cardio:
            continue
        somma = sum(b.get("time", 0) for b in cardio.get("distribution_buckets", []))
        movimento = v["dettaglio"].get("moving_time") or 0
        if movimento and abs(somma - movimento) > movimento * 0.25:
            incoerenti.append((data_di(v), somma, movimento))
    if incoerenti:
        e.avviso(f"{len(incoerenti)} corse dove le zone non sommano al tempo in movimento",
                 "; ".join(f"{d}: zone {s//60}′ vs movimento {m//60}′"
                           for d, s, m in incoerenti[:5]))
        e.nota("normale quando il cardio parte tardi o si perde per un tratto")
    else:
        e.ok("Le zone sommano sempre al tempo in movimento (±25%)")


# ============================================
# PARTE 3 — COERENZA INTERNA
# ============================================

def controlla_coerenza(e, archivio, righe, solo_2026):
    titolo("3. COERENZA — i numeri del CSV tornano fra loro?")
    if not righe:
        e.grave("Nessun CSV da controllare")
        return

    if solo_2026:
        righe = [r for r in righe if r["data"] >= DAL_2026]

    def num(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    def passo_sec(testo):
        try:
            m, _, s = testo.partition(":")
            return int(m) * 60 + int(s)
        except (ValueError, AttributeError):
            return None

    problemi = []

    # --- il passo corrisponde a km e minuti? ---
    for r in righe:
        km, minuti = num(r["km"]), num(r["minuti"])
        atteso = passo_sec(r["passo"])
        if not km or not minuti or atteso is None:
            continue
        calcolato = minuti * 60 / km
        if abs(calcolato - atteso) > 12:        # 12s: l'arrotondamento dei minuti
            problemi.append(f"{r['data']}: passo {r['passo']} ma {km} km in "
                            f"{minuti}′ fanno {int(calcolato)//60}:{int(calcolato)%60:02d}")
    if problemi:
        e.grave(f"{len(problemi)} corse col passo incoerente", "; ".join(problemi[:4]))
    else:
        e.ok("Il passo corrisponde sempre a chilometri e minuti")

    # --- FC massima >= media ---
    male = [r["data"] for r in righe
            if r.get("bpm_max") and r.get("bpm_media") not in ("", "N/D")
            and num(r["bpm_max"]) < num(r["bpm_media"])]
    if male:
        e.grave(f"{len(male)} corse con FC massima sotto la media", ", ".join(male[:5]))
    else:
        e.ok("La FC massima non è mai sotto la media")

    # --- FC impossibili ---
    assurde = [(r["data"], r["bpm_max"]) for r in righe
               if r.get("bpm_max") and num(r["bpm_max"]) > HR_IMPOSSIBILE]
    if assurde:
        e.avviso(f"{len(assurde)} corse con FC massima oltre {HR_IMPOSSIBILE}",
                 "; ".join(f"{d}: {v}" for d, v in assurde))
    else:
        e.ok(f"Nessuna FC massima oltre {HR_IMPOSSIBILE} bpm")

    # --- i record sono monotoni? il passo sul 10 km non può battere l'1 km ---
    rotti = []
    for r in righe:
        t1, t5, t10 = (passo_sec(r.get(k) or "") for k in ("best_1k", "best_5k", "best_10k"))
        if t1 and t5 and t5 / 5 < t1 * 0.98:
            rotti.append(f"{r['data']}: 5 km più veloce al km dell'1 km")
        if t5 and t10 and t10 / 10 < t5 / 5 * 0.98:
            rotti.append(f"{r['data']}: 10 km più veloce al km del 5 km")
    if rotti:
        e.grave(f"{len(rotti)} incoerenze nei best effort", "; ".join(rotti[:4]))
    else:
        e.ok("I best effort sono coerenti fra le distanze")

    # --- un best effort più lungo della corsa stessa è impossibile ---
    impossibili = []
    for r in righe:
        km = num(r["km"])
        for chiave, distanza in (("best_5k", 5), ("best_10k", 10)):
            if r.get(chiave) and km < distanza - 0.05:
                impossibili.append(f"{r['data']}: {chiave} su {km} km")
    if impossibili:
        e.grave(f"{len(impossibili)} best effort più lunghi della corsa",
                "; ".join(impossibili[:4]))
    else:
        e.ok("Nessun best effort più lungo della corsa che lo contiene")

    # --- zone_fonte coerente con la presenza delle zone ---
    incoerenti = [r["data"] for r in righe
                  if (r.get("zone_fonte") or "") and not (r.get("z2_min") or "")]
    if incoerenti:
        e.grave(f"{len(incoerenti)} corse con fonte zone dichiarata ma zone vuote",
                ", ".join(incoerenti[:5]))
    else:
        e.ok("La colonna 'zone_fonte' è coerente con le zone")

    # --- il moltiplicatore del terreno è plausibile? ---
    strani = []
    for r in righe:
        km, equiv = num(r["km"]), num(r.get("km_equiv"))
        if not km or not equiv:
            continue
        molt = equiv / km
        if not MOLTIPLICATORE_MIN <= molt <= MOLTIPLICATORE_MAX:
            strani.append(f"{r['data']}: ×{molt:.3f} (D+ {r.get('dislivello')} m)")
    if strani:
        e.avviso(f"{len(strani)} moltiplicatori del terreno fuori dall'atteso",
                 "; ".join(strani[:4]))
    else:
        e.ok(f"Moltiplicatori del terreno tutti fra "
             f"×{MOLTIPLICATORE_MIN} e ×{MOLTIPLICATORE_MAX}")

    # --- il CSV si rigenera identico dall'archivio? ---
    with open(strava_sync.OUTPUT_CSV, encoding="utf-8") as f:
        prima = f.read()
    try:
        strava_sync.costruisci_csv()
        with open(strava_sync.OUTPUT_CSV, encoding="utf-8") as f:
            dopo = f.read()
        if prima == dopo:
            e.ok("Il CSV si rigenera identico dall'archivio (nessuna modifica a mano)")
        else:
            e.avviso("Il CSV rigenerato differisce da quello su disco",
                     "era stato modificato a mano, o l'archivio è cambiato dopo")
    except Exception as errore:                      # noqa: BLE001
        e.grave(f"Il CSV non si rigenera: {type(errore).__name__}: {errore}")


# ============================================
# PARTE 4 — QUALITÀ DEL SEGNALE
# ============================================

def controlla_segnale(e, archivio):
    titolo("4. QUALITÀ DEL SEGNALE — l'orologio ha registrato bene?")

    buchi_cardio, salti_hr, salti_gps, distanze = [], [], [], []
    senza_cardio = []

    for v in archivio:
        det = v["dettaglio"]
        data = data_di(v)
        if not det.get("average_heartrate"):
            senza_cardio.append(data)

        s = streams_di(det.get("id"))
        if not s:
            continue

        # distanza dichiarata contro distanza negli streams
        dist = s.get("distance")
        if dist:
            scarto = abs(dist[-1] - (det.get("distance") or 0))
            if scarto > 50:
                distanze.append(f"{data}: {scarto:.0f} m di differenza")

        # buchi nel cardio
        hr = s.get("heartrate")
        if hr:
            vuoti = sum(1 for x in hr if x is None or x == 0)
            if vuoti > len(hr) * 0.05:
                buchi_cardio.append(f"{data}: {vuoti/len(hr)*100:.0f}% senza battito")
            # salti impossibili del sensore ottico
            salti = sum(1 for a, b in zip(hr, hr[1:])
                        if a and b and abs(b - a) > SALTO_HR)
            if salti:
                salti_hr.append(f"{data}: {salti} salti oltre {SALTO_HR} bpm")

        # salti del GPS
        tempi = s.get("time")
        if dist and tempi:
            veloci = 0
            for i in range(1, min(len(dist), len(tempi))):
                dt = tempi[i] - tempi[i - 1]
                if dt > 0 and (dist[i] - dist[i - 1]) / dt > VELOCITA_IMPOSSIBILE:
                    veloci += 1
            if veloci:
                salti_gps.append(f"{data}: {veloci} istanti oltre "
                                 f"{VELOCITA_IMPOSSIBILE} m/s")

    # Ogni controllo porta la frase per quando trova qualcosa E quella per
    # quando non trova niente: costruirle a pezzi dalla stessa stringa dava
    # mostri come «Nessuna delle buchi nel cardio».
    for trovato, assente, elenco, livello in (
            ("corse con buchi nel cardio oltre il 5%",
             "Nessun buco significativo nel cardio", buchi_cardio, "avviso"),
            ("corse con salti del battito dal sensore ottico",
             "Nessun salto sospetto del battito", salti_hr, "nota"),
            ("corse con salti del GPS",
             "Nessun salto del GPS", salti_gps, "avviso"),
            ("corse dove la distanza degli streams non torna con quella dichiarata",
             "La distanza degli streams torna sempre con quella dichiarata",
             distanze, "avviso")):
        if not elenco:
            e.ok(assente)
        elif livello == "nota":
            e.nota(f"{len(elenco)} {trovato}: " + "; ".join(elenco[:3]))
        else:
            e.avviso(f"{len(elenco)} {trovato}", "; ".join(elenco[:4]))

    # Il cambio di orologio è una discontinuità nei dati, non un dettaglio:
    # sensori ottici diversi leggono il battito in modo diverso, e confrontare
    # a cavallo del passaggio porta a concludere cose sulla forma che sono
    # dello strumento.
    attrezzi = {}
    for v in archivio:
        nome = (v["dettaglio"].get("device_name") or "").strip()
        if nome:
            attrezzi.setdefault(nome, []).append(data_di(v))
    if len(attrezzi) > 1:
        e.avviso(f"{len(attrezzi)} orologi diversi nell'archivio: il cardio non è "
                 f"confrontabile a cavallo del passaggio")
        for nome, date_ in sorted(attrezzi.items(), key=lambda x: min(x[1])):
            print(f"     {nome}: {len(date_)} corse, dal {min(date_)} al {max(date_)}")
    elif attrezzi:
        e.ok(f"Un solo orologio in archivio ({next(iter(attrezzi))}): "
             f"il cardio è confrontabile su tutta la serie")

    if senza_cardio:
        e.nota(f"{len(senza_cardio)} corse senza cardio: {', '.join(senza_cardio)}")
        e.nota("per queste le zone non esistono e non si possono ricostruire")

    # Quanta distanza fantasma hanno aggiunto i salti, corsa per corsa. Conta
    # perché i record — e quindi le proiezioni di gara — si cercano sulla
    # traccia: 38 metri regalati dal GPS diventano un record che non esiste.
    import strava_piano
    fantasmi = []
    for v in archivio:
        s = streams_di(v["dettaglio"].get("id"))
        if not s or not s.get("distance") or not s.get("time"):
            continue
        _, tolti = strava_piano._distanza_ripulita(s["distance"], s["time"])
        if tolti > 10:
            fantasmi.append((data_di(v), tolti))
    if fantasmi:
        e.nota(f"{len(fantasmi)} corse con distanza fantasma dai salti "
               f"(già scontata nei record):")
        for data, m in sorted(fantasmi, key=lambda x: -x[1])[:6]:
            print(f"       {data}: {m:.0f} m")
    else:
        e.ok("Nessuna distanza fantasma dai salti del GPS")


# ============================================
# PARTE 5 — TENUTA DOPO LA SCADENZA
# ============================================

def controlla_tenuta(e, archivio):
    titolo("5. DOPO LA SCADENZA DEL PREMIUM — cosa resta")

    con_re = sum(1 for v in archivio
                 if v["dettaglio"].get("suffer_score") is not None)
    con_zone = sum(1 for v in archivio
                   if any(z.get("type") == "heartrate" for z in v.get("zone") or []))
    con_streams = sum(1 for v in archivio if streams_di(v["dettaglio"].get("id")))

    e.nota(f"sforzo relativo archiviato su {con_re}/{len(archivio)} corse "
           f"— dalla scadenza non arriva più, e non è ricostruibile")
    e.nota(f"zone di Strava archiviate su {con_zone}/{len(archivio)} corse "
           f"— dalla scadenza si ricalcolano dagli streams")
    e.nota(f"streams archiviati su {con_streams}/{len(archivio)} corse "
           f"— restano gratuiti, sono la base di tutto")

    if os.path.exists(strava_sync.FILE_SOGLIE):
        e.ok("Le soglie vere sono su disco: il ricalcolo delle zone resta ancorato")
    else:
        e.grave("Soglie vere NON archiviate",
                "lancia 'python3 strava_sync.py --offline' finché il premium è attivo")

    mancano = [data_di(v) for v in archivio
               if not streams_di(v["dettaglio"].get("id"))]
    if mancano:
        e.avviso(f"{len(mancano)} corse senza streams: per queste, dopo la "
                 f"scadenza, non ci sarà modo di avere le zone",
                 ", ".join(mancano[:8]))
    else:
        e.ok("Ogni corsa ha gli streams: nessuna dipendenza residua dal premium")


# ============================================
# MAIN
# ============================================

def main():
    solo_2026 = "--tutto" not in sys.argv
    online = "--online" in sys.argv

    print()
    print("─" * 64)
    print("   CHECKUP DELL'ARCHIVIO STRAVA")
    print("─" * 64)

    e = Esito()
    archivio = carica_archivio(solo_2026)
    righe = carica_csv()

    controlla_completezza(e, archivio, righe, solo_2026)
    if online:
        controlla_contro_strava(e, archivio)
    else:
        print()
        print("  (con --online si confronta anche con l'elenco vero su Strava)")
    controlla_zone(e, archivio)
    controlla_coerenza(e, archivio, righe, solo_2026)
    controlla_segnale(e, archivio)
    controlla_tenuta(e, archivio)

    titolo("VERDETTO")
    if e.gravi:
        print(f"  ✗  {e.gravi} problemi gravi, {e.avvisi} avvisi.")
    elif e.avvisi:
        print(f"  ⚠  Nessun problema grave. {e.avvisi} avvisi da guardare.")
    else:
        print("  ✓  Tutto in ordine: nessun problema, nessun avviso.")
    print()
    return 1 if e.gravi else 0


if __name__ == "__main__":
    sys.exit(main())
