class PortfolioManager:
    def __init__(self, presupuesto_cop):
        self.presupuesto_cop = presupuesto_cop
        self.trm = 4050  # TRM Aproximada (Se puede automatizar luego)
        self.presupuesto_usd = self.presupuesto_cop / self.trm

    def evaluar_compra(self, ticker, precio_actual, probabilidad):
        """
        Decide si alcanza el dinero y si vale la pena el riesgo.
        """
        # Filtro 1: Presupuesto
        if precio_actual > self.presupuesto_usd:
            return False, f"❌ {ticker} (${precio_actual:.2f}) excede tu presupuesto (${self.presupuesto_usd:.2f})."

        # Filtro 2: Estrategia según precio
        recomendacion = ""
        aprobado = False

        if self.presupuesto_usd < 125: # Presupuesto Bajo
            if precio_actual < 50 and probabilidad > 0.60:
                aprobado = True
                recomendacion = "✅ Oportunidad 'Low Cost' detectada."
            elif precio_actual >= 50:
                return False, f"⚠️ {ticker} consume todo tu capital bajo."
        
        elif self.presupuesto_usd >= 125: # Presupuesto Medio/Alto
            if probabilidad > 0.55:
                aprobado = True
                recomendacion = "✅ Oportunidad sólida detectada."

        if aprobado:
            mensaje = (f"{recomendacion}\n"
                       f"📊 Activo: {ticker}\n"
                       f"💰 Precio: ${precio_actual:.2f}\n"
                       f"📈 Probabilidad de subida: {probabilidad*100:.1f}%")
            return True, mensaje
        
        return False, "Probabilidad baja o riesgo alto."