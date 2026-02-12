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
    # Calculamos el ATR (Volatilidad promedio)
    atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else row['Close'] * 0.005

    # --- LÓGICA DE SEÑALES ---
    tipo = "NEUTRAL"
    señal = "RANGO"
    icono = "⚪"
    veredicto = "ESPERAR"
    motivo = "Sin tendencia clara"
    prob_mostrar = prob

    # AJUSTE DE PRECISIÓN (SCALPING TIGHT)
    # Multiplicadores reducidos para que el TP y SL estén más cerca del precio
    factor_sl = 0.8  # Stop Loss ajustado (Antes 1.5)
    factor_tp = 1.6  # Take Profit rápido (Antes 3.0)

    if prob > 0.50:
        sl = row['Close'] - (atr * factor_sl)
        tp = row['Close'] + (atr * factor_tp)
        tipo = "LONG (COMPRA)"
        icono = "🟢"
        prob_mostrar = prob
        if prob > 0.60:
            señal = "FUERTE"
            veredicto = "ABRIR LONG 🚀"
            motivo = f"Impulso alcista detectado ({prob_mostrar*100:.0f}%)"
        else:
            señal = "MODERADA"
            veredicto = "POSIBLE REBOTE ↗️"
            motivo = f"Técnicos favorables ({prob_mostrar*100:.0f}%)"
    else:
        # En Short: SL arriba, TP abajo
        sl = row['Close'] + (atr * factor_sl)
        tp = row['Close'] - (atr * factor_tp)
        tipo = "SHORT (VENTA)"
        icono = "🔴"
        prob_mostrar = 1.0 - prob
        if prob < 0.40:
            señal = "FUERTE"
            veredicto = "ABRIR SHORT 📉"
            motivo = f"Caída inminente detectada ({prob_mostrar*100:.0f}%)"
        else:
            señal = "MODERADA"
            veredicto = "POSIBLE CORRECCIÓN ↘️"
            motivo = f"Debilidad técnica ({prob_mostrar*100:.0f}%)"

    if tipo == "SHORT (VENTA)" and categoria == "ACCIONES":
        veredicto = "NO COMPRAR (BAJISTA) ❌"
        motivo = "Acción en tendencia bajista. Esperar."

    # --- ETIQUETADO Y FORMATO ---
    etiqueta = "GEN"
    if categoria == "CRIPTO": etiqueta = "CRI"
    elif categoria == "FOREX": etiqueta = "FOR"
    elif categoria == "ACCIONES": etiqueta = "ACC"

    nombre_broker = ticker.replace("-USD", "USD").replace("=X", "")
    precio_actual = row['Close']
    
    # Lógica de decimales (SHIB, JPY, etc.)
    if "JPY" in ticker:
        fmt = ",.3f"
    elif any(x in ticker for x in ["COP", "CLP"]):
        fmt = ",.0f"
    elif precio_actual < 0.001: 
        fmt = ",.8f" # Para SHIB/PEPE
    elif precio_actual < 1.0: 
        fmt = ",.4f"
    else:
        fmt = ",.4f" if row['Close'] < 50 else ",.2f"

    info = {
        "ticker": nombre_broker,
        "mercado": etiqueta,
        "precio": format(precio_actual, fmt),
        "sl": format(sl, fmt),
        "tp": format(tp, fmt),
        "rsi": f"{row['RSI']:.1f}",
        "señal": señal,
        "icono": icono,
        "veredicto": veredicto,
        "tipo_operacion": tipo,
        "motivo": motivo
    }
    
    return info, prob
