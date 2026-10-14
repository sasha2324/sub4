# ============================================
# STRAVA PENDENZA — IL PASSO EQUIVALENTE IN PIANO
# ============================================
# PERCHÉ ESISTE QUESTO FILE
#
#   Il 30/08 (martani trail) ha 608 m di dislivello su 13 km: 47 metri di
#   salita per chilometro, contro i 3 delle corse in città. Il passo grezzo
#   dice 7:58/km e sembra la corsa peggiore della stagione. Non lo è: lo
#   sforzo relativo di quel giorno è 134, il doppio di qualsiasi altra uscita.
#
#   Confrontare il passo di terreni diversi è come confrontare il consumo
#   di un'auto in pianura e in montagna. Qui traduciamo ogni corsa nel passo
#   che avrebbe avuto IN PIANO a parità di energia spesa, così le uscite
#   tornano confrontabili fra loro.
#
# COME
#   Curva di Minetti (2002, J Appl Physiol 93:1039-46): il costo energetico
#   della corsa misurato su tapis roulant da -45% a +45% di pendenza. Dà
#   quanti joule per chilo e per metro costa correre su una certa pendenza.
#   Il rapporto con il costo in piano è il fattore di conversione.
#
#   Si applica secondo per secondo sugli streams, che sono gratuiti e
#   restano nell'archivio: funziona offline e dopo la scadenza del premium.
# ============================================

import json
import os
from collections import namedtuple

CARTELLA_STREAMS = os.path.join("dati", "streams")

# Namedtuple e non tupla nuda: i campi diagnostici servono a dimostrare che
# il modello ha visto tutta la salita, e vanno chiamati per nome.
Terreno = namedtuple("Terreno", "moltiplicatore metri salita salita_da_pendenza")

# Coefficienti del polinomio di Minetti, dal grado 5 al grado 0.
# La variabile è la pendenza come frazione (0.10 = 10% di salita).
MINETTI = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)

# Costo della corsa in piano: 3.6 J/(kg·m), il termine noto del polinomio.
COSTO_PIANO = MINETTI[-1]

# Oltre queste pendenze la curva è extrapolazione, non misura: lì si
# cammina comunque, e il modello della CORSA non descrive più niente.
PENDENZA_MAX = 0.45


def costo(pendenza):
    """
    Joule per chilo e per metro per correre su questa pendenza.
    In piano vale 3.6; al 10% di salita ~5.97 (il 66% in più).
    """
    p = max(-PENDENZA_MAX, min(PENDENZA_MAX, pendenza))
    valore = 0.0
    for coefficiente in MINETTI:
        valore = valore * p + coefficiente
    return valore


def fattore(pendenza):
    """Quante volte costa più del piano. 1.0 in piano, >1 in salita."""
    return costo(pendenza) / COSTO_PIANO


def percorso_streams(id_corsa):
    return os.path.join(CARTELLA_STREAMS, f"{id_corsa}.json")


# Su quanta DISTANZA percorsa misurare la pendenza quando va ricavata dalla
# quota. Venti metri: abbastanza da coprire il rumore dell'altimetro,
# abbastanza pochi da seguire un cambio di pendenza vero.
#
# Perché a distanza e non a campioni: un secondo di corsa sono 2-3 metri in
# piano e mezzo metro in salita ripida, quindi una finestra di N campioni
# misura tratti di lunghezza diversa a seconda di come si sta correndo.
# Calibrato sulle 29 corse che hanno SIA grade_smooth di Strava SIA la quota:
# errore medio sul moltiplicatore 0,06 punti contro gli 0,78 di una media
# mobile sui campioni, massimo 0,47 contro 2,3.
FINESTRA_PENDENZA_M = 20.0


def _pendenze(streams, n):
    """
    La pendenza a ogni istante, come frazione.

    Strava la fornisce già lisciata in 'grade_smooth' (in percento) ed è la
    fonte migliore quando c'è. Garmin NON la manda, e la sua quota barometrica
    è più mossa: sulla stessa corsa piana somma 161 metri di variazioni contro
    i 54 dell'Apple Watch. Derivare la pendenza da campioni adiacenti
    amplificava quel rumore e dava ×1,030 a una corsa piana che vale ×1,005.
    """
    grade = streams.get("grade_smooth")
    if grade and len(grade) >= n:
        return [g / 100.0 if g is not None else 0.0 for g in grade]

    quote = streams.get("altitude")
    distanze = streams.get("distance")
    if not quote or not distanze:
        return None

    limite = min(n, len(quote), len(distanze))
    fuori = [0.0] * n
    j = 0
    for i in range(limite):
        if quote[i] is None or distanze[i] is None:
            continue
        # Si allunga la finestra finché non copre la distanza voluta.
        while (j < limite - 1 and distanze[j] is not None
               and distanze[j] - distanze[i] < FINESTRA_PENDENZA_M):
            j += 1
        if quote[j] is None or distanze[j] is None:
            continue
        percorsa = distanze[j] - distanze[i]
        # Finestra troppo corta (fine traccia, o fermo): non si inventa nulla.
        if percorsa >= FINESTRA_PENDENZA_M * 0.5:
            fuori[i] = (quote[j] - quote[i]) / percorsa
    return fuori


def moltiplicatore(id_corsa):
    """
    Quante volte il terreno ha alzato il costo di questa corsa: 1.00 in
    piano, 1.17 sul martani. È una media pesata sulla DISTANZA, non sul
    tempo — e questa è la scelta che rende il numero affidabile.

    Pesare sul tempo obbligherebbe a decidere quali secondi sono "fermo",
    e il flag 'moving' di Strava su un trail sbaglia di 17 minuti (si spegne
    a ogni passo lento in salita). Pesando sulla distanza il problema
    sparisce: i secondi da fermo avanzano di zero metri e non contano da soli.

    Restituisce un Terreno, oppure None.

    'salita' viene dall'altimetro; 'salita_da_pendenza' ricostruisce lo
    stesso dislivello dalle pendenze pesate sulla distanza — cioè esattamente
    dai numeri che alimentano il moltiplicatore. Se le due coincidono, il
    modello sta vedendo tutta la salita e non una parte.
    """
    percorso = percorso_streams(id_corsa)
    if not os.path.exists(percorso):
        return None
    try:
        with open(percorso) as f:
            s = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    distanze = s.get("distance")
    if not distanze:
        return None
    n = len(distanze)
    pendenze = _pendenze(s, n)
    if pendenze is None:
        return None
    quote = s.get("altitude")

    metri = metri_equiv = salita = salita_pendenza = 0.0
    for i in range(1, n):
        # La salita si somma SEMPRE, anche quando la distanza non avanza:
        # su un trail il 22% dei secondi non registra metri (passo lento in
        # salita, GPS che quantizza) e quei secondi contengono dislivello
        # vero. Filtrarli qui faceva sparire un terzo della salita.
        if quote and i < len(quote) and quote[i] > quote[i - 1]:
            salita += quote[i] - quote[i - 1]

        avanzato = distanze[i] - distanze[i - 1]
        if avanzato <= 0:
            continue
        metri += avanzato
        metri_equiv += avanzato * fattore(pendenze[i])
        if pendenze[i] > 0:
            salita_pendenza += avanzato * pendenze[i]

    if metri < 100:
        return None
    return Terreno(metri_equiv / metri, metri, salita, salita_pendenza)


def analizza(dettaglio):
    """
    Il passo equivalente in piano di una corsa archiviata.

    Distanza e tempo restano quelli ufficiali di Strava: così i numeri di
    partenza non contraddicono mai l'app. Dagli streams prendiamo solo il
    moltiplicatore del terreno, e lo applichiamo alla distanza.

        km            i km veri
        km_equiv      i km EQUIVALENTI in piano (stessa energia)
        passo         secondi al km, reali
        passo_equiv   secondi al km, come se fosse stato tutto in piano
        salita        dislivello positivo secondo Strava
        salita_vista  il dislivello che il moltiplicatore ha effettivamente
                      contato: se combacia con 'salita', il modello ha visto
                      tutta la salita
        moltiplicatore  quanto il terreno ha alzato il costo
        guadagno      secondi al km che il terreno ti stava nascondendo

    None se mancano gli streams o la corsa è troppo corta.
    """
    km = (dettaglio.get("distance") or 0) / 1000
    secondi = dettaglio.get("moving_time") or 0
    if km < 0.1 or secondi < 60:
        return None

    t = moltiplicatore(dettaglio.get("id"))
    if t is None:
        return None

    km_equiv = km * t.moltiplicatore
    passo = secondi / km
    passo_equiv = secondi / km_equiv

    return {
        "km":             km,
        "km_equiv":       km_equiv,
        "passo":          passo,
        "passo_equiv":    passo_equiv,
        "salita":         dettaglio.get("total_elevation_gain") or 0,
        "salita_streams": t.salita,
        "salita_vista":   t.salita_da_pendenza,
        "moltiplicatore": t.moltiplicatore,
        "guadagno":       passo - passo_equiv,
    }


def passo_leggibile(secondi_al_km):
    """Secondi al km → 'm:ss'. Si arrotonda prima di dividere, altrimenti
    59.6 secondi diventano il '6:60' che non esiste."""
    if not secondi_al_km:
        return "—"
    interi = int(round(secondi_al_km))
    return f"{interi // 60}:{interi % 60:02d}"


# --- prova rapida: python3 strava_pendenza.py ---
if __name__ == "__main__":
    import glob

    print("Fattore di costo secondo Minetti")
    for p in (-0.30, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.30):
        print(f"  {p*100:+6.0f}%   ×{fattore(p):.3f}")

    print("\nLe tue corse, passo reale contro passo equivalente in piano")
    print(f"  {'data':11} {'km':>6} {'D+':>5} {'passo':>7} {'equiv':>7}  {'×':>6}")
    righe = []
    for f in glob.glob(os.path.join("dati", "attivita", "*.json")):
        with open(f) as fh:
            d = json.load(fh)
        det = d.get("dettaglio", d)
        if det.get("type") not in ("Run", "TrailRun", "VirtualRun"):
            continue
        r = analizza(det)
        if r:
            righe.append((det.get("start_date_local", "")[:10], r, det.get("name", "")))
    for data, r, nome in sorted(righe, key=lambda x: x[0]):
        print(f"  {data} {r['km']:6.2f} {r['salita']:5.0f} "
              f"{passo_leggibile(r['passo']):>7} {passo_leggibile(r['passo_equiv']):>7} "
              f" ×{r['moltiplicatore']:.3f}  {nome[:24]}")
