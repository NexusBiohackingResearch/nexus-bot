import os
import re
import pandas as pd
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ===== LISTE DES PRODUITS ET PRIX =====
PRODUCTS = {
    "hgh 10u": 40.00,
    "bac water 10ml": 10.00,
    "hmg 76": 50.00,
    "hcg 5000": 55.00,
    "retatrutide 10mg": 100.00,
    "retatrutide 20mg": 150.00,
    "bpc157 5mg": 30.00,
    "bpc157 10mg": 50.00,
    "tb500 10mg": 70.00,
    "bpc-157+tb-500 5mg+5mg": 70.00,
    "bpc-157+tb-500 10mg+10mg": 140.00,
    "ghk-cu 50mg": 35.00,
    "glow-70 70mg": 96.00,
    "mgf 2mg": 45.00,
    "peg mgf 2mg": 23.00,
    "epithalon 10mg": 35.00,
    "tesamorelin 12mg+ipamorelin 6mg": 180.00,
    "semax 10mg+selank 10mg": 70.00,
    "cjc-1295 w/o dac + ipamorelin 5mg+5mg": 60.00,
    "nad+ 1000mg": 100.00,
    "ghrp-2 2mg": 21.00,
    "ghrp-6 5mg": 21.00,
    "igf-lr3 1mg": 149.00,
    "mots-c 10mg": 47.00,
    "dsip 10mg": 50.00,
    "oxytocin 5mg": 35.00,
    "aod-9604 5mg": 50.00,
    "pt141 10mg": 50.00,
    "mt-i 10mg": 38.00,
    "mt-ii (melanotan 2 acetate) 10mg": 40.00,
    "kisspeptin 5mg": 40.00,
    "ss-31 10mg": 70.00,
    "kpv": 47.00,
    "glutathione": 55.00,
    "5-amino-1mq 5mg": 45.00,
    "bronchogen 20mg": 80.00,
    "livagen 20mg": 80.00,
    "pancragen 20mg": 80.00,
}

FRAIS_PORT = 12.00
SEUIL_GRATUIT = 150.00
CODES_FILE = "codes_promo.xlsx"

def load_promo_codes():
    """Charge les codes promo depuis le fichier Excel."""
    try:
        df = pd.read_excel(CODES_FILE)
        codes = {}
        for _, row in df.iterrows():
            code = str(row['Code']).strip().upper()
            actif = str(row['Actif']).strip().lower() in ['oui', 'yes', 'true', '1']
            if actif:
                codes[code] = {
                    'influenceur': str(row['Influenceur']).strip(),
                    'reduction': float(row['Réduction (%)']),
                }
        return codes
    except Exception as e:
        print(f"Erreur lecture codes promo: {e}")
        return {}

def find_product(text):
    """Recherche un produit dans la liste par correspondance partielle."""
    text_lower = text.lower().strip()
    if text_lower in PRODUCTS:
        return text_lower, PRODUCTS[text_lower]
    for product, price in PRODUCTS.items():
        words = product.split()
        if all(w in text_lower for w in words[:2]):
            return product, price
        if text_lower in product or product.split()[0] in text_lower:
            return product, price
    return None, None

def parse_quantity(line):
    """Extrait la quantité et le nom du produit d'une ligne."""
    match = re.match(r'^(\d+)\s*[xX]?\s*(.+)$', line.strip())
    if match:
        return int(match.group(1)), match.group(2).strip()
    match = re.match(r'^[xX](\d+)\s*(.+)$', line.strip())
    if match:
        return int(match.group(1)), match.group(2).strip()
    return 1, line.strip()

def extract_promo_code(lines):
    """Cherche un code promo dans les lignes du message."""
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
    """Parse le message de commande et extrait les infos."""
    lines = message_text.strip().split('\n')

    separator_idx = None
    for i, line in enumerate(lines):
        if line.strip() == '':
            separator_idx = i
            break

    if separator_idx is None:
        return None, None, None, None, None

    product_lines = [l for l in lines[:separator_idx] if l.strip()]
    info_lines = [l for l in lines[separator_idx+1:] if l.strip()]

    # Cherche code promo dans les infos client
    promo_code, info_lines = extract_promo_code(info_lines)
    # Aussi dans les produits (au cas où)
    if not promo_code:
        promo_code, product_lines = extract_promo_code(product_lines)

    found_products = []
    not_found = []
    total = 0.0

    for line in product_lines:
        qty, name = parse_quantity(line)
        product, price = find_product(name)
        if product:
            subtotal = price * qty
            total += subtotal
            found_products.append((qty, product, price, subtotal))
        else:
            not_found.append(name)

    return found_products, not_found, info_lines, total, promo_code

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
            "❌ Format non reconnu.\n\n"
            "Merci d'envoyer votre commande dans ce format :\n\n"
            "Produit 1\n"
            "Produit 2\n"
            "\n"
            "Nom Prénom\n"
            "Adresse\n"
            "Code postal\n"
            "Ville\n"
            "Pays\n"
            "Téléphone\n"
            "Email\n"
            "CODE: VOTRE_CODE (optionnel)"
        )
        return

    found_products, not_found, client_info, total, promo_code = result

    if not found_products:
        await message.reply_text(
            "❌ Aucun produit reconnu dans votre commande.\n"
            f"Produits non trouvés : {', '.join(not_found)}\n\n"
            "Merci de vérifier les noms des produits."
        )
        return

    # Vérification code promo
    reduction_pct = 0.0
    reduction_montant = 0.0
    promo_info = ""
    if promo_code:
        codes = load_promo_codes()
        if promo_code in codes:
            reduction_pct = codes[promo_code]['reduction']
            reduction_montant = total * (reduction_pct / 100)
            influenceur = codes[promo_code]['influenceur']
            promo_info = f"🎁 Code *{promo_code}* ({influenceur}) : -*{reduction_pct:.0f}%* (-{reduction_montant:.2f}€)\n"
        else:
            promo_info = f"⚠️ Code *{promo_code}* invalide ou désactivé\n"

    total_apres_reduction = total - reduction_montant
    frais = 0.00 if total_apres_reduction >= SEUIL_GRATUIT else FRAIS_PORT
    total_final = total_apres_reduction + frais

    # Construction du message
    recap = "✅ *CONFIRMATION DE COMMANDE*\n"
    recap += "━━━━━━━━━━━━━━━━━━━━\n\n"
    recap += "🛒 *Vos produits :*\n"

    for qty, product, price, subtotal in found_products:
        name_display = product.upper()
        if qty > 1:
            recap += f"• {qty}x {name_display} — {price:.2f}€ x {qty} = *{subtotal:.2f}€*\n"
        else:
            recap += f"• {name_display} — *{price:.2f}€*\n"

    if not_found:
        recap += f"\n⚠️ Produits non reconnus : {', '.join(not_found)}\n"

    recap += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    recap += f"💰 Sous-total : *{total:.2f}€*\n"

    if promo_info:
        recap += promo_info

    if reduction_montant > 0:
        recap += f"💰 Après réduction : *{total_apres_reduction:.2f}€*\n"

    if frais == 0:
        recap += f"🚚 Frais de port : *GRATUIT* (commande > {SEUIL_GRATUIT:.0f}€)\n"
    else:
        recap += f"🚚 Frais de port : *{frais:.2f}€*\n"

    recap += f"💳 *TOTAL : {total_final:.2f}€*\n"
    recap += f"━━━━━━━━━━━━━━━━━━━━\n\n"

    if client_info:
        recap += "📦 *Adresse de livraison :*\n"
        for line in client_info:
            recap += f"{line}\n"
        recap += "\n"

    recap += "🔗 *Lien de paiement :*\n"
    recap += "[Votre lien de paiement ici]\n\n"
    recap += "_Merci de votre commande ! 🙏_"

    await message.reply_text(recap, parse_mode='Markdown')

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN manquant !")
        return

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot Nexus démarré !")
    app.run_polling()

if __name__ == "__main__":
    main()
