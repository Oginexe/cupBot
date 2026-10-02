# La versione dell'immagine deve coincidere con quella di playwright in
# requirements.txt, altrimenti Playwright non trova i browser.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app

# Prima solo requirements.txt: se il codice cambia ma le dipendenze no,
# Docker riusa questo livello e la build è più veloce.
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY *.py ./

# Cartella dei tracciamenti, scrivibile dall'utente non root dell'immagine
RUN mkdir -p /app/data && chown pwuser:pwuser /app/data
USER pwuser

CMD ["python3", "bot.py"]
