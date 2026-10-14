# ============================================
# PIANO MARATONA — PAGINA WEB
# ============================================
# Genera la pagina consultabile dal telefono a partire dagli stessi
# dati che usa il tracker. Nessuna logica di allenamento vive qui:
# tutti i numeri arrivano da strava_piano.py, così la pagina non può
# raccontare una cosa diversa dal terminale.
#
# Si usa da lì:  python3 strava_piano.py --html
# ============================================

from datetime import date, datetime, timedelta

import strava_piano as sp
import strava_pendenza as pendenza

SETTIMANE_FUTURE = 11   # quante settimane di piano mostrare in avanti

# Sopra questo dislivello per chilometro il terreno smette di essere un
# dettaglio e diventa la cosa che decide il passo. Le corse in città stanno
# a 3 m/km, i giri lunghi sui colli a 16, il martani a 47.
SALITA_VERA = 10.0

# ============================================
# PEZZI DI PAGINA
# ============================================

def _stat(valore, unita, etichetta, nota="", stato=""):
    cls = f" stat--{stato}" if stato else ""
    u   = f"<span class='stat__u'>{unita}</span>" if unita else ""
    n   = f"<p class='stat__nota'>{nota}</p>" if nota else ""
    return (f"<div class='stat{cls}'>"
            f"<p class='stat__v'>{valore}{u}</p>"
            f"<p class='stat__l'>{etichetta}</p>{n}</div>")

def _grafico(storico, futuro):
    """Barre del volume reale, sagome tratteggiate per le settimane previste.
    La linea è l'obiettivo settimana per settimana."""
    dati = storico + futuro
    if not dati:
        return ""

    L, A = 760, 200
    px, pt, pb = 34, 16, 34
    massimo = max([d["km"] for d in dati] + [d["previsto"] for d in dati] + [10]) * 1.12
    passo   = (L - px * 2) / max(len(dati), 1)
    larg    = min(passo * 0.62, 26)

    def y(v):
        return pt + (A - pt - pb) * (1 - v / massimo)

    barre, etichette, punti = [], [], []
    for i, d in enumerate(dati):
        cx = px + passo * i + passo / 2
        punti.append(f"{cx:.1f},{y(d['previsto']):.1f}")

        if d["reale"]:
            h = max(A - pb - y(d["km"]), 0)
            cls = "barra barra--corso" if d["in_corso"] else "barra"
            barre.append(f"<rect class='{cls}' x='{cx - larg/2:.1f}' y='{y(d['km']):.1f}' "
                         f"width='{larg:.1f}' height='{h:.1f}'>"
                         f"<title>{d['etichetta']}: {d['km']} km</title></rect>")
        else:
            h = max(A - pb - y(d["previsto"]), 0)
            barre.append(f"<rect class='barra barra--prevista' x='{cx - larg/2:.1f}' "
                         f"y='{y(d['previsto']):.1f}' width='{larg:.1f}' height='{h:.1f}'>"
                         f"<title>{d['etichetta']}: {d['previsto']} km previsti</title></rect>")

        if i % 2 == 0 or i == len(dati) - 1:
            etichette.append(f"<text class='asse' x='{cx:.1f}' y='{A - 12}' "
                             f"text-anchor='middle'>{d['etichetta']}</text>")

    griglia = []
    for v in range(0, int(massimo) + 1, 20):
        if v == 0:
            continue
        griglia.append(f"<line class='griglia' x1='{px}' x2='{L - px}' y1='{y(v):.1f}' y2='{y(v):.1f}'/>"
                       f"<text class='asse asse--y' x='{px - 8}' y='{y(v) + 4:.1f}' text-anchor='end'>{v}</text>")

    return f"""<figure class="grafico">
  <svg viewBox="0 0 {L} {A}" role="img" aria-label="Volume settimanale in chilometri, reale e previsto">
    {''.join(griglia)}
    <polyline class="obiettivo" points="{' '.join(punti)}"/>
    {''.join(barre)}
    {''.join(etichette)}
  </svg>
  <figcaption>Barre: corso. Sagome: previsto. La linea è l'obiettivo.</figcaption>
</figure>"""

def _tabella_zone(corse):
    """Le soglie in battiti e il passo che ci corri davvero.

    La barra sotto dice DOVE stanno i minuti; questa dice A CHE ANDATURA."""
    fasce = sp.passi_per_zona(corse)
    if not any(z["minuti"] for z in fasce):
        return ""
    _, vere = sp.carica_soglie()

    righe = []
    for i, z in enumerate(fasce):
        fascia = f"{z['da']}–{z['a']}" if z["a"] else f"{z['da']}+"
        if z["passo"]:
            m, sec = divmod(int(z["passo"]), 60)
            passo = f"{m}:{sec:02d}/km"
        elif z["minuti"]:
            passo = "<span class='scarso'>dati troppo pochi</span>"
        else:
            passo = "<span class='scarso'>mai</span>"
        minuti = f"{z['minuti']:.0f}′" if z["minuti"] else "—"
        # La Z2 è la zona in cui vive la fase 0: si evidenzia da sola.
        ev = " class='evidenza'" if i == 1 else ""
        righe.append(
            f"<tr{ev}><th scope='row'><span class='chiave chiave--z{i+1}'></span>"
            f"Z{i+1} {z['nome']}</th>"
            f"<td class='n'>{fascia}</td><td class='n'>{passo}</td>"
            f"<td class='n'>{minuti}</td></tr>")

    fonte = ("soglie vere di Strava, archiviate in <code>dati/soglie_zone.json</code>"
             if vere else f"soglie stimate da una FC massima di {sp.HR_MASSIMA}")
    return f"""<div class="tabella-cont">
  <table class="tabella">
    <thead>
      <tr><th scope="col">Zona</th><th scope="col" class="n">Battiti</th>
          <th scope="col" class="n">Passo</th><th scope="col" class="n">Tempo</th></tr>
    </thead>
    <tbody>{''.join(righe)}</tbody>
  </table>
</div>
<p class="nota">Dove i minuti sono pochi il passo non c'è: sarebbe falso. Fonte: {fonte}.</p>"""

def _zone(settimane):
    """Come si distribuiscono i minuti fra le zone nelle ultime settimane."""
    ultime = [s for s in settimane if s["min_con_zone"]][-4:]
    if not ultime:
        return ""
    tot = [sum(s["zone"][i] for s in ultime) for i in range(5)]
    somma = sum(tot)
    nomi  = ["Z1 recupero", "Z2 facile", "Z3 medio", "Z4 soglia", "Z5 massimale"]

    fette, legenda = [], []
    for i, minuti in enumerate(tot):
        if not minuti:
            continue
        quota = minuti / somma * 100
        fette.append(f"<div class='fetta fetta--z{i+1}' style='flex:{quota:.2f}'></div>")
        legenda.append(f"<li><span class='chiave chiave--z{i+1}'></span>"
                       f"<span class='legenda__n'>{nomi[i]}</span>"
                       f"<span class='legenda__v'>{minuti:.0f}′ · {quota:.0f}%</span></li>")

    facile = (tot[0] + tot[1]) / somma * 100
    stato  = "ok" if facile >= 85 else "attenzione"
    return f"""<div class="zone">
  <div class="zone__testa">
    <p class="zone__v zone__v--{stato}">{facile:.0f}<span class="stat__u">% in Z1-Z2</span></p>
    <p class="zone__l">ultime {len(ultime)} settimane con dati cardio · obiettivo ≥ 85%</p>
  </div>
  <div class="barra-zone">{''.join(fette)}</div>
  <ul class="legenda">{''.join(legenda)}</ul>
</div>"""

def _fasi(piano, settimane, corse, FASI):
    fase_ora = piano["fase"]
    blocchi = []
    for f in FASI:
        n = f["numero"]
        if n < fase_ora:
            stato, tag = "fatta", "completata"
        elif n == fase_ora:
            stato, tag = "ora", "in corso"
        else:
            stato, tag = "dopo", "da fare"

        if n == fase_ora:
            criteri, aperto = sp.valuta_cancello(n, settimane, corse)
            voci = []
            for fatto, testo, dettaglio in criteri:
                s = "si" if fatto else ("forse" if fatto is None else "no")
                d = f"<span class='criterio__d'>{dettaglio}</span>" if dettaglio else ""
                voci.append(f"<li class='criterio criterio--{s}'><span class='criterio__t'>{testo}</span>{d}</li>")
            cancello = (f"<p class='cancello__stato cancello__stato--{'aperto' if aperto else 'chiuso'}'>"
                        f"{'Cancello aperto' if aperto else 'Cancello ancora chiuso'}</p>"
                        f"<ul class='criteri'>{''.join(voci)}</ul>")
        else:
            cancello = f"<p class='cancello__testo'>{f['cancello']}</p>"

        # Ricavati dalle funzioni del piano, non scritti a mano: scritti a mano
        # restano indietro ogni volta che la progressione cambia.
        # Un'unica fonte per durata, volume e lungo: se la scheda dice
        # "13 settimane" i numeri accanto sono quelli di 13 settimane.
        durata = {0: 5, 1: 15, 2: sp.DURATA_FASE2}[n]
        etichetta_durata = f"{durata} settimane"
        volumi = [sp.volume_previsto(n, i) for i in range(durata)]
        lunghi = [sp.lungo_previsto(n, i) for i in range(durata)]
        vol = f"{volumi[0]:.0f} → {max(volumi):.0f} km"
        lun = f"{lunghi[0]:.0f} → {max(lunghi):.0f} km"

        blocchi.append(f"""<article class="fase fase--{stato}">
  <header class="fase__testa">
    <p class="fase__num">Fase {n}</p>
    <h3 class="fase__nome">{f['nome']}</h3>
    <p class="fase__tag">{tag} · {etichetta_durata}</p>
  </header>
  <p class="fase__scopo">{f['scopo']}</p>
  <dl class="fase__dati">
    <div><dt>Volume</dt><dd>{vol}</dd></div>
    <div><dt>Lungo</dt><dd>{lun}</dd></div>
  </dl>
  <div class="cancello">{cancello}</div>
</article>""")
    return "".join(blocchi)

# ============================================
# LA PAGINA
# ============================================


def _continua(corse, settimane):
    """Il numero che conta: quanto corri di fila, e quanto manca ai 42,195."""
    migliore = max((c for c in corse if c["continua"]), key=lambda c: c["continua"], default=None)
    if not migliore:
        return ""
    km, minuti = migliore["continua"], migliore["cont_min"]

    tappe = [(km, "oggi", True), (13, "cancello fase 1", False),
             (21.1, "mezza", False), (32, "lungo di picco", False),
             (42.195, "maratona", False)]
    META = 42.195
    segni = "".join(
        f"<div class='tappa{" tappa--ora" if ora else ""}' style='left:{v/META*100:.1f}%'>"
        f"<span class='tappa__v'>{v:g}</span><span class='tappa__l'>{nome}</span></div>"
        for v, nome, ora in tappe)

    return f"""<div class="continua">
  <p class="continua__v">{km:.2f}<span class="continua__u">km di corsa continua</span></p>
  <p class="continua__l">{minuti} minuti, il {migliore['data'][8:10]}/{migliore['data'][5:7]} — il tuo record</p>
  <div class="scala"><div class="scala__fatto" style="width:{km/META*100:.1f}%"></div>{segni}</div>
</div>"""

def _terreno(corse):
    """Il passo che il dislivello nascondeva.

    Confrontare il passo di un trail con quello di una corsa in città è come
    confrontare il consumo di un'auto in pianura e in montagna. Qui ogni
    corsa viene tradotta nel passo che avrebbe avuto IN PIANO a parità di
    energia spesa, con la curva di Minetti (vedi strava_pendenza.py).

    La sezione compare solo se c'è almeno una corsa in salita vera: in una
    stagione tutta in città non avrebbe niente da dire."""
    salite = [c for c in corse
              if c["salita_per_km"] >= SALITA_VERA and c["passo_equiv"]]
    if not salite:
        return ""

    righe = "".join(
        f"<tr><th scope='row'>{c['data'][8:10]}/{c['data'][5:7]}"
        f"<span class='quando'>{c['nome'][:18]}</span></th>"
        f"<td class='n'>{c['km']:.2f}</td>"
        f"<td class='n'>{c['dislivello']:.0f} m</td>"
        f"<td class='n'>{c['passo']}</td>"
        f"<td class='n evid'>{c['passo_equiv']}</td>"
        f"<td class='n'>{c['km_equiv']:.1f}</td></tr>"
        for c in sorted(salite, key=lambda c: c["salita_per_km"], reverse=True))

    # La corsa da raccontare è quella con più salita per chilometro. Tutto
    # ciò che si dice di lei va CALCOLATO, non scritto a mano: fra un mese
    # sarà un'altra corsa e la frase deve restare vera da sola.
    peggiore = max(salite, key=lambda c: c["salita_per_km"])

    # Quanto risale in classifica una volta corretta. Il confronto è fra
    # passi equivalenti, quindi fra pari: è l'unico modo onesto di dire
    # "non era la peggiore".
    def in_secondi(passo):
        m, _, s = passo.partition(":")
        return int(m) * 60 + int(s)

    tutte  = [c for c in corse if c["passo_equiv"]]
    grezzo = sorted(tutte, key=lambda c: in_secondi(c["passo"]))
    equiv  = sorted(tutte, key=lambda c: in_secondi(c["passo_equiv"]))
    prima = next(i for i, c in enumerate(grezzo, 1) if c["data"] == peggiore["data"])
    dopo  = next(i for i, c in enumerate(equiv, 1) if c["data"] == peggiore["data"])

    # Si dice di quanto risale, non dove arriva: "in mezzo al gruppo" sarebbe
    # una valutazione, e in fondo a una classifica di 16 sarebbe pure falsa.
    salto = (f"e risale dal {prima}º al {dopo}º posto per passo fra le "
             f"{len(equiv)} corse della stagione" if dopo < prima
             else f"e resta {dopo}ª su {len(equiv)} per passo")
    lentezza = "il più lento della stagione" if prima == len(grezzo) else "fra i più lenti"
    coda = (" — ed era comunque la più lunga che tu abbia fatto."
            if peggiore["km"] == max(c["km"] for c in tutte) else ".")
    risalita = (f"Il passo grezzo dice {peggiore['passo']}/km, {lentezza}. "
                f"Corretto per il terreno dice <strong>{peggiore['passo_equiv']}/km</strong>, {salto}. "
                f"È costata come {peggiore['km_equiv']:.1f} km in piano invece di "
                f"{peggiore['km']:.2f}{coda}")

    # La prova che il modello ha visto tutta la salita: si ricostruisce il
    # dislivello dalle stesse pendenze che alimentano il moltiplicatore e lo
    # si mette accanto a quello dichiarato da Strava. Se combaciano, la
    # correzione poggia sulla salita intera e non su una parte di essa.
    t = pendenza.moltiplicatore(peggiore["id"])
    if t and peggiore["dislivello"]:
        scarto = abs(t.salita_da_pendenza - peggiore["dislivello"]) / peggiore["dislivello"]
        quanto = "meno dell'1%" if scarto < 0.01 else f"{scarto*100:.0f}%"
        verifica = (f" Controprova: le pendenze da cui esce la correzione "
                    f"ricostruiscono {t.salita_da_pendenza:.0f} m di salita, contro i "
                    f"{peggiore['dislivello']:.0f} m dichiarati da Strava — {quanto} di "
                    f"scarto, quindi la correzione poggia sulla salita intera.")
    else:
        verifica = ""

    return f"""<div class="tabella-cont">
  <table class="tabella">
    <thead><tr><th scope="col">Corsa</th><th scope="col" class="n">km</th>
    <th scope="col" class="n">D+</th><th scope="col" class="n">passo</th>
    <th scope="col" class="n">in piano</th><th scope="col" class="n">km equiv.</th></tr></thead>
    <tbody>{righe}</tbody>
  </table>
</div>
<p class="nota">Il <strong>{peggiore['data'][8:10]}/{peggiore['data'][5:7]}</strong> ha
{peggiore['dislivello']:.0f} metri di salita in {peggiore['km']:.2f} km:
{peggiore['salita_per_km']:.0f} metri per chilometro, contro i 3 delle uscite in
città. {risalita}</p>
<p class="nota">La conversione usa la curva di Minetti (2002): il costo
energetico della corsa misurato in laboratorio da −45% a +45% di pendenza,
applicato metro per metro sulla pendenza che Strava registra lungo la traccia.
Distanza e tempo restano quelli ufficiali di Strava — il modello tocca solo il
confronto, mai i tuoi numeri.{verifica}</p>"""

def _rampa(piano, rientro):
    """La risalita per intero, non una settimana alla volta.

    Serve perché la domanda vera è «quando torno normale»: vedere solo la
    settimana in corso non risponde, e un piano che non dice quando finisce
    la prudenza invita a saltarla."""
    calendario = (piano.get("rientro") or {}).get("per_settimana") or {}
    if not calendario or not rientro:
        return ""
    oggi = sp.lunedi_di(date.today()).isoformat()

    righe = ""
    for lunedi in sorted(calendario):
        v = calendario[lunedi]
        sedute = v.get("sedute", [])
        lungo = max((s["km"] for s in sedute if "Lungo" in s["nome"]), default=0)
        ora = " class='evidenza'" if lunedi == oggi else ""
        righe += (f"<tr{ora}><th scope='row'>{lunedi[8:10]}/{lunedi[5:7]}</th>"
                  f"<td class='n'>{v['volume']:.1f}</td>"
                  f"<td class='n'>{len(sedute)}</td>"
                  f"<td class='n'>{f'{lungo:.0f}' if lungo else '—'}</td>"
                  f"<td class='come'>{v.get('nota_settimana', '')}</td></tr>")

    fine = sorted(calendario)[-1]
    normale = (datetime.strptime(fine, "%Y-%m-%d").date() + timedelta(days=7))
    return f"""<div class="tabella-cont">
  <table class="tabella">
    <thead><tr><th scope="col">Settimana</th><th scope="col" class="n">km</th>
    <th scope="col" class="n">uscite</th><th scope="col" class="n">lungo</th>
    <th scope="col">cosa cambia</th></tr></thead>
    <tbody>{righe}</tbody>
  </table>
</div>
<p class="nota">Dal <strong>{normale.strftime('%d/%m')}</strong> la rampa è finita e
riprende la settimana piena del piano, <strong>qualità compresa</strong> — è
l'ultima cosa che torna, perché i cambi di ritmo caricano le gambe più di
qualsiasi chilometro lento.</p>
<p class="nota">Gli incrementi qui sopra superano la regola del 10% che il
tracker applica normalmente, e lo fanno di proposito: quella regola serve
quando si va in territorio nuovo. Qui il tetto è la tua storia recente — 34 km
li avevi già fatti il 24/08 — e il vincolo non è il motore, è quanto carico
l'articolazione accetta. Per questo ogni gradino vale solo se il precedente non
ha lasciato niente.</p>"""

def _tempi(corse, piano, settimane):
    """Record e proiezioni in una tabella sola.

    Erano due tabelle che dicevano quasi la stessa cosa, con una colonna
    ('record vero') ripetuta di peso. Qui ogni distanza ha una riga, e la
    colonna 'quando' distingue il tempo MISURATO da quello STIMATO: è
    l'unica differenza che conta davvero fra un record e una proiezione.
    """
    migliori = sp.record_distanze(corse)
    in_piano = sp.record_in_piano(corse)
    prev = sp.previsioni(corse, piano)
    stime = sp.stime_oggi(corse, piano)
    continua = max((c["continua"] for c in corse if c["continua"]), default=0)
    obiettivi = sp.obiettivi_derivati(piano)
    gradino = sp.obiettivo_attivo(piano)
    pluriennali = set((piano.get("obiettivi") or {}).get("pluriennale") or {})

    def scarto(secondi):
        """Quanto manca, nell'unità che si legge davvero.

        Sotto il minuto i secondi ('+23″'); fino a un'ora minuti e secondi
        ('+1:26', non '+86″' né '+1′'); oltre, minuti tondi. Arrotondare tutto
        ai minuti nascondeva proprio la differenza da leggere: sui 1000 metri
        ventitré secondi sono l'intero divario."""
        segno = "+" if secondi > 0 else "−"
        s = abs(secondi)
        if s < 60:
            testo = f"{segno}{s:.0f}″"
        elif s < 3600:
            testo = f"{segno}{int(s) // 60}:{int(s) % 60:02d}"
        else:
            testo = f"{segno}{s / 60:.0f}′"
        col = "caldo" if secondi > 0 else "pino"
        return f"<span class='scarto scarto--{col}'>{testo}</span>"

    def cella_passo(nome, km, previsto):
        """Il passo della riga. Dove la stima e' una forchetta lo e' anche il
        passo: un passo solo accanto a due tempi si legge come se uno dei due
        fosse quello buono."""
        s = stime.get(nome) or {}
        if "da" in s:
            return (f"<td class='n'>{sp.mmss(s['da'] / km)}"
                    f"<span class='quando'>–</span>{sp.mmss(s['a'] / km)}/km</td>")
        return f"<td class='n'>{sp.mmss(previsto / km)}/km</td>"

    def cella_stima(nome):
        s = stime.get(nome)
        if not s:
            return "<td class='n'>—</td>"
        if s["fonte"] == "record":
            # uguale al record: ripetere il numero riempirebbe la colonna
            # di doppioni, e la cosa da vedere e' dove la stima SI STACCA
            return "<td class='n'><span class='scarso'>= record</span></td>"
        if "da" in s:
            # Due esponenti di Riegel, due estremi. La forchetta non e'
            # prudenza: e' la larghezza vera di quello che non sappiamo
            # ancora, e si stringe con la prova sui 5 km.
            return (f"<td class='n evid'>{sp.hms(s['da'])}"
                    f"<span class='quando'>–</span>{sp.hms(s['a'])}</td>")
        return f"<td class='n evid'>{sp.hms(s['secondi'])}</td>"

    righe = []
    # Prima le distanze corse davvero, in ordine crescente.
    for metri, nome in sp.DISTANZE_RECORD:
        ob = obiettivi.get(nome)
        cella_ob = "—"
        if ob:
            cella_ob = sp.hms(ob)
            if nome in pluriennali:
                cella_ob += "<span class='quando'>pluriennale</span>"
            if nome in migliori:
                cella_ob += " " + scarto(migliori[nome][0] - ob)
        if nome in migliori:
            t, data = migliori[nome]
            righe.append(
                f"<tr><th scope='row'>{nome}</th>"
                f"<td class='n'>{sp.hms(t)}</td>"
                f"<td class='n'>{sp.mmss(t / (metri / 1000))}/km</td>"
                f"<td class='n'>{data[8:10]}/{data[5:7]}</td>"
                f"{cella_stima(nome)}"
                f"<td class='n'>{cella_ob}</td></tr>")
        else:
            righe.append(
                f"<tr class='vuota'><th scope='row'>{nome}</th>"
                f"<td class='n' colspan='3'>da conquistare</td>"
                f"{cella_stima(nome)}"
                f"<td class='n'>{cella_ob}</td></tr>")

    # Poi le due gare, che un tempo misurato non ce l'hanno ancora.
    if prev:
        for r in prev["righe"]:
            if r["nome"] in migliori or not r["obiettivo"]:
                continue
            righe.append(
                f"<tr class='stimata'><th scope='row'>{r['nome']}</th>"
                f"<td class='n'><span class='scarso'>mai corsa</span></td>"
                f"{cella_passo(r['nome'], r['km'], r['previsto'])}"
                f"<td class='n'>—</td>"
                f"{cella_stima(r['nome'])}"
                f"<td class='n'>{sp.hms(r['obiettivo'])} "
                f"{scarto(r['scarto'])}</td></tr>")

    note = ""
    ob_piano = piano.get("obiettivi") or {}
    if gradino:
        prova = ob_piano.get("prova") or {}
        quando = prova.get("quando", "")
        note += f"""<p class="nota">Derivati con Riegel dall'ancora: il
<strong>{ob_piano.get('ancora', '5 km')}</strong> in {sp.hms(gradino['secondi'])}."""
        note += (f""" Test il <strong>{quando[8:10]}/{quando[5:7]}</strong>."""
                 if quando else "") + "</p>"
    if prev:
        b = sp.esponente_personale({k: (v[0],) for k, v in in_piano.items()})
        ancora = in_piano.get(prev["base"])
        dettaglio_ancora = ""
        if ancora:
            _, _, reale, molt = ancora
            if abs(molt - 1) > 0.005:
                dettaglio_ancora = (f" Corso in {sp.hms(reale)} su un tratto in "
                                    f"{'discesa' if molt < 1 else 'salita'}: in piano vale "
                                    f"{sp.hms(prev['tempo_base'])}, ed è quello che conta per proiettare.")
        note += f"""<p class="nota"><strong>Stimato</strong> = quanto potresti
correre oggi: il più veloce fra il tuo record e la proiezione dal
<strong>{prev['base']} equivalente in piano</strong> del
{prev['data_base'][8:10]}/{prev['data_base'][5:7]}.{dettaglio_ancora}</p>"""
        if b is not None:
            note += f"""<p class="nota">La <strong>forchetta</strong> sono due
esponenti di Riegel: 1,06 (allenato su tutte le distanze) e
{str(round(b, 2)).replace('.', ',')}, quello che descrive i tuoi record una
volta riportati in piano. Il tuo è più alto perché hai più velocità che
resistenza. La prova sui 5 km lo misura invece di presumerlo.</p>"""

    return f"""<div class="tabella-cont">
  <table class="tabella">
    <thead><tr><th scope="col">Distanza</th><th scope="col" class="n">Tempo</th>
    <th scope="col" class="n">Passo</th><th scope="col" class="n">Quando</th>
    <th scope="col" class="n">Stimato</th>
    <th scope="col" class="n">Obiettivo</th></tr></thead>
    <tbody>{''.join(righe)}</tbody>
  </table>
</div>
{note}"""

def _settimana(piano, corrente, rimanenti, evento, rientro=None, sedute=None):
    """Le uscite della settimana: fatte con la spunta, da fare senza.

    Una riga per seduta prevista, in ordine. Le corse già fatte prendono il
    posto delle prime sedute e mostrano i numeri veri — quello che conta, di
    una corsa fatta, non è più l'istruzione ma com'è andata."""
    previste = list(sedute or [])
    fatte = list(corrente.get("corse", []))
    righe = []

    for i, c in enumerate(fatte):
        nome = previste[i][0] if i < len(previste) else "Extra"
        pezzi = (f" · {c['pezzi']} pezzi" if c.get("pezzi") and c["pezzi"] > 1
                 else " · di fila")
        righe.append(
            f"<tr class='fatta'><td class='spunta'>✓</td>"
            f"<th scope='row'>{nome}</th>"
            f"<td class='n'>{c['km']:.2f}</td>"
            f"<td class='come'>{c['data'][8:10]}/{c['data'][5:7]} · "
            f"{c['passo']}/km{pezzi}</td></tr>")

    # Il testo si prende per POSIZIONE, non per nome: nella settimana della
    # gara ci sono due sedute chiamate "Facile" con istruzioni diverse, e
    # cercare per nome restituiva sempre la prima.
    testi = [s.get("come", "") for s in (rientro or {}).get("sedute", [])]
    for i, (nome, km) in enumerate(previste[len(fatte):], start=len(fatte)):
        come = testi[i] if i < len(testi) else sp.ritmo_di(nome, rientro)
        righe.append(
            f"<tr><td class='spunta spunta--vuota'>○</td>"
            f"<th scope='row'>{nome}</th>"
            f"<td class='n'>{km:.1f}</td>"
            f"<td class='come'>{come}</td></tr>")

    if evento:
        km = f"{evento['km']:.0f} km · " if evento.get("km") else ""
        righe.append(
            f"<tr class='evento'><td class='spunta'>◆</td>"
            f"<th scope='row'>{evento.get('etichetta', 'evento').capitalize()}</th>"
            f"<td class='n'>{evento.get('km', 0):.1f}</td>"
            f"<td class='come'>{km}{evento['nome']}</td></tr>")

    if not righe:
        return "<p class='nota'>Niente in programma questa settimana.</p>"

    totale_fatto = sum(c["km"] for c in fatte)
    # L'evento è una riga della settimana come le altre: se i suoi km non
    # entrano nel totale, la settimana della gara sembra da 16 km invece di 31.
    totale = (totale_fatto + sum(km for _, km in previste[len(fatte):])
              + (evento.get("km", 0) if evento else 0))
    return f"""<div class="tabella-cont">
  <table class="tabella tabella--settimana">
    <tbody>{''.join(righe)}</tbody>
    <tfoot><tr><td></td><th scope="row">Totale</th>
    <td class="n">{totale:.1f}</td>
    <td class="come">{totale_fatto:.1f} km già fatti</td></tr></tfoot>
  </table>
</div>"""

def _gare(piano):
    """Le due date che ora hanno un nome."""
    from datetime import date as _d
    oggi = _d.today()
    voci = []
    for chiave, ruolo in (("mezza", "L'esame di metà percorso"), ("gara", "Il traguardo")):
        g = piano.get(chiave)
        if not g:
            continue
        d = _d.fromisoformat(g["data"])
        giorni = (d - oggi).days
        extra = f" · {g['obiettivo']}" if g.get("obiettivo") else ""
        alt = f"<span class='gara__alt'>{g['alternativa']}</span>" if g.get("alternativa") else ""
        voci.append(f"""<article class="gara">
  <p class="gara__ruolo">{ruolo}</p>
  <h3 class="gara__nome">{g['nome']}</h3>
  <p class="gara__data">{d.strftime('%d/%m/%Y')}{extra}</p>
  <p class="gara__conto"><strong>{giorni}</strong> giorni · {giorni // 7} settimane</p>
  {alt}
  <p class="gara__nota">{g.get('nota','')}</p>
</article>""")
    return f"<div class='gare'>{''.join(voci)}</div>" if voci else ""

def genera(percorso, piano, corse, settimane, FASI):
    # Lanciando strava_piano.py il file viene caricato due volte — una come
    # __main__ e una come modulo importato da qui — quindi il DURATA_FASE2
    # calcolato nel main non arriva a questa copia. Va rifissato.
    sp.DURATA_FASE2 = sp.durata_fase2(piano)

    fase     = piano["fase"]
    f        = FASI[fase]
    n_sett   = sp.settimane_nella_fase(piano, settimane)
    corrente = settimane[-1]
    sedute, vol_previsto = sp.settimana_tipo(fase, n_sett, piano["giorni_settimana"])
    lungo_ob = sp.lungo_previsto(fase, n_sett)

    # Un rientro sospende la settimana normale: la pagina deve mostrare quella
    # vera, altrimenti mette davanti agli occhi 34 km e un lungo da 11 mentre
    # in chat si è deciso il contrario.
    rientro = sp.rientro_attivo(piano, settimane[-1])
    if rientro:
        sedute = [(s["nome"], s["km"]) for s in rientro["sedute"]]
        vol_previsto = rientro.get("volume", sum(km for _, km in sedute))
        # Un rientro può non avere sedute affatto: è lo stop. max() su una
        # lista vuota solleva ValueError e porterebbe giù tutta la pagina
        # proprio nella settimana in cui serve di più.
        lungo_ob = max((km for _, km in sedute), default=0)
    inizio   = sp.lunedi_di(datetime.strptime(piano["fase_inizio"], "%Y-%m-%d").date())

    # ── storico + previsione per il grafico ──
    storico = []
    for s in settimane:
        dentro = s["lunedi"] >= inizio
        idx    = (s["lunedi"] - inizio).days // 7
        storico.append({
            "etichetta": s["etichetta"], "km": s["km"],
            "previsto": sp.volume_previsto(fase, idx) if dentro else 0,
            "reale": True, "in_corso": s["in_corso"],
        })
    ultimo_lun = settimane[-1]["lunedi"]
    futuro = []
    for k in range(1, SETTIMANE_FUTURE + 1):
        lun = ultimo_lun + timedelta(days=7 * k)
        idx = (lun - inizio).days // 7
        fs  = fase if idx < 8 else min(fase + 1, 2)
        futuro.append({
            "etichetta": lun.strftime("%d/%m"), "km": 0,
            "previsto": sp.volume_previsto(fs, idx if fs == fase else idx - 8),
            "reale": False, "in_corso": False,
        })

    # ── numeri della settimana in corso ──
    p_facile = sp.perc_facile(corrente)
    # Durante un rientro chiudere sotto il volume È l'obiettivo, non un
    # problema: la spia verde/arancione qui direbbe il contrario di quello
    # che si è deciso.
    stato_vol = ("" if rientro else
                 "ok" if corrente["km"] >= vol_previsto * 0.9
                 else "attenzione" if corrente["km"] > vol_previsto * 1.15 else "")
    stat_zone = (_stat(f"{p_facile:.0f}", "%", "Tempo in Z1-Z2", "obiettivo ≥ 85%",
                       "ok" if p_facile >= 85 else "attenzione")
                 if p_facile is not None
                 else _stat("—", "", "Tempo in Z1-Z2", "nessun dato cardio"))

    testi_sedute = [s.get("come", "") for s in (rientro or {}).get("sedute", [])]
    righe_sedute = "".join(
        f"<tr><th scope='row'>{nome}</th><td class='n'>{km:.1f}</td>"
        f"<td class='come'>"
        f"{testi_sedute[i] if i < len(testi_sedute) else sp.ritmo_di(nome, rientro)}"
        f"</td></tr>"
        for i, (nome, km) in enumerate(sedute))

    evento = sp.evento_in_sospeso(piano, corrente)
    rimanenti, _ = sp.sedute_rimanenti(piano, corrente, fase, n_sett, evento)
    sez_gare     = _gare(piano)
    sez_continua = _continua(corse, settimane)
    sez_terreno  = _terreno(corse)
    sez_rampa    = _rampa(piano, rientro)
    sez_tempi    = _tempi(corse, piano, settimane)
    sez_settimana = _settimana(piano, corrente, rimanenti, evento, rientro, sedute)

    tabella_sedute = (f"""<div class="tabella-cont">
      <table class="tabella">
        <thead><tr><th scope="col">Seduta</th><th scope="col" class="n">km</th><th scope="col">Come</th></tr></thead>
        <tbody>{righe_sedute}</tbody>
        <tfoot><tr><th scope="row">Totale</th><td class="n">{vol_previsto:.1f}</td><td></td></tr></tfoot>
      </table>
    </div>""" if sedute else "")

    # Le due statistiche che un rientro rende prive di senso. Il "lungo" non
    # esiste questa settimana, e le uscite previste non sono più quattro:
    # lasciarle com'erano mostrerebbe 7.2/4 km di lungo (già superato!) e
    # un traguardo di quattro uscite che nessuno vuole più che tu insegua.
    if rientro and not rimanenti and not sedute:
        # Stop: non esiste un traguardo da raggiungere, e stampare "7.2 / 0 km"
        # è peggio che non stampare niente. Restano i numeri fatti, senza meta.
        stat_lungo  = _stat("—", "", "Lungo", "non si corre")
        stat_uscite = _stat(corrente["n"], "", "Uscite", "prima dello stop")
        stat_volume = _stat(f"{corrente['km']:.1f}", " km", "Volume settimana",
                            "prima dello stop")
    elif rientro:
        stat_lungo  = _stat("—", "", "Lungo", "nessuno, questa settimana")
        stat_uscite = _stat(corrente["n"], f" / {corrente['n'] + len(rimanenti)}", "Uscite")
        obiettivo = f"{vol_previsto:.1f}" if vol_previsto < 5 else f"{vol_previsto:.0f}"
        stat_volume = _stat(f"{corrente['km']:.1f}", f" / {obiettivo} km",
                            "Volume settimana", "rientro", stato_vol)
    else:
        stat_lungo  = _stat(f"{corrente['lungo']:.1f}", f" / {lungo_ob:.0f} km", "Lungo")
        stat_uscite = _stat(corrente["n"], f" / {piano['giorni_settimana']}", "Uscite")
        stat_volume = _stat(f"{corrente['km']:.1f}", f" / {vol_previsto:.0f} km",
                            "Volume settimana", f["durata"], stato_vol)

    # Il cartello del rientro. Porta la data di fine bene in vista: è quello
    # che impedisce alla prudenza di diventare permanente per dimenticanza.
    avviso_rientro = ""
    intro_sedute = ("Quattro uscite. Tutti i minuti duri della settimana stanno "
                    "nella seduta di qualità: le altre tre sono facili sul serio — "
                    "se il passo che serve è 7:10, il passo è 7:10.")
    if rientro:
        fine = f"{rientro['al'][8:10]}/{rientro['al'][5:7]}"
        stop = sp.etichetta_rientro(rientro) == "STOP"
        titolo_avviso = (f"Stop — da rivedere il {fine}" if stop
                         else f"Rientro fino al {fine}")
        extra = ""
        if rientro.get("prima"):
            extra += f"<p class='avviso__prima'>Prima di uscire: {rientro['prima']}</p>"
        if rientro.get("si_puo"):
            extra += f"<p class='avviso__p'>Si può: {rientro['si_puo']}</p>"
        if rientro.get("condizione"):
            extra += f"<p class='avviso__c'>{rientro['condizione']}</p>"
        avviso_rientro = (
            f"<div class='avviso{' avviso--stop' if stop else ''}'>"
            f"<p class='avviso__t'>{titolo_avviso} — la settimana normale è sospesa</p>"
            f"<p class='avviso__p'>{rientro['perche']}</p>"
            f"<p class='avviso__r'>{rientro['regola']}</p>"
            f"<p class='avviso__v'>Vietato: {rientro['vietato']}</p>"
            f"{extra}</div>")
        km_piano = sp.settimana_tipo(fase, n_sett, piano['giorni_settimana'])[1]
        if stop:
            intro_sedute = (
                f"<strong>Questa settimana non si corre.</strong> Il piano "
                f"prevedeva {km_piano:.0f} km su quattro uscite: è sospeso, e non "
                f"c'è niente da recuperare. Riprende quando il problema è stato "
                f"risolto — la data del {fine} serve solo a non lasciare la "
                f"sospensione aperta per dimenticanza.")
        else:
            intro_sedute = (
                f"<strong>Non è la settimana del piano.</strong> Quella prevedeva "
                f"{km_piano:.0f} km su quattro uscite, con qualità e lungo: è "
                f"sospesa fino al {fine}. Queste sono prove corte per capire se è "
                f"tutto a posto.")

    oggi = date.today().strftime("%d/%m/%Y")
    # Gara e data vengono da piano.json (privato), non dal codice.
    gara_riga = ""
    if piano.get("gara") and piano["gara"].get("data"):
        g = datetime.strptime(piano["gara"]["data"], "%Y-%m-%d").date()
        mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                "agosto", "settembre", "ottobre", "novembre", "dicembre"]
        gara_riga = f"\n    {piano['gara']['nome']}, {g.day} {mesi[g.month - 1]} {g.year}."

    html = f"""<title>Maratona sotto le 4 ore</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400..700&display=swap">
<style>
{_css()}
</style>

<main class="pagina">

  <header class="testata">
    <p class="occhiello">Piano di Sasha · aggiornato il {oggi}</p>
    <h1>Maratona sotto le 4 ore</h1>
    <p class="sottotitolo">42,195 km a <strong>5:41</strong> al chilometro.{gara_riga}</p>
  </header>

  <section class="banda">
    <div class="banda__interno">
      <p class="occhiello occhiello--chiaro">Fase {fase} · {f['nome']} — settimana {n_sett + 1}</p>
      <div class="stats">
        {stat_volume}
        {stat_uscite}
        {stat_lungo}
        {stat_zone}
      </div>
    </div>
  </section>

  <section class="sezione">
    <h2>Le due date</h2>
    {sez_gare}
  </section>

  <section class="sezione">
    <h2>Questa settimana</h2>
    {sez_settimana}
  </section>

  <section class="sezione">
    <h2>Quanto corri di fila</h2>
    {sez_continua}
  </section>

  <section class="sezione">
    <h2>Passi e zone</h2>
    <p>Soglie vere di Strava, non stime dalla FC massima.</p>
    <div class="tabella-cont">
      <table class="tabella">
        <thead><tr><th scope="col">Andatura</th><th scope="col" class="n">Passo</th><th scope="col" class="n">FC</th></tr></thead>
        <tbody>
          <tr><th scope="row">Facile / lungo</th><td class="n">6:30-7:15</td><td class="n">130-150</td></tr>
          <tr><th scope="row">Medio</th><td class="n">6:00</td><td class="n">~160</td></tr>
          <tr><th scope="row">Soglia <span class="quando">da fase 1</span></th><td class="n">~5:00</td><td class="n">170-180</td></tr>
          <tr class="evidenza"><th scope="row">Ritmo maratona</th><td class="n">5:41</td><td class="n">~160</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  

  <section class="sezione">
    <h2>I tuoi tempi</h2>
    {sez_tempi}
  </section>

  <section class="sezione">
    <h2>Il volume, settimana per settimana</h2>
    {_grafico(storico, futuro)}
  </section>

  <section class="sezione">
    <h2>Dove stanno i minuti</h2>
    <h3 class="sotto">Le tue zone</h3>
    {_tabella_zone(corse)}
    <h3 class="sotto">Dove sono finiti i minuti</h3>
    {_zone(settimane)}
  </section>

  <section class="sezione sezione--larga">
    <h2>Le tre fasi</h2>
    <p class="sezione__intro">Si cambia fase quando i criteri sono soddisfatti,
    non a calendario. Salti una settimana e il cancello si sposta.</p>
    <div class="fasi">{_fasi(piano, settimane, corse, FASI)}</div>
  </section>


  <footer class="chiusura">
    <p>Generato da <code>strava_piano.py --html</code> dall'archivio in <code>dati/</code>.</p>
  </footer>

</main>"""

    with open(percorso, "w", encoding="utf-8") as fp:
        fp.write(html)
    return percorso



# ============================================
# FOGLIO DI STILE — MERCURY
# ============================================
# Segue DESIGN.md: «alpine banking at blue hour», letto da
# styles.refero.design. Quattro regole comandano tutto il resto.
#
#   UN MONDO SCURO, E BASTA.  Nessuna variante chiara: il sistema si dichiara
#   «full-bleed dark canvas throughout», e farne una versione bianca lo
#   distruggerebbe. Ogni colore è dipinto esplicitamente.
#
#   L'ELEVAZIONE È VALORE, NON OMBRA.  Tre livelli e nient'altro:
#   onice #171721 (la pagina) → grafite #1e1e2a (le schede) → obsidiana
#   #272735 (un gradino sopra: la fase in corso, le righe stimate).
#   Zero ombre in tutta la pagina, zero gradienti.
#
#   UN SOLO COBALTO, RAZIONATO.  Il #5266eb non è decorazione: marca DOVE SEI.
#   La settimana in corso nel grafico, la tacca di oggi sulla scala, la riga
#   del ritmo maratona, la zona 2. Nient'altro. Tutto il resto è grigio.
#
#   PESO 480.  Né grassetto né leggero. È la firma di Mercury, e Instrument
#   Sans è variabile quindi il 480 è un peso vero, non un arrotondamento.
#   Il display grande ha spaziatura POSITIVA (+0.015em), al contrario di
#   quasi tutti: è scritto nel sistema e si sente.
#
# Cosa ho aggiunto, e perché — il dettaglio sta in DESIGN.md:
#   · due semantici, ruotando la tinta del cobalto a parità di luminosità e
#     saturazione: allerta #ebd752 (il complementare esatto) e stop #eb7152;
#   · la scala delle cinque zone come rampa di solo VALORE sul cobalto, che è
#     il principio di Mercury applicato a una scala ordinata. La z2 esce
#     cobalto puro: la zona in cui deve vivere prende l'accento della pagina;
#   · --cobalto-testo #8290ed, perché il cobalto pieno sull'onice sta a
#     3,78:1 — va bene come riempimento, non come testo;
#   · --divisore #33333f, perché il bordo slate pieno a 1px è troppo presente
#     per un sistema che si dichiara «flat and borderless».
#
# I nomi delle classi vengono da prima e non li ho toccati (li genera il
# python): `.scarto--pino` e `.scarto--caldo` si chiamano ancora così, ma
# ora sono il cobalto e la cenere.

def _css():
    return """
*, *::before, *::after { box-sizing: border-box; }

:root {
  color-scheme: dark;   /* così l'host dipinge scuro anche barre e controlli */

  --onice:     #171721;
  --grafite:   #1e1e2a;
  --obsidiana: #272735;
  --bordo:     #70707d;
  --divisore:  #33333f;
  --cenere:    #c3c3cc;
  --avorio:    #ededf3;
  --cobalto:       #5266eb;
  --cobalto-testo: #8290ed;
  --bianco:    #ffffff;

  --allerta: #ebd752;
  --stop:    #eb7152;

  --z1: #4a5280;
  --z2: #5266eb;
  --z3: #8290ed;
  --z4: #b6bef1;
  --z5: #e5e7f5;

  --testo: 'Instrument Sans', Inter, ui-sans-serif, system-ui, sans-serif;

  --colonna: 40rem;   /* 640px, la colonna di contenuto di Mercury */
  --larga:   75rem;   /* 1200px, la sua larghezza massima */
  --ritmo:   4.5rem;  /* 72px fra le sezioni principali */

  --scheda:  12px;    /* raggio delle schede */
  --pillola: 32px;    /* «non negoziabile» */
  --strutt:  4px;
}

body {
  margin: 0;
  background: var(--onice);
  color: var(--avorio);
  font-family: var(--testo);
  font-size: 1rem;
  font-weight: 400;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.pagina { display: flex; flex-direction: column; gap: var(--ritmo); padding-bottom: 7.5rem; }

/* ── titoli e testo ─────────────────────────── */
/* Scala seconda maggiore (1.125) da 20px. I titoli stanno a 480, il display
   grande a 530 con spaziatura positiva. Mai il grassetto. */

h1, h2, h3 { text-wrap: balance; margin: 0; }

h1 {
  font-size: clamp(2.53rem, 8vw, 4.06rem);   /* 40.5 → 65px */
  font-weight: 530;
  line-height: 1.1;
  letter-spacing: 0.015em;
}

h2 {
  font-size: clamp(1.78rem, 4vw, 2.25rem);   /* 28.5 → 36px */
  font-weight: 480;
  line-height: 1.2;
  letter-spacing: 0.01em;
  margin-bottom: 0.5rem;
}

p { margin: 0 0 1rem; }
p:last-child { margin-bottom: 0; }
strong { font-weight: 480; }

.occhiello { font-size: 0.875rem; font-weight: 400; color: var(--cenere); margin-bottom: 1rem; }
.occhiello--chiaro { color: var(--cenere); margin-bottom: 1.5rem; }

.testata { width: min(100% - 2rem, var(--colonna)); margin: 5rem auto 0; }
.sottotitolo {
  font-size: 1.25rem; font-weight: 400; line-height: 1.5;
  color: var(--cenere); margin-top: 1.25rem; max-width: 34rem;
  margin-inline: auto;
}

.sezione { width: min(100% - 2rem, var(--colonna)); margin-inline: auto; }
.sezione--larga { width: min(100% - 2rem, var(--larga)); }
.sezione > p { color: var(--cenere); }
.sezione__intro { max-width: 38rem; margin-inline: auto; }
.nota { font-size: 0.875rem; color: var(--cenere); margin-top: 1.25rem; }

/* Titolo di terzo livello: peso intermedio, nessun maiuscoletto. */
.sotto { font-size: 1.11rem; font-weight: 480; color: var(--avorio); margin: 2rem 0 0; }

/* ── la scheda di stato ─────────────────────── */
/* Era una banda a tutta larghezza; in Mercury le superfici FLUTTUANO, quindi
   diventa la prima scheda di grafite della pagina. */

.banda {
  width: min(100% - 2rem, var(--larga));
  margin-inline: auto;
  background: var(--grafite);
  border-radius: var(--scheda);
  padding: 2rem;
}
.banda__interno { width: 100%; }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 2rem; }
.stat__v {
  font-size: 2.53rem;      /* 40.5px */
  font-weight: 480;
  line-height: 1.1;
  letter-spacing: 0.01em;
  font-variant-numeric: tabular-nums;
  margin: 0 0 0.25rem;
}
.stat__u { font-size: 0.99rem; font-weight: 400; color: var(--cenere); margin-left: 0.25rem; }
.stat__l { font-size: 0.875rem; color: var(--cenere); margin: 0; }
.stat__nota { font-size: 0.875rem; color: var(--cenere); margin: 0.5rem 0 0; }
.stat--ok .stat__v { color: var(--cobalto-testo); }
.stat--attenzione .stat__v { color: var(--allerta); }

/* ── tabelle ────────────────────────────────── */
/* Ogni tabella vive dentro la sua scheda di grafite: è il contenitore che
   già esisteva, quindi la pagina non è cambiata, solo il suo aspetto. */

.tabella-cont {
  overflow-x: auto;
  margin-top: 1.5rem;
  background: var(--grafite);
  border-radius: var(--scheda);
  padding: 2rem;
}
.tabella { width: 100%; border-collapse: collapse; font-size: 0.99rem; }
.tabella th, .tabella td {
  text-align: left; padding: 0.75rem 1rem 0.75rem 0;
  border-bottom: 1px solid var(--divisore);
}
.tabella thead th {
  font-size: 0.875rem; font-weight: 400; color: var(--cenere);
  border-bottom-color: var(--bordo);
}
.tabella tbody th { font-weight: 480; white-space: nowrap; }
.tabella .n { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.tabella .come { color: var(--cenere); font-size: 0.875rem; padding-left: 1.5rem; }
.tabella tfoot th, .tabella tfoot td {
  font-size: 0.875rem; color: var(--cenere);
  border-bottom: none; border-top: 1px solid var(--bordo);
}
.tabella tfoot .n { font-size: 0.99rem; font-weight: 480; color: var(--avorio); }
.tabella tbody tr:last-child th,
.tabella tbody tr:last-child td { border-bottom: none; }
/* Il cobalto marca la riga che conta: il ritmo maratona, la zona 2. */
.tabella .evidenza th, .tabella .evidenza td { color: var(--cobalto-testo); font-weight: 480; }
.tabella .evid { color: var(--cobalto-testo); font-weight: 480; }
/* Il dislivello che spiega i pezzi: in avorio pieno. Il colore resta al
   cobalto, e su una corsa in piano la colonna tace. */
.tabella .salita { color: var(--avorio); font-weight: 480; }
.tabella .vuota td, .tabella .vuota th { color: var(--cenere); }
/* Le righe stimate salgono di un gradino di valore, che in Mercury è il modo
   di dire «questo è un altro piano». La differenza fra un tempo misurato e
   uno calcolato è la cosa più importante di questa tabella. */
.tabella .stimata th, .tabella .stimata td { background: var(--obsidiana); }
.tabella .stimata th:first-child { border-radius: var(--strutt) 0 0 var(--strutt); }
.tabella .stimata td:last-child  { border-radius: 0 var(--strutt) var(--strutt) 0; }
.tabella th .chiave { display: inline-block; margin-right: 0.5rem; vertical-align: middle; }
.quando { font-size: 0.78rem; color: var(--cenere); margin-left: 0.5rem; }
.scarso { color: var(--cenere); }
/* Lo scarto: il cobalto solo a quello centrato. Quello che manca resta
   cenere — un obiettivo non ancora preso non è un allarme. */
.scarto--caldo { color: var(--cenere); }
.scarto--pino  { color: var(--cobalto-testo); font-weight: 480; }

/* ── grafico ────────────────────────────────── */
/* Le settimane fatte sono cenere; quella in corso è cobalto, perché il
   cobalto in Mercury vuol dire «qui». Le previste sono sagome slate. */

.grafico {
  margin: 1.5rem 0 0;
  background: var(--grafite);
  border-radius: var(--scheda);
  padding: 2rem;
}
.grafico svg { width: 100%; height: auto; display: block; overflow: visible; }
.barra { fill: var(--cenere); }
.barra--corso { fill: var(--cobalto); }
.barra--prevista { fill: none; stroke: var(--bordo); stroke-width: 1; stroke-dasharray: 3 3; }
.obiettivo { fill: none; stroke: var(--avorio); stroke-width: 1; stroke-dasharray: 5 4; opacity: 0.55; }
.griglia { stroke: var(--divisore); stroke-width: 1; }
.asse { font-size: 11px; fill: var(--cenere); }
.grafico figcaption { font-size: 0.875rem; color: var(--cenere); margin-top: 1.25rem; max-width: 34rem; margin-inline: auto; }

/* ── distribuzione delle zone ───────────────── */

.zone {
  margin-top: 1.5rem;
  background: var(--grafite);
  border-radius: var(--scheda);
  padding: 2rem;
}
.zone__testa { display: flex; flex-direction: column; }
.zone__v {
  font-size: 2.53rem; font-weight: 480; line-height: 1.1;
  letter-spacing: 0.01em; margin: 0; font-variant-numeric: tabular-nums;
}
.zone__v--ok { color: var(--cobalto-testo); }
.zone__v--attenzione { color: var(--allerta); }
.zone__v .stat__u { color: var(--cenere); font-size: 0.99rem; }
.zone__l { font-size: 0.875rem; color: var(--cenere); margin: 0.25rem 0 1.5rem; }

.barra-zone {
  display: flex; height: 12px; gap: 2px; overflow: hidden;
  background: var(--obsidiana); border-radius: var(--strutt);
}
.fetta--z1 { background: var(--z1); }
.fetta--z2 { background: var(--z2); }
.fetta--z3 { background: var(--z3); }
.fetta--z4 { background: var(--z4); }
.fetta--z5 { background: var(--z5); }

.legenda {
  list-style: none; margin: 1.25rem 0 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 0.5rem 1.5rem;
}
.legenda li { display: flex; align-items: center; gap: 0.625rem; font-size: 0.875rem; }
.chiave { width: 10px; height: 10px; border-radius: 2px; flex: none; }
.chiave--z1 { background: var(--z1); }
.chiave--z2 { background: var(--z2); }
.chiave--z3 { background: var(--z3); }
.chiave--z4 { background: var(--z4); }
.chiave--z5 { background: var(--z5); }
.legenda__n { color: var(--cenere); }
.legenda__v { font-variant-numeric: tabular-nums; color: var(--cenere); margin-left: auto; }

/* ── le due gare ────────────────────────────── */
/* Schede piatte, 12px, 32px di padding, nessuna ombra e nessun bordo:
   si staccano dall'onice solo perché sono più chiare. */

.gare { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: 1.5rem; margin-top: 1.5rem; }
.gara {
  background: var(--grafite); border-radius: var(--scheda); padding: 2rem;
  display: flex; flex-direction: column; gap: 0.25rem;
}
/* Il vocabolario a pillola di Mercury: qui non ci sono bottoni, quindi lo
   portano le etichette di ruolo e di stato. */
.gara__ruolo {
  align-self: center;
  font-size: 0.78rem; color: var(--cenere); margin: 0 0 0.75rem;
  padding: 0.25rem 0.75rem;
  background: var(--obsidiana); border-radius: var(--pillola);
}
.gara__nome { font-size: 1.58rem; font-weight: 480; line-height: 1.25; letter-spacing: 0.01em; margin: 0; }
.gara__data { font-size: 0.99rem; color: var(--cenere); margin: 0.5rem 0 0; }
.gara__conto { font-size: 0.875rem; color: var(--cenere); margin: 1.25rem 0 0; }
.gara__conto strong {
  display: block; font-size: 2.25rem; font-weight: 480; line-height: 1.1;
  letter-spacing: 0.01em; color: var(--avorio); font-variant-numeric: tabular-nums;
}
.gara__alt { font-size: 0.78rem; color: var(--cenere); margin-top: 0.5rem; }
.gara__nota { font-size: 0.875rem; color: var(--cenere); margin: 0.75rem 0 0; }

/* ── quanto corri di fila ───────────────────── */

.continua {
  margin-top: 1.5rem;
  background: var(--grafite); border-radius: var(--scheda); padding: 2rem 2rem 1rem;
}
.continua__v {
  font-size: clamp(3.21rem, 12vw, 4.06rem);   /* 51 → 65px */
  font-weight: 530; line-height: 1.1; letter-spacing: 0.015em;
  color: var(--avorio); font-variant-numeric: tabular-nums; margin: 0;
}
.continua__u { font-size: 1.11rem; font-weight: 400; color: var(--cenere); margin-left: 0.75rem; }
.continua__l { font-size: 0.875rem; color: var(--cenere); margin: 0.5rem 0 4.5rem; }

/* La scala verso i 42,195: la distanza fra dove sei e dove vai, in scala vera. */
.scala {
  position: relative; height: 8px; border-radius: var(--strutt);
  background: var(--obsidiana); margin-bottom: 5rem;
}
.scala__fatto { height: 100%; border-radius: var(--strutt); background: var(--cobalto); }
.tappa { position: absolute; top: -6px; transform: translateX(-50%); text-align: center; }
.tappa::before { content: ""; display: block; width: 1px; height: 20px; background: var(--bordo); margin: 0 auto; }
.tappa__v {
  display: block; font-size: 0.78rem; font-variant-numeric: tabular-nums;
  color: var(--cenere); margin-top: 0.5rem;
}
.tappa__l { display: block; font-size: 0.78rem; color: var(--cenere); margin-top: 0.125rem; white-space: nowrap; }
.tappa--ora::before { background: var(--cobalto); height: 28px; width: 2px; }
/* L'ultima tappa sta a 100%: centrata sborderebbe. La si ancora a destra,
   tenendo la tacca allineata al punto esatto. */
.tappa:last-child { transform: translateX(-100%); text-align: right; }
.tappa:last-child::before { margin: 0 0 0 auto; }
.tappa--ora .tappa__v { color: var(--cobalto-testo); font-weight: 480; }
.tappa--ora .tappa__l { color: var(--cobalto-testo); }

/* ── la settimana: una riga per seduta, con la spunta ── */

.tabella--settimana tbody th { font-size: 0.99rem; }
.spunta { width: 2rem; padding-right: 0.5rem !important; font-size: 0.99rem; color: var(--cobalto-testo); text-align: center; }
.spunta--vuota { color: var(--bordo); }
/* Le fatte restano leggibili ma arretrano: quello che serve a colpo d'occhio
   è cosa manca, non cosa è già archiviato. */
.tabella--settimana .fatta th,
.tabella--settimana .fatta td { color: var(--cenere); }
.tabella--settimana .evento .spunta { color: var(--allerta); }

/* ── il cartello del rientro ────────────────── */
/* Mercury documenta i filetti come unico bordo ammesso: un filo di allerta
   attorno alla scheda basta, senza barrette laterali. */

.avviso {
  background: var(--grafite); border: 1px solid var(--allerta);
  border-radius: var(--scheda); padding: 2rem; margin-top: 1.5rem;
}
.avviso__t { font-size: 1.41rem; font-weight: 480; line-height: 1.2; color: var(--allerta); margin: 0 0 0.75rem; }
.avviso__p { font-size: 0.875rem; color: var(--cenere); margin: 0 0 0.75rem; }
.avviso__r { font-size: 0.99rem; font-weight: 480; color: var(--avorio); margin: 0 0 0.5rem; }
.avviso--stop { border-color: var(--stop); }
.avviso--stop .avviso__t { color: var(--stop); }
/* I controlli da fare prima: sono il gesto che può risparmiare la corsa,
   quindi stanno in evidenza come la regola, non fra le note. */
.avviso__prima {
  font-size: 0.875rem; color: var(--avorio); margin: 0 0 0.75rem;
  padding: 1rem; background: var(--obsidiana); border-radius: var(--strutt);
}
.avviso__c {
  font-size: 0.875rem; color: var(--cenere); margin: 0.75rem 0 0;
  padding-top: 0.75rem; border-top: 1px solid var(--divisore);
}
.avviso__v { font-size: 0.78rem; color: var(--cenere); margin: 0; }

/* ── i giorni della settimana ───────────────── */
/* Una scheda sola, divisa da filetti: niente bordi attorno a ogni riga. */

.giorni {
  list-style: none; margin: 1.5rem 0 0; padding: 0;
  background: var(--grafite); border-radius: var(--scheda); overflow: hidden;
}
.g {
  padding: 1rem 2rem; min-height: 3rem;
  display: grid; grid-template-columns: 3.5rem 1fr auto; gap: 1rem; align-items: baseline;
  border-bottom: 1px solid var(--divisore);
}
.giorni .g:last-child { border-bottom: none; }
.g__d { font-size: 0.875rem; color: var(--cenere); font-variant-numeric: tabular-nums; }
.g__t { font-weight: 480; font-size: 0.99rem; }
.g__n { display: block; font-weight: 400; font-size: 0.875rem; color: var(--cenere); margin-top: 0.25rem; }
/* Anche gli stati sono pillole. */
.g__s {
  font-size: 0.78rem; color: var(--cobalto-testo); white-space: nowrap;
  padding: 0.125rem 0.625rem; border-radius: var(--pillola); background: var(--obsidiana);
}
.g__s--todo { color: var(--cenere); }
.g__s--test { color: var(--allerta); }
.g--fatto .g__t, .g--fatto .g__d { color: var(--cenere); }
.g--test { background: var(--obsidiana); }

@media (max-width: 40rem) {
  .g { grid-template-columns: 3rem 1fr; padding: 1rem 1.25rem; }
  .g__s { grid-column: 2; justify-self: start; }
  .tappa__l { display: none; }
}

/* ── le fasi ────────────────────────────────── */
/* La fase in corso non cambia colore: sale di un gradino di valore. È come
   Mercury dice «questa è in primo piano», senza ombre e senza bordi. */

.fasi { display: grid; grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr)); gap: 1.5rem; margin-top: 1.5rem; }
.fase {
  background: var(--grafite); border-radius: var(--scheda); padding: 2rem;
  display: flex; flex-direction: column; gap: 1.25rem;
}
.fase--ora { background: var(--obsidiana); }
.fase--fatta .fase__nome, .fase--fatta .fase__scopo { color: var(--cenere); }
/* .fase--dopo non ha regole di proposito: la fase da fare È la scheda
   neutra. Il gradino di valore dice «qui sei», la cenere «questa è chiusa». */

.fase__testa { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; }
.fase__num { font-size: 0.875rem; color: var(--cenere); margin: 0; }
.fase__nome { font-size: 1.58rem; font-weight: 480; line-height: 1.25; letter-spacing: 0.01em; }
.fase__tag {
  font-size: 0.78rem; color: var(--cenere); margin: 0.25rem 0 0;
  padding: 0.25rem 0.75rem; border-radius: var(--pillola); background: var(--grafite);
}
.fase--ora .fase__tag { background: var(--cobalto); color: var(--bianco); }
.fase__scopo { font-size: 0.875rem; color: var(--cenere); margin: 0; }

.fase__dati { display: flex; gap: 2rem; margin: 0; }
.fase__dati dt { font-size: 0.78rem; color: var(--cenere); }
.fase__dati dd { font-size: 0.99rem; font-weight: 480; margin: 0.25rem 0 0; font-variant-numeric: tabular-nums; }

.cancello { border-top: 1px solid var(--divisore); padding-top: 1.25rem; margin-top: auto; }
.cancello__testo { font-size: 0.875rem; color: var(--cenere); margin: 0; }
.cancello__stato { font-size: 0.875rem; font-weight: 480; margin: 0 0 0.75rem; }
.cancello__stato--aperto { color: var(--cobalto-testo); }
.cancello__stato--chiuso { color: var(--cenere); }

.criteri { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; }
.criterio { font-size: 0.875rem; padding-left: 1.5rem; position: relative; }
.criterio::before { position: absolute; left: 0; top: 0; }
.criterio--si::before    { content: "✓"; color: var(--cobalto-testo); }
.criterio--no::before    { content: "✗"; color: var(--stop); }
.criterio--forse::before { content: "–"; color: var(--cenere); }
.criterio__t { display: block; }
.criterio__d { display: block; font-size: 0.78rem; color: var(--cenere); margin-top: 0.25rem; }

/* ── chiusura ───────────────────────────────── */

.chiusura {
  width: min(100% - 2rem, var(--colonna));
  margin-inline: auto;
  border-top: 1px solid var(--divisore);
  padding-top: 1.5rem;
  font-size: 0.78rem;
  color: var(--cenere);
}
code { font-size: 0.9em; color: var(--avorio); }

a { color: var(--cobalto-testo); text-decoration: underline; text-underline-offset: 2px; }
a:hover { color: var(--z4); }

:focus-visible { outline: 2px solid var(--cobalto-testo); outline-offset: 2px; }

/* ── titoli centrati ───────────────────────── */
/* Chiesto da Sasha il 29/09/2026, commentando la pagina: «fai tutti questi
   titoli mettili centrali». Mercury lo prevede — il suo eroe è un «centered
   content stack» — quindi il gesto sta dentro il sistema.
   Centro i titoli e il testo che appartiene a loro: occhielli, sottotitolo,
   introduzioni, note, didascalie. NON centro quello che si legge per righe
   allineate: le tabelle, l'elenco dei criteri, i due dati delle fasi. */

.testata, h2, .sotto, .sezione > p, .chiusura, .avviso__t { text-align: center; }

.banda__interno { text-align: center; }
.gara { text-align: center; }
.fase__testa { text-align: center; }
.continua__v, .continua__u, .continua__l { text-align: center; }
.zone__testa { text-align: center; }

/* Le colonne di cifre restano allineate: il centrato le sfalserebbe. */
.fase__dati, .criteri, .legenda { text-align: left; }

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}

@media (max-width: 40rem) {
  .stat__v, .zone__v { font-size: 2rem; }
  .tabella .come { display: none; }
  .fase__dati { flex-direction: column; gap: 0.75rem; }
  /* 32px di padding su un telefono da 400px lasciano poco al contenuto. */
  .banda, .tabella-cont, .grafico, .zone, .gara, .fase, .avviso, .continua { padding: 1.25rem; }
}
"""
