# ☁️ DevCloud Agent: Agente Autónomo para Operaciones Cloud y Mesa de Ayuda TI

**Asignatura:** ISY0101 - Ingeniería de Soluciones con IA (Duoc UC)  
**Evaluación:** Parcial N°2 (EP2)  

## 📌 Descripción del Proyecto
Este repositorio contiene la implementación de **DevCloud Agent**, un agente autónomo basado en IA diseñado para resolver incidentes de infraestructura, evaluar políticas de seguridad de forma determinista y aplicar mitigaciones en la nube (ej. Kubernetes, PostgreSQL). 

El agente utiliza un bucle **ReAct (Reason + Act)** con *Tool Calling* estricto (Pydantic), y cuenta con una arquitectura de **Memoria Híbrida** (corto plazo en sesión y largo plazo semántica) para mantener coherencia en flujos operacionales complejos sin alucinaciones.

---

## 🏗️ Arquitectura de Componentes

El proyecto está modularizado en los siguientes componentes principales:
*   **Orquestador (`src/agent_ep2.py`):** Controla el flujo ReAct, planifica tareas y gestiona la toma de decisiones.
*   **Herramientas Tipadas (`src/tools_ep2.py`):** 
    *   *Consulta:* RAG Interno (ChromaDB) y Mock API Externa.
    *   *Razonamiento:* Motor determinista que evalúa SLAs (P1/P2/P3) y políticas (bloqueo en producción).
    *   *Escritura:* Ejecución de mitigaciones y persistencia de auditoría en `data/tickets_db.json`.
*   **Gestor de Memoria (`src/memory_ep2.py`):** Mantiene el historial de la sesión (corto plazo) y un registro episódico vectorial (largo plazo en `data/long_term_memory_db/`).

---

## ⚙️ Requisitos Previos

*   **Python:** 3.10 o superior.
*   **Clave API:** Una API Key de OpenAI u otro proveedor configurado en LangChain.

---

## 🚀 Instalación y Configuración

Sigue estos pasos para clonar y preparar el entorno de ejecución:

**1. Clonar el repositorio**
```bash
git clone https://github.com/TU_USUARIO/devcloud-rag-assistant.git
cd devcloud-rag-assistant
```

**2. Crear y activar el entorno virtual**
```bash
python -m venv .venv

# En Windows (PowerShell):
.venv\Scripts\Activate.ps1

# En macOS/Linux o Git Bash:
source .venv/bin/activate
```

**3. Instalar dependencias**
```bash
pip install -r requirements.txt
```

**4. Configurar variables de entorno**
Crea un archivo llamado `.env` en la raíz del proyecto y agrega tu clave de OpenAI y la ruta de la base de datos vectorial:
```env
OPENAI_API_KEY=tu_api_key_aqui
CHROMA_PERSIST_DIRECTORY=data/vector_store
```

---

## ▶️ Instrucciones de Ejecución y Pruebas

Para que el evaluador pueda validar el correcto funcionamiento del agente y la persistencia de datos, se deben ejecutar los siguientes scripts en orden:

### Paso 1: Inicializar la Base de Conocimiento Interna (RAG - EP1)
Carga los manuales técnicos (`.txt`) en la base de datos vectorial ChromaDB.
```bash
python -m src.ingestion
```
*(Se debe confirmar en consola que la base vectorial fue indexada exitosamente).*

### Paso 2: Ejecutar la Demostración del Agente Autónomo (EP2)
Este script lanza dos escenarios simulados para demostrar la **toma de decisiones adaptativa**:
1.  Un fallo en *Staging* (donde el agente autoriza el arreglo y aplica mitigación).
2.  Un fallo en *Producción* (donde el motor de reglas bloquea la acción y el agente escala el problema a SRE).
```bash
python -m src.agent_ep2
```
*(Al finalizar, se puede revisar el archivo `data/tickets_db.json` para auditar los tickets generados por el agente en disco).*

### Paso 3: Ejecutar la Suite de Pruebas Automatizadas (Pytest)
Para validar técnicamente los indicadores de la pauta (IE1, IE3, IE4, IE5, IE7), ejecuta la suite de pruebas:
```bash
pytest tests/test_agent_ep2.py -v
```
*(Se espera que los 4 tests pasen exitosamente al 100%).*

---

## 👥 Autores
*   **Christian Carriel Aldas**