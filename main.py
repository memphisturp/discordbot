from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
from dotenv import load_dotenv
import os

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()
TOKEN = os.getenv("TOKEN")  # Récupère le token depuis le fichier .env

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

# Serveur keep-alive pour Replit ou autre hébergement
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
    input_name = input_name.lower()  # Convertir en minuscule pour comparaison
    for normalized, aliases in BOOKMAKER_ALIASES.items():
        if input_name in [alias.lower() for alias in aliases]:
            return normalized, input_name.capitalize()  # Retourne le nom standard et l'alias original
    return None, input_name  # Si aucun alias ne correspond, utiliser le nom fourni

# Événement de démarrage du bot
@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

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
                msg = await bot.wait_for("message", check=check_author, timeout=120)  # Timeout de 2 minutes
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

# Démarrage du bot avec le serveur keep-alive
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
