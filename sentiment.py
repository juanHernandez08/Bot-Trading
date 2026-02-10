from gnews import GNews
from textblob import TextBlob
import time

def analizar_sentimiento(ticker):
    """
    Busca noticias en Google News sobre el Ticker y calcula el sentimiento.
    Retorna entre -1 (Negativo) y 1 (Positivo).
    """
    print(f"📰 Consultando Google News para {ticker}...")
    
    try:
        # Configuramos Google News (en inglés para mejor análisis de TextBlob)
        google_news = GNews(language='en', country='US', period='1d', max_results=5)
        
        # Buscamos noticias del ticker (ej. "Nubank stock", "Apple stock")
        # Añadimos 'stock' para evitar noticias de productos (ej. "Nuevo iPhone")
        query = f"{ticker} stock"
        noticias = google_news.get_news(query)
        
        if not noticias:
            print(f"   ⚠️ No se encontraron noticias recientes para {ticker}.")
            return 0.0

        suma_polaridad = 0
        contador = 0

        print(f"   found {len(noticias)} articles. Analizando...")

        for articulo in noticias:
            # GNews garantiza que siempre hay un 'title'
            titulo = articulo.get('title', '')
            
            # Limpieza básica: A veces el título trae el nombre del diario al final " - Reuters"
            if "-" in titulo:
                titulo = titulo.split("-")[:-1] # Quitamos la fuente
                titulo = "-".join(titulo)
            
            # Análisis de sentimiento
            analysis = TextBlob(titulo)
            polaridad = analysis.sentiment.polarity
            
            # Solo contamos si el sentimiento no es neutro (para evitar ruido)
            if polaridad != 0:
                suma_polaridad += polaridad
                contador += 1
                # Descomenta esta línea si quieres ver qué está leyendo
                # print(f"     🗣️ {titulo[:30]}... -> {polaridad:.2f}")

        if contador == 0:
            return 0.0

        promedio = suma_polaridad / contador
        return promedio

    except Exception as e:
        print(f"   ❌ Error en módulo de noticias: {e}")
        return 0.0