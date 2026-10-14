# ============================================
# STRAVA TRACKER — AUTENTICAZIONE + DATI
# ============================================
# PRIMA DI INIZIARE:
#   1. Installa le librerie: pip3 install requests
#   2. Inserisci il tuo CLIENT_ID qui sotto
#   3. Inserisci il tuo CLIENT_SECRET qui sotto
#   4. Esegui: python3 strava_tracker.py
# ============================================

import requests
import json
import csv
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import os
import impostazioni

# --- LE TUE CREDENZIALI STRAVA (dal file .env, mai nel codice) ---
CLIENT_ID     = impostazioni.leggi("STRAVA_CLIENT_ID", "INSERISCI_QUI")
CLIENT_SECRET = impostazioni.leggi("STRAVA_CLIENT_SECRET", "INSERISCI_QUI")

# File dove salviamo il token (così non devi fare login ogni volta)
TOKEN_FILE = "strava_token.json"
OUTPUT_CSV = "strava_corse.csv"

# ============================================
# PASSO 1: AUTENTICAZIONE OAUTH
# ============================================

# Variabile globale per catturare il codice dal browser
codice_autorizzazione = None

class StravaCatcher(BaseHTTPRequestHandler):
    """
    Piccolo server locale che cattura il codice
    che Strava manda dopo che autorizzi l'app.
    """
    def do_GET(self):
        global codice_autorizzazione
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            codice_autorizzazione = params["code"][0]
            # Risposta che vedi nel browser dopo l'autorizzazione
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style='font-family:Arial;text-align:center;padding:50px'>
                <h2>&#10003; Autorizzazione completata!</h2>
                <p>Puoi chiudere questa scheda e tornare al terminale.</p>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silenzia i log del server

def salva_token(token_data, precedente=None):
    """
    Salva il token su disco.
    Il rinnovo non restituisce i dati dell'atleta: li teniamo
    da quelli vecchi così non li perdiamo.
    """
    if precedente and "athlete" not in token_data:
        token_data["athlete"] = precedente.get("athlete", {})
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

def rinnova_token(token_data):
    """
    I token Strava scadono dopo 6 ore.
    Con il refresh_token ne otteniamo uno nuovo senza rifare il login.
    Restituisce il nuovo access_token, o None se il rinnovo fallisce.
    """
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return None

    print("• Token scaduto — lo rinnovo automaticamente...")
    risposta = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    })

    if risposta.status_code != 200:
        print(f"✗ Rinnovo fallito: {risposta.status_code} — {risposta.text}")
        return None

    nuovo = risposta.json()
    salva_token(nuovo, precedente=token_data)
    print("✓ Token rinnovato e salvato.")
    return nuovo["access_token"]

def ottieni_token():
    """
    Gestisce il flusso OAuth completo:
    1. Se abbiamo già un token salvato e valido, lo riutilizza
    2. Se è scaduto, lo rinnova con il refresh_token
    3. Altrimenti apre il browser per autorizzare
    """
    global codice_autorizzazione

    # Controlla se abbiamo già un token
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)

        # Scaduto? (60 secondi di margine, per sicurezza)
        if token_data.get("expires_at", 0) > time.time() + 60:
            print("✓ Token esistente trovato — accesso diretto.")
            return token_data["access_token"]

        token = rinnova_token(token_data)
        if token:
            return token
        print("  Riprovo con l'autorizzazione dal browser.\n")

    # Nessun token valido: avvia il flusso OAuth
    print("\n--- PASSO 1: Autorizzazione Strava ---")
    print("Apertura del browser per autorizzare l'app...")
    print("(Se il browser non si apre, copia e incolla l'URL mostrato)\n")

    url_autorizzazione = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri=http://localhost:8080"
        f"&response_type=code"
        f"&scope=activity:read_all"
    )

    # Avvia server locale in background
    server = HTTPServer(("localhost", 8080), StravaCatcher)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    # Apri il browser
    webbrowser.open(url_autorizzazione)
    print(f"URL: {url_autorizzazione}\n")
    print("Attendo che tu autorizzi su Strava...")

    # Aspetta che l'utente autorizzi
    thread.join(timeout=120)  # aspetta max 2 minuti

    if not codice_autorizzazione:
        print("✗ Timeout: autorizzazione non completata entro 2 minuti.")
        return None

    print("✓ Codice ricevuto da Strava!")

    # Scambia il codice con il token di accesso
    print("\n--- PASSO 2: Ottengo il token di accesso ---")
    risposta = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          codice_autorizzazione,
        "grant_type":    "authorization_code",
    })

    if risposta.status_code != 200:
        print(f"✗ Errore: {risposta.status_code} — {risposta.text}")
        return None

    token_data = risposta.json()

    # Salva il token per le prossime volte
    salva_token(token_data)

    print(f"✓ Token ottenuto e salvato in '{TOKEN_FILE}'")
    print(f"  Benvenuto, {token_data.get('athlete', {}).get('firstname', '')}!")
    return token_data["access_token"]

# ============================================
# PASSO 2: SCARICA LE ATTIVITÀ DA STRAVA
# ============================================

def scarica_attivita(token, max_attivita=50):
    """
    Scarica le ultime attività da Strava.
    Filtra solo le corse (tipo Run).
    """
    print(f"\n--- PASSO 3: Scarico le attività da Strava ---")

    headers = {"Authorization": f"Bearer {token}"}
    attivita = []
    pagina = 1

    while len(attivita) < max_attivita:
        risposta = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers=headers,
            params={"per_page": 50, "page": pagina}
        )

        if risposta.status_code != 200:
            print(f"✗ Errore API: {risposta.status_code}")
            break

        dati = risposta.json()
        if not dati:
            break

        # Filtra solo le corse
        corse = [a for a in dati if a["type"] == "Run"]
        attivita.extend(corse)
        pagina += 1

        if len(dati) < 50:
            break

    print(f"✓ Scaricate {len(attivita)} corse da Strava.")
    return attivita[:max_attivita]

# ============================================
# PASSO 3: ELABORA E SALVA I DATI
# ============================================

def elabora_e_salva(attivita, nome_file):
    """
    Elabora i dati grezzi di Strava e li salva in CSV.
    Calcola passo, converte le unità, formatta le date.
    """
    if not attivita:
        print("Nessuna corsa trovata.")
        return []

    corse_elaborate = []

    for a in attivita:
        km = round(a["distance"] / 1000, 2)
        secondi = a["moving_time"]
        minuti = secondi / 60
        data = a["start_date_local"][:10]

        # Passo min/km
        if km > 0:
            pace_sec = secondi / km
            pace_min = int(pace_sec // 60)
            pace_sec_rest = int(pace_sec % 60)
            pace_str = f"{pace_min}:{pace_sec_rest:02d}"
        else:
            pace_str = "N/D"

        # Frequenza cardiaca (se disponibile)
        hr = a.get("average_heartrate", "N/D")
        hr = round(hr) if isinstance(hr, float) else hr

        # Dislivello
        dislivello = round(a.get("total_elevation_gain", 0))

        corsa = {
            "data":        data,
            "nome":        a.get("name", "Corsa"),
            "km":          km,
            "minuti":      round(minuti),
            "passo":       pace_str,
            "dislivello":  dislivello,
            "bpm_media":   hr,
        }
        corse_elaborate.append(corsa)

    # Salva CSV
    with open(nome_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=corse_elaborate[0].keys())
        writer.writeheader()
        writer.writerows(corse_elaborate)

    print(f"✓ Dati salvati in '{nome_file}'")
    return corse_elaborate

# ============================================
# PASSO 4: MOSTRA IL RIEPILOGO
# ============================================

def mostra_riepilogo(corse):
    """Stampa un riepilogo delle statistiche."""
    if not corse:
        return

    km_list  = [c["km"] for c in corse]
    min_list = [c["minuti"] for c in corse]

    km_totali  = sum(km_list)
    ore_totali = sum(min_list) // 60
    min_extra  = sum(min_list) % 60

    print("\n" + "=" * 50)
    print("   RIEPILOGO CORSE STRAVA")
    print("=" * 50)
    print(f"  Corse totali:      {len(corse)}")
    print(f"  Km totali:         {km_totali:.1f} km")
    print(f"  Media per uscita:  {km_totali/len(corse):.1f} km")
    print(f"  Uscita più lunga:  {max(km_list):.1f} km")
    print(f"  Tempo totale:      {ore_totali}h {min_extra}min")
    print(f"\n  Ultime 5 corse:")
    print(f"  {'Data':<12} {'Nome':<20} {'Km':>5} {'Passo':>8}")
    print("  " + "─" * 48)
    for c in corse[:5]:
        nome = c["nome"][:19]
        print(f"  {c['data']:<12} {nome:<20} {c['km']:>4.1f}  {c['passo']:>7}/km")
    print("=" * 50)
    print(f"\n✓ Apri '{OUTPUT_CSV}' con Excel o Numbers per tutti i dati.\n")

# ============================================
# PROGRAMMA PRINCIPALE
# ============================================

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("   STRAVA TRACKER — AVVIO")
    print("=" * 50)

    # Controlla che il Client Secret sia stato inserito
    if "INSERISCI_QUI" in CLIENT_SECRET:
        print("\n⚠️  Devi inserire il tuo CLIENT_SECRET!")
        print("   Copia .env.example in .env e scrivi nella riga")
        print("   STRAVA_CLIENT_SECRET= il tuo Client Secret dalla pagina Strava API.\n")
        exit()

    # Autenticazione
    token = ottieni_token()
    if not token:
        print("✗ Autenticazione fallita.")
        exit()

    # Scarica attività
    attivita = scarica_attivita(token, max_attivita=100)

    # Elabora e salva
    corse = elabora_e_salva(attivita, OUTPUT_CSV)

    # Mostra riepilogo
    mostra_riepilogo(corse)
