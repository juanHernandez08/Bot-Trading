import os
import asyncio
import traceback
import re
import discord
from discord.ext import tasks
from discord.ui import Button, View
from dotenv import load_dotenv
import ccxt

from src.data_loader import descargar_datos 
from src.strategy import examinar_activo
from src.brain import interpretar_intencion, generar_resumen_humano
from src.scanner import escanear_mercado

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ==========================================================
# 🧠 MEMORIA DEL BOT (Valor por defecto y seguro)
# ==========================================================
LOTAJE_ACTUAL = 0.01

# ==========================================================
# 🏢 MAPA DEL CUARTEL GENERAL (TUS CANALES)
# ==========================================================
CANALES_ALERTAS = {
    "FOREX": 1477333205341180047,
    "CRIPTO": 1477333234768417004,
    "ACCIONES": 1477333258634006689
}

# ==========================================================
# 🔌 CONEXIÓN AL BROKER (BINANCE TESTNET)
# ==========================================================
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

try:
    broker = ccxt.binance({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_API_SECRET,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'} # Aseguramos que opere en el mercado Spot
    })
    broker.set_sandbox_mode(True) # ¡CRÍTICO! Esto activa el dinero de prueba
    print("✅ Conexión a Binance Testnet ESTABLECIDA.")
except Exception as e:
    print(f"❌ Error al conectar con Binance: {e}")
    broker = None

# Configuramos los permisos de Discord
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ==========================================================
# 🎛️ INTERFAZ DE USUARIO: BOTONES INTERACTIVOS
# ==========================================================
class BotonesTrading(View):
    def __init__(self, ticker, tipo_operacion):
        super().__init__(timeout=None)
        self.ticker = ticker
        
        # 🛠️ CORRECCIÓN DEL SÍMBOLO PARA BINANCE 🛠️
        # Quitamos el guion si existe, y luego armamos el par correcto
        ticker_limpio = self.ticker.replace("-", "") # Convierte BTC-USD en BTCUSD
        self.simbolo_broker = ticker_limpio.replace("USD", "/USDT") # Convierte BTCUSD en BTC/USDT
        
        if "LONG" in tipo_operacion or "COMPRA" in tipo_operacion:
            btn = Button(label=f"🟢 Ejecutar COMPRA a {LOTAJE_ACTUAL} lotes", style=discord.ButtonStyle.success)
            btn.callback = self.ejecutar_compra
            self.add_item(btn)
        elif "SHORT" in tipo_operacion or "VENTA" in tipo_operacion:
            btn = Button(label=f"🔴 Ejecutar VENTA a {LOTAJE_ACTUAL} lotes", style=discord.ButtonStyle.danger)
            btn.callback = self.ejecutar_venta
            self.add_item(btn)

    async def ejecutar_compra(self, interaction: discord.Interaction):
        await self.enviar_orden(interaction, 'buy')

    async def ejecutar_venta(self, interaction: discord.Interaction):
        await self.enviar_orden(interaction, 'sell')

    async def enviar_orden(self, interaction: discord.Interaction, side: str):
        if not broker:
            await interaction.response.send_message("❌ Error: API de Binance no configurada o caída.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True) 

        try:
            orden = broker.create_market_order(self.simbolo_broker, side, LOTAJE_ACTUAL)
            msg_exito = (
                f"✅ **¡OPERACIÓN EJECUTADA CON ÉXITO!**\n"
                f"🏦 **Broker:** Binance Testnet\n"
                f"💎 **Activo:** `{self.simbolo_broker}`\n"
                f"⚖️ **Lote:** `{LOTAJE_ACTUAL}`\n"
                f"🆔 **ID de Orden:** `{orden['id']}`"
            )
            await interaction.followup.send(msg_exito, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ **Error al ejecutar en Binance:**\n`{str(e)}`", ephemeral=True)

# ==========================================================
# 🧠 LÓGICA PRINCIPAL DEL BOT
# ==========================================================
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
    if message.author == client.user:
        return

    texto = message.content

    # 🧪 COMANDO SECRETO DE PRUEBA
    if texto.lower() == "probar botones":
        embed = discord.Embed(
            title="🧪 PRUEBA DE CONEXIÓN BYBIT",
            description="Simulación forzada para probar el Brazo Robótico.",
            color=discord.Color.blue()
        )
        vista = BotonesTrading("BTC-USD", "COMPRA") 
        await message.channel.send(embed=embed, view=vista)
        return

    # 🧪 COMANDO DE DIAGNÓSTICO PROFUNDO
    if texto.lower() == "diagnostico":
        key = os.getenv("BYBIT_API_KEY", "")
        secret = os.getenv("BYBIT_API_SECRET", "")
        
        if not key or not secret:
            await message.channel.send("❌ **ERROR CRÍTICO:** Railway no está leyendo las variables. Están vacías.")
            return
            
        key_oculta = f"{key[:4]}...{key[-4:]}" if len(key) >= 8 else key
        
        msg = (
            f"🔍 **DIAGNÓSTICO DE VARIABLES EN RAILWAY**\n"
            f"🔑 **API Key leída:** `{key_oculta}`\n"
            f"📏 **Longitud de la Key:** `{len(key)}` caracteres (Deberían ser 18)\n"
            f"📏 **Longitud del Secret:** `{len(secret)}` caracteres (Deberían ser 36)\n"
        )
        await message.channel.send(msg)
        
        try:
            test_broker = ccxt.bybit({
                'apiKey': key.strip(), 
                'secret': secret.strip(),
                'enableRateLimit': True,
            })
            test_broker.set_sandbox_mode(True)
            balance = test_broker.fetch_balance()
            await message.channel.send("✅ **¡TEST INTERNO EXITOSO!** El problema eran espacios ocultos. Conectado a Bybit Testnet.")
        except Exception as e:
            await message.channel.send(f"⚠️ **FALLÓ EL TEST INTERNO:**\n`{str(e)}`")
        return

    # Si no es un comando de prueba, sigue el flujo normal
    msg_espera = await message.channel.send("⏳ **Analizando...**")
    
    try:
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        
        est = data.get("estilo", "SCALPING")
        cat = data.get("categoria", "GENERAL") 
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # 🎛️ MEMORIA: CONFIGURAR LOTE
        if acc == "CONFIGURAR_LOTE":
            global LOTAJE_ACTUAL
            nuevo_lote = data.get("valor")
            LOTAJE_ACTUAL = nuevo_lote
            await msg_espera.delete()
            await message.channel.send(f"✅ **¡Entendido, socio!** \nHe actualizado mi memoria. A partir de ahora, ejecutaré las operaciones con **`{LOTAJE_ACTUAL}` lotes**.")
            return

        # 1. COMPARAR
        if acc == "COMPARAR" and lst:
            await msg_espera.edit(content=f"⚖️ **Comparando...**")
            # Logica de comparar
            await msg_espera.delete()
            await message.channel.send("Funcionalidad de comparar procesada.")

        # 2. RECOMENDAR (Escáner Manual)
        elif acc == "RECOMENDAR":
            cats = ["CRIPTO", "FOREX", "ACCIONES"] if cat == "GENERAL" else [cat]
            await msg_espera.edit(content=f"🌎 **Escaneando {cat} ({est})...**")
            
            hay = False
            for c in cats:
                try: candidatos = await escanear_mercado(c, est)
                except: candidatos = []
                for t in candidatos:
                    try:
                        info, prob = await analizar_activo_completo(t, est, c)
                        if info and info['tipo_operacion'] != "NEUTRAL":
                            hay = True
                            tipo = info['tipo_operacion']
                            icono = "🔥" if info.get('señal') in ["FUERTE", "GOLDEN"] else "⚡"
                            color_tarjeta = discord.Color.green() if "LONG" in tipo else discord.Color.red()

                            embed = discord.Embed(
                                title=f"{icono} Oportunidad ({est})",
                                description=f"💎 **{info['ticker']}** ➔ **{tipo}**\n💪 **Fuerza: {prob}%**",
                                color=color_tarjeta
                            )
                            embed.add_field(name="💰 Entrada", value=f"`${info['precio']}`", inline=True)
                            embed.add_field(name="🎯 TP", value=f"`${info['tp']}`", inline=True)
                            embed.add_field(name="⛔ SL", value=f"`${info['sl']}`", inline=True)
                            
                            vista = BotonesTrading(info['ticker'], tipo)
                            await message.channel.send(embed=embed, view=vista)
                    except: continue 
            
            await msg_espera.delete()
            if not hay: await message.channel.send(f"💤 Mercado lateral en {cat}. Sin entradas claras.")

        # 3. ANALIZAR INDIVIDUAL
        elif acc == "ANALIZAR" and tick:
            await msg_espera.edit(content=f"🔎 **Calculando {tick}...**")
            info, prob = await analizar_activo_completo(tick, est, cat)
            
            if info:
                tipo = info.get('veredicto', 'NEUTRAL')
                razon_ia = generar_resumen_humano(f"RSI:{info['rsi']} Motivo:{info.get('motivo')}", prob)
                
                color_tarjeta = discord.Color.green() if "COMPRA" in tipo or "LONG" in tipo else discord.Color.red()
                if "NEUTRAL" in tipo: color_tarjeta = discord.Color.light_gray()

                embed = discord.Embed(
                    title=f"🔎 Análisis de {info['ticker']}",
                    description=f"👉 **{tipo}**\n🤖 IA: _{razon_ia}_",
                    color=color_tarjeta
                )
                embed.add_field(name="💰 Precio", value=f"`${info['precio']}`", inline=True)
                embed.add_field(name="🎯 TP", value=f"`${info['tp']}`", inline=True)
                embed.add_field(name="⛔ SL", value=f"`${info['sl']}`", inline=True)

                await msg_espera.delete()
                
                if "NEUTRAL" not in tipo:
                    vista = BotonesTrading(info['ticker'], tipo)
                    await message.channel.send(embed=embed, view=vista)
                else:
                    await message.channel.send(embed=embed)
            else: 
                await msg_espera.delete()
                await message.channel.send(f"❌ No pude leer datos de {tick}.")
        
        else:
            await msg_espera.delete()
            await message.channel.send("👋 Hola. Prueba 'Oportunidades Cripto' o 'Analiza BTC'.")

    except Exception as e:
        print(traceback.format_exc()) # Imprime el error detallado en la consola de Railway
        try: await msg_espera.delete() 
        except: pass
        await message.channel.send(f"⚠️ **Error Técnico:**\n`{str(e)}`")

# ==========================================================
# 🎯 EL CAZADOR AUTOMÁTICO (ENRUTADOR Y FILTRO ÉLITE)
# ==========================================================
@tasks.loop(minutes=30)
async def cazador_automatico():
    categorias_a_escanear = ["FOREX", "CRIPTO", "ACCIONES"]
    estilos = ["SCALPING", "SWING"]
    
    for cat in categorias_a_escanear:
        canal_id = CANALES_ALERTAS.get(cat)
        if not canal_id: continue
        
        channel = client.get_channel(canal_id)
        if not channel: continue 

        for estilo in estilos:
            try:
                candidatos = await escanear_mercado(cat, estilo)
                for t in candidatos:
                    info, prob = await analizar_activo_completo(t, estilo, cat)
                    if info:
                        tipo = info.get('tipo_operacion', 'NEUTRAL')
                        if tipo == "NEUTRAL" or prob < 60: 
                            continue

                        titulo = "OPORTUNIDAD DE ORO" if estilo == "SWING" else "ALERTA SCALPING"
                        emoji = "🏆" if estilo == "SWING" else "⚡"
                        color_tarjeta = discord.Color.green() if "LONG" in tipo or "COMPRA" in tipo else discord.Color.red()

                        embed = discord.Embed(
                            title=f"{emoji} {titulo}",
                            description=f"💎 **{info['ticker']}** ({info.get('mercado','GEN')}) ➔ **{tipo}**\n💪 **Fuerza: {prob}%**",
                            color=color_tarjeta
                        )
                        embed.add_field(name="💰 Entrada", value=f"`${info['precio']}`", inline=True)
                        embed.add_field(name="🎯 TP", value=f"`${info['tp']}`", inline=True)
                        embed.add_field(name="⛔ SL", value=f"`${info['sl']}`", inline=True)
                        embed.add_field(name="📝 Análisis", value=f"_{info.get('motivo', '')}_", inline=False)
                        embed.set_footer(text="Cazador FX • Algoritmo de Trading")

                        vista = BotonesTrading(info['ticker'], tipo)
                        try: await channel.send(embed=embed, view=vista)
                        except Exception as e: pass
            except Exception as e: 
                pass

@cazador_automatico.before_loop
async def before_cazador():
    await client.wait_until_ready()

if __name__ == '__main__':
    if DISCORD_TOKEN:
        client.run(DISCORD_TOKEN)
    else:
        print("❌ Falta el DISCORD_TOKEN.")
