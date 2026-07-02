#!/usr/bin/env python3
"""
Surveillance de la bourse aux dossards Paris-Versailles.
Envoie une alerte Telegram dès qu'un dossard semble disponible.

Fonctionnement :
1. Tourne en boucle pendant DUREE_BOUCLE_SECONDES, en checkant la page
   toutes les INTERVALLE_SECONDES secondes (au lieu d'un check unique).
2. À chaque check : isole la cellule de statut (td rowspan=3, unique dans
   la page), vérifie si la phrase négative fixe est toujours présente.
3. Son absence = changement d'état = alerte Telegram immédiate.
4. En fin de boucle, sauvegarde l'état dans state.json pour le prochain
   déclenchement du workflow (5 minutes plus tard).
"""

import os
import sys
import time
import json
import hashlib
import requests
from bs4 import BeautifulSoup

# ---------- CONFIGURATION ----------

URL = "https://www.parisversailles.com/inscription_bourse.php"

PHRASE_NEGATIVE = "pas de dossard disponible à la revente"

# La boucle tourne 270s (4min30), pour laisser une marge de sécurité avant
# le prochain déclenchement du cron à 5 minutes (300s). Elle checke toutes
# les 30 secondes à l'intérieur de cette fenêtre.
DUREE_BOUCLE_SECONDES = 270
INTERVALLE_SECONDES = 30

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.parisversailles.com/site/bourse-aux-dossards/",
    "Connection": "keep-alive",
}


# ---------- FONCTIONS ----------

def fetch_page():
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def extraire_zone(html):
    """Isole la cellule de statut (td rowspan='3'), unique dans la page."""
    soup = BeautifulSoup(html, "html.parser")
    cellule = soup.find("td", attrs={"rowspan": "3"})
    if cellule is None:
        print("ATTENTION : cellule rowspan=3 introuvable, la structure de la page a peut-être changé.")
        return soup.get_text(separator=" ", strip=True)
    return cellule.get_text(separator=" ", strip=True)


def analyser_texte(texte):
    """True si le texte suggère qu'un dossard est disponible."""
    return PHRASE_NEGATIVE not in texte.lower()


def charger_etat():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"hash": None, "dernier_statut": "inconnu"}


def sauvegarder_etat(etat):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2)


def envoyer_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERREUR : TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    r = requests.post(url, data=payload, timeout=10)
    if r.status_code != 200:
        print(f"Erreur envoi Telegram : {r.status_code} - {r.text}")


def verifier_une_fois(etat):
    """Un check unique. Retourne l'état mis à jour."""
    try:
        html = fetch_page()
    except Exception as e:
        print(f"Erreur de récupération de la page : {e}")
        return etat  # on ne casse pas la boucle pour un raté réseau ponctuel

    zone_texte = extraire_zone(html)
    hash_actuel = hashlib.sha256(zone_texte.encode("utf-8")).hexdigest()
    dossard_disponible = analyser_texte(zone_texte)
    statut_actuel = "disponible" if dossard_disponible else "indisponible"

    changement_de_statut = statut_actuel != etat.get("dernier_statut")

    print(f"[{time.strftime('%H:%M:%S')}] Statut : {statut_actuel} | Changement : {changement_de_statut}")

    if statut_actuel == "disponible" and changement_de_statut:
        envoyer_telegram(
            "🏃 ALERTE Paris-Versailles : un dossard semble disponible !\n"
            f"{URL}\n\n"
            "Vérifie et fonce, ça part vite."
        )

    etat["hash"] = hash_actuel
    etat["dernier_statut"] = statut_actuel
    return etat


def main():
    etat = charger_etat()
    fin_boucle = time.time() + DUREE_BOUCLE_SECONDES

    while True:
        etat = verifier_une_fois(etat)
        sauvegarder_etat(etat)  # sauvegarde à chaque tour, pas seulement à la fin

        if time.time() >= fin_boucle:
            break
        time.sleep(INTERVALLE_SECONDES)


if __name__ == "__main__":
    main()
