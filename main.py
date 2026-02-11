import logging
import json
import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- IMPORTAMOS TUS MÓDULOS DE LA CARPETA SRC ---
# Asegúrate de que los archivos en 'src' se llamen exactamente así:
from src.data_loader import motor_analisis 
from src.brain import interpretar_intencion, generar_resumen_humano
from src.scanner import escanear_mercado

# --- CONFIGURACIÓN ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ARCHIVO_CARTERA = 'cartera.json'

# --- GESTIÓN DE CARTERA (VIGILAR) ---
def cargar_cartera():
    try: return json.load(open(ARCHIVO_CARTERA)) if os.path.exists(ARCHIVO_CARTERA) else []
    except: return []

def guardar_cartera(d):
    try: json.dump(d, open(ARCHIVO_CARTERA, 'w'))
    except: pass

# --- CEREBRO PRINCIPAL DEL BOT ---
async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    # Icono de "escribiendo..." para que se sienta vivo
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    try:
        # 1. LA IA INTERPRETA TU INTENCIÓN
        data = interpretar_intencion(texto)
        
        # Extraemos las variables limpias
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        est = data.get("estilo")
        cat = data.get("categoria", "GENERAL") # ¡Importante para saber si es Forex/Cripto!
        explicacion = data.get("explicacion")
        
        # Seguridad: Si el estilo viene vacío, ponemos Scalping por defecto
        if not est: est = "SCALPING"
        
        # Si pide analizar sin decir qué, lo convertimos en recomendación
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # ------------------------------------------------------------------
        # BLOQUE 1: COMPARAR / ESTRATEGIA (Varios Activos)
        # ------------------------------------------------------------------
        if acc == "COMPARAR" and lst:
            titulo = "📊 **Estrategia**" if explicacion else "⚖️ **Comparando**"
            msg = await update.message.reply_text(f"{titulo} ({est})...")
            
            reporte = f"{titulo} | {est}\n"
            if explicacion:
                reporte += f"💡 _{explicacion}_\n"
            reporte += "━━━━━━━━━━━━━━━━━━\n"
            
            encontrados = False
            for t in lst:
                # Llamamos al motor pasándole la CATEGORÍA (para que sepa si puede Shortear)
                info, prob, _, _ = await motor_analisis(t, est, cat)
                if info:
                    encontrados = True
                    # Formato compacto para listas
                    reporte += (
                        f"💎 **{info['ticker']}**\n"
                        f"💰 ${info['precio']} | {info['tipo_operacion']} {info['icono']}\n"
                        f"🎯 TP: ${info['tp']} | ⛔ SL: ${info['sl']}\n"
                        f"〰〰〰〰〰〰〰〰〰\n"
                    )
            
            await msg.delete()
            if encontrados:
                await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text("❌ No encontré datos para esos activos.")

        # ------------------------------------------------------------------
        # BLOQUE 2: RECOMENDAR (Escáner de Mercado)
        # ------------------------------------------------------------------
        elif acc == "RECOMENDAR":
            msg = await update.message.reply_text(f"🔎 Escaneando **{cat}** ({est})...")
            
            # El escáner busca tickers interesantes en esa categoría
            candidatos = await escanear_mercado(cat, est)
            
            reporte = f"⚡ **TOP {cat} ({est})**\n━━━━━━━━━━━━━━━━━━\n"
            encontrados = False
            
            for t in candidatos:
                info, prob, _, _ = await motor_analisis(t, est, cat)
                # Filtramos solo lo que tenga probabilidad decente (>50% o <40% para shorts)
                if info and (prob > 0.55 or (prob < 0.45 and cat in ['FOREX', 'CRIPTO'])):
                    encontrados = True
                    reporte += (
                        f"🔥 **{info['ticker']}**\n"
                        f"💰 ${info['precio']} | {info['veredicto']}\n"
                        f"🎯 TP: ${info['tp']}\n"
                        f"〰〰〰〰〰〰〰〰〰\n"
                    )
            
            await msg.delete()
            if encontrados:
                await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"💤 Mercado lateral en {cat}. Mejor esperar.")

        # ------------------------------------------------------------------
        # BLOQUE 3: ANALIZAR (Un solo activo - Tarjeta Francotirador)
        # ------------------------------------------------------------------
        elif acc == "ANALIZAR" and tick:
            msg = await update.message.reply_text(f"🔎 Analizando {tick}...")
            
            # Análisis profundo
            info, prob, _, _ = await motor_analisis(tick, est, cat)
            
            if info:
                # IA genera explicación humana
                razon = generar_resumen_humano(f"RSI:{info['rsi']}", prob)
                
                # Aviso si estamos en modo rescate (Diario en vez de 15m)
                aviso_modo = " | ⚠️ DIARIO" if info['backup'] else f" | {est.upper()}"
                
                # Tarjeta Profesional
                tarjeta = (
                    f"💎 **{info['ticker']}**{aviso_modo}\n"
                    f"💵 **Precio:** `${info['precio']}`\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💡 **CONCLUSIÓN:**\n"
                    f"👉 **{info['veredicto']}**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📝 **Lógica:** _{razon}_\n\n"
                    f"🛡️ **Gestión de Riesgo:**\n"
                    f"⛔ Stop Loss: `${info['sl']}`\n"
                    f"🎯 Take Profit: `${info['tp']}`\n"
                    f"📉 RSI: `{info['rsi']}`"
                )
                await msg.delete()
                await update.message.reply_text(tarjeta, parse_mode=ParseMode.MARKDOWN)
            else:
                await msg.edit_text(f"❌ No pude leer datos de {tick}. Intenta con otro.")

        # ------------------------------------------------------------------
        # BLOQUE 4: VIGILAR (Guardar en cartera)
        # ------------------------------------------------------------------
        elif acc == "VIGILAR" and tick:
            _, _, p, _ = await motor_analisis(tick, "SWING")
            c = cargar_cartera()
            c.append({"ticker": tick, "precio_compra": p})
            guardar_cartera(c)
            await update.message.reply_text(f"🛡️ Vigilando {tick} desde ${p:.2f}")

        # ------------------------------------------------------------------
        # BLOQUE DEFAULT: CHARLA
        # ------------------------------------------------------------------
        else:
            await update.message.reply_text("👋 Soy tu Bot de Trading.\nPrueba: 'Analiza Rockstar', 'Apostar contra Chile' o 'Qué cripto compro'.")

    except Exception as e:
        print(f"ERROR CRÍTICO: {e}")
        await update.message.reply_text("⚠️ Ocurrió un error interno. Intenta de nuevo.")

# --- TAREA DE FONDO: GUARDIÁN DE PRECIOS ---
async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    c = cargar_cartera()
    if not c or not TELEGRAM_CHAT_ID: return
    for i in c:
        await asyncio.sleep(2)
        # Revisamos rápido en modo Scalping
        _, _, now, _ = await motor_analisis(i['ticker'], "SCALPING")
        if now > 0:
            chg = (now - i['precio_compra']) / i['precio_compra']
            # Si se mueve más de un 3%, avisa
            if abs(chg) > 0.03:
                await context.bot.send_message(
                    TELEGRAM_CHAT_ID, 
                    f"🚨 **ALERTA {i['ticker']}**\nSe movió un {chg*100:.1f}%\nPrecio actual: ${now:.2f}", 
                    parse_mode=ParseMode.MARKDOWN
                )

# --- ARRANQUE DEL BOT ---
if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Error: No encontré el Token de Telegram en .env")
        exit()
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Manejador de mensajes de texto
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje))
    
    # Tarea repetitiva (Guardián) cada 15 minutos
    if app.job_queue:
        app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
        
    print("🤖 BOT DE TRADING PROFESIONAL ACTIVO 🚀")
    app.run_polling()
