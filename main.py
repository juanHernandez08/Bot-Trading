import logging
import json
import os
import asyncio
import traceback
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

from src.data_loader import descargar_datos 
from src.strategy import examinar_activo
from src.brain import interpretar_intencion, generar_resumen_humano
from src.scanner import escanear_mercado

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ARCHIVO_CARTERA = 'cartera.json'

# --- AHORA PASAMOS EL ESTILO A LA ESTRATEGIA ---
async def analizar_activo_completo(ticker, estilo, categoria):
    df, backup_mode = await descargar_datos(ticker, estilo)
    if df is None or df.empty: return None, 0.0
    # Aquí pasamos 'estilo' para que strategy sepa qué lógica usar
    info, prob = examinar_activo(df, ticker, estilo, categoria)
    if info:
        info['backup'] = backup_mode
        return info, prob
    return None, 0.0

def cargar_cartera():
    try: return json.load(open(ARCHIVO_CARTERA)) if os.path.exists(ARCHIVO_CARTERA) else []
    except: return []

def guardar_cartera(d):
    try: json.dump(d, open(ARCHIVO_CARTERA, 'w'))
    except: pass

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    global TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    msg_espera = await update.message.reply_text("⏳ **Analizando...**", parse_mode=ParseMode.MARKDOWN)
    
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

        elif acc == "RECOMENDAR":
            cats = ["CRIPTO", "FOREX", "ACCIONES"] if cat == "GENERAL" else [cat]
            await msg_espera.edit_text(f"🌎 **Escaneando {cat} ({est})...**")
            
            reporte = f"⚡ **OPORTUNIDADES ({est})**\n━━━━━━━━━━━━━━━━━━\n"
            hay = False
            
            for c in cats:
                try: candidatos = await escanear_mercado(c, est)
                except: candidatos = []
                for t in candidatos:
                    try:
                        info, prob = await analizar_activo_completo(t, est, c)
                        if info:
                            es_long = prob > 0.53
                            es_short = prob < 0.47
                            if es_long or es_short:
                                hay = True
                                icono = "🔥" if info.get('señal') in ["FUERTE", "GOLDEN"] else "⚡"
                                reporte += (
                                    f"{icono} **{info['ticker']}** ({info.get('mercado', 'GEN')})\n"
                                    f"💰 ${info['precio']} | {info['veredicto']}\n"
                                    f"🎯 TP: ${info['tp']}\n"
                                    f"⛔ SL: ${info['sl']}\n" 
                                    f"📝 _{info.get('motivo', '')}_\n\n"
                                )
                    except: continue 
            
            await msg_espera.delete()
            if hay: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else: await update.message.reply_text(f"💤 Sin entradas claras en {cat} ({est}).")

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
        error_msg = f"⚠️ **Error Técnico:**\n`{str(e)}`"
        print(traceback.format_exc()) 
        try: await msg_espera.delete() 
        except: pass
        await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)

# --- CAZADOR AUTOMÁTICO (DOBLE PASADA) ---
async def cazador_automatico(context: ContextTypes.DEFAULT_TYPE):
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_CHAT_ID: return
    
    categorias = ["FOREX"]
    # Escaneamos AMBOS estilos
    estilos_a_buscar = ["SCALPING", "SWING"]
    
    for estilo in estilos_a_buscar:
        for cat in categorias:
            try:
                candidatos = await escanear_mercado(cat, estilo)
                for t in candidatos:
                    info, prob = await analizar_activo_completo(t, estilo, cat)
                    if info:
                        # Filtros:
                        # Scalping: Prob > 53% / < 47%
                        # Swing: Prob > 65% / < 35% (Más exigente)
                        es_oportunidad = False
                        if estilo == "SCALPING" and (prob > 0.53 or prob < 0.47): es_oportunidad = True
                        if estilo == "SWING" and (prob > 0.65 or prob < 0.35): es_oportunidad = True

                        if es_oportunidad:
                            titulo = "OPORTUNIDAD DE ORO" if estilo == "SWING" else "ALERTA SCALPING"
                            emoji = "🏆" if estilo == "SWING" else "⚡"
                            
                            mensaje = (
                                f"{emoji} **{titulo} ({info['tipo_operacion']})**\n"
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
