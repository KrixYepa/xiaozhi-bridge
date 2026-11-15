import asyncio
import json
import os
import re
import websockets
import aiohttp
from aiohttp import web

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
MCP_WSS_URL = os.environ.get("MCP_WSS_URL")

def nettoyer_pour_voix(texte):
    """Supprime les URLs et balises Markdown pour éviter que le robot ne les épelle à voix haute."""
    if not texte:
        return ""
    texte = re.sub(r'http[s]?://\S+', '', texte)
    texte = re.sub(r'[*#_`\[\]]', '', texte)
    texte = re.sub(r'\s+', ' ', texte).strip()
    return texte[:600]

async def search_with_tavily(query):
    if not TAVILY_API_KEY:
        return "Erreur : clé API Tavily manquante."

    url = "https://tavily.com"
    
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "include_answer": True,
        "max_results": 3
    }
    
    timeout = aiohttp.ClientTimeout(total=8)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    err_text = await response.text()
                    print(f"❌ Erreur HTTP Tavily ({response.status}) : {err_text}")
                    return "Le moteur de recherche est temporairement indisponible."
                
                data = await response.json()
                print(f"✅ Réponse Tavily reçue pour '{query}'")
                
                # 1. Synthèse directe de Tavily (nettoyée pour la voix)
                if data.get("answer"):
                    return nettoyer_pour_voix(data["answer"])
                
                # 2. Repli : combine les 2 meilleurs extraits nettoyés
                results = data.get("results", [])
                extraits = [nettoyer_pour_voix(r.get("content", "")) for r in results[:2] if r.get("content")]
                if extraits:
                    return " | ".join(extraits)[:600]
                
                return "Aucune information récente trouvée sur ce sujet."
                
    except asyncio.TimeoutError:
        print(f"⏱️ Timeout Tavily pour : {query}")
        return "La recherche a pris trop de temps, réessaie dans un instant."
    except Exception as e:
        print(f"❌ Exception recherche : {str(e)}")
        return "Erreur technique lors de la recherche."

async def keep_alive(websocket):
    while True:
        await asyncio.sleep(25)
        try:
            await websocket.send(json.dumps({"jsonrpc": "2.0", "method": "ping"}))
        except Exception:
            break

async def handle_mcp():
    if not MCP_WSS_URL:
        print("❌ Variable MCP_WSS_URL manquante !")
        return

    while True:
        ping_task = None
        try:
            async with websockets.connect(MCP_WSS_URL, ping_interval=20, ping_timeout=20) as websocket:
                print("✅ Connecté avec succès au serveur MCP de Xiaozhi !")
                ping_task = asyncio.create_task(keep_alive(websocket))
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    msg_id = data.get("id")
                    method = data.get("method")
                    params = data.get("params", {})

                    if method == "initialize":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0", "id": msg_id,
                            "result": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "xiaozhi-tavily-bridge", "version": "1.2.0"}
                            }
                        }))
                    elif method == "tools/list":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0", "id": msg_id,
                            "result": {
                                "tools": [{
                                    "name": "recherche_web",
                                    "description": "Recherche des informations récentes sur internet (météo à Theys par défaut si aucune ville n'est précisée, actualités, faits récents). Formule une requête courte avec des mots-clés précis.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "requete": {
                                                "type": "string",
                                                "description": "Mots-clés précis pour la recherche web."
                                            }
                                        },
                                        "required": ["requete"]
                                    }
                                }]
                            }
                        }))
                    elif method == "tools/call":
                        if params.get("name") == "recherche_web":
                            query = params.get("arguments", {}).get("requete", "")
                            print(f"🔍 Recherche demandée par le robot : {query}")
                            result_text = await search_with_tavily(query)
                            await websocket.send(json.dumps({
                                "jsonrpc": "2.0", "id": msg_id,
                                "result": {"content": [{"type": "text", "text": result_text}], "isError": False}
                            }))
        except Exception as e:
            print(f"⚠️ Déconnexion ({e}), nouvelle tentative dans 5 secondes...")
            await asyncio.sleep(5)
        finally:
            if ping_task:
                ping_task.cancel()

async def health_check(request):
    return web.Response(text="Pont MCP Tavily v1.2 actif")

async def test_search(request):
    query = request.query.get("q", "météo Theys")
    print(f"--- TEST MANUEL HTTP DÉCLENCHÉ --- : {query}")
    result = await search_with_tavily(query)
    return web.Response(text=f"Test réussi !\nRequête : {query}\nRésultat : {result}")

async def main():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/test', test_search)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    await handle_mcp()

if __name__ == "__main__":
    asyncio.run(main())
