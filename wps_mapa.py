from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import psycopg2
import numpy as np

app = FastAPI(title="API de Temperatura MODIS")

def get_conn():
    return psycopg2.connect(
        host="localhost",
        port="5433",
        user="usuario", # cambiar a tu user
        password="xxxxx",
        database="nombre_bd" # cambiar a tu BD
    )

def convertir_temperatura(fp_value):
    if fp_value is None:
        return None
    temp_kelvin = fp_value * 0.02 + 273.15
    return temp_kelvin - 273.15

def interpolacion_idw(lat, lon, datos, potencia=2):
    distancias = []
    temps_t21 = []
    temps_t31 = []
    for d in datos:
        lat_ref, lon_ref, fp_t31, fp_t21 = d
        dist = np.sqrt((lat - lat_ref)**2 + (lon - lon_ref)**2)
        distancias.append(dist)
        temps_t21.append(convertir_temperatura(fp_t21))
        temps_t31.append(convertir_temperatura(fp_t31))
    datos_validos = [(d, t21, t31) for d, t21, t31 in zip(distancias, temps_t21, temps_t31)
                     if t21 is not None and t31 is not None and d > 0]
    if not datos_validos:
        return None, 0
    distancias, temps_t21, temps_t31 = zip(*datos_validos)
    distancias = np.array(distancias)
    temps_t21 = np.array(temps_t21)
    temps_t31 = np.array(temps_t31)
    pesos = 1.0 / (distancias ** potencia)
    pesos_norm = pesos / np.sum(pesos)
    temp_t21_interp = np.sum(pesos_norm * temps_t21)
    temp_t31_interp = np.sum(pesos_norm * temps_t31)
    dist_promedio = np.average(distancias, weights=pesos_norm)
    confianza = max(0, 1 - (dist_promedio / 100000))
    temp_min = round(min(temp_t21_interp, temp_t31_interp), 2)
    temp_max = round(max(temp_t21_interp, temp_t31_interp), 2)
    temp_promedio = round((temp_min + temp_max) / 2, 2)
    return {
        "min": temp_min,
        "max": temp_max,
        "promedio": temp_promedio
    }, round(confianza, 3)

@app.get("/temperatura")
def estimar_temperatura(
    lat: float = Query(..., description="Latitud en grados decimales"),
    lon: float = Query(..., description="Longitud en grados decimales"),
    radio: int = Query(50000, description="Radio de búsqueda en metros")
):
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT "Latitud", "Longitud", "FP_T31", "FP_T21"
        FROM "girsar"."MODIS_TERRA_parted"
        WHERE "FP_T21" IS NOT NULL AND "FP_T31" IS NOT NULL
        AND sqrt(power(%s - "Longitud", 2) + power(%s - "Latitud", 2)) * 111111 <= %s
    """
    cursor.execute(query, (lon, lat, radio))
    datos = cursor.fetchall()
    cursor.close()
    conn.close()

    if not datos:
        return {
            "temperatura_minima": None,
            "temperatura_maxima": None,
            "temperatura_promedio": None,
            "confianza": 0.0,
            "num_puntos_usados": 0,
            "mensaje": "No se encontraron datos MODIS cerca del punto"
        }

    resultado, confianza = interpolacion_idw(lat, lon, datos)
    if resultado is None:
        return {
            "temperatura_minima": None,
            "temperatura_maxima": None,
            "temperatura_promedio": None,
            "confianza": 0.0,
            "num_puntos_usados": len(datos),
            "mensaje": "No se pudo interpolar"
        }

    return {
        "temperatura_minima": resultado["min"],
        "temperatura_maxima": resultado["max"],
        "temperatura_promedio": resultado["promedio"],
        "confianza": confianza,
        "num_puntos_usados": len(datos),
        "mensaje": ""
    }

@app.get("/mapa", response_class=HTMLResponse)
def mostrar_mapa():
    html_content = """
<!DOCTYPE html>
<html>
<head>
  <title>Mapa Temperatura MODIS</title>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html, body, #map {
      height: 100%;
      margin: 0;
      padding: 0;
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    var map = L.map('map').setView([-29.5, -62.1], 6);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    var marker;

    map.on('click', function(e) {
      var lat = e.latlng.lat.toFixed(5);
      var lon = e.latlng.lng.toFixed(5);

      if(marker){
        map.removeLayer(marker);
      }
      marker = L.marker([lat, lon]).addTo(map);

      fetch(`/temperatura?lat=${lat}&lon=${lon}&radio=50000`)
        .then(response => response.json())
        .then(data => {
          var popupContent = "";
          if(data.mensaje){
            popupContent = `<b>Mensaje:</b> ${data.mensaje}`;
          } else {
            popupContent = `
              <b>Temperatura mínima:</b> ${data.temperatura_minima} °C<br>
              <b>Temperatura máxima:</b> ${data.temperatura_maxima} °C<br>
              <b>Temperatura promedio:</b> ${data.temperatura_promedio} °C<br>
              <b>Confianza:</b> ${data.confianza}<br>
              <b>Puntos usados:</b> ${data.num_puntos_usados}`;
          }
          marker.bindPopup(popupContent).openPopup();
        })
        .catch(() => {
          marker.bindPopup("<b>Error:</b> No se pudo obtener datos.").openPopup();
        });
    });
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
