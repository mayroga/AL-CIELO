import os
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types

app = FastAPI(title="AL CIELO - Production Engine", version="2.3.0")

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

# Inicialización segura de Gemini con respaldo si la clave falla
try:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception:
    gemini_client = None

# Memoria temporal de dispositivos autorizados (incluye el acceso de cortesía)
AUTHORIZED_DEVICES = set()

SYSTEM_WELLNESS_PROMPT = """
You are the exclusive wellness advisor for the platform "AL CIELO", designed for adults aged 50 and over.
Your instructions must be direct, extremely concise, warm, and highly effective. The user listens via voice.

ABSOLUTE RULES:
1. LEGAL SAFETY BLOCK: Every session strictly starts by stating that this is a general wellness service, not medical advice, and that each person participates at their own discretion and comfort.
2. DIRECT INSTRUCTION FORMAT: Short, clear movements or breathing steps suitable for active people, wheelchair users, or bedridden individuals.
3. Zero medical jargon. Speak as a lifestyle and wellness specialist.
"""

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    return "index.html"

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request: Request):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    device_id = body.get("device_id", "").strip()

    # Credenciales oficiales de cortesía
    if username == "admin" and password == "alcielo2026" and device_id:
        AUTHORIZED_DEVICES.add(device_id)
        return {"status": "success"}
    
    raise HTTPException(status_code=401, detail="Invalid credentials.")

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request: Request):
    try:
        body = await request.json()
        device_id = body.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        # Validar si Stripe está configurado correctamente
        if not stripe.api_key or not STRIPE_PRICE_ID:
            raise HTTPException(status_code=500, detail="Stripe is not configured on the server.")

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
        AUTHORIZED_DEVICES.add(device_id)
    return """
    <html><body style="background:#0f172a; color:white; text-align:center; padding-top:60px; font-family:sans-serif;">
        <h1 style="color:#4ade80;">Subscription Activated Successfully!</h1>
        <p>Your device is now permanently authorized.</p>
        <a href="/" style="display:inline-block; margin-top:20px; padding:12px 24px; background:#0284c7; color:white; text-decoration:none; border-radius:8px; font-weight:bold;">Return to AL CIELO</a>
    </body></html>
    """

@app.get("/cancel", response_class=HTMLResponse)
async def payment_cancel():
    return """
    <html><body style="background:#0f172a; color:white; text-align:center; padding-top:60px; font-family:sans-serif;">
        <h1 style="color:#f87171;">Payment Canceled</h1>
        <a href="/" style="display:inline-block; margin-top:20px; padding:12px 24px; background:#0284c7; color:white; text-decoration:none; border-radius:8px; font-weight:bold;">Return Home</a>
    </body></html>
    """

@app.post("/api/v1/generate-session")
async def generate_session(request: Request):
    try:
        body = await request.json()
        device_id = body.get("device_id")
        language = body.get("language", "es")
        is_hook = body.get("is_hook", False)

        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        # Verificar si está autorizado por pago o por cortesía
        is_authorized = (device_id in AUTHORIZED_DEVICES)
        if not is_hook and not is_authorized:
            raise HTTPException(status_code=403, detail="Subscription required.")

        duration_desc = "30-second free preview" if is_hook else "full 10-minute guided wellness session"
        
        lang_names = {"es": "Spanish", "en": "English", "pt": "Portuguese"}
        selected_lang_name = lang_names.get(language, "Spanish")

        prompt = f"""
        Generate a [{duration_desc}] strictly in [{selected_lang_name}] for adults aged 50 and over.
        Direct, warm, human instructions focusing on gentle mobility and breathing. 
        CRITICAL: Output ONLY plain conversational sentences in {selected_lang_name}. Do NOT mix languages. Do NOT include any intro text like 'Here is your session'.
        """

        response_text = ""
        if gemini_client:
            try:
                response = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=0.6,
                    ),
                )
                response_text = response.text
            except Exception:
                response_text = ""

        # Respaldo automático de emergencia si la IA no responde
        if not response_text:
            if language == 'en':
                response_text = "Welcome to AL CIELO. This session is for general well-being. Please take a comfortable posture. Inhale deeply through your nose, and exhale slowly through your mouth. Gently move your toes and ankles, feeling a soft, natural circulation. Remember to move only within your personal comfort. Thank you for sharing this peaceful moment."
            elif language == 'pt':
                response_text = "Bem-vindo ao AL CIELO. Esta sessão é para o seu bem-estar geral. Por favor, adote uma postura confortável. Inspire profundamente pelo nariz e expire devagar pela boca. Mova suavemente os dedos dos pés e os tornozelos, sentindo uma circulação leve. Lembre-se de fazer apenas o que for confortável."
            else:
                response_text = "Bienvenido a AL CIELO. Esta sesión es de bienestar general. Tome una postura cómoda. Inhale profundamente por la nariz y exhale despacio por la boca. Mueva suavemente los dedos de los pies y los tobillos sintiendo una circulación suave. Recuerde hacer solo lo que le resulte cómodo."

        return {
            "status": "success",
            "session_content": response_text
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
