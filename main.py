import logging
import json
import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from sklearn.ensemble import RandomForestClassifier

# --- IMPORTAMOS TUS MÓDULOS DE SRC ---
from src.data_loader import descargar_datos
from src.brain import interpretar_intencion, generar_resumen_humano
from src.scanner import escanear_mercado

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ARCHIVO_CARTERA = 'cartera.json'

# --- Pequeño Predictor Local (Para no complicar importando model_handler) ---
def predecir_rapido(df):
    try:
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        cols = [c for c in ['RSI', 'MACD', 'Signal', 'SMA_50', 'Volatilidad'] if c in df.columns]
        model.fit(df[cols].iloc[:-1], df['Target'].iloc[:-1])
        prob = model.predict_proba(df[cols].iloc[[-1]])[0][1]
        return prob
    except: return 0.5

async def flujo_analisis(ticker, estilo):
    # 1. Usar data_loader
    df, backup = await descargar_datos(ticker, estilo)
    if df is None: return None
    
    # 2. Predecir
    prob = predecir_rapido(df)
    row = df.iloc[-1]
    
    # 3. Formatear
    if prob > 0.65: señal, icono, veredicto = "ALCISTA", "🟢", "COMPRAR AHORA 🚀"
    elif prob > 0.55: señal, icono, veredicto = "MODERADA", "🟢", "COMPRA CAUTELOSA ✅"
    elif prob < 0.40: señal, icono, veredicto = "BAJISTA", "🔴", "NO COMPRAR ❌"
    else: señal, icono, veredicto = "NEUTRAL", "⚪", "ESPERAR ✋"
    
    fmt = ",.4f" if row['Close'] < 50 else ",.2f"
    if "COP" in ticker or "CLP" in ticker: fmt = ",.0f"
    
    return {
        "ticker": ticker, "precio": format(row['Close'], fmt),
        "sl": format(row['Stop_Loss'], fmt), "tp": format(row['Take_Profit'], fmt),
        "rsi": f"{row['RSI']:.1f}", "señal": señal, "icono": icono,
        "veredicto": veredicto, "prob": prob, "backup": backup
    }

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    try:
        # 1. Brain analiza
        data = interpretar_intencion(texto)
        acc, tick, lst, est, cat, exp = (
            data.get("accion"), data.get("ticker"), data.get("lista_activos"),
            data.get("estilo", "SCALPING"), data.get("categoria", "GENERAL"), data.get("explicacion")
        )
        if not est: est = "SCALPING" # Seguridad
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"
        
        # 2. Ejecutar Acción
        if acc == "COMPARAR" and lst:
            msg = await update.message.reply_text(f"⚖️ Comparando...")
            rep = f"📊 **Estrategia**\n💡 _{exp}_\n━━━━━━━━━━\n" if exp else "⚖️ **Comparativa**\n━━━━━━━━━━\n"
            for t in lst:
                res = await flujo_analisis(t, est)
                if res: rep += f"💎 **{res['ticker']}**\n💰 ${res['precio']} | {res['veredicto']}\n🎯 TP: ${res['tp']}\n〰〰〰〰〰\n"
            await msg.delete()
            await update.message.reply_text(rep, parse_mode=ParseMode.MARKDOWN)

        elif acc == "RECOMENDAR":
            msg = await update.message.reply_text(f"🔎 Escaneando **{cat}**...")
            # 3. Scanner busca en la lista correcta
            lista = await escanear_mercado(cat, est)
            rep = f"⚡ **TOP {cat}**\n━━━━━━━━━━\n"
            for t in lista:
                res = await flujo_analisis(t, est)
                if res and res['prob'] > 0.5:
                    rep += f"🔥 **{res['ticker']}**\n💰 ${res['precio']} | {res['veredicto']}\n🎯 TP: ${res['tp']}\n〰〰〰〰〰\n"
            await msg.delete()
            await update.message.reply_text(rep, parse_mode=ParseMode.MARKDOWN)

        elif acc == "ANALIZAR" and tick:
            msg = await update.message.reply_text(f"🔎 Analizando {tick}...")
            res = await flujo_analisis(tick, est)
            if res:
                razon = generar_resumen_humano(f"RSI:{res['rsi']}", res['prob'])
                aviso = "⚠️ DIARIO" if res['backup'] else est
                card = (
                    f"💎 **{res['ticker']}** | {aviso}\n"
                    f"💵 Precio: `${res['precio']}`\n"
                    f"━━━━━━━━━━\n"
                    f"💡 **{res['veredicto']}**\n"
                    f"📝 _{razon}_\n\n"
                    f"🎯 TP: `${res['tp']}`\n"
                    f"⛔ SL: `${res['sl']}`"
                )
                await msg.delete()
                await update.message.reply_text(card, parse_mode=ParseMode.MARKDOWN)
            else: await msg.edit_text(f"❌ No encontré datos de {tick}")

    except Exception as e:
        print(e)
        await update.message.reply_text("⚠️ Error interno.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje))
    print("🤖 BOT MODULAR ACTIVO")
    app.run_polling()
