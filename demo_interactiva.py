import sys
from src.agent_ep2 import AgenteOperacionesDevCloud

def main():
    print("=" * 65)
    print("  DEVCLOUD AGENT - CONSOLA DE OPERACIONES INTERACTIVA (EP2)")
    print("=" * 65)
    print("Iniciando agente y cargando memoria...")
    agente = AgenteOperacionesDevCloud()
    print("\n[OK] Agente listo. Escribe tus requerimientos.")
    print("(Escribe 'salir' o 'exit' para terminar la sesion)\n")

    while True:
        try:
            consulta = input("[TU CONSULTA]: ").strip()
            if not consulta:
                continue
            if consulta.lower() in ["exit", "salir", "quit"]:
                print("\nCerrando sesion del Agente. ¡Hasta pronto!")
                break

            print("\n[-] El agente esta analizando el requerimiento y ejecutando herramientas...")
            resultado = agente.ejecutar_tarea(consulta, session_id="sesion_presentacion")
            
            herramientas = [t["herramienta"] for t in resultado["traza_ejecucion"]]
            if herramientas:
                print(f"[+] Herramientas llamadas: {herramientas}")
            
            print(f"\n[RESPUESTA DEL AGENTE]:\n{resultado['respuesta_final']}")
            print("-" * 65)

        except KeyboardInterrupt:
            print("\nSesion interrumpida por el usuario.")
            break
        except Exception as e:
            print(f"\n[ERROR]: Ocurrio un problema: {e}")

if __name__ == "__main__":
    main()

