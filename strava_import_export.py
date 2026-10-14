# ============================================
# STRAVA — IMPORT DALL'ARCHIVIO UFFICIALE
# ============================================
# Legge l'export completo che Strava ti manda via email
# (Impostazioni → Il mio account → "Richiedi il tuo archivio")
# e lo converte nello stesso formato di strava_corse.csv,
# così analisi, report ed export Notion continuano a funzionare
# senza toccare nulla.
#
# Serve perché dal 2026 l'API Strava è riservata agli abbonati.
#
# Uso:
#   python3 strava_import_export.py export_strava.zip
#   python3 strava_import_export.py activities.csv
#
# Le corse già presenti in strava_corse.csv vengono mantenute:
# lo script aggiunge solo quelle nuove.
# ============================================

import csv
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime

OUTPUT_CSV = "strava_corse.csv"
BACKUP_CSV = "strava_corse.backup.csv"

# Colonne del nostro CSV (non cambiarle: le usano gli altri script)
CAMPI = ["data", "nome", "km", "minuti", "passo", "dislivello", "bpm_media"]

# Mesi abbreviati in italiano → inglese, per le date localizzate
MESI_IT = {
    "gen": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr",
    "mag": "May", "giu": "Jun", "lug": "Jul", "ago": "Aug",
    "set": "Sep", "ott": "Oct", "nov": "Nov", "dic": "Dec",
}

# ============================================
# LETTURA DEL FILE DI EXPORT
# ============================================

def apri_activities_csv(percorso):
    """
    Accetta lo zip dell'export oppure direttamente activities.csv.
    Restituisce il contenuto del file come testo.
    """
    if not os.path.exists(percorso):
        print(f"✗ File '{percorso}' non trovato.")
        exit(1)

    if percorso.lower().endswith(".zip"):
        with zipfile.ZipFile(percorso) as z:
            candidati = [n for n in z.namelist()
                         if n.lower().endswith("activities.csv")]
            if not candidati:
                print("✗ Dentro lo zip non c'è nessun 'activities.csv'.")
                print("  Contenuto trovato:")
                for n in z.namelist()[:15]:
                    print(f"    {n}")
                exit(1)
            print(f"✓ Trovato '{candidati[0]}' dentro lo zip.")
            return z.read(candidati[0]).decode("utf-8-sig", errors="replace")

    with open(percorso, "r", encoding="utf-8-sig", errors="replace") as f:
        return f.read()

def canonicalizza(nome):
    """
    Strava traduce le intestazioni nella lingua dell'account: lo stesso
    file può avere 'Activity Date' o 'Data attività'. Riconosciamo le
    colonne che ci servono in entrambe le lingue e le riportiamo sempre
    al nome inglese, così il resto dello script non deve saperne nulla.
    Le colonne non riconosciute restano com'erano: non ci servono.
    """
    n = nome.strip().lower()
    ha = lambda *parole: all(p in n for p in parole)

    if ha("activity", "date") or ha("data", "attiv"):
        return "Activity Date"
    if ha("activity", "name") or ha("nome", "attiv"):
        return "Activity Name"
    if ha("activity", "type") or ha("tipo", "attiv"):
        return "Activity Type"
    if n in ("distance", "distanza"):
        return "Distance"
    if ha("moving", "time") or ha("tempo", "moviment"):
        return "Moving Time"
    if ha("elapsed", "time") or ha("tempo", "trascorso") or ha("tempo", "totale"):
        return "Elapsed Time"
    if ha("elevation", "gain") or ha("dislivello", "positiv"):
        return "Elevation Gain"
    # "media" va richiesto: senza, 'Max Heart Rate' finirebbe qui
    if ha("average", "heart rate") or ha("frequenza cardiaca", "media"):
        return "Average Heart Rate"
    return nome.strip()

def indicizza_colonne(intestazione):
    """
    L'export di Strava ha nomi di colonna ripetuti: 'Distance' compare
    due volte (prima in km, poi in metri), idem 'Elapsed Time'.
    Qui teniamo TUTTE le posizioni di ogni nome, così dopo scegliamo
    consapevolmente quale usare invece di sperare.
    """
    indici = defaultdict(list)
    for posizione, nome in enumerate(intestazione):
        indici[canonicalizza(nome)].append(posizione)
    return indici

def campo(riga, indici, nome, occorrenza=0):
    """Legge un campo per nome di colonna, gestendo i duplicati."""
    posizioni = indici.get(nome, [])
    if len(posizioni) <= occorrenza:
        return ""
    pos = posizioni[occorrenza]
    return riga[pos].strip() if pos < len(riga) else ""

# ============================================
# CONVERSIONE DEI VALORI
# ============================================

def numero(testo):
    """Converte in float gestendo campi vuoti e virgola decimale."""
    if not testo:
        return None
    try:
        return float(testo.replace(",", "."))
    except ValueError:
        return None

def converti_data(testo):
    """
    L'export usa la lingua dell'account: 'Aug 5, 2025, 6:19:22 PM'
    in inglese, '5 ago 2025, 18:19:22' in italiano.
    Proviamo i formati più comuni e restituiamo 'AAAA-MM-GG'.
    """
    if not testo:
        return None

    # Traduci il mese italiano in inglese, se c'è
    normalizzato = testo
    for it, en in MESI_IT.items():
        normalizzato = re.sub(rf"\b{it}\w*\b", en, normalizzato, flags=re.IGNORECASE)

    formati = [
        "%b %d, %Y, %I:%M:%S %p",
        "%b %d, %Y, %H:%M:%S",
        "%d %b %Y, %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y, %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%b %d, %Y",
        "%Y-%m-%d",
    ]
    for formato in formati:
        try:
            return datetime.strptime(normalizzato, formato).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Ultima spiaggia: pesca giorno/mese/anno con una regex
    trovato = re.search(r"(\d{4})-(\d{2})-(\d{2})", testo)
    if trovato:
        return trovato.group(0)
    return None

def e_una_corsa(tipo):
    """L'export localizza il tipo di attività: 'Run' o 'Corsa'."""
    t = tipo.lower()
    return "run" in t or "corsa" in t

def distanza_km(riga, indici):
    """
    'Distance' compare due volte: la prima nelle unità che vedi su Strava
    (km), la seconda sempre in metri. Preferiamo la seconda.
    """
    posizioni = indici.get("Distance", [])

    if len(posizioni) >= 2:
        metri = numero(campo(riga, indici, "Distance", 1))
        if metri is not None:
            return metri / 1000

    valore = numero(campo(riga, indici, "Distance", 0))
    if valore is None:
        return None
    # Con una sola colonna deduciamo l'unità dall'ordine di grandezza:
    # nessuno corre 1000 km, quindi sopra quella soglia sono metri.
    return valore / 1000 if valore > 1000 else valore

def durata_secondi(riga, indici):
    """Preferiamo il tempo in movimento, come faceva l'API."""
    for nome in ("Moving Time", "Elapsed Time"):
        for occorrenza in range(len(indici.get(nome, []))):
            secondi = numero(campo(riga, indici, nome, occorrenza))
            if secondi:
                return secondi
    return None

def formatta_passo(secondi, km):
    if not km or km <= 0 or not secondi:
        return "N/D"
    pace = secondi / km
    return f"{int(pace // 60)}:{int(pace % 60):02d}"

# ============================================
# ELABORAZIONE
# ============================================

def estrai_corse(testo_csv):
    """Dall'activities.csv dell'export tira fuori solo le corse."""
    righe = list(csv.reader(testo_csv.splitlines()))
    if not righe:
        print("✗ Il file è vuoto.")
        exit(1)

    intestazione = righe[0]
    indici = indicizza_colonne(intestazione)
    print(f"✓ Lette {len(righe) - 1} attività totali dall'export.")

    corse = []
    scartate_tipo = 0
    scartate_dati = 0

    for riga in righe[1:]:
        if not riga:
            continue

        if not e_una_corsa(campo(riga, indici, "Activity Type")):
            scartate_tipo += 1
            continue

        data = converti_data(campo(riga, indici, "Activity Date"))
        km = distanza_km(riga, indici)
        secondi = durata_secondi(riga, indici)

        if not data or not km or not secondi:
            scartate_dati += 1
            continue

        dislivello = numero(campo(riga, indici, "Elevation Gain")) or 0
        bpm = numero(campo(riga, indici, "Average Heart Rate"))

        corse.append({
            "data":       data,
            "nome":       campo(riga, indici, "Activity Name") or "Corsa",
            "km":         round(km, 2),
            "minuti":     round(secondi / 60),
            "passo":      formatta_passo(secondi, km),
            "dislivello": round(dislivello),
            "bpm_media":  round(bpm) if bpm else "N/D",
        })

    print(f"  Di cui corse: {len(corse)}  "
          f"(altri sport: {scartate_tipo}, dati incompleti: {scartate_dati})")
    return corse

def carica_csv_esistente(nome_file):
    """Rilegge le corse già salvate, per non perderle."""
    if not os.path.exists(nome_file):
        return []
    with open(nome_file, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def unisci(esistenti, nuove):
    """
    Unisce vecchie e nuove corse.
    Chiave: data + nome + km, così due uscite diverse nello stesso
    giorno restano distinte. I nomi ripetuti nello stesso giorno
    vengono numerati, perché il sync Notion usa data+nome come chiave.
    """
    tutte = []
    viste = set()

    for corsa in list(esistenti) + list(nuove):
        # I km arrivano come stringa dal CSV vecchio e come numero dall'export:
        # normalizziamo, altrimenti "24" e 24.0 sembrano corse diverse.
        try:
            km_chiave = f"{float(corsa['km']):.2f}"
        except (TypeError, ValueError):
            km_chiave = str(corsa["km"])
        chiave = (corsa["data"], corsa["nome"], km_chiave)
        if chiave in viste:
            continue
        viste.add(chiave)
        tutte.append(dict(corsa))

    # Numera gli omonimi nello stesso giorno: "Evening Run" → "Evening Run (2)"
    conteggio = defaultdict(int)
    for corsa in tutte:
        etichetta = (corsa["data"], corsa["nome"])
        conteggio[etichetta] += 1
        if conteggio[etichetta] > 1:
            corsa["nome"] = f"{corsa['nome']} ({conteggio[etichetta]})"

    tutte.sort(key=lambda c: c["data"], reverse=True)
    return tutte

def salva(corse, nome_file):
    with open(nome_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPI)
        writer.writeheader()
        for corsa in corse:
            writer.writerow({campo_: corsa.get(campo_, "") for campo_ in CAMPI})

# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("   STRAVA — IMPORT DALL'ARCHIVIO")
    print("=" * 50)

    if len(sys.argv) < 2:
        print("\nUso:  python3 strava_import_export.py <export.zip oppure activities.csv>")
        print("\nL'archivio si richiede da:")
        print("  Strava → Impostazioni → Il mio account →")
        print("  'Scarica o elimina il tuo account' → Richiedi il tuo archivio")
        print("  (fermati al passo 1, gli altri servono a cancellare l'account)\n")
        exit(1)

    testo = apri_activities_csv(sys.argv[1])
    nuove = estrai_corse(testo)

    if not nuove:
        print("\n✗ Nessuna corsa riconosciuta nell'export.")
        print("  Se il file c'è ma è in una lingua inattesa, dimmelo e adatto lo script.")
        exit(1)

    esistenti = carica_csv_esistente(OUTPUT_CSV)
    if esistenti:
        salva(esistenti, BACKUP_CSV)
        print(f"\n✓ Backup delle {len(esistenti)} corse precedenti in '{BACKUP_CSV}'.")

    tutte = unisci(esistenti, nuove)
    aggiunte = len(tutte) - len(esistenti)

    salva(tutte, OUTPUT_CSV)

    km_totali = sum(float(c["km"]) for c in tutte)

    print("\n" + "=" * 50)
    print(f"  Corse nel file:  {len(tutte)}   (+{aggiunte} nuove)")
    print(f"  Km totali:       {km_totali:.1f} km")
    if tutte:
        print(f"  Periodo:         dal {tutte[-1]['data']} al {tutte[0]['data']}")
    print(f"  Salvato in:      {OUTPUT_CSV}")
    print("=" * 50)
    print("\n  Ora puoi lanciare:  python3 strava_analisi.py\n")
