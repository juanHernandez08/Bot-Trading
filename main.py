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
# 🧠 MEMORIA DEL BOT
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
# 🎛️ INTERFAZ DE USUARIO: BOTONES INTERACTIVOS Y GESTIÓN DE RIESGO
# ==========================================================
class BotonesTrading(View):
    def __init__(self, ticker, tipo_operacion, precio, tp, sl):
        super().__init__(timeout=None)
        self.ticker = ticker
        self.tipo_operacion = tipo_operacion
        
        # 🛠️ CORRECCIÓN: Limpiamos las comas del texto antes de convertir a decimales
        self.precio = float(str(precio).replace(',', ''))
        self.tp = float(str(tp).replace(',', ''))
        self.sl = float(str(sl).replace(',', ''))
        
        ticker_limpio = self.ticker.replace("-", "")
        self.simbolo_broker = ticker_limpio.replace("USD", "/USDT")
        
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
            await interaction.response.send_message("❌ Error: API de OKX no configurada o caída.", ephemeral=True)
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
                f"✅ **¡OPERACIÓN INSTITUCIONAL EJECUTADA!**\n"
                f"🏦 **Broker:** OKX Testnet\n"
                f"💎 **Activo:** `{self.simbolo_broker}` | **Posición:** `{'LONG 🟢' if side == 'buy' else 'SHORT 🔴'}`\n"
                f"💸 **Capital Comprometido:** `~${costo_usdt:.2f} USDT`\n"
                f"⚖️ **Lote:** `{LOTAJE_ACTUAL}` | 💵 **Entrada:** `${precio_ejecutado}`\n"
                f"---\n"
                f"🎯 **Take Profit:** `${self.tp}` ➔ _(Ganancia est.: +${ganancia_usdt:.2f})_\n"
                f"⛔ **Stop Loss:** `${self.sl}` ➔ _(Riesgo est.: -${riesgo_usdt:.2f})_\n"
                f"---\n"
                f"🆔 **ID de Orden:** `{orden.get('id', 'N/A')}`\n"
                f"🛡️ _Protección automática enviada al broker._"
            )
            await interaction.followup.send(msg_exito, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ **Error al ejecutar en OKX:**\n`{str(e)}`", ephemeral=True)

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
    texto_lower = texto.lower()

    # 🧪 COMANDO SECRETO DE PRUEBA
    if texto_lower == "probar botones":
        embed = discord.Embed(
            title="🧪 PRUEBA DE CONEXIÓN OKX",
            description="Simulación forzada para probar el Brazo Robótico.",
            color=discord.Color.blue()
        )
        vista = BotonesTrading("BTC-USD", "COMPRA", 60000.0, 62000.0, 59000.0) 
        await message.channel.send(embed=embed, view=vista)
        return

    # 🎛️ COMANDO DIRECTO: CONFIGURAR LOTE (MÁS FLEXIBLE CON REGEX)
    if "lote" in texto_lower or "configurar" in texto_lower:
        numeros = re.findall(r"[-+]?\d*\.\d+|\d+", texto)
        if numeros and ("lote" in texto_lower):
            try:
                nuevo_lote = float(numeros[0])
                global LOTAJE_ACTUAL
                LOTAJE_ACTUAL = nuevo_lote
                await message.channel.send(f"✅ **¡Memoria actualizada, socio!** \nA partir de ahora, las operaciones se ejecutarán con **`{LOTAJE_ACTUAL}` lotes**.")
                return
            except Exception:
                pass # Si falla, sigue de largo al cerebro de IA

    msg_espera = await message.channel.send("⏳ **Procesando comando...**")

    # 👁️ NUEVO COMANDO: VISUALIZAR (MODO RAYOS X - ESCÁNER GENERAL SIN FILTROS)
    if texto_lower.startswith("visualizar"):
        await msg_espera.edit(content="👁️ **Modo Rayos X: Escaneando todo el mercado en crudo...**")
        
        cats = ["CRIPTO", "FOREX", "ACCIONES"]
        est = "SCALPING"
        hay = False
        
        for c in cats:
            try: 
                candidatos = await escanear_mercado(c, est)
            except: 
                candidatos = []
                
            for t in candidatos:
                try:
                    info, prob = await analizar_activo_completo(t, est, c)
                    # AQUÍ ESTÁ LA MAGIA: Muestra todo, sin importar si es Neutral o baja probabilidad
                    if info:
                        hay = True
                        tipo_real = info.get('tipo_operacion', info.get('veredicto', 'NEUTRAL'))
                        
                        # Colores sin importar el filtro
                        color_tarjeta = discord.Color.light_gray() if "NEUTRAL" in tipo_real else (discord.Color.green() if "COMPRA" in tipo_real or "LONG" in tipo_real else discord.Color.red())
                        
                        embed = discord.Embed(
                            title=f"👁️ Rayos X en Crudo",
                            description=f"💎 **{info['ticker']}** ➔ **{tipo_real}**\n💪 **Fuerza: {prob}%**\n🤖 IA: _{info.get('motivo', 'Análisis en crudo sin filtro')}_",
                            color=color_tarjeta
                        )
                        embed.add_field(name="💰 Entrada", value=f"`${info['precio']}`", inline=True)
                        embed.add_field(name="🎯 TP", value=f"`${info['tp']}`", inline=True)
                        embed.add_field(name="⛔ SL", value=f"`${info['sl']}`", inline=True)
                        
                        # Forzamos un botón verde si es Neutral para que puedas presionar y probar la orden
                        tipo_para_boton = "COMPRA" if "NEUTRAL" in tipo_real else tipo_real
                        vista = BotonesTrading(info['ticker'], tipo_para_boton, info['precio'], info['tp'], info['sl'])
                        
                        await message.channel.send(embed=embed, view=vista)
                except Exception as e: 
                    continue 
        
        await msg_espera.delete()
        if not hay: 
            await message.channel.send("❌ No se encontraron activos en la lista.")
        return

    # Si no es visualizar ni lote, pasa por el cerebro de la IA
    try:
        data = interpretar_intencion(texto)
        acc = data.get("accion", "CHARLA")
        tick = data.get("ticker")
        lst = data.get("lista_activos")
        
        est = data.get("estilo", "SCALPING")
        cat = data.get("categoria", "GENERAL") 
        if acc == "ANALIZAR" and not tick and not lst: acc = "RECOMENDAR"

        # 1. COMPARAR
        if acc == "COMPARAR" and lst:
            await msg_espera.edit(content=f"⚖️ **Comparando...**")
            await msg_espera.delete()
            await message.channel.send("Funcionalidad de comparar procesada.")

        # 2. RECOMENDAR (Escáner Manual NORMAL CON FILTROS)
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
                            
                            vista = BotonesTrading(info['ticker'], tipo, info['precio'], info['tp'], info['sl'])
                            await message.channel.send(embed=embed, view=vista)
                    except: continue 
            
            await msg_espera.delete()
            if not hay: await message.channel.send(f"💤 Mercado lateral en {cat}. Sin entradas claras.")

        # 3. ANALIZAR INDIVIDUAL NORMAL
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
                    vista = BotonesTrading(info['ticker'], tipo, info['precio'], info['tp'], info['sl'])
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
        print(traceback.format_exc()) 
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
                        if tipo == "NEUTRAL" or prob < 40: 
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

                        vista = BotonesTrading(info['ticker'], tipo, info['precio'], info['tp'], info['sl'])
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
