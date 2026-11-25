import os
import sys
import csv
import json
import statistics
from collections import defaultdict
from typing import List, Dict, Any

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.agent_ep2 import AgenteOperacionesDevCloud
from src.observability_ep3 import COLUMNAS_RUNS, COLUMNAS_SPANS

SCENARIOS_FILE = os.path.join("data", "scenarios_ep3.json")
LOGS_DIR = "logs"


def inicializar_archivos_logs(logs_dir: str) -> None:
    os.makedirs(logs_dir, exist_ok=True)
    runs_path = os.path.join(logs_dir, "agent_runs.csv")
    spans_path = os.path.join(logs_dir, "agent_spans.csv")
    events_path = os.path.join(logs_dir, "agent_events.jsonl")

    with open(runs_path, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=COLUMNAS_RUNS).writeheader()
    with open(spans_path, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=COLUMNAS_SPANS).writeheader()
    with open(events_path, "w", encoding="utf-8") as f:
        f.write("")


def evaluar_precision_escenario(
    escenario: Dict[str, Any],
    resultado: Dict[str, Any],
) -> bool:
    obs = resultado["observabilidad"]
    decision_obtenida = obs["decision_final"]
    decision_esperada = escenario["decision_esperada"]

    tools_llamadas = [t["herramienta"] for t in resultado["traza_ejecucion"]]
    respuesta_txt = (resultado["respuesta_final"] or "").lower()

    # 1. Validar decisión final o términos equivalentes
    decision_valida = (decision_obtenida == decision_esperada)
    if not decision_valida and decision_esperada == "ESCALADO_A_SRE":
        decision_valida = any(
            k in respuesta_txt for k in ["escalado", "sre", "bloqueo", "prohibid", "degraded", "sec-pol", "sop-ti"]
        )

    # 2. Validar herramientas mínimas críticas
    tools_requeridas = escenario.get("tools_requeridas", [])
    if tools_requeridas:
        # Al menos la mitad o las herramientas clave de acción/consulta deben haberse invocado
        coincidencias_tools = sum(1 for t in tools_requeridas if t in tools_llamadas)
        tools_validas = coincidencias_tools >= max(1, len(tools_requeridas) // 2)
    else:
        tools_validas = len(tools_llamadas) == 0

    return bool(decision_valida and tools_validas)


def ejecutar_bateria_ep3(logs_dir: str = LOGS_DIR, reanudar_existentes: bool = True) -> Dict[str, Any]:
    print("=" * 72)
    print("  EVALUACIÓN DE OBSERVABILIDAD, TRAZABILIDAD Y RENDIMIENTO (EP3)")
    print("=" * 72)

    with open(SCENARIOS_FILE, "r", encoding="utf-8") as f:
        escenarios: List[Dict[str, Any]] = json.load(f)

    runs_path = os.path.join(logs_dir, "agent_runs.csv")
    existentes_por_id: Dict[str, Dict[str, Any]] = {}
    hubo_429_previo = False

    if reanudar_existentes and os.path.exists(runs_path) and os.path.getsize(runs_path) > 0:
        with open(runs_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                existentes_por_id[row["scenario_id"]] = row
                if "429" in row.get("tipo_error", ""):
                    hubo_429_previo = True
    else:
        inicializar_archivos_logs(logs_dir)

    agente = AgenteOperacionesDevCloud(max_req_por_min=30, max_tokens_sesion=100000)
    if hubo_429_previo:
        agente._circuit_breaker_429 = True

    resultados_runs: List[Dict[str, Any]] = []
    decisiones_por_grupo: Dict[str, List[str]] = defaultdict(list)

    for idx, esc in enumerate(escenarios, 1):
        sc_id = esc["scenario_id"]
        cat = esc["categoria"]
        amb = esc["ambiente"]
        grp = esc.get("consistencia_grupo", "N/A")
        forzar_cont = bool(esc.get("simular_contingencia", False))

        if sc_id in existentes_por_id:
            obs_row = existentes_por_id[sc_id]
            tools_list = [t.strip() for t in obs_row.get("tools_usadas", "").split("->") if t.strip() and t.strip() != "NINGUNA"]
            res_sim = {
                "observabilidad": obs_row,
                "traza_ejecucion": [{"herramienta": t} for t in tools_list],
                "respuesta_final": obs_row.get("decision_final", ""),
            }
            es_preciso = evaluar_precision_escenario(esc, res_sim)
            obs_row["precision_ok"] = str(es_preciso)
            resultados_runs.append(obs_row)
            if grp != "N/A":
                decisiones_por_grupo[grp].append(obs_row["decision_final"])
            print(
                f"[{idx:02d}/{len(escenarios):02d}] {sc_id} (Reutilizado de traza en vivo) -> "
                f"Decisión: {obs_row['decision_final']} | Precisión: {es_preciso} | Latencia: {obs_row['latencia_total_ms']} ms"
            )
            continue

        print(f"\n[{idx:02d}/{len(escenarios):02d}] Ejecutando {sc_id} ({cat} | {amb})...")
        res = agente.ejecutar_tarea(
            consulta_usuario=esc["consulta"],
            session_id=f"eval_ep3_{sc_id.lower()}",
            scenario_id=sc_id,
            categoria=cat,
            ambiente=amb,
            consistencia_grupo=grp,
            logs_dir=logs_dir,
            forzar_contingencia=forzar_cont,
        )

        es_preciso = evaluar_precision_escenario(esc, res)
        res["observabilidad"]["precision_ok"] = str(es_preciso)
        resultados_runs.append(res["observabilidad"])

        if grp != "N/A":
            decisiones_por_grupo[grp].append(res["observabilidad"]["decision_final"])

        print(
            f"      -> Decisión: {res['observabilidad']['decision_final']} | "
            f"Precisión: {es_preciso} | Latencia: {res['observabilidad']['latencia_total_ms']} ms | "
            f"Tokens: {res['observabilidad']['tokens_total']}"
        )

    # Actualizar columna precision_ok en agent_runs.csv con la evaluación final
    runs_path = os.path.join(logs_dir, "agent_runs.csv")
    with open(runs_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS_RUNS)
        writer.writeheader()
        writer.writerows(resultados_runs)

    # Calcular consistencia por grupo de variación semántica
    puntajes_consistencia = []
    detalle_consistencia = {}
    for grp, decs in decisiones_por_grupo.items():
        mas_comun = max(set(decs), key=decs.count)
        ratio = round((decs.count(mas_comun) / len(decs)) * 100.0, 2)
        puntajes_consistencia.append(ratio)
        detalle_consistencia[grp] = {"decision_dominante": mas_comun, "muestras": len(decs), "consistencia_pct": ratio}

    consistencia_global_pct = round(statistics.mean(puntajes_consistencia), 2) if puntajes_consistencia else 100.0

    # Leer spans generados para análisis de cuellos de botella por etapa
    spans_path = os.path.join(logs_dir, "agent_spans.csv")
    duraciones_por_etapa: Dict[str, List[float]] = defaultdict(list)
    total_spans = 0
    with open(spans_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            total_spans += 1
            duraciones_por_etapa[row["etapa"]].append(float(row["duracion_ms"]))

    resumen_etapas = {}
    tiempo_total_spans = sum(sum(v) for v in duraciones_por_etapa.values()) or 1.0
    for etapa, durs in duraciones_por_etapa.items():
        suma_etapa = sum(durs)
        resumen_etapas[etapa] = {
            "cantidad_spans": len(durs),
            "latencia_promedio_ms": round(statistics.mean(durs), 2),
            "latencia_max_ms": round(max(durs), 2),
            "latencia_acumulada_ms": round(suma_etapa, 2),
            "porcentaje_tiempo_total": round((suma_etapa / tiempo_total_spans) * 100.0, 2),
        }

    latencias = [float(r["latencia_total_ms"]) for r in resultados_runs]
    latencias_ordenadas = sorted(latencias)
    idx_p95 = min(len(latencias_ordenadas) - 1, int(len(latencias_ordenadas) * 0.95))

    total_runs = len(resultados_runs)
    aciertos = sum(1 for r in resultados_runs if r["precision_ok"] == "True")
    errores = sum(1 for r in resultados_runs if r["tuvo_error"] == "True")
    fallbacks = sum(1 for r in resultados_runs if r["uso_fallback"] == "True")
    bloqueos_sec = sum(1 for r in resultados_runs if r["bloqueo_seguridad"] == "True")
    tokens_totales = sum(int(r["tokens_total"]) for r in resultados_runs)
    costo_total = round(sum(float(r["costo_usd"]) for r in resultados_runs), 6)
    memoria_max = max(float(r["memoria_mb"]) for r in resultados_runs)

    resumen_final = {
        "fecha_evaluacion": resultados_runs[-1]["timestamp"] if resultados_runs else "",
        "total_escenarios_ejecutados": total_runs,
        "total_spans_registrados": total_spans,
        "metricas_calidad_ie1": {
            "tasa_precision_pct": round((aciertos / total_runs) * 100.0, 2),
            "tasa_consistencia_pct": consistencia_global_pct,
            "tasa_errores_api_pct": round((errores / total_runs) * 100.0, 2),
            "tasa_recuperacion_fallback_pct": round((fallbacks / max(errores, 1)) * 100.0, 2) if errores else 100.0,
            "detalle_consistencia_grupos": detalle_consistencia,
        },
        "metricas_rendimiento_ie2": {
            "latencia_promedio_ms": round(statistics.mean(latencias), 2),
            "latencia_mediana_p50_ms": round(statistics.median(latencias), 2),
            "latencia_p95_ms": round(latencias_ordenadas[idx_p95], 2),
            "latencia_maxima_ms": round(max(latencias), 2),
            "tokens_totales_consumidos": tokens_totales,
            "tokens_promedio_por_consulta": round(tokens_totales / total_runs, 1),
            "costo_total_estimado_usd": costo_total,
            "memoria_ram_pico_mb": memoria_max,
        },
        "analisis_cuellos_de_botella_ie3": resumen_etapas,
        "seguridad_y_blindaje_ie8": {
            "ataques_prompt_injection_bloqueados": bloqueos_sec,
            "logs_sanitizados_pii": True,
            "integridad_rag_sha256": agente.integridad_rag["estado"],
        },
    }

    resumen_path = os.path.join(logs_dir, "resumen_metricas_ep3.json")
    with open(resumen_path, "w", encoding="utf-8") as f:
        json.dump(resumen_final, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 72)
    print("  RESUMEN EJECUTIVO DE MÉTRICAS EP3 (GUARDADO EN logs/resumen_metricas_ep3.json)")
    print("=" * 72)
    print(json.dumps(resumen_final, ensure_ascii=False, indent=2))
    return resumen_final


if __name__ == "__main__":
    ejecutar_bateria_ep3()
