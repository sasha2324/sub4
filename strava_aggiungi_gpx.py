# ============================================
# STRAVA — AGGIUNGI UNA CORSA DA UN GPX
# ============================================
# Per aggiornare dopo una singola corsa, senza richiedere
# tutto l'archivio (che ci mette ore).
#
# Su Strava: apri l'attività → menu "..." → Esporta GPX
#
# Uso:
#   python3 strava_aggiungi_gpx.py corsa.gpx
#   python3 strava_aggiungi_gpx.py corsa.gpx --km 6.12 --minuti 38
#
# Senza --km la distanza viene stimata dalla traccia GPS. Con le corse
# registrate dall'orologio l'errore resta entro il 2%; con quelle
# registrate dal telefono la stima è più incerta. Se hai i numeri
# ufficiali sotto gli occhi nell'app, passali: diventa esatto.
# ============================================

import csv
import math
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime

FILE_CSV = "strava_corse.csv"
CAMPI = ["data", "nome", "km", "minuti", "passo", "dislivello", "bpm_media"]

NS = {"g": "http://www.topografix.com/GPX/1/1",
      "x": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"}

# La correzione dipende da CHI ha registrato, e ignorarlo costa centinaia
# di metri.
#
# Registrazione dall'orologio: Strava riceve la distanza calcolata dal
# watch, che fonde GPS e accelerometro ed è più corta della somma grezza
# dei punti di circa il 4%. Lì campionare ogni 5 s e moltiplicare per
# 0,977 azzecca la distanza entro il 2% (misurato su 13 corse).
#
# Registrazione dal telefono: quel flusso non esiste e la distanza
# ufficiale coincide in pratica con la traccia. Applicare la stessa
# correzione la accorcia di 300 metri e rende tutti i parziali più lenti
# del vero.
#
# Distinguiamo dalla presenza del battito: se c'è, ha registrato
# l'orologio. Non è infallibile — un orologio col cardio spento ricadrebbe
# nel caso sbagliato — quindi lo script dice sempre quale ipotesi ha usato,
# e con --km non tira a indovinare affatto.
PASSO_CAMPIONE = 5
CORREZIONE = 0.977

# Un buco di oltre 20 s significa che l'orologio era in pausa: quel
# tempo non è tempo di corsa.
BUCO_PAUSA = 20

# ============================================
# LETTURA
# ============================================

def leggi_gpx(percorso):
    if not os.path.exists(percorso):
        print(f"✗ File '{percorso}' non trovato.")
        exit(1)

    radice = ET.parse(percorso).getroot()
    nome = radice.findtext(".//g:trk/g:name", default="", namespaces=NS)

    punti = []
    for p in radice.iterfind(".//g:trkpt", NS):
        orario = p.findtext("g:time", namespaces=NS)
        if not orario:
            continue
        battito = p.findtext(".//x:hr", namespaces=NS)
        quota = p.findtext("g:ele", namespaces=NS)
        punti.append({
            "lat": float(p.get("lat")),
            "lon": float(p.get("lon")),
            "t":   _orario(orario),
            "hr":  int(battito) if battito else None,
            "ele": float(quota) if quota else None,
        })

    punti = [p for p in punti if p["t"]]
    if len(punti) < 10:
        print("✗ La traccia è vuota o troppo corta.")
        exit(1)
    return nome.strip() or "Corsa", punti

def _orario(testo):
    for formato in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(testo, formato)
        except ValueError:
            continue
    return None

def mediana(valori):
    ordinati = sorted(valori)
    return ordinati[len(ordinati)//2]

def ripulisci_battiti(punti, scarto=25):
    """
    Toglie le letture impossibili del cardio ottico.

    Il caso tipico è l'avvio: finché l'orologio non aggancia il polso
    ripete un valore fisso — 190 per trentacinque secondi, poi 111 —
    e un cuore non scende di ottanta battiti in quattordici secondi.
    Non è una lettura isolata ma un blocco intero, quindi filtrarlo
    confrontandolo con i suoi vicini non funziona: i vicini sono
    sbagliati quanto lui. Serve un riferimento preso più avanti,
    a corsa avviata.

    Toglie anche i picchi isolati nel resto della traccia.
    """
    battiti = [p["hr"] for p in punti]
    validi = [b for b in battiti if b is not None]
    if len(validi) < 120:
        return 0

    # riferimento: la mediana fra il secondo e il quinto minuto,
    # quando il sensore ha agganciato ma la corsa è ancora tranquilla
    finestra = validi[120:300] if len(validi) > 300 else validi
    riferimento = mediana(finestra)
    scartati = 0

    # blocco iniziale gonfiato: si scarta finché non rientra
    for i in range(min(180, len(battiti))):
        if battiti[i] is None:
            continue
        if battiti[i] > riferimento + scarto:
            punti[i]["hr"] = None
            scartati += 1
        else:
            break

    # picchi isolati nel resto: confronto con i vicini stretti
    for i in range(len(battiti)):
        if punti[i]["hr"] is None:
            continue
        vicini = [b for b in battiti[max(0, i-8):i+9] if b is not None]
        if len(vicini) >= 5 and abs(battiti[i] - mediana(vicini)) > 40:
            punti[i]["hr"] = None
            scartati += 1

    return scartati

def distanza(a, b):
    R = 6371000
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(h))

# ============================================
# CALCOLI
# ============================================

def stima_km(punti, da_orologio=None):
    """Distanza stimata. Vedi la nota sulla correzione qui sopra."""
    if da_orologio is None:
        da_orologio = any(p["hr"] for p in punti)

    if da_orologio:
        campione = punti[::PASSO_CAMPIONE] + [punti[-1]]
        metri = sum(distanza(a, b) for a, b in zip(campione, campione[1:]))
        return metri / 1000 * CORREZIONE

    metri = sum(distanza(a, b) for a, b in zip(punti, punti[1:]))
    return metri / 1000

def tempo_in_movimento(punti):
    """Somma gli intervalli, saltando le pause dell'orologio."""
    secondi = 0
    for a, b in zip(punti, punti[1:]):
        salto = (b["t"] - a["t"]).total_seconds()
        if 0 < salto <= BUCO_PAUSA:
            secondi += salto
    return secondi

def soste(punti):
    """Numero e durata totale delle pause."""
    buchi = [(b["t"] - a["t"]).total_seconds()
             for a, b in zip(punti, punti[1:])
             if (b["t"] - a["t"]).total_seconds() > BUCO_PAUSA]
    return len(buchi), sum(buchi)

def dislivello(punti):
    """
    Somma solo le salite, ignorando le oscillazioni sotto il metro:
    il GPS ballerino altrimenti inventa centinaia di metri.
    """
    quote = [p["ele"] for p in punti if p["ele"] is not None]
    if len(quote) < 2:
        return 0
    salita = 0.0
    riferimento = quote[0]
    for q in quote[1:]:
        if q > riferimento + 1.0:
            salita += q - riferimento
            riferimento = q
        elif q < riferimento:
            riferimento = q
    return round(salita)

def tratto_piu_lungo(punti):
    """Il pezzo corso senza fermarsi più lungo, in km e minuti."""
    tagli = [i for i in range(len(punti)-1)
             if (punti[i+1]["t"] - punti[i]["t"]).total_seconds() > BUCO_PAUSA]
    bordi = [-1] + tagli + [len(punti)-1]
    migliore = (0.0, 0.0)
    for a, b in zip(bordi, bordi[1:]):
        seg = punti[a+1:b+1]
        if len(seg) < 10:
            continue
        km = stima_km(seg)
        minuti = (seg[-1]["t"] - seg[0]["t"]).total_seconds() / 60
        if km > migliore[0]:
            migliore = (km, minuti)
    return migliore

def passo_leggibile(secondi, km):
    if km <= 0:
        return "N/D"
    p = secondi / km
    return f"{int(p // 60)}:{int(p % 60):02d}"

# ============================================
# SCRITTURA
# ============================================

def argomento(nome, tipo):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            try:
                return tipo(sys.argv[i + 1].replace(",", "."))
            except ValueError:
                print(f"✗ Valore non valido per {nome}")
                exit(1)
    return None

def aggiungi_al_csv(corsa):
    esistenti = []
    if os.path.exists(FILE_CSV):
        with open(FILE_CSV, encoding="utf-8") as f:
            esistenti = list(csv.DictReader(f))

    for riga in esistenti:
        if riga["data"] == corsa["data"] and riga["nome"] == corsa["nome"]:
            print(f"\n• Una corsa del {corsa['data']} con lo stesso nome c'è già.")
            print("  Non l'ho aggiunta due volte.")
            return False

    esistenti.append(corsa)
    esistenti.sort(key=lambda c: c["data"], reverse=True)

    with open(FILE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPI)
        writer.writeheader()
        for riga in esistenti:
            writer.writerow({c: riga.get(c, "") for c in CAMPI})
    return True

# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 56)
    print("   STRAVA — AGGIUNGI UNA CORSA")
    print("=" * 56)

    file_gpx = [a for a in sys.argv[1:] if a.lower().endswith(".gpx")]
    if not file_gpx:
        print("\nUso:  python3 strava_aggiungi_gpx.py corsa.gpx [--km 6.12] [--minuti 38]")
        print("\nIl GPX si scarica da Strava: apri l'attività,")
        print("menu '...' in alto a destra → Esporta GPX\n")
        exit(1)

    km_dato = argomento("--km", float)
    minuti_dati = argomento("--minuti", int)

    for percorso in file_gpx:
        nome, punti = leggi_gpx(percorso)

        scartati = ripulisci_battiti(punti)
        da_orologio = any(x["hr"] for x in punti)

        km = km_dato if km_dato else stima_km(punti, da_orologio)
        secondi = minuti_dati * 60 if minuti_dati else tempo_in_movimento(punti)
        battiti = [p["hr"] for p in punti if p["hr"]]
        n_soste, sec_soste = soste(punti)
        best_km, best_min = tratto_piu_lungo(punti)

        corsa = {
            "data":       str(punti[0]["t"].date()),
            "nome":       nome,
            "km":         round(km, 2),
            "minuti":     round(secondi / 60),
            "passo":      passo_leggibile(secondi, km),
            "dislivello": dislivello(punti),
            "bpm_media":  round(sum(battiti) / len(battiti)) if battiti else "N/D",
        }

        print(f"\n  {corsa['data']}  {corsa['nome']}")
        print(f"  {'-' * 44}")
        if km_dato:
            nota_km = "   (ufficiale)"
        elif da_orologio:
            nota_km = "   (stimata, registrata dall'orologio, ±2%)"
        else:
            nota_km = "   (stimata, registrata dal telefono — passa --km per essere esatto)"
        print(f"  Distanza          {corsa['km']} km" + nota_km)
        print(f"  Tempo in corsa    {corsa['minuti']} min")
        print(f"  Passo             {corsa['passo']} /km")
        print(f"  Dislivello        {corsa['dislivello']} m")
        print(f"  Battito medio     {corsa['bpm_media']}"
              + (f"   (max {max(battiti)})" if battiti else "   — nessun cardio")
              + (f"   [{scartati} letture anomale scartate]" if scartati else ""))
        print(f"  Soste             {n_soste}"
              + (f"  ({sec_soste/60:.1f} min in totale)" if n_soste else ""))
        print(f"  Tratto più lungo  {best_km:.2f} km in {best_min:.1f} min"
              f"   → {passo_leggibile(best_min*60, best_km)} /km")

        if aggiungi_al_csv(corsa):
            print(f"\n  ✓ Aggiunta a '{FILE_CSV}'.")

    print("\n  Poi:  python3 strava_analisi.py")
    print("        python3 strava_report.py\n")
