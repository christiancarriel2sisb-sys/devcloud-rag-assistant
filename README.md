# ☁️ DevCloud Agent: Agente Autónomo con Observabilidad, Trazabilidad y Blindaje Ético (EP1 - EP2 - EP3)

**Asignatura:** ISY0101 - Ingeniería de Soluciones con IA (Duoc UC)  
**Evaluaciones Cubiertas:** Parcial N°1 (RAG Híbrido), Parcial N°2 (Agente Autónomo ReAct) y Parcial N°3 (Observabilidad, Trazabilidad OpenInference, Seguridad y Dashboard Power BI)  
**Caso Organizacional:** DevCloud Solutions SpA  

## 📌 Descripción del Proyecto
Este repositorio contiene la implementación integral de **DevCloud Agent**, un agente autónomo de operaciones Cloud y soporte TI diseñado para diagnosticar incidentes de infraestructura, evaluar políticas de seguridad de forma determinista, aplicar mitigaciones controladas y exportar telemetría completa para monitoreo en **Power BI**.

En su **Fase EP3**, el sistema incorpora los **tres pilares de la observabilidad** (Logs estructurados en JSONL, Métricas de rendimiento/calidad/costos y Trazas distribuidas Padre-Hijo estilo *OpenInference*), junto con una capa de **seguridad y uso responsable en producción** (detección de *Prompt Injection*, sanitización de PII/secretos, verificación criptográfica SHA-256 anti-*Data Poisoning* en RAG y *Rate Limiting* anti-DoS).

---

## 🏗️ Arquitectura de Componentes

* **Orquestador Instrumentado (`src/agent_ep2.py`):** Controla el flujo ReAct, integra los guardrails de seguridad pre-LLM y envuelve cada operación en *Spans* jerárquicos (`SECURITY`, `MEMORY`, `LLM`, `RETRIEVER`, `TOOL`).
* **Módulo de Observabilidad y Trazabilidad (`src/observability_ep3.py`):**
  * Genera identificadores correlacionados (`session_id` $\rightarrow$ `trace_id` $\rightarrow$ `root_span_id` / `span_id`).
  * Mide latencia por etapa en milisegundos, consumo de tokens (`input`, `output`, `total`), *throughput* (`tokens/s`), costo estimado en USD y uso de memoria RAM (`psutil`).
  * Exporta automáticamente **`logs/agent_runs.csv`**, **`logs/agent_spans.csv`** (optimizados con UTF-8 BOM para Power BI) y **`logs/agent_events.jsonl`**.
* **Módulo de Seguridad y Ética Digital (`src/security_ep3.py`):**
  * `detectar_prompt_injection`: Bloquea intentos de manipulación o extracción de prompts antes de invocar al LLM.
  * `sanitizar_texto`: Enmascara correos, RUTs, IPs y API Keys (`[EMAIL_REDACTED]`, `[RUT_REDACTED]`, `[IP_REDACTED]`, `[API_KEY_REDACTED]`).
  * `verificar_integridad_rag`: Valida hashes **SHA-256** (`data/rag_integrity.json`) de los manuales internos contra *Data Poisoning*.
  * `RateLimiterSesion`: Previene ataques DoS por agotamiento de tokens o ráfagas de consultas.
* **Herramientas Tipadas (`src/tools_ep2.py`):** Consulta RAG/API Cloud, razonamiento determinista de SLAs/políticas y escritura auditable en `data/tickets_db.json`.
* **Gestor de Memoria Híbrida (`src/memory_ep2.py`):** Memoria de corto plazo en RAM y memoria episódica semántica de largo plazo en ChromaDB (`data/long_term_memory_db/`).

---

## 🚀 Instalación y Configuración

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar variables de entorno en .env
GEMINI_API_KEY=tu_api_key_aqui
OPENAI_API_KEY=tu_api_key_aqui
CHROMA_PERSIST_DIRECTORY=data/vector_store
```

---

## ▶️ Instrucciones de Ejecución y Pruebas (EP1, EP2 y EP3)

### Paso 1: Indexar la Base de Conocimiento Interna (ChromaDB)
```bash
python -m src.ingestion
```

### Paso 2: Ejecutar la Batería de Evaluación de Observabilidad (EP3)
Ejecuta los **12 escenarios con variabilidad de datos** (`data/scenarios_ep3.json`), incluyendo casos en Staging, bloqueos en Producción, correlación Cloud SQL, políticas IAM/Firewall, grupos de consistencia semántica, ataques de *Prompt Injection* y estrés/contingencia `429`:
```bash
python run_eval_ep3.py
```
Al finalizar, se actualizan los archivos listos para **Power BI**:
* `logs/agent_runs.csv` (Tabla maestra de ejecuciones)
* `logs/agent_spans.csv` (Tabla detalle de Spans por etapa)
* `logs/agent_events.jsonl` (Logs estructurados sanitizados)
* `logs/resumen_metricas_ep3.json` (Resumen de KPIs IE1, IE2, IE3 e IE8)

### Paso 3: Ejecutar la Suite Completa de Pruebas Automatizadas (Pytest)
```bash
# Pruebas unitarias y de integración de Observabilidad y Seguridad (EP3)
python -m pytest tests/test_observability_ep3.py -v

# Pruebas del Agente Autónomo (EP2) y Pipeline RAG (EP1)
python -m pytest tests/ -v
```

### Paso 4: Visualizar el Dashboard en Power BI
1. Abre **Power BI Desktop** $\rightarrow$ **Obtener datos** $\rightarrow$ **Texto o CSV** y carga `logs/agent_runs.csv` y `logs/agent_spans.csv`.
2. Verifica la relación `1:*` por `trace_id` en la Vista de Modelo (o abre directamente `ing ia.pbix`).

---

## 👥 Autores
* **Christian Carriel Aldas**
* **Vicente Silva**
