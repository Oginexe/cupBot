"""Modulo contenente funzioni che dato un tracciamento e l'istante attuale, dicono se è l'ora di controllarlo."""

import random
from datetime import timedelta

MARGINE_MINUTI = 10
JITTER_SECONDI = 300
PAUSA_MIN_SECONDI = 30
PAUSA_MAX_SECONDI = 40


def fascia_attuale(adesso, fascia_inizio, fascia_fine) -> tuple | None:
    """Restituisce (inizio, fine) della fascia oraria che contiene 'adesso'; oppure None se 'adesso' è fuori dalla fascia. L'inizio è incluso e la fine è esclusa"""
    durata = (fascia_fine - fascia_inizio) % 24
    inizio = adesso.replace(hour=fascia_inizio, minute=0, second=0, microsecond=0)
    if inizio > adesso:
        inizio -= timedelta(days=1)
    fine = inizio + timedelta(hours=durata)
    if adesso >= inizio and adesso < fine:
        return inizio, fine
    else:
        return None


def deve_controllare(tracciamento, adesso) -> bool:
    """Verifica se il tracciamento dev'essere controllato nell'istante 'adesso'"""
    ogni_ore = tracciamento["ogni_ore"]
    fascia_inizio = tracciamento["fascia_inizio"]
    fascia_fine = tracciamento["fascia_fine"]
    ultimo_controllo = tracciamento["ultimo_controllo"]
    margine = timedelta(minutes=MARGINE_MINUTI)
    fascia = fascia_attuale(adesso, fascia_inizio, fascia_fine)
    if fascia is None:
        return False
    inizio, fine = fascia
    if adesso < inizio + margine:
        return False
    if ultimo_controllo is None:
        return True
    if ultimo_controllo < inizio + margine:
        return True
    if adesso >= fine - margine and ultimo_controllo < fine - margine:
        return True
    return adesso - ultimo_controllo >= timedelta(hours=ogni_ore)


def da_controllare(tracciamenti, adesso) -> list:
    """Restituisce i tracciamenti per cui deve controllare. Se nessuno è True, restituisce una lista vuota."""
    lista_da_controllare = []
    for tracciamento in tracciamenti:
        if deve_controllare(tracciamento, adesso):
            lista_da_controllare.append(tracciamento)

    return lista_da_controllare


def pausa_tra_controlli() -> float:
    """Secondi casuali di attesa tra un controllo ed un successivo"""
    return random.uniform(PAUSA_MIN_SECONDI, PAUSA_MAX_SECONDI)


def ritardo_iniziale() -> int:
    """Secondi casuali da attendere prima di un controllo automatico. Deve restare sotto MARGINE_MINUTI, altrimenti il controllo di chiusura potrebbe cadere fuori fascia."""
    return random.randint(0, JITTER_SECONDI)
