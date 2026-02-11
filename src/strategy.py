import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

# --- CEREBRO MATEMÁTICO (Machine Learning) ---
class Predictor:
    def __init__(self):
        # Configuramos el modelo de Bosque Aleatorio
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.entrenado = False

    def entrenar(self, data):
        if data is None or len(data) < 5: return
        # Entrenamos usando las columnas técnicas que generamos en data_loader
        cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'Volatilidad'] if f in data.columns]
        try:
            # Target es la columna que nos dice si el precio subió al día siguiente
            self.model.fit(data[cols], data['Target'])
            self.entrenado = True
        except: self.entrenado = False

    def predecir_mañana(self, data):
        if not self.entrenado: return 0, 0.5
        try:
            cols = [f for f in ['RSI', 'MACD', 'Signal', 'SMA_50', 'Volatilidad'] if f in data.columns]
            # Retorna: Clase (Sube/Baja) y Probabilidad (0.0 a 1.0)
            return self.model.predict(data[cols].iloc[[-1]])[0], self.model.predict_proba(data[cols].iloc[[-1]])[0][1]
        except: return 0, 0.5

# --- EL GENERAL: TOMA DE DECISIONES ---
def examinar_activo(df, ticker, categoria="GENERAL"):
    """
    Recibe los datos crudos y decide la estrategia (Long/Short).
    """
    if df is None or df.empty: return None, 0.0

    # 1. Entrenar y Predecir
    prob = 0.5
    if len(df) > 15:
        brain = Predictor()
        brain.entrenar(df.iloc[:-1])
        _, prob = brain.predecir_mañana(df)
    
    row = df.iloc[-1]
    
    # Obtener ATR para Stop Loss dinámico
    atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else row['Close'] * 0.01

    # --- REGLAS DE ESTRATEGIA BIDIRECCIONAL ---
    
    # CASO 1: ALCISTA (LONG) 🚀
    if prob > 0.60:
        tipo = "LONG (COMPRA)"
        señal = "ALCISTA FUERTE"
        icono = "🟢"
        veredicto = "ABRIR LONG 🚀"
        sl = row['Close'] - (atr * 1.5) # SL Abajo
        tp = row['Close'] + (atr * 3.0) # TP Arriba

    # CASO 2: BAJISTA (SHORT) 🐻 (Solo Forex/Cripto)
    elif prob < 0.40 and categoria in ["FOREX", "CRIPTO"]:
        tipo = "SHORT (VENTA)"
        señal = "BAJISTA FUERTE"
        icono = "🔴"
        veredicto = "ABRIR SHORT 📉"
        sl = row['Close'] + (atr * 1.5) # SL Arriba
        tp = row['Close'] - (atr * 3.0) # TP Abajo
        prob = 1.0 - prob # Invertimos la probabilidad para mostrar fuerza (ej: 30% prob subida = 70% fuerza bajada)

    # CASO 3: NEUTRAL ✋
    else:
        tipo = "NEUTRAL"
        señal = "RANGO"
        icono = "⚪"
        veredicto = "ESPERAR ✋"
        sl = row['Close'] * 0.99
        tp = row['Close'] * 1.01

    # Formato de precios (Sin decimales para monedas grandes como COP o CLP)
    fmt = ",.4f" if row['Close'] < 50 else ",.2f"
    if "COP" in ticker or "CLP" in ticker or "JPY" in ticker: fmt = ",.0f"

    info = {
        "ticker": ticker,
        "precio": format(row['Close'], fmt),
        "sl": format(sl, fmt),
        "tp": format(tp, fmt),
        "rsi": f"{row['RSI']:.1f}",
        "señal": señal,
        "icono": icono,
        "veredicto": veredicto,
        "tipo_operacion": tipo
    }
    
    return info, prob
