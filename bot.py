import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import InvalidToken, NetworkError, TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from dizionari import AREE_DISPONIBILI
from parsing import converti_mesi, normalizza_testo
from scheduler import (
    da_controllare,
    deve_controllare,
    pausa_tra_controlli,
    ritardo_iniziale,
)
from scraper import ErroreBannerCUP, cerca_appuntamento, filtra_appuntamenti
from storage import (
    ErroreStorage,
    RicettaGiaPresente,
    aggiorna_ultimo_controllo,
    aggiungi_tracciamento,
    leggi_tracciamenti,
    rimuovi_tracciamento,
)
from validazione import valida_codice_fiscale, valida_numero_ricetta

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

# Ogni costante identifica un punto del flusso "Aggiungi"
(
    CF,
    RICETTA,
    VUOLE_AREA,
    AREA,
    VUOLE_PROVINCIA,
    PROVINCIA,
    MESI,
    FREQUENZA,
    ORA_INIZIO,
    ORA_FINE,
    RIEPILOGO,
) = range(11)

MAX_APPUNTAMENTI_MESSAGGIO = 10  # per non superare il limite di Telegram sul testo


def carica_configurazione() -> tuple[str, int]:
    """Legge token e ID autorizzato dal .env. Solleva SystemExit con un messaggio chiaro se mancano o sono malformati."""
    load_dotenv()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Manca TELEGRAM_BOT_TOKEN nel file .env")

    grezzo = os.environ.get("ALLOWED_ID", "").strip()
    if not grezzo:
        raise SystemExit("Manca ALLOWED_ID nel file .env")
    try:
        allowed_id = int(grezzo)
    except ValueError:
        raise SystemExit("ALLOWED_ID deve essere un solo numero: il tuo ID Telegram")

    return token, allowed_id


async def controllo_autorizzazione(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Gira PRIMA di ogni altro handler, per qualsiasi tipo di update."""
    utente = update.effective_user
    if utente is not None and utente.id == context.bot_data["allowed_id"]:
        return  # autorizzato: l'update prosegue verso gli handler normali

    log.warning("Accesso non autorizzato: id=%s", utente.id if utente else None)

    if update.callback_query:
        await update.callback_query.answer("Non sei autorizzato.", show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text("Non sei autorizzato.")

    raise ApplicationHandlerStop  # blocca l'update: nessun altro handler lo vedrà


async def dettaglio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    # "dettaglio:ABC123..." -> "ABC123..."
    numero_ricetta = query.data.split(":", 1)[1]
    trovato = next(
        (t for t in leggi_tracciamenti() if t["numero_ricetta"] == numero_ricetta),
        None,
    )
    if trovato is None:
        await query.edit_message_text(
            "Tracciamento non trovato.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Indietro", callback_data="elenca")]]
            ),
        )
        return

    testo = (
        f"Ricetta: {trovato['numero_ricetta']}\n"
        f"Codice fiscale: {trovato['codice_fiscale']}\n"
        f"Area: {trovato['area'] or 'tutta la Sardegna'}\n"
        f"Provincia: {trovato['provincia'] or 'tutte'}\n"
        f"Cerca entro il: {trovato['data_limite'].strftime('%d/%m/%Y')}\n"
        f"Controllo ogni: {trovato['ogni_ore']} ore\n"
        f"Fascia oraria: {trovato['fascia_inizio']:02d}:00-{trovato['fascia_fine']:02d}:00"
    )
    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 Controlla ora", callback_data=f"controlla:{numero_ricetta}"
                )
            ],
            [
                InlineKeyboardButton("⬅️ Indietro", callback_data="elenca"),
                InlineKeyboardButton(
                    "🗑 Rimuovi", callback_data=f"elimina:{numero_ricetta}"
                ),
            ],
        ]
    )
    await query.edit_message_text(testo, reply_markup=tastiera)


async def elimina(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    numero_ricetta = query.data.split(":", 1)[1]
    rimuovi_tracciamento(numero_ricetta)
    menu = tastiera_menu(bool(leggi_tracciamenti()))
    await query.edit_message_text(
        f"Tracciamento {numero_ricetta} rimosso.\n\nCosa vuoi fare?",
        reply_markup=menu,
    )


def tastiera_menu(ha_tracciamenti: bool) -> InlineKeyboardMarkup:
    """Costruisce il menu. Elenca e Rimuovi compaiono solo se esiste almeno un tracciamento."""
    righe = [
        [InlineKeyboardButton("➕ Aggiungi tracciamento", callback_data="aggiungi")]
    ]
    if ha_tracciamenti:
        righe.append(
            [InlineKeyboardButton("📋 Elenca tracciamenti", callback_data="elenca")]
        )
        righe.append(
            [InlineKeyboardButton("🗑 Rimuovi tracciamento", callback_data="rimuovi")]
        )
    return InlineKeyboardMarkup(righe)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    messaggio = update.effective_message
    if messaggio is None:
        return
    menu = tastiera_menu(bool(leggi_tracciamenti()))
    await messaggio.reply_text("Cosa vuoi fare?", reply_markup=menu)


async def elenca(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    tracciamenti = leggi_tracciamenti()
    if not tracciamenti:
        testo = "Nessun tracciamento attivo."
        righe = []
    else:
        testo = "Scegli un tracciamento:"
        # Un bottone per riga; il numero ricetta viaggia dentro il callback_data
        righe = [
            [
                InlineKeyboardButton(
                    t["numero_ricetta"],
                    callback_data=f"dettaglio:{t['numero_ricetta']}",
                )
            ]
            for t in tracciamenti
        ]
    righe.append([InlineKeyboardButton("⬅️ Indietro", callback_data="menu")])
    await query.edit_message_text(testo, reply_markup=InlineKeyboardMarkup(righe))


async def scegli_da_rimuovere(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    tracciamenti = leggi_tracciamenti()
    if not tracciamenti:
        testo = "Nessun tracciamento attivo."
        righe = []
    else:
        testo = "Quale tracciamento vuoi rimuovere?"
        # callback_data "elimina:..." è lo stesso usato dal bottone Rimuovi del dettaglio
        righe = [
            [
                InlineKeyboardButton(
                    t["numero_ricetta"],
                    callback_data=f"elimina:{t['numero_ricetta']}",
                )
            ]
            for t in tracciamenti
        ]
    righe.append([InlineKeyboardButton("⬅️ Indietro", callback_data="menu")])
    await query.edit_message_text(testo, reply_markup=InlineKeyboardMarkup(righe))


async def torna_al_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    menu = tastiera_menu(bool(leggi_tracciamenti()))
    await query.edit_message_text("Cosa vuoi fare?", reply_markup=menu)


def tastiera_si_no_area() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Sì", callback_data="area_si"),
                InlineKeyboardButton("No, tutta la Sardegna", callback_data="area_no"),
            ],
            [InlineKeyboardButton("❌ Annulla", callback_data="annulla")],
        ]
    )


def tastiera_aree() -> InlineKeyboardMarkup:
    # Un bottone per ogni area, generato dal dizionario
    righe = [
        [InlineKeyboardButton(area, callback_data=f"area:{area}")]
        for area in AREE_DISPONIBILI
    ]
    righe.append([InlineKeyboardButton("❌ Annulla", callback_data="annulla")])
    return InlineKeyboardMarkup(righe)


async def sceglie_si_no_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return VUOLE_AREA
    await query.answer()

    if query.data == "area_no":
        dati_utente(context)["area"] = None
        dati_utente(context)["provincia"] = None
        return await chiede_mesi(query)

    await query.edit_message_text("Scegli un'area:", reply_markup=tastiera_aree())
    return AREA


async def sceglie_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return AREA
    await query.answer()

    area = query.data.split(":", 1)[1]
    dati_utente(context)["area"] = area
    await query.edit_message_text(
        f"Area: {area}\n\nVuoi cercare in una provincia specifica?",
        reply_markup=tastiera_si_no_provincia(),
    )
    return VUOLE_PROVINCIA


def tastiera_annulla() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Annulla", callback_data="annulla")]]
    )


def dati_utente(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Restituisce user_data; l'autorizzazione garantisce che esista."""
    if context.user_data is None:
        raise RuntimeError("user_data non disponibile: update senza utente")
    return context.user_data


async def aggiungi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: parte quando premi 'Aggiungi tracciamento'."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    dati_utente(context).clear()  # scarta eventuali dati di un flusso interrotto
    await query.edit_message_text(
        "Inserisci il codice fiscale:", reply_markup=tastiera_annulla()
    )
    return CF


async def riceve_cf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    messaggio = update.effective_message
    if messaggio is None or messaggio.text is None:
        return CF
    # Normalizzazione: la validazione presuppone testo già in maiuscolo e senza spazi
    testo = normalizza_testo(messaggio.text)
    if not valida_codice_fiscale(testo):
        await messaggio.reply_text(
            "Codice fiscale non valido (16 caratteri, 9 lettere e 7 numeri). Riprova:",
            reply_markup=tastiera_annulla(),
        )
        return CF  # resta nello stesso stato: aspetta un altro tentativo
    dati_utente(context)["codice_fiscale"] = testo
    await messaggio.reply_text(
        "Inserisci il numero ricetta:", reply_markup=tastiera_annulla()
    )
    return RICETTA


async def riceve_ricetta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    messaggio = update.effective_message
    if messaggio is None or messaggio.text is None:
        return RICETTA
    testo = normalizza_testo(messaggio.text)
    if not valida_numero_ricetta(testo):
        await messaggio.reply_text(
            "Numero ricetta non valido (15 caratteri alfanumerici). Riprova:",
            reply_markup=tastiera_annulla(),
        )
        return RICETTA
    dati_utente(context)["numero_ricetta"] = testo
    await messaggio.reply_text(
        "Vuoi cercare in un'area specifica?", reply_markup=tastiera_si_no_area()
    )
    return VUOLE_AREA


def tastiera_si_no_provincia() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Sì", callback_data="prov_si"),
                InlineKeyboardButton("No, tutta l'area", callback_data="prov_no"),
            ],
            [InlineKeyboardButton("❌ Annulla", callback_data="annulla")],
        ]
    )


def tastiera_province(area: str) -> InlineKeyboardMarkup:
    # Solo le province dell'area scelta
    righe = [
        [InlineKeyboardButton(p, callback_data=f"provincia:{p}")]
        for p in AREE_DISPONIBILI[area]
    ]
    righe.append([InlineKeyboardButton("❌ Annulla", callback_data="annulla")])
    return InlineKeyboardMarkup(righe)


async def sceglie_si_no_provincia(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return VUOLE_PROVINCIA
    await query.answer()

    dati = dati_utente(context)
    if query.data == "prov_no":
        dati["provincia"] = None
        return await chiede_mesi(query)

    await query.edit_message_text(
        "Scegli una provincia:", reply_markup=tastiera_province(dati["area"])
    )
    return PROVINCIA


async def sceglie_provincia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return PROVINCIA
    await query.answer()

    provincia = query.data.split(":", 1)[1]
    dati = dati_utente(context)
    dati["provincia"] = provincia
    return await chiede_mesi(query)


def tastiera_mesi() -> InlineKeyboardMarkup:
    # 12 bottoni in 3 righe da 4: "1" ... "12"
    righe = [
        [
            InlineKeyboardButton(str(n), callback_data=f"mesi:{n}")
            for n in range(inizio, inizio + 4)
        ]
        for inizio in (1, 5, 9)
    ]
    righe.append([InlineKeyboardButton("❌ Annulla", callback_data="annulla")])
    return InlineKeyboardMarkup(righe)


async def chiede_mesi(query) -> int:
    """Mostra la schermata dei mesi e restituisce lo stato MESI."""
    await query.edit_message_text(
        "Entro quanti mesi vuoi cercare l'appuntamento?",
        reply_markup=tastiera_mesi(),
    )
    return MESI


async def sceglie_mesi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return MESI
    await query.answer()

    mesi = int(query.data.split(":", 1)[1])
    dati_utente(context)["mesi"] = mesi
    return await chiede_frequenza(query)


def tastiera_frequenza() -> InlineKeyboardMarkup:
    # Valori in ore tra un controllo e l'altro: modificabili a piacere
    valori = (1, 2, 3, 6, 12)
    righe = [
        [InlineKeyboardButton(f"{n} h", callback_data=f"ore:{n}") for n in valori[:3]],
        [InlineKeyboardButton(f"{n} h", callback_data=f"ore:{n}") for n in valori[3:]],
        [InlineKeyboardButton("❌ Annulla", callback_data="annulla")],
    ]
    return InlineKeyboardMarkup(righe)


async def chiede_frequenza(query) -> int:
    """Mostra la schermata della frequenza e restituisce lo stato FREQUENZA."""
    await query.edit_message_text(
        "Ogni quante ore vuoi che controlli?", reply_markup=tastiera_frequenza()
    )
    return FREQUENZA


async def sceglie_frequenza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return FREQUENZA
    await query.answer()

    ore = int(query.data.split(":", 1)[1])
    dati_utente(context)["ogni_ore"] = ore
    return await chiede_ora_inizio(query)


def tastiera_ore(prefisso: str, ore: list[int]) -> InlineKeyboardMarkup:
    """Bottoni per le ore date, 6 per riga. Il prefisso distingue inizio e fine."""
    bottoni = [
        InlineKeyboardButton(f"{h:02d}", callback_data=f"{prefisso}:{h}") for h in ore
    ]
    righe = [bottoni[i : i + 6] for i in range(0, len(bottoni), 6)]
    righe.append([InlineKeyboardButton("❌ Annulla", callback_data="annulla")])
    return InlineKeyboardMarkup(righe)


async def chiede_ora_inizio(query) -> int:
    await query.edit_message_text(
        "Da che ora vuoi che inizino i controlli?",
        reply_markup=tastiera_ore("inizio", list(range(24))),
    )
    return ORA_INIZIO


async def sceglie_ora_inizio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return ORA_INIZIO
    await query.answer()

    inizio = int(query.data.split(":", 1)[1])
    dati = dati_utente(context)
    dati["fascia_inizio"] = inizio
    frequenza = dati["ogni_ore"]

    # Durata della fascia = (fine - inizio) modulo 24: gestisce anche le fasce
    # che passano la mezzanotte (es. dalle 22 alle 06 = 8 ore).
    # Se fine == inizio la durata è 0, quindi viene esclusa da sola.
    ore_fine = [h for h in range(24) if (h - inizio) % 24 >= frequenza]

    await query.edit_message_text(
        f"Inizio: {inizio:02d}:00\n\n"
        f"Fino a che ora? (la fascia deve durare almeno {frequenza} ore)",
        reply_markup=tastiera_ore("fine", ore_fine),
    )
    return ORA_FINE


async def sceglie_ora_fine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return ORA_FINE
    await query.answer()

    fine = int(query.data.split(":", 1)[1])
    dati = dati_utente(context)
    dati["fascia_fine"] = fine
    # Stringa per il dettaglio; gli interi restano per lo scheduler
    dati["fascia"] = f"{dati['fascia_inizio']:02d}:00-{fine:02d}:00"
    return await mostra_riepilogo(query, dati)


def tastiera_conferma() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Conferma", callback_data="conferma"),
                InlineKeyboardButton("❌ Annulla", callback_data="annulla"),
            ]
        ]
    )


async def mostra_riepilogo(query, dati: dict) -> int:
    """Mostra tutti i dati raccolti e chiede conferma."""
    testo = (
        "Riepilogo del tracciamento:\n\n"
        f"Codice fiscale: {dati['codice_fiscale']}\n"
        f"Ricetta: {dati['numero_ricetta']}\n"
        f"Area: {dati['area'] or 'tutta la Sardegna'}\n"
        f"Provincia: {dati['provincia'] or 'tutte'}\n"
        f"Cerca entro: {dati['mesi']} mesi\n"
        f"Controllo ogni: {dati['ogni_ore']} ore\n"
        f"Fascia oraria: {dati['fascia']}\n\n"
        "Confermi?"
    )
    await query.edit_message_text(testo, reply_markup=tastiera_conferma())
    return RIEPILOGO


async def conferma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return RIEPILOGO
    await query.answer()

    dati = dati_utente(context)
    # La data limite si calcola una sola volta, qui, alla conferma
    oggi = adesso().date()
    tracciamento = {
        "numero_ricetta": dati["numero_ricetta"],
        "codice_fiscale": dati["codice_fiscale"],
        "area": dati["area"],
        "provincia": dati["provincia"],
        "data_limite": converti_mesi(dati["mesi"], oggi),
        "ogni_ore": dati["ogni_ore"],
        "fascia_inizio": dati["fascia_inizio"],
        "fascia_fine": dati["fascia_fine"],
        "ultimo_controllo": None,  # None = mai controllato
    }

    try:
        aggiungi_tracciamento(tracciamento)
        esito = (
            f"Tracciamento {tracciamento['numero_ricetta']} salvato. "
            "Controllo di tutti i tracciamenti in corso."
        )
        context.application.create_task(controlla_tutti(context.application))
    except RicettaGiaPresente:
        esito = f"La ricetta {tracciamento['numero_ricetta']} è già presente."

    dati.clear()
    menu = tastiera_menu(bool(leggi_tracciamenti()))
    await query.edit_message_text(f"{esito}\n\nCosa vuoi fare?", reply_markup=menu)
    return ConversationHandler.END


async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    dati_utente(context).clear()
    menu = tastiera_menu(bool(leggi_tracciamenti()))
    await query.edit_message_text(
        "Operazione annullata.\n\nCosa vuoi fare?", reply_markup=menu
    )
    return ConversationHandler.END


def esce_dal_flusso(handler):
    """Avvolge un handler: svuota i dati del flusso "Aggiungi", esegue
    l'handler e chiude la conversazione."""

    async def avvolto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        dati_utente(context).clear()
        await handler(update, context)
        return ConversationHandler.END

    return avvolto


async def gestisci_errore(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce le eccezioni non catturate negli handler: dettaglio completo
    nel log, messaggio breve all'utente."""
    errore = context.error
    # exc_info scrive nel log l'errore completo, con il traceback
    log.error("Errore in un handler", exc_info=errore)

    if isinstance(errore, ErroreStorage):
        testo = "Errore: il file dei tracciamenti è vuoto o danneggiato."
    else:
        testo = "Si è verificato un errore. I dettagli sono nel log."

    # update può non essere un Update (errori del bot non legati a un messaggio)
    if isinstance(update, Update) and update.effective_chat is not None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=testo)


def adesso() -> datetime:
    """Istante attuale con fuso  orario Europe/Rome"""
    return datetime.now(tz=ZoneInfo("Europe/Rome"))


def testo_esito(tracciamento: dict, appuntamenti: list) -> str:
    """Messaggio con il risultato di un controllo, sempre con la ricetta."""
    ricetta = tracciamento["numero_ricetta"]
    if not appuntamenti:
        limite = tracciamento["data_limite"].strftime("%d/%m/%Y")
        return f"Ricetta {ricetta}: nessun appuntamento entro il {limite}."

    righe = [f"Ricetta {ricetta}: trovati {len(appuntamenti)} appuntamenti:"]
    for a in appuntamenti[:MAX_APPUNTAMENTI_MESSAGGIO]:
        righe.append(f"• {a['Data']} {a['Ora']} - {a['Luogo']}")
    if len(appuntamenti) > MAX_APPUNTAMENTI_MESSAGGIO:
        righe.append(f"... e altri {len(appuntamenti) - MAX_APPUNTAMENTI_MESSAGGIO}.")
    return "\n".join(righe)


async def esegui_controllo(
    application: Application, numero_ricetta: str, solo_se_dovuto: bool = False
) -> None:
    """Controlla un tracciamento, invia il messaggio e aggiorna ultimo_controllo.
    Con solo_se_dovuto=True (giro automatico) salta il controllo se nel frattempo
    non è più necessario, per esempio perché è appena stato fatto."""
    # Un solo controllo alla volta: gli altri aspettano il loro turno
    async with application.bot_data["lock"]:
        # Si rilegge il tracciamento: nel frattempo potrebbe essere stato rimosso
        tracciamento = next(
            (t for t in leggi_tracciamenti() if t["numero_ricetta"] == numero_ricetta),
            None,
        )
        if tracciamento is None:
            return
        # Giro automatico: il controllo potrebbe essere già stato fatto da
        # "Controlla ora" o dal controllo dopo l'aggiunta mentre si aspettava
        if solo_se_dovuto and not deve_controllare(tracciamento, adesso()):
            return

        try:
            # Lo scraper è sincrono e lento: gira in un thread, il bot resta libero
            risultati = await asyncio.to_thread(
                cerca_appuntamento,
                tracciamento["codice_fiscale"],
                tracciamento["numero_ricetta"],
                tracciamento["area"],
                tracciamento["provincia"],
            )
            filtrati = filtra_appuntamenti(tracciamento["data_limite"], risultati)
            testo = testo_esito(tracciamento, filtrati)
        except ErroreBannerCUP as errore:
            log.warning("Errore dal sito per la ricetta %s: %s", numero_ricetta, errore)
            testo = f"Ricetta {numero_ricetta}: il sito ha risposto con un errore.\n{str(errore)[:200]}"
        except Exception:
            log.exception("Errore nel controllo della ricetta %s", numero_ricetta)
            testo = f"Ricetta {numero_ricetta}: errore tecnico durante il controllo. Dettagli nel log."

        # Anche in caso di errore, per non riprovare ogni minuto
        aggiorna_ultimo_controllo(numero_ricetta, adesso())

    try:
        await application.bot.send_message(
            chat_id=application.bot_data["allowed_id"], text=testo
        )
    except TelegramError:
        # Un invio fallito non deve fermare il resto del giro
        log.exception("Invio del messaggio non riuscito")


async def controlla_tutti(application: Application) -> None:
    """Controlla uno ad uno tutti i tracciamenti, con la pausa tra l'uno e l'altro."""
    numeri = [t["numero_ricetta"] for t in leggi_tracciamenti()]
    for i, numero in enumerate(numeri):
        if i > 0:
            await asyncio.sleep(pausa_tra_controlli())
        await esegui_controllo(application, numero)


async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chiamata dal JobQueue ogni minuto: controlla i tracciamenti che ne hanno bisogno."""
    application = context.application
    if application.bot_data.get("giro_in_corso"):
        return  # il giro precedente non è ancora finito
    application.bot_data["giro_in_corso"] = True
    try:
        da_fare = da_controllare(leggi_tracciamenti(), adesso())
        if not da_fare:
            return
        await asyncio.sleep(ritardo_iniziale())  # jitter, una volta per giro
        for i, tracciamento in enumerate(da_fare):
            if i > 0:
                await asyncio.sleep(pausa_tra_controlli())
            await esegui_controllo(
                application, tracciamento["numero_ricetta"], solo_se_dovuto=True
            )
    finally:
        application.bot_data["giro_in_corso"] = False


async def controlla_ora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bottone 'Controlla ora' nel dettaglio: controlla subito quel tracciamento."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer("Controllo avviato, il risultato arriva in un messaggio.")
    numero_ricetta = query.data.split(":", 1)[1]
    # create_task: l'handler termina subito e il bot resta libero
    context.application.create_task(
        esegui_controllo(context.application, numero_ricetta)
    )


def main() -> None:
    token, allowed_id = carica_configurazione()

    app = Application.builder().token(token).build()
    app.bot_data["allowed_id"] = allowed_id  # accessibile da ogni handler
    app.bot_data["lock"] = asyncio.Lock()
    # group=-1: viene eseguito prima del gruppo 0, dove stanno gli handler normali
    app.add_handler(TypeHandler(Update, controllo_autorizzazione), group=-1)
    app.add_error_handler(gestisci_errore)

    conversazione_aggiungi = ConversationHandler(
        entry_points=[CallbackQueryHandler(aggiungi, pattern="^aggiungi$")],
        states={
            CF: [MessageHandler(filters.TEXT & ~filters.COMMAND, riceve_cf)],
            RICETTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, riceve_ricetta)],
            VUOLE_AREA: [
                CallbackQueryHandler(sceglie_si_no_area, pattern="^area_(si|no)$")
            ],
            AREA: [CallbackQueryHandler(sceglie_area, pattern="^area:")],
            VUOLE_PROVINCIA: [
                CallbackQueryHandler(sceglie_si_no_provincia, pattern="^prov_(si|no)$")
            ],
            PROVINCIA: [CallbackQueryHandler(sceglie_provincia, pattern="^provincia:")],
            MESI: [CallbackQueryHandler(sceglie_mesi, pattern=r"^mesi:\d+$")],
            FREQUENZA: [CallbackQueryHandler(sceglie_frequenza, pattern=r"^ore:\d+$")],
            ORA_INIZIO: [
                CallbackQueryHandler(sceglie_ora_inizio, pattern=r"^inizio:\d+$")
            ],
            ORA_FINE: [CallbackQueryHandler(sceglie_ora_fine, pattern=r"^fine:\d+$")],
            RIEPILOGO: [CallbackQueryHandler(conferma, pattern="^conferma$")],
        },
        fallbacks=[
            CallbackQueryHandler(annulla, pattern="^annulla$"),
            CommandHandler("start", esce_dal_flusso(start)),
            CallbackQueryHandler(esce_dal_flusso(elenca), pattern="^elenca$"),
            CallbackQueryHandler(esce_dal_flusso(torna_al_menu), pattern="^menu$"),
            CallbackQueryHandler(
                esce_dal_flusso(scegli_da_rimuovere), pattern="^rimuovi$"
            ),
            CallbackQueryHandler(esce_dal_flusso(dettaglio), pattern="^dettaglio:"),
            CallbackQueryHandler(esce_dal_flusso(elimina), pattern="^elimina:"),
            CallbackQueryHandler(esce_dal_flusso(controlla_ora), pattern="^controlla:"),
        ],
        allow_reentry=True,
        per_message=False,
    )
    # La conversazione va registrata PRIMA degli altri handler
    app.add_handler(conversazione_aggiungi)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(elenca, pattern="^elenca$"))
    app.add_handler(CallbackQueryHandler(torna_al_menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(dettaglio, pattern="^dettaglio:"))
    app.add_handler(CallbackQueryHandler(elimina, pattern="^elimina:"))
    app.add_handler(CallbackQueryHandler(scegli_da_rimuovere, pattern="^rimuovi$"))
    app.add_handler(CallbackQueryHandler(controlla_ora, pattern="^controlla:"))
    app.add_handler(CallbackQueryHandler(annulla, pattern="^annulla$"))

    if app.job_queue is None:
        raise SystemExit(
            'Manca il JobQueue: pip install "python-telegram-bot[job-queue]"'
        )
    # Il tick parte 10 secondi dopo l'avvio e poi ogni 60 secondi
    app.job_queue.run_repeating(tick, interval=60, first=10)
    try:
        app.run_polling()
    except InvalidToken:
        raise SystemExit("Token non valido: controlla TELEGRAM_BOT_TOKEN nel .env")
    except NetworkError as e:
        raise SystemExit(f"Impossibile contattare Telegram: {e}")


if __name__ == "__main__":
    main()
