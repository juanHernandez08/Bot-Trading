import logging
import json
import os
import asyncio
import re
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yfinance as yf 
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from openai import OpenAI

# --- 1. CONFIGURACIÓN ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- 2. CEREBRO MATEMÁTICO ---
def preparar_datos(df):
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    for col in ['Close', 'High', 'Low', 'Open']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    df.ffill(inplace=True)

    try:
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        df['EMA_12'] = df['Close'].ewm(span=12).mean()
        df['EMA_26'] = df['Close'].ewm(span=26).mean()
        df['MACD'] = df['EMA_12'] - df['EMA_26']
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        
        ranges = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift()).abs(),
            (df['Low'] - df['Close'].shift()).abs()
        ], axis=1)
        df['ATR'] = ranges.max(axis=1).rolling(14).mean().bfill()
        
        atr = df['ATR'].iloc[-1]
        if pd.isna(atr): atr = df['Close'].iloc[-1] * 0.01
        
        df['Stop_Loss'] = df['Close'] - (atr * 1.5)
        df['Take_Profit'] = df['Close'] + (atr * 3.0)
        
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        df['Volatilidad'] = df['Close'].rolling(20).std()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        
        return df.dropna(subset=['RSI', 'Close'])
    except: return pd.DataFrame()

class Predictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.entrenado = False

    def entrenar(self, data):
        if data is None or len(data) < 5: return
        cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'Volatilidad'] if f in data.columns]
        try:
            self.model.fit(data[cols], data['Target'])
            self.entrenado = True
        except: self.entrenado = False

    def predecir_mañana(self, data):
        if not self.entrenado: return 0, 0.5
        try:
            cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'Volatilidad'] if f in data.columns]
            return self.model.predict(data[cols].iloc[[-1]])[0], self.model.predict_proba(data[cols].iloc[[-1]])[0][1]
        except: return 0, 0.5

# --- 3. DICCIONARIO GLOBAL "EL ESTRATEGA" ---
SINONIMOS = {
    # --- EMPRESAS ---
    "ROCKSTAR": "TTWO", "GTA": "TTWO", "TAKE TWO": "TTWO", "TTWO": "TTWO",
    "TESLA": "TSLA", "NVIDIA": "NVDA", "APPLE": "AAPL", "GOOGLE": "GOOGL", "META": "META",
    "AMAZON": "AMZN", "MICROSOFT": "MSFT", "NETFLIX": "NFLX", "MERCADO LIBRE": "MELI", "NU BANK": "NU",

    # --- ESTRATEGIAS CONTRA POTENCIAS ---
    "CHINA": "YANG", "CONTRA CHINA": "YANG",
    "EEUU": "SQQQ", "CONTRA EEUU": "SQQQ", "USA": "SQQQ",
    "EUROPA": "EPV", "CONTRA EUROPA": "EPV", "ALEMANIA": "EPV",
    "JAPON": "EWV", "CONTRA JAPON": "EWV",

    # --- LATINOAMÉRICA & EMERGENTES (FOREX / DEFENSA) ---
    # Lógica: Si apuestas contra el país, compras Dólares (La moneda local se devalúa)
    "COLOMBIA": "GXG", "CONTRA COLOMBIA": "COP=X",
    "MEXICO": "EWW", "CONTRA MEXICO": "MXN=X",
    "CHILE": "ECH", "CONTRA CHILE": "USDCLP=X",
    "PERU": "EPU", "CONTRA PERU": "USDPEN=X",
    "BRASIL": "EWZ", "CONTRA BRASIL": "BZQ", # Brasil tiene ETF Inverso
    "ARGENTINA": "ARGT", "CONTRA ARGENTINA": "USDARS=X", # Dólar oficial (referencia)
    "COSTA RICA": "USDCRC=X", "CONTRA COSTA RICA": "USDCRC=X",
    
    # --- ECONOMÍAS DOLARIZADAS O COMPLEJAS (REFUGIO) ---
    # Si la economía de estos países falla, lo mejor es Oro o Bitcoin
    "VENEZUELA": "BTC-USD", "CONTRA VENEZUELA": "BTC-USD",
    "ECUADOR": "GLD", "CONTRA ECUADOR": "GLD",
    "PANAMA": "GLD", "CONTRA PANAMA": "GLD",
    "CUBA": "BTC-USD", "CONTRA CUBA": "BTC-USD",
    "PUERTO RICO": "GLD", "CONTRA PUERTO RICO": "GLD",
    "EL SALVADOR": "BTC-USD", "CONTRA EL SALVADOR": "GLD",

    # --- ACTIVOS ---
    "DOLAR": "COP=X", "USD": "COP=X", "PESO": "COP=X",
    "EURO": "EURUSD=X", "EUR": "EURUSD=X",
    "BITCOIN": "BTC-USD", "BTC": "BTC-USD",
    "ETH": "ETH-USD", "ORO": "GLD", "PLATA": "SLV", "PETROLEO": "USO"
}

def normalizar_ticker(ticker):
    if not ticker: return None
    t = ticker.upper().strip()
    # Búsqueda difusa (si la palabra clave está dentro del mensaje)
    for clave, valor in SINONIMOS.items():
        if clave in t: return valor
    return t.replace(" ", "")

# --- 4. ESCÁNER ---
async def escanear_mercado_real(categoria="GENERAL", estilo="SCALPING"):
    UNIVERSO = {
        "FOREX": ['EURUSD=X', 'GBPUSD=X', 'JPY=X', 'COP=X', 'MXN=X', 'USDCLP=X', 'USDPEN=X'],
        "CRIPTO": ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD'],
        "ACCIONES": ['AAPL', 'TSLA', 'NVDA', 'AMZN', 'MSFT', 'GLD', 'TTWO', 'NU', 'MELI'],
        "GENERAL": ['AAPL', 'BTC-USD', 'EURUSD=X', 'GLD', 'NVDA', 'COP=X']
    }
    lista = UNIVERSO.get(categoria, UNIVERSO["GENERAL"])
    inter, per = ("15m", "5d") if estilo == "SCALPING" else ("1d", "6mo")
    try:
        df = yf.download(lista, period=per, interval=inter, progress=False, auto_adjust=True)['Close']
        if isinstance(df, pd.Series): df = df.to_frame()
        cands = []
        for t in lista:
            if t in df.columns:
                p = df[t].dropna()
                if len(p) > 5:
                    vol = abs((p.iloc[-1] - p.iloc[-4])/p.iloc[-4])
                    if vol > 0.001: cands.append(t)
        return cands[:5]
    except: return lista[:3]

# --- 5. IA ---
client = None
if Config.GROQ_API_KEY:
    try: client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    except: pass

def interpretar_intencion(msg):
    if not client: return {"accion": "CHARLA"}
    prompt = f"""
    Analiza: "{msg}".
    1. CATEGORIA: "FOREX", "ACCIONES", "CRIPTO", "GENERAL".
    2. ESTRATEGIA: Si pide contra pais/crisis -> accion="COMPARAR", lista_activos=[TICKERS REALES DEL DICCIONARIO], explicacion="Frase corta del porqué".
    3. JSON Only.
    
    JSON Schema: {{
        "accion": "ANALIZAR"|"COMPARAR"|"RECOMENDAR"|"VIGILAR"|"CHARLA", 
        "ticker": "S"|null, 
        "lista_activos": ["A", "B"]|null, 
        "estilo": "SCALPING"|"SWING",
        "categoria": "GENERAL"|"FOREX"|"ACCIONES"|"CRIPTO",
        "explicacion": "Texto"|null
    }}
    """
    try:
        resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user", "content":prompt}, {"role":"system", "content":"JSON only"}])
        data = json.loads(re.search(r"\{.*\}", resp.choices[0].message.content, re.DOTALL).group(0))
        if data.get("ticker"): data["ticker"] = normalizar_ticker(data["ticker"])
        if data.get("lista_activos"): data["lista_activos"] = [normalizar_ticker(t) for t in data["lista_activos"]]
        return data
    except: return {"accion":"CHARLA", "categoria": "GENERAL"}

def generar_resumen_humano(datos_txt, prob):
    """Genera una explicación simple para principiantes."""
    if not client: return "Revisa los indicadores técnicos."
    
    accion = "COMPRAR" if prob > 0.6 else "VENDER" if prob < 0.4 else "ESPERAR"
    
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user", "content":f"Datos: {datos_txt}. Probabilidad: {prob}. Explica en 15 palabras por qué debo {accion}. Usa lenguaje muy simple."}],
            max_tokens=40
        )
        return resp.choices[0].message.content.replace('"', '')
    except: return "Mercado volátil, ten cuidado."

# --- 6. MOTOR ANALÍTICO ---
async def motor_analisis(ticker, estilo="SCALPING"):
    await asyncio.sleep(0.5) 
    if not estilo: estilo = "SCALPING"
    inv, per = ("1d", "1y") if estilo == "SWING" else ("15m", "5d")
    backup_mode = False

    try:
        df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 5:
            inv, per = "1d", "1y"
            df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
            backup_mode = True
        
        if df is None or df.empty or len(df) < 5: return None, 0.0, 0.0, None
        
        clean = preparar_datos(df)
        if clean.empty: return None, 0.0, 0.0, None
        
        prob = 0.5
        if len(clean) > 15:
            brain = Predictor()
            brain.entrenar(clean.iloc[:-1])
            _, prob = brain.predecir_mañana(clean)
        
        row = clean.iloc[-1]
        
        # --- VEREDICTO CLARO ---
        if prob > 0.65: señal, icono, accion_txt = "ALCISTA", "🟢", "COMPRAR AHORA 🚀"
        elif prob > 0.55: señal, icono, accion_txt = "MODERADA", "🟢", "COMPRA CON CUIDADO ✅"
        elif prob < 0.40: señal, icono, accion_txt = "BAJISTA", "🔴", "NO COMPRAR / VENDER ❌"
        else: señal, icono, accion_txt = "NEUTRAL", "⚪", "MEJOR ESPERAR ✋"

        fmt = ",.4f" if row['Close'] < 50 else ",.2f"
        if "COP" in ticker or "CLP" in ticker or "ARS" in ticker: fmt = ",.0f"

        info = {
            "precio": format(row['Close'], fmt),
            "sl": format(row['Stop_Loss'], fmt),
            "tp": format(row['Take_Profit'], fmt),
            "rsi": f"{row['RSI']:.1f}",
            "señal": señal,
            "icono": icono,
            "ticker": ticker,
            "backup": backup_mode,
            "veredicto": accion_txt # Nuevo campo para principiantes
        }
        return info, prob, row['Close'], clean
    except: return None, 0.0, 0.0, None

# --- 7. CONTROLADOR ---
ARCHIVO_CARTERA = 'cartera.json'
def cargar_cartera():
    try: return json.load(open(ARCHIVO_CARTERA)) if os.path.exists(ARCHIVO_CARTERA) else []
    except: return []
def guardar_cartera(d):
    try: json.dump(d, open(ARCHIVO_CARTERA, 'w'))
    except: pass

async def manejar_mensaje_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    try:
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        est = data.get("estilo")
        cat = data.get("categoria", "GENERAL")
        explicacion = data.get("explicacion")
        
        if not est: est = "SCALPING"
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"
    except: acc, est, cat, explicacion = "CHARLA", "SCALPING", "GENERAL", None
    
    if acc == "COMPARAR" and lst:
        titulo = "📊 **Estrategia**" if explicacion else "⚖️ **Comparando**"
        msg = await update.message.reply_text(f"{titulo}...")
        reporte = f"{titulo}\n" + (f"💡 _{explicacion}_\n" if explicacion else "") + "━━━━━━━━━━━━━━━━━━\n"
        
        found = False
        for t in lst:
            info, prob, _, _ = await motor_analisis(t, est)
            if info:
                found = True
                reporte += f"💎 **{info['ticker']}**\n💰 ${info['precio']} | {info['veredicto']}\n🎯 TP: ${info['tp']} | ⛔ SL: ${info['sl']}\n〰〰〰〰〰〰〰〰〰\n"
        await msg.delete()
        if found: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
        else: await update.message.reply_text("❌ Sin datos.")

    elif acc == "RECOMENDAR":
        msg = await update.message.reply_text(f"🔎 Buscando en **{cat}**...")
        cands = await escanear_mercado_real(cat, est)
        reporte = f"⚡ **MEJORES {cat}**\n━━━━━━━━━━━━━━━━━━\n"
        found = False
        for t in cands:
            info, prob, _, _ = await motor_analisis(t, est)
            if prob > 0.5:
                found = True
                reporte += f"🔥 **{info['ticker']}**\n💰 ${info['precio']} | {info['veredicto']}\n🎯 TP: ${info['tp']}\n〰〰〰〰〰〰〰〰〰\n"
        await msg.delete()
        if found: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
        else: await update.message.reply_text(f"💤 Sin oportunidades claras en {cat}.")

    elif acc == "ANALIZAR" and tick:
        msg = await update.message.reply_text(f"🔎 Analizando {tick}...")
        info, prob, _, _ = await motor_analisis(tick, est)
        if info:
            resumen = generar_resumen_humano(f"RSI:{info['rsi']}, Prob:{prob:.2f}", prob)
            aviso_modo = " | ⚠️ DIARIO" if info['backup'] else f" | {est.upper()}"
            
            tarjeta = (
                f"💎 **{info['ticker']}**{aviso_modo}\n"
                f"💵 **Precio:** `${info['precio']}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💡 **CONCLUSIÓN:**\n"
                f"👉 **{info['veredicto']}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📝 **Por qué:** _{resumen}_\n\n"
                f"🛡️ **Plan de Gestión:**\n"
                f"⛔ Stop Loss: `${info['sl']}`\n"
                f"🎯 Take Profit: `${info['tp']}`\n"
            )
            await msg.delete()
            await update.message.reply_text(tarjeta, parse_mode=ParseMode.MARKDOWN)
        else: await msg.edit_text(f"⚠️ No pude leer datos de {tick}.")

    elif acc == "VIGILAR" and tick:
        _, _, p, _ = await motor_analisis(tick, "SWING")
        c = cargar_cartera()
        c.append({"ticker": tick, "precio_compra": p})
        guardar_cartera(c)
        await update.message.reply_text(f"🛡️ Vigilando {tick}")

    else: await update.message.reply_text("👋 Soy tu Bot.\nDime 'Analiza Rockstar' o 'Contra Chile'.")

async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    c = cargar_cartera()
    if not c or not Config.TELEGRAM_CHAT_ID: return
    for i in c:
        await asyncio.sleep(2)
        _, _, now, _ = await motor_analisis(i['ticker'], "SCALPING")
        if now > 0:
            chg = (now - i['precio_compra']) / i['precio_compra']
            if abs(chg) > 0.03:
                await context.bot.send_message(Config.TELEGRAM_CHAT_ID, f"🚨 **{i['ticker']}** Mov: {chg*100:.1f}%", parse_mode=ParseMode.MARKDOWN)

if __name__ == '__main__':
    if not Config.TELEGRAM_TOKEN: exit()
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_ia))
    if app.job_queue: app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
    print("🤖 BOT GLOBAL ACTIVO")
    app.run_polling()
