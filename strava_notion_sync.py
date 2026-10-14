# ============================================
# STRAVA → NOTION SYNC
# ============================================
# Legge il file strava_corse.csv e inserisce
# le corse nel database Notion automaticamente.
#
# Prima di usarlo:
#   pip3 install requests
#
# Esegui: python3 strava_notion_sync.py
# ============================================

import csv
import requests
import json
import os
from datetime import datetime

import impostazioni

# --- CONFIGURAZIONE ---

# Il tuo token di integrazione Notion
# Come ottenerlo:
#   1. Vai su https://www.notion.so/my-integrations
#   2. Clicca "New integration"
#   3. Dai un nome (es. "Strava Sync")
#   4. Copia il token "Internal Integration Secret"
#   5. Mettilo nel file .env come NOTION_TOKEN=...
NOTION_TOKEN = impostazioni.leggi("NOTION_TOKEN", "INSERISCI_QUI")

# ID del database Notion (anche questo nel .env)
DATABASE_ID = impostazioni.leggi("NOTION_DATABASE_ID", "INSERISCI_QUI")

# Versione dell'API Notion.
# Dalla 2025-09-03 un database può contenere più "data source" e le
# pagine si creano puntando alla data source, non più al database.
# Con la versione vecchia le letture funzionavano ma le scritture
# rispondevano 404: da qui il passaggio.
NOTION_VERSION = "2025-09-03"

# File CSV prodotto da strava_tracker.py
FILE_CSV = "strava_corse.csv"

# File dove teniamo traccia delle corse già inviate
# (così non le duplichiamo ogni volta)
FILE_SINCRONIZZATE = "corse_sincronizzate.json"

# ============================================
# FUNZIONI
# ============================================

def carica_corse_sincronizzate():
    """Legge quali corse sono già state inviate a Notion."""
    if os.path.exists(FILE_SINCRONIZZATE):
        with open(FILE_SINCRONIZZATE, "r") as f:
            return set(json.load(f))
    return set()

def salva_corse_sincronizzate(sincronizzate):
    """Salva l'elenco delle corse già inviate."""
    with open(FILE_SINCRONIZZATE, "w") as f:
        json.dump(list(sincronizzate), f)

def carica_csv(nome_file):
    """Legge il CSV delle corse."""
    corse = []
    try:
        with open(nome_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for riga in reader:
                corse.append(riga)
        print(f"✓ Lette {len(corse)} corse da '{nome_file}'.")
    except FileNotFoundError:
        print(f"✗ File '{nome_file}' non trovato.")
        print("  Esegui prima strava_tracker.py")
        exit()
    return corse

def classifica_corsa(km, passo_str):
    """
    Classifica la corsa in base a km e passo.
    Restituisce uno dei valori Notion: Lento, Medio, Veloce, Recupero.
    """
    try:
        parti = passo_str.split(":")
        pace_sec = int(parti[0]) * 60 + int(parti[1])
    except:
        pace_sec = 999

    if km <= 6 and pace_sec > 360:
        return "Recupero"
    elif pace_sec < 290:        # sotto 4:50 min/km
        return "Veloce"
    elif pace_sec < 340:        # sotto 5:40 min/km
        return "Medio"
    else:
        return "Lento"

def trova_data_source(headers):
    """
    Chiede a Notion qual è la data source del database.
    La ricaviamo ogni volta invece di scriverla a mano: se un giorno
    cambia, lo script continua a funzionare da solo.
    """
    risposta = requests.get(
        f"https://api.notion.com/v1/databases/{DATABASE_ID}",
        headers=headers
    )

    if risposta.status_code != 200:
        print(f"✗ Non riesco a leggere il database: {risposta.status_code}")
        print(f"  {risposta.text[:300]}")
        return None

    dati = risposta.json()

    # Un database nel cestino accetta comunque le pagine via API,
    # ma finiscono invisibili: meglio fermarsi e dirlo.
    if dati.get("in_trash") or dati.get("archived"):
        print("✗ Il database Notion è nel CESTINO.")
        print("  Le corse verrebbero scritte ma non le vedresti.")
        print("  Ripristinalo da Notion → Cestino → cerca 'Strava' → Ripristina,")
        print("  poi rilancia questo script.")
        return None

    sorgenti = dati.get("data_sources", [])
    if not sorgenti:
        print("✗ Il database non espone nessuna data source.")
        return None

    print(f"✓ Database trovato: {sorgenti[0]['name']}")
    return sorgenti[0]["id"]

def invia_a_notion(corsa, headers, data_source_id):
    """
    Invia una singola corsa al database Notion.
    Restituisce (True, "") se l'invio è andato bene,
    (False, motivo) altrimenti — così l'errore si vede.
    """
    # Classifica automatica
    tipo = classifica_corsa(
        float(corsa.get("km", 0)),
        corsa.get("passo", "6:00")
    )

    # Gestisci BPM (può essere N/D)
    bpm = corsa.get("bpm_media", "N/D")
    try:
        bpm_num = float(bpm)
    except:
        bpm_num = None

    # Costruisci il payload per l'API Notion
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": {
            "Nome": {
                "title": [{"text": {"content": corsa.get("nome", "Corsa")}}]
            },
            "Data": {
                "date": {"start": corsa["data"]}
            },
            "Km": {
                "number": float(corsa.get("km", 0))
            },
            "Durata (min)": {
                "number": int(corsa.get("minuti", 0))
            },
            "Passo (min/km)": {
                "rich_text": [{"text": {"content": corsa.get("passo", "N/D")}}]
            },
            "Tipo": {
                "select": {"name": tipo}
            },
        }
    }

    # Aggiungi dislivello se disponibile
    try:
        dislivello = int(corsa.get("dislivello", 0) or 0)
        if dislivello > 0:
            payload["properties"]["Dislivello (m)"] = {"number": dislivello}
    except:
        pass

    # Aggiungi BPM se disponibile
    if bpm_num:
        payload["properties"]["BPM medio"] = {"number": int(bpm_num)}

    # Invia alla API Notion
    risposta = requests.post(
        "https://api.notion.com/v1/pages",
        headers=headers,
        json=payload
    )

    if risposta.status_code in (200, 201):
        return True, ""

    # Il messaggio di Notion dice quasi sempre cosa manca: mostriamolo
    try:
        motivo = risposta.json().get("message", risposta.text)
    except ValueError:
        motivo = risposta.text
    return False, f"{risposta.status_code} — {motivo[:200]}"

# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

if __name__ == "__main__":

    print("\n" + "=" * 50)
    print("   STRAVA → NOTION SYNC")
    print("=" * 50)

    # Controlla token
    if "INSERISCI_QUI" in NOTION_TOKEN:
        print("\n⚠️  Devi inserire il tuo token Notion!")
        print("   Segui questi passi:")
        print("   1. Vai su https://www.notion.so/my-integrations")
        print("   2. Clicca 'New integration'")
        print("   3. Dai un nome: 'Strava Sync'")
        print("   4. Copia 'Internal Integration Secret'")
        print("   5. Mettilo nel file .env come NOTION_TOKEN=...")
        print("\n   ⚠️  Poi devi anche:")
        print("   - Aprire il database Notion 🏃 Strava — Le mie corse")
        print("   - Cliccare '...' in alto a destra → 'Connections'")
        print("   - Aggiungere la tua integrazione 'Strava Sync'")
        exit()

    # Headers per l'API Notion
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    # Scopri dove vanno scritte le pagine
    data_source_id = trova_data_source(headers)
    if not data_source_id:
        print("\n  Controlla che l'integrazione 'Strava Sync' sia ancora")
        print("  collegata al database (menu '...' → Connessioni).")
        exit()

    # Carica corse dal CSV
    corse = carica_csv(FILE_CSV)

    # Carica quelle già sincronizzate
    sincronizzate = carica_corse_sincronizzate()
    print(f"  Già sincronizzate: {len(sincronizzate)}")

    # Filtra solo le nuove
    nuove = [c for c in corse if c["data"] + "_" + c["nome"] not in sincronizzate]
    print(f"  Da sincronizzare:  {len(nuove)}\n")

    if not nuove:
        print("✓ Tutto aggiornato! Nessuna corsa nuova da inviare.")
        exit()

    # Invia le nuove corse
    inviate = 0
    errori = 0

    for corsa in nuove:
        chiave = corsa["data"] + "_" + corsa["nome"]
        print(f"  → {corsa['data']}  {corsa['nome'][:25]:<25}  {corsa['km']} km", end=" ")

        ok, motivo = invia_a_notion(corsa, headers, data_source_id)
        if ok:
            sincronizzate.add(chiave)
            inviate += 1
            print("✓")
        else:
            errori += 1
            print(f"✗  {motivo}")

    # Salva quelle sincronizzate
    salva_corse_sincronizzate(sincronizzate)

    print("\n" + "=" * 50)
    print(f"  ✓ Inviate:  {inviate} corse")
    if errori:
        print(f"  ✗ Errori:   {errori}")
    print(f"  Apri Notion per vedere le corse!")
    print("=" * 50 + "\n")
