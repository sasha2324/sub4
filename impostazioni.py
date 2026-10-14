# ============================================
# IMPOSTAZIONI PRIVATE
# ============================================
# Credenziali e valori personali NON stanno nel codice: stanno nel file
# .env accanto agli script, escluso da git (vedi .gitignore).
# Per crearlo: copia .env.example in .env e riempi i valori.
#
# Niente librerie esterne: il formato è una riga CHIAVE=valore per volta,
# le righe vuote e quelle che iniziano con # si saltano.

import os

_CARTELLA = os.path.dirname(os.path.abspath(__file__))


def _carica_env(percorso=os.path.join(_CARTELLA, ".env")):
    if not os.path.exists(percorso):
        return
    with open(percorso, encoding="utf-8") as f:
        for riga in f:
            riga = riga.strip()
            if not riga or riga.startswith("#") or "=" not in riga:
                continue
            chiave, valore = riga.split("=", 1)
            # Una variabile già impostata nel terminale vince sul file.
            os.environ.setdefault(chiave.strip(), valore.strip().strip("\"'"))


_carica_env()


def leggi(chiave, predefinito=""):
    """Il valore di una impostazione, o il predefinito se manca."""
    return os.environ.get(chiave, predefinito)
