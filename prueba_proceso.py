from fastapi import FastAPI, Query
from pydantic import BaseModel
import psycopg2
import numpy as np

app = FastAPI(title="Servicio de Temperatura MODIS")

# Conexión a tu base de datos
def get_conn():
    return psycopg2.connect(
        host="localhost",
        port="5433",
        user="administrator", 
        password="xxxx",
        database="girsar"
    )

# Conversión MODIS a Celsius
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
    datos_validos = [(d, t21, t31) for d, t21, t31 in zip(distancias, temps_t21, temps_t31) if t21 is not None and t31 is not None]
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
    return {
        "min": round(min(temp_t21_interp, temp_t31_interp), 2),
        "max": round(max(temp_t21_interp, temp_t31_interp), 2)
    }, round(confianza, 3)

@app.get("/temperatura")
def estimar_temperatura(
    lat: float = Query(..., description="Latitud en grados decimales"),
    lon: float = Query(..., description="Longitud en grados decimales"),
    radio: int = Query(50000, description="Radio de búsqueda en metros")
):
    conn = get_conn()
    cursor = conn.cursor()
    # Consulta adaptada a tu estructura
    query = """
        SELECT "Latitud", "Longitud", "FP_T31", "FP_T21"
        FROM "girsar"."girsar"."MODIS_TERRA_parted"
        WHERE "FP_T21" IS NOT NULL AND "FP_T31" IS NOT NULL
        AND sqrt(power(%s - "Longitud", 2) + power(%s - "Latitud", 2)) * 111111 <= %s
        LIMIT 50
    """
    cursor.execute(query, (lon, lat, radio))
    datos = cursor.fetchall()
    cursor.close()
    conn.close()
    if not datos:
        return {"error": "No se encontraron datos MODIS cerca del punto"}
    resultado, confianza = interpolacion_idw(lat, lon, datos)
    if resultado is None:
        return {"error": "No se pudo interpolar"}
    return {
        "temperatura_minima": resultado["min"],
        "temperatura_maxima": resultado["max"],
        "confianza": confianza,
        "num_puntos_usados": len(datos)
    }