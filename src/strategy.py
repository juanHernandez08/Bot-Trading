import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

class Predictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=150, random_state=42, min_samples_split=8)
        self.entrenado = False

    def entrenar(self, data):
        if data is None or len(data) < 50: return
        cols = [f for f in ['RSI', 'MACD', 'Signal', 'EMA_9', 'EMA_21', 'SMA_200', 'Volatilidad'] if f in data.columns]
        try:
            self.model.fit(data[cols], data['Target'])
            self.entrenado = True
        except: self.entrenado = False

    def predecir_mañana(self, data):
        if not self.entrenado: return 0, 0.5
        try:
            cols = [f for f in ['RSI', 'MACD', 'Signal', 'EMA_9', 'EMA_21', 'SMA_200', 'Volatilidad'] if f in data.columns]
            return self.model.predict(data[cols].iloc[[-1]])[0], self.model.predict_proba(data[cols].iloc[[-1]])[0][1]
        except: return 0, 0.5

def examinar_activo(df, ticker, estilo="SCALPING", categoria="GENERAL"):
    if df is None or df.empty: return None, 0.0

    # 1. CÁLCULO DE TODOS LOS INDICADORES
    # Para Scalping
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
    # Para Swing (Golden)
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    # --- CORRECCIÓN DEL ERROR ---
    # Antes: df.fillna(method='bfill', inplace=True)
    # Ahora (Compatible con Pandas nuevo):
    df = df.bfill()

    # 2. IA
    prob = 0.5
    if len(df) > 210:
        brain = Predictor()
        brain.entrenar(df.iloc[:-1])
        _, prob = brain.predecir_mañana(df)
    
    row = df.iloc[-1]
    precio = row['Close']
    rsi = row['RSI']
    
    # Estructura de mercado (Mínimos/Máximos recientes)
    min_reciente = df['Low'].iloc[-5:-1].min()
    max_reciente = df['High'].iloc[-5:-1].max()
    atr = df['ATR'].iloc[-1] if 'ATR' in df.columns else precio * 0.005

    # --- VARIABLES POR DEFECTO ---
    tipo = "NEUTRAL"
    señal = "RANGO"
    icono = "⚪"
    veredicto = "ESPERAR"
    motivo = "Sin señal clara"
    prob_mostrar = prob
    sl, tp = precio, precio

    # ==========================================================
    # ⚡ MODALIDAD 1: SCALPING (Rápido, EMA 9/21, Ratio 1.5)
    # ==========================================================
    if estilo == "SCALPING":
        ratio = 1.5
        ema_9 = row['EMA_9']
        ema_21 = row['EMA_21']

        # LONG SCALPING
        if prob > 0.55 and ema_9 > ema_21 and precio > ema_9 and rsi < 70:
            sl = min_reciente
            if (precio - sl) < (precio * 0.0005): sl = precio * 0.9995
            riesgo = precio - sl
            tp = precio + (riesgo * ratio)
            
            tipo = "LONG (COMPRA)"
            icono = "🟢"
            prob_mostrar = prob
            señal = "SCALPING"
            veredicto = "SCALPING LONG ⚡"
            motivo = f"Momentum (EMA 9>21) ({prob*100:.0f}%)"

        # SHORT SCALPING
        elif prob < 0.45 and ema_9 < ema_21 and precio < ema_9 and rsi > 30:
            sl = max_reciente
            if (sl - precio) < (precio * 0.0005): sl = precio * 1.0005
            riesgo = sl - precio
            tp = precio - (riesgo * ratio)
            
            tipo = "SHORT (VENTA)"
            icono = "🔴"
            prob_mostrar = 1.0 - prob
            señal = "SCALPING"
            veredicto = "SCALPING SHORT ⚡"
            motivo = f"Momentum (EMA 9<21) ({prob_mostrar*100:.0f}%)"

    # ==========================================================
    # 🏆 MODALIDAD 2: SWING (Oportunidad de Oro, SMA 200, Ratio 2.0)
    # ==========================================================
    elif estilo == "SWING":
        sma_200 = row['SMA_200']
        ema_50 = row['EMA_50']
        # SL y TP más amplios basados en ATR
        sl_dist = atr * 2.0
        tp_dist = atr * 4.0 

        # LONG GOLDEN
        if prob > 0.65 and precio > sma_200 and precio > ema_50 and rsi < 65:
            sl = precio - sl_dist
            tp = precio + tp_dist
            tipo = "LONG (COMPRA)"
            icono = "🟢"
            prob_mostrar = prob
            señal = "GOLDEN"
            veredicto = "OPORTUNIDAD DE ORO 🚀"
            motivo = f"Tendencia Mayor Alcista (SMA 200) ({prob*100:.0f}%)"

        # SHORT GOLDEN
        elif prob < 0.35 and precio < sma_200 and precio < ema_50 and rsi > 35:
            sl = precio + sl_dist
            tp = precio - tp_dist
            tipo = "SHORT (VENTA)"
            icono = "🔴"
            prob_mostrar = 1.0 - prob
            señal = "GOLDEN"
            veredicto = "OPORTUNIDAD DE ORO 📉"
            motivo = f"Tendencia Mayor Bajista (SMA 200) ({prob_mostrar*100:.0f}%)"

    if tipo == "SHORT (VENTA)" and categoria == "ACCIONES":
        veredicto = "NO COMPRAR (BAJISTA) ❌"
        motivo = "Acción bajista."

    # --- FORMATO ---
    etiqueta = "GEN"
    if categoria == "CRIPTO": etiqueta = "CRI"
    elif categoria == "FOREX": etiqueta = "FOR"
    elif categoria == "ACCIONES": etiqueta = "ACC"

    nombre_broker = ticker.replace("-USD", "USD").replace("=X", "")
    if "JPY" in ticker: fmt = ",.3f"
    elif any(x in ticker for x in ["COP", "CLP"]): fmt = ",.0f"
    elif precio < 0.001: fmt = ",.8f"
    elif precio < 1.0: fmt = ",.4f"
    else: fmt = ",.4f" if precio < 50 else ",.2f"

    info = {
        "ticker": nombre_broker,
        "mercado": etiqueta,
        "precio": format(precio, fmt),
        "sl": format(sl, fmt),
        "tp": format(tp, fmt),
        "rsi": f"{rsi:.1f}",
        "señal": señal,
        "icono": icono,
        "veredicto": veredicto,
        "tipo_operacion": tipo,
        "motivo": motivo
    }
    
    return info, prob
