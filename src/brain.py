import os
import json
import re
from openai import OpenAI
# Importamos la normalización desde data_loader
from src.data_loader import normalizar_ticker 

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = None
if GROQ_API_KEY:
    try: client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    except: pass

def interpretar_intencion(msg):
    if not client: return {"accion": "CHARLA"}
    # Convertimos a minúsculas para que sea más fácil buscar (usa tu variable msg)
    mensaje_limpio = msg.lower()
    
    # 🎛️ NUEVA INTENCIÓN: CONFIGURAR LOTE
    if "lote" in mensaje_limpio or "lotaje" in mensaje_limpio:
        numeros = re.findall(r"0\.\d+", mensaje_limpio)
        if numeros:
            return {"accion": "CONFIGURAR_LOTE", "valor": float(numeros[0])}
    # Prompt mejorado para detectar CATEGORÍAS
    prompt = f"""
    Analiza: "{msg}".
    
    1. CATEGORIA:
       - Si pide divisas/monedas/forex -> "FOREX"
       - Si pide cripto/bitcoin -> "CRIPTO"
       - Si pide acciones/empresas -> "ACCIONES"
       - Si no especifica -> "GENERAL"
       
    2. ESTRATEGIA: 
       - Si pide "contra [PAIS]" -> accion="COMPARAR", lista_activos=[TICKER SEGUN CONTEXTO].
    
    3. ROCKSTAR -> ticker="TTWO".
    
    JSON Schema: {{
        "accion": "ANALIZAR"|"COMPARAR"|"RECOMENDAR"|"VIGILAR"|"CHARLA", 
        "ticker": "S"|null, 
        "lista_activos": ["A", "B"]|null, 
        "estilo": "SCALPING"|"SWING",
        "categoria": "GENERAL"|"FOREX"|"ACCIONES"|"CRIPTO",
        "explicacion": "Texto breve"|null
    }}
    """
    try:
        resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user", "content":prompt}, {"role":"system", "content":"JSON only"}])
        data = json.loads(re.search(r"\{.*\}", resp.choices[0].message.content, re.DOTALL).group(0))
        
        # Normalizamos los tickers aquí mismo
        if data.get("ticker"): data["ticker"] = normalizar_ticker(data["ticker"])
        if data.get("lista_activos"): data["lista_activos"] = [normalizar_ticker(t) for t in data["lista_activos"]]
        
        return data
    except: return {"accion":"CHARLA", "categoria": "GENERAL"}

def generar_resumen_humano(datos_txt, prob):
    if not client: return "Revisa los niveles técnicos."
    accion = "COMPRAR" if prob > 0.6 else "VENDER" if prob < 0.4 else "ESPERAR"
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user", "content":f"Datos: {datos_txt}. Prob: {prob}. En 15 palabras explica por qué debo {accion}."}],
            max_tokens=45
        )
        return resp.choices[0].message.content.replace('"', '')
    except: return "Mercado volátil."

