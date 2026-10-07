import requests
import uuid
import platform

# URL de tu backend desplegado en Render (Esta es la URL que obtienes al desplegar)
# Ejemplo: BACKEND_URL = "https://al-cielo-backend.onrender.com/api/v1"
BACKEND_URL = "https://TU-URL-DE-RENDER.onrender.com/api/v1"

def get_or_create_device_id():
    """
    Genera un identificador único de hardware para asegurar que la suscripción 
    de $15.99 de Stripe se quede atada permanentemente a este mismo dispositivo.
    """
    # Utiliza características fijas del dispositivo local
    hardware_signature = f"{platform.node()}-{platform.machine()}-{platform.system()}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, hardware_signature))

def solicitar_sesion_al_cielo(language="en", is_hook=False):
    """
    Se conecta al servidor en Render para obtener la sesión única generada por IA 
    para adultos mayores de 50 años en adelante.
    """
    device_id = get_or_create_device_id()
    
    payload = {
        "device_id": device_id,
        "language": language, # 'es' (Español), 'en' (English), 'pt' (Português)
        "is_hook": is_hook    # True para los 30 segundos gratis, False para los 10 minutos completos
    }
    
    try:
        response = requests.post(f"{BACKEND_URL}/generate-session", json=payload)
        if response.status_code == 200:
            data = response.json()
            return data.get("session_content")
        else:
            return f"Error de conexión: {response.status_code}"
    except Exception as e:
        return f"Error técnico: {str(e)}"

# --- EJEMPLO DE USO LOCAL EN EL DISPOSITIVO DEL ADULTO MAYOR ---
if __name__ == "__main__":
    print("--- BIENVENIDO A AL CIELO (50+) ---")
    print("Idiomas disponibles: Español ('es'), English ('en'), Português ('pt')")
    
    # Ejemplo solicitando la sesión en Portugués para Brasil (muestra de gancho de 30 segundos)
    idioma_seleccionado = "pt" 
    
    print(f"\nGenerando sesión en [{idioma_seleccionado}] para dispositivo único...")
    contenido_sesion = solicitar_sesion_al_cielo(language=idioma_seleccionado, is_hook=True)
    
    print("\n--- CONTENIDO DE LA SESIÓN ---")
    print(contenido_sesion)
