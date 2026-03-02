import os
import asyncio
import traceback
import re
import discord
from discord.ext import tasks
from discord.ui import Button, View
from dotenv import load_dotenv
import ccxt
import yfinance as yf  # <-- NUEVA LIBRERÍA PARA LAS NOTICIAS

from src.data_loader import descargar_datos 
from src.strategy import examinar_activo
from src.brain import interpretar_intencion, generar_resumen_humano
from src.scanner import escanear_mercado

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ==========================================================
# 🧠 MEMORIA DEL BOT
# ==========================================================
LOTAJE_ACTUAL = 0.01

# ==========================================================
# 🏢 MAPA DEL CUARTEL GENERAL (TUS CANALES)
# ==========================================================
CANALES_ALERTAS = {
    "FOREX": 1477333205341180047,
    "CRIPTO": 1477333234768417004,
    "ACCIONES": 1477333258634006689,
    "NOTICIAS": 1478135975136989294 # ⚠️ ¡CAMBIA ESTO POR EL ID DE TU CANAL NUEVO!
}

# Diccionario para rastrear inactividad del mercado
rondas_vacias = {"FOREX": 0, "CRIPTO": 0, "ACCIONES": 0}

# ==========================================================
# 🔌 CONEXIÓN AL BROKER (OKX DEMO TRADING)
# ==========================================================
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_API_SECRET = os.getenv("OKX_API_SECRET")
OKX_PASSWORD = os.getenv("OKX_PASSWORD")

try:
    broker = ccxt.okx({
        'apiKey': OKX_API_KEY,
        'secret': OKX_API_SECRET,
        'password': OKX_PASSWORD,
        'enableRateLimit': True,
    })
    broker.set_sandbox_mode(True) 
    print("✅ Conexión a OKX Demo ESTABLECIDA.")
except Exception as e:
    print(f"❌ Error al conectar con OKX: {e}")
    broker = None

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ==========================================================
# 🎛️ INTERFAZ DE USUARIO: BOTONES INTERACTIVOS
# ==========================================================
class BotonesTrading(View):
    def __init__(self, ticker, tipo_operacion, precio, tp, sl):
        super().__init__(timeout=None)
        self.ticker = ticker
        self.tipo_operacion = tipo_operacion
        
        self.precio = float(str(precio).replace(',', ''))
        self.tp = float(str(tp).replace(',', ''))
        self.sl = float(str(sl).replace(',', ''))
        
        ticker_limpio = self.ticker.replace("-", "")
        self.simbolo_broker = ticker_limpio.replace("USD", "/USDT")
        
        if "LONG" in tipo_operacion or "COMPRA" in tipo_operacion:
            btn = Button(label=f"🟢 COMPRAR {LOTAJE_ACTUAL} lotes", style=discord.ButtonStyle.success)
            btn.callback = self.ejecutar_compra
            self.add_item(btn)
        elif "SHORT" in tipo_operacion or "VENTA" in tipo_operacion:
            btn = Button(label=f"🔴 VENDER {LOTAJE_ACTUAL} lotes", style=discord.ButtonStyle.danger)
            btn.callback = self.ejecutar_venta
            self.add_item(btn)

    async def ejecutar_compra(self, interaction: discord.Interaction):
        await self.enviar_orden(interaction, 'buy')

    async def ejecutar_venta(self, interaction: discord.Interaction):
        await self.enviar_orden(interaction, 'sell')

    async def enviar_orden(self, interaction: discord.Interaction, side: str):
        if not broker:
            await interaction.response.send_message("❌ Error: API de OKX no configurada.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True) 

        try:
            costo_usdt = float(LOTAJE_ACTUAL) * self.precio
            ganancia_usdt = abs(self.tp - self.precio) * float(LOTAJE_ACTUAL)
            riesgo_usdt = abs(self.precio - self.sl) * float(LOTAJE_ACTUAL)

            parametros_extra = {
                'takeProfit': {'triggerPrice': self.tp},
                'stopLoss': {'triggerPrice': self.sl}
            }

            orden = broker.create_market_order(
                symbol=self.simbolo_broker, 
                side=side, 
                amount=LOTAJE_ACTUAL,
                params=parametros_extra
            )
            
            precio_ejecutado = orden.get('average', orden.get('price', self.precio))
            if precio_ejecutado is None: precio_ejecutado = self.precio

            msg_exito = (
                f"✅ **¡ORDEN ENVIADA A OKX!**\n"
                f"💎 **Activo:** `{self.simbolo_broker}` | **Tipo:** `{'COMPRA' if side == 'buy' else 'VENTA'}`\n"
                f"💸 **Costo Aprox:** `${costo_usdt:.2f} USD`\n"
                f"⚖️ **Lote:** `{LOTAJE_ACTUAL}` | 💵 **Entrada:** `${precio_ejecutado}`\n"
                f"---\n"
                f"🎯 **TP:** `${self.tp}` _(+${ganancia_usdt:.2f})_\n"
                f"⛔ **SL:** `${self.sl}` _(-${riesgo_usdt:.2f})_\n"
                f"---\n"
                f"🆔 **ID:** `{orden.get('id', 'N/A')}`\n"
            )
            await interaction.followup.send(msg_exito, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ **Rechazo del Broker:**\n`{str(e)}`", ephemeral=True)

# ==========================================================
# 🧠 LÓGICA DE ANÁLISIS
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
    print(f"🤖 CAZADOR FX CONECTADO COMO: {client.user}")
    if not cazador_automatico.is_running():
        cazador_automatico.start()
    if not noticiero_automatico.is_running():
        noticiero_automatico.start()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    texto = message.content
    texto_lower = texto.lower()

    # COMANDO DIRECTO: CONFIGURAR LOTE
    if "lote" in texto_lower or "configurar" in texto_lower:
        numeros = re.findall(r"[-+]?\d*\.\d+|\d+", texto)
        if numeros and ("lote" in texto_lower):
            try:
                global LOTAJE_ACTUAL
                LOTAJE_ACTUAL = float(numeros[0])
                await message.channel.send(f"✅ **Memoria actualizada.** Operaré con **`{LOTAJE_ACTUAL}` lotes**.")
                return
            except Exception: pass 

    msg_espera = await message.channel.send("⏳ **Procesando...**")

    # COMANDO: VISUALIZAR (RAYOS X)
    if texto_lower.startswith("visualizar"):
        await msg_espera.edit(content="👁️ **Rayos X: Escaneando sin filtros...**")
        hay = False
        
        for c in ["CRIPTO", "FOREX", "ACCIONES"]:
            try: candidatos = await escanear_mercado(c, "SCALPING")
            except: candidatos = []
            for t in candidatos:
                try:
                    info, prob = await analizar_activo_completo(t, "SCALPING", c)
                    if info:
                        hay = True
                        tipo_real = info.get('tipo_operacion', info.get('veredicto', 'NEUTRAL'))
                        color = discord.Color.light_gray() if "NEUTRAL" in tipo_real else (discord.Color.green() if "COMPRA" in tipo_real or "LONG" in tipo_real else discord.Color.red())
                        
                        embed = discord.Embed(
                            title=f"👁️ Rayos X: {info['ticker']}",
                            description=f"Estado: **{tipo_real}** (Fuerza: {prob}%)\n🤖 IA: _{info.get('motivo', 'Análisis crudo')}_",
                            color=color
                        )
                        embed.add_field(name="Entrada", value=f"`${info['precio']}`")
                        embed.add_field(name="TP", value=f"`${info['tp']}`")
                        embed.add_field(name="SL", value=f"`${info['sl']}`")
                        
                        tipo_btn = "COMPRA" if "NEUTRAL" in tipo_real else tipo_real
                        vista = BotonesTrading(info['ticker'], tipo_btn, info['precio'], info['tp'], info['sl'])
                        await message.channel.send(embed=embed, view=vista)
                except: continue 
        
        await msg_espera.delete()
        if not hay: await message.channel.send("❌ No hay datos.")
        return

    # FLUJO NORMAL (Manual)
    try:
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        est = data.get("estilo", "SCALPING")
        cat = data.get("categoria", "GENERAL") 
        if acc == "ANALIZAR" and not tick: acc = "RECOMENDAR"

        if acc == "RECOMENDAR":
            cats = ["CRIPTO", "FOREX", "ACCIONES"] if cat == "GENERAL" else [cat]
            await msg_espera.edit(content=f"🌎 **Buscando oportunidades en {cat}...**")
            
            hay = False
            for c in cats:
                try: candidatos = await escanear_mercado(c, est)
                except: candidatos = []
                for t in candidatos:
                    try:
                        info, prob = await analizar_activo_completo(t, est, c)
                        if info and info['tipo_operacion'] != "NEUTRAL" and prob >= 40:
                            hay = True
                            tipo = info['tipo_operacion']
                            embed = discord.Embed(
                                title=f"⚡ Alerta Manual ({est})",
                                description=f"💎 **{info['ticker']}** ➔ **{tipo}**\n💪 Fuerza: {prob}%",
                                color=discord.Color.green() if "LONG" in tipo else discord.Color.red()
                            )
                            embed.add_field(name="Entrada", value=f"`${info['precio']}`")
                            embed.add_field(name="TP", value=f"`${info['tp']}`")
                            embed.add_field(name="SL", value=f"`${info['sl']}`")
                            
                            vista = BotonesTrading(info['ticker'], tipo, info['precio'], info['tp'], info['sl'])
                            
                            # Enrutamiento Manual (Opcional, pero te lo dejo en el mismo canal para que lo veas al pedirlo)
                            await message.channel.send(embed=embed, view=vista)
                    except: continue 
            
            await msg_espera.delete()
            if not hay: await message.channel.send(f"💤 Mercado lateral en {cat}.")

        elif acc == "ANALIZAR" and tick:
            await msg_espera.edit(content=f"🔎 **Calculando {tick}...**")
            info, prob = await analizar_activo_completo(tick, est, cat)
            if info:
                tipo = info.get('veredicto', 'NEUTRAL')
                color = discord.Color.light_gray() if "NEUTRAL" in tipo else (discord.Color.green() if "COMPRA" in tipo or "LONG" in tipo else discord.Color.red())
                embed = discord.Embed(
                    title=f"🔎 Análisis: {info['ticker']}",
                    description=f"👉 **{tipo}**\n🤖 IA: _{info.get('motivo', '...')}_",
                    color=color
                )
                embed.add_field(name="Precio", value=f"`${info['precio']}`")
                embed.add_field(name="TP", value=f"`${info['tp']}`")
                embed.add_field(name="SL", value=f"`${info['sl']}`")

                await msg_espera.delete()
                if "NEUTRAL" not in tipo:
                    vista = BotonesTrading(info['ticker'], tipo, info['precio'], info['tp'], info['sl'])
                    await message.channel.send(embed=embed, view=vista)
                else:
                    await message.channel.send(embed=embed)
            else: 
                await msg_espera.delete()
                await message.channel.send(f"❌ Sin datos de {tick}.")
        else:
            await msg_espera.delete()
    except Exception as e:
        try: await msg_espera.delete() 
        except: pass
        await message.channel.send(f"⚠️ **Error:** `{str(e)}`")

# ==========================================================
# 🎯 RUTINAS AUTOMÁTICAS (CAZADOR Y NOTICIERO)
# ==========================================================
@tasks.loop(minutes=30)
async def cazador_automatico():
    categorias_a_escanear = ["FOREX", "CRIPTO", "ACCIONES"]
    estilos = ["SCALPING", "SWING"]
    global rondas_vacias
    
    for cat in categorias_a_escanear:
        canal_id = CANALES_ALERTAS.get(cat)
        if not canal_id: continue
        channel = client.get_channel(canal_id)
        if not channel: continue 

        hubo_senal_en_categoria = False

        for estilo in estilos:
            try:
                candidatos = await escanear_mercado(cat, estilo)
                for t in candidatos:
                    info, prob = await analizar_activo_completo(t, estilo, cat)
                    if info:
                        tipo = info.get('tipo_operacion', 'NEUTRAL')
                        if tipo == "NEUTRAL" or prob < 40: continue

                        hubo_senal_en_categoria = True
                        color = discord.Color.green() if "LONG" in tipo or "COMPRA" in tipo else discord.Color.red()
                        embed = discord.Embed(
                            title=f"🤖 Radar Automático ({estilo})",
                            description=f"💎 **{info['ticker']}** ➔ **{tipo}**\n💪 **Fuerza: {prob}%**",
                            color=color
                        )
                        embed.add_field(name="💰 Entrada", value=f"`${info['precio']}`", inline=True)
                        embed.add_field(name="🎯 TP", value=f"`${info['tp']}`", inline=True)
                        embed.add_field(name="⛔ SL", value=f"`${info['sl']}`", inline=True)
                        embed.add_field(name="📝 Análisis", value=f"_{info.get('motivo', '')}_", inline=False)

                        vista = BotonesTrading(info['ticker'], tipo, info['precio'], info['tp'], info['sl'])
                        try: await channel.send(embed=embed, view=vista)
                        except Exception: pass
            except Exception: pass
        
        # Lógica del Heartbeat (Reporte de inactividad cada hora = 2 ciclos de 30 min)
        if hubo_senal_en_categoria:
            rondas_vacias[cat] = 0
        else:
            rondas_vacias[cat] += 1
            if rondas_vacias[cat] >= 2:
                embed_vacio = discord.Embed(
                    title=f"📡 Reporte de Radar: {cat}",
                    description=f"En la última hora no he detectado tendencias seguras en el mercado de **{cat}**. He filtrado el ruido para proteger el capital. Sigo monitoreando... 🦉",
                    color=discord.Color.dark_gray()
                )
                try: await channel.send(embed=embed_vacio)
                except: pass
                rondas_vacias[cat] = 0

@cazador_automatico.before_loop
async def before_cazador():
    await client.wait_until_ready()

# --- NUEVO: MOTOR DE NOTICIAS ---
@tasks.loop(hours=1)
async def noticiero_automatico():
    canal_id = CANALES_ALERTAS.get("NOTICIAS")
    if not canal_id: return
    channel = client.get_channel(canal_id)
    if not channel: return

    try:
        # Usamos el SPY (S&P 500) para obtener noticias clave de la economía global
        ticker_mercado = yf.Ticker("SPY")
        noticias = ticker_mercado.news[:3] # Tomamos las 3 más recientes
        
        if noticias:
            embed = discord.Embed(
                title="📰 Boletín Económico de la Hora",
                description="Últimos movimientos institucionales y noticias de impacto global.",
                color=discord.Color.blue()
            )
            for n in noticias:
                titulo = n.get('title', 'Noticia de Mercado')
                link = n.get('link', 'https://finance.yahoo.com')
                editor = n.get('publisher', 'Fuente Financiera')
                embed.add_field(name=f"🗞️ {editor}", value=f"[{titulo}]({link})", inline=False)
            
            await channel.send(embed=embed)
    except Exception as e:
        print(f"Error en noticias: {e}")

@noticiero_automatico.before_loop
async def before_noticiero():
    await client.wait_until_ready()

if __name__ == '__main__':
    if DISCORD_TOKEN:
        client.run(DISCORD_TOKEN)
