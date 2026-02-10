import yfinance as yf
import pandas as pd

# --- UNIVERSO DE ACTIVOS (AQUÍ PUEDES AGREGAR MÁS) ---
UNIVERSO = {
    "FOREX": [
        'EURUSD=X', 'GBPUSD=X', 'JPY=X', 'AUDUSD=X', 'NZDUSD=X', 
        'USDCAD=X', 'USDCHF=X', 'COP=X', 'MXN=X', 'BRL=X'
    ],
    "CRIPTO": [
        'BTC-USD', 'ETH-USD', 'BNB-USD', 'SOL-USD', 'XRP-USD', 
        'DOGE-USD', 'ADA-USD', 'AVAX-USD', 'DOT-USD', 'MATIC-USD',
        'LINK-USD', 'SHIB-USD', 'LTC-USD', 'PEPE-USD'
    ],
    "ACCIONES": [
        # Tecnológicas (Magnificent 7 + otras)
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'NFLX', 'AMD', 'INTC',
        # Financieras y Consumo
        'JPM', 'V', 'MA', 'DIS', 'KO', 'PEP', 'MCD', 'WMT',
        # ETFs y Materias Primas (GLD = Oro, SLV = Plata, USO = Petróleo)
        'SPY', 'QQQ', 'GLD', 'SLV', 'USO'
    ]
}

async def escanear_mercado_real(categoria="GENERAL", estilo="SCALPING"):
    """
    Escanea el mercado buscando activos con movimiento interesante.
    """
    # 1. Seleccionar la lista
    if categoria == "GENERAL":
        # Mezcla un poco de todo para el escáner general
        lista = UNIVERSO["ACCIONES"][:10] + UNIVERSO["FOREX"][:5] + UNIVERSO["CRIPTO"][:5]
    else:
        lista = UNIVERSO.get(categoria, [])

    if not lista: return []

    print(f"📡 Escaneando {len(lista)} activos ({categoria}) en modo {estilo}...")

    # 2. Configurar Tiempos (Scalping vs Swing)
    if estilo == "SCALPING":
        intervalo = "15m"   # Velas de 15 minutos
        periodo = "5d"      # Últimos 5 días
        umbral = 0.003      # 0.3% de movimiento mínimo
    else:
        intervalo = "1d"    # Velas diarias
        periodo = "6mo"     # Últimos 6 meses
        umbral = 0.015      # 1.5% de movimiento mínimo

    # 3. Descarga Masiva (Optimizada)
    try:
        datos = yf.download(lista, period=periodo, interval=intervalo, progress=False)['Close']
    except Exception as e:
        print(f"⚠️ Error descarga masiva: {e}")
        return []
    
    candidatos = []
    
    # Si solo hay un activo, 'datos' es una Serie, lo convertimos a DataFrame
    if isinstance(datos, pd.Series): datos = datos.to_frame()

    # 4. Filtrar Volatilidad
    for ticker in lista:
        try:
            if ticker not in datos.columns: continue
            
            precios = datos[ticker].dropna()
            if len(precios) < 5: continue
            
            precio_actual = precios.iloc[-1]
            
            # Comparar con el pasado reciente
            if estilo == "SCALPING":
                referencia = precios.iloc[-4] # Hace 1 hora (4 velas de 15m)
            else:
                referencia = precios.iloc[-2] # Ayer
            
            cambio = (precio_actual - referencia) / referencia
            volatilidad = abs(cambio)
            
            # Si se mueve más que el umbral, es candidato
            if volatilidad > umbral:
                candidatos.append({"ticker": ticker, "vol": volatilidad})
        except: continue

    # Ordenar por los más volátiles y devolver el Top 5
    candidatos.sort(key=lambda x: x['vol'], reverse=True)
    return [x['ticker'] for x in candidatos[:5]]