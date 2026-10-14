# ============================================
# STRAVA — I TUOI RECORD
# ============================================
# Migliori parziali su ogni distanza, calcolati con una finestra
# scorrevole sulla traccia GPS e solo dentro i tratti corsi senza
# fermarsi: un "miglior 2 km" che comprendesse due minuti fermo
# a bere non vorrebbe dire niente.
#
# Uso:
#   python3 strava_record.py export.zip corsa.gpx ...
#   python3 strava_record.py *.gpx --tutto     (include l'archivio 2025)
# ============================================

import csv
import math
import os
import statistics
import sys
import zipfile

from strava_battiti import (DAL, leggi_gpx, distanza, passo_leggibile,
                            carica_ufficiali, abbina, km_stimati)
from strava_aggiungi_gpx import ripulisci_battiti

FILE_CSV = "strava_corse.csv"

# Le distanze per cui teniamo un record
DISTANZE = [400, 1000, 1609, 2000, 3000, 5000, 10000]
NOMI = {400: "400 m", 1000: "1 km", 1609: "1 miglio", 2000: "2 km",
        3000: "3 km", 5000: "5 km", 10000: "10 km"}

# Un buco di oltre 20 s nella registrazione = orologio in pausa
BUCO_PAUSA = 20

# Correzione del gonfiaggio GPS, come in strava_aggiungi_gpx.py
PASSO_CAMPIONE = 5
CORREZIONE = 0.977

# ============================================

def metri_grezzi(punti):
    """
    Somma punto per punto. Gonfia di circa il 4% per il rumore del GPS,
    ma è LA STESSA somma usata dalla finestra scorrevole: normalizzando
    questa sulla distanza ufficiale, i parziali restano coerenti.
    (Usare qui un metodo diverso da quello dell'accumulo produce record
    più veloci del vero: è un errore che ho già fatto.)
    """
    return sum(distanza(a, b) for a, b in zip(punti, punti[1:]))

def spezza_in_tratti(punti):
    """Divide la traccia nei pezzi corsi senza fermarsi."""
    tagli = [i for i in range(len(punti)-1)
             if (punti[i+1]["t"] - punti[i]["t"]).total_seconds() > BUCO_PAUSA]
    bordi = [-1] + tagli + [len(punti)-1]
    return [punti[a+1:b+1] for a, b in zip(bordi, bordi[1:]) if b-a > 30]

def cerca_record(tratto, scala, record, data, nome):
    """Finestra scorrevole: il tempo minimo per coprire ogni distanza."""
    cumulate, tempi = [0.0], [0.0]
    t0 = tratto[0]["t"]
    for a, b in zip(tratto, tratto[1:]):
        cumulate.append(cumulate[-1] + distanza(a, b)*scala)
        tempi.append((b["t"] - t0).total_seconds())

    for D in DISTANZE:
        if cumulate[-1] < D:
            continue
        j = 0
        for i in range(len(cumulate)):
            while j < len(cumulate) and cumulate[j] - cumulate[i] < D:
                j += 1
            if j >= len(cumulate):
                break
            durata = tempi[j] - tempi[i]
            if record[D] is None or durata < record[D]["secondi"]:
                battiti = [p["hr"] for p in tratto[i:j+1] if p["hr"]]
                record[D] = {
                    "secondi": durata, "data": data, "nome": nome,
                    "hr": round(statistics.mean(battiti)) if battiti else None,
                }

def tempo_leggibile(secondi):
    minuti = int(secondi // 60)
    if minuti >= 60:
        return f"{minuti//60}h{minuti%60:02d}:{int(secondi%60):02d}"
    return f"{minuti}:{int(secondi % 60):02d}"

# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("   STRAVA — I TUOI RECORD")
    print("=" * 60)

    percorsi = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not percorsi:
        print("\nUso:  python3 strava_record.py <export.zip oppure corsa.gpx ...>\n")
        exit(1)

    dal = None if "--tutto" in sys.argv else DAL

    if not os.path.exists(FILE_CSV):
        print(f"✗ Manca '{FILE_CSV}'.")
        exit(1)

    ufficiali = carica_ufficiali(dal)

    tracce = []
    for percorso in percorsi:
        if percorso.lower().endswith(".zip"):
            z = zipfile.ZipFile(percorso)
            for n in sorted(x for x in z.namelist() if x.endswith(".gpx")):
                tracce.append(z.read(n))
        elif percorso.lower().endswith(".gpx"):
            with open(percorso, "rb") as f:
                tracce.append(f.read())

    record = {D: None for D in DISTANZE}
    continuo = {"km": 0.0, "minuti": 0.0, "data": None}
    analizzate = 0

    for dati in tracce:
        punti = leggi_gpx(dati)
        if not punti or not punti[0]["t"]:
            continue
        ripulisci_battiti(punti)
        data = str(punti[0]["t"].date())
        if data not in ufficiali:
            continue
        analizzate += 1

        # con due corse nello stesso giorno, prende quella giusta
        km_ufficiali, nome_corsa = abbina(ufficiali[data], km_stimati(punti))

        # riscala la traccia sulla distanza ufficiale di Strava
        grezzi = metri_grezzi(punti)
        scala = (km_ufficiali*1000 / grezzi) if grezzi else 1

        for tratto in spezza_in_tratti(punti):
            cerca_record(tratto, scala, record, data, nome_corsa)
            km = metri_grezzi(tratto)*scala/1000
            if km > continuo["km"]:
                continuo.update({
                    "km": km, "data": data,
                    "minuti": (tratto[-1]["t"]-tratto[0]["t"]).total_seconds()/60,
                })

    if not analizzate:
        print("\n✗ Nessuna traccia utilizzabile.")
        exit(1)

    print(f"✓ {analizzate} corse analizzate"
          + (f", dal {dal} in poi" if dal else "") + ".")
    print("  Ricavati dalla traccia GPS: rispetto ai numeri di Strava,")
    print("  che usano anche i sensori dell'orologio, aspettati ±10 secondi.\n")

    print(f"{'distanza':>10} {'tempo':>9} {'passo':>9} {'HR':>5}   quando")
    print("-" * 60)
    for D in DISTANZE:
        r = record[D]
        if r:
            print(f"{NOMI[D]:>10} {tempo_leggibile(r['secondi']):>9} "
                  f"{passo_leggibile(r['secondi']/(D/1000)):>8}  "
                  f"{(r['hr'] or '—'):>5}   {r['data']}  {r['nome']}")
        else:
            print(f"{NOMI[D]:>10} {'—':>9} {'—':>9} {'—':>5}   "
                  f"mai corsi {D/1000:g} km di fila")

    print()
    print(f"  Tratto più lungo senza fermarsi: "
          f"{continuo['km']:.2f} km in {continuo['minuti']:.1f} min "
          f"({continuo['data']})")
    print()
