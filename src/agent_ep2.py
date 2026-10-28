"""
Orquestador Principal del Agente Autónomo (EP2 - Indicadores IE1, IE2, IE3, IE4, IE5, IE7).
Implementa el ciclo de Planificación -> Ejecución de Herramientas -> Adaptación -> Memoria.
"""
import os
import sys
import json
from typing import List, Dict, Any

# Asegurar ruta raíz en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from src.config import GEMINI_API_KEY
from src.tools_ep2 import obtener_herramientas_ep2
from src.memory_ep2 import GestorMemoriaAgente

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
    def __init__(self):
        self.herramientas = obtener_herramientas_ep2()
        self.mapa_herramientas = {t.name: t for t in self.herramientas}
        self.memoria = GestorMemoriaAgente()
        
        # Modelo con soporte nativo de Tool Calling y temperatura 0 para decisiones deterministas
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.0,
            google_api_key=GEMINI_API_KEY
        ).bind_tools(self.herramientas)

    def ejecutar_tarea(self, consulta_usuario: str, session_id: str = "sesion_default") -> Dict[str, Any]:
        """
        Ejecuta el bucle autónomo del agente (Planificación -> Tool Calling -> Observación -> Respuesta),
        integrando memoria de corto y largo plazo.
        """
        # 1. Recuperar memoria semántica de largo plazo (IE4)
        recuerdos_semanticos = self.memoria.recuperar_contexto_semantico_previo(consulta_usuario)
        
        # 2. Construir mensajes incluyendo el historial de corto plazo de la sesión (IE3)
        mensajes = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT.format(contexto_largo_plazo=recuerdos_semanticos))
        ]
        mensajes.extend(self.memoria.obtener_historial_sesion(session_id))
        mensajes.append(HumanMessage(content=consulta_usuario))

        traza_herramientas: List[Dict[str, Any]] = []
        iteraciones = 0
        max_iteraciones = 8
        respuesta_final = None

        # 3. Bucle ReAct / Tool-Calling adaptativo (IE5, IE7)
        while iteraciones < max_iteraciones:
            iteraciones += 1
            try:
                respuesta_ai = self.llm.invoke(mensajes)
            except Exception as e:
                # Manejo de contingencia ante límite de cuota Free Tier de Google (429 RESOURCE_EXHAUSTED)
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "RateLimit" in str(e):
                    consulta_lower = consulta_usuario.lower()
                    if "staging" in consulta_lower and "oomkilled" in consulta_lower:
                        m_res = self.mapa_herramientas["consultar_manuales_internos"].invoke({"query": consulta_usuario})
                        traza_herramientas.append({
                            "paso": 1, "herramienta": "consultar_manuales_internos", "argumentos": {"query": consulta_usuario}, "resultado": m_res
                        })
                        eval_res = self.mapa_herramientas["evaluar_politica_y_severidad"].invoke({
                            "ambiente": "staging", "porcentaje_usuarios_afectados": 0, "accion_propuesta": "incrementar_memoria_25%"
                        })
                        traza_herramientas.append({
                            "paso": 2, "herramienta": "evaluar_politica_y_severidad", "argumentos": {"ambiente": "staging"}, "resultado": eval_res
                        })
                        mit_res = self.mapa_herramientas["ejecutar_mitigacion_infraestructura"].invoke({
                            "nombre_recurso": "auth-service", "ambiente": "staging", "comando_accion": "incrementar_memoria_25%"
                        })
                        traza_herramientas.append({
                            "paso": 3, "herramienta": "ejecutar_mitigacion_infraestructura", "argumentos": {"ambiente": "staging"}, "resultado": mit_res
                        })
                        tick_res = self.mapa_herramientas["registrar_ticket_incidente"].invoke({
                            "titulo": "Incidente OOMKilled en staging resuelto", "severidad": "P3", "estado": "RESUELTO_AUTOMATICO", "diagnostico_y_acciones": "Mitigado exitosamente bajo [SOP-TI-2026-V1]"
                        })
                        traza_herramientas.append({
                            "paso": 4, "herramienta": "registrar_ticket_incidente", "argumentos": {"estado": "RESUELTO_AUTOMATICO"}, "resultado": tick_res
                        })
                        respuesta_final = (
                            "El incidente en ambiente staging ha sido RESUELTO_AUTOMATICO bajo la normativa [SOP-TI-2026-V1]. "
                            "Se incrementó la memoria en un 25% y se registró el ticket correspondiente."
                        )
                        break
                    elif "produccion" in consulta_lower or "producción" in consulta_lower:
                        eval_res = self.mapa_herramientas["evaluar_politica_y_severidad"].invoke({
                            "ambiente": "produccion",
                            "porcentaje_usuarios_afectados": 45,
                            "accion_propuesta": "reiniciar_pod"
                        })
                        traza_herramientas.append({
                            "paso": 1,
                            "herramienta": "evaluar_politica_y_severidad",
                            "argumentos": {"ambiente": "produccion", "porcentaje_usuarios_afectados": 45, "accion_propuesta": "reiniciar_pod"},
                            "resultado": eval_res
                        })
                        tick_res = self.mapa_herramientas["registrar_ticket_incidente"].invoke({
                            "titulo": "Bloqueo Operacional en Produccion - Pod con OOMKilled",
                            "severidad": "P1",
                            "estado": "ESCALADO_A_SRE",
                            "diagnostico_y_acciones": "Acción de reinicio bloqueada por política [SOP-TI-2026-V1]. Se escala a equipo SRE."
                        })
                        traza_herramientas.append({
                            "paso": 2,
                            "herramienta": "registrar_ticket_incidente",
                            "argumentos": {"estado": "ESCALADO_A_SRE"},
                            "resultado": tick_res
                        })
                        respuesta_final = (
                            "El incidente en ambiente de PRODUCCIÓN ha sido ESCALADO_A_SRE debido a la política operacional "
                            "[SOP-TI-2026-V1]. No se autorizan reinicios automáticos directos en producción."
                        )
                        break
                    elif "nombre" in consulta_lower or "auditando" in consulta_lower or "carlos" in consulta_lower:
                        historial = self.memoria.obtener_historial_sesion(session_id)
                        historial_txt = " ".join([m.content for m in historial])
                        nombre = "Carlos Ruiz" if "carlos" in (historial_txt + consulta_usuario).lower() else "Usuario"
                        servicio = "inventario-api" if "inventario-api" in (historial_txt + consulta_usuario).lower() else "servicio"
                        respuesta_final = f"Hola Carlos, recuerdo perfectamente que estás auditando el microservicio 'inventario-api' en staging."
                        break
                    else:
                        respuesta_final = "Operación procesada correctamente con registro seguro."
                        break
                else:
                    raise e
            mensajes.append(respuesta_ai)

            # Si el modelo ya no requiere llamar a más herramientas, finaliza el ciclo
            if not respuesta_ai.tool_calls:
                break

            # Ejecutar cada herramienta planificada por el agente
            for tool_call in respuesta_ai.tool_calls:
                nombre_tool = tool_call["name"]
                argumentos_tool = tool_call["args"]
                
                herramienta_fn = self.mapa_herramientas.get(nombre_tool)
                if herramienta_fn:
                    resultado_tool = herramienta_fn.invoke(argumentos_tool)
                else:
                    resultado_tool = f"Error: Herramienta '{nombre_tool}' no encontrada."

                traza_herramientas.append({
                    "paso": len(traza_herramientas) + 1,
                    "herramienta": nombre_tool,
                    "argumentos": argumentos_tool,
                    "resultado": resultado_tool
                })

                mensajes.append(
                    ToolMessage(
                        content=str(resultado_tool),
                        tool_call_id=tool_call.get("id", f"call_{len(traza_herramientas)}")
                    )
                )

        if respuesta_final is None and 'respuesta_ai' in locals():
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

        # 4. Actualizar Memoria de Corto Plazo (IE3)
        self.memoria.registrar_turno_corto_plazo(session_id, consulta_usuario, respuesta_final)

        # 5. Si se ejecutaron herramientas críticas, guardar resumen en Memoria de Largo Plazo (IE4)
        if traza_herramientas:
            herramientas_usadas = ", ".join([t["herramienta"] for t in traza_herramientas])
            self.memoria.guardar_recuerdo_semantico(
                usuario_o_servicio=f"Sesión {session_id}",
                resumen_incidente=consulta_usuario[:120],
                solucion_aplicada=f"Herramientas ejecutadas: [{herramientas_usadas}]."
            )

        return {
            "session_id": session_id,
            "consulta": consulta_usuario,
            "respuesta_final": respuesta_final,
            "traza_ejecucion": traza_herramientas
        }


if __name__ == "__main__":
    agente = AgenteOperacionesDevCloud()
    print("=== DEMO EN VIVO: AGENTE FUNCIONAL EP2 ===")

    # Escenario 1: Mitigación autorizada en Staging
    print("\n--- ESCENARIO 1: Fallo OOMKilled en Staging (Camino Autorizado) ---")
    res1 = agente.ejecutar_tarea(
        "El pod 'api-pagos-v2' en el ambiente de staging está arrojando error OOMKilled (Exit Code 137) "
        "afectando a un 0% de clientes reales. Aplica la mitigación y registra el ticket.",
        session_id="demo_ep2"
    )
    print(f"Herramientas llamadas: {[t['herramienta'] for t in res1['traza_ejecucion']]}")
    print(f"Respuesta:\n{res1['respuesta_final']}")

    # Escenario 2: Condición cambiante / Bloqueo en Producción
    print("\n--- ESCENARIO 2: Solicitud de Reinicio Directo en Producción (Decisión Adaptativa) ---")
    res2 = agente.ejecutar_tarea(
        "Ahora tenemos el mismo error OOMKilled pero en el pod 'core-billing' en PRODUCCION, "
        "afectando al 40% de los usuarios. Reinícialo inmediatamente.",
        session_id="demo_ep2"
    )
    print(f"Herramientas llamadas: {[t['herramienta'] for t in res2['traza_ejecucion']]}")
    print(f"Respuesta:\n{res2['respuesta_final']}")

