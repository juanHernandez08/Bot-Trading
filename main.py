import logging
import json
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv # Asegúrate de que esto esté aquí
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yfinance as yf 

# --- CARGAR VARIABLES DE ENTORNO ---
load_dotenv() # Esto lee el archivo .env en tu PC (y Railway usa sus Variables propias)

# --- CLASE DE CONFIGURACIÓN (INTEGRADA AQUÍ MISMO) ---
class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- TUS MÓDULOS (SRC SÍ DEBE ESTAR SUBIDO) ---
# Si src/ tampoco se subió, avísame, pero probemos arreglando config primero.
try:
    from src.features import preparar_datos
    from src.model_handler import Predictor
    from src.scanner import escanear_mercado_real
    from src.brain import (
        interpretar_intencion, 
        generar_respuesta_natural, 
        generar_recomendacion_mercado
    )
except ImportError as e:
    print(f"❌ ERROR CRÍTICO IMPORTANDO SRC: {e}")
    print("Asegúrate de que la carpeta 'src' y sus archivos (__init__.py, brain.py, etc.) estén en GitHub.")
    exit()

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- NOMBRES COSMÉTICOS ---
NOMBRES_ACTIVOS = {
    'GLD': 'Oro (ETF)',
    'USO': 'Petróleo (ETF)',
    'BTC-USD': 'Bitcoin',
    'ETH-USD': 'Ethereum',
    'TSLA': 'Tesla',
    'EURUSD=X': 'Euro/Dólar',
    'NVDA': 'NVIDIA',
    'AMZN': 'Amazon'
}

def obtener_nombre_bonito(ticker):
    return f"{NOMBRES_ACTIVOS.get(ticker, ticker)} ({ticker})"

# --- CARTERA (DATABASE SIMPLE) ---
ARCHIVO_CARTERA = 'cartera.json'

def cargar_cartera():
    try:
        if not os.path.exists(ARCHIVO_CARTERA): return []
        with open(ARCHIVO_CARTERA, 'r') as f: return json.load(f)
    except: return []

def guardar_cartera(datos):
    try:
        with open(ARCHIVO_CARTERA, 'w') as f: json.dump(datos, f)
    except Exception as e:
        print(f"Error guardando cartera: {e}")

# --- MOTOR DE ANÁLISIS ---
async def motor_analisis(ticker, estilo="SCALPING"):
    await asyncio.sleep(1) 
    
    if estilo == "SWING":
        intervalo, periodo, tipo = "1d", "1y", "Swing"
    else:
        intervalo, periodo, tipo = "15m", "5d", "Scalping"

    try:
        # Auto-adjust=True ayuda a limpiar datos raros de Yahoo
        df = yf.download(ticker, period=periodo, interval=intervalo, progress=False, auto_adjust=True)
        
        # Fallback (Respaldo) si 15m falla
        if df is None or df.empty:
            if estilo == "SCALPING":
                print(f"⚠️ {ticker}: Sin datos 15m. Backup Diario...")
                intervalo, periodo, tipo = "1d", "1y", "Swing (Backup)"
                df = yf.download(ticker, period=periodo, interval=intervalo, progress=False, auto_adjust=True)

    except Exception as e:
        print(f"Error descarga {ticker}: {e}")
        return None, 0.0, 0.0

    if df is None or df.empty: return None, 0.0, 0.0
    
    try:
        clean_data = preparar_datos(df)
        
        if clean_data.empty: return None, 0.0, 0.0

        # Separar entrenamiento (pasado) de predicción (presente)
        data_train = clean_data.iloc[:-1] 
        ultimo_dato = clean_data.iloc[[-1]]

        prob = 0.5
        if len(data_train) > 10:
            cerebro = Predictor()
            cerebro.entrenar(data_train)
            _, prob = cerebro.predecir_mañana(clean_data)
        
        # Datos de la vela actual
        fila_actual = ultimo_dato.iloc[0]
        precio = fila_actual['Close']
        stop_loss = fila_actual['Stop_Loss']
        take_profit = fila_actual['Take_Profit']
        rsi = fila_actual['RSI']
        
        # Formato decimales
        fmt = ".4f" if precio < 50 else ".2f"

        datos_txt = (
            f"MODO: {tipo}\n"
            f"ACTIVO: {ticker}\n"
            f"PRECIO: ${format(precio, fmt)}\n" 
            f"RSI: {rsi:.1f}\n"
            f"⛔ STOP LOSS: ${format(stop_loss, fmt)}\n"
            f"🎯 TAKE PROFIT: ${format(take_profit, fmt)}\n"
            f"PROBABILIDAD SUBIDA: {prob*100:.1f}%\n"
        )
        return datos_txt, prob, precio

    except Exception as e:
        print(f"Error procesando {ticker}: {e}")
        return None, 0.0, 0.0

# --- CONTROLADOR ---
async def manejar_mensaje_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    # Enviar acción "escribiendo..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    try:
        ment = interpretar_intencion(texto)
        accion = ment.get("accion", "CHARLA")
        ticker = ment.get("ticker")
        lista = ment.get("lista_activos", [])
        categoria = ment.get("categoria", "GENERAL")
        estilo = ment.get("estilo", "SCALPING")
        
        if accion == "ANALIZAR" and not ticker and not lista:
            accion = "RECOMENDAR"
            
    except:
        accion, estilo = "CHARLA", "SCALPING"
    
    print(f"🧠 {accion} | {ticker or lista}")

    # --- CASO 1: COMPARAR ---
    if accion == "COMPARAR" and lista:
        msg = await update.message.reply_text(f"⚖️ **Comparando {len(lista)} activos...**")
        reporte = ""
        for t in lista:
            await asyncio.sleep(1) # Evitar ban de Yahoo
            txt, prob, precio = await motor_analisis(t, estilo)
            if txt:
                emoji = "🏆" if prob > 0.6 else "⚠️"
                reporte += f"- {t}: ${precio:.2f} | Prob: {prob*100:.1f}% {emoji}\n"
        
        await msg.delete()
        if reporte:
            final = generar_recomendacion_mercado(reporte, "COMPARATIVA")
            await update.message.reply_text(final, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ No pude obtener datos.")

    # --- CASO 2: RECOMENDAR ---
    elif accion == "RECOMENDAR":
        msg = await update.message.reply_text(f"🔎 **Escaneando {categoria} ({estilo})...**")
        candidatos = await escanear_mercado_real(categoria, estilo)
        
        if not candidatos:
            await msg.edit_text("💤 Mercado lento.")
            return

        reporte = ""
        for i, t in enumerate(candidatos):
            txt, prob, precio = await motor_analisis(t, estilo)
            # Actualizar mensaje cada 2 activos para que el usuario vea progreso
            if i % 2 == 0:
                try: await msg.edit_text(f"⏳ Analizando {t}...") 
                except: pass
            
            if prob > 0.5:
                emoji = "🔥" if prob > 0.7 else "⚡"
                reporte += f"- {t}: ${precio:.2f} | {prob*100:.1f}% {emoji}\n"
        
        await msg.delete()
        if reporte:
            resp = generar_recomendacion_mercado(reporte, estilo)
            await update.message.reply_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("📉 Nada interesante ahora.")

    # --- CASO 3: ANALIZAR UNO ---
    elif accion == "ANALIZAR" and ticker:
        msg = await update.message.reply_text(f"🔎 Analizando **{ticker}**...")
        txt, prob, precio = await motor_analisis(ticker, estilo)
        if txt:
            resp = generar_respuesta_natural(txt, texto)
            await msg.delete()
            await update.message.reply_text(resp, parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text(f"⚠️ No encontré datos para `{ticker}`.")

    # --- CASO 4: VIGILAR ---
    elif accion == "VIGILAR" and ticker:
        _, _, p = await motor_analisis(ticker, "SWING")
        cartera = cargar_cartera()
        cartera.append({"ticker": ticker, "precio_compra": p, "fecha": str(datetime.now())})
        guardar_cartera(cartera)
        await update.message.reply_text(f"🛡️ **Vigilando {ticker}** desde ${p:.2f}")

    # --- DEFAULT ---
    else:
        await update.message.reply_text("👋 Soy tu Asesor Bursátil IA.\nDime 'Analiza Bitcoin' o 'Qué compro hoy'.")

# --- GUARDIÁN ---
async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    cartera = cargar_cartera()
    if not cartera: return

    for item in cartera:
        await asyncio.sleep(2)
        ticker = item['ticker']
        precio_orig = item['precio_compra']
        
        _, _, precio_now = await motor_analisis(ticker, "SCALPING")
        
        if precio_now > 0:
            cambio = (precio_now - precio_orig) / precio_orig
            # Alerta si se mueve más de un 3%
            if abs(cambio) > 0.03: 
                emoji = "🚀" if cambio > 0 else "🔻"
                try:
                    # OJO: Necesitas definir TELEGRAM_CHAT_ID en Railway
                    if Config.TELEGRAM_CHAT_ID:
                        await context.bot.send_message(
                            chat_id=Config.TELEGRAM_CHAT_ID,
                            text=f"🚨 **ALERTA {ticker}**\n{emoji} Movimiento: {cambio*100:.1f}%\nPrecio: ${precio_now:.2f}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                except Exception as e:
                    print(f"Error enviando alerta: {e}")

if __name__ == '__main__':
    if not Config.TELEGRAM_TOKEN:
        print("❌ Error: Falta TELEGRAM_TOKEN en las Variables de Railway")
        exit()

    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_ia))
    
    # Trabajo en segundo plano (Guardián)
    if app.job_queue:
        app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
    
    print("🤖 BOT DEPLOYED & READY EN RAILWAY")
    app.run_polling()
