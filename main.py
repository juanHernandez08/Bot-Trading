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
    # 1. Descargar Datos
    df, backup_mode = await descargar_datos(ticker, estilo)
    if df is None or df.empty: return None, 0.0

    # 2. Analizar Estrategia (Calcula TP, SL, Motivo y Mercado)
    info, prob = examinar_activo(df, ticker, categoria)
    
    # 3. Empaquetar resultado
    if info:
        info['backup'] = backup_mode
        return info, prob
    return None, 0.0

# --- GESTIÓN DE CARTERA (Simulación) ---
def cargar_cartera():
    try: return json.load(open(ARCHIVO_CARTERA)) if os.path.exists(ARCHIVO_CARTERA) else []
    except: return []

def guardar_cartera(d):
    try: json.dump(d, open(ARCHIVO_CARTERA, 'w'))
    except: pass

# --- CEREBRO PRINCIPAL (INTERACCIÓN MANUAL) ---
async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    
    # Actualizamos el ID para que el Cazador sepa a dónde enviar alertas
    global TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID = update.effective_chat.id
    
    # 1. FEEDBACK VISUAL (Barra de espera)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    msg_espera = await update.message.reply_text("⏳ **Analizando mercado...**", parse_mode=ParseMode.MARKDOWN)
    
    try:
        # 2. IA INTERPRETA INTENCIÓN
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        est = data.get("estilo")
        cat = data.get("categoria", "GENERAL") 
        explicacion = data.get("explicacion")
        
        if not est: est = "SCALPING"
        # Si dice "Analiza" pero no da ticker, asumimos que quiere recomendaciones
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # ------------------------------------------------------------------
        # BLOQUE 1: COMPARAR (Estrategias contra países)
        # ------------------------------------------------------------------
        if acc == "COMPARAR" and lst:
            await msg_espera.edit_text(f"⚖️ **Comparando activos ({est})...**")
            
            titulo = "📊 **Estrategia**" if explicacion else "⚖️ **Comparando**"
            reporte = f"{titulo} | {est}\n"
            if explicacion: reporte += f"💡 _{explicacion}_\n"
            reporte += "━━━━━━━━━━━━━━━━━━\n"
            
            encontrados = False
            for t in lst:
                info, prob, = await analizar_activo_completo(t, est, cat)
                if info:
                    encontrados = True
                    reporte += (
                        f"💎 **{info['ticker']}** ({info.get('mercado', 'GEN')})\n"
                        f"💰 ${info['precio']} | {info['tipo_operacion']} {info['icono']}\n"
                        f"🎯 TP: ${info['tp']} | ⛔ SL: ${info['sl']}\n"
                        f"📝 _{info.get('motivo', 'Análisis técnico')}_\n"
                        f"〰〰〰〰〰〰〰〰〰\n"
                    )
            
            await msg_espera.delete()
            if encontrados: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else: await update.message.reply_text("❌ Sin datos.")

        # ------------------------------------------------------------------
        # BLOQUE 2: RECOMENDAR (MEGA ESCÁNER)
        # ------------------------------------------------------------------
        elif acc == "RECOMENDAR":
            # Si es GENERAL, escanea todo. Si es específica, solo esa categoría.
            cats = ["CRIPTO", "FOREX", "ACCIONES"] if cat == "GENERAL" else [cat]
            await msg_espera.edit_text(f"🌎 **Escaneando {cat}...**\nBuscando las mejores probabilidades.")
            
            reporte = f"⚡ **OPORTUNIDADES ({est})**\n━━━━━━━━━━━━━━━━━━\n"
            hay = False

            for c in cats:
                candidatos = await escanear_mercado(c, est)
                for t in candidatos:
                    info, prob = await analizar_activo_completo(t, est, c)
                    
                    if info:
                        # FILTRO SENSIBLE:
                        # Long > 53% | Short < 47% (Solo Forex/Cripto)
                        es_long = prob > 0.53
                        es_short = (prob < 0.47 and c in ['FOREX', 'CRIPTO'])

                        if es_long or es_short:
                            hay = True
                            fuerza_texto = info.get('señal', 'MODERADA') 
                            icono = "🔥" if fuerza_texto == "FUERTE" else "⚠️"
                            etiqueta = info.get('mercado', 'GEN')
                            
                            reporte += (
                                f"{icono} **{info['ticker']}** ({etiqueta})\n"
                                f"💰 ${info['precio']} | {info['veredicto']}\n"
                                f"🎯 TP: ${info['tp']}\n"
                                f"⛔ SL: ${info['sl']}\n" 
                                f"📝 _{info.get('motivo', '')}_\n"
                                f"〰〰〰〰〰〰〰〰〰\n"
                            )
            
            await msg_espera.delete()
            if hay: await update.message.reply_text(reporte, parse_mode=ParseMode.MARKDOWN)
            else: await update.message.reply_text(f"💤 Mercado lateral. No encontré entradas claras.")

        # ------------------------------------------------------------------
        # BLOQUE 3: ANALIZAR INDIVIDUAL
        # ------------------------------------------------------------------
        elif acc == "ANALIZAR" and tick:
            await msg_espera.edit_text(f"🔎 **Calculando {tick}...**")
            info, prob = await analizar_activo_completo(tick, est, cat)
            
            if info:
                # Generamos resumen humano usando la IA y los datos técnicos
                razon_ia = generar_resumen_humano(f"RSI:{info['rsi']} Motivo:{info.get('motivo')}", prob)
                aviso_modo = " | ⚠️ DIARIO" if info['backup'] else f" | {est.upper()}"
                
                tarjeta = (
                    f"💎 **{info['ticker']}** ({info.get('mercado', 'GEN')}){aviso_modo}\n"
                    f"💵 **Precio:** `${info['precio']}`\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💡 **CONCLUSIÓN:**\n"
                    f"👉 **{info['veredicto']}**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📝 **Análisis:** _{info.get('motivo', '')}_\n"
                    f"🤖 **IA:** _{razon_ia}_\n\n"
                    f"🛡️ **Gestión de Riesgo:**\n"
                    f"⛔ SL: `${info['sl']}`\n"
                    f"🎯 TP: `${info['tp']}`\n"
                    f"📉 RSI: `{info['rsi']}`"
                )
                await msg_espera.delete()
                await update.message.reply_text(tarjeta, parse_mode=ParseMode.MARKDOWN)
            else: 
                await msg_espera.delete()
                await update.message.reply_text(f"❌ No pude leer datos de {tick}.")

        # ------------------------------------------------------------------
        # BLOQUE 4: VIGILAR
        # ------------------------------------------------------------------
        elif acc == "VIGILAR" and tick:
            info, _ = await analizar_activo_completo(tick, "SWING", cat)
            await msg_espera.delete()
            if info:
                c = cargar_cartera()
                precio_limpio = float(info['precio'].replace(",",""))
                c.append({"ticker": tick, "precio_compra": precio_limpio})
                guardar_cartera(c)
                await update.message.reply_text(f"🛡️ Vigilando {tick} desde ${info['precio']}")
            else: await update.message.reply_text("❌ Error al obtener precio.")

        else:
            await msg_espera.delete()
            await update.message.reply_text("👋 Hola. Prueba: 'Qué hacemos hoy?', 'Oportunidades Cripto' o 'Analiza Tesla'.")

    except Exception as e:
        print(f"ERROR: {e}")
        try: await msg_espera.delete()
        except: pass
        await update.message.reply_text("⚠️ Ocurrió un error interno.")

# --- 🚀 CAZADOR AUTOMÁTICO (SOLO FOREX) 🚀 ---
async def cazador_automatico(context: ContextTypes.DEFAULT_TYPE):
    """
    Escanea periódicamente buscando oportunidades.
    CONFIGURADO SOLO PARA FOREX (FOR).
    """
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_CHAT_ID: return
    
    # ⚠️ SOLO FOREX
    categorias = ["FOREX"] 
    print("🕵️‍♂️ Cazador de Divisas (FOREX) Buscando...")
    
    for cat in categorias:
        candidatos = await escanear_mercado(cat, "SCALPING")
        for t in candidatos:
            info, prob = await analizar_activo_completo(t, "SCALPING", cat)
            
            if info:
                # Filtros de Sensibilidad para Scalping
                es_long = prob > 0.53
                es_short = prob < 0.47 
                
                if es_long or es_short:
                    titulo = info['tipo_operacion'] 
                    icono = info['icono']
                    fuerza = info['señal']
                    motivo = info.get('motivo', 'Patrón técnico detectado')
                    etiqueta = info.get('mercado', 'GEN')
                    
                    mensaje = (
                        f"{icono} **ALERTA AUTOMÁTICA: {titulo}**\n"
                        f"💎 Activo: **{info['ticker']}** ({etiqueta})\n"
                        f"📊 Señal: **{fuerza}**\n"
                        f"📝 Porqué: _{motivo}_\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"💰 Entrada: `${info['precio']}`\n"
                        f"🎯 TP: `${info['tp']}`\n"
                        f"⛔ SL: `${info['sl']}`"
                    )
                    
                    try:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje, parse_mode=ParseMode.MARKDOWN)
                        await asyncio.sleep(4) # Pausa para no saturar
                    except: pass

# --- ARRANQUE ---
if __name__ == '__main__':
    if not TELEGRAM_TOKEN: 
        print("❌ Error: Falta TELEGRAM_TOKEN en .env")
        exit()
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje))
    
    if app.job_queue:
        # Tarea automática: Cazador cada 30 minutos (1800 segundos)
        app.job_queue.run_repeating(cazador_automatico, interval=1800, first=30)
        
    print("🤖 BOT CAZADOR ACTIVO (SOLO FOREX + ETIQUETAS) 🚀")
    app.run_polling()
