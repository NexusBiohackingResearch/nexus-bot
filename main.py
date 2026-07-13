import os
import re
import asyncio
import json
import html
import uuid
from datetime import datetime
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from aiohttp import web, ClientSession, ClientTimeout

FRAIS_PORT = 12.00
SEUIL_GRATUIT = 150.00
CODES_FILE = "codes_promo.xlsx"
SPREADSHEET_ID = "1pGnRnnQEmpnuwJiB6mkbFHaEmhh4wPFhCd4wtehAmKc"
SHEET_NAME = "Commande NEXUS"
BITCOIN_ADDRESS = os.environ.get("BITCOIN_ADDRESS", "3KNT1ksKmqoYySEHULRuD6hcAa8e67DjYH")
BTC_RATE_CACHE_SECONDS = 300
_btc_rate_cache = {"rate": None, "timestamp": 0.0}

PRODUCTS = {
    "hgh 10u": {"price": 40.00, "available": True},
    "bac water 10ml": {"price": 10.00, "available": True},
    "hmg 76": {"price": 50.00, "available": True},
    "hcg 5000": {"price": 55.00, "available": True},
    "retatrutide 10mg": {"price": 100.00, "available": True},
    "retatrutide 20mg": {"price": 150.00, "available": True},
    "bpc157 5mg": {"price": 30.00, "available": True},
    "bpc157 10mg": {"price": 50.00, "available": True},
    "tb500 10mg": {"price": 70.00, "available": True},
    "bpc-157+tb-500 5mg+5mg": {"price": 70.00, "available": True},
    "bpc-157+tb-500 10mg+10mg": {"price": 140.00, "available": True},
    "ghk-cu 50mg": {"price": 35.00, "available": True},
    "glow-70 70mg": {"price": 96.00, "available": True},
    "mgf 2mg": {"price": 45.00, "available": True},
    "peg mgf 2mg": {"price": 23.00, "available": True},
    "epithalon 10mg": {"price": 35.00, "available": True},
    "tesamorelin 12mg+ipamorelin 6mg": {"price": 180.00, "available": True},
    "semax 10mg+selank 10mg": {"price": 70.00, "available": True},
    "cjc-1295 w/o dac + ipamorelin 5mg+5mg": {"price": 60.00, "available": True},
    "nad+ 1000mg": {"price": 100.00, "available": True},
    "ghrp-2 2mg": {"price": 21.00, "available": True},
    "ghrp-6 5mg": {"price": 21.00, "available": True},
    "igf-lr3 1mg": {"price": 149.00, "available": True},
    "mots-c 10mg": {"price": 47.00, "available": True},
    "dsip 10mg": {"price": 50.00, "available": True},
    "oxytocin 5mg": {"price": 35.00, "available": True},
    "aod-9604 5mg": {"price": 50.00, "available": True},
    "pt141 10mg": {"price": 50.00, "available": True},
    "mt-i 10mg": {"price": 38.00, "available": True},
    "mt-ii (melanotan 2 acetate) 10mg": {"price": 40.00, "available": True},
    "kisspeptin 5mg": {"price": 40.00, "available": True},
    "ss-31 10mg": {"price": 70.00, "available": True},
    "kpv": {"price": 47.00, "available": True},
    "glutathione": {"price": 55.00, "available": True},
    "5-amino-1mq 5mg": {"price": 45.00, "available": True},
    "bronchogen 20mg": {"price": 80.00, "available": True},
    "livagen 20mg": {"price": 80.00, "available": True},
    "pancragen 20mg": {"price": 80.00, "available": True},
}


def get_public_base_url():
    explicit = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        return f"https://{railway_domain}"
    return None


async def get_btc_eur_rate():
    now = asyncio.get_running_loop().time()
    cached_rate = _btc_rate_cache["rate"]
    if cached_rate and now - _btc_rate_cache["timestamp"] < BTC_RATE_CACHE_SECONDS:
        return cached_rate

    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=eur"
    timeout = ClientTimeout(total=10)
    async with ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"accept": "application/json"}) as response:
            response.raise_for_status()
            data = await response.json()
            rate = float(data["bitcoin"]["eur"])

    _btc_rate_cache["rate"] = rate
    _btc_rate_cache["timestamp"] = now
    return rate


def build_payment_link(order_id, btc_amount):
    base_url = get_public_base_url()
    if not base_url:
        return None
    return f"{base_url}/pay?order_id={order_id}&amount={btc_amount:.8f}"


async def payment_page(request):
    order_id = request.query.get("order_id", "Commande NEXUS")
    amount_raw = request.query.get("amount", "")
    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        raise web.HTTPBadRequest(text="Montant Bitcoin invalide")

    bitcoin_uri = (
        f"bitcoin:{BITCOIN_ADDRESS}?amount={amount:.8f}"
        f"&label=NEXUS&message={order_id}"
    )
    safe_order = html.escape(order_id)
    safe_address = html.escape(BITCOIN_ADDRESS)
    safe_uri = html.escape(bitcoin_uri, quote=True)
    page = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Paiement Bitcoin NEXUS</title>
  <style>
    body {{ font-family: Arial, sans-serif; background:#f5f5f5; margin:0; padding:24px; }}
    .card {{ max-width:560px; margin:40px auto; background:white; border-radius:18px; padding:28px; box-shadow:0 10px 35px rgba(0,0,0,.10); }}
    h1 {{ margin-top:0; }}
    .amount {{ font-size:32px; font-weight:700; margin:18px 0; }}
    .button {{ display:block; text-align:center; background:#f7931a; color:white; text-decoration:none; padding:16px; border-radius:12px; font-weight:700; font-size:18px; }}
    .box {{ background:#f1f1f1; padding:14px; border-radius:10px; overflow-wrap:anywhere; margin-top:18px; }}
    .muted {{ color:#666; font-size:14px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Paiement Bitcoin</h1>
    <p class="muted">Référence : {safe_order}</p>
    <div class="amount">{amount:.8f} BTC</div>
    <a class="button" href="{safe_uri}">Ouvrir mon portefeuille Bitcoin</a>
    <div class="box"><strong>Adresse :</strong><br>{safe_address}</div>
    <div class="box"><strong>Montant exact :</strong><br>{amount:.8f} BTC</div>
    <p class="muted">Vérifiez toujours l’adresse et le montant dans votre portefeuille avant de confirmer.</p>
  </div>
</body>
</html>"""
    return web.Response(text=page, content_type="text/html")


async def healthcheck(request):
    return web.json_response({"status": "ok"})


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/pay", payment_page)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Serveur web demarre sur le port {port}")
    return runner


def get_sheet():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        return sheet
    except Exception as e:
        print(f"Erreur Google Sheets: {e}")
        return None

def load_promo_codes():
    try:
        df = pd.read_excel(CODES_FILE, header=1)
        codes = {}
        for _, row in df.iterrows():
            code = str(row.iloc[0]).strip().upper()
            actif = str(row.iloc[3]).strip().lower() in ['oui', 'yes', 'true', '1']
            if actif:
                codes[code] = {
                    'influenceur': str(row.iloc[1]).strip(),
                    'reduction': float(row.iloc[2]),
                }
        return codes
    except Exception as e:
        print(f"Erreur codes promo: {e}")
        return {}

def find_product(text):
    text_lower = text.lower().strip()
    if text_lower in PRODUCTS:
        return text_lower, PRODUCTS[text_lower]
    for name, data in PRODUCTS.items():
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

    found_products = []
    not_found = []
    unavailable = []
    total = 0.0

    for line in product_lines:
        qty, name = parse_quantity(line)
        product_name, data = find_product(name)
        if product_name:
            if data['available']:
                subtotal = data['price'] * qty
                total += subtotal
                found_products.append((qty, product_name, data['price'], subtotal))
            else:
                unavailable.append(product_name)
        else:
            not_found.append(name)

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

def add_to_sheet(found_products, client, total, promo_code, reduction_montant, total_final, order_id, btc_amount, btc_rate, payment_link):
    sheet = get_sheet()
    if not sheet:
        return
    try:
        produits_str = ", ".join([f"{qty}x {p.upper()}" if qty > 1 else p.upper() for qty, p, _, _ in found_products])
        date_heure = datetime.now().strftime("%d/%m/%Y %H:%M")
        row = [
            date_heure, produits_str, client['nom_prenom'], client['adresse'],
            client['code_postal'], client['ville'], client['pays'],
            client['telephone'], client['email'], f"{total:.2f}",
            promo_code if promo_code else '', f"{reduction_montant:.2f}" if reduction_montant > 0 else '',
            f"{total_final:.2f}", "En attente", order_id, f"{btc_amount:.8f}", f"{btc_rate:.2f}", payment_link or ""
        ]
        sheet.append_row(row)
        print("Commande ajoutee dans Google Sheets")
    except Exception as e:
        print(f"Erreur ajout Google Sheets: {e}")

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
        await message.reply_text(f"Aucun produit reconnu.\nProduits non trouves : {', '.join(not_found)}")
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

    order_id = f"NEXUS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    try:
        btc_rate = await get_btc_eur_rate()
        btc_amount = total_final / btc_rate
    except Exception as e:
        print(f"Erreur recuperation cours BTC/EUR: {e}")
        await message.reply_text(
            "Le cours Bitcoin est momentanement indisponible. Merci de reessayer dans quelques minutes."
        )
        return

    payment_link = build_payment_link(order_id, btc_amount)
    add_to_sheet(
        found_products, client, total, promo_code, reduction_montant, total_final,
        order_id, btc_amount, btc_rate, payment_link
    )

    recap = "CONFIRMATION DE COMMANDE\n--------------------\n\n"
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
    recap += f"Frais de port : {'GRATUIT' if frais == 0 else f'{frais:.2f}EUR'}\n"
    recap += f"TOTAL : {total_final:.2f}EUR\n"
    recap += f"--------------------\n\n"
    recap += f"Adresse de livraison :\n{client['nom_prenom']}\n{client['adresse']}\n"
    recap += f"{client['code_postal']} {client['ville']}\n{client['pays']}\n\n"
    recap += f"Reference commande : {order_id}\n"
    recap += f"Montant Bitcoin : {btc_amount:.8f} BTC\n"
    recap += f"Cours utilise : 1 BTC = {btc_rate:.2f} EUR\n\n"
    recap += f"Adresse Bitcoin :\n{BITCOIN_ADDRESS}\n\n"
    recap += "Cliquez sur le bouton ci-dessous pour ouvrir la page de paiement.\n"
    recap += "Le statut reste 'En attente' jusqu'a verification manuelle.\n\nMerci de votre commande !"

    if payment_link:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("₿ Payer en Bitcoin", url=payment_link)
        ]])
        await message.reply_text(recap, reply_markup=keyboard)
    else:
        await message.reply_text(
            recap + "\n\nBouton indisponible : ajoutez PUBLIC_BASE_URL dans Railway."
        )

async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN manquant !")
        return

    print("Bot Nexus demarre !")
    web_runner = await start_web_server()
    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(30)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=["message"])
    try:
        await asyncio.Event().wait()
    finally:
        await web_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())