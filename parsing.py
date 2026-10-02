"""Riceve dati grezzi ottenuti da bot.py dall'utente, li normalizza e li converte in tipi Python utilizzabili."""

from datetime import timedelta


def normalizza_testo(testo) -> str:
    """Rende il testo maiuscolo e senza spazi (anche quelli interni)"""
    testo_pulito = testo.strip().upper().replace(" ", "")
    return testo_pulito


def converti_mesi(n_mesi, oggi):
    """Restituisce la data limite"""
    data_limite = oggi + timedelta(days=30 * n_mesi)
    return data_limite
