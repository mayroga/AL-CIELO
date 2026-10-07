import os
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
from database import authorize_device, check_device_authorization

app = FastAPI(title="AL CIELO - Production Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Carga estricta de variables de entorno configuradas en Render
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Prompt maestro inmutable estructurado por bloques temporales estrictos para garantizar calidad profesional de 10 minutos
SYSTEM_WELLNESS_PROMPT = """
Eres el motor de bienestar universal de la aplicación "AL CIELO", diseñada exclusivamente para adultos mayores de 50 años en adelante. 
Tu alcance es universal: debes estructurar sesiones aptas para cualquier condición física (personas totalmente activas, con movilidad reducida, en silla de ruedas o completamente postradas/en cama).

REGLAS ABSOLUTAS E INMUTABLES PARA LA DURACIÓN Y ESTRUCTURA DE 10 MINUTOS:
Cada sesión diaria debe entregarse estrictamente estructurada en 4 bloques temporales claros para garantizar una experiencia completa y profesional:
1. BLOQUE 1 (Minuto 0 al 1): Aviso de seguridad obligatorio de 5 segundos, seguido de calibración respiratoria inicial y toma de conciencia corporal (adaptada para cualquier postura, incluso encamados).
2. BLOQUE 2 (Minuto 1 al 4): Movilización articular suave y activación circulatoria por tandas (comenzando desde extremidades superiores o inferiores según el enfoque del día, asegurando micro-movimientos seguros).
3. BLOQUE 3 (Minuto 4 al 8): Tandas principales de bienestar postural, estiramientos de bajo impacto y conexión de movilidad funcional, con instrucciones claras y pausas de respiración.
4. BLOQUE 4 (Minuto 8 al 10): Cierre de relajación profunda, integración de la postura y mensaje de estabilidad y esperanza para el resto del día.

REGLAS DE ORO:
1. ENFOQUE EXCLUSIVO DE WELLNESS: Cero términos médicos, diagnósticos, tratamientos o curas. Eres un especialista en bienestar, movilidad, circulación y estilo de vida.
2. VARIABILIDAD INFINITA: Jamás repites la misma secuencia. Cambias sutilmente el orden, los enfoques, las metáforas de bienestar y las pautas de respiración para que cada sesión diaria sea única y diferente.
3. Tono sumamente cálido, humano, respetuoso, claro, directo y fácil de seguir.
"""

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request: Request):
    """Crea la pasarela de pago en Stripe por $15.99 vinculada al hardware del dispositivo."""
    try:
        body = await request.json()
        device_id = body.get("device_id")
        
        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': STRIPE_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"https://alcielo.app/success?device_id={device_id}",
            cancel_url="https://alcielo.app/cancel",
            metadata={'device_id': device_id}
        )
        return {"checkout_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """Webhook oficial de Stripe para activar automáticamente el dispositivo al completarse el pago."""
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature or payload.")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        device_id = session.get("metadata", {}).get("device_id")
        if device_id:
            authorize_device(device_id)

    return {"status": "success"}

@app.post("/api/v1/verify-device")
async def verify_device(request: Request):
    """Verifica si el dispositivo actual posee una licencia activa."""
    body = await request.json()
    device_id = body.get("device_id")
    authorized = check_device_authorization(device_id)
    return {"device_id": device_id, "authorized": authorized}

@app.post("/api/v1/generate-session")
async def generate_session(request: Request):
    """
    Genera la sesión diaria de 10 minutos (o gancho gratuito de 30 segundos) 
    validando obligatoriamente la suscripción del dispositivo bajo la estructura por bloques.
    """
    try:
        body = await request.json()
        device_id = body.get("device_id")
        language = body.get("language", "en") # 'es', 'en', 'pt'
        is_hook = body.get("is_hook", False) # True para la muestra de 30 segundos gratis

        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        # Si no es la sesión de gancho de 30 segundos, exige verificación estricta de pago en el dispositivo
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(status_code=403, detail="Device not authorized. Subscription required.")

        duration_text = "30 seconds free visual preview hook" if is_hook else "10 minutes complete unique daily session structured in 4 time blocks"
        
        prompt = f"""
        Genera una sesión dirigida a adultos mayores de 50 años en adelante, en idioma [{language}], duración [{duration_text}].
        Sigue estrictamente la estructura de bloques temporales exigida, asegurando el aviso legal inicial de seguridad, activación circulatoria universal, confort postural y tandas de bienestar.
        Tono cálido, directo, sin rodeos, adaptado para cualquier estado físico (desde activos hasta postrados), variabilidad infinita.
        """

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_WELLNESS_PROMPT,
                temperature=0.7,
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

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
