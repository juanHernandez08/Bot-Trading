import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

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

def examinar_activo(df, ticker, categoria="GENERAL"):
    if df is None or df.empty: return None, 0.0

    # 1. Predecir
    prob = 0.5
    if len(df) > 15:
        brain = Predictor()
        brain.entrenar(df.iloc[:-1])
        _, prob = brain.predecir_mañana(df)
    
    row = df.iloc[-1]
    atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else row['Close'] * 0.01

    # --- LÓGICA CORREGIDA (Sin invertir probabilidades) ---
    
    tipo = "NEUTRAL"
    señal = "RANGO"
    icono = "⚪"
    veredicto = "ESPERAR"
    motivo = "Sin tendencia clara"

    # CASO 1: ALCISTA (LONG) - Probabilidad Alta (> 0.50)
    if prob > 0.50:
        sl = row['Close'] - (atr * 1.5) # SL Abajo
        tp = row['Close'] + (atr * 3.0) # TP Arriba
        tipo = "LONG (COMPRA)"
        icono = "🟢"
        
        if prob > 0.60:
            señal = "FUERTE"
            veredicto = "ABRIR LONG 🚀"
            motivo = f"IA detecta impulso alcista ({prob*100:.0f}%)"
        else:
            señal = "MODERADA"
            veredicto = "POSIBLE REBOTE ↗️"
            motivo = f"Probabilidad técnica favorable ({prob*100:.0f}%)"

    # CASO 2: BAJISTA (SHORT) - Probabilidad Baja (< 0.50)
    else:
        # En Short, el SL va ARRIBA y el TP va ABAJO
        sl = row['Close'] + (atr * 1.5) 
        tp = row['Close'] - (atr * 3.0)
        tipo = "SHORT (VENTA)"
        icono = "🔴"
        
        if prob < 0.40:
            señal = "FUERTE"
            veredicto = "ABRIR SHORT 📉"
            motivo = f"IA detecta caída inminente ({prob*100:.0f}%)"
        else:
            señal = "MODERADA"
            veredicto = "POSIBLE CORRECCIÓN ↘️"
            motivo = f"Debilidad técnica detectada ({prob*100:.0f}%)"

    # Filtro de categoría: Si es Acciones, evitamos recomendar Short directo
    if tipo == "SHORT (VENTA)" and categoria == "ACCIONES":
        veredicto = "NO COMPRAR (BAJISTA) ❌"
        motivo = "Acción en tendencia bajista. Esperar."

    fmt = ",.4f" if row['Close'] < 50 else ",.2f"
   if "JPY=X" in ticker:
        fmt = ",.3f" 
    elif "COP" in ticker or "CLP" in ticker:
        fmt = ",.3f"
    else:
        fmt = ",.3f" if row['Close'] < 50 else ",.3f"

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
        "motivo": motivo # <--- Nueva variable explicativa
    }
    
    return info, prob

