import yfinance as yf
import pandas as pd
import numpy as np

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

def normalizar_ticker(ticker):
    if not ticker: return None
    ticker = ticker.upper().strip()
    return ALIAS_CRIPTO.get(ticker, ticker)

async def descargar_datos(ticker, estilo="SCALPING"):
    ticker = normalizar_ticker(ticker)
    print(f"📥 Descargando: {ticker}")

    try:
        if estilo == "SCALPING":
            periodo = "5d"
            intervalo = "15m"
        else: # SWING
            periodo = "60d"
            intervalo = "1h"

        df = yf.download(ticker, period=periodo, interval=intervalo, progress=False)

        if df is None or df.empty or len(df) < 20:
            if "-" not in ticker and "=" not in ticker:
                ticker_rescue = ticker + "-USD"
                print(f"⚠️ Reintentando con: {ticker_rescue}")
                df = yf.download(ticker_rescue, period=periodo, interval=intervalo, progress=False)
                if df is None or df.empty: return None, False
            else:
                return None, False

        # Limpieza MultiIndex Yahoo
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df.dropna()

        # ==========================================================
        # 🧮 CÁLCULO NATIVO DE INDICADORES (A PRUEBA DE FALLOS)
        # ==========================================================
        
        # 1. RSI
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # 2. MACD
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

        # 3. Bandas de Bollinger & Volatilidad
        sma20 = df['Close'].rolling(window=20).mean()
        std20 = df['Close'].rolling(window=20).std()
        df['Upper'] = sma20 + (std20 * 2)
        df['Lower'] = sma20 - (std20 * 2)
        df['Volatilidad'] = (df['Upper'] - df['Lower']) / df['Close']

        # 4. ATR (Average True Range para el Stop Loss)
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['ATR'] = true_range.rolling(14).mean()

        # 5. Target IA (Shift -1)
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)

        # Llenar datos faltantes sin eliminar la vela actual (en vivo)
        df = df.bfill().ffill()

        return df, False

    except Exception as e:
        print(f"❌ Error en data_loader: {e}")
        return None, False
