import asyncio
import json
import os
import websockets
import requests
from aiohttp import web

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
MCP_WSS_URL = os.environ.get("MCP_WSS_URL")

async def search_with_tavily(query):
    url = "https://api.tavily.com/search"
    # On force le contexte en français dans la requête envoyée à Tavily
    french_query = f"Réponds obligatoirement en français : {query}"
    
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": french_query,
        "search_depth": "basic",
        "include_answer": True,
        "max_results": 3
    }
    try:
        response = requests.post(url, json=payload)
        data = response.json()
        print(f"Réponse brute Tavily : {json.dumps(data)}")
        
        if "answer" in data and data["answer"]:
            return data["answer"]
        return "Je n'ai pas trouvé de réponse précise sur le web."
    except Exception as e:
        return f"Erreur de recherche : {str(e)}"

async def handle_mcp():
    while True:
        try:
            # Ajout de ping_interval et ping_timeout pour garder la ligne active
            async with websockets.connect(MCP_WSS_URL, ping_interval=20, ping_timeout=20) as websocket:
                print("Connecté avec succès au serveur MCP de Xiaozhi !")
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
                                "serverInfo": {"name": "xiaozhi-tavily-bridge", "version": "1.0.0"}
                            }
                        }))
                    elif method == "tools/list":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0", "id": msg_id,
                            "result": {
                                "tools": [{
                                    "name": "recherche_web",
                                    "description": "Recherche des informations récentes sur internet (météo, actualités).",
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
                            print(f"Recherche demandée : {query}")
                            result_text = await search_with_tavily(query)
                            await websocket.send(json.dumps({
                                "jsonrpc": "2.0", "id": msg_id,
                                "result": {"content": [{"type": "text", "text": result_text}], "isError": False}
                            }))
        except Exception as e:
            print(f"Déconnexion ({e}), nouvelle tentative dans 5 secondes...")
            await asyncio.sleep(5)
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
