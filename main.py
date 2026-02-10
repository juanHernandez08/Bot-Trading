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

# --- 3. ESCÁNER DE MERCADO ---
UNIVERSO = {
    "FOREX": ['EURUSD=X', 'GBPUSD=X', 'JPY=X', 'COP=X', 'MXN=X'],
    "CRIPTO": ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'DOGE-USD'],
    "ACCIONES": ['AAPL', 'TSLA', 'NVDA', 'AMZN', 'GOOGL', 'MSFT', 'GLD', 'USO']
}

async def escanear_mercado_real(categoria="GENERAL", estilo="SCALPING"):
    lista = UNIVERSO.get(categoria, UNIVERSO["ACCIONES"][:5] + UNIVERSO["CRIPTO"][:3])
    inter, per = ("15m", "5d") if estilo == "SCALPING" else ("1d", "6mo")
    try:
        df = yf.download(lista, period=per, interval=inter, progress=False, auto_adjust=True)['Close']
        if isinstance(df, pd.Series): df = df.to_frame()
        cands = []
        for t in lista:
            if t in df.columns:
                p = df[t].dropna()
                if len(p) > 5 and abs((p.iloc[-1] - p.iloc[-4])/p.iloc[-4]) > 0.002: cands.append(t)
        return cands[:5]
    except: return lista[:3]

# --- 4. INTELIGENCIA ARTIFICIAL (GROQ) ---
client = None
if Config.GROQ_API_KEY:
    try: client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    except: pass

# --- DICCIONARIO DE CORRECCIÓN (LO NUEVO) ---
SINONIMOS = {
    "DOLAR": "COP=X",
    "DÓLAR": "COP=X",
    "USD": "COP=X",
    "EURO": "EURUSD=X",
    "BITCOIN": "BTC-USD",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD",
    "ORO": "GLD",
    "PETROLEO": "USO"
}

def normalizar_ticker(ticker):
    if not ticker: return None
    t = ticker.upper().strip()
    return SINONIMOS.get(t, t)

def interpretar_intencion(msg):
    if not client: return {"accion": "CHARLA"}
    prompt = f"""Analiza: "{msg}". Regla: Si no hay tiempo, asume SCALPING.
    JSON: {{"accion": "ANALIZAR"|"COMPARAR"|"RECOMENDAR"|"VIGILAR"|"CHARLA", "ticker": "SIMBOLO"|null, "lista_activos": ["A"]|null, "estilo": "SCALPING"|"SWING"}}"""
    try:
        resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user", "content":prompt}, {"role":"system", "content":"JSON only"}])
        data = json.loads(re.search(r"\{.*\}", resp.choices[0].message.content, re.DOTALL).group(0))
        
        # APLICAR CORRECCIÓN
        if data.get("ticker"): data["ticker"] = normalizar_ticker(data["ticker"])
        if data.get("lista_activos"): data["lista_activos"] = [normalizar_ticker(t) for t in data["lista_activos"]]
        
        return data
    except: return {"accion":"CHARLA"}

def generar_resumen_breve(datos_txt, prob):
    """Genera frase condicionada a la probabilidad matemática."""
    if not client: return "Análisis técnico estándar."
    
    # Instrucción de seguridad: Si probabilidad es baja, PROHIBIDO recomendar entrar.
    seguridad = "ADVERTENCIA: La probabilidad es BAJA (<40%). NO RECOMIENDES ENTRAR. Sugiere esperar o vender." if prob < 0.4 else "Probabilidad favorable."
    
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role":"system", "content":"Eres un experto en Trading. Responde en Español."},
                {"role":"user", "content":f"Datos: {datos_txt}. {seguridad}. Escribe UNA SOLA FRASE de máximo 15 palabras explicando la decisión."}
            ],
            max_tokens=45
        )
        return resp.choices[0].message.content.replace('"', '')
    except: return "Mercado volátil, precaución."

def generar_recomendacion_mercado(reporte, estilo):
    if not client: return reporte
    try:
        return client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role":"system", "content":"Formatea esto para Telegram bonito."},
                {"role":"user", "content":reporte}
            ]
        ).choices[0].message.content
    except: return reporte

# --- 5. CONTROLADOR PRINCIPAL ---
ARCHIVO_CARTERA = 'cartera.json'
def cargar_cartera():
    try: return json.load(open(ARCHIVO_CARTERA)) if os.path.exists(ARCHIVO_CARTERA) else []
    except: return []
def guardar_cartera(d):
    try: json.dump(d, open(ARCHIVO_CARTERA, 'w'))
    except: pass

async def motor_analisis(ticker, estilo="SCALPING"):
    await asyncio.sleep(1)
    if not estilo: estilo = "SCALPING"
    inv, per = ("1d", "1y") if estilo == "SWING" else ("15m", "5d")

    try:
        df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        if df is None or df.empty:
            if estilo == "SCALPING":
                estilo = "SWING (Backup)"
                inv, per = "1d", "1y"
                df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        
        if df is None or df.empty: return None, 0.0, 0.0
        
        clean = preparar_datos(df)
        if clean.empty: return None, 0.0, 0.0
        
        prob = 0.5
        if len(clean) > 15:
            brain = Predictor()
            brain.entrenar(clean.iloc[:-1])
            _, prob = brain.predecir_mañana(clean)
        
        row = clean.iloc[-1]
        
        if prob > 0.60: señal, icono = "FUERTE ALCISTA", "🟢🔥"
        elif prob > 0.50: señal, icono = "MODERADA ALCISTA", "🟢"
        else: señal, icono = "NEUTRAL / BAJISTA", "⚪⚠️"

        # Ajuste de decimales según el precio
        fmt = ",.4f" if row['Close'] < 50 else ",.2f"
        # Caso especial para COP (Pesos) que no usa decimales
        if "COP" in ticker: fmt = ",.0f"

        # Generar resumen con la probabilidad en mente
        contexto_ia = f"RSI:{row['RSI']:.1f}, Prob:{prob:.2f}, Tendencia:{señal}"
        resumen = generar_resumen_breve(contexto_ia, prob)

        tarjeta = (
            f"💎 **{ticker}** | {estilo.upper()}\n"
            f"💵 **Precio:** `${format(row['Close'], fmt)}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔮 **Señal:** {icono} {señal}\n"
            f"📊 **Probabilidad:** `{prob*100:.1f}%`\n"
            f"📝 **Resumen:** _{resumen}_\n"
            f"\n"
            f"🛡️ **Plan de Gestión:**\n"
            f"⛔ Stop Loss: `${format(row['Stop_Loss'], fmt)}`\n"
            f"🎯 Take Profit: `${format(row['Take_Profit'], fmt)}`\n"
            f"\n"
            f"📉 **RSI:** `{row['RSI']:.1f}`"
        )
        
        return tarjeta, prob, row['Close']

    except Exception as e:
        print(f"Error {ticker}: {e}")
        return None, 0.0, 0.0

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
    
    if acc == "COMPARAR" and lst:
        msg = await update.message.reply_text(f"⚖️ Comparando {len(lst)}...")
        rep = ""
        for t in lst:
            card, prob, p = await motor_analisis(t, est)
            if card: 
                icono = "🟢" if prob > 0.55 else "⚪"
                rep += f"{icono} **{t}**: ${p:.2f} (Prob: {prob*100:.1f}%)\n"
        await msg.delete()
        await update.message.reply_text(rep or "❌ Error", parse_mode=ParseMode.MARKDOWN)

    elif acc == "RECOMENDAR":
        msg = await update.message.reply_text(f"🔎 Escaneando {est}...")
        cands = await escanear_mercado_real("GENERAL", est)
        rep = ""
        for t in cands:
            card, prob, p = await motor_analisis(t, est)
            if prob > 0.5:
                rep += f"🔥 **{t}**: ${p:.2f} | Prob: {prob*100:.1f}%\n"
        await msg.delete()
        await update.message.reply_text(f"📊 **Oportunidades {est}:**\n\n{rep}" if rep else "💤 Mercado lateral.", parse_mode=ParseMode.MARKDOWN)

    elif acc == "ANALIZAR" and tick:
        msg = await update.message.reply_text(f"🔎 Analizando {tick}...")
        tarjeta, prob, p = await motor_analisis(tick, est)
        await msg.delete()
        if tarjeta:
            await update.message.reply_text(tarjeta, parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text("⚠️ No pude leer los datos.")

    elif acc == "VIGILAR" and tick:
        _, _, p = await motor_analisis(tick, "SWING")
        c = cargar_cartera()
        c.append({"ticker": tick, "precio_compra": p})
        guardar_cartera(c)
        await update.message.reply_text(f"🛡️ Vigilando {tick} desde ${p:.2f}")

    else:
        await update.message.reply_text("👋 Soy tu Bot.\nEscribe: 'Analiza Bitcoin' o 'Qué compro'.")

async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    c = cargar_cartera()
    if not c or not Config.TELEGRAM_CHAT_ID: return
    for i in c:
        await asyncio.sleep(2)
        _, _, now = await motor_analisis(i['ticker'], "SCALPING")
        if now > 0:
            chg = (now - i['precio_compra']) / i['precio_compra']
            if abs(chg) > 0.03:
                await context.bot.send_message(Config.TELEGRAM_CHAT_ID, f"🚨 **{i['ticker']}** se movió {chg*100:.1f}%!\nPrecio: ${now:.2f}", parse_mode=ParseMode.MARKDOWN)

if __name__ == '__main__':
    if not Config.TELEGRAM_TOKEN: exit()
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_ia))
    if app.job_queue: app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
    print("🤖 BOT ACTIVO")
    app.run_polling()
