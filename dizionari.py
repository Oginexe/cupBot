"""Dizionari di configurazione: mesi, codici del sito per aree e province ed aree disponibili."""

# Dizionario che mappa mesi dell'anno con i valori del mese corrispondente
MESI = {
    "GENNAIO": 1,
    "FEBBRAIO": 2,
    "MARZO": 3,
    "APRILE": 4,
    "MAGGIO": 5,
    "GIUGNO": 6,
    "LUGLIO": 7,
    "AGOSTO": 8,
    "SETTEMBRE": 9,
    "OTTOBRE": 10,
    "NOVEMBRE": 11,
    "DICEMBRE": 12,
}

# Dizionario che mappa la corrispondenza tra aree "visibili" disponibili e i selettori web delle aree
VALUES = {
    "NORD SARDEGNA": "MZ_NORD",
    "CENTRO SARDEGNA": "MZ_CENT",
    "SUD SARDEGNA": "MZ_SUD",
    "SASSARI": "ZN_SS",
    "GALLURA": "ZN_OT",
    "NUORO": "ZN_NU",
    "OGLIASTRA": "ZN_OG",
    "ORISTANO": "ZN_OR",
    "MEDIO CAMPIDANO": "ZN_VS",
    "SULCIS": "ZN_CI",
    "CAGLIARI": "ZN_CA",
}

# Dizionario con liste di valori per filtrare la ricerca con le aree e province disponibili
AREE_DISPONIBILI = {
    "NORD SARDEGNA": ["SASSARI", "GALLURA"],
    "CENTRO SARDEGNA": ["NUORO", "OGLIASTRA", "ORISTANO"],
    "SUD SARDEGNA": ["MEDIO CAMPIDANO", "SULCIS", "CAGLIARI"],
}
