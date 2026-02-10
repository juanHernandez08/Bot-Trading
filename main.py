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

# --- 2. EL CEREBRO MATEMÁTICO (Features & Model) ---
def preparar_datos(df):
    """Calcula indicadores técnicos."""
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Limpieza básica
    for col in ['Close', 'High', 'Low', 'Open']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df.ffill(inplace=True)

    # Indicadores RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    df['EMA_12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA_26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA_12'] - df['EMA_26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # ATR & Niveles
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df['ATR'] = ranges.max(axis=1).rolling(14).mean().bfill()
    
    atr = df['ATR'].iloc[-1]
    if pd.isna(atr):
        atr = df['Close'].iloc[-1] * 0.01
    
    df['Stop_Loss'] = df['Close'] - (atr * 1.5)
    df['Take_Profit'] = df['Close'] + (atr * 3.0)
    
    # Target
    df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
    
    # Volatilidad y Medias
    df['Volatilidad'] = df['Close'].rolling(20).std()
    df['SMA_50'] = df['Close'].rolling(50).mean()
    
    if len(df) > 200:
        df['SMA_200'] = df['Close'].rolling(200).mean()
    else:
        df['SMA_200'] = df['Close'].rolling(50).mean()
    
    return df.dropna(subset=['RSI', 'MACD', 'SMA_50'])

class Predictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.entrenado = False

    def entrenar(self, data):
        if data is None or len(data) < 5:
            return
        
        features = ['RSI', 'MACD', 'Signal', 'SMA_50', 'SMA_200', 'Volatilidad']
        cols_reales = [f for f in features if f in data.columns]
        X = data[cols_reales]
        y = data['Target']
        
        try:
            self.model.fit(X, y)
            self.entrenado = True
        except:
            self.entrenado = False

    def predecir_mañana(self, data):
        if not self.entrenado:
            return 0, 0.5
        try:
            features = ['RSI', 'MACD', 'Signal', 'SMA_50', 'SMA_200', 'Volatilidad']
            cols_reales = [f for f in features if f in data.columns]
            ultimo = data[cols_reales].iloc[[-1]]
            return self.model.predict(ultimo)[0], self.model.predict_proba(ultimo)[0][1]
        except:
            return 0, 0.5

# --- 3. EL ESCÁNER DE MERCADO ---
UNIVERSO = {
    "FOREX": ['EURUSD=X', 'GBPUSD=X', 'JPY=X', 'COP=X', 'MXN=X'],
    "CRIPTO": ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'DOGE-USD'],
    "ACCIONES": ['AAPL', 'TSLA', 'NVDA', 'AMZN', 'GOOGL', 'MSFT', 'GLD', 'USO']
}

async def escanear_mercado_real(categoria="GENERAL", estilo="SCALPING"):
    if categoria == "GENERAL":
        lista = UNIVERSO["ACCIONES"][:5] + UNIVERSO["CRIPTO"][:3] + UNIVERSO["FOREX"][:2]
    else:
        lista = UNIVERSO.get(categoria, [])
    
    if not lista: return []
    
    if estilo == "SCALPING":
        intervalo, periodo = "15m", "5d"
    else:
        intervalo, periodo = "1d", "6mo"
    
    try:
        datos = yf.download(lista, period=periodo, interval=intervalo, progress=False, auto_adjust=True)['Close']
        if isinstance(datos, pd.Series): datos = datos.to_frame()
        
        candidatos = []
        for t in lista:
            if t in datos.columns:
                precios = datos[t].dropna()
                if len(precios) > 5:
                    vol = abs((precios.iloc[-1] - precios.iloc[-4]) / precios.iloc[-4])
                    if vol > 0.002: candidatos.append(t)
        return candidatos[:5]
    except:
        return lista[:3]

# --- 4. LA MENTE (LLM / GROQ) ---
client = None
if Config.GROQ_API_KEY:
    try:
        client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    except: pass

def interpretar_intencion(msg):
    if not client: return {"accion": "CHARLA", "ticker": None}
    
    # --- PROMPT CORREGIDO: DEFAULT SCALPING ---
    prompt = f"""
    Analiza: "{msg}".
    Regla: Si el usuario NO especifica temporalidad (como 'Swing', 'Diario', 'Largo plazo'), asume SIEMPRE "SCALPING".
    Responde JSON: {{"accion": "ANALIZAR"|"COMPARAR"|"RECOMENDAR"|"VIGILAR"|"CHARLA", "ticker": "SIMBOLO"|null, "lista_activos": ["A", "B"]|null, "estilo": "SCALPING"|"SWING"}}
    """
    
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user", "content":prompt}, {"role":"system", "content":"JSON only"}]
        )
        txt = resp.choices[0].message.content
        match = re.search(r"\{.*\}", txt, re.DOTALL)
        if match: return json.loads(match.group(0))
        return {"accion":"CHARLA"}
    except:
        return {"accion":"CHARLA"}

def generar_respuesta_natural(datos, msg):
    if not client: return str(datos)
    try:
        return client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role":"system", "content":"Eres Trader Experto. Sé breve. Usa emojis."},
                {"role":"user", "content":f"Datos: {datos}. Usuario: {msg}. Responde análisis."}
            ]
        ).choices[0].message.content
    except: return str(datos)

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

# --- 5. EL CORE (Telegram Bot) ---
ARCHIVO_CARTERA = 'cartera.json'

def cargar_cartera():
    try:
        if os.path.exists(ARCHIVO_CARTERA):
            with open(ARCHIVO_CARTERA, 'r') as f: return json.load(f)
        return []
    except: return []

def guardar_cartera(d):
    try:
        with open(ARCHIVO_CARTERA, 'w') as f: json.dump(d, f)
    except: pass

async def motor_analisis(ticker, estilo="SCALPING"):
    await asyncio.sleep(1)
    # Refuerzo de seguridad: Si llega vacío, forzar Scalping
    if not estilo: estilo = "SCALPING"

    if estilo == "SWING":
        inv, per, tipo = "1d", "1y", "Swing"
    else:
        inv, per, tipo = "15m", "5d", "Scalping"
    
    try:
        df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        if df is None or df.empty:
            if estilo == "SCALPING":
                inv, per, tipo = "1d", "1y", "Swing (Backup)"
                df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        
        if df is None or df.empty: return None, 0.0, 0.0
        
        clean = preparar_datos(df)
        if clean.empty: return None, 0.0, 0.0
        
        train = clean.iloc[:-1]
        actual = clean.iloc[[-1]]
        prob = 0.5
        
        if len(train) > 10:
            brain = Predictor()
            brain.entrenar(train)
            _, prob = brain.predecir_mañana(clean)
            
        row = actual.iloc[0]
        fmt = ".4f" if row['Close'] < 50 else ".2f"
        
        txt = (f"MODO: {tipo}\nACTIVO: {ticker}\nPRECIO: ${format(row['Close'], fmt)}\n"
               f"RSI: {row['RSI']:.1f}\n⛔ STOP: ${format(row['Stop_Loss'], fmt)}\n"
               f"🎯 TAKE: ${format(row['Take_Profit'], fmt)}\nPROB: {prob*100:.1f}%")
        
        return txt, prob, row['Close']
    
    except Exception as e:
        print(f"Error {ticker}: {e}")
        return None, 0.0, 0.0

async def manejar_mensaje_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    # --- DEFAULT FORZADO A SCALPING ---
    acc = "CHARLA"
    est = "SCALPING" 

    try:
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        # Aquí forzamos el default si viene vacío
        est = data.get("estilo") or "SCALPING"

        if acc == "ANALIZAR" and not tick and not lst:
            acc = "RECOMENDAR"
    except:
        acc = "CHARLA"
        est = "SCALPING"
    
    if acc == "COMPARAR" and lst:
        msg = await update.message.reply_text(f"⚖️ Comparando {len(lst)} ({est})...")
        rep = ""
        for t in lst:
            txt, prob, p = await motor_analisis(t, est)
            if txt: rep += f"- {t}: ${p:.2f} | {prob*100:.1f}%\n"
        await msg.delete()
        if rep: await update.message.reply_text(generar_recomendacion_mercado(rep, "COMP"))
        else: await update.message.reply_text("❌ Error.")

    elif acc == "RECOMENDAR":
        msg = await update.message.reply_text(f"🔎 Escaneando ({est})...")
        cands = await escanear_mercado_real("GENERAL", est)
        rep = ""
        for t in cands:
            txt, prob, p = await motor_analisis(t, est)
            if prob > 0.5: rep += f"- {t}: ${p:.2f} | {prob*100:.1f}%\n"
        await msg.delete()
        if rep: await update.message.reply_text(generar_recomendacion_mercado(rep, est))
        else: await update.message.reply_text("💤 Nada claro.")

    elif acc == "ANALIZAR" and tick:
        msg = await update.message.reply_text(f"🔎 Analizando {tick} ({est})...")
        txt, prob, p = await motor_analisis(tick, est)
        if txt:
            final = generar_respuesta_natural(txt, texto)
            await msg.delete()
            await update.message.reply_text(final, parse_mode=ParseMode.MARKDOWN)
        else: await msg.edit_text("⚠️ Sin datos.")

    elif acc == "VIGILAR" and tick:
        _, _, p = await motor_analisis(tick, "SWING")
        c = cargar_cartera()
        c.append({"ticker": tick, "precio_compra": p})
        guardar_cartera(c)
        await update.message.reply_text(f"🛡️ Vigilando {tick}")
        
    else:
        await update.message.reply_text("👋 Soy tu Bot. Dime 'Analiza Bitcoin' o 'Qué compro'.")

async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    c = cargar_cartera()
    if not c: return
    for i in c:
        await asyncio.sleep(2)
        _, _, now = await motor_analisis(i['ticker'], "SCALPING")
        if now > 0 and Config.TELEGRAM_CHAT_ID:
            chg = (now - i['precio_compra']) / i['precio_compra']
            if abs(chg) > 0.03:
                await context.bot.send_message(Config.TELEGRAM_CHAT_ID, f"🚨 **{i['ticker']}**\nMov: {chg*100:.1f}%")

if __name__ == '__main__':
    if not Config.TELEGRAM_TOKEN:
        print("Falta Token")
        exit()
        
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_ia))
    
    if app.job_queue:
        app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
        
    print("🤖 BOT NUCLEAR ACTIVO")
    app.run_polling()
