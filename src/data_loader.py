import yfinance as yf
import pandas as pd

def descargar_datos(ticker, start_date):
    """
    Descarga datos históricos de Yahoo Finance.
    """
    print(f"⬇️ Descargando datos para {ticker}...")
    try:
        df = yf.download(ticker, start=start_date, progress=False)
        if df.empty:
            print(f"⚠️ No se encontraron datos para {ticker}")
            return None
        return df
    except Exception as e:
        print(f"❌ Error descargando {ticker}: {e}")
        return None
