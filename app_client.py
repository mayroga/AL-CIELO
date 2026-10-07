import requests
import uuid
import platform
import webbrowser

# REEMPLAZA ESTA URL CON LA QUE TE DEA RENDER AL DESPLEGAR TU BACKEND
BACKEND_URL = "https://al-cielo.onrender.com/api/v1"

def get_or_create_device_id():
    """
    Genera un identificador único de hardware invariable para asegurar 
    que la suscripción de $15.99 se quede atada permanentemente a este dispositivo.
    """
    hardware_signature = f"{platform.node()}-{platform.machine()}-{platform.system()}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, hardware_signature))

def solicitar_sesion_al_cielo(language="en", is_hook=False):
    """
    Solicita al servidor en Render la sesión única de 10 minutos (o los 30 segundos de gancho)
    para adultos mayores de 50+, validando el acceso del dispositivo.
    """
    device_id = get_or_create_device_id()
    
    payload = {
        "device_id": device_id,
        "language": language, # 'es' (Español), 'en' (English), 'pt' (Português)
        "is_hook": is_hook    # True para la muestra gratis, False para la sesión completa
    }
    
    try:
        response = requests.post(f"{BACKEND_URL}/generate-session", json=payload)
        if response.status_code == 200:
            data = response.json()
            return data.get("session_content")
        elif response.status_code == 403:
            return "ACCESS_DENIED_REQUIRES_PAYMENT"
        else:
            return f"Error de conexión: {response.status_code}"
    except Exception as e:
        return f"Error técnico: {str(e)}"

def iniciar_pago_stripe():
    """
    Abre la pasarela de pago seguro en Stripe por $15.99 vinculada al dispositivo.
    """
    device_id = get_or_create_device_id()
    payload = {"device_id": device_id}
    
    try:
        response = requests.post(f"{BACKEND_URL}/create-checkout-session", json=payload)
        if response.status_code == 200:
            checkout_url = response.json().get("checkout_url")
            print(f"Abriendo pasarela de pago segura en Stripe...")
            webbrowser.open(checkout_url)
        else:
            print("Error al generar la pasarela de pago.")
    except Exception as e:
        print(f"Error de red al procesar pago: {str(e)}")

# --- EJECUCIÓN LOCAL DE PRUEBA EN EL DISPOSITIVO ---
if __name__ == "__main__":
    print("--- BIENVENIDO A AL CIELO (50+) ---")
    
    # 1. Probamos primero el gancho gratuito de 30 segundos en el idioma elegido (ej: 'es' para Español)
    idioma = "es" 
    print(f"\n[1] Cargando muestra gratuita de 30 segundos en [{idioma}]...")
    muestra = solicitar_sesion_al_cielo(language=idioma, is_hook=True)
    print(muestra)
    
    # 2. Intentamos cargar la sesión completa de 10 minutos
    print(f"\n[2] Verificando acceso para la sesión completa de 10 minutos...")
    sesion_completa = solicitar_sesion_al_cielo(language=idioma, is_hook=False)
    
    if sesion_completa == "ACCESS_DENIED_REQUIRES_PAYMENT":
        print("\nDispositivo sin suscripción activa.")
        # Opcional: Descomentar la siguiente línea para activar el pago automático de $15.99 en Stripe
        # iniciar_pago_stripe()
    else:
        print("\n--- SESIÓN DIARIA ÚNICA ---")
        print(sesion_completa)
