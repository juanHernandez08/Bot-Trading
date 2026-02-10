import logging
import json
import os
import asyncio
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yfinance as yf 

# --- TUS MÓDULOS ---
from config.settings import Config
from src.features import preparar_datos
from src.model_handler import Predictor
from src.scanner import escanear_mercado_real
from src.brain import (
    interpretar_intencion, 
    generar_respuesta_natural, 
    generar_recomendacion_mercado
)

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

# --- CARTERA ---
ARCHIVO_CARTERA = 'cartera.json'
def cargar_cartera():
    try:
        with open(ARCHIVO_CARTERA, 'r') as f: return json.load(f)
    except: return []
def guardar_cartera(datos):
    with open(ARCHIVO_CARTERA, 'w') as f: json.dump(datos, f)

# --- MOTOR DE ANÁLISIS ---
# EN MAIN.PY - REEMPLAZAR LA FUNCIÓN motor_analisis

async def motor_analisis(ticker, estilo="SCALPING"):
    await asyncio.sleep(1) 
    
    if estilo == "SWING":
        intervalo, periodo, tipo = "1d", "1y", "Swing"
    else:
        intervalo, periodo, tipo = "15m", "5d", "Scalping" # Aumentamos buffer

    try:
        # Forzamos descarga de datos planos
        df = yf.download(ticker, period=periodo, interval=intervalo, progress=False, auto_adjust=True)
        
        if df is None or df.empty:
            if estilo == "SCALPING":
                print(f"⚠️ {ticker}: Sin datos 15m. Backup Diario...")
                intervalo, periodo, tipo = "1d", "1y", "Swing (Backup)"
                df = yf.download(ticker, period=periodo, interval=intervalo, progress=False, auto_adjust=True)

    except Exception as e:
        print(f"Error DL {ticker}: {e}")
        return None, 0.0, 0.0

    if df is None or df.empty: return None, 0.0, 0.0
    
    try:
        clean_data = preparar_datos(df)
        
        # Necesitamos al menos 1 fila
        if clean_data.empty: 
            print(f"⚠️ {ticker}: Datos insuficientes tras limpieza.")
            return None, 0.0, 0.0

        # --- SEPARAR DATOS ---
        # 1. Datos para ENTRENAR (Todo menos la última fila, porque necesitamos Target real)
        data_train = clean_data.iloc[:-1] 
        
        # 2. Dato para PREDECIR (La última fila, es la vela actual)
        ultimo_dato = clean_data.iloc[[-1]]

        prob = 0.5
        # Solo entrenamos si hay suficientes datos históricos
        if len(data_train) > 10:
            cerebro = Predictor()
            cerebro.entrenar(data_train)
            _, prob = cerebro.predecir_mañana(clean_data) # Predice sobre el set completo
        
        # Extraer info de la vela ACTUAL
        fila_actual = ultimo_dato.iloc[0]
        precio = fila_actual['Close']
        stop_loss = fila_actual['Stop_Loss']
        take_profit = fila_actual['Take_Profit']
        rsi = fila_actual['RSI']
        
        datos_txt = (
            f"MODO: {tipo}\n"
            f"ACTIVO: {ticker}\n"
            f"PRECIO: ${precio:.4f}\n" # 4 decimales para Forex
            f"RSI: {rsi:.1f}\n"
            f"⛔ STOP LOSS: ${stop_loss:.4f}\n"
            f"🎯 TAKE PROFIT: ${take_profit:.4f}\n"
            f"PROBABILIDAD SUBIDA: {prob*100:.1f}%\n"
        )
        
        return datos_txt, prob, precio

    except Exception as e:
        print(f"Error procesando {ticker}: {e}")
        import traceback
        traceback.print_exc() # Para ver el error real en consola
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
        categoria = ment.get("categoria", "GENERAL")
        estilo = ment.get("estilo", "SCALPING")
        
        # --- PARCHE DE LÓGICA ---
        # Si dice ANALIZAR pero no hay ticker ni lista, es RECOMENDAR
        if accion == "ANALIZAR" and not ticker and not lista:
            accion = "RECOMENDAR"
            
    except:
        accion, estilo = "CHARLA", "SCALPING"
    
    print(f"🧠 {accion} | {ticker or lista} | {estilo}")

    # --- CASO 1: COMPARAR VARIOS ---
    if accion == "COMPARAR" and lista:
        msg = await update.message.reply_text(f"⚖️ **Comparando {len(lista)} activos...**")
        reporte = ""
        
        for t in lista:
            await asyncio.sleep(1)
            txt, prob, precio = await motor_analisis(t, estilo)
            if txt:
                emoji = "🏆" if prob > 0.6 else "⚠️"
                reporte += f"- {t}: ${precio:.2f} | Prob: {prob*100:.1f}% {emoji}\n"
        
        await msg.delete()
        if reporte:
            final = generar_recomendacion_mercado(reporte, "COMPARATIVA")
            await update.message.reply_text(final, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ No pude obtener datos de esos activos.")

    # --- CASO 2: RECOMENDAR (ESCÁNER) ---
    elif accion == "RECOMENDAR":
        msg = await update.message.reply_text(f"🔎 **Escaneando {categoria} ({estilo})...**")
        candidatos = await escanear_mercado_real(categoria, estilo)
        
        if not candidatos:
            await msg.edit_text("💤 Mercado lento, sin volatilidad clara.")
            return

        reporte = ""
        for i, t in enumerate(candidatos):
            txt, prob, precio = await motor_analisis(t, estilo)
            # Barra visual
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
            await update.message.reply_text("📉 Analicé los más movidos, pero ninguno da señal de compra fuerte.")

    # --- CASO 3: ANALIZAR UNO SOLO ---
    elif accion == "ANALIZAR" and ticker:
        msg = await update.message.reply_text(f"🔎 Analizando **{ticker}** ({estilo})...")
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

    # --- OTROS ---
    else:
        await update.message.reply_text(
            "👋 **Bot Trading Activo**\n"
            "Modo actual: **Scalping (15 min)** ⚡\n\n"
            "Comandos:\n"
            "🔹 _'Qué compro hoy?'_ (Escáner General)\n"
            "🔹 _'Recomienda Criptos'_ (Escáner Cripto)\n"
            "🔹 _'Compara Bitcoin, Oro y Tesla'_ (Comparativa)\n"
            "🔹 _'Analiza Apple'_ (Análisis Individual)", 
            parse_mode=ParseMode.MARKDOWN
        )

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
            if abs(cambio) > 0.03: 
                emoji = "🚀" if cambio > 0 else "🔻"
                await context.bot.send_message(
                    chat_id=Config.TELEGRAM_CHAT_ID,
                    text=f"🚨 **ALERTA {ticker}**\n{emoji} Movimiento: {cambio*100:.1f}%\nPrecio: ${precio_now:.2f}",
                    parse_mode=ParseMode.MARKDOWN
                )

if __name__ == '__main__':
    if not Config.TELEGRAM_TOKEN:
        print("❌ Error: Falta TELEGRAM_TOKEN en .env")
        exit()

    app = ApplicationBuilder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_ia))
    
    if app.job_queue:
        app.job_queue.run_repeating(guardian_cartera, interval=900, first=10)
    
    print("🤖 BOT MODO BURSÁTIL ACTIVO")
    app.run_polling()