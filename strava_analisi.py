# ============================================
# STRAVA — ANALISI AVANZATE
# ============================================
# Legge il file strava_corse.csv prodotto da
# strava_tracker.py e produce analisi avanzate.
#
# Esegui: python3 strava_analisi.py
# ============================================

import csv
import sys
from datetime import datetime, timedelta
from collections import defaultdict

FILE_CSV = "strava_corse.csv"

# Analizza solo dalla ripresa in poi: il 2025 resta nel CSV come
# archivio, ma non fa parte dei confronti.
# Per vedere tutto:        python3 strava_analisi.py --tutto
# Per un'altra data:       python3 strava_analisi.py --dal 2026-07-01
DAL = "2026-01-01"

# ============================================
# CARICAMENTO DATI
# ============================================

def leggi_argomenti():
    """Restituisce la data minima da considerare (None = tutte)."""
    if "--tutto" in sys.argv:
        return None
    if "--dal" in sys.argv:
        i = sys.argv.index("--dal")
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return DAL

def carica_corse(nome_file, dal=None):
    """Legge il CSV e restituisce lista di dizionari."""
    corse = []
    scartate = 0
    try:
        with open(nome_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for riga in reader:
                if dal and riga["data"] < dal:
                    scartate += 1
                    continue
                try:
                    corse.append({
                        "data":       riga["data"],
                        "nome":       riga["nome"],
                        "km":         float(riga["km"]),
                        "minuti":     int(riga["minuti"]),
                        "passo":      riga["passo"],
                        "dislivello": int(riga.get("dislivello", 0) or 0),
                        "bpm":        riga.get("bpm_media", "N/D"),
                        "data_dt":    datetime.strptime(riga["data"], "%Y-%m-%d"),
                    })
                except:
                    continue
    except FileNotFoundError:
        print(f"✗ File '{nome_file}' non trovato.")
        print("  Esegui prima strava_tracker.py per scaricare le corse.")
        exit()

    if not corse:
        print(f"✗ Nessuna corsa dal {dal} in poi.")
        print("  Usa --tutto per includere anche l'archivio.")
        exit()

    corse.sort(key=lambda x: x["data_dt"])
    print(f"✓ Caricate {len(corse)} corse da '{nome_file}'.")
    if scartate:
        print(f"  ({scartate} corse prima del {dal} escluse — archivio)")
    print()
    return corse

# ============================================
# FUNZIONI DI ANALISI
# ============================================

def pace_in_secondi(pace_str):
    """Converte '5:30' in 330 secondi."""
    try:
        parti = pace_str.split(":")
        return int(parti[0]) * 60 + int(parti[1])
    except:
        return None

def secondi_in_pace(secondi):
    """Converte 330 secondi in '5:30'."""
    return f"{secondi // 60}:{secondi % 60:02d}"

def record_personali(corse):
    """Trova i record per distanza: 5k, 10k, mezza, maratona."""
    distanze = {
        "5 km":        (4.5,  5.5),
        "10 km":       (9.0,  11.0),
        "Mezza (21k)": (19.0, 23.0),
        "Maratona":    (40.0, 45.0),
    }

    records = {}
    for label, (minimo, massimo) in distanze.items():
        candidate = [
            c for c in corse
            if minimo <= c["km"] <= massimo
        ]
        if candidate:
            # Record = corsa con passo più veloce
            migliore = min(
                candidate,
                key=lambda c: c["minuti"] / c["km"]
            )
            pace_sec = migliore["minuti"] * 60 / migliore["km"]
            records[label] = {
                "data":   migliore["data"],
                "km":     migliore["km"],
                "minuti": migliore["minuti"],
                "passo":  secondi_in_pace(int(pace_sec)),
            }
    return records

def progressione_mensile(corse):
    """Raggruppa km e numero uscite per mese."""
    mesi = defaultdict(lambda: {"km": 0, "uscite": 0, "minuti": 0})
    for c in corse:
        mese = c["data"][:7]
        mesi[mese]["km"]     += c["km"]
        mesi[mese]["uscite"] += 1
        mesi[mese]["minuti"] += c["minuti"]
    return dict(sorted(mesi.items()))

def progressione_passo(corse):
    """Calcola il passo medio per ogni mese — mostra se stai migliorando."""
    mesi = defaultdict(list)
    for c in corse:
        mese = c["data"][:7]
        pace_sec = c["minuti"] * 60 / c["km"] if c["km"] > 0 else None
        if pace_sec:
            mesi[mese].append(pace_sec)

    risultato = {}
    for mese, passi in sorted(mesi.items()):
        risultato[mese] = sum(passi) / len(passi)
    return risultato

def consistenza_settimanale(corse):
    """Conta quante settimane hai corso almeno X volte."""
    settimane = defaultdict(int)
    for c in corse:
        dt = c["data_dt"]
        # Lunedì della settimana
        lunedi = dt - timedelta(days=dt.weekday())
        settimane[lunedi.strftime("%Y-%m-%d")] += 1
    return dict(sorted(settimane.items()))

def striscia_corrente(corse):
    """Calcola quante settimane consecutive hai corso."""
    if not corse:
        return 0

    settimane = set()
    for c in corse:
        dt = c["data_dt"]
        lunedi = dt - timedelta(days=dt.weekday())
        settimane.add(lunedi)

    settimane_ordinate = sorted(settimane, reverse=True)
    striscia = 1
    for i in range(1, len(settimane_ordinate)):
        diff = (settimane_ordinate[i-1] - settimane_ordinate[i]).days
        if diff == 7:
            striscia += 1
        else:
            break
    return striscia

def barra(valore, massimo, larghezza=16):
    if massimo == 0:
        return "░" * larghezza
    n = min(int((valore / massimo) * larghezza), larghezza)
    return "█" * n + "░" * (larghezza - n)

def sep(n=52):
    print("─" * n)

# ============================================
# STAMPA RISULTATI
# ============================================

def stampa_analisi(corse):
    print("=" * 52)
    print("   ANALISI AVANZATE STRAVA")
    print("=" * 52)

    # ── STATISTICHE GENERALI ──────────────────────
    km_tot   = sum(c["km"] for c in corse)
    min_tot  = sum(c["minuti"] for c in corse)
    ore      = min_tot // 60
    min_ext  = min_tot % 60
    pace_med = min_tot * 60 / km_tot if km_tot > 0 else 0

    sep()
    print("STATISTICHE GENERALI")
    sep()
    print(f"  Corse totali:        {len(corse)}")
    print(f"  Km totali:           {km_tot:.1f} km")
    print(f"  Tempo totale:        {ore}h {min_ext}min")
    print(f"  Media km per uscita: {km_tot/len(corse):.1f} km")
    print(f"  Passo medio:         {secondi_in_pace(int(pace_med))} min/km")
    print(f"  Uscita più lunga:    {max(c['km'] for c in corse):.1f} km")
    print(f"  Striscia attuale:    {striscia_corrente(corse)} settimane consecutive")

    # ── RECORD PERSONALI ──────────────────────────
    sep()
    print("RECORD PERSONALI")
    sep()
    records = record_personali(corse)
    if records:
        for distanza, r in records.items():
            print(f"  {distanza:<14}  {r['passo']}/km  ({r['km']:.1f}km il {r['data']})")
    else:
        print("  Nessun record trovato per le distanze standard.")

    # ── PROGRESSIONE MENSILE ──────────────────────
    sep()
    print("KM MENSILI")
    sep()
    mesi = progressione_mensile(corse)
    max_km = max(v["km"] for v in mesi.values()) if mesi else 1
    for mese, dati in mesi.items():
        b = barra(dati["km"], max_km)
        print(f"  {mese}  {b}  {dati['km']:>5.1f} km  ({dati['uscite']} uscite)")

    # ── PROGRESSIONE PASSO ────────────────────────
    sep()
    print("PROGRESSIONE PASSO (stai migliorando?)")
    sep()
    passi = progressione_passo(corse)
    passi_valori = list(passi.values())
    for i, (mese, pace_sec) in enumerate(passi.items()):
        pace_str = secondi_in_pace(int(pace_sec))
        if i == 0:
            trend = "  "
        elif pace_sec < passi_valori[i-1]:
            trend = "↑ "   # più veloce
        else:
            trend = "↓ "   # più lento
        print(f"  {mese}  {trend} {pace_str} min/km")

    print("\n  (↑ = più veloce  ↓ = più lento)")

    # ── CONSISTENZA SETTIMANALE ───────────────────
    sep()
    print("CONSISTENZA SETTIMANALE")
    sep()
    settimane = consistenza_settimanale(corse)
    tot_settimane  = len(settimane)
    sett_con_corsa = sum(1 for v in settimane.values() if v >= 1)
    sett_doppia    = sum(1 for v in settimane.values() if v >= 2)
    perc = (sett_con_corsa / tot_settimane * 100) if tot_settimane else 0

    print(f"  Settimane tracciate:     {tot_settimane}")
    print(f"  Settimane con almeno 1 corsa: {sett_con_corsa} ({perc:.0f}%)")
    print(f"  Settimane con 2+ corse:  {sett_doppia}")

    # Ultime 8 settimane
    print(f"\n  Ultime settimane:")
    ultime = list(settimane.items())[-8:]
    for sett, n in ultime:
        quadrati = "■" * n + "□" * max(0, 4 - n)
        print(f"    {sett}  {quadrati}  ({n} uscite)")

    print("=" * 52)

# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

if __name__ == "__main__":
    corse = carica_corse(FILE_CSV, dal=leggi_argomenti())
    stampa_analisi(corse)
