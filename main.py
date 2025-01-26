from flask import Flask
from threading import Thread
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import logging
import json
from datetime import datetime

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()
TOKEN = os.getenv("TOKEN")  # Récupère le token depuis le fichier .env

# Configuration du logging
logging.basicConfig(level=logging.INFO)

# Création du bot avec ses intentions
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Taux minimums attendus pour chaque bookmaker
BOOKMAKER_TAUX = {
    "betclic": 88,
    "winamax": 90,
    "unibet": 85,
    "psel / zebet": 85,
    "pmu / vbet": 72,
}

# Alias acceptés pour chaque bookmaker
BOOKMAKER_ALIASES = {
    "betclic": ["betclic", "Betclic", "BETCLIC"],
    "winamax": ["winamax", "Winamax", "WINAMAX"],
    "unibet": ["unibet", "Unibet", "UNIBET"],
    "psel / zebet": ["psel", "zebet", "Psel", "Zebet", "PSEL", "ZEBET", "psel / zebet", "Psel / Zebet"],
    "pmu / vbet": ["pmu", "vbet", "PMU", "Vbet", "VBET", "PMU / Vbet", "pmu / vbet"],
}

# Structure pour stocker l'historique
class HistoryManager:
    def __init__(self):
        self.conversions = []
        self.load_history()
    
    def load_history(self):
        try:
            with open('history.json', 'r') as f:
                self.conversions = json.load(f)
        except FileNotFoundError:
            self.save_history()
    
    def save_history(self):
        with open('history.json', 'w') as f:
            json.dump(self.conversions, f, indent=2)
    
    def add_conversion(self, data):
        data['timestamp'] = datetime.now().isoformat()
        self.conversions.append(data)
        self.save_history()
    
    def get_history(self, bookmaker=None, limit=5):
        filtered = self.conversions
        if bookmaker:
            filtered = [c for c in filtered if c['bookmaker'].lower() == bookmaker.lower()]
        return sorted(filtered, key=lambda x: x['timestamp'], reverse=True)[:limit]

# Instance globale de l'historique
history_manager = HistoryManager()

# Serveur keep-alive pour hébergement
app = Flask('')

@app.route('/')
def home():
    return "Le bot est en ligne !"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Fonctions utilitaires
def parse_float(value):
    """Convertit une chaîne avec '.' ou ',' en float. Renvoie None si la conversion échoue."""
    try:
        return float(value.replace(',', '.'))
    except ValueError:
        return None

def get_normalized_bookmaker(input_name):
    """Renvoie le nom standard et l'alias d'origine pour le bookmaker."""
    input_name = input_name.lower()
    for normalized, aliases in BOOKMAKER_ALIASES.items():
        if input_name in [alias.lower() for alias in aliases]:
            return normalized, input_name.capitalize()
    return None, input_name

def calculate_max_freebet(cote_arjel, cote_ha, cash_ha, frais_arjel=0, frais_ha=0.03):
    """Calcule le montant maximum de freebet possible avec le cash HA disponible"""
    try:
        mise_ha = cash_ha / (cote_ha - 1)
        nb_fb = mise_ha * (cote_ha - frais_ha) / ((cote_arjel - 1) * (1 - frais_arjel))
        return nb_fb, mise_ha
    except ZeroDivisionError:
        return None, None

# Événement de démarrage du bot
@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

@bot.event
async def on_error(event, *args, **kwargs):
    """Gérer les erreurs"""
    logging.error(f"Une erreur est survenue dans {event}: {args} {kwargs}")

# Commande principale de conversion
@bot.command()
async def conversion(ctx):
    """Commande de conversion avec gestion des alias et continuation sans erreur."""
    def check_author(m):
        return m.author == ctx.author and m.channel == ctx.channel

    async def ask_for_input(prompt, parse_function):
        while True:
            await ctx.send(prompt)
            try:
                msg = await bot.wait_for("message", check=check_author, timeout=120)
                value = parse_function(msg.content.strip())
                if value is not None:
                    return value
                else:
                    await ctx.send("❌ Valeur invalide. Veuillez réessayer.")
            except Exception as e:
                await ctx.send(f"⚠️ Une erreur est survenue : {e}")
                return None

    # Étape 1 : Demander les entrées utilisateur
    cote_arjel = await ask_for_input("🎯 **Entrez la cote ARJEL :**", parse_float)
    if cote_arjel is None:
        return

    cote_ha = await ask_for_input("🎯 **Entrez la cote HA :**", parse_float)
    if cote_ha is None:
        return

    nb_fb = await ask_for_input("💸 **Entrez le nombre de freebets :**", parse_float)
    if nb_fb is None:
        return

    await ctx.send(
        "🏦 **Choisissez un bookmaker parmi la liste suivante ou entrez le vôtre :**\n"
        + ", ".join(BOOKMAKER_TAUX.keys())
    )
    try:
        msg_book = await bot.wait_for("message", check=check_author, timeout=120)
        bookmaker, alias_original = get_normalized_bookmaker(msg_book.content.strip())
    except Exception as e:
        await ctx.send(f"⚠️ Une erreur est survenue : {e}")
        return

    # Étape 2 : Données fixes et calculs
    frais_arjel = 0
    frais_ha = 0.03

    mise_arjel = nb_fb
    mise_ha = (nb_fb * ((cote_arjel - 1) * (1 - frais_arjel) + 0)) / (cote_ha - frais_ha)
    ha_si_issue_arjel = -mise_ha * (cote_ha - 1)
    arjel_si_cote_passe = nb_fb * (cote_arjel - 1) * (1 - frais_arjel)
    total_si_issue_arjel = ha_si_issue_arjel + arjel_si_cote_passe
    taux_conversion = (total_si_issue_arjel / nb_fb) * 100
    cash_necessaire = (cote_ha * mise_ha) - mise_ha

    commentaire = ""
    if bookmaker in BOOKMAKER_TAUX:
        taux_min = BOOKMAKER_TAUX[bookmaker]
        difference = taux_conversion - taux_min
        if abs(difference) <= 2:
            couleur = "🟧"
            commentaire = "⚠️ Le taux est proche du minimum attendu."
        elif difference > 2:
            couleur = "🟩"
            commentaire = "✅ Le taux est au-dessus du minimum attendu, c’est avantageux !"
        else:
            couleur = "🟥"
            commentaire = "❌ Le taux est en dessous du minimum attendu, attention."
    else:
        couleur = "🟦"

    # Étape 3 : Résultats
    await ctx.send(
        f"{couleur} **Taux de conversion** : {taux_conversion:.2f}%\n"
        f"💸 **Nombre de freebets en ARJEL** : {mise_arjel:.2f}\n"
        f"💰 **Mise en HA (en stake)** : {mise_ha:.2f}\n"
        f"⚠️ **Cash nécessaire en HA (en liability)** : {cash_necessaire:.2f}\n"
        f"{commentaire}"
    )

    # Sauvegarde dans l'historique
    conversion_data = {
        'type': 'conversion',
        'cote_arjel': cote_arjel,
        'cote_ha': cote_ha,
        'nb_fb': nb_fb,
        'mise_arjel': mise_arjel,
        'mise_ha': mise_ha,
        'cash_necessaire': cash_necessaire,
        'taux': taux_conversion,
        'bookmaker': bookmaker
    }
    history_manager.add_conversion(conversion_data)

@bot.command()
async def maxfb(ctx):
    """Calcule le montant maximum de freebet possible avec le cash HA disponible"""
    def check_author(m):
        return m.author == ctx.author and m.channel == ctx.channel

    async def ask_for_input(prompt, parse_function):
        while True:
            await ctx.send(prompt)
            try:
                msg = await bot.wait_for("message", check=check_author, timeout=120)
                value = parse_function(msg.content.strip())
                if value is not None and value > 0:
                    return value
                await ctx.send("❌ Valeur invalide. Veuillez entrer un nombre positif.")
            except Exception as e:
                await ctx.send(f"⚠️ Une erreur est survenue : {e}")
                return None

    # Demander les entrées utilisateur
    cote_arjel = await ask_for_input("🎯 **Entrez la cote ARJEL :**", parse_float)
    if cote_arjel is None:
        return

    cote_ha = await ask_for_input("🎯 **Entrez la cote HA :**", parse_float)
    if cote_ha is None:
        return

    cash_ha = await ask_for_input("💰 **Entrez votre cash disponible en HA (liability) :**", parse_float)
    if cash_ha is None:
        return

    # Vérifications supplémentaires
    if cote_arjel <= 1:
        await ctx.send("❌ La cote ARJEL doit être supérieure à 1")
        return
    if cote_ha <= 1:
        await ctx.send("❌ La cote HA doit être supérieure à 1")
        return

    # Calcul du maximum de freebet possible
    max_fb, mise_ha = calculate_max_freebet(cote_arjel, cote_ha, cash_ha)
    if max_fb is None or mise_ha is None:
        await ctx.send("❌ Impossible de calculer avec ces valeurs")
        return

    # Calcul du taux de conversion
    ha_si_issue_arjel = -mise_ha * (cote_ha - 1)
    arjel_si_cote_passe = max_fb * (cote_arjel - 1)
    total_si_issue_arjel = ha_si_issue_arjel + arjel_si_cote_passe
    taux_conversion = (total_si_issue_arjel / max_fb) * 100

    # Sauvegarde dans l'historique
    conversion_data = {
        'type': 'maxfb',
        'cote_arjel': cote_arjel,
        'cote_ha': cote_ha,
        'cash_ha': cash_ha,
        'max_fb': max_fb,
        'mise_ha': mise_ha,
        'taux': taux_conversion
    }
    history_manager.add_conversion(conversion_data)

    # Affichage des résultats
    await ctx.send(
        f"💫 **Résultats du calcul maximum**\n\n"
        f"💰 **Freebet maximum possible** : {max_fb:.2f}€\n"
        f"📊 **Mise en HA (stake)** : {mise_ha:.2f}€\n"
        f"📈 **Taux de conversion** : {taux_conversion:.2f}%\n\n"
        f"ℹ️ Ces calculs sont basés sur :\n"
        f"   • Cote ARJEL : {cote_arjel}\n"
        f"   • Cote HA : {cote_ha}\n"
        f"   • Cash HA disponible : {cash_ha}€"
    )

@bot.command()
async def historique(ctx, limit: int = 5):
    """Affiche l'historique des dernières conversions"""
    conversions = history_manager.get_history(limit=limit)
    
    if not conversions:
        await ctx.send("❌ Aucune conversion trouvée dans l'historique.")
        return
    
    response = "📜 **Historique des conversions**\n\n"
    for conv in conversions:
        date = datetime.fromisoformat(conv['timestamp']).strftime('%d/%m/%Y %H:%M')
        
        if conv.get('type') == 'maxfb':
            response += f"🔄 **Calcul MaxFB** - {date}\n"
            response += f"💰 Max FB: {conv['max_fb']:.2f}€ | Mise HA: {conv['mise_ha']:.2f}€\n"
            response += f"📊 Taux: {conv['taux']:.2f}% | Cash HA: {conv['cash_ha']:.2f}€\n"
        else:
            response += f"🎯 **Conversion Standard** - {date}\n"
            response += f"💰 Mise: {conv.get('mise_arjel', 'N/A')}€ | Cash: {conv.get('cash_necessaire', 'N/A')}€\n"
            response += f"📊 Taux: {conv.get('taux', 'N/A')}%\n"
        response += "\n"
    
    await ctx.send(response)

# Démarrage du bot avec le serveur keep-alive
if __name__ == "__main__":
    keep_alive()
    while True:
        try:
            bot.run(TOKEN)
        except Exception as e:
            logging.error(f"Erreur de connexion: {e}")
            continue
