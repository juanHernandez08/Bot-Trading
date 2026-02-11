import logging
import json
import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- IMPORTAMOS TUS MÓDULOS DE LA CARPETA SRC ---
# 1. El Cargador de Datos (Descarga de Yahoo)
from src.data_loader import descargar_datos 
# 2. El Estratega (Decide si es Long o Short)
from src.strategy import examinar_activo
# 3. El Cerebro (IA para entender texto y resumir)
from src.brain import interpretar_intencion, generar_resumen_humano
# 4. El Escáner (Busca oportunidades en listas)
from src.scanner import escanear_mercado

# --- CONFIGURACIÓN ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ARCHIVO_CARTERA = 'cartera.json'

# --- FUNCIÓN "PEGAMENTO" (Coordina Data + Estrategia) ---
async def analizar_activo_completo(ticker, estilo, categoria):
    """
    Esta función conecta los cables:
    1. Pide datos a data_loader.
    2. Pasa los datos a strategy.
    3. Devuelve el resultado final.
    """
    # Paso 1: Descargar
    df, backup_mode = await descargar_datos(ticker, estilo)
    
    # Si no hay datos, abortamos
    if df is None or df.empty: 
        return None, 0.0

    # Paso 2: Analizar Estrategia (Long/Short)
    info, prob = examinar_activo(df, ticker, categoria)
    
    # Paso 3: Añadir etiqueta de Backup si se usó diario en vez de scalping
    if info:
        info['backup'] = backup_mode
        return info, prob
        
    return None, 0.0

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
    # Icono de "escribiendo..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    
    try:
        # 1. LA IA INTERPRETA TU INTENCIÓN
        data = interpretar_intencion(texto)
        
        # Extraemos variables
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        est = data.get("estilo")
        cat = data.get("categoria", "GENERAL") 
        explicacion = data.get("explicacion")
        
        # Seguridad: Si el estilo viene vacío, ponemos Scalping
        if not est: est = "SCALPING"
        
        # Si pide analizar sin ticker, asumimos recomendación
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # ------------------------------------------------------------------
        # BLOQUE 1: COMPARAR / ESTRATEGIA (Varios Activos)
        # ------------------------------------------------------------------
        if acc == "COMPARAR" and lst:
            titulo = "📊 **Estrategia**" if explicacion else "⚖️ **Comparando**"
            msg = await update.message.reply_text(f"{titulo} ({est})...")
            
            reporte = f"{titulo} | {est}\n"
            if explicacion: reporte += f"💡 _{explicacion}_\n"
            reporte += "━━━━━━━━━━━━━━━━━━\n"
            
            encontrados = False
            for t in lst:
                # Usamos nuestra función pegamento
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
            if encontrados:
                await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text("❌ No encontré datos para esos activos.")

        # ------------------------------------------------------------------
        # BLOQUE 2: RECOMENDAR (Escáner de Mercado)
        # ------------------------------------------------------------------
        elif acc == "RECOMENDAR":
            msg = await update.message.reply_text(f"🔎 Escaneando **{cat}** ({est})...")
            
            candidatos = await escanear_mercado(cat, est)
            
            reporte = f"⚡ **TOP {cat} ({est})**\n━━━━━━━━━━━━━━━━━━\n"
            encontrados = False
            
            for t in candidatos:
                info, prob = await analizar_activo_completo(t, est, cat)
                # Filtramos solo señales fuertes (>60% probabilidad ya invertida por strategy)
                if info and prob > 0.60:
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
        # BLOQUE 3: ANALIZAR (Un solo activo - Tarjeta Completa)
        # ------------------------------------------------------------------
        elif acc == "ANALIZAR" and tick:
            msg = await update.message.reply_text(f"🔎 Analizando {tick}...")
            
            info, prob = await analizar_activo_completo(tick, est, cat)
            
            if info:
                # IA genera explicación humana
                razon = generar_resumen_humano(f"RSI:{info['rsi']}", prob)
                
                # Aviso si estamos en modo rescate
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
                await msg.edit_text(f"❌ No pude leer datos de {tick}.")

        # ------------------------------------------------------------------
        # BLOQUE 4: VIGILAR (Guardar en cartera)
        # ------------------------------------------------------------------
        elif acc == "VIGILAR" and tick:
            info, _ = await analizar_activo_completo(tick, "SWING", cat)
            if info:
                c = cargar_cartera()
                # Limpiamos el precio para guardar solo el número
                precio_limpio = float(info['precio'].replace(",",""))
                c.append({"ticker": tick, "precio_compra": precio_limpio})
                guardar_cartera(c)
                await update.message.reply_text(f"🛡️ Vigilando {tick} desde ${info['precio']}")
            else:
                await update.message.reply_text("❌ No pude obtener el precio para vigilar.")

        # ------------------------------------------------------------------
        # BLOQUE DEFAULT: CHARLA
        # ------------------------------------------------------------------
        else:
            await update.message.reply_text("👋 Soy tu Bot de Trading.\nPrueba: 'Analiza Rockstar', 'Apostar contra Chile' o 'Qué cripto compro'.")

    except Exception as e:
        print(f"ERROR MAIN: {e}")
        await update.message.reply_text("⚠️ Ocurrió un error. Intenta de nuevo.")

# --- TAREA DE FONDO: GUARDIÁN DE PRECIOS ---
async def guardian_cartera(context: ContextTypes.DEFAULT_TYPE):
    c = cargar_cartera()
    if not c or not TELEGRAM_CHAT_ID: return
    for i in c:
        await asyncio.sleep(2)
        # Usamos la función pegamento en modo SCALPING para revisar rápido
        info, _ = await analizar_activo_completo(i['ticker'], "SCALPING", "GENERAL")
        
        if info:
            now = float(info['precio'].replace(",",""))
            compra = i['precio_compra']
            
            if compra > 0:
                chg = (now - compra) / compra
                # Si se mueve más de un 3%, avisa
                if abs(chg) > 0.03:
                    emoji = "🚀" if chg > 0 else "🔻"
                    await context.bot.send_message(
                        TELEGRAM_CHAT_ID, 
                        f"🚨 **ALERTA {i['ticker']}**\nMovimiento: {emoji} {chg*100:.1f}%\nPrecio actual: ${now}", 
                        parse_mode=ParseMode.MARKDOWN
                    )

# --- ARRANQUE DEL BOT ---
if __name__ == '__main__':
    if not TELEGRAM_TOKEN:
        print("Error: No encontré el Token de Telegram en .env")
        exit()
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje))
    
    if app.job_queue:
        app.job_queue.run_repeating(guardian_cartera, interval=900, first=30)
        
    print("🤖 BOT MODULAR BIDIRECCIONAL ACTIVO 🚀")
    app.run_polling()
