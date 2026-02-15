import yfinance as yf
import pandas as pd
import pandas_ta as ta

# --- DICCIONARIO DE TRADUCCIÓN ---
ALIAS_CRIPTO = {
    "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD",
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

# --- FUNCIÓN QUE FALTABA (ESENCIAL PARA BRAIN.PY) ---
def normalizar_ticker(ticker):
    """
    Convierte 'SOL' en 'SOL-USD' para que Yahoo Finance lo entienda.
    Esta es la función que brain.py estaba buscando y no encontraba.
    """
    if not ticker: return None
    ticker = ticker.upper().strip()
    return ALIAS_CRIPTO.get(ticker, ticker)

async def descargar_datos(ticker, estilo="SCALPING"):
    # 1. Usamos la función normalizar
    ticker = normalizar_ticker(ticker)
    
    print(f"📥 Descargando: {ticker}")

    try:
        # 2. Configurar tiempos
        if estilo == "SCALPING":
            periodo = "5d"
            intervalo = "15m"
        else: # SWING
            periodo = "60d"
            intervalo = "1h"

        df = yf.download(ticker, period=periodo, interval=intervalo, progress=False)

        # 3. Validación y Rescate
        if df is None or df.empty or len(df) < 20:
            # Si falla y no tiene guion, probamos agregar -USD por si acaso
            if "-" not in ticker and "=" not in ticker:
                ticker_rescue = ticker + "-USD"
                print(f"⚠️ Reintentando con: {ticker_rescue}")
                df = yf.download(ticker_rescue, period=periodo, interval=intervalo, progress=False)
                if df is None or df.empty: return None, False
            else:
                return None, False

        # 4. Limpieza (Yahoo Fix)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df.dropna()
        
        # 5. Indicadores Técnicos (Usando pandas_ta)
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
        
        # ATR (Stop Loss)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)

        # Target IA
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        
        df = df.dropna()
        return df, False

    except Exception as e:
        print(f"❌ Error en data_loader: {e}")
        return None, False
