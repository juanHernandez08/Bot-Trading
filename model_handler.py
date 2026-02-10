import pandas as pd
from sklearn.ensemble import RandomForestClassifier

class Predictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.entrenado = False

    def entrenar(self, data):
        """
        Entrena el modelo usando los datos históricos.
        """
        # --- BLINDAJE ANTI-CRASH ---
        if data is None or len(data) < 2:
            print("⚠️ Datos insuficientes para entrenar modelo.")
            self.entrenado = False
            return
        # ---------------------------

        # Usamos RSI, MACD, etc. para predecir si el precio sube (Target)
        features = ['RSI', 'MACD', 'Signal', 'SMA_50', 'SMA_200', 'Volatilidad']
        
        # Asegurarnos de que las columnas existen
        features_reales = [f for f in features if f in data.columns]
        
        if not features_reales:
            print("⚠️ No se encontraron indicadores técnicos.")
            self.entrenado = False
            return

        X = data[features_reales]
        y = data['Target']
        
        try:
            self.model.fit(X, y)
            self.entrenado = True
        except Exception as e:
            print(f"⚠️ Error interno entrenando: {e}")
            self.entrenado = False

    def predecir_mañana(self, data):
        """
        Devuelve (Predicción, Probabilidad)
        """
        # Si no se pudo entrenar (por falta de datos), devolvemos Neutral (50%)
        if not self.entrenado:
            return 0, 0.5

        try:
            features = ['RSI', 'MACD', 'Signal', 'SMA_50', 'SMA_200', 'Volatilidad']
            features_reales = [f for f in features if f in data.columns]
            
            ultimo_dato = data[features_reales].iloc[[-1]]
            
            prediccion = self.model.predict(ultimo_dato)[0]
            probabilidad = self.model.predict_proba(ultimo_dato)[0][1]
            
            return prediccion, probabilidad
        except:
            return 0, 0.5