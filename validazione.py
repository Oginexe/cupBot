"""Funzioni di validazione per i dati di tracciamento: codice fiscale e numero ricetta"""


def valida_codice_fiscale(testo) -> bool:
    """Un codice fiscale valido ha 16 caratteri alfanumerici, di cui 7 sono numeri e 9 sono lettere. Restituisce True/False"""
    if not testo.isalnum() or len(testo) != 16:
        return False
    caratteri = ""
    numeri = ""
    for c in testo:
        if c.isalpha():
            caratteri += c
        if c.isdigit():
            numeri += c
    return len(caratteri) == 9 and len(numeri) == 7


def valida_numero_ricetta(testo) -> bool:
    """Un numero ricetta valido ha 15 caratteri alfanumerici. Restituisce True/False"""
    return testo.isalnum() and len(testo) == 15
