import os
import re
import asyncio
import pandas as pd
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

FRAIS_PORT = 12.00
SEUIL_GRATUIT = 150.00
PRODUCTS_FILE = "produits.xlsx"
CODES_FILE = "codes_promo.xlsx"

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
        return None, None, None, None, None, None

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

    return found_products, not_found, unavailable, info_lines, total, promo_code

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
            "Nom Prenom\nAdresse\nCode postal\nVille\nPays\nTelephone\nEmail\n"
            "CODE: VOTRE_CODE (optionnel)"
        )
        return

    found_products, not_found, unavailable, client_info, total, promo_code = result

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

    if client_info:
        recap += "Adresse de livraison :\n"
        for line in client_info:
            recap += f"{line}\n"
        recap += "\n"

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