---
name: Mercury
fonte: https://styles.refero.design/style/3172cd4d-118a-4a16-a259-6b634d32322e
letto: 2026-09-29
descrizione: >
  «Alpine banking at blue hour». Tela quasi nera che crea un'atmosfera
  cinematografica, da osservatorio, dove le superfici di contenuto fluttuano
  come schede di grafite appena più chiare. Interfaccia marcatamente
  monocromatica, testo avorio su fondo scuro, punteggiata esclusivamente da un
  solo cobalto riservato all'azione principale. La tipografia usa pesi
  intermedi (480 per i display, 400 per il testo) che danno sicurezza senza
  aggressività. I componenti sono piatti e senza bordi: contano sull'elevazione
  della scheda e sui controlli a pillola, non sulle ombre.

colori:
  onice:      "#171721"   # fondo pagina
  grafite:    "#1e1e2a"   # superfici elevate, schede
  obsidiana:  "#272735"   # bottoni secondari, fondo dei campi
  bordo:      "#70707d"   # divisori, bordi strutturali
  bordo-2:    "#e2e3ed"   # filetti, bottoni fantasma
  cenere:     "#c3c3cc"   # testo attenuato, aiuti
  avorio:     "#ededf3"   # testo principale, icone
  cobalto:    "#5266eb"   # UNICO riempimento dell'azione principale
  bianco:     "#ffffff"   # testo sul cobalto

tipografia:
  corpo:    { famiglia: Arcadia,         pesi: [360, 400, 420, 480], fallback: Inter }
  display:  { famiglia: Arcadia Display, pesi: [360, 480, 530],      fallback: "Söhne Breit" }
  scala:    "seconda maggiore (1.125) da 20px, da 12px a 65px"
  base:     "16px peso 400, interlinea 1.5"
  display-grande: "65px peso 480, interlinea 1.1, spaziatura +0.01/+0.02em"

impaginazione:
  larghezza-max: 1200px
  colonna:       640px
  ritmo:         72px fra le sezioni principali
  scheda:        { raggio: 12px, padding: 32px, ombra: nessuna }
  pillola:       "32-40px su bottoni e campi — non negoziabile"
  strutturale:   4px

firme:
  - Elevazione SENZA ombre: solo contrasto di valore (grafite sull'onice).
  - Disciplina cromatica: il cobalto è l'unico accento, tutto il resto è grigio.
  - Peso 480 sui titoli: «né grassetto né leggero».
  - Navigazione trasparente sull'eroe, vetro smerigliato allo scroll.
---

# Quello che ho aggiunto io

Mercury è monocromatico più un cobalto, e questa pagina ha bisogno di due
cose che il sistema non dà. Le ho ricavate dal cobalto stesso invece di
inventarle, così restano dentro il suo mondo. Il cobalto sta a tinta 232°,
luminosità 0,62, saturazione 0,79.

## I due colori semantici

Ruotando la tinta del cobalto e tenendo identiche luminosità e saturazione:

    allerta   #ebd752   +180°, il complementare esatto   12,2:1 sull'onice
    stop      #eb7152   +140°                             5,9:1 sull'onice

## La scala delle cinque zone cardiache

Una rampa di **solo valore** sul cobalto, che è esattamente il principio di
Mercury («all elevation communicated through value contrast alone») applicato
a una scala ordinata. Più chiaro = più intenso. La z2 esce cobalto puro: la
zona in cui deve vivere prende l'accento della pagina.

    z1  #4a5280      z2  #5266eb      z3  #8290ed
    z4  #b6bef1      z5  #e5e7f5

ΔE fra adiacenti: 50,8 · 29,3 · 29,3 · 24,5 — la peggiore è a 24,5, ben oltre
i ~15 che servono per distinguere due caselle accanto.

## Due token di servizio

    cobalto-testo  #8290ed   il cobalto puro su onice sta a 3,78:1: va bene
                             come RIEMPIMENTO, non come testo. Questo è la z3
                             della rampa e sta a 6,06:1.
    divisore       #33333f   interpolato fra obsidiana e bordo: il #70707d
                             pieno come filetto da 1px è troppo presente per
                             un sistema che si dichiara «flat and borderless».

## Il tema

Mercury è un mondo **dichiaratamente scuro** («full-bleed dark canvas
throughout»). La pagina quindi è a tema unico: niente variante chiara, e ogni
colore dipinto in modo esplicito perché tenga su qualsiasi fondo dell'host.

## I font

Arcadia e Arcadia Display sono proprietari. Fallback documentato: Inter.
Uso **Instrument Sans** da Google Fonts, che è variabile e regge i pesi
intermedi veri del sistema (400 per il corpo, 480 per i titoli, 530 per il
display) — il motivo per cui Mercury li usa. Il sistema non prevede un
monospaziato: i numeri stanno in Instrument Sans con `tabular-nums`.
