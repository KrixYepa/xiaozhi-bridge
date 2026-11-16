import os
import json
import re
import time
import asyncio
import aiohttp
import websockets
from aiohttp import web

# Récupération des variables d'environnement Render
MCP_WSS_URL = os.environ.get("MCP_WSS_URL")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# Cache mémoire simple : { "requete": (timestamp, "reponse") }
CACHE_RECHERCHES = {}
DUREE_CACHE_SECONDES = 300  # 5 minutes

# Protection anti-rafale
DERNIER_APPEL_TIME = 0
DELAI_MIN_ENTRE_REQUETES = 2.0  # Secondes minimum entre deux vraies requêtes API


def nettoyer_pour_voix(texte):
    """Nettoie le texte brut pour qu'il soit lu naturellement par la synthèse vocale."""
    if not texte:
        return "Je n'ai trouvé aucune information à ce sujet."
    # Supprime les URLs
    texte = re.sub(r'http[s]?://\S+', '', texte)
    # Supprime le Markdown (*, #, _, `, etc.)
    texte = re.sub(r'[*#_`~\[\]\(\)]', '', texte)
    # Remplace les sauts de ligne et espaces multiples par un seul espace
    texte = re.sub(r'\s+', ' ', texte).strip()
    # Coupe proprement à 450 caractères max pour éviter les monologues interminables
    if len(texte) > 450:
        texte = texte[:447].rsplit(' ', 1)[0] + "..."
    return texte


async def search_with_tavily(query):
    """Interroge Tavily avec gestion de cache et protection contre les timeouts."""
    global DERNIER_APPEL_TIME
    query_clean = query.strip().lower()
    maintenant = time.time()

    # 1. Vérification dans le cache
    if query_clean in CACHE_RECHERCHES:
        ts, reponse_cache = CACHE_RECHERCHES[query_clean]
        if maintenant - ts < DUREE_CACHE_SECONDES:
            print(f"⚡ Réponse servie depuis le cache pour : '{query}'")
            return reponse_cache

    # 2. Protection anti-rafale (si le robot spamme)
    if maintenant - DERNIER_APPEL_TIME < DELAI_MIN_ENTRE_REQUETES:
        print(f"🛡️ Requête trop rapide ignorée pour éviter la saturation : '{query}'")
        return "Donne directement une réponse avec les informations que tu as déjà."

    DERNIER_APPEL_TIME = maintenant

    url = "https://api.tavily.com/search"
    french_query = f"Faits précis et récents en français (France) : {query}"

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": french_query,
        "search_depth": "basic",
        "include_answer": True,
        "max_results": 3,
        "topic": "general"
    }

    timeout = aiohttp.ClientTimeout(total=8)
    connector = aiohttp.TCPConnector(ssl=False)

    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    print(f"❌ Erreur API Tavily : HTTP {response.status}")
                    return "Le service de recherche est momentanément indisponible."

                data = await response.json()
                brut = data.get("answer")
                if not brut and data.get("results"):
                    brut = data["results"][0].get("content", "")

                reponse_propre = nettoyer_pour_voix(brut)
                
                # Mise en cache
                CACHE_RECHERCHES[query_clean] = (time.time(), reponse_propre)
                print(f"✅ Réponse Tavily reçue et mise en cache pour : '{query}'")
                return reponse_propre

    except asyncio.TimeoutError:
        print(f"⏱️ Timeout Tavily pour : '{query}'")
        return "La recherche a pris trop de temps, reformule ta question."
    except Exception as e:
        print(f"❌ Exception Tavily : {e}")
        return "Une erreur technique est survenue pendant la recherche."


async def mcp_bridge_loop():
    """Boucle principale de connexion WebSocket au serveur MCP de Xiaozhi."""
    if not MCP_WSS_URL or not TAVILY_API_KEY:
        print("⚠️ ERREUR : Variables MCP_WSS_URL ou TAVILY_API_KEY manquantes !")
        return

    while True:
        try:
            async with websockets.connect(
                MCP_WSS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5
            ) as websocket:
                print("✅ Connecté avec succès au serveur MCP de Xiaozhi !")

                async for message in websocket:
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    msg_id = data.get("id")
                    method = data.get("method")
                    params = data.get("params", {})

                    # Initialisation du protocole MCP
                    if method == "initialize":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "xiaozhi-tavily-bridge", "version": "2.0.0"}
                            }
                        }))

                    # Déclaration de l'outil de recherche
                    elif method == "tools/list":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "tools": [
                                    {
                                        "name": "recherche_web",
                                        "description": (
                                            "Effectue UNE SEULE recherche web concise pour obtenir des actualités, "
                                            "résultats sportifs, météo (par défaut à Theys, Isère) ou faits récents. "
                                            "RÈGLE STRICTE : N'appelle cet outil qu'une seule fois par question utilisateur, "
                                            "avec 2 à 4 mots-clés précis. Ne fais jamais d'appels multiples en chaîne."
                                        ),
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {
                                                "requete": {
                                                    "type": "string",
                                                    "description": "Mots-clés courts en français (ex: 'prochain match equipe de france football')"
                                                }
                                            },
                                            "required": ["requete"]
                                        }
                                    }
                                ]
                            }
                        }))

                    # Exécution de la recherche
                    elif method == "tools/call":
                        if params.get("name") == "recherche_web":
                            query = params.get("arguments", {}).get("requete", "")
                            print(f"🔍 Recherche demandée par le robot : {query}")

                            result_text = await search_with_tavily(query)

                            await websocket.send(json.dumps({
                                "jsonrpc": "2.0",
                                "id": msg_id,
                                "result": {
                                    "content": [{"type": "text", "text": result_text}],
                                    "isError": False
                                }
                            }))

                    # Ping standard MCP
                    elif method == "ping" and msg_id is not None:
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {}
                        }))

        except Exception as e:
            print(f"⚠️ Déconnexion ({e}), nouvelle tentative dans 1 seconde...")
            await asyncio.sleep(1)


# --- Serveur HTTP minimal pour Render et UptimeRobot ---
async def health_check(request):
    return web.Response(text="Pont MCP Xiaozhi-Tavily opérationnel !", status=200)


async def main():
    app = web.Application()
    app.router.add_get("/", health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Serveur HTTP en écoute sur le port {port}")

    # Lancement de la boucle WebSocket en parallèle
    await mcp_bridge_loop()


if __name__ == "__main__":
    asyncio.run(main())
