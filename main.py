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
