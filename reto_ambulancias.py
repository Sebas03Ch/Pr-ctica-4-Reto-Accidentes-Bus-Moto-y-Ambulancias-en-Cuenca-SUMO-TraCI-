import os
import sys

# Configurar SUMO_HOME si no está definido en el sistema
if 'SUMO_HOME' not in os.environ:
    # Ruta común en Linux (si lo instalaste por apt o compilaste)
    os.environ['SUMO_HOME'] = '/usr/share/sumo' 
    # O si usas otra ruta personalizada, cámbiala aquí.

# Añadir la carpeta tools de SUMO al path de Python
tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
if tools not in sys.path:
    sys.path.append(tools)


import os
import sys
import traci
import sumolib
import random
from collections import deque

# Configurar SUMO_HOME automáticamente si es necesario en el entorno
if 'SUMO_HOME' not in os.environ:
    os.environ['SUMO_HOME'] = '/usr/share/sumo'

tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
if tools not in sys.path:
    sys.path.append(tools)

# Tabla 4.5: Hospitales del reto con sus coordenadas WGS84[cite: 58]
hospitales_data = {
    "VCM": {"tipo": "público", "nombre": "Hospital Vicente Corral Moscoso (MSP)", "lon": -78.992923, "lat": -2.911098},
    "IESS_JCA": {"tipo": "público", "nombre": "Hospital José Carrasco Arteaga (IESS)", "lon": -78.970118, "lat": -2.898698},
    "MILITAR": {"tipo": "público", "nombre": "Hospital Militar HB-III Tarqui", "lon": -79.003968, "lat": -2.903146},
    "MUNI_PAT": {"tipo": "público", "nombre": "Hospital Municipal de Cuenca (Patamarca)", "lon": -78.982263, "lat": -2.866103},
    "MUNI_VALLE": {"tipo": "público", "nombre": "Hospital Municipal de El Valle", "lon": -78.961959, "lat": -2.919522},
    "MONTE_SINAI": {"tipo": "privado", "nombre": "Hospital Monte Sinaí", "lon": -79.007373, "lat": -2.908606},
    "DEL_RIO": {"tipo": "privado", "nombre": "Hospital Universitario del Río", "lon": -78.960796, "lat": -2.892939}
}

def ejecutar_fase2():
    # Iniciar SUMO en modo consola (headless) usando el archivo de configuración de la Fase 1
    traci.start(["sumo", "-c", "reto.sumocfg"])
    
    # Fijar semilla para asegurar reproducibilidad en las pruebas aleatorias[cite: 61]
    random.seed(42)
    
    hospitales_info = {}
    
    print("\n" + "="*60)
    print("--- TAREA 2.1 y 2.2: MAPEGO DE HOSPITALES Y FLOTA ---")
    print("="*60)
    
    for hid, hinfo in hospitales_data.items():
        # Convertir coordenadas geográficas WGS84 a la arista y carril de la red[cite: 61]
        edge, pos, lane = traci.simulation.convertRoad(hinfo["lon"], hinfo["lat"], isGeo=True, vClass="emergency")
        street_name = traci.edge.getStreetName(edge)
        
        # Stock inicial aleatorio: públicos (1-3 unidades), privados (0-1 unidades)[cite: 60]
        stock_inicial = random.randint(1, 3) if hinfo["tipo"] == "público" else random.randint(0, 1)
        
        # Cola FIFO de unidades disponibles (deque)
        cola_unidades = deque([f"{hid}_U{i+1}" for i in range(stock_inicial)])
        
        hospitales_info[hid] = {
            "edge": edge,
            "pos": pos,
            "cola": cola_unidades,
            "stock_ini": stock_inicial,
            "tipo": hinfo["tipo"]
        }
        
        # Dibujar POI visual en SUMO-GUI (si se abriera con GUI) o registrarlo en la simulación
        x, y = traci.simulation.convertGeo(hinfo["lon"], hinfo["lat"], fromGeo=True)
        traci.poi.add(hid, x, y, color=(255, 0, 0, 255), layer=100, poiType="hospital")
        
        print(f"Hospital: {hid:<12} | Arista: {edge:<15} | Stock: {stock_inicial} | Calle: {street_name}")

    print("="*60 + "\n")

    # --- TAREA 2.3 y VALIDACIÓN A4: PRUEBA MANUAL DE DESPACHO (En t = 120 s) ---
    prueba_realizada = False
    step_salida = 0
    travel_time_estimado = 0.0
    
    step = 0
    end_step = 12600  # 3 horas + 30 min
    
    while step < end_step:
        traci.simulationStep()
        
        # Despachar ambulancia de prueba a los 120 segundos desde VCM hasta IESS_JCA
        if step == 120 and not prueba_realizada:
            print("--- EJECUTANDO AMBULANCIA DE PRUEBA (T = 120s) ---")
            origen_edge = hospitales_info["VCM"]["edge"]
            destino_edge = hospitales_info["IESS_JCA"]["edge"]
            
            # Calcular ruta óptima en tiempo real usando findRoute[cite: 59]
            route_data = traci.simulation.findRoute(origen_edge, destino_edge, vType="ambulance")
            
            if route_data.edges:
                amb_id = "amb_test_01"
                route_id = "route_test_vcm_iess"
                
                traci.route.add(route_id, route_data.edges)
                traci.vehicle.add(
                    vehID=amb_id, 
                    routeID=route_id, 
                    typeID="ambulance", 
                    depart="now", 
                    departPos=hospitales_info["VCM"]["pos"]
                )
                
                step_salida = step
                travel_time_estimado = route_data.travelTime
                
                print(f"Ambulancia {amb_id} despachada desde VCM en t = {step_salida} s.")
                print(f"-> TravelTime ESTIMADO (findRoute): {travel_time_estimado:.2f} segundos")
            
            prueba_realizada = True
            
        # Comprobar llegada de la ambulancia de prueba usando getArrivedIDList() y comparar[cite: 60]
        if prueba_realizada:
            arrived_list = traci.simulation.getArrivedIDList()
            if "amb_test_01" in arrived_list:
                step_llegada = step
                tiempo_medido_real = step_llegada - step_salida
                
                print("\n" + "="*60)
                print("RESULTADO DE LA COMPARACIÓN (Validación A4)")
                print("="*60)
                print(f"Momento de salida:           {step_salida} s")
                print(f"Momento de llegada:          {step_llegada} s")
                print(f"Tiempo Real Medido (Sim):    {tiempo_medido_real} s")
                print(f"Tiempo Estimado (findRoute): {travel_time_estimado:.2f} s")
                print(f"Diferencia absoluta:         {abs(tiempo_medido_real - travel_time_estimado):.2f} s")
                print("="*60 + "\n")
                break
                
        step += 1

    traci.close()

if __name__ == "__main__":
    ejecutar_fase2()
