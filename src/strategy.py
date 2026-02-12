import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

class Predictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42, min_samples_split=5)
        self.entrenado = False

    def entrenar(self, data):
        if data is None or len(data) < 25: return
        cols = [f for f in ['RSI', 'MACD', 'Signal', 'EMA_9', 'EMA_21', 'Volatilidad'] if f in data.columns]
        try:
            self.model.fit(data[cols], data['Target'])
            self.entrenado = True
        except: self.entrenado = False

    def predecir_mañana(self, data):
        if not self.entrenado: return 0, 0.5
        try:
            cols = [f for f in ['RSI', 'MACD', 'Signal', 'EMA_9', 'EMA_21', 'Volatilidad'] if f in data.columns]
            return self.model.predict(data[cols].iloc[[-1]])[0], self.model.predict_proba(data[cols].iloc[[-1]])[0][1]
        except: return 0, 0.5

def examinar_activo(df, ticker, categoria="GENERAL"):
    if df is None or df.empty: return None, 0.0

    # 1. CÁLCULO DE INDICADORES RÁPIDOS (SCALPING)
    # EMA 9: La "liebre" (Rápida)
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    # EMA 21: La "base" (Tendencia Corta)
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()

    # 2. Predecir con IA
    prob = 0.5
    if len(df) > 30:
        brain = Predictor()
        brain.entrenar(df.iloc[:-1])
        _, prob = brain.predecir_mañana(df)
    
    row = df.iloc[-1]
    precio_actual = row['Close']
    ema_9 = row['EMA_9']
    ema_21 = row['EMA_21']
    rsi = row['RSI']
    
    # Estructura de Mercado para SL (Últimas 3 velas)
    minimo_reciente = df['Low'].iloc[-4:-1].min()
    maximo_reciente = df['High'].iloc[-4:-1].max()

    # --- LÓGICA SCALPING (MOMENTUM) ---
    tipo = "NEUTRAL"
    señal = "RANGO"
    icono = "⚪"
    veredicto = "ESPERAR"
    motivo = "Sin momentum claro"
    prob_mostrar = prob

    ratio = 1.5 

    # === CASO LONG (COMPRA RÁPIDA) ===
    # Reglas:
    # 1. EMA 9 > EMA 21 (Cruce Alcista Confirmado)
    # 2. Precio > EMA 9 (Momentum fuerte, el precio "corre")
    # 3. RSI < 70 (No comprar en techo)
    # 4. IA > 55%
    if prob > 0.55 and ema_9 > ema_21 and precio_actual > ema_9 and rsi < 70:
        
        sl = minimo_reciente
        # Anti-ruido
        if (precio_actual - sl) < (precio_actual * 0.001): sl = precio_actual * 0.999
            
        riesgo = precio_actual - sl
        tp = precio_actual + (riesgo * ratio)
        
        tipo = "LONG (COMPRA)"
        icono = "🟢"
        prob_mostrar = prob
        señal = "MOMENTUM"
        veredicto = "SCALPING LONG ⚡"
        motivo = f"Fuerza Alcista (EMA 9>21) ({prob*100:.0f}%)"

    # === CASO SHORT (VENTA RÁPIDA) ===
    # Reglas:
    # 1. EMA 9 < EMA 21 (Cruce Bajista Confirmado)
    # 2. Precio < EMA 9 (Momentum fuerte hacia abajo)
    # 3. RSI > 30 (No vender en suelo)
    # 4. IA < 45%
    elif prob < 0.45 and ema_9 < ema_21 and precio_actual < ema_9 and rsi > 30:
        
        sl = maximo_reciente
        # Anti-ruido
        if (sl - precio_actual) < (precio_actual * 0.001): sl = precio_actual * 1.001
            
        riesgo = sl - precio_actual
        tp = precio_actual - (riesgo * ratio)
        
        tipo = "SHORT (VENTA)"
        icono = "🔴"
        prob_mostrar = 1.0 - prob
        señal = "MOMENTUM"
        veredicto = "SCALPING SHORT ⚡"
        motivo = f"Fuerza Bajista (EMA 9<21) ({prob_mostrar*100:.0f}%)"

    if tipo == "SHORT (VENTA)" and categoria == "ACCIONES":
        veredicto = "NO COMPRAR (BAJISTA) ❌"
        motivo = "Acción en tendencia bajista."

    # --- FORMATO ---
    etiqueta = "GEN"
    if categoria == "CRIPTO": etiqueta = "CRI"
    elif categoria == "FOREX": etiqueta = "FOR"
    elif categoria == "ACCIONES": etiqueta = "ACC"

    nombre_broker = ticker.replace("-USD", "USD").replace("=X", "")
    
    if "JPY" in ticker: fmt = ",.3f"
    elif any(x in ticker for x in ["COP", "CLP"]): fmt = ",.0f"
    elif precio_actual < 0.001: fmt = ",.8f"
    elif precio_actual < 1.0: fmt = ",.4f"
    else: fmt = ",.4f" if precio_actual < 50 else ",.2f"

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
