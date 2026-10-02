"""Modulo che salva e legge i tracciamenti in un file JSON."""

import json
import os
from datetime import date, datetime
from pathlib import Path

PERCORSO_TRACCIAMENTI = Path(__file__).parent / "data" / "tracciamenti.json"


class ErroreStorage(Exception):
    """Il file dei tracciamenti è vuoto o non è un JSON valido"""


class RicettaGiaPresente(Exception):
    """Il numero di ricetta è già presente nel file"""


def leggi_tracciamenti() -> list:
    """Legge i tracciamenti dal file e restituisce una lista di dizionari. Converte data_limite in date e ultimo_controllo in datetime (o None). Se il file non esiste restituisce []. Se è vuoto o non è JSON valido solleva ErroreStorage."""
    try:
        with open(PERCORSO_TRACCIAMENTI, "r", encoding="utf-8") as f:
            try:
                tracciamenti = json.load(f)
            except json.JSONDecodeError:
                raise ErroreStorage("Il file tracciamenti.json è vuoto o non valido")
    except FileNotFoundError:
        return []

    for tracciamento in tracciamenti:
        tracciamento["data_limite"] = date.fromisoformat(tracciamento["data_limite"])
        tracciamento["ultimo_controllo"] = _testo_in_datetime(
            tracciamento["ultimo_controllo"]
        )

    return tracciamenti


def aggiungi_tracciamento(tracciamento):
    """Aggiunge un tracciamento al file. Riceve un dizionario con le date come oggetti date/datetime. Se esiste già un tracciamento con lo stesso numero_ricetta solleva RicettaGiaPresente e il file non viene modificato."""
    lista = leggi_tracciamenti()
    if any(tracciamento["numero_ricetta"] == t["numero_ricetta"] for t in lista):
        raise RicettaGiaPresente(tracciamento["numero_ricetta"])
    lista.append(tracciamento)
    _salva(lista)


def rimuovi_tracciamento(numero_ricetta):
    """Rimuove il tracciamento con il numero ricetta indicato. Se il numero di ricetta non esiste, la funzione non fa nulla e non solleva eccezioni"""
    lista = leggi_tracciamenti()
    nuova_lista = [t for t in lista if t["numero_ricetta"] != numero_ricetta]
    _salva(nuova_lista)


def aggiorna_ultimo_controllo(numero_ricetta, quando):
    """Dopo ogni controllo scrive l'istante in cui è avvenuto, nel file. Se il numero di ricetta non esiste non fa nulla."""
    lista_tracciamenti = leggi_tracciamenti()
    for tracciamento in lista_tracciamenti:
        if tracciamento["numero_ricetta"] == numero_ricetta:
            tracciamento["ultimo_controllo"] = quando
    _salva(lista_tracciamenti)


def _salva(tracciamenti):
    """Scrive la lista di tracciamenti nel file in modo sicuro. Converte le date in testo ISO su copie dei dizionari (gli originali non vengono modificati), scrive su un file temporaneo con permessi 0o600 e lo sostituisce al file vero con os.replace, così il file non resta mai a metà."""
    lista_da_scrivere = []
    for tracciamento in tracciamenti:
        copia_tracciamento = dict(tracciamento)
        copia_tracciamento["data_limite"] = _data_in_testo(tracciamento["data_limite"])
        copia_tracciamento["ultimo_controllo"] = _data_in_testo(
            tracciamento["ultimo_controllo"]
        )
        lista_da_scrivere.append(copia_tracciamento)
    testo = json.dumps(lista_da_scrivere, indent=2, ensure_ascii=False)

    PERCORSO_TRACCIAMENTI.parent.mkdir(parents=True, exist_ok=True)
    output_temporaneo = PERCORSO_TRACCIAMENTI.with_suffix(".json.tmp")

    with open(output_temporaneo, "w", encoding="utf-8") as f:
        f.write(testo)

    output_temporaneo.chmod(0o600)
    os.replace(output_temporaneo, PERCORSO_TRACCIAMENTI)


def _data_in_testo(d):
    """Converte una date o un datetime in testo ISO. None resta None."""
    if d is not None:
        return d.isoformat()
    else:
        return None


def _testo_in_datetime(t):
    """Converte un testo ISO in datetime. None resta None."""
    if t is not None:
        return datetime.fromisoformat(t)
    else:
        return None
