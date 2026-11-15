import asyncio
import json
import os
import websockets
import aiohttp
from aiohttp import web

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
MCP_WSS_URL = os.environ.get("MCP_WSS_URL")

async def search_with_tavily(query):
    url = "https://api.tavily.com/search"
    french_query = f"Réponds obligatoirement en français de manière concise : {query}"
    
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": french_query,
        "search_depth": "basic",
        "include_answer": True,
        "max_results": 3
    }
    
    timeout = aiohttp.ClientTimeout(total=8) # Évite que Xiaozhi n'attende trop longtemps
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    err_text = await response.text()
                    print(f"❌ Erreur HTTP Tavily ({response.status}) : {err_text}")
                    return "Le moteur de recherche est temporairement indisponible."
                
                data = await response.json()
                print(f"✅ Réponse Tavily reçue pour '{query}'")
                
                # 1. On prend la réponse synthétisée si elle existe
                if data.get("answer"):
                    return data["answer"]
                
                # 2. Repli : si pas de synthèse, on prend le premier extrait brut trouvé
                results = data.get("results", [])
                if results and results[0].get("content"):
                    return results[0]["content"][:500]
                
                return "Aucune information récente trouvée sur ce sujet."
                
    except asyncio.TimeoutError:
        print(f"⏱️ Timeout Tavily pour : {query}")
        return "La recherche a pris trop de temps, réessaie dans un instant."
    except Exception as e:
        print(f"❌ Exception recherche : {str(e)}")
        return f"Erreur technique lors de la recherche."

async def keep_alive(websocket):
    while True:
        await asyncio.sleep(25)
        try:
            await websocket.send(json.dumps({"jsonrpc": "2.0", "method": "ping"}))
        except Exception:
            break

async def handle_mcp():
    while True:
        ping_task = None
        try:
            async with websockets.connect(MCP_WSS_URL, ping_interval=20, ping_timeout=20) as websocket:
                print("Connecté avec succès au serveur MCP de Xiaozhi !")
                ping_task = asyncio.create_task(keep_alive(websocket))
                
                async for message in websocket:
                    data = json.loads(message)
                    msg_id = data.get("id")
                    method = data.get("method")
                    params = data.get("params", {})

                    if method == "initialize":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0", "id": msg_id,
                            "result": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "xiaozhi-tavily-bridge", "version": "1.1.0"}
                            }
                        }))
                    elif method == "tools/list":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0", "id": msg_id,
                            "result": {
                                "tools": [{
                                    "name": "recherche_web",
                                    "description": "Recherche des informations récentes sur internet (météo, actualités, faits).",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"requete": {"type": "string", "description": "La recherche à effectuer."}},
                                        "required": ["requete"]
                                    }
                                }]
                            }
                        }))
                    elif method == "tools/call":
                        if params.get("name") == "recherche_web":
                            query = params.get("arguments", {}).get("requete")
                            print(f"🔍 Recherche demandée par le robot : {query}")
                            result_text = await search_with_tavily(query)
                            await websocket.send(json.dumps({
                                "jsonrpc": "2.0", "id": msg_id,
                                "result": {"content": [{"type": "text", "text": result_text}], "isError": False}
                            }))
        except Exception as e:
            print(f"Déconnexion ({e}), nouvelle tentative dans 5 secondes...")
            await asyncio.sleep(5)
        finally:
            if ping_task:
                ping_task.cancel()

async def health_check(request):
    return web.Response(text="Pont MCP Tavily actif")

async def test_search(request):
    query = request.query.get("q", "actualités technologies")
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
