import pandas as pd
import numpy as np

def preparar_datos(df):
    """
    Calcula indicadores técnicos y niveles de riesgo sin borrar la última vela.
    """
    df = df.copy()
    
    # --- 1. CORRECCIÓN DE COLUMNAS (Aplanar MultiIndex) ---
    # Yahoo a veces devuelve ('Close', 'BTC-USD'). Lo convertimos a 'Close'.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Asegurarnos de que tenemos datos numéricos limpios
    for col in ['Close', 'High', 'Low', 'Open']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
    # Si hay vacíos en los precios base, llenar con el anterior
    df.ffill(inplace=True)

    # --- 2. INDICADORES ---
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['EMA_12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA_26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA_12'] - df['EMA_26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # Medias Móviles Flexibles
    # Si tenemos pocos datos, la SMA_200 rompería todo.
    if len(df) > 200:
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
    else:
        df['SMA_200'] = df['Close'].rolling(window=len(df)//2).mean() # Fallback
        
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['Volatilidad'] = df['Close'].rolling(window=20).std()

    # --- 3. ATR y STOP LOSS ---
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()

    # Rellenar ATR inicial con media simple para no perder datos
    df['ATR'] = df['ATR'].bfill()

    # Niveles (SL / TP)
    atr_actual = df['ATR'].iloc[-1] 
    if pd.isna(atr_actual): atr_actual = df['Close'].iloc[-1] * 0.01 # Fallback 1%

    precio_actual = df['Close'].iloc[-1]
    df['Stop_Loss'] = precio_actual - (atr_actual * 1.5)
    df['Take_Profit'] = precio_actual + (atr_actual * 3.0)

    # --- 4. TARGET (OBJETIVO) ---
    # El Target es para entrenar (Histórico). 
    # La última fila tendrá Target = NaN, pero la necesitamos para predecir.
    df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
    
    # IMPORTANTE: No hacemos dropna() global.
    # Solo limpiamos filas que tengan NaN en los INDICADORES clave para entrenar
    cols_indicadores = ['RSI', 'MACD', 'SMA_50']
    df_clean = df.dropna(subset=cols_indicadores).copy()
    
    return df_clean