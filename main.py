import os
import asyncio
import traceback
import discord
from discord.ext import tasks
from dotenv import load_dotenv

from src.data_loader import descargar_datos 
from src.strategy import examinar_activo
from src.brain import interpretar_intencion, generar_resumen_humano
from src.scanner import escanear_mercado

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ==========================================================
# 🏢 MAPA DEL CUARTEL GENERAL (TUS CANALES)
# ==========================================================
CANALES_ALERTAS = {
    "FOREX": 1477333205341180047,
    "CRIPTO": 1477333234768417004,
    "ACCIONES": 1477333258634006689
}

# Configuramos los permisos
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

async def analizar_activo_completo(ticker, estilo, categoria):
    df, backup_mode = await descargar_datos(ticker, estilo)
    if df is None or df.empty: return None, 0.0
    info, prob = examinar_activo(df, ticker, estilo, categoria)
    if info:
        info['backup'] = backup_mode
        return info, prob
    return None, 0.0

@client.event
async def on_ready():
    print(f"🤖 BOT HÍBRIDO CONECTADO A DISCORD COMO: {client.user}")
    if not cazador_automatico.is_running():
        cazador_automatico.start()

@client.event
async def on_message(message):
    # Evitar que el bot se responda a sí mismo
    if message.author == client.user:
        return

    texto = message.content
    msg_espera = await message.channel.send("⏳ **Analizando...**")
    
    try:
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        
        est = data.get("estilo")
        if not est: est = "SCALPING"
        
        cat = data.get("categoria", "GENERAL") 
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # 1. COMPARAR
        if acc == "COMPARAR" and lst:
            await msg_espera.edit(content=f"⚖️ **Comparando...**")
            reporte = f"📊 **Estrategia** | {est}\n━━━━━━━━━━━━━━━━━━\n"
            encontrados = False
            for t in lst:
                info, prob = await analizar_activo_completo(t, est, cat)
                if info:
                    encontrados = True
                    icono = info['icono']
                    if info['tipo_operacion'] == "NEUTRAL": icono = "⚪"
                    reporte += (
                        f"💎 **{info['ticker']}** ({info.get('mercado', 'GEN')})\n"
                        f"💰 ${info['precio']} | {info['tipo_operacion']} {icono}\n"
                        f"🎯 TP: ${info['tp']} | ⛔ SL: ${info['sl']}\n"
                        f"📝 _{info.get('motivo', '')}_\n\n"
                    )
            await msg_espera.delete()
            if encontrados: await message.channel.send(reporte)
            else: await message.channel.send("❌ No encontré datos para comparar.")

        # 2. RECOMENDAR (El Mega Escáner Manual)
        elif acc == "RECOMENDAR":
            cats = ["CRIPTO", "FOREX", "ACCIONES"] if cat == "GENERAL" else [cat]
            await msg_espera.edit(content=f"🌎 **Escaneando {cat} ({est})...**")
            
            reporte = f"⚡ **OPORTUNIDADES ({est})**\n━━━━━━━━━━━━━━━━━━\n"
            hay = False
            
            for c in cats:
                try: candidatos = await escanear_mercado(c, est)
                except: candidatos = []
                for t in candidatos:
                    try:
                        info, prob = await analizar_activo_completo(t, est, c)
                        if info:
                            # Filtro: Silenciar Neutrales
                            if info['tipo_operacion'] == "NEUTRAL": continue

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
            if hay: await message.channel.send(reporte)
            else: await message.channel.send(f"💤 Mercado lateral en {cat}. Sin entradas claras.")

        # 3. ANALIZAR INDIVIDUAL
        elif acc == "ANALIZAR" and tick:
            await msg_espera.edit(content=f"🔎 **Calculando {tick}...**")
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
                await message.channel.send(tarjeta)
            else: 
                await msg_espera.delete()
                await message.channel.send(f"❌ No pude leer datos de {tick}.")
        
        else:
            await msg_espera.delete()
            await message.channel.send("👋 Hola. Prueba 'Oportunidades Forex' o 'Analiza BTC'.")

    except Exception as e:
        print(traceback.format_exc()) 
        try: await msg_espera.delete() 
        except: pass
        await message.channel.send(f"⚠️ **Error Técnico:**\n`{str(e)}`")

# ==========================================================
# 🎯 EL CAZADOR AUTOMÁTICO (ENRUTADOR INTELIGENTE CON EMBEDS)
# ==========================================================
@tasks.loop(minutes=30)
async def cazador_automatico():
    # Ahora el cazador escanea los 3 mercados
    categorias_a_escanear = ["FOREX", "CRIPTO", "ACCIONES"]
    estilos = ["SCALPING", "SWING"]
    
    for cat in categorias_a_escanear:
        # Busca el canal correspondiente a esta categoría
        canal_id = CANALES_ALERTAS.get(cat)
        if not canal_id: continue
        
        channel = client.get_channel(canal_id)
        if not channel: continue # Si el canal no existe, lo salta

        for estilo in estilos:
            try:
                candidatos = await escanear_mercado(cat, estilo)
                for t in candidatos:
                    info, prob = await analizar_activo_completo(t, estilo, cat)
                    if info:
                        tipo = info.get('tipo_operacion', 'NEUTRAL')
                        if tipo == "NEUTRAL": continue

                        titulo = "OPORTUNIDAD DE ORO" if estilo == "SWING" else "ALERTA SCALPING"
                        emoji = "🏆" if estilo == "SWING" else "⚡"
                        
                        # ✨ LA MAGIA DEL EMBED ✨
                        # 1. Definimos el color (Verde para LONG, Rojo para SHORT)
                        if "LONG" in tipo or "COMPRA" in tipo:
                            color_tarjeta = discord.Color.green()
                        else:
                            color_tarjeta = discord.Color.red()

                        # 2. Creamos la estructura de la tarjeta
                        embed = discord.Embed(
                            title=f"{emoji} {titulo}",
                            description=f"💎 **{info['ticker']}** ({info.get('mercado','GEN')}) ➔ **{tipo}**",
                            color=color_tarjeta
                        )

                        # 3. Agregamos las columnas (inline=True hace que se pongan una al lado de la otra)
                        embed.add_field(name="💰 Entrada", value=f"`${info['precio']}`", inline=True)
                        embed.add_field(name="🎯 Take Profit", value=f"`${info['tp']}`", inline=True)
                        embed.add_field(name="⛔ Stop Loss", value=f"`${info['sl']}`", inline=True)
                        
                        # 4. Agregamos la razón en una fila completa abajo (inline=False)
                        embed.add_field(name="📝 Análisis", value=f"_{info.get('motivo', '')}_", inline=False)
                        
                        # 5. Un toque profesional al final de la tarjeta
                        embed.set_footer(text="Cazador FX • Algoritmo de Trading")

                        # Envía el Embed al canal correspondiente
                        try: await channel.send(embed=embed)
                        except Exception as e: print(f"Error enviando embed a Discord: {e}")
            except Exception as e: 
                pass

@cazador_automatico.before_loop
async def before_cazador():
    await client.wait_until_ready()

if __name__ == '__main__':
    if DISCORD_TOKEN:
        client.run(DISCORD_TOKEN)
    else:
        print("❌ Falta el DISCORD_TOKEN en las variables de entorno.")
