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
    df['SMA_200'] = df['Close'].rolling(200 if len(df)>200 else 50).mean()
    
    return df.dropna(subset=['RSI', 'MACD', 'SMA_50'])

class Predictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.entrenado = False

    def entrenar(self, data):
        if data is None or len(data) < 5: return
        cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'SMA_200', 'Volatilidad'] if f in data.columns]
        try:
            self.model.fit(data[cols], data['Target'])
            self.entrenado = True
        except: self.entrenado = False

    def predecir_mañana(self, data):
        if not self.entrenado: return 0, 0.5
        try:
            cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'SMA_200', 'Volatilidad'] if f in data.columns]
            return self.model.predict(data[cols].iloc[[-1]])[0], self.model.predict_proba(data[cols].iloc[[-1]])[0][1]
        except: return 0, 0.5

# --- 3. ESCÁNER ---
async def escanear_mercado_real(categoria="GENERAL", estilo="SCALPING"):
    UNIVERSO = {
        "FOREX": ['EURUSD=X', 'GBPUSD=X', 'JPY=X', 'COP=X', 'MXN=X'],
        "CRIPTO": ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD'],
        "ACCIONES": ['AAPL', 'TSLA', 'NVDA', 'AMZN', 'MSFT', 'GLD']
    }
    lista = UNIVERSO.get(categoria, UNIVERSO["ACCIONES"][:4] + UNIVERSO["CRIPTO"][:2])
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

# --- 4. INTELIGENCIA ARTIFICIAL & DICCIONARIOS ---
client = None
if Config.GROQ_API_KEY:
    try: client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    except: pass

# DICCIONARIO DE TRADUCCIÓN (Para que no busque Apple cuando pides Rockstar)
SINONIMOS = {
    "DOLAR": "COP=X", "USD": "COP=X", "EURO": "EURUSD=X",
    "BITCOIN": "BTC-USD", "BTC": "BTC-USD",
    "ETH": "ETH-USD", "ETHEREUM": "ETH-USD",
    "ORO": "GLD", "GOLD": "GLD", "PLATA": "SLV",
    "PETROLEO": "USO", "OIL": "USO",
    "TESLA": "TSLA", "NVIDIA": "NVDA", "APPLE": "AAPL", "GOOGLE": "GOOGL", "META": "META",
    "ROCKSTAR": "TTWO", "GTA": "TTWO", "TAKE TWO": "TTWO",
    "AMAZON": "AMZN", "MICROSOFT": "MSFT"
}

def normalizar_ticker(ticker):
    if not ticker: return None
    t = ticker.upper().strip()
    return SINONIMOS.get(t, t)

def interpretar_intencion(msg):
    if not client: return {"accion": "CHARLA"}
    
    # PROMPT DE HEDGE FUND: Interpreta estrategias complejas
    prompt = f"""
    Analiza: "{msg}".
    
    Reglas:
    1. Si no hay tiempo explícito, asume "SCALPING".
    2. Si el usuario pide una ESTRATEGIA ABSTRACTA (ej: "Apostar contra EEUU", "Crisis", "Caída del mercado", "Shortear Tech"):
       -> Pon accion="COMPARAR".
       -> En "lista_activos" pon los TICKERS REALES que ganan en ese escenario (ej: SQQQ, SPXU, GLD, VIXY).
    3. JSON Only.
    
    JSON Schema: {{"accion": "ANALIZAR"|"COMPARAR"|"RECOMENDAR"|"VIGILAR"|"CHARLA", "ticker": "S"|null, "lista_activos": ["A", "B"]|null, "estilo": "SCALPING"|"SWING"}}
    """
    try:
        resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user", "content":prompt}, {"role":"system", "content":"JSON only"}])
        data = json.loads(re.search(r"\{.*\}", resp.choices[0].message.content, re.DOTALL).group(0))
        
        # Limpieza de Tickers con el Diccionario
        if data.get("ticker"): data["ticker"] = normalizar_ticker(data["ticker"])
        if data.get("lista_activos"): data["lista_activos"] = [normalizar_ticker(t) for t in data["lista_activos"]]
        
        return data
    except: return {"accion":"CHARLA"}

def generar_resumen_breve(datos_txt, prob):
    if not client: return "Análisis técnico estándar."
    seguridad = "ADVERTENCIA: Probabilidad BAJA. NO RECOMIENDES ENTRAR." if prob < 0.45 else "Probabilidad favorable."
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role":"system", "content":"Experto en Trading. Español."},
                {"role":"user", "content":f"Datos: {datos_txt}. {seguridad}. UNA FRASE CORTA (max 12 palabras) de consejo directo."}
            ],
            max_tokens=35
        )
        return resp.choices[0].message.content.replace('"', '')
    except: return "Mercado volátil."

# --- 5. MOTOR DE ANÁLISIS ---
async def motor_analisis(ticker, estilo="SCALPING"):
    await asyncio.sleep(0.5) 
    if not estilo: estilo = "SCALPING"
    inv, per = ("1d", "1y") if estilo == "SWING" else ("15m", "5d")

    try:
        df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        if df is None or df.empty:
            if estilo == "SCALPING":
                inv, per = "1d", "1y" # Fallback silencioso a diario
                df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        
        if df is None or df.empty: return None, 0.0, 0.0, None
        
        clean = preparar_datos(df)
        if clean.empty: return None, 0.0, 0.0, None
        
        # Predicción
        prob = 0.5
        if len(clean) > 15:
            brain = Predictor()
            brain.entrenar(clean.iloc[:-1])
            _, prob = brain.predecir_mañana(clean)
        
        row = clean.iloc[-1]
        
        # Señales
        if prob > 0.60: señal, icono = "ALCISTA", "🟢"
        elif prob > 0.50: señal, icono = "NEUTRAL", "⚪"
        else: señal, icono = "BAJISTA", "🔴"

        # Formato Inteligente
        fmt = ",.4f" if row['Close'] < 50 else ",.2f"
        if "COP" in ticker: fmt = ",.0f"

        # --- OBJETO DE DATOS (Vital para el formato Mini-Sniper) ---
        info = {
            "precio": format(row['Close'], fmt),
            "sl": format(row['Stop_Loss'], fmt),
            "tp": format(row['Take_Profit'], fmt),
            "rsi": f"{row['RSI']:.1f}",
            "señal": señal,
            "icono": icono,
            "ticker": ticker
        }
        
        return info, prob, row['Close'], clean
    except: return None, 0.0, 0.0, None

# --- 6. CONTROLADOR DE MENSAJES ---
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
        est = data.get("estilo", "SCALPING")
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"
    except: acc, est = "CHARLA", "SCALPING"
    
    # ---------------- CASO 1: COMPARACIÓN (Formato Mini-Sniper) ----------------
    if acc == "COMPARAR" and lst:
        titulo = "📊 **Estrategia**" if len(lst) > 3 else f"⚖️ **Comparando {len(lst)} activos**"
        msg = await update.message.reply_text(f"{titulo} ({est})...")
        
        reporte_final = f"{titulo} | {est}\n━━━━━━━━━━━━━━━━━━\n"
        activos_validos = 0
        
        for t in lst:
            info, prob, _, _ = await motor_analisis(t, est)
            if info:
                activos_validos += 1
                # TARJETA COMPACTA PARA LISTAS
                mini_card = (
                    f"💎 **{info['ticker']}**\n"
                    f"💰 ${info['precio']} | {info['icono']} {info['señal']} ({prob*100:.0f}%)\n"
                    f"🎯 TP: ${info['tp']} | ⛔ SL: ${info['sl']}\n"
                    f"〰〰〰〰〰〰〰〰〰\n"
                )
                reporte_final += mini_card
        
        await msg.delete()
        if activos_validos > 0:
            await update.message.reply_text(reporte_final, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ No encontré datos para esa estrategia.")

    # ---------------- CASO 2: ESCÁNER GENERAL ----------------
    elif acc == "RECOMENDAR":
        msg = await update.message.reply_text(f"🔎 Buscando oportunidades ({est})...")
        cands = await escanear_mercado_real("GENERAL", est)
        reporte = f"⚡ **OPORTUNIDADES {est}**\n━━━━━━━━━━━━━━━━━━\n"
        encontrado = False
        
        for t in cands:
            info, prob, _, _ = await motor_analisis(t, est)
            if prob > 0.5:
                encontrado = True
                mini_card = (
                    f"🔥 **{info['ticker']}**\n"
                    f"💰 ${info['precio']} | Prob: {prob*100:.0f}%\n"
                    f"🎯 TP: ${info['tp']}\n"
                    f"〰〰〰〰〰〰〰〰〰\n"
                )
                reporte += mini_card
                
        await msg.delete()
        if encontrado:
            await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("💤 Mercado lateral. Mejor esperar.")

    # ---------------- CASO 3: ANÁLISIS INDIVIDUAL (Full Card) ----------------
    elif acc == "ANALIZAR" and tick:
        msg = await update.message.reply_text(f"🔎 Analizando {tick}...")
        info, prob, _, _ = await motor_analisis(tick, est)
        
        if info:
            resumen = generar_resumen_breve(f"RSI:{info['rsi']}, Prob:{prob:.2f}", prob)
            
            tarjeta = (
                f"💎 **{info['ticker']}** | {est.upper()}\n"
                f"💵 **Precio:** `${info['precio']}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔮 **Señal:** {info['icono']} {info['señal']}\n"
                f"📊 **Probabilidad:** `{prob*100:.1f}%`\n"
                f"📝 **Resumen:** _{resumen}_\n"
                f"\n"
                f"🛡️ **Plan de Gestión:**\n"
                f"⛔ Stop Loss: `${info['sl']}`\n"
                f"🎯 Take Profit: `${info['tp']}`\n"
                f"\n"
                f"📉 **RSI:** `{info['rsi']}`"
            )
            await msg.delete()
            await update.message.reply_text(tarjeta, parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text(f"⚠️ No pude leer datos de {tick}.")

    elif acc == "VIGILAR" and tick:
        _, _, p, _ = await motor_analisis(tick, "SWING")
        c = cargar_cartera()
        c.append({"ticker": tick, "precio_compra": p})
        guardar_cartera(c)
        await update.message.reply_text(f"🛡️ Vigilando {tick}")

    else:
        await update.message.reply_text("👋 Soy tu Bot.\nPrueba: 'Apostar contra EEUU' o 'Analiza Rockstar'.")

# --- 7. GUARDIÁN ---
async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    c = cargar_cartera()
    if not c or not Config.TELEGRAM_CHAT_ID: return
    for i in c:
        await asyncio.sleep(2)
        _, _, now, _ = await motor_analisis(i['ticker'], "SCALPING")
        if now > 0:
            chg = (now - i['precio_compra']) / i['precio_compra']
            if abs(chg) > 0.03:
                await context.bot.send_message(Config.TELEGRAM_CHAT_ID, f"🚨 **{i['ticker']}** Mov: {chg*100:.1f}%\nPrecio: ${now:.2f}", parse_mode=ParseMode.MARKDOWN)

if __name__ == '__main__':
    if not Config.TELEGRAM_TOKEN: exit()
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_ia))
    if app.job_queue: app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
    print("🤖 BOT ACTIVO")
    app.run_polling()
