import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- CONFIGURACIÓN GROQ (GRATIS Y RÁPIDO) ---
api_key = os.getenv("GROQ_API_KEY")
client = None

if not api_key:
    print("⚠️ ADVERTENCIA: No se encontró GROQ_API_KEY en .env")
else:
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        print("✅ Conectado a Groq (Llama 3.3)")
    except Exception as e:
        print(f"❌ Error conectando Groq: {e}")

MODELO_USADO = "llama-3.3-70b-versatile"

def limpiar_json(texto_sucio):
    try:
        patron = r"\{[\s\S]*\}"
        match = re.search(patron, texto_sucio)
        if match: return match.group(0)
        return texto_sucio
    except: return texto_sucio

def interpretar_intencion(mensaje_usuario):
    if not client: return {"accion": "CHARLA", "ticker": None}

    prompt = f"""
    Eres un experto financiero. Analiza: "{mensaje_usuario}"

    1. Identifica si quiere ANALIZAR (uno), COMPARAR (varios), RECOMENDAR (general) o VIGILAR.
    2. Identifica los activos. Usa símbolos de Yahoo Finance:
       - Oro = GLD (ETF)
       - Petróleo = USO (ETF)
       - Bitcoin = BTC-USD
       - Tesla = TSLA
       - Euro = EURUSD=X

    Responde SOLAMENTE un JSON con:
    {{
      "accion": "COMPARAR", "ANALIZAR", "RECOMENDAR", "VIGILAR" o "CHARLA",
      "ticker": "SIMBOLO" (si es uno solo) o null,
      "lista_activos": ["SIMBOLO1", "SIMBOLO2"...] (si son varios),
      "categoria": "GENERAL", "CRIPTO", "FOREX", "ACCIONES",
      "estilo": "SCALPING" (Si no especifica tiempo, pon SCALPING).
    }}
    """

    try:
        response = client.chat.completions.create(
            model=MODELO_USADO,
            messages=[
                {"role": "system", "content": "JSON válido solamente."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        texto = response.choices[0].message.content
        datos = json.loads(limpiar_json(texto))
        
        # Corrección lógica: Si hay lista, es comparar
        if datos.get("lista_activos") and len(datos["lista_activos"]) > 1:
            datos["accion"] = "COMPARAR"
            
        print(f"🤖 Groq: {datos}")
        return datos

    except Exception as e:
        print(f"❌ Error Brain: {e}")
        return {"accion": "CHARLA", "ticker": None, "estilo": "SCALPING"}

# EN SRC/BRAIN.PY - REEMPLAZAR SOLO LA FUNCIÓN generar_respuesta_natural

def generar_respuesta_natural(datos_tecnicos, mensaje_original):
    if not client: return f"Datos técnicos:\n{datos_tecnicos}"

    try:
        response = client.chat.completions.create(
            model=MODELO_USADO,
            messages=[
                {"role": "system", "content": "Eres un Trader Profesional y Disciplinado. Sé breve."},
                {"role": "user", "content": f"""
                Datos del mercado: 
                {datos_tecnicos}
                
                Pregunta del usuario: "{mensaje_original}"
                
                TU TAREA:
                Responde con un análisis rápido.
                OBLIGATORIO: Menciona el Precio, la Probabilidad, y SUGIERE el Stop Loss y Take Profit que te di en los datos.
                Usa emojis: ⛔ para Stop Loss y 🎯 para Take Profit.
                """}
            ]
        )
        return response.choices[0].message.content
    except: return f"Datos:\n{datos_tecnicos}"

def generar_recomendacion_mercado(oportunidades, estilo):
    if not client: return oportunidades
    try:
        response = client.chat.completions.create(
            model=MODELO_USADO,
            messages=[
                {"role": "system", "content": "Eres un Asesor Financiero directo. NO uses frases como 'Parece que', 'La lista incluye'. Simplemente presenta el informe."},
                {"role": "user", "content": f"Genera un reporte limpio para Telegram con estos datos:\n{oportunidades}\n\nFormato:\n🏆 **TÍTULO**\n\n🔸 Activo: Precio | Probabilidad % EMOJI\n(Conclusión breve)"}
            ]
        )
        return response.choices[0].message.content
    except: return oportunidades