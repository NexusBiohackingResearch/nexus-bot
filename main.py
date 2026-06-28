import os
import re
import asyncio
import json
from datetime import datetime
import pandas as pd
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials

FRAIS_PORT = 12.00
SEUIL_GRATUIT = 150.00
PRODUCTS_FILE = "produits.xlsx"
CODES_FILE = "codes_promo.xlsx"
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_ID = "1pGnRnnQEmpnuwJiB6mkbFHaEmhh4wPFhCd4wtehAmKc"
SHEET_NAME = "Commande NEXUS"

def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    return sheet

def load_products():
    try:
        df = pd.read_excel(PRODUCTS_FILE)
        products = {}
        for _, row in df.iterrows():
            name = str(row['Produit']).strip().lower()
            price = float(row['Prix (EUR)'])
            dispo = str(row['Disponible (Oui/Non)']).strip().lower() in ['oui', 'yes', 'true', '1']
            products[name] = {'price': price, 'available': dispo}
        return products
    except Exception as e:
        print(f"Erreur chargement produits: {e}")
        return {}

def load_promo_codes():
    try:
        df = pd.read_excel(CODES_FILE)
        codes = {}
        for _, row in df.iterrows():
            code = str(row['Code']).strip().upper()
            actif = str(row['Actif']).strip().lower() in ['oui', 'yes', 'true', '1']
            if actif:
                codes[code] = {
                    'influenceur': str(row['Influenceur']).strip(),
                    'reduction': float(row['Reduction (%)']),
                }
        return codes
    except Exception as e:
        print(f"Erreur codes promo: {e}")
        return {}

def find_product(text, products):
    text_lower = text.lower().strip()
    if text_lower in products:
        return text_lower, products[text_lower]
    for name, data in products.items():
        words = name.split()
        if all(w in text_lower for w in words[:2]):
            return name, data
        if text_lower in name or name.split()[0] in text_lower:
            return name, data
    return None, None

def parse_quantity(line):
    match = re.match(r'^(\d+)\s*[xX]?\s*(.+)$', line.strip())
    if match:
        return int(match.group(1)), match.group(2).strip()
    match = re.match(r'^[xX](\d+)\s*(.+)$', line.strip())
    if match:
        return int(match.group(1)), match.group(2).strip()
    return 1, line.strip()

def extract_promo_code(lines):
    promo_code = None
    clean_lines = []
    for line in lines:
        match = re.match(r'^(?:code|promo|code promo)\s*[:\-]?\s*(\w+)$', line.strip(), re.IGNORECASE)
        if match:
            promo_code = match.group(1).upper()
        else:
            clean_lines.append(line)
    return promo_code, clean_lines

def parse_order(message_text):
    lines = message_text.strip().split('\n')
    separator_idx = None
    for i, line in enumerate(lines):
        if line.strip() == '':
            separator_idx = i
            break
    if separator_idx is None:
        return None, None, None, None, None, None, None

    product_lines = [l for l in lines[:separator_idx] if l.strip()]
    info_lines = [l for l in lines[separator_idx+1:] if l.strip()]

    promo_code, info_lines = extract_promo_code(info_lines)
    if not promo_code:
        promo_code, product_lines = extract_promo_code(product_lines)

    products = load_products()
    found_products = []
    not_found = []
    unavailable = []
    total = 0.0

    for line in product_lines:
        qty, name = parse_quantity(line)
        product_name, data = find_product(name, products)
        if product_name:
            if data['available']:
                subtotal = data['price'] * qty
                total += subtotal
                found_products.append((qty, product_name, data['price'], subtotal))
            else:
                unavailable.append(product_name)
        else:
            not_found.append(name)

    # Parse client info - ordre: nom prenom, adresse, code postal, ville, pays, tel, email
    client = {
        'nom_prenom': info_lines[0] if len(info_lines) > 0 else '',
        'adresse': info_lines[1] if len(info_lines) > 1 else '',
        'code_postal': info_lines[2] if len(info_lines) > 2 else '',
        'ville': info_lines[3] if len(info_lines) > 3 else '',
        'pays': info_lines[4] if len(info_lines) > 4 else '',
        'telephone': info_lines[5] if len(info_lines) > 5 else '',
        'email': info_lines[6] if len(info_lines) > 6 else '',
    }

    return found_products, not_found, unavailable, client, total, promo_code

def add_to_sheet(found_products, client, total, promo_code, reduction_montant, total_final):
    try:
        sheet = get_sheet()
        produits_str = ", ".join([f"{qty}x {p.upper()}" if qty > 1 else p.upper() for qty, p, _, _ in found_products])
        date_heure = datetime.now().strftime("%d/%m/%Y %H:%M")
        row = [
            date_heure,
            produits_str,
            client['nom_prenom'],
            client['adresse'],
            client['code_postal'],
            client['ville'],
            client['pays'],
            client['telephone'],
            client['email'],
            f"{total:.2f}",
            promo_code if promo_code else '',
            f"{reduction_montant:.2f}" if reduction_montant > 0 else '',
            f"{total_final:.2f}",
            "En attente"
        ]
        sheet.append_row(row)
        print("Commande ajoutee dans Google Sheets")
    except Exception as e:
        print(f"Erreur Google Sheets: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    text = message.text
    if text.startswith('/'):
        return

    result = parse_order(text)
    if result[0] is None:
        await message.reply_text(
            "Format non reconnu.\n\n"
            "Merci d'envoyer votre commande dans ce format :\n\n"
            "Produit 1\nProduit 2\n\n"
            "Nom Prenom\nAdresse\nCode postal\nVille\nPays\nTelephone\nEmail"
        )
        return

    found_products, not_found, unavailable, client, total, promo_code = result

    if unavailable:
        msg = "Certains produits ne sont pas disponibles :\n"
        for p in unavailable:
            msg += f"- {p.upper()}\n"
        msg += "\nMerci de modifier votre commande."
        await message.reply_text(msg)
        return

    if not found_products:
        await message.reply_text(
            f"Aucun produit reconnu.\nProduits non trouves : {', '.join(not_found)}"
        )
        return

    reduction_montant = 0.0
    promo_info = ""
    if promo_code:
        codes = load_promo_codes()
        if promo_code in codes:
            reduction_pct = codes[promo_code]['reduction']
            reduction_montant = total * (reduction_pct / 100)
            influenceur = codes[promo_code]['influenceur']
            promo_info = f"Code {promo_code} ({influenceur}) : -{reduction_pct:.0f}% (-{reduction_montant:.2f}EUR)\n"
        else:
            promo_info = f"Code {promo_code} invalide ou desactive\n"

    total_apres = total - reduction_montant
    frais = 0.00 if total_apres >= SEUIL_GRATUIT else FRAIS_PORT
    total_final = total_apres + frais

    # Ajouter dans Google Sheets
    add_to_sheet(found_products, client, total, promo_code, reduction_montant, total_final)

    recap = "CONFIRMATION DE COMMANDE\n"
    recap += "--------------------\n\n"
    recap += "Vos produits :\n"
    for qty, product, price, subtotal in found_products:
        if qty > 1:
            recap += f"- {qty}x {product.upper()} : {price:.2f}EUR x {qty} = {subtotal:.2f}EUR\n"
        else:
            recap += f"- {product.upper()} : {price:.2f}EUR\n"

    if not_found:
        recap += f"\nProduits non reconnus : {', '.join(not_found)}\n"

    recap += f"\n--------------------\n"
    recap += f"Sous-total : {total:.2f}EUR\n"
    if promo_info:
        recap += promo_info
    if reduction_montant > 0:
        recap += f"Apres reduction : {total_apres:.2f}EUR\n"
    if frais == 0:
        recap += f"Frais de port : GRATUIT\n"
    else:
        recap += f"Frais de port : {frais:.2f}EUR\n"
    recap += f"TOTAL : {total_final:.2f}EUR\n"
    recap += f"--------------------\n\n"
    recap += f"Adresse de livraison :\n"
    recap += f"{client['nom_prenom']}\n"
    recap += f"{client['adresse']}\n"
    recap += f"{client['code_postal']} {client['ville']}\n"
    recap += f"{client['pays']}\n\n"
    recap += "Paiement en Bitcoin :\n"
    recap += "3KNT1ksKmqoYySEHULRuD6hcAa8e67DjYH\n\n"
    recap += "Merci de votre commande !"

    await message.reply_text(recap)

async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN manquant !")
        return

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot Nexus demarre !")
    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())