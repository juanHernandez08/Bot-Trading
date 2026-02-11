import yfinance as yf
import pandas as pd
import numpy as np

# --- DICCIONARIO GLOBAL ---
SINONIMOS = {
    # EMPRESAS
    "ROCKSTAR": "TTWO", "GTA": "TTWO", "TAKE TWO": "TTWO", "TTWO": "TTWO",
    "TESLA": "TSLA", "NVIDIA": "NVDA", "APPLE": "AAPL", "GOOGLE": "GOOGL", "META": "META",
    "AMAZON": "AMZN", "MICROSOFT": "MSFT", "NETFLIX": "NFLX", "MERCADO LIBRE": "MELI", "NU BANK": "NU",

    # ESTRATEGIAS
    "CHINA": "YANG", "CONTRA CHINA": "YANG",
    "EEUU": "SQQQ", "CONTRA EEUU": "SQQQ", "USA": "SQQQ",
    "EUROPA": "EPV", "CONTRA EUROPA": "EPV", "ALEMANIA": "EPV",
    "JAPON": "EWV", "CONTRA JAPON": "EWV",

    # LATINOAMÉRICA & FOREX
    "COLOMBIA": "GXG", "CONTRA COLOMBIA": "COP=X",
    "MEXICO": "EWW", "CONTRA MEXICO": "MXN=X",
    "CHILE": "ECH", "CONTRA CHILE": "USDCLP=X",
    "PERU": "EPU", "CONTRA PERU": "USDPEN=X",
    "BRASIL": "EWZ", "CONTRA BRASIL": "BZQ",
    "ARGENTINA": "ARGT", "CONTRA ARGENTINA": "USDARS=X", 
    
    # REFUGIOS
    "VENEZUELA": "BTC-USD", "CONTRA VENEZUELA": "BTC-USD",
    "ECUADOR": "GLD", "CONTRA ECUADOR": "GLD",
    "PANAMA": "GLD", "CONTRA PANAMA": "GLD",

    # ACTIVOS
    "DOLAR": "COP=X", "USD": "COP=X", "PESO": "COP=X",
    "EURO": "EURUSD=X",
    "BITCOIN": "BTC-USD", "BTC": "BTC-USD", "ETH": "ETH-USD",
    "ORO": "GLD", "PETROLEO": "USO"
}

def normalizar_ticker(ticker):
    if not ticker: return None
    t = ticker.upper().strip()
    for clave, valor in SINONIMOS.items():
        if clave in t: return valor
    return t.replace(" ", "")

def preparar_datos(df):
    """Calcula indicadores matemáticos"""
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    for col in ['Close', 'High', 'Low', 'Open']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    df.ffill(inplace=True)

    try:
        # Indicadores Técnicos
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        df['EMA_12'] = df['Close'].ewm(span=12).mean()
        df['EMA_26'] = df['Close'].ewm(span=26).mean()
        df['MACD'] = df['EMA_12'] - df['EMA_26']
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        
        ranges = pd.concat([df['High']-df['Low'], (df['High']-df['Close'].shift()).abs(), (df['Low']-df['Close'].shift()).abs()], axis=1)
        df['ATR'] = ranges.max(axis=1).rolling(14).mean().bfill()
        
        # Objetivo (Target) para la IA
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        df['Volatilidad'] = df['Close'].rolling(20).std()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        
        return df.dropna(subset=['RSI', 'Close'])
    except: return pd.DataFrame()

async def descargar_datos(ticker, estilo="SCALPING"):
    """Solo descarga datos, no analiza."""
    inv, per = ("1d", "1y") if estilo == "SWING" else ("15m", "5d")
    backup = False
    
    try:
        df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 5:
            inv, per = "1d", "1y"
            df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
            backup = True
            
        if df is None or df.empty or len(df) < 5: return None, False
        
        clean = preparar_datos(df)
        return clean, backup
    except: return None, False
