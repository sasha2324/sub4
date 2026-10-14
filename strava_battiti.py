# ============================================
# STRAVA — ANALISI DEI BATTITI
# ============================================
# Il CSV delle corse contiene solo la frequenza cardiaca media.
# I file GPX dentro l'archivio Strava contengono invece il battito
# secondo per secondo: qui li leggiamo per capire come è distribuito
# lo sforzo dentro ogni corsa, non solo la media.
#
# Calcola: tempo di corsa vs cammino, passo della sola corsa,
# zone cardiache, deriva cardiaca, efficienza (metri per battito).
#
# Uso:  python3 strava_battiti.py export_XXXXXX.zip
# ============================================

import csv
import io
import math
import os
import statistics
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import timedelta

# Stesso filtro anti-artefatto usato quando si aggiunge una corsa:
# senza, un avvio sballato del cardio falsa massimi e medie.
from strava_aggiungi_gpx import ripulisci_battiti
import impostazioni

FILE_CSV = "strava_corse.csv"

# Analizza solo dalla ripresa in poi. Con --tutto si include l'archivio.
DAL = "2026-01-01"

# Frequenza cardiaca massima di riferimento per le zone (dato personale: nel .env).
# Senza un test sotto sforzo si stima con le formule, per esempio Tanaka
# (208 - 0,7 x età) o 220 meno l'età, e si prende una via di mezzo.
# La più alta mai registrata di solito è più bassa del vero, perché in
# allenamento non ci si spinge fino in fondo.
HR_MASSIMA = int(impostazioni.leggi("HR_MASSIMA", "190"))

# Fuso orario locale rispetto all'UTC dei file GPX (Italia d'estate: +2)
FUSO_ORARIO = 2

# Soglie di velocità in m/s per distinguere fermo / cammino / corsa
FERMO, CAMMINA = 0.7, 1.8

NS = {"g": "http://www.topografix.com/GPX/1/1",
      "x": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"}

# ============================================
# LETTURA GPX
# ============================================

def leggi_gpx(dati):
    """Estrae i punti traccia: posizione, orario e battito."""
    radice = ET.parse(io.BytesIO(dati)).getroot()
    punti = []
    for p in radice.iterfind(".//g:trkpt", NS):
        orario = p.findtext("g:time", namespaces=NS)
        battito = p.findtext(".//x:hr", namespaces=NS)
        if not orario:
            continue
        punti.append({
            "lat": float(p.get("lat")),
            "lon": float(p.get("lon")),
            "t":   _data(orario),
            "hr":  int(battito) if battito else None,
        })
    return punti

def _data(testo):
    from datetime import datetime
    for formato in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(testo, formato)
        except ValueError:
            continue
    return None

def distanza(a, b):
    """Distanza in metri fra due coordinate (formula dell'emisenoverso)."""
    R = 6371000
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def liscia(valori, finestra=10):
    """
    Media mobile sulla velocità: il GPS è rumoroso e senza questo
    passaggio ogni sobbalzo sembrerebbe una partenza o una sosta.
    """
    lisci = []
    for i in range(len(valori)):
        a = max(0, i - finestra//2)
        b = min(len(valori), i + finestra//2 + 1)
        lisci.append(sum(valori[a:b]) / (b - a))
    return lisci

# ============================================
# ANALISI DI UNA CORSA
# ============================================

def analizza(punti, km_ufficiali, hr_massima):
    """
    Divide la corsa in fermo / cammino / corsa e calcola le statistiche
    sulla sola parte corsa. Le distanze GPS vengono riscalate su quella
    ufficiale di Strava: sommare punto per punto gonfia il totale di
    qualche punto percentuale, e falserebbe il passo.
    """
    battiti_presenti = [p["hr"] for p in punti if p["hr"]]
    if not battiti_presenti or len(punti) < 2:
        return None

    km_grezzi = sum(distanza(a, b) for a, b in zip(punti, punti[1:])) / 1000
    if km_grezzi <= 0:
        return None
    scala = km_ufficiali / km_grezzi

    passi, tempi, velocita = [], [], []
    for a, b in zip(punti, punti[1:]):
        d = distanza(a, b) * scala
        t = (b["t"] - a["t"]).total_seconds() or 1
        passi.append(d); tempi.append(t); velocita.append(d / t)

    t_corsa = t_cammino = t_fermo = 0.0
    metri_corsa = battiti_totali = 0.0
    hr_corsa, serie = [], []

    for i, v in enumerate(liscia(velocita)):
        if v < FERMO:
            t_fermo += tempi[i]
        elif v < CAMMINA:
            t_cammino += tempi[i]
        else:
            t_corsa += tempi[i]
            metri_corsa += passi[i]
            if punti[i]["hr"]:
                hr_corsa.append(punti[i]["hr"])
                battiti_totali += punti[i]["hr"] * tempi[i] / 60
                serie.append((t_corsa, punti[i]["hr"]))

    if metri_corsa < 500 or not hr_corsa:
        return None

    # Deriva cardiaca: quanto sale il battito fra prima e seconda metà
    meta = t_corsa / 2
    prima = [hr for t, hr in serie if t <= meta]
    dopo  = [hr for t, hr in serie if t > meta]
    deriva = statistics.mean(dopo) - statistics.mean(prima) if prima and dopo else 0

    zone = {z: 0.0 for z in range(1, 6)}
    for i, p in enumerate(punti[:-1]):
        if p["hr"]:
            zone[zona(p["hr"], hr_massima)] += tempi[i]

    return {
        "totale":    (punti[-1]["t"] - punti[0]["t"]).total_seconds(),
        "t_corsa":   t_corsa,
        "t_cammino": t_cammino,
        "t_fermo":   t_fermo,
        "passo":     t_corsa / (metri_corsa / 1000),
        "hr_media":  statistics.mean(hr_corsa),
        "hr_max":    max(hr_corsa),
        "deriva":    deriva,
        "efficienza": metri_corsa / battiti_totali,
        "zone":      zone,
        "ora":       (punti[0]["t"] + timedelta(hours=FUSO_ORARIO)).strftime("%H:%M"),
    }

def carica_ufficiali(dal=None):
    """
    data → elenco di (km, nome). È un elenco e non un valore singolo
    perché in una giornata può esserci più di una corsa: indicizzare
    per sola data farebbe sparire il doppio, e riscalerebbe una traccia
    sui chilometri dell'altra.
    """
    per_data = {}
    with open(FILE_CSV, encoding="utf-8") as f:
        for riga in csv.DictReader(f):
            if dal and riga["data"] < dal:
                continue
            per_data.setdefault(riga["data"], []).append(
                (float(riga["km"]), riga["nome"]))
    return per_data

def abbina(candidati, km_stimati):
    """Fra le corse dello stesso giorno sceglie quella di lunghezza più simile."""
    return min(candidati, key=lambda c: abs(c[0] - km_stimati))

def km_stimati(punti):
    """Distanza approssimativa della traccia, solo per l'abbinamento."""
    campione = punti[::5] + [punti[-1]]
    return sum(distanza(a, b) for a, b in zip(campione, campione[1:])) / 1000 * 0.977

def zona(battito, hr_massima):
    """Zone classiche in percentuale della frequenza massima."""
    quota = battito / hr_massima
    if quota < 0.60: return 1
    if quota < 0.70: return 2
    if quota < 0.80: return 3
    if quota < 0.90: return 4
    return 5

NOMI_ZONE = {1: "recupero", 2: "facile", 3: "medio",
             4: "soglia", 5: "massimale"}

def passo_leggibile(secondi):
    return f"{int(secondi)//60}:{int(secondi)%60:02d}"

# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("   STRAVA — ANALISI DEI BATTITI")
    print("=" * 60)

    if len(sys.argv) < 2:
        print("\nUso:  python3 strava_battiti.py <export.zip oppure corsa.gpx ...>\n")
        exit(1)

    if not os.path.exists(FILE_CSV):
        print(f"✗ Manca '{FILE_CSV}': esegui prima strava_import_export.py")
        exit(1)

    dal = None if "--tutto" in sys.argv else DAL

    ufficiali = carica_ufficiali(dal)

    if dal:
        print(f"  Solo corse dal {dal} in poi (--tutto per includere l'archivio)")

    # Accetta sia l'archivio completo sia singoli GPX scaricati
    # dalla pagina di una attività
    tracce = []
    for percorso in [a for a in sys.argv[1:] if not a.startswith("--")]:
        if percorso.lower().endswith(".zip"):
            archivio = zipfile.ZipFile(percorso)
            for nome in sorted(n for n in archivio.namelist() if n.endswith(".gpx")):
                tracce.append(archivio.read(nome))
        elif percorso.lower().endswith(".gpx"):
            with open(percorso, "rb") as f:
                tracce.append(f.read())

    if not tracce:
        print("✗ Nessuna traccia GPX da leggere.")
        exit(1)
    print(f"✓ {len(tracce)} tracce GPX da analizzare.\n")

    corse = []
    anomale = 0
    for dati in tracce:
        punti = leggi_gpx(dati)
        if not punti or not punti[0]["t"]:
            continue
        anomale += ripulisci_battiti(punti)
        data = str(punti[0]["t"].date())
        if data in ufficiali:
            km, nome = abbina(ufficiali[data], km_stimati(punti))
            corse.append((data, nome, km, punti))

    if anomale:
        print(f"  {anomale} letture anomale del cardio scartate\n")

    registrata = max((p["hr"] for *_, punti in corse for p in punti if p["hr"]),
                     default=0)
    if not registrata:
        print("✗ Nessun dato di frequenza cardiaca nelle tracce.")
        exit(1)

    hr_massima = HR_MASSIMA or registrata
    print(f"  Frequenza massima di riferimento: {hr_massima} bpm (stimata)")
    print(f"  Più alta effettivamente registrata: {registrata} bpm\n")

    intestazione = (f"{'data':<11} {'ora':>6} {'km':>6} {'totale':>7} {'corsa':>6} "
                    f"{'cammino':>8} {'passo':>7} {'HR':>4} {'max':>4} "
                    f"{'deriva':>7} {'m/batt':>7}")
    print(intestazione)
    print("-" * len(intestazione))

    risultati = []
    for data, nome, km, punti in sorted(corse, key=lambda c: (c[0], c[1])):
        r = analizza(punti, km, hr_massima)
        if not r:
            continue
        risultati.append((data, r))
        print(f"{data:<11} {r['ora']:>6} {km:>6.2f} "
              f"{r['totale']/60:>6.0f}' {r['t_corsa']/60:>5.0f}' "
              f"{r['t_cammino']/60:>7.1f}' {passo_leggibile(r['passo']):>7} "
              f"{r['hr_media']:>4.0f} {r['hr_max']:>4} "
              f"{r['deriva']:>+6.1f} {r['efficienza']:>7.2f}")

    if not risultati:
        print("\n✗ Nessuna corsa con battiti utilizzabile.")
        exit(1)

    print("\nZONE CARDIACHE (% del tempo)")
    for data, r in risultati:
        totale = sum(r["zone"].values()) or 1
        barre = "  ".join(f"Z{z} {100*r['zone'][z]/totale:>3.0f}%"
                          for z in range(1, 6))
        print(f"  {data}   {barre}")

    print("\nMEDIE PER ANNO (sulla sola parte corsa)")
    anni = sorted({d[:4] for d, _ in risultati})
    for anno in anni:
        sel = [r for d, r in risultati if d.startswith(anno)]
        movimento = sum(r["t_corsa"] + r["t_cammino"] for r in sel)
        print(f"  {anno}:  {len(sel)} corse  |  "
              f"passo {passo_leggibile(statistics.mean([r['passo'] for r in sel]))}/km  |  "
              f"HR {statistics.mean([r['hr_media'] for r in sel]):.0f}  |  "
              f"efficienza {statistics.mean([r['efficienza'] for r in sel]):.2f} m/battito  |  "
              f"deriva {statistics.mean([r['deriva'] for r in sel]):+.1f} bpm  |  "
              f"cammino {100*sum(r['t_cammino'] for r in sel)/movimento:.0f}%")
    print()
