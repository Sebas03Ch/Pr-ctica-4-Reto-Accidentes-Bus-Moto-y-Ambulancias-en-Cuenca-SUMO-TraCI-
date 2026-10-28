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
import csv
import pandas as pd
import numpy as np

# Configurar Matplotlib para modo no interactivo (headless Linux)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from collections import deque

if 'SUMO_HOME' not in os.environ:
    os.environ['SUMO_HOME'] = '/usr/share/sumo'

tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
if tools not in sys.path:
    sys.path.append(tools)

# Tabla 4.5: Hospitales del reto con coordenadas WGS84
hospitales_data = {
    "VCM": {"tipo": "público", "nombre": "Hospital Vicente Corral Moscoso (MSP)", "lon": -78.992923, "lat": -2.911098},
    "IESS_JCA": {"tipo": "público", "nombre": "Hospital José Carrasco Arteaga (IESS)", "lon": -78.970118, "lat": -2.898698},
    "MILITAR": {"tipo": "público", "nombre": "Hospital Militar HB-III Tarqui", "lon": -79.003968, "lat": -2.903146},
    "MUNI_PAT": {"tipo": "público", "nombre": "Hospital Municipal de Cuenca (Patamarca)", "lon": -78.982263, "lat": -2.866103},
    "MUNI_VALLE": {"tipo": "público", "nombre": "Hospital Municipal de El Valle", "lon": -78.961959, "lat": -2.919522},
    "MONTE_SINAI": {"tipo": "privado", "nombre": "Hospital Monte Sinaí", "lon": -79.007373, "lat": -2.908606},
    "DEL_RIO": {"tipo": "privado", "nombre": "Hospital Universitario del Río", "lon": -78.960796, "lat": -2.892939}
}

def ejecutar_simulacion():
    traci.start(["sumo", "-c", "reto.sumocfg"])
    random.seed(42)
    
    hospitales_info = {}
    print("\n" + "="*60)
    print("--- FASES 2, 3, 4 y 5: SIMULACIÓN INTEGRAL DE EMERGENCIAS ---")
    print("="*60)
    
    for hid, hinfo in hospitales_data.items():
        edge, pos, lane = traci.simulation.convertRoad(hinfo["lon"], hinfo["lat"], isGeo=True, vClass="emergency")
        street_name = traci.edge.getStreetName(edge)
        
        stock_inicial = random.randint(1, 3) if hinfo["tipo"] == "público" else random.randint(0, 1)
        cola_unidades = deque([f"{hid}_U{i+1}" for i in range(stock_inicial)])
        
        hospitales_info[hid] = {
            "edge": edge,
            "pos": pos,
            "cola": cola_unidades,
            "stock_ini": stock_inicial,
            "stock_fin": stock_inicial,
            "tipo": hinfo["tipo"],
            "despachos": 0,
            "retornos": 0,
            "rechazos_sin_unidad": 0,
            "tiempo_ocupado_total": 0.0
        }
        
        x, y = traci.simulation.convertGeo(hinfo["lon"], hinfo["lat"], fromGeo=True)
        traci.poi.add(hid, x, y, color=(255, 0, 0, 255), layer=100, poiType="hospital")

    # --- FASE 3: AGENDA DE ACCIDENTES (15 eventos, 5 por hora) ---
    agenda_accidentes = []
    for hora in range(3):
        inicio_hora = hora * 3600 + 300
        fin_hora = (hora + 1) * 3600
        instantes_hora = sorted([random.randint(inicio_hora, fin_hora) for _ in range(5)])
        agenda_accidentes.extend(instantes_hora)
    
    # Estructuras de datos para Fase 5 (CSV y analítica)
    accidentes_registrados = []  # Filas para accidentes.csv
    stock_historial = []         # Filas para stock.csv
    
    accidentes_pendientes = []
    misiones_activas = {}
    pares_colisionados = set()
    intentos_activos = {}
    
    prueba_realizada = False
    step_salida = 0
    travel_time_estimado = 0.0
    
    step = 0
    end_step = 12600  # 3 horas + 30 min
    
    print("\n--- INICIANDO BUCLE DE SIMULACIÓN ---")
    while step < end_step:
        traci.simulationStep()
        
        # Validación A4 (t = 120s)
        if step == 120 and not prueba_realizada:
            origen_edge = hospitales_info["VCM"]["edge"]
            destino_edge = hospitales_info["IESS_JCA"]["edge"]
            route_data = traci.simulation.findRoute(origen_edge, destino_edge, vType="ambulance")
            if route_data.edges:
                amb_id = "amb_test_01"
                route_id = "route_test_vcm_iess"
                traci.route.add(route_id, route_data.edges)
                traci.vehicle.add(vehID=amb_id, routeID=route_id, typeID="ambulance", depart="now", departPos=hospitales_info["VCM"]["pos"])
                step_salida = step
                travel_time_estimado = route_data.travelTime
            prueba_realizada = True
            
        if prueba_realizada and step_salida > 0 and "amb_test_01" in traci.simulation.getArrivedIDList():
            step_salida = -1

        # --- TAREA 4.5 / 5.1: SNAPSHOT DE STOCK CADA 60 s ---
        if step % 60 == 0:
            snapshot = {"step": step}
            for hid, hinfo in hospitales_info.items():
                snapshot[hid] = len(hinfo["cola"])
            stock_historial.append(snapshot)

        # Timeout motos (Fase 3)
        for moto in list(intentos_activos.keys()):
            if step >= intentos_activos[moto]["tiempo_limite"]:
                if moto in traci.vehicle.getIDList():
                    try:
                        traci.vehicle.setSpeedMode(moto, 31)
                        traci.vehicle.setSpeed(moto, -1)
                    except traci.TraCIException:
                        pass
                del intentos_activos[moto]
                agenda_accidentes.append(step + 5)

        # Disparar accidente por agenda
        if step in agenda_accidentes:
            buses_activos = [v for v in traci.vehicle.getIDList() if "bus" in traci.vehicle.getTypeID(v)]
            if buses_activos:
                bus = random.choice(buses_activos)
                bus_edge = traci.vehicle.getRoadID(bus)
                if not bus_edge.startswith(':'):
                    bus_pos = traci.vehicle.getLanePosition(bus)
                    if traci.vehicle.getSpeed(bus) > 2 and bus_pos > 20:
                        try:
                            edge_len = traci.lane.getLength(f"{bus_edge}_0")
                        except Exception:
                            edge_len = 100.0
                        pos_moto = max(2.0, min(bus_pos - 10.0, edge_len - 5.0))
                        
                        moto = f"moto_acc_{step}"
                        route_id = f"route_acc_{step}"
                        bus_route = traci.vehicle.getRoute(bus)
                        if len(bus_route) > 0:
                            try:
                                traci.route.add(route_id, bus_route)
                                traci.vehicle.add(moto, route_id, typeID="moto", depart="now", departPos=pos_moto, departSpeed="max", departLane="0")
                                traci.vehicle.setSpeedMode(moto, 0)
                                traci.vehicle.setSpeed(moto, 30)
                                intentos_activos[moto] = {"bus": bus, "tiempo_limite": step + 90}
                            except Exception:
                                pass

        # Detección de colisiones Bus-Moto
        try:
            for col in traci.simulation.getCollisions():
                collider, victim = col.collider, col.victim
                c_type = traci.vehicle.getTypeID(collider) if collider in traci.vehicle.getIDList() else ""
                v_type = traci.vehicle.getTypeID(victim) if victim in traci.vehicle.getIDList() else ""
                
                if ("bus" in c_type.lower() and "moto" in v_type.lower()) or ("moto" in c_type.lower() and "bus" in v_type.lower()):
                    par = tuple(sorted([collider, victim]))
                    if par not in pares_colisionados:
                        pares_colisionados.add(par)
                        if collider in intentos_activos: del intentos_activos[collider]
                        if victim in intentos_activos: del intentos_activos[victim]
                        
                        bus_veh = collider if "bus" in c_type.lower() else victim
                        edge_destino = None
                        try:
                            edge_destino = traci.vehicle.getRoadID(bus_veh)
                            if edge_destino.startswith(':'):
                                r_idx = traci.vehicle.getRouteIndex(bus_veh)
                                r_edges = traci.vehicle.getRoute(bus_veh)
                                edge_destino = r_edges[r_idx + 1] if r_idx + 1 < len(r_edges) else r_edges[-1]
                        except Exception:
                            pass
                        if not edge_destino or edge_destino.startswith(':'):
                            edge_destino = col.lane.rsplit('_', 1)[0] if not col.lane.startswith(':') else "333179949"

                        acc_dict = {
                            "id": f"acc_{step}_{random.randint(100,999)}",
                            "t_accidente": step,
                            "collider": collider,
                            "victim": victim,
                            "edge": edge_destino,
                            "pos": max(0.0, col.pos),
                            "t_despacho": None,
                            "t_llegada": None,
                            "t_retorno": None,
                            "hospital_origen": None,
                            "hospital_retorno": None,
                            "espera_ambulancia_s": 0,
                            "reintentos": 0,
                            "ultimo_reintento": 0,
                            "estado_final": "pendiente"
                        }
                        accidentes_pendientes.append(acc_dict)
                        accidentes_registrados.append(acc_dict)
                        
                        for veh in [collider, victim]:
                            if veh in traci.vehicle.getIDList():
                                try:
                                    traci.vehicle.setSpeedMode(veh, 0)
                                    traci.vehicle.setSpeed(veh, 0.01)
                                    traci.vehicle.setSpeedMode(veh, 31)
                                except traci.TraCIException:
                                    pass
        except Exception:
            pass

        # --- FASE 4.1 & 4.2: DESPACHO ---
        for acc in list(accidentes_pendientes):
            if step - acc["ultimo_reintento"] >= 30:
                acc["ultimo_reintento"] = step
                acc["reintentos"] += 1
                
                mejor_hospital = None
                menor_travel_time = float('inf')
                hospitales_con_stock = False
                
                for hid, hinfo in hospitales_info.items():
                    if len(hinfo["cola"]) > 0:
                        hospitales_con_stock = True
                        route_res = traci.simulation.findRoute(hinfo["edge"], acc["edge"], vType="ambulance")
                        if route_res.edges and route_res.travelTime < menor_travel_time:
                            menor_travel_time = route_res.travelTime
                            mejor_hospital = hid
                
                if not hospitales_con_stock:
                    for hinfo in hospitales_info.values():
                        hinfo["rechazos_sin_unidad"] += 1
                
                if mejor_hospital:
                    unit_id = hospitales_info[mejor_hospital]["cola"].popleft()
                    route_id = f"route_{unit_id}_{step}"
                    route_res = traci.simulation.findRoute(hospitales_info[mejor_hospital]["edge"], acc["edge"], vType="ambulance")
                    traci.route.add(route_id, route_res.edges)
                    traci.vehicle.add(vehID=unit_id, routeID=route_id, typeID="ambulance", depart="now", departPos=hospitales_info[mejor_hospital]["pos"])
                    
                    acc["t_despacho"] = step
                    acc["hospital_origen"] = mejor_hospital
                    acc["espera_ambulancia_s"] = step - acc["t_accidente"]
                    acc["estado_final"] = "en_camino"
                    
                    hospitales_info[mejor_hospital]["despachos"] += 1
                    
                    misiones_activas[unit_id] = {
                        "estado": "en_camino",
                        "hospital_origen": mejor_hospital,
                        "t_despacho": step,
                        "accidente": acc,
                        "tiempo_en_ruta": 0
                    }
                    accidentes_pendientes.remove(acc)

        # --- FASE 4.3, 4.4 & 4.5: SEGUIMIENTO, ATENCIÓN Y RETORNO ---
        arrived_ids = traci.simulation.getArrivedIDList()
        for amb_id in list(misiones_activas.keys()):
            mision = misiones_activas[amb_id]
            acc = mision["accidente"]
            
            if mision["estado"] == "en_camino":
                mision["tiempo_en_ruta"] += 1
                if mision["tiempo_en_ruta"] % 60 == 0:
                    try: traci.vehicle.rerouteTraveltime(amb_id)
                    except traci.TraCIException: pass
                
                llego_por_arrived = amb_id in arrived_ids
                try:
                    amb_edge = traci.vehicle.getRoadID(amb_id)
                    amb_pos = traci.vehicle.getLanePosition(amb_id)
                    d = traci.simulation.getDistanceRoad(amb_edge, amb_pos, acc["edge"], acc["pos"], isDriving=True)
                except Exception:
                    d = -1.0
                
                if (0 <= d <= 50) or llego_por_arrived:
                    acc["t_llegada"] = step
                    mision["estado"] = "atendiendo"
                    mision["timer_atencion"] = step
                    acc["estado_final"] = "atendiendo"
                    try:
                        traci.vehicle.setSpeedMode(amb_id, 0)
                        traci.vehicle.setSpeed(amb_id, 0.01)
                    except traci.TraCIException: pass

            elif mision["estado"] == "atendiendo":
                if step - mision["timer_atencion"] >= 120:
                    for veh_id in [acc["collider"], acc["victim"]]:
                        if veh_id in traci.vehicle.getIDList():
                            try: traci.vehicle.remove(veh_id)
                            except traci.TraCIException: pass
                            
                    mejor_retorno = None
                    menor_tt_retorno = float('inf')
                    for hid, hinfo in hospitales_info.items():
                        route_res = traci.simulation.findRoute(acc["edge"], hinfo["edge"], vType="ambulance")
                        if route_res.edges and route_res.travelTime < menor_tt_retorno:
                            menor_tt_retorno = route_res.travelTime
                            mejor_retorno = hid
                    if not mejor_retorno: mejor_retorno = mision["hospital_origen"]
                    
                    acc["hospital_retorno"] = mejor_retorno
                    hospitales_info[mejor_retorno]["retornos"] += 1
                    
                    try:
                        traci.vehicle.setSpeedMode(amb_id, 31)
                        traci.vehicle.setLaneChangeMode(amb_id, 1621)
                        traci.vehicle.setSpeed(amb_id, -1)
                        traci.vehicle.changeTarget(amb_id, hospitales_info[mejor_retorno]["edge"])
                    except traci.TraCIException: pass
                    
                    mision["estado"] = "retornando"
                    acc["estado_final"] = "retornando"

            elif mision["estado"] == "retornando":
                if amb_id in arrived_ids:
                    acc["t_retorno"] = step
                    acc["estado_final"] = "completado"
                    duracion_mision = acc["t_retorno"] - acc["t_despacho"]
                    
                    ret_hid = acc["hospital_retorno"]
                    hospitales_info[ret_hid]["cola"].append(amb_id)
                    
                    orig_hid = mision["hospital_origen"]
                    hospitales_info[orig_hid]["tiempo_ocupado_total"] += duracion_mision
                    
                    del misiones_activas[amb_id]

        step += 1

    # Actualizar stock final en hospitales
    for hid, hinfo in hospitales_info.items():
        hinfo["stock_fin"] = len(hinfo["cola"])

    traci.close()
    print("\nSimulación finalizada. Generando archivos CSV e indicadores...")

    # =========================================================================
    # --- FASE 5.1: ESCRITURA DE ARCHIVOS CSV ---
    # =========================================================================
    
    # 1. accidentes.csv
    keys_acc = ["id", "t_accidente", "t_despacho", "t_llegada", "t_retorno", "hospital_origen", "hospital_retorno", "espera_ambulancia_s", "estado_final"]
    with open("accidentes.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys_acc)
        writer.writeheader()
        for acc in accidentes_registrados:
            row = {k: acc.get(k) for k in keys_acc}
            writer.writerow(row)

    # 2. hospitales.csv
    with open("hospitales.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["hospital", "tipo", "stock_inicial", "stock_final", "despachos", "retornos", "rechazos_sin_unidad", "segundos_ocupados", "utilizacion"])
        for hid, hinfo in hospitales_info.items():
            # Utilizacion = ocupado / (3h * stock inicial) = ocupado / (10800 * stock_ini)
            if hinfo["stock_ini"] > 0:
                util = hinfo["tiempo_ocupado_total"] / (10800.0 * hinfo["stock_ini"])
            else:
                util = "n/a"
            writer.writerow([hid, hinfo["tipo"], hinfo["stock_ini"], hinfo["stock_fin"], hinfo["despachos"], hinfo["retornos"], hinfo["rechazos_sin_unidad"], hinfo["tiempo_ocupado_total"], util])

    # 3. stock.csv
    if stock_historial:
        stock_keys = list(stock_historial[0].keys())
        with open("stock.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=stock_keys)
            writer.writeheader()
            for row in stock_historial:
                writer.writerow(row)

    # =========================================================================
    # --- FASE 5.2: INDICADORES CON PANDAS ---
    # =========================================================================
    df_acc = pd.DataFrame(accidentes_registrados)
    
    # Calcular métricas temporales si existen registros
    if not df_acc.empty and df_acc["t_llegada"].notnull().any():
        df_acc["tiempo_respuesta"] = df_acc["t_llegada"] - df_acc["t_despacho"]
        df_acc["tiempo_total"] = df_acc["t_llegada"] - df_acc["t_accidente"]
        df_acc["duracion_mision"] = df_acc["t_retorno"] - df_acc["t_despacho"]
        
        print("\n" + "="*50)
        print("--- INDICADORES DE RENDIMIENTO (Fase 5.2) ---")
        print("="*50)
        print(f"Total accidentes registrados: {len(df_acc)}")
        print(f"Accidentes atendidos con éxito: {df_acc['t_llegada'].notnull().sum()}")
        print(f"Accidentes que esperaron ambulancia: (espera > 0): {(df_acc['espera_ambulancia_s'] > 0).sum()}")
        print(f"Espera máxima de ambulancia: {df_acc['espera_ambulancia_s'].max():.1f} s")
        
        print("\n--- Tiempo de Respuesta (Despacho -> Llegada) ---")
        tr = df_acc["tiempo_respuesta"].dropna()
        print(f"  Media: {tr.mean():.1f}s | Mediana: {tr.median():.1f}s | P90: {tr.quantile(0.9):.1f}s | Min: {tr.min():.1f}s | Max: {tr.max():.1f}s")
        
        print("\n--- Tiempo Total (Accidente -> Llegada) ---")
        tt = df_acc["tiempo_total"].dropna()
        print(f"  Media: {tt.mean():.1f}s | Mediana: {tt.median():.1f}s | P90: {tt.quantile(0.9):.1f}s | Min: {tt.min():.1f}s | Max: {tt.max():.1f}s")
        
        # Porcentaje de retornos a un hospital distinto
        df_completos = df_acc[df_acc["hospital_retorno"].notnull()]
        if not df_completos.empty:
            distintos = (df_completos["hospital_origen"] != df_completos["hospital_retorno"]).sum()
            porc_distintos = (distintos / len(df_completos)) * 100
            print(f"\nPorcentaje de retornos a hospital distinto: {porc_distintos:.1f}%")
        
        print("\n--- Estadísticas de Hospitales Públicos ---")
        for hid, hinfo in hospitales_info.items():
            if hinfo["tipo"] == "público":
                util = hinfo["tiempo_ocupado_total"] / (10800.0 * hinfo["stock_ini"]) if hinfo["stock_ini"] > 0 else 0
                print(f"  {hid:<10} | Despachos: {hinfo['despachos']:<3} | Retornos: {hinfo['retornos']:<3} | Utilización: {util*100:.1f}%")
        print("="*50)

    # =========================================================================
    # --- FASE 5.3: GENERACIÓN DE GRÁFICOS (Matplotlib) ---
    # =========================================================================
    if not df_acc.empty and df_acc["t_llegada"].notnull().any():
        os.makedirs("figuras", exist_ok=True)
        
        # (a) Gráfico de tiempo de respuesta por accidente con mediana y p90
        plt.figure(figsize=(10, 5))
        plt.plot(df_acc.index, df_acc["tiempo_respuesta"], marker='o', linestyle='-', color='b', label='Tiempo de Respuesta')
        med_tr = df_acc["tiempo_respuesta"].median()
        p90_tr = df_acc["tiempo_respuesta"].quantile(0.9)
        plt.axhline(med_tr, color='g', linestyle='--', label=f'Mediana ({med_tr:.1f}s)')
        plt.axhline(p90_tr, color='r', linestyle='--', label=f'P90 ({p90_tr:.1f}s)')
        plt.title('Tiempo de Respuesta por Accidente')
        plt.xlabel('Índice de Accidente')
        plt.ylabel('Segundos')
        plt.legend()
        plt.grid(True)
        plt.savefig("figuras/tiempo_respuesta_accidentes.png")
        plt.close()

    # (b) Stock inicial, despachos y retornos por hospital
    nombres_h = list(hospitales_info.keys())
    s_ini = [h["stock_ini"] for h in hospitales_info.values()]
    desp = [h["despachos"] for h in hospitales_info.values()]
    rets = [h["retornos"] for h in hospitales_info.values()]
    
    x = np.arange(len(nombres_h))
    width = 0.25
    plt.figure(figsize=(10, 5))
    plt.bar(x - width, s_ini, width, label='Stock Inicial')
    plt.bar(x, desp, width, label='Despachos')
    plt.bar(x + width, rets, width, label='Retornos')
    plt.title('Estadísticas Operativas por Hospital')
    plt.xticks(x, nombres_h)
    plt.ylabel('Cantidad')
    plt.legend()
    plt.grid(axis='y')
    plt.savefig("figuras/hospitales_operativa.png")
    plt.close()

    # (c) Stock disponible en el tiempo (un panel por hospital)
    if stock_historial:
        df_stock = pd.DataFrame(stock_historial)
        fig, axes = plt.subplots(nrows=4, ncols=2, figsize=(12, 10), sharex=True)
        axes = axes.flatten()
        for idx, hid in enumerate(hospitales_info.keys()):
            if hid in df_stock.columns:
                axes[idx].plot(df_stock["step"] / 3600.0, df_stock[hid], color='purple', drawstyle='steps-post')
                axes[idx].set_title(hid)
                axes[idx].set_ylabel('Unidades')
                axes[idx].grid(True)
        plt.suptitle('Evolución del Stock Disponible por Hospital (Horas)')
        plt.tight_layout()
        plt.savefig("figuras/stock_en_el_tiempo.png")
        plt.close()

    print("\n¡Archivos CSV ('accidentes.csv', 'hospitales.csv', 'stock.csv') y gráficos de la Fase 5 guardados con éxito!")

if __name__ == "__main__":
    ejecutar_simulacion()
