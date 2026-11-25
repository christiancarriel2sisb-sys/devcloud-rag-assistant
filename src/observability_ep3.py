import os
import sys
import csv
import json
import time
import uuid
import psutil
from datetime import datetime
from contextlib import contextmanager
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.security_ep3 import sanitizar_texto

# Tarifas referenciales por 1M de tokens (Gemini 2.5 Flash) para auditoría de costos
PRECIO_INPUT_POR_1M_USD = 0.30
PRECIO_OUTPUT_POR_1M_USD = 2.50

LOGS_DIR_DEFAULT = "logs"

COLUMNAS_RUNS = [
    "trace_id","session_id","timestamp","scenario_id","categoria","ambiente","consulta_sanitizada","decision_final","latencia_total_ms",
    "tokens_in","tokens_out","tokens_total","tokens_por_seg","costo_usd", "memoria_mb","iteraciones_react","num_tools","tools_usadas",
    "precision_ok","consistencia_grupo","tuvo_error","tipo_error", "uso_fallback","bloqueo_seguridad",]

COLUMNAS_SPANS = [
    "span_id","parent_span_id","trace_id","session_id","timestamp","orden_paso","etapa","componente",
    "duracion_ms","estado","tokens_in", "tokens_out","detalle_sanitizado",
]


def extraer_tokens_respuesta(respuesta_ai: Any) -> Dict[str, int]:
    usage = getattr(respuesta_ai, "usage_metadata", None)
    if not usage and hasattr(respuesta_ai, "response_metadata"):
        usage = respuesta_ai.response_metadata.get("usage_metadata")

    if isinstance(usage, dict):
        in_tok = int(usage.get("input_tokens") or usage.get("prompt_token_count") or 0)
        out_tok = int(usage.get("output_tokens") or usage.get("candidates_token_count") or 0)
        tot_tok = int(usage.get("total_tokens") or (in_tok + out_tok))
        return {"input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": tot_tok}

    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def calcular_costo_usd(tokens_in: int, tokens_out: int) -> float:
    costo_in = (tokens_in / 1_000_000) * PRECIO_INPUT_POR_1M_USD
    costo_out = (tokens_out / 1_000_000) * PRECIO_OUTPUT_POR_1M_USD
    return round(costo_in + costo_out, 6)


def obtener_memoria_proceso_mb() -> float:
    proceso = psutil.Process(os.getpid())
    return round(proceso.memory_info().rss / (1024 * 1024), 2)


class RegistroSpan:
    def __init__(
        self,
        span_id: str,
        parent_span_id: str,
        trace_id: str,
        session_id: str,
        orden_paso: int,
        etapa: str,
        componente: str,
    ):
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.trace_id = trace_id
        self.session_id = session_id
        self.orden_paso = orden_paso
        self.etapa = etapa
        self.componente = componente
        self.timestamp = datetime.now().isoformat()
        self.duracion_ms = 0.0
        self.estado = "OK"
        self.tokens_in = 0
        self.tokens_out = 0
        self.detalle = ""

    def registrar_tokens(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += int(tokens_in or 0)
        self.tokens_out += int(tokens_out or 0)

    def registrar_detalle(self, detalle: Any) -> None:
        self.detalle = sanitizar_texto(detalle)[:400]

    def marcar_error(self, error: Any) -> None:
        self.estado = "ERROR"
        self.detalle = sanitizar_texto(error)[:400]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "orden_paso": self.orden_paso,
            "etapa": self.etapa,
            "componente": self.componente,
            "duracion_ms": round(self.duracion_ms, 2),
            "estado": self.estado,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "detalle_sanitizado": self.detalle,
        }


class ObservabilidadTracer:

    def __init__(
        self,
        session_id: str,
        consulta_usuario: str,
        logs_dir: str = LOGS_DIR_DEFAULT,
        scenario_id: str = "AD_HOC",
        categoria: str = "Interactivo",
        ambiente: str = "no_especificado",
        consistencia_grupo: str = "N/A",
    ):
        self.logs_dir = logs_dir
        self.trace_id = f"tr-{uuid.uuid4().hex[:12]}"
        self.root_span_id = f"sp-{uuid.uuid4().hex[:10]}"
        self.session_id = session_id
        self.timestamp = datetime.now().isoformat()
        self.scenario_id = scenario_id
        self.categoria = categoria
        self.ambiente = ambiente
        self.consistencia_grupo = consistencia_grupo
        self.consulta_sanitizada = sanitizar_texto(consulta_usuario)[:500]

        self._inicio_ts = time.perf_counter()
        self._orden_actual = 0
        self.spans: List[Dict[str, Any]] = []
        self.eventos: List[Dict[str, Any]] = []

        # Acumuladores de la ejecución
        self.tokens_in = 0
        self.tokens_out = 0
        self.iteraciones_react = 0
        self.tools_usadas: List[str] = []
        self.decision_final = "COMPLETADO"
        self.precision_ok: Optional[bool] = None
        self.tuvo_error = False
        self.tipo_error = "NINGUNO"
        self.uso_fallback = False
        self.bloqueo_seguridad = False

    def registrar_evento(self, nivel: str, etapa: str, mensaje: str, datos: Optional[Dict[str, Any]] = None) -> None:
        datos_limpios = {}
        if datos:
            for k, v in datos.items():
                datos_limpios[k] = sanitizar_texto(v) if isinstance(v, str) else v

        self.eventos.append({
            "timestamp": datetime.now().isoformat(),
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "nivel": nivel,
            "etapa": etapa,
            "mensaje": sanitizar_texto(mensaje),
            "datos": datos_limpios,
        })

    @contextmanager
    def span(self, etapa: str, componente: str, parent_span_id: Optional[str] = None):
        self._orden_actual += 1
        sp = RegistroSpan(
            span_id=f"sp-{uuid.uuid4().hex[:10]}",
            parent_span_id=parent_span_id or self.root_span_id,
            trace_id=self.trace_id,
            session_id=self.session_id,
            orden_paso=self._orden_actual,
            etapa=etapa,
            componente=componente,
        )
        t0 = time.perf_counter()
        try:
            yield sp
        except Exception as exc:
            sp.marcar_error(f"{type(exc).__name__}: {exc}")
            self.tuvo_error = True
            self.tipo_error = type(exc).__name__
            raise
        finally:
            sp.duracion_ms = (time.perf_counter() - t0) * 1000.0
            self.tokens_in += sp.tokens_in
            self.tokens_out += sp.tokens_out
            self.spans.append(sp.to_dict())
            self.registrar_evento(
                nivel="ERROR" if sp.estado == "ERROR" else "INFO",
                etapa=etapa,
                mensaje=f"Span {componente} finalizado ({sp.duracion_ms:.2f} ms)",
                datos={"span_id": sp.span_id, "estado": sp.estado},
            )

    def finalizar_y_guardar(self, precision_ok: Optional[bool] = None) -> Dict[str, Any]:
        latencia_total_ms = round((time.perf_counter() - self._inicio_ts) * 1000.0, 2)
        if precision_ok is not None:
            self.precision_ok = precision_ok

        tokens_total = self.tokens_in + self.tokens_out
        duracion_seg = max(latencia_total_ms / 1000.0, 0.001)
        tokens_por_seg = round(tokens_total / duracion_seg, 2)
        costo_usd = calcular_costo_usd(self.tokens_in, self.tokens_out)
        memoria_mb = obtener_memoria_proceso_mb()

        run_row = {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "scenario_id": self.scenario_id,
            "categoria": self.categoria,
            "ambiente": self.ambiente,
            "consulta_sanitizada": self.consulta_sanitizada,
            "decision_final": self.decision_final,
            "latencia_total_ms": latencia_total_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_total": tokens_total,
            "tokens_por_seg": tokens_por_seg,
            "costo_usd": costo_usd,
            "memoria_mb": memoria_mb,
            "iteraciones_react": self.iteraciones_react,
            "num_tools": len(self.tools_usadas),
            "tools_usadas": " -> ".join(self.tools_usadas) if self.tools_usadas else "NINGUNA",
            "precision_ok": "" if self.precision_ok is None else str(self.precision_ok),
            "consistencia_grupo": self.consistencia_grupo,
            "tuvo_error": str(self.tuvo_error),
            "tipo_error": self.tipo_error,
            "uso_fallback": str(self.uso_fallback),
            "bloqueo_seguridad": str(self.bloqueo_seguridad),
        }

        os.makedirs(self.logs_dir, exist_ok=True)
        self._append_csv(os.path.join(self.logs_dir, "agent_runs.csv"), COLUMNAS_RUNS, [run_row])
        self._append_csv(os.path.join(self.logs_dir, "agent_spans.csv"), COLUMNAS_SPANS, self.spans)
        self._append_jsonl(os.path.join(self.logs_dir, "agent_events.jsonl"), self.eventos)

        return run_row

    @staticmethod
    def _append_csv(ruta: str, columnas: List[str], filas: List[Dict[str, Any]]) -> None:
        if not filas:
            return
        archivo_existe = os.path.exists(ruta) and os.path.getsize(ruta) > 0
        # utf-8-sig agrega BOM para que Power BI / Excel lean acentos correctamente en Windows
        with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=columnas)
            if not archivo_existe:
                writer.writeheader()
            writer.writerows(filas)

    @staticmethod
    def _append_jsonl(ruta: str, eventos: List[Dict[str, Any]]) -> None:
        if not eventos:
            return
        with open(ruta, "a", encoding="utf-8") as f:
            for ev in eventos:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")



# AUTO-PRUEBA RÁPIDA EN CONSOLA

if __name__ == "__main__":
    print("=== PRUEBA MODULO DE OBSERVABILIDAD EP3 ===")
    carpeta_prueba = os.path.join("logs", "demo_test")

    tracer = ObservabilidadTracer(
        session_id="sesion_demo_obs",
        consulta_usuario="Usuario ch.carriel@duocuc.cl reporta OOMKilled con key AIzaSyTestFakeKey123456789012345",
        logs_dir=carpeta_prueba,
        scenario_id="TEST-OBS-01",
        categoria="Prueba Unitaria",
        ambiente="staging",
    )

    with tracer.span("SECURITY", "detectar_prompt_injection") as sp:
        time.sleep(0.02)
        sp.registrar_detalle("Validación OK sin inyección")

    with tracer.span("LLM", "gemini-2.5-flash") as sp:
        time.sleep(0.08)
        sp.registrar_tokens(tokens_in=450, tokens_out=120)
        sp.registrar_detalle("Solicita herramienta consultar_manuales_internos")

    with tracer.span("TOOL", "consultar_manuales_internos") as sp:
        time.sleep(0.04)
        tracer.tools_usadas.append("consultar_manuales_internos")
        sp.registrar_detalle("Recuperado SOP-TI-2026-V1")

    tracer.iteraciones_react = 1
    tracer.decision_final = "RESUELTO_AUTOMATICO"
    resumen = tracer.finalizar_y_guardar(precision_ok=True)

    print("\n[OK] Resumen generado:")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(f"\n[OK] Archivos creados en '{carpeta_prueba}':", os.listdir(carpeta_prueba))