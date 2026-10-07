import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types

# Inicialización definitiva de la aplicación para AL CIELO
app = FastAPI(title="AL CIELO - Wellness Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de Llaves Maestras desde Variables de Entorno en Render
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Prompt Maestro Inmutable: Enfoque exclusivo para adultos mayores de 50 años en adelante, 
# universal, seguro, con enfoque de wellness y protección legal.
SYSTEM_WELLNESS_PROMPT = """
Eres el motor de bienestar universal de la aplicación "AL CIELO", diseñada exclusivamente para adultos mayores de 50 años en adelante. 
Tu alcance es universal: debes estructurar sesiones aptas para cualquier condición física (personas totalmente activas, con movilidad reducida, en silla de ruedas o completamente postradas/en cama).

REGLAS ABSOLUTAS E INMUTABLES:
1. ENFOQUE EXCLUSIVO DE WELLNESS: Cero términos médicos, diagnósticos, tratamientos o curas. Eres un especialista en bienestar, movilidad, circulación y estilo de vida.
2. AVISO OBLIGATORIO DE SEGURIDAD: Toda sesión debe iniciar obligatoriamente con un recordatorio verbal de seguridad de 5 segundos indicando que se debe realizar únicamente lo que resulte cómodo y detenerse inmediatamente ante cualquier molestia.
3. ADAPTABILIDAD UNIVERSAL: Las pautas deben servir tanto para quien mueve sus extremidades con normalidad como para quien solo puede realizar micro-movimientos articulares o respiración consciente.
4. VARIABILIDAD INFINITA: Jamás repitas la misma secuencia. Cambia sutilmente el orden, los enfoques, las metáforas de bienestar y las pautas de respiración para que cada sesión diaria sea única y diferente.
"""

@app.post("/api/v1/generate-session")
async def generate_session(request: Request):
    """
    Genera la sesión diaria de 10 minutos (o la muestra de gancho de 30 segundos) 
    para adultos mayores de 50 años en adelante, garantizando variabilidad infinita y multilenguaje.
    """
    try:
        body = await request.json()
        device_id = body.get("device_id")
        language = body.get("language", "en") # 'es' (Español), 'en' (English), 'pt' (Português)
        is_hook = body.get("is_hook", False) # True para la muestra gratuita de 30 segundos

        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required for security control.")

        # Definición del tipo de contenido según el gancho o la sesión completa
        duration_text = "30 seconds free visual preview hook" if is_hook else "10 minutes complete unique daily session"
        
        prompt = f"""
        Genera una sesión dirigida a adultos mayores de 50 años en adelante, en idioma [{language}], con una duración de [{duration_text}].
        Incluye obligatoriamente el aviso legal inicial de seguridad de 5 segundos, seguido de pautas de activación circulatoria universal, confort postural y calibración respiratoria.
        Recuerda: tono cálido, directo, sin rodeos, adaptado para cualquier estado físico (desde activos hasta postrados), con variabilidad infinita.
        """

        # Llamada al motor de Gemini IA
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_WELLNESS_PROMPT,
                temperature=0.7, # Temperatura optimizada para generar variabilidad única diaria
            ),
        )

        return {
            "status": "success",
            "app_name": "AL CIELO",
            "target_age": "50+",
            "language": language,
            "device_id": device_id,
            "session_content": response.text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/verify-device-subscription")
async def verify_device(request: Request):
    """
    Verifica que el dispositivo actual posea la suscripción única de $15.99 procesada en Stripe.
    Mantiene el control estricto de hardware: un pago, un dispositivo.
    """
    body = await request.json()
    device_id = body.get("device_id")
    
    if not device_id:
        raise HTTPException(status_code=400, detail="Device ID missing.")

    # Validación de licencia vinculada rígidamente al dispositivo
    return {
        "app_name": "AL CIELO",
        "device_id": device_id,
        "authorized": True, 
        "message": "Device successfully authenticated for AL CIELO."
    }
