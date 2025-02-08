from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
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

# Dictionnaires pour les taux minimum et les alias des bookmakers
BOOKMAKER_TAUX = {
    "betclic": 88,
    "winamax": 90,
    "unibet": 85,
    "psel / zebet": 85,
    "pmu / vbet": 72,
}

BOOKMAKER_ALIASES = {
    "betclic": ["betclic", "Betclic", "BETCLIC"],
    "winamax": ["winamax", "Winamax", "WINAMAX"],
    "unibet": ["unibet", "Unibet", "UNIBET"],
    "psel / zebet": ["psel", "zebet", "Psel", "Zebet", "PSEL", "ZEBET", "psel / zebet", "Psel / Zebet"],
    "pmu / vbet": ["pmu", "vbet", "PMU", "Vbet", "VBET", "PMU / Vbet", "pmu / vbet"],
}

# Gestion de l'historique des conversions (stocké dans un fichier JSON)
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
            filtered = [c for c in filtered if c.get('bookmaker', '').lower() == bookmaker.lower()]
        return sorted(filtered, key=lambda x: x['timestamp'], reverse=True)[:limit]

history_manager = HistoryManager()

# Serveur Flask pour le keep-alive (utile sur certains hébergeurs)
app = Flask('')

@app.route('/')
def home():
    return "Le bot est en ligne !"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True  # Pour que le thread se ferme avec le programme
    t.start()

# --- Fonctions utilitaires ---

def parse_float(value: str):
    """
    Convertit une chaîne avec '.' ou ',' en float.
    Renvoie None si la conversion échoue.
    """
    try:
        return float(value.replace(',', '.'))
    except ValueError:
        return None

def get_normalized_bookmaker(input_name: str):
    """
    Renvoie le nom standard du bookmaker et son alias tel qu’entré.
    Si aucun alias ne correspond, retourne (None, input_name).
    """
    input_name = input_name.lower()
    for normalized, aliases in BOOKMAKER_ALIASES.items():
        if input_name in [alias.lower() for alias in aliases]:
            return normalized, input_name.capitalize()
    return None, input_name

def calculate_max_freebet(cote_arjel: float, cote_ha: float, cash_ha: float, frais_arjel: float = 0, frais_ha: float = 0.03):
    """
    Calcule le nombre maximum de freebets et la mise en HA correspondante.
    """
    try:
        mise_ha = cash_ha / (cote_ha - 1)
        nb_fb = mise_ha * (cote_ha - frais_ha) / ((cote_arjel - 1) * (1 - frais_arjel))
        return nb_fb, mise_ha
    except ZeroDivisionError:
        return None, None

async def ask_for_input(ctx, prompt: str, parse_function):
    """
    Demande à l'utilisateur une saisie via Discord jusqu'à obtention d'une valeur valide.
    En cas d'exception (timeout, etc.), retourne None.
    """
    def check_author(m):
        return m.author == ctx.author and m.channel == ctx.channel

    await ctx.send(prompt)
    try:
        msg = await bot.wait_for("message", check=check_author, timeout=120)
        value = parse_function(msg.content.strip())
        if value is not None:
            return value
        else:
            await ctx.send("❌ Valeur invalide. Veuillez réessayer.")
            return await ask_for_input(ctx, prompt, parse_function)
    except Exception as e:
        await ctx.send(f"⚠️ Une erreur est survenue : {e}")
        return None

# --- Commandes du bot ---

@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

@bot.event
async def on_error(event, *args, **kwargs):
    logging.error(f"Erreur dans {event} : {args} {kwargs}")

@bot.command()
async def conversion(ctx):
    """Effectue une conversion et propose de partager les résultats."""
    # Demander les valeurs d'entrée
    cote_arjel = await ask_for_input(ctx, "🎯 **Entrez la cote ARJEL :**", parse_float)
    if cote_arjel is None:
        return

    cote_ha = await ask_for_input(ctx, "🎯 **Entrez la cote HA :**", parse_float)
    if cote_ha is None:
        return

    nb_fb = await ask_for_input(ctx, "💸 **Entrez le nombre de freebets :**", parse_float)
    if nb_fb is None:
        return

    # Choix du bookmaker
    await ctx.send("🏦 **Choisissez un bookmaker parmi la liste suivante ou entrez le vôtre :**\n" +
                   ", ".join(BOOKMAKER_TAUX.keys()))
    bookmaker_input = await ask_for_input(ctx, "Entrez le bookmaker :", lambda x: x)
    bookmaker, _ = get_normalized_bookmaker(bookmaker_input)
    if bookmaker is None:
        bookmaker = bookmaker_input  # Utilisation de l'entrée brute si pas d'alias connu

    # Calculs
    frais_arjel = 0
    frais_ha = 0.03
    mise_arjel = nb_fb
    try:
        mise_ha = (nb_fb * ((cote_arjel - 1) * (1 - frais_arjel))) / (cote_ha - frais_ha)
    except ZeroDivisionError:
        await ctx.send("❌ Erreur dans le calcul (division par zéro).")
        return

    ha_si_issue_arjel = -mise_ha * (cote_ha - 1)
    arjel_si_cote_passe = nb_fb * (cote_arjel - 1) * (1 - frais_arjel)
    total_si_issue_arjel = ha_si_issue_arjel + arjel_si_cote_passe
    taux_conversion = (total_si_issue_arjel / nb_fb) * 100
    cash_necessaire = (cote_ha * mise_ha) - mise_ha

    # Détermination de la couleur en fonction du taux minimum attendu
    if bookmaker in BOOKMAKER_TAUX:
        taux_min = BOOKMAKER_TAUX[bookmaker]
        difference = taux_conversion - taux_min
        if abs(difference) <= 2:
            couleur = "🟧"
        elif difference > 2:
            couleur = "🟩"
        else:
            couleur = "🟥"
    else:
        couleur = "🟦"

    # Affichage des résultats calculés
    await ctx.send(
        f"{couleur} **Taux de conversion** : {taux_conversion:.2f}%\n"
        f"💸 **Nombre de freebets en ARJEL** : {mise_arjel:.2f}\n"
        f"💰 **Mise en HA (stake)** : {mise_ha:.2f}\n"
        f"⚠️ **Cash nécessaire en HA (liability)** : {cash_necessaire:.2f}"
    )

    # Proposition de partage
    await ctx.send("🔗 Voulez-vous partager ces résultats ? (oui/non)")
    share_resp = await ask_for_input(ctx, "Votre réponse :", lambda x: x.lower())
    if share_resp != "oui":
        await ctx.send("❌ Pas de problème, à bientôt pour de nouvelles conversions !")
        # Enregistrer la conversion avant de quitter
        history_manager.add_conversion({
            'type': 'conversion',
            'cote_arjel': cote_arjel,
            'cote_ha': cote_ha,
            'nb_fb': nb_fb,
            'mise_arjel': mise_arjel,
            'mise_ha': mise_ha,
            'cash_necessaire': cash_necessaire,
            'taux': taux_conversion,
            'bookmaker': bookmaker
        })
        return

    # Demander les informations pour le message de partage
    athlete = await ask_for_input(ctx, "🏅 **Entrez l'athlète/l'issue :**", lambda x: x)
    heure = await ask_for_input(ctx, "⏰ **Entrez l'heure (ex: Demain 11h) :**", lambda x: x)
    cash_disponible = await ask_for_input(ctx, "💸 **Entrez le cash disponible (en liability HA) :**", lambda x: x)

    # Format du message de partage (selon le format souhaité)
    share_message = (
        f"🎯 Conversion {bookmaker} : {couleur} - {taux_conversion:.2f}% 🎯\n"
        f"🏅 Athlète : {athlete}\n"
        f"⏰ Heure : {heure}\n"
        f"💸 Cash disponible : {cash_disponible}€\n\n"
        f"🔢 Cotes :\n"
        f"    •   ARJEL : {cote_arjel:.1f}\n"
        f"    •   Lay : {cote_ha:.1f}"
    )
    await ctx.send("Voici le message final de partage :")
    await ctx.send(share_message)

    # Sauvegarder la conversion dans l'historique
    history_manager.add_conversion({
        'type': 'conversion',
        'cote_arjel': cote_arjel,
        'cote_ha': cote_ha,
        'nb_fb': nb_fb,
        'mise_arjel': mise_arjel,
        'mise_ha': mise_ha,
        'cash_necessaire': cash_necessaire,
        'taux': taux_conversion,
        'bookmaker': bookmaker
    })

@bot.command()
async def maxfb(ctx):
    """Calcule le maximum de freebet possible avec le cash HA disponible."""
    cote_arjel = await ask_for_input(ctx, "🎯 **Entrez la cote ARJEL :**", parse_float)
    if cote_arjel is None:
        return

    cote_ha = await ask_for_input(ctx, "🎯 **Entrez la cote HA :**", parse_float)
    if cote_ha is None:
        return

    cash_ha = await ask_for_input(ctx, "💰 **Entrez votre cash disponible en HA (liability) :**", parse_float)
    if cash_ha is None:
        return

    if cote_arjel <= 1 or cote_ha <= 1:
        await ctx.send("❌ Les cotes doivent être supérieures à 1.")
        return

    max_fb_val, mise_ha = calculate_max_freebet(cote_arjel, cote_ha, cash_ha)
    if max_fb_val is None or mise_ha is None:
        await ctx.send("❌ Impossible de calculer avec ces valeurs.")
        return

    warning_mise_minimale = ""
    if mise_ha < 6:
        warning_mise_minimale = "\n⚠️ **ATTENTION** : La mise en HA calculée est inférieure à 6€, on force la mise minimale."
        mise_ha = 6
        max_fb_val = 6 * (cote_ha - 0.03) / (cote_arjel - 1)
        cash_necessaire = 6 * (cote_arjel - 1) / (cote_ha - 0.03)
        warning_mise_minimale += (
            f"\n💡 Pour respecter la mise minimale :\n"
            f"   • Mise HA minimale : 6.00€\n"
            f"   • Freebet correspondant : {max_fb_val:.2f}€\n"
            f"   • Cash à mettre : {cash_necessaire:.2f}€"
        )
    else:
        cash_necessaire = (cote_ha * mise_ha) - mise_ha

    if cash_ha < cash_necessaire:
        await ctx.send(f"❌ Il vous faut au moins {cash_necessaire:.2f}€ en cash HA.")
        return

    nb_freebets_possibles = cash_ha / mise_ha
    await ctx.send(f"💰 Avec {cash_ha:.2f}€ de cash HA, vous pouvez convertir jusqu'à {nb_freebets_possibles:.2f} freebets.")

    ha_si_issue_arjel = -mise_ha * (cote_ha - 1)
    arjel_si_cote_passe = max_fb_val * (cote_arjel - 1)
    taux_conversion = (ha_si_issue_arjel + arjel_si_cote_passe) / max_fb_val * 100

    history_manager.add_conversion({
        'type': 'maxfb',
        'cote_arjel': cote_arjel,
        'cote_ha': cote_ha,
        'cash_ha': cash_ha,
        'max_fb': max_fb_val,
        'mise_ha': mise_ha,
        'taux': taux_conversion
    })

    result_message = (
        f"💫 **Résultats du calcul maximum**\n\n"
        f"💰 Freebet maximum possible : {max_fb_val:.2f}€\n"
        f"📊 Mise en HA (stake) : {mise_ha:.2f}€\n"
        f"📈 Taux de conversion : {taux_conversion:.2f}%\n\n"
        f"ℹ️ Basé sur :\n"
        f"   • Cote ARJEL : {cote_arjel}\n"
        f"   • Cote HA : {cote_ha}\n"
        f"   • Cash HA disponible : {cash_ha:.2f}€\n"
        f"{warning_mise_minimale}\n"
        f"💰 Liquidité disponible : {cash_necessaire:.2f}€"
    )
    await ctx.send(result_message)

@bot.command()
async def historique(ctx, limit: int = 5):
    """Affiche l'historique des conversions enregistrées."""
    conversions = history_manager.get_history(limit=limit)
    if not conversions:
        await ctx.send("❌ Aucune conversion trouvée dans l'historique.")
        return

    response = "📜 **Historique des conversions**\n\n"
    total_fb = 0
    somme_ponderee = 0
    nb_conversions_standard = 0
    for conv in conversions:
        date = datetime.fromisoformat(conv['timestamp']).strftime('%d/%m/%Y %H:%M')
        if conv.get('type') == 'maxfb':
            response += f"🔄 **Calcul MaxFB** - {date}\n"
            response += (f"💰 Max FB: {conv.get('max_fb', 0):.2f}€ | Mise HA: {conv.get('mise_ha', 0):.2f}€\n"
                         f"📊 Taux: {conv.get('taux', 0):.2f}% | Cash HA: {conv.get('cash_ha', 0):.2f}€\n\n")
        else:
            nb_fb_conv = conv.get('nb_fb', 0)
            taux_conv = conv.get('taux', 0)
            total_fb += nb_fb_conv
            somme_ponderee += (nb_fb_conv * taux_conv)
            nb_conversions_standard += 1
            response += f"🎯 **Conversion** - {date}\n"
            response += (f"💰 Freebet: {conv.get('nb_fb', 'N/A')}€ | Cash: {conv.get('cash_necessaire', 'N/A')}€\n"
                         f"📊 Taux: {conv.get('taux', 'N/A')}% | Mise HA: {conv.get('mise_ha', 'N/A')}€\n\n")
    if total_fb > 0:
        moyenne_ponderee = somme_ponderee / total_fb
        response = f"📊 **Statistiques globales**: Total freebets convertis : {total_fb:.2f}€ | Taux moyen pondéré : {moyenne_ponderee:.2f}%\n\n" + response

    await ctx.send(response)

@bot.command()
async def presentation(ctx):
    """Présente les fonctionnalités du bot."""
    presentation_message = (
        "👋 Bienvenue dans le bot de conversion ! Voici les commandes disponibles :\n"
        "1. **!conversion** : Effectue une conversion entre cotes et propose de partager le résultat.\n"
        "2. **!maxfb** : Calcule le maximum de freebet possible avec le cash HA disponible.\n"
        "3. **!historique** : Affiche l'historique des conversions enregistrées.\n"
        "4. **!presentation** : Affiche cette présentation.\n"
    )
    await ctx.send(presentation_message)

# --- Démarrage du bot ---
if __name__ == "__main__":
    keep_alive()
    while True:
        try:
            bot.run(TOKEN)
        except Exception as e:
            logging.error(f"Erreur de connexion: {e}")
            continue
