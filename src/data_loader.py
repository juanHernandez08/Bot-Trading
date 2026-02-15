import yfinance as yf
import pandas as pd
import pandas_ta as ta

# --- DICCIONARIO DE TRADUCCIÓN ---
# Esto obliga al bot a entender tus criptos favoritas
ALIAS_CRIPTO = {
    "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD",   # <--- AQUÍ ESTÁ EL ARREGLO
    "SOLANA": "SOL-USD",
    "XRP": "XRP-USD",
    "RIPPLE": "XRP-USD",
    "ADA": "ADA-USD",
    "CARDANO": "ADA-USD",
    "DOT": "DOT-USD",
    "POLKADOT": "DOT-USD",
    "MATIC": "MATIC-USD",
    "DOGE": "DOGE-USD",
    "SHIB": "SHIB-USD",
    "LTC": "LTC-USD",
    "LINK": "LINK-USD",
    "BNB": "BNB-USD",
    # Forex Comunes
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "YEN": "USDJPY=X",
    "ORO": "GC=F",
    "XAU": "GC=F",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC"
}

async def descargar_datos(ticker, estilo="SCALPING"):
    # 1. Limpieza y Traducción
    ticker = ticker.upper().strip()
    
    # Si está en el diccionario, usamos el nombre correcto
    if ticker in ALIAS_CRIPTO:
        ticker = ALIAS_CRIPTO[ticker]
    
    # Si parece cripto y no tiene -USD, probamos agregarlo
    if estilo == "SCALPING" and "-" not in ticker and "=" not in ticker and len(ticker) <= 4:
        # Intento inteligente: si falla luego, es culpa de Yahoo, pero esto ayuda
        pass 

    print(f"📥 Descargando: {ticker}") # Log para ver qué busca

    try:
        # 2. Definir temporalidad según estilo
        # Scalping = M15 (Últimos 5 días para tener mucha data)
        # Swing = H1 (Últimos 60 días)
        if estilo == "SCALPING":
            periodo = "5d"
            intervalo = "15m"
        else: # SWING
            periodo = "60d"
            intervalo = "1h"

        df = yf.download(ticker, period=periodo, interval=intervalo, progress=False)

        if df is None or df.empty or len(df) < 20:
            # INTENTO DE RESCATE: Si falló, probamos agregarle "-USD" si no lo tenía
            if "-" not in ticker and "=" not in ticker:
                ticker_rescue = ticker + "-USD"
                print(f"⚠️ Reintentando con: {ticker_rescue}")
                df = yf.download(ticker_rescue, period=periodo, interval=intervalo, progress=False)
                if df is None or df.empty: return None, False
            else:
                return None, False

        # 3. Limpieza de datos (Multi-Index fix para Yahoo nuevo)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df.dropna()
        
        # 4. Cálculo de Indicadores Técnicos
        # RSI
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        # MACD
        macd = ta.macd(df['Close'])
        df['MACD'] = macd['MACD_12_26_9']
        df['Signal'] = macd['MACDs_12_26_9']
        
        # Bandas de Bollinger (Volatilidad)
        bb = ta.bbands(df['Close'], length=20)
        df['Upper'] = bb['BBU_20_2.0']
        df['Lower'] = bb['BBL_20_2.0']
        df['Volatilidad'] = (df['Upper'] - df['Lower']) / df['Close']
        
        # ATR (Average True Range) para Stop Loss profesionales
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

        # Target (Para la IA)
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        
        df = df.dropna()
        return df, False

    except Exception as e:
        print(f"❌ Error en data_loader: {e}")
        return None, False
# --- FUNCIÓN FALTANTE (AGREGAR AL FINAL) ---
def normalizar_ticker(ticker):
    """
    Función de compatibilidad para que brain.py no falle.
    Usa el mismo diccionario de traducción.
    """
    ticker = ticker.upper().strip()
    return ALIAS_CRIPTO.get(ticker, ticker)
