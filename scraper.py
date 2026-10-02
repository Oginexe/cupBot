"""
Questo modulo si occupa di cercare nel sito CUP Sardegna gli appuntamenti usando la libreria playwright, e in base ai dati inseriti ed alle condizioni di filtraggio, filtra e restituisce una lista dei risultati filtrati.
"""

# Import di librerie built-in e third party
from datetime import date

from playwright.sync_api import sync_playwright

from dizionari import MESI, VALUES


class ErroreBannerCUP(Exception):
    """Classe dell'errore-banner che viene generato dal sito CUP Sardegna ogni volta che occorre un errore"""


def cerca_appuntamento(codice_fiscale, numero_ricetta, area, provincia):
    """Sulla base dei dati inseriti cerca appuntamenti disponibili in base alle condizioni precedentemente indicate restituendo una lista di appuntamenti grezza, da raffinare"""
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(120000)
        page.goto("https://cupweb.sardegnasalute.it/web/guest/ricetta-elettronica")
        # Chiude il banner dei cookies per evitare interferenze bel funzionamento del programma
        page.locator('button[class*="js-cookieBarAccept"]').click()
        # Il sito chiede l'inserimento del codice fiscale
        page.locator(
            'input[name="_ricettaelettronica_WAR_cupprenotazione_:ePrescriptionSearchForm:CFInput"]'
        ).fill(codice_fiscale)
        # Il sito chiede l'inserimento del numero della ricetta
        page.locator(
            'input[name="_ricettaelettronica_WAR_cupprenotazione_:ePrescriptionSearchForm:nreInput0"]'
        ).fill(numero_ricetta)
        # Selezione area e provincia - salvo i dati in variabili per rendere più leggibile il codice
        area_html = 'select[name="_ricettaelettronica_WAR_cupprenotazione_:ePrescriptionSearchForm:macrozonaDropDown_input"]'
        provincia_html = 'select[name="_ricettaelettronica_WAR_cupprenotazione_:ePrescriptionSearchForm:zonaDropDown_input"]'
        # Area e provincia sono specificate
        if area is not None and provincia is not None:
            area_value = VALUES[area]
            provincia_value = VALUES[provincia]
            page.locator(area_html).select_option(value=f"{area_value}")
            page.wait_for_timeout(3000)
            page.locator(provincia_html).select_option(value=f"{provincia_value}")
        # Area è specificata ma provincia no
        elif area is not None and provincia is None:
            area_value = VALUES[area]
            page.locator(area_html).select_option(value=area_value)
        # Default se né area né provincia sono specificate
        # Click bottone Avanti
        page.wait_for_timeout(3000)
        page.locator(
            'button[name="_ricettaelettronica_WAR_cupprenotazione_:ePrescriptionSearchForm:nreButton_button"]'
        ).click()

        # La pagina genera un banner se capita un errore
        selettore_errore = 'div[class*="alert-danger"]'
        # Altrimenti genera la pagina con il bottone Avanti
        selettore_successo = 'button[name="_ricettaelettronica_WAR_cupprenotazione_:navigation-prestazioni-under:prestazioni-nextButton-under__button"]'

        # Verifico se risponde con successo o se genera un banner di errore
        aspetta_o_fallisci(page, selettore_successo, selettore_errore)

        # Altro click bottone Avanti
        page.locator(
            'button[name="_ricettaelettronica_WAR_cupprenotazione_:navigation-prestazioni-under:prestazioni-nextButton-under__button"]'
        ).click()

        # Apre "altri appuntamenti" così da avere una lista completa
        page.get_by_role("button", name="Altri appuntamenti disponibili").first.click()

        # Lista gli appuntamenti disponibili ma prima controlla se viene generato qualche errore
        selettore_successo = 'div[class*="disponibiliContainer"]'
        aspetta_o_fallisci(page, selettore_successo, selettore_errore)
        page.locator('div[class*="disponibiliContainer"]').wait_for()
        cards = (
            page.locator('div[class*="disponibiliContainer"]')
            .locator('div[class*="disponibiliPanel"]')
            .all()
        )
        lista_appuntamenti = []
        for card in cards:
            spans = (
                card.locator('div[class*="captionAppointment-dateApp"]')
                .locator("span")
                .all()
            )
            luogo = (
                card.locator("div.unita-address")
                .last.locator("span")
                .nth(1)
                .inner_text()
            )
            luogo = luogo.strip().removeprefix("- ")
            appuntamento = {
                "Data": spans[0].inner_text(),
                "Ora": spans[2].inner_text(),
                "Luogo": luogo,
            }
            lista_appuntamenti.append(appuntamento)
        browser.close()
        return lista_appuntamenti


def aspetta_o_fallisci(page, selettore_successo, selettore_errore):
    """Aspetta che compaia uno tra i due possibili elementi per valutare il successo o errore. Se compare il selettore di errore, solleva ErroreBannerCUP con il messaggio letto dalla pagina"""
    page.locator(f"{selettore_successo}, {selettore_errore}").first.wait_for()
    if page.locator(selettore_errore).count() > 0:
        messaggio = page.locator(selettore_errore).inner_text()
        raise ErroreBannerCUP(f"Errore: {messaggio}")


def filtra_appuntamenti(data_limite, lista_appuntamenti):
    """Raffina la lista degli appuntamenti sulla base di un confronto di date. Restituisce una lista filtrata che corrisponde ai limiti temporali imposti."""
    appuntamenti_filtrati = []
    for appuntamento in lista_appuntamenti:
        parti_appuntamento = appuntamento["Data"].split()
        mese_numero = MESI[parti_appuntamento[2].upper()]
        data_appuntamento = date(
            int(parti_appuntamento[3]), mese_numero, int(parti_appuntamento[1])
        )
        if data_appuntamento <= data_limite:
            appuntamenti_filtrati.append(appuntamento)

    return appuntamenti_filtrati
