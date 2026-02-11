import yfinance as yf
import pandas as pd
import numpy as np
import asyncio
from sklearn.ensemble import RandomForestClassifier

# --- DICCIONARIO GLOBAL DE INTELIGENCIA ---
SINONIMOS = {
    # EMPRESAS TECH & GAMING
    "ROCKSTAR": "TTWO", "GTA": "TTWO", "TAKE TWO": "TTWO", "TTWO": "TTWO",
    "TESLA": "TSLA", "NVIDIA": "NVDA", "APPLE": "AAPL", "GOOGLE": "GOOGL", "META": "META",
    "AMAZON": "AMZN", "MICROSOFT": "MSFT", "NETFLIX": "NFLX", "MERCADO LIBRE": "MELI", "NU BANK": "NU",

    # ESTRATEGIAS CONTRA POTENCIAS (ETFs Inversos)
    "CHINA": "YANG", "CONTRA CHINA": "YANG",
    "EEUU": "SQQQ", "CONTRA EEUU": "SQQQ", "USA": "SQQQ",
    "EUROPA": "EPV", "CONTRA EUROPA": "EPV", "ALEMANIA": "EPV",
    "JAPON": "EWV", "CONTRA JAPON": "EWV",

    # LATINOAMÉRICA & DIVISAS (Forex / Defensa)
    "COLOMBIA": "GXG", "CONTRA COLOMBIA": "COP=X",
    "MEXICO": "EWW", "CONTRA MEXICO": "MXN=X",
    "CHILE": "ECH", "CONTRA CHILE": "USDCLP=X",
    "PERU": "EPU", "CONTRA PERU": "USDPEN=X",
    "BRASIL": "EWZ", "CONTRA BRASIL": "BZQ",
    "ARGENTINA": "ARGT", "CONTRA ARGENTINA": "USDARS=X", 
    
    # REFUGIOS (Economías complejas)
    "VENEZUELA": "BTC-USD", "CONTRA VENEZUELA": "BTC-USD",
    "ECUADOR": "GLD", "CONTRA ECUADOR": "GLD",
    "PANAMA": "GLD", "CONTRA PANAMA": "GLD",

    # COMMODITIES Y CRIPTO
    "DOLAR": "COP=X", "USD": "COP=X", "PESO": "COP=X",
    "EURO": "EURUSD=X",
    "BITCOIN": "BTC-USD", "BTC": "BTC-USD", "ETH": "ETH-USD",
    "ORO": "GLD", "PETROLEO": "USO"
}

def normalizar_ticker(ticker):
    """Buscador inteligente de tickers"""
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
        
        # Corrección ATR si falla
        atr = df['ATR'].iloc[-1] 
        if pd.isna(atr): atr = df['Close'].iloc[-1] * 0.01
        
        df['Stop_Loss'] = df['Close'] - (atr * 1.5)
        df['Take_Profit'] = df['Close'] + (atr * 3.0)
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        df['Volatilidad'] = df['Close'].rolling(20).std()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        
        return df.dropna(subset=['RSI', 'Close'])
    except: return pd.DataFrame()

async def descargar_datos(ticker, estilo="SCALPING"):
    """Descarga datos de Yahoo Finance con modo rescate"""
    inv, per = ("1d", "1y") if estilo == "SWING" else ("15m", "5d")
    backup = False
    
    try:
        df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
        # Modo Rescate: Si falla 15m, intenta Diario
        if df is None or df.empty or len(df) < 5:
            inv, per = "1d", "1y"
            df = yf.download(ticker, period=per, interval=inv, progress=False, auto_adjust=True)
            backup = True
            
        if df is None or df.empty or len(df) < 5: return None, False
        
        clean = preparar_datos(df)
        return clean, backup
    except: return None, False

# --- CEREBRO MATEMÁTICO (CLASE PREDICTOR) ---
class Predictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.entrenado = False

    def entrenar(self, data):
        if data is None or len(data) < 5: return
        cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'Volatilidad'] if f in data.columns]
        try:
            self.model.fit(data[cols], data['Target'])
            self.entrenado = True
        except: self.entrenado = False

    def predecir_mañana(self, data):
        if not self.entrenado: return 0, 0.5
        try:
            cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'Volatilidad'] if f in data.columns]
            return self.model.predict(data[cols].iloc[[-1]])[0], self.model.predict_proba(data[cols].iloc[[-1]])[0][1]
        except: return 0, 0.5

# --- MOTOR DE ANÁLISIS BIDIRECCIONAL (LONG & SHORT) ---
async def motor_analisis(ticker, estilo="SCALPING", categoria="GENERAL"):
    """
    Analiza y decide si entrar en LONG (Compra) o SHORT (Venta).
    """
    # 1. Obtener datos limpios
    df, backup_mode = await descargar_datos(ticker, estilo)
    if df is None or df.empty: return None

    # 2. Entrenar y Predecir
    prob = 0.5
    if len(df) > 15:
        brain = Predictor()
        brain.entrenar(df.iloc[:-1])
        _, prob = brain.predecir_mañana(df)
    
    row = df.iloc[-1]
    
    # Obtener ATR para Stop Loss
    atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else row['Close'] * 0.01

    # --- LÓGICA DE SEÑALES ---
    
    # CASO 1: ALCISTA (LONG) 🚀
    if prob > 0.60:
        tipo = "LONG (COMPRA)"
        señal = "ALCISTA FUERTE"
        icono = "🟢"
        veredicto = "ABRIR LONG 🚀"
        sl = row['Close'] - (atr * 1.5) # SL Abajo
        tp = row['Close'] + (atr * 3.0) # TP Arriba

    # CASO 2: BAJISTA (SHORT) 🐻 (Solo Forex/Cripto/Indices)
    elif prob < 0.40 and categoria in ["FOREX", "CRIPTO"]:
        tipo = "SHORT (VENTA)"
        señal = "BAJISTA FUERTE"
        icono = "🔴"
        veredicto = "ABRIR SHORT 📉"
        sl = row['Close'] + (atr * 1.5) # SL Arriba (Si sube pierdes)
        tp = row['Close'] - (atr * 3.0) # TP Abajo (Si baja ganas)
        prob = 1.0 - prob # Invertimos la probabilidad para mostrar la fuerza de la caída

    # CASO 3: NEUTRAL ✋
    else:
        tipo = "NEUTRAL"
        señal = "RANGO / INDECISIÓN"
        icono = "⚪"
        veredicto = "ESPERAR ✋"
        sl = row['Close'] * 0.99
        tp = row['Close'] * 1.01

    # Formato decimales
    fmt = ",.4f" if row['Close'] < 50 else ",.2f"
    if "COP" in ticker or "CLP" in ticker or "JPY" in ticker: fmt = ",.0f"

    # Estructura final
    info = {
        "ticker": ticker,
        "precio": format(row['Close'], fmt),
        "sl": format(sl, fmt),
        "tp": format(tp, fmt),
        "rsi": f"{row['RSI']:.1f}",
        "señal": señal,
        "icono": icono,
        "veredicto": veredicto,
        "tipo_operacion": tipo,
        "backup": backup_mode
    }
    
    return info, prob, row['Close'], df
