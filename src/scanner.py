import pandas as pd
import yfinance as yf
import asyncio

# --- EL MEGA-UNIVERSO DE ACTIVOS ---
UNIVERSO = {
    "FOREX": [
        # Majors
        'EURUSD=X', 'GBPUSD=X', 'JPY=X', 'AUDUSD=X', 'NZDUSD=X', 'USDCAD=X', 'USDCHF=X',
        # Cruces y Exóticos
        'EURGBP=X', 'EURJPY=X', 'GBPJPY=X', 'AUDJPY=X', 'CHFJPY=X', 'EURAUD=X',
        # Latinos
        'COP=X', 'MXN=X', 'BRL=X', 'CLP=X', 'PEN=X'
    ],
    "CRIPTO": [
        # Top Market Cap
        'BTC-USD', 'ETH-USD', 'BNB-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD',
        'AVAX-USD', 'TRX-USD', 'DOT-USD', 'LINK-USD', 'MATIC-USD', 'SHIB-USD', 'LTC-USD',
        'UNI-USD', 'ATOM-USD', 'XLM-USD', 'NEAR-USD', 'ALGO-USD', 'APE-USD', 'SAND-USD'
    ],
    "ACCIONES": [
        # Tech Gigantes (Magnificent 7)
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META',
        # Populares y Volátiles
        'NFLX', 'AMD', 'INTC', 'PYPL', 'COIN', 'UBER', 'ABNB', 'SHOP', 'SQ', 'ROKU',
        # ETFs Inversos y Apalancados
        'SQQQ', 'TQQQ', 'SOXL', 'SOXS', 'LABU', 'LABD',
        # Latinos
        'NU', 'MELI', 'ECOPETROL.CN'
    ],
    "GENERAL": [
        'BTC-USD', 'ETH-USD', 'EURUSD=X', 'GBPUSD=X', 'AAPL', 'NVDA', 'TSLA', 'COP=X', 'XRP-USD'
    ]
}

async def escanear_mercado(categoria="GENERAL", estilo="SCALPING"):
    """
    Escanea listas grandes buscando volatilidad.
    """
    lista = UNIVERSO.get(categoria, UNIVERSO["GENERAL"])
    inter, per = ("15m", "5d") if estilo == "SCALPING" else ("1d", "6mo")
    
    try:
        # Descarga masiva (Optimizado)
        # yfinance descarga todo de una vez, es rápido aunque la lista sea larga
        datos = yf.download(lista, period=per, interval=inter, progress=False, auto_adjust=True)['Close']
        
        if isinstance(datos, pd.Series): datos = datos.to_frame()
        
        candidatos = []
        for ticker in lista:
            if ticker in datos.columns:
                precios = datos[ticker].dropna()
                
                if len(precios) > 5:
                    # Filtro de Volatilidad:
                    # Solo nos interesan activos que se hayan movido al menos un 0.2% recientemente
                    # Así evitamos que el bot te recomiende "monedas muertas"
                    volatilidad = abs((precios.iloc[-1] - precios.iloc[-4]) / precios.iloc[-4])
                    
                    if volatilidad > 0.002: 
                        candidatos.append(ticker)
                    
        # Retornamos hasta 10 candidatos para tener variedad
        return candidatos[:10]
        
    except Exception as e:
        print(f"Error scanner: {e}")
        return lista[:5]
