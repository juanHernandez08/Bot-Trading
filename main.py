import logging
import json
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yfinance as yf 

# --- CARGAR VARIABLES ---
load_dotenv()

class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- IMPORTACIÓN INTELIGENTE ---
try:
    # Intenta buscar 'src'
    from src.features import preparar_datos
    from src.model_handler import Predictor
    from src.scanner import escanear_mercado_real
    from src.brain import interpreting_intencion, generar_respuesta_natural, generar_recomendacion_mercado
    # Nota: Si brain tiene otro nombre de funciones, ajústalo aquí. Asumo que son estas.
    from src.brain import interpretar_intencion # Corrección nombre
    print("✅ Módulos cargados desde carpeta 'src/'")
except ImportError:
    # Si falla, busca en la raíz
    try:
        from features import preparar_datos
        from model_handler import Predictor
        from scanner import escanear_mercado_real
        from brain import interpretar_intencion, generar_respuesta_natural, generar_recomendacion_mercado
        print("✅ Módulos cargados desde la raíz (archivos sueltos)")
    except ImportError as e:
        print(f"❌ ERROR CRÍTICO: No encuentro los archivos. {e}")
        exit()

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- NOMBRES COSMÉTICOS ---
NOMBRES_ACTIVOS = {
    'GLD': 'Oro (ETF)', 'USO': 'Petróleo (ETF)', 'BTC-USD': 'Bitcoin',
    'ETH-USD': 'Ethereum', 'TSLA': 'Tesla', 'EURUSD=X': 'Euro/Dólar',
    'COP=X': 'Peso Colombiano', 'MXN=X': 'Peso Mexicano'
}

def obtener_nombre_bonito(ticker):
    return f"{NOMBRES_ACTIVOS.get(ticker, ticker)} ({ticker})"

# --- CARTERA (DATABASE SIMPLE) ---
ARCHIVO_CARTERA = 'cartera.json'

def cargar_cartera():
    try:
        if not os.path.exists(ARCHIVO_CARTERA):
            return []
        with open(ARCHIVO_CARTERA, 'r') as f:
            return json.load(f)
    except:
        return []

def guardar_cartera(datos):
    try:
        with open(ARCHIVO_CARTERA, 'w') as f:
            json.dump(datos, f)
    except:
        pass

# --- MOTOR DE ANÁLISIS ---
async def motor_analisis(ticker, estilo="SCALPING"):
    await asyncio.sleep(1) 
    if estilo == "SWING":
        intervalo, periodo, tipo = "1d", "1y", "Swing"
    else:
        intervalo, periodo, tipo = "15m", "5d", "Scalping"

    try:
        df = yf.download(ticker, period=periodo, interval=intervalo, progress=False, auto_adjust=True)
        if df is None or df.empty:
            if estilo == "SCALPING":
                print(f"⚠️ {ticker}: Backup Diario activado...")
                intervalo, periodo, tipo = "1d", "1y", "Swing (Backup)"
                df = yf.download(ticker, period=periodo, interval=intervalo, progress=False, auto_adjust=True)
    except:
        return None, 0.0, 0.0

    if df is None or df.empty:
        return None, 0.0, 0.0
    
    try:
        clean_data = preparar_datos(df)
        if clean_data.empty:
            return None, 0.0, 0.0
        
        data_train = clean_data.iloc[:-1] 
        ultimo_dato = clean_data.iloc[[-1]]

        prob = 0.5
        if len(data_train) > 10:
            cerebro = Predictor()
            cerebro.entrenar(data_train)
            _, prob = cerebro.predecir_mañana(clean_data)
        
        fila = ultimo_dato.iloc[0]
        fmt = ".4f" if fila['Close'] < 50 else ".2f"
        
        datos_txt = (
            f"MODO: {tipo}\nACTIVO: {ticker}\nPRECIO: ${format(fila['Close'], fmt)}\n"
            f"RSI: {fila['RSI']:.1f}\n⛔ STOP LOSS: ${format(fila['Stop_Loss'], fmt)}\n"
            f"🎯 TAKE PROFIT: ${format(fila['Take_Profit'], fmt)}\nPROBABILIDAD: {prob*100:.1f}%"
        )
        return datos_txt, prob, fila['Close']
    except:
        return None, 0.0, 0.0

# --- CONTROLADOR ---
async def manejar_mensaje_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    try:
        ment = interpretar_intencion(texto)
        accion = ment.get("accion", "CHARLA")
        ticker = ment.get("ticker")
        lista = ment.get("lista_activos", [])
        estilo = ment.get("estilo", "SCALPING")
        if accion == "ANALIZAR" and not ticker and not lista:
            accion = "RECOMENDAR"
    except:
        accion, estilo = "CHARLA", "SCALPING"
    
    print(f"🧠 {accion} | {ticker or lista}")

    if accion == "COMPARAR" and lista:
        msg = await update.message.reply_text(f"⚖️ **Comparando {len(lista)} activos...**")
        reporte = ""
        for t in lista:
            await asyncio.sleep(1)
            txt, prob, precio = await motor_analisis(t, estilo)
            if txt:
                reporte += f"- {t}: ${precio:.2f} | {prob*100:.1f}%\n"
        await msg.delete()
        if reporte:
            await update.message.reply_text(generar_recomendacion_mercado(reporte, "COMPARATIVA"), parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Sin datos.")

    elif accion == "RECOMENDAR":
        msg = await update.message.reply_text("🔎 **Escaneando...**")
        candidatos = await escanear_mercado_real("GENERAL", estilo)
        if not candidatos: 
            await msg.edit_text("💤 Mercado lento.")
            return
        
        reporte = ""
        for t in candidatos:
            txt, prob, precio = await motor_analisis(t, estilo)
            if prob > 0.5:
                reporte += f"- {t}: ${precio:.2f} | {prob*100:.1f}%\n"
        
        await msg.delete()
        if reporte:
            await update.message.reply_text(generar_recomendacion_mercado(reporte, estilo), parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("📉 Nada claro ahora.")

    elif accion == "ANALIZAR" and ticker:
        msg = await update.message.reply_text(f"🔎 Analizando **{ticker}**...")
        txt, prob, precio = await motor_analisis(ticker, estilo)
        if txt:
            resp = generar_respuesta_natural(txt, texto)
            await msg.delete()
            await update.message.reply_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text("⚠️ No encontré datos.")

    elif accion == "VIGILAR" and ticker:
        _, _, p = await motor_analisis(ticker, "SWING")
        cartera = cargar_cartera()
        cartera.append({"ticker": ticker, "precio_compra": p})
        guardar_cartera(cartera)
        await update.message.reply_text(f"🛡️ Vigilando {ticker}")

    else:
        await update.message.reply_text("👋 Soy tu Bot de Trading. Dime 'Analiza Bitcoin'.")

async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    cartera = cargar_cartera()
    if not cartera: return
    for item in cartera:
        await asyncio.sleep(2)
        ticker = item['ticker']
        _, _, precio_now = await motor_analisis(ticker, "SCALPING")
        if precio_now > 0 and Config.TELEGRAM_CHAT_ID:
            cambio = (precio_now - item['precio_compra']) / item['precio_compra']
            if abs(cambio) > 0.03:
                emoji = "🚀" if cambio > 0 else "🔻"
                await context.bot.send_message(chat_id=Config.TELEGRAM_CHAT_ID, text=f"🚨 **ALERTA {ticker}**\n{emoji} Movimiento: {cambio*100:.1f}%")

if __name__ == '__main__':
    if not Config.TELEGRAM_TOKEN:
        print("❌ ERROR: Falta TELEGRAM_TOKEN")
        exit()
        
    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_ia))
    
    if app.job_queue:
        app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
        
    print("🤖 BOT ACTIVO EN RAILWAY")
    app.run_polling()
