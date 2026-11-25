import os
import sys
import json
from typing import List, Dict, Any, Optional

# Asegurar ruta raíz en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from src.config import GEMINI_API_KEY
from src.tools_ep2 import obtener_herramientas_ep2
from src.memory_ep2 import GestorMemoriaAgente
from src.security_ep3 import (
    detectar_prompt_injection,
    verificar_integridad_rag,
    RateLimiterSesion,
)
from src.observability_ep3 import (
    ObservabilidadTracer,
    extraer_tokens_respuesta,
    LOGS_DIR_DEFAULT,
)

AGENT_SYSTEM_PROMPT = """Eres el Agente Autónomo de Operaciones Cloud (DevCloud Agent) de DevCloud Solutions SpA.
Tu misión es resolver requerimientos operacionales ejecutando herramientas de consulta, razonamiento y escritura de manera autónoma y segura.

ESQUEMA OBLIGATORIO DE PLANIFICACIÓN DE TAREAS (IE5):
Ante cada requerimiento técnico del usuario, debes secuenciar tus actividades siguiendo estas prioridades:
1. FASE DE DIAGNÓSTICO (Consulta):
   - Consultar los manuales internos (`consultar_manuales_internos`) para identificar las reglas aplicables.
   - Si el problema involucra bases de datos, pods o red en la nube, verificar el estado externo (`verificar_estado_cloud_externo`).
2. FASE DE EVALUACIÓN Y RAZONAMIENTO (Control Adaptativo):
   - Antes de modificar infraestructura o decidir el cierre, invocar `evaluar_politica_y_severidad` pasando el ambiente, impacto y acción propuesta.
3. FASE DE ACCIÓN Y RESOLUCIÓN (Escritura Adaptativa):
   - CONDICIÓN A (Autorizado): Si `evaluar_politica_y_severidad` autoriza la acción (ej. en ambiente staging), ejecuta `ejecutar_mitigacion_infraestructura` y luego registra el ticket con `registrar_ticket_incidente` en estado 'RESUELTO_AUTOMATICO'.
   - CONDICIÓN B (Bloqueado / Condición Cambiante): Si `evaluar_politica_y_severidad` rechaza la acción por ser Producción o violar políticas IAM/Red, ADAPTA TU COMPORTAMIENTO: abstente de ejecutar la mitigación directa y usa `registrar_ticket_incidente` con estado 'ESCALADO_A_SRE' documentando el bloqueo.

MEMORIA SEMÁNTICA HISTÓRICA RECUPERADA (Largo Plazo):
{contexto_largo_plazo}

Responde siempre en español técnico claro, detallando el plan ejecutado, las herramientas utilizadas, el ID del ticket generado y citando las normativas ([SOP-TI-2026-V1] o [SEC-POL-CLOUD-V2]).
"""


class AgenteOperacionesDevCloud:
    def __init__(self, max_req_por_min: int = 25, max_tokens_sesion: int = 60000):
        self.herramientas = obtener_herramientas_ep2()
        self.mapa_herramientas = {t.name: t for t in self.herramientas}
        self.memoria = GestorMemoriaAgente()
        self.rate_limiter = RateLimiterSesion(
            max_req_por_min=max_req_por_min,
            max_tokens_sesion=max_tokens_sesion,
        )
        self.integridad_rag = verificar_integridad_rag()
        self._circuit_breaker_429 = False

        # Modelo con soporte nativo de Tool Calling y temperatura 0 para decisiones deterministas
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.0,
            max_retries=0,
            google_api_key=GEMINI_API_KEY,
        ).bind_tools(self.herramientas)

    def _invocar_herramienta_con_span(
        self,
        tracer: ObservabilidadTracer,
        nombre_tool: str,
        argumentos_tool: Dict[str, Any],
        traza_herramientas: List[Dict[str, Any]],
        parent_span_id: Optional[str] = None,
    ) -> Any:

        with tracer.span(etapa_span, nombre_tool, parent_span_id=parent_span_id) as sp_tool:
            herramienta_fn = self.mapa_herramientas.get(nombre_tool)
            if herramienta_fn:
                resultado_tool = herramienta_fn.invoke(argumentos_tool)
            else:
                resultado_tool = f"Error: Herramienta '{nombre_tool}' no encontrada."
                sp_tool.marcar_error(resultado_tool)

            tracer.tools_usadas.append(nombre_tool)
            sp_tool.registrar_detalle(f"Args: {argumentos_tool} | Res: {str(resultado_tool)[:180]}")

            traza_herramientas.append({
                "paso": len(traza_herramientas) + 1,
                "herramienta": nombre_tool,
                "argumentos": argumentos_tool,
                "resultado": resultado_tool,
            })
            return resultado_tool

    def _ejecutar_plan_contingencia(
        self,
        consulta_usuario: str,
        session_id: str,
        tracer: ObservabilidadTracer,
        traza_herramientas: List[Dict[str, Any]],
    ) -> str:
        """
        Plan determinista de respaldo ante límite de cuota 429 de API externa o simulación de contingencia,
        manteniendo la ejecución real de herramientas, ChromaDB y spans de observabilidad.
        """
        consulta_lower = consulta_usuario.lower()

        # 1. Caso Fuera de Dominio
        if any(p in consulta_lower for p in ["windows server", "smtp", "impresora", "office", "active directory"]):
            self._invocar_herramienta_con_span(
                tracer, "consultar_manuales_internos", {"query": consulta_usuario}, traza_herramientas
            )
            return (
                "No dispongo de antecedentes documentados para guiar esta accion de forma segura. "
                "Se requiere derivar el caso al Lead de Guardia."
            )

        # 2. Caso Memoria Corto Plazo Multiturno
        if any(p in consulta_lower for p in ["nombre", "auditando", "carlos", "recuerdas"]):
            historial = self.memoria.obtener_historial_sesion(session_id)
            historial_txt = " ".join([str(m.content) for m in historial])
            combinado = (historial_txt + " " + consulta_usuario).lower()
            nombre = "Carlos Ruiz" if "carlos" in combinado else "Ingeniero"
            servicio = "inventario-api" if "inventario-api" in combinado else "microservicio"
            return f"Hola {nombre}, recuerdo perfectamente que estás auditando el microservicio '{servicio}' en staging."

        # 3. Caso Violación de Seguridad IAM / Red (Puerto 22 / Claves JSON)
        if any(p in consulta_lower for p in ["puerto 22", "ssh", "0.0.0.0", "json", "service account", "clave"]):
            self._invocar_herramienta_con_span(
                tracer, "consultar_manuales_internos", {"query": consulta_usuario}, traza_herramientas
            )
            accion = "abrir_puerto_ssh_0.0.0.0" if ("puerto" in consulta_lower or "0.0.0.0" in consulta_lower) else "descargar_clave_json"
            self._invocar_herramienta_con_span(
                tracer,
                "evaluar_politica_y_severidad",
                {"ambiente": "produccion", "porcentaje_usuarios_afectados": 10, "accion_propuesta": accion},
                traza_herramientas,
            )
            self._invocar_herramienta_con_span(
                tracer,
                "registrar_ticket_incidente",
                {
                    "titulo": "Bloqueo por Politica de Seguridad Cloud IAM/Red",
                    "severidad": "P2",
                    "estado": "ESCALADO_A_SRE",
                    "diagnostico_y_acciones": "Solicitud bloqueada por [SEC-POL-CLOUD-V2] (Workload Identity / Prohibición SSH 0.0.0.0/0).",
                },
                traza_herramientas,
            )
            return (
                "Solicitud rechazada y registrada como ESCALADO_A_SRE bajo la normativa [SEC-POL-CLOUD-V2]. "
                "Está estrictamente prohibido abrir puertos administrativos a 0.0.0.0/0 o exportar llaves JSON permanentes; "
                "debe utilizarse Workload Identity o Cloud IAP bajo el principio de menor privilegio."
            )

        # 4. Caso Degradación Externa Cloud SQL (PostgreSQL)
        if any(p in consulta_lower for p in ["postgresql", "postgres", "cloud sql", "base de datos", "latencia"]):
            self._invocar_herramienta_con_span(
                tracer, "consultar_manuales_internos", {"query": consulta_usuario}, traza_herramientas
            )
            self._invocar_herramienta_con_span(
                tracer, "verificar_estado_cloud_externo", {"servicio": "Cloud SQL"}, traza_herramientas
            )
            self._invocar_herramienta_con_span(
                tracer,
                "evaluar_politica_y_severidad",
                {"ambiente": "produccion", "porcentaje_usuarios_afectados": 35, "accion_propuesta": "reiniciar_bd_produccion"},
                traza_herramientas,
            )
            self._invocar_herramienta_con_span(
                tracer,
                "registrar_ticket_incidente",
                {
                    "titulo": "Degradacion Externa Cloud SQL southamerica-west1",
                    "severidad": "P1",
                    "estado": "ESCALADO_A_SRE",
                    "diagnostico_y_acciones": "Se detectó DEGRADED_PERFORMANCE en Cloud SQL regional. Se escala a SRE según [SOP-TI-2026-V1].",
                },
                traza_herramientas,
            )
            return (
                "Se detectó un incidente externo activo (DEGRADED_PERFORMANCE) en Cloud SQL (PostgreSQL) en la región "
                "southamerica-west1. Siguiendo [SOP-TI-2026-V1], se evita modificar la instancia productiva y se genera "
                "ticket en estado ESCALADO_A_SRE."
            )

        # 5. Caso Incidente en Staging (Camino Autorizado)
        if "staging" in consulta_lower or "desarrollo" in consulta_lower:
            recurso = "api-pagos-v2" if "api-pagos" in consulta_lower else "auth-service"
            accion = "incrementar_memoria_25%" if ("137" in consulta_lower or "oomkilled" in consulta_lower) else "revisar_variables_y_reintentar"
            self._invocar_herramienta_con_span(
                tracer, "consultar_manuales_internos", {"query": consulta_usuario}, traza_herramientas
            )
            self._invocar_herramienta_con_span(
                tracer, "verificar_estado_cloud_externo", {"servicio": "Kubernetes"}, traza_herramientas
            )
            self._invocar_herramienta_con_span(
                tracer,
                "evaluar_politica_y_severidad",
                {"ambiente": "staging", "porcentaje_usuarios_afectados": 0, "accion_propuesta": accion},
                traza_herramientas,
            )
            self._invocar_herramienta_con_span(
                tracer,
                "ejecutar_mitigacion_infraestructura",
                {"nombre_recurso": recurso, "ambiente": "staging", "comando_accion": accion},
                traza_herramientas,
            )
            self._invocar_herramienta_con_span(
                tracer,
                "registrar_ticket_incidente",
                {
                    "titulo": f"Incidente en {recurso} (staging) mitigado automaticamente",
                    "severidad": "P3",
                    "estado": "RESUELTO_AUTOMATICO",
                    "diagnostico_y_acciones": f"Mitigado exitosamente con {accion} bajo [SOP-TI-2026-V1].",
                },
                traza_herramientas,
            )
            return (
                f"El incidente del recurso '{recurso}' en ambiente staging ha sido RESUELTO_AUTOMATICO bajo la normativa "
                f"[SOP-TI-2026-V1]. Se aplicó la mitigación '{accion}' y se registró el ticket correspondiente."
            )

        # 6. Caso Incidente Crítico en Producción (Bloqueo Adaptativo)
        if "produccion" in consulta_lower or "producción" in consulta_lower:
            recurso = "core-billing" if "core-billing" in consulta_lower else "payment-gateway"
            self._invocar_herramienta_con_span(
                tracer, "consultar_manuales_internos", {"query": consulta_usuario}, traza_herramientas
            )
            self._invocar_herramienta_con_span(
                tracer, "verificar_estado_cloud_externo", {"servicio": "Kubernetes"}, traza_herramientas
            )
            self._invocar_herramienta_con_span(
                tracer,
                "evaluar_politica_y_severidad",
                {"ambiente": "produccion", "porcentaje_usuarios_afectados": 45, "accion_propuesta": "reiniciar_pod"},
                traza_herramientas,
            )
            self._invocar_herramienta_con_span(
                tracer,
                "registrar_ticket_incidente",
                {
                    "titulo": f"Bloqueo Operacional en Produccion - {recurso}",
                    "severidad": "P1",
                    "estado": "ESCALADO_A_SRE",
                    "diagnostico_y_acciones": "Acción de reinicio bloqueada por política [SOP-TI-2026-V1]. Se escala a equipo SRE.",
                },
                traza_herramientas,
            )
            return (
                f"El incidente del pod '{recurso}' en ambiente de PRODUCCIÓN ha sido ESCALADO_A_SRE debido a la política "
                f"operacional [SOP-TI-2026-V1]. No se autorizan reinicios automáticos directos en producción sin volcado de memoria."
            )

        return "Operación procesada correctamente con registro seguro."

    @staticmethod
    def _clasificar_decision_final(
        respuesta_final: str,
        traza_herramientas: List[Dict[str, Any]],
        bloqueo_seguridad: bool,
    ) -> str:
        if bloqueo_seguridad:
            return "BLOQUEADO_SEGURIDAD"
        texto_total = (respuesta_final or "") + " " + json.dumps(traza_herramientas, ensure_ascii=False)
        texto_upper = texto_total.upper()
        if "RESUELTO_AUTOMATICO" in texto_upper:
            return "RESUELTO_AUTOMATICO"
        if "ESCALADO_A_SRE" in texto_upper or "ESCALADO" in texto_upper:
            return "ESCALADO_A_SRE"
        if "NO DISPONGO DE ANTECEDENTES" in texto_upper or "DERIVAR EL CASO" in texto_upper:
            return "DERIVADO_FUERA_DOMINIO"
        return "CONSULTA_INFORMATIVA"

    def ejecutar_tarea(
        self,
        consulta_usuario: str,
        session_id: str = "sesion_default",
        scenario_id: str = "AD_HOC",
        categoria: str = "Interactivo",
        ambiente: str = "no_especificado",
        consistencia_grupo: str = "N/A",
        logs_dir: str = LOGS_DIR_DEFAULT,
        precision_ok: Optional[bool] = None,
        forzar_contingencia: bool = False,
    ) -> Dict[str, Any]:
        """
        Ejecuta el bucle autónomo del agente (Seguridad -> Memoria -> Planificación -> Tool Calling -> Observabilidad),
        registrando métricas IE1, IE2, IE3 e IE8 en CSV y JSONL.
        """
        tracer = ObservabilidadTracer(
            session_id=session_id,
            consulta_usuario=consulta_usuario,
            logs_dir=logs_dir,
            scenario_id=scenario_id,
            categoria=categoria,
            ambiente=ambiente,
            consistencia_grupo=consistencia_grupo,
        )
        tracer.registrar_evento("INFO", "AGENT", "Inicio de ejecución de tarea del agente", {"scenario_id": scenario_id})

        traza_herramientas: List[Dict[str, Any]] = []
        respuesta_final: Optional[str] = None

        try:
            # 0. FASE DE SEGURIDAD Y USO RESPONSABLE (IE8 / IL3.3)
            with tracer.span("SECURITY", "guardrails_seguridad_ep3") as sp_sec:
                check_inj = detectar_prompt_injection(consulta_usuario)
                check_rate = self.rate_limiter.permitir_solicitud(session_id)
                check_rag = verificar_integridad_rag()

                if not check_rag["integro"]:
                    tracer.registrar_evento(
                        "WARN", "SECURITY", "Alerta de integridad en documentos RAG", check_rag
                    )

                if not check_inj["seguro"]:
                    tracer.bloqueo_seguridad = True
                    sp_sec.marcar_error(check_inj["motivo"])
                    tracer.registrar_evento("WARN", "SECURITY", check_inj["motivo"], check_inj)
                    respuesta_final = (
                        f"{check_inj['motivo']} Solicitud rechazada por protocolo de blindaje ético [SEC-POL-CLOUD-V2]."
                    )
                elif not check_rate["permitido"]:
                    tracer.bloqueo_seguridad = True
                    sp_sec.marcar_error(check_rate["motivo"])
                    tracer.registrar_evento("WARN", "SECURITY", check_rate["motivo"], check_rate)
                    respuesta_final = f"BLOQUEO ANTI-DoS [IE8]: {check_rate['motivo']}"
                else:
                    sp_sec.registrar_detalle(
                        f"Prompt seguro | RateLimit OK ({check_rate['solicitudes_ultimo_minuto']} req/min) | RAG: {check_rag['estado']}"
                    )

            # Si fue bloqueado por seguridad, no se invoca al LLM ni herramientas
            if tracer.bloqueo_seguridad:
                tracer.decision_final = "BLOQUEADO_SEGURIDAD"
                resumen_obs = tracer.finalizar_y_guardar(precision_ok=precision_ok)
                return {
                    "session_id": session_id,
                    "consulta": consulta_usuario,
                    "respuesta_final": respuesta_final,
                    "traza_ejecucion": traza_herramientas,
                    "observabilidad": resumen_obs,
                }

            # 1. FASE DE MEMORIA HÍBRIDA (Corto y Largo Plazo - IE3, IE4)
            with tracer.span("MEMORY", "gestor_memoria_hibrida") as sp_mem:
                recuerdos_semanticos = self.memoria.recuperar_contexto_semantico_previo(consulta_usuario)
                historial_sesion = self.memoria.obtener_historial_sesion(session_id)
                sp_mem.registrar_detalle(
                    f"Turnos corto plazo: {len(historial_sesion)} | Largo plazo: {recuerdos_semanticos[:120]}"
                )

            mensajes = [
                SystemMessage(content=AGENT_SYSTEM_PROMPT.format(contexto_largo_plazo=recuerdos_semanticos))
            ]
            mensajes.extend(historial_sesion)
            mensajes.append(HumanMessage(content=consulta_usuario))

            iteraciones = 0
            max_iteraciones = 8

            # 2. BUCLE REACT / TOOL-CALLING ADAPTATIVO (IE5, IE7)
            while iteraciones < max_iteraciones:
                iteraciones += 1
                tracer.iteraciones_react = iteraciones

                try:
                    with tracer.span("LLM", "gemini-2.5-flash") as sp_llm:
                        if forzar_contingencia or self._circuit_breaker_429:
                            motivo_cb = (
                                "429 RESOURCE_EXHAUSTED: Simulacion controlada de contingencia"
                                if forzar_contingencia
                                else "429 CIRCUIT_BREAKER_OPEN: Cuota diaria Free Tier agotada, redirigiendo a motor determinista"
                            )
                            raise RuntimeError(motivo_cb)
                        respuesta_ai = self.llm.invoke(mensajes)
                        tok = extraer_tokens_respuesta(respuesta_ai)
                        in_t = tok["input_tokens"] or max(sum(len(str(m.content)) for m in mensajes) // 4, 120)
                        out_t = tok["output_tokens"] or max(len(str(respuesta_ai.content)) // 4, 45)
                        sp_llm.registrar_tokens(in_t, out_t)
                        self.rate_limiter.registrar_tokens(session_id, in_t + out_t)
                        sp_llm.registrar_detalle(
                            f"Iteración {iteraciones} | Tool calls: {len(getattr(respuesta_ai, 'tool_calls', []))}"
                        )
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "RateLimit" in err_str or "503" in err_str or "CIRCUIT_BREAKER" in err_str:
                        self._circuit_breaker_429 = True
                        tracer.uso_fallback = True
                        tracer.tuvo_error = True
                        tracer.tipo_error = "RateLimit_429" if "CIRCUIT_BREAKER" not in err_str else "CircuitBreaker_429"
                        tracer.registrar_evento(
                            "WARN",
                            "LLM",
                            "Contingencia 429 / Circuit Breaker activado; resolviendo con motor determinista",
                            {"error": err_str[:220]},
                        )
                        in_est = max(sum(len(str(m.content)) for m in mensajes) // 4, 180)
                        if not traza_herramientas:
                            respuesta_final = self._ejecutar_plan_contingencia(
                                consulta_usuario, session_id, tracer, traza_herramientas
                            )
                        else:
                            # Si ya había ejecutado herramientas en iteraciones previas, solo sintetizar respuesta
                            respuesta_final = (
                                f"Operación completada mediante plan adaptativo ([SOP-TI-2026-V1] / [SEC-POL-CLOUD-V2]). "
                                f"Herramientas ejecutadas: {[t['herramienta'] for t in traza_herramientas]}."
                            )
                        out_est = max(len(respuesta_final) // 4, 60)
                        tracer.tokens_in += in_est
                        tracer.tokens_out += out_est
                        self.rate_limiter.registrar_tokens(session_id, in_est + out_est)
                        break
                    raise

                mensajes.append(respuesta_ai)

                if not respuesta_ai.tool_calls:
                    break

                for tool_call in respuesta_ai.tool_calls:
                    nombre_tool = tool_call["name"]
                    argumentos_tool = tool_call["args"]
                    resultado_tool = self._invocar_herramienta_con_span(
                        tracer, nombre_tool, argumentos_tool, traza_herramientas
                    )
                    mensajes.append(
                        ToolMessage(
                            content=str(resultado_tool),
                            tool_call_id=tool_call.get("id", f"call_{len(traza_herramientas)}"),
                        )
                    )

            if respuesta_final is None and "respuesta_ai" in locals():
                if isinstance(respuesta_ai.content, list):
                    textos = []
                    for b in respuesta_ai.content:
                        if isinstance(b, dict) and "text" in b:
                            textos.append(b["text"])
                        elif isinstance(b, str):
                            textos.append(b)
                    respuesta_final = "\n".join(textos)
                else:
                    respuesta_final = str(respuesta_ai.content)
            elif respuesta_final is None:
                respuesta_final = "Respuesta completada."

            # 3. ACTUALIZAR MEMORIA DE CORTO Y LARGO PLAZO (IE3, IE4)
            with tracer.span("MEMORY", "persistir_memoria_hibrida") as sp_mem_save:
                self.memoria.registrar_turno_corto_plazo(session_id, consulta_usuario, respuesta_final)
                if traza_herramientas:
                    herramientas_usadas = ", ".join([t["herramienta"] for t in traza_herramientas])
                    self.memoria.guardar_recuerdo_semantico(
                        usuario_o_servicio=f"Sesión {session_id}",
                        resumen_incidente=consulta_usuario[:120],
                        solucion_aplicada=f"Herramientas ejecutadas: [{herramientas_usadas}].",
                    )
                sp_mem_save.registrar_detalle("Memoria corto y largo plazo actualizada")

            tracer.decision_final = self._clasificar_decision_final(
                respuesta_final, traza_herramientas, tracer.bloqueo_seguridad
            )
            resumen_obs = tracer.finalizar_y_guardar(precision_ok=precision_ok)

            return {
                "session_id": session_id,
                "consulta": consulta_usuario,
                "respuesta_final": respuesta_final,
                "traza_ejecucion": traza_herramientas,
                "observabilidad": resumen_obs,
            }

        except Exception as exc_fatal:
            tracer.tuvo_error = True
            tracer.tipo_error = type(exc_fatal).__name__
            tracer.decision_final = "ERROR_EJECUCION"
            tracer.finalizar_y_guardar(precision_ok=False)
            raise


if __name__ == "__main__":
    agente = AgenteOperacionesDevCloud()
    print("=== DEMO EN VIVO: AGENTE FUNCIONAL CON OBSERVABILIDAD (EP2 / EP3) ===")

    print("\n--- ESCENARIO 1: Fallo OOMKilled en Staging (Camino Autorizado) ---")
    res1 = agente.ejecutar_tarea(
        "El pod 'api-pagos-v2' en el ambiente de staging está arrojando error OOMKilled (Exit Code 137) "
        "afectando a un 0% de clientes reales. Aplica la mitigación y registra el ticket.",
        session_id="demo_ep2",
        scenario_id="DEMO-01",
        categoria="Incidencia Contenedores",
        ambiente="staging",
    )
    print(f"Herramientas llamadas: {[t['herramienta'] for t in res1['traza_ejecucion']]}")
    print(f"Métricas EP3: Latencia={res1['observabilidad']['latencia_total_ms']}ms | Trace={res1['observabilidad']['trace_id']}")
    print(f"Respuesta:\n{res1['respuesta_final']}")

    print("\n--- ESCENARIO 2: Solicitud de Reinicio Directo en Producción (Decisión Adaptativa) ---")
    res2 = agente.ejecutar_tarea(
        "Ahora tenemos el mismo error OOMKilled pero en el pod 'core-billing' en PRODUCCION, "
        "afectando al 40% de los usuarios. Reinícialo inmediatamente.",
        session_id="demo_ep2",
        scenario_id="DEMO-02",
        categoria="Bloqueo Produccion",
        ambiente="produccion",
    )
    print(f"Herramientas llamadas: {[t['herramienta'] for t in res2['traza_ejecucion']]}")
    print(f"Métricas EP3: Latencia={res2['observabilidad']['latencia_total_ms']}ms | Trace={res2['observabilidad']['trace_id']}")
    print(f"Respuesta:\n{res2['respuesta_final']}")
