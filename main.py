import logging
import json
import os
import asyncio
import traceback # <--- Nuevo para ver el error real
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- IMPORTAMOS TUS MÓDULOS DE SRC ---
from src.data_loader import descargar_datos 
from src.strategy import examinar_activo
from src.brain import interpretar_intencion, generar_resumen_humano
from src.scanner import escanear_mercado

# --- CONFIGURACIÓN ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ARCHIVO_CARTERA = 'cartera.json'

# --- FUNCIÓN PEGAMENTO ---
async def analizar_activo_completo(ticker, estilo, categoria):
    df, backup_mode = await descargar_datos(ticker, estilo)
    if df is None or df.empty: return None, 0.0
    info, prob = examinar_activo(df, ticker, categoria)
    if info:
        info['backup'] = backup_mode
        return info, prob
    return None, 0.0

# --- GESTIÓN DE CARTERA ---
def cargar_cartera():
    try: return json.load(open(ARCHIVO_CARTERA)) if os.path.exists(ARCHIVO_CARTERA) else []
    except: return []

def guardar_cartera(d):
    try: json.dump(d, open(ARCHIVO_CARTERA, 'w'))
    except: pass

# --- CEREBRO PRINCIPAL ---
async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    global TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    msg_espera = await update.message.reply_text("⏳ **Analizando...**", parse_mode=ParseMode.MARKDOWN)
    
    try:
        # IA INTERPRETA
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        est = data.get("estilo", "SCALPING")
        cat = data.get("categoria", "GENERAL") 
        explicacion = data.get("explicacion")
        
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # 1. COMPARAR
        if acc == "COMPARAR" and lst:
            await msg_espera.edit_text(f"⚖️ **Comparando...**")
            reporte = f"📊 **Estrategia** | {est}\n━━━━━━━━━━━━━━━━━━\n"
            encontrados = False
            for t in lst:
                info, prob, = await analizar_activo_completo(t, est, cat)
                if info:
                    encontrados = True
                    reporte += (
                        f"💎 **{info['ticker']}** ({info.get('mercado', 'GEN')})\n"
                        f"💰 ${info['precio']} | {info['tipo_operacion']} {info['icono']}\n"
                        f"🎯 TP: ${info['tp']} | ⛔ SL: ${info['sl']}\n"
                        f"📝 _{info.get('motivo', '')}_\n\n"
                    )
            await msg_espera.delete()
            if encontrados: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else: await update.message.reply_text("❌ Sin datos.")

        # 2. RECOMENDAR
        elif acc == "RECOMENDAR":
            cats = ["CRIPTO", "FOREX", "ACCIONES"] if cat == "GENERAL" else [cat]
            await msg_espera.edit_text(f"🌎 **Escaneando {cat}...**")
            
            reporte = f"⚡ **OPORTUNIDADES ({est})**\n━━━━━━━━━━━━━━━━━━\n"
            hay = False
            
            for c in cats:
                # Usamos try-except interno para que no falle todo si una lista falla
                try:
                    candidatos = await escanear_mercado(c, est)
                except Exception as e:
                    print(f"Error escaneando {c}: {e}")
                    candidatos = []
                    
                for t in candidatos:
                    try:
                        info, prob = await analizar_activo_completo(t, est, c)
                        if info:
                            # Filtros Sensibles
                            es_long = prob > 0.53
                            es_short = prob < 0.47
                            if es_long or es_short:
                                hay = True
                                icono = "🔥" if info.get('señal') == "FUERTE" else "⚠️"
                                reporte += (
                                    f"{icono} **{info['ticker']}** ({info.get('mercado', 'GEN')})\n"
                                    f"💰 ${info['precio']} | {info['veredicto']}\n"
                                    f"🎯 TP: ${info['tp']}\n"
                                    f"⛔ SL: ${info['sl']}\n" 
                                    f"📝 _{info.get('motivo', '')}_\n\n"
                                )
                    except: continue # Si falla un activo, pasa al siguiente
            
            await msg_espera.delete()
            if hay: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else: await update.message.reply_text(f"💤 Mercado lateral en {cat}. No hay entradas claras.")

        # 3. ANALIZAR
        elif acc == "ANALIZAR" and tick:
            await msg_espera.edit_text(f"🔎 **Calculando {tick}...**")
            info, prob = await analizar_activo_completo(tick, est, cat)
            
            if info:
                razon_ia = generar_resumen_humano(f"RSI:{info['rsi']} Motivo:{info.get('motivo')}", prob)
                tarjeta = (
                    f"💎 **{info['ticker']}** ({info.get('mercado', 'GEN')})\n"
                    f"💵 Precio: `${info['precio']}`\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👉 **{info['veredicto']}**\n"
                    f"📝 _{info.get('motivo', '')}_\n"
                    f"🤖 IA: _{razon_ia}_\n\n"
                    f"⛔ SL: `${info['sl']}`\n"
                    f"🎯 TP: `${info['tp']}`"
                )
                await msg_espera.delete()
                await update.message.reply_text(tarjeta, parse_mode=ParseMode.MARKDOWN)
            else: 
                await msg_espera.delete()
                await update.message.reply_text(f"❌ No pude leer datos de {tick}.")
        
        else:
            await msg_espera.delete()
            await update.message.reply_text("👋 Hola. Prueba 'Oportunidades Forex' o 'Analiza BTC'.")

    except Exception as e:
        # --- AQUÍ ESTÁ LA MAGIA DEL DIAGNÓSTICO ---
        # Esto te enviará el error exacto al chat
        error_msg = f"⚠️ **Error Técnico:**\n`{str(e)}`"
        print(traceback.format_exc()) # Imprime en consola Railway
        try: await msg_espera.delete() 
        except: pass
        await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)

# --- CAZADOR AUTOMÁTICO ---
async def cazador_automatico(context: ContextTypes.DEFAULT_TYPE):
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_CHAT_ID: return
    categorias = ["FOREX"] 
    
    for cat in categorias:
        try:
            candidatos = await escanear_mercado(cat, "SCALPING")
            for t in candidatos:
                info, prob = await analizar_activo_completo(t, "SCALPING", cat)
                if info:
                    if prob > 0.53 or prob < 0.47:
                        mensaje = (
                            f"{info['icono']} **ALERTA: {info['tipo_operacion']}**\n"
                            f"💎 **{info['ticker']}** ({info.get('mercado','GEN')})\n"
                            f"📝 _{info.get('motivo', '')}_\n"
                            f"💰 Ent: `${info['precio']}`\n"
                            f"🎯 TP: `${info['tp']}` | ⛔ SL: `${info['sl']}`"
                        )
                        try: await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje, parse_mode=ParseMode.MARKDOWN)
                        except: pass
        except: pass

if __name__ == '__main__':
    if not TELEGRAM_TOKEN: exit()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje))
    if app.job_queue: app.job_queue.run_repeating(cazador_automatico, interval=1800, first=30)
    app.run_polling()
