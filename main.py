import os
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
from database import authorize_device, check_device_authorization

app = FastAPI(title="AL CIELO - Production Engine", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_WELLNESS_PROMPT = """
Eres el asesor de bienestar exclusivo de la plataforma "AL CIELO", para adultos mayores de 50 años en adelante.
Tus instrucciones deben ser directas, sumamente concisas, cálidas y de alto peso resolutivo. El usuario NO lee textos largos; escucha las instrucciones en audio.

REGLAS ABSOLUTAS E INMUTABLES:
1. BLOQUE DE SEGURIDAD LEGAL OBLIGATORIO: Toda sesión inicia informando estrictamente que el servicio es de bienestar general, no médico, y que cada persona realiza solo lo que le resulte cómodo bajo su propia responsabilidad.
2. FORMATO DE INSTRUCCIÓN DIRECTA: Da instrucciones cortas y claras de movilidad, respiración o confort postural (aptas para personas activas o en silla/cama), listas para ser leídas por voz.
3. Cero lenguaje médico, cero términos de diagnósticos. Eres un especialista en estilo de vida y bienestar.
"""

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    """Sirve la interfaz visual directamente desde un archivo HTML externo independiente."""
    return "index.html"

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request: Request):
    try:
        body = await request.json()
        device_id = body.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            mode='subscription',
            success_url=f"https://al-cielo.onrender.com/success?device_id={device_id}",
            cancel_url="https://al-cielo.onrender.com/cancel",
            metadata={'device_id': device_id}
        )
        return {"checkout_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/success", response_class=HTMLResponse)
async def payment_success(device_id: str = None):
    if device_id:
        authorize_device(device_id)
    return """
    <html><body style="background:#0f172a; color:white; text-align:center; padding-top:60px; font-family:sans-serif;">
        <h1 style="color:#4ade80;">¡Suscripción Activada con Éxito!</h1>
        <p>Su dispositivo ha quedado registrado permanentemente.</p>
        <a href="/" style="display:inline-block; margin-top:20px; padding:12px 24px; background:#0284c7; color:white; text-decoration:none; border-radius:8px; font-weight:bold;">Volver a AL CIELO</a>
    </body></html>
    """

@app.get("/cancel", response_class=HTMLResponse)
async def payment_cancel():
    return """
    <html><body style="background:#0f172a; color:white; text-align:center; padding-top:60px; font-family:sans-serif;">
        <h1 style="color:#f87171;">Proceso de Pago Cancelado</h1>
        <a href="/" style="display:inline-block; margin-top:20px; padding:12px 24px; background:#0284c7; color:white; text-decoration:none; border-radius:8px; font-weight:bold;">Volver al Inicio</a>
    </body></html>
    """

@app.post("/api/v1/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook error.")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        device_id = session.get("metadata", {}).get("device_id")
        if device_id:
            authorize_device(device_id)
    return {"status": "success"}

@app.post("/api/v1/generate-session")
async def generate_session(request: Request):
    try:
        body = await request.json()
        device_id = body.get("device_id")
        language = body.get("language", "es")
        is_hook = body.get("is_hook", False)

        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(status_code=403, detail="Subscription required.")

        duration_desc = "muestra gratuita de 30 segundos" if is_hook else "sesión completa guiada de bienestar"
        
        prompt = f"""
        Genera una sesión de [{duration_desc}] en idioma [{language}] para adultos mayores de 50 años.
        Instrucciones directas, cálidas, enfocadas en movimientos cortos de movilidad y respiración que se puedan escuchar por voz. Sin textos largos ni viñetas complejas.
        """

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_WELLNESS_PROMPT,
                temperature=0.6,
            ),
        )

        return {
            "status": "success",
            "session_content": response.text
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
