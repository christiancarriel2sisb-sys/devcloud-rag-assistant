import json
from typing import Dict, Any

MOCK_EXTERNAL_CLOUD_STATUS: Dict[str, Any] = {
    "provider": "Google Cloud Platform - Regional Status (southamerica-west1)",
    "last_updated": "2026-10-28T14:30:00Z",
    "services": {
        "Google Kubernetes Engine (GKE)": {
            "status": "OPERATIONAL",
            "incident_detected": False,
            "message": "Todos los clusteres operan con normalidad en la region Santiago."
        },
        "Cloud SQL (PostgreSQL)": {
            "status": "DEGRADED_PERFORMANCE",
            "incident_detected": True,
            "message": "Elevada latencia en resolucion de conexiones y E/S en la zona southamerica-west1-a. El equipo de infraestructura global esta mitigando."
        },
        "Compute Engine (VPC Network)": {
            "status": "OPERATIONAL",
            "incident_detected": False,
            "message": "Enrutamiento y balanceadores de carga funcionando correctamente."
        }
    }
}

def consultar_estado_proveedor_externo(servicio: str = None) -> str:
    """
    Consulta el estado operativo de proveedores externos de nube.
    Permite contrastar incidentes locales reportados contra fallas globales.
    """
    if servicio:
        for nombre_serv, info in MOCK_EXTERNAL_CLOUD_STATUS["services"].items():
            if servicio.lower() in nombre_serv.lower():
                return json.dumps({
                    "proveedor": MOCK_EXTERNAL_CLOUD_STATUS["provider"],
                    "servicio": nombre_serv,
                    "estado": info["status"],
                    "incidente_global": info["incident_detected"],
                    "detalle": info["message"],
                    "timestamp": MOCK_EXTERNAL_CLOUD_STATUS["last_updated"]
                }, ensure_ascii=False, indent=2)

    return json.dumps(MOCK_EXTERNAL_CLOUD_STATUS, ensure_ascii=False, indent=2)
