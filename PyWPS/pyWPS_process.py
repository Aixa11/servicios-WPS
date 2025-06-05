from pywps import Process, LiteralInput, LiteralOutput
import psycopg2
import numpy as np

class TemperaturaMODISProcess(Process):
    def __init__(self):
        inputs = [
            LiteralInput('lat', 'Latitud', data_type='float', abstract='Latitud en grados decimales'),
            LiteralInput('lon', 'Longitud', data_type='float', abstract='Longitud en grados decimales'),
            LiteralInput('radio', 'Radio de búsqueda (m)', data_type='integer', default=50000,
                         abstract='Radio de búsqueda en metros')
        ]

        outputs = [
            LiteralOutput('temperatura_minima', 'Temperatura mínima (°C)', data_type='float'),
            LiteralOutput('temperatura_maxima', 'Temperatura máxima (°C)', data_type='float'),
            LiteralOutput('temperatura_promedio', 'Temperatura promedio (°C)', data_type='float'),
            LiteralOutput('confianza', 'Confianza de la interpolación', data_type='float'),
            LiteralOutput('num_puntos_usados', 'Número de puntos usados', data_type='integer'),
            LiteralOutput('mensaje', 'Mensaje de estado o error', data_type='string')
        ]

        super().__init__(
            self._handler,
            identifier='temperatura_modis',
            title='Estimación de temperatura MODIS',
            abstract='Calcula el rango de temperaturas en un punto dado usando datos MODIS y una interpolación IDW',
            version='1.0',
            inputs=inputs,
            outputs=outputs,
            store_supported=True,
            status_supported=True
        )

    def get_conn(self):
        return psycopg2.connect(
            host="localhost",
            port="5433",
            user="administrator",
            password="Sa0.C0n43",
            database="girsar"
        )

    def convertir_temperatura(self, fp_value):
        if fp_value is None:
            return None
        temp_kelvin = fp_value * 0.02 + 273.15
        return temp_kelvin - 273.15

    def interpolacion_idw(self, lat, lon, datos, potencia=2):
        distancias = []
        temps_t21 = []
        temps_t31 = []
        for d in datos:
            lat_ref, lon_ref, fp_t31, fp_t21 = d
            dist = np.sqrt((lat - lat_ref)**2 + (lon - lon_ref)**2)
            distancias.append(dist)
            temps_t21.append(self.convertir_temperatura(fp_t21))
            temps_t31.append(self.convertir_temperatura(fp_t31))
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

    def _handler(self, request, response):
        lat = request.inputs['lat'][0].data
        lon = request.inputs['lon'][0].data
        radio = request.inputs['radio'][0].data

        try:
            conn = self.get_conn()
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
                response.outputs['mensaje'].data = "No se encontraron datos MODIS cerca del punto"
                response.outputs['temperatura_minima'].data = None
                response.outputs['temperatura_maxima'].data = None
                response.outputs['temperatura_promedio'].data = None
                response.outputs['confianza'].data = 0.0
                response.outputs['num_puntos_usados'].data = 0
                return response

            resultado, confianza = self.interpolacion_idw(lat, lon, datos)
            if resultado is None:
                response.outputs['mensaje'].data = "No se pudo interpolar"
                response.outputs['temperatura_minima'].data = None
                response.outputs['temperatura_maxima'].data = None
                response.outputs['temperatura_promedio'].data = None
                response.outputs['confianza'].data = 0.0
                response.outputs['num_puntos_usados'].data = len(datos)
                return response

            response.outputs['temperatura_minima'].data = resultado["min"]
            response.outputs['temperatura_maxima'].data = resultado["max"]
            response.outputs['temperatura_promedio'].data = resultado["promedio"]
            response.outputs['confianza'].data = confianza
            response.outputs['num_puntos_usados'].data = len(datos)
            response.outputs['mensaje'].data = ""

        except Exception as e:
            response.outputs['mensaje'].data = f"Error al procesar: {str(e)}"
            response.outputs['temperatura_minima'].data = None
            response.outputs['temperatura_maxima'].data = None
            response.outputs['temperatura_promedio'].data = None
            response.outputs['confianza'].data = 0.0
            response.outputs['num_puntos_usados'].data = 0

        return response