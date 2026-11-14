import asyncio
import json
import os
import websockets
import requests
from aiohttp import web

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MCP_WSS_URL = os.environ.get("MCP_WSS_URL")

async def search_with_gemini(query):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 350}
    }
    try:
        response = requests.post(url, json=payload)
        data = response.json()
        return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Aucun résultat trouvé.")
    except Exception as e:
        return f"Erreur technique : {str(e)}"

async def handle_mcp():
    while True:
        try:
            async with websockets.connect(MCP_WSS_URL) as websocket:
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
                                "serverInfo": {"name": "xiaozhi-gemini-bridge", "version": "1.0.0"}
                            }
                        }))
                    elif method == "tools/list":
                        await websocket.send(json.dumps({
                            "jsonrpc": "2.0", "id": msg_id,
                            "result": {
                                "tools": [{
                                    "name": "recherche_web",
                                    "description": "Recherche des informations récentes sur internet via Google (météo, actualités).",
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
                            result_text = await search_with_gemini(query)
                            await websocket.send(json.dumps({
                                "jsonrpc": "2.0", "id": msg_id,
                                "result": {"content": [{"type": "text", "text": result_text}], "isError": False}
                            }))
        except Exception as e:
            print(f"Déconnexion ({e}), nouvelle tentative dans 5 secondes...")
            await asyncio.sleep(5)

# Petit serveur web factice pour valider le plan gratuit Web Service de Render
async def health_check(request):
    return web.Response(text="Pont MCP Xiaozhi actif")

async def main():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    # Lance la boucle WebSocket Xiaozhi en parallèle
    await handle_mcp()

if __name__ == "__main__":
    asyncio.run(main())
