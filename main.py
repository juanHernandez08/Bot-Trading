import logging
import json
import os
import asyncio
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

# --- FUNCIÓN PEGAMENTO (Coordina Data + Estrategia) ---
async def analizar_activo_completo(ticker, estilo, categoria):
    # 1. Descargar
    df, backup_mode = await descargar_datos(ticker, estilo)
    if df is None or df.empty: return None, 0.0

    # 2. Analizar
    info, prob = examinar_activo(df, ticker, categoria)
    
    # 3. Empaquetar
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

# --- CEREBRO PRINCIPAL (INTERACCIÓN MANUAL) ---
async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    
    # Actualizamos el ID del chat para que el Cazador sepa a dónde enviar alertas
    global TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    try:
        # 1. IA INTERPRETA
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        est = data.get("estilo")
        cat = data.get("categoria", "GENERAL") 
        explicacion = data.get("explicacion")
        
        if not est: est = "SCALPING"
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # BLOQUE 1: COMPARAR
        if acc == "COMPARAR" and lst:
            titulo = "📊 **Estrategia**" if explicacion else "⚖️ **Comparando**"
            msg = await update.message.reply_text(f"{titulo} ({est})...")
            reporte = f"{titulo} | {est}\n"
            if explicacion: reporte += f"💡 _{explicacion}_\n"
            reporte += "━━━━━━━━━━━━━━━━━━\n"
            
            encontrados = False
            for t in lst:
                info, prob, = await analizar_activo_completo(t, est, cat)
                if info:
                    encontrados = True
                    reporte += (
                        f"💎 **{info['ticker']}**\n"
                        f"💰 ${info['precio']} | {info['tipo_operacion']} {info['icono']}\n"
                        f"🎯 TP: ${info['tp']} | ⛔ SL: ${info['sl']}\n"
                        f"〰〰〰〰〰〰〰〰〰\n"
                    )
            await msg.delete()
            if encontrados: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else: await update.message.reply_text("❌ Sin datos.")

        # BLOQUE 2: RECOMENDAR (MEGA ESCÁNER)
        elif acc == "RECOMENDAR":
            # Si pide General, revisamos todo. Si no, solo la categoría pedida.
            cats = ["CRIPTO", "FOREX", "ACCIONES"] if cat == "GENERAL" else [cat]
            titulo_msg = "🌎 Escaneando Oportunidades..." if cat == "GENERAL" else f"🔎 Escaneando {cat}..."
            
            msg = await update.message.reply_text(titulo_msg)
            reporte = f"⚡ **MEJORES OPORTUNIDADES ({est})**\n━━━━━━━━━━━━━━━━━━\n"
            hay = False

            for c in cats:
                candidatos = await escanear_mercado(c, est)
                for t in candidatos:
                    info, prob = await analizar_activo_completo(t, est, c)
                    
                    # FILTRO SENSIBLE (>53% o Shorts <47%)
                    es_long = prob > 0.53
                    es_short = (prob < 0.47 and c in ['FOREX', 'CRIPTO'])

                    if info and (es_long or es_short):
                        hay = True
                        fuerza = "🔥" if (prob > 0.60 or prob < 0.40) else "⚠️"
                        reporte += (
                            f"{fuerza} **{info['ticker']}** ({c[:3]})\n"
                            f"💰 ${info['precio']} | {info['veredicto']}\n"
                            f"🎯 TP: ${info['tp']}\n"
                            f"⛔ SL: ${info['sl']}\n" 
                            f"〰〰〰〰〰〰〰〰〰\n"
                        )
            
            await msg.delete()
            if hay: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else: await update.message.reply_text(f"💤 Mercado muy lateral. No veo entradas claras.")

        # BLOQUE 3: ANALIZAR INDIVIDUAL
        elif acc == "ANALIZAR" and tick:
            msg = await update.message.reply_text(f"🔎 Analizando {tick}...")
            info, prob = await analizar_activo_completo(tick, est, cat)
            
            if info:
                razon = generar_resumen_humano(f"RSI:{info['rsi']}", prob)
                aviso_modo = " | ⚠️ DIARIO" if info['backup'] else f" | {est.upper()}"
                
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
            else: await msg.edit_text(f"❌ No pude leer datos de {tick}.")

        # BLOQUE 4: VIGILAR
        elif acc == "VIGILAR" and tick:
            info, _ = await analizar_activo_completo(tick, "SWING", cat)
            if info:
                c = cargar_cartera()
                precio_limpio = float(info['precio'].replace(",",""))
                c.append({"ticker": tick, "precio_compra": precio_limpio})
                guardar_cartera(c)
                await update.message.reply_text(f"🛡️ Vigilando {tick} desde ${info['precio']}")
            else: await update.message.reply_text("❌ Error al obtener precio.")

        else:
            await update.message.reply_text("👋 Hola. Pregúntame: 'Qué hacemos hoy?', 'Oportunidades Cripto' o 'Analiza Tesla'.")

    except Exception as e:
        print(f"ERROR: {e}")
        await update.message.reply_text("⚠️ Error interno.")

# --- 🚀 CAZADOR AUTOMÁTICO (MODO SENSIBLE) 🚀 ---
async def cazador_automatico(context: ContextTypes.DEFAULT_TYPE):
    """
    Escanea periódicamente buscando oportunidades, incluso pequeñas (Scalping).
    """
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_CHAT_ID: return
    
    # Escaneamos Cripto y Forex (mercados activos)
    categorias = ["CRIPTO", "FOREX"] 
    print("🕵️‍♂️ Cazador Sensible Buscando...")
    
    encontradas = 0
    
    for cat in categorias:
        candidatos = await escanear_mercado(cat, "SCALPING")
        
        for t in candidatos:
            info, prob = await analizar_activo_completo(t, "SCALPING", cat)
            
            if info:
                es_long = False
                es_short = False
                fuerza = ""
                
                # 1. ANÁLISIS LONG (> 53%)
                if prob > 0.60:
                    es_long = True
                    fuerza = "🔥 FUERTE"
                elif prob > 0.53:
                    es_long = True
                    fuerza = "⚠️ MODERADA (Scalping)"
                    
                # 2. ANÁLISIS SHORT (< 47%)
                elif prob < 0.40:
                    es_short = True
                    fuerza = "🔥 FUERTE"
                elif prob < 0.47:
                    es_short = True
                    fuerza = "⚠️ MODERADA (Scalping)"
                
                # --- ENVIAR ALERTA ---
                if es_long or es_short:
                    encontradas += 1
                    titulo = "COMPRA (LONG) 🚀" if es_long else "VENTA (SHORT) 📉"
                    icono = "🟢" if es_long else "🔴"
                    
                    mensaje = (
                        f"{icono} **ALERTA: {titulo}**\n"
                        f"💎 Activo: **{info['ticker']}**\n"
                        f"📊 Señal: **{fuerza}**\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Entrada: `${info['precio']}`\n"
                        f"🎯 TP: `${info['tp']}`\n"
                        f"⛔ SL: `${info['sl']}`\n\n"
                        f"💡 _Oportunidad detectada._"
                    )
                    
                    try:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje, parse_mode=ParseMode.MARKDOWN)
                        await asyncio.sleep(3) # Pausa para no saturar
                    except Exception as e:
                        print(f"Error enviando alerta: {e}")

# --- ARRANQUE ---
if __name__ == '__main__':
    if not TELEGRAM_TOKEN: exit()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje))
    
    if app.job_queue:
        # Tareas Automáticas
        # 1. Cazador: Cada 30 minutos (1800 seg)
        app.job_queue.run_repeating(cazador_automatico, interval=1800, first=30)
        
    print("🤖 BOT CAZADOR SENSIBLE ACTIVO 🚀")
    app.run_polling()
