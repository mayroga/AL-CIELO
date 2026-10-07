import os
import time
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe
from google import genai
from google.genai import types

app = FastAPI(title="AL CIELO - Production Engine", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de Stripe desde Variables de Entorno de Render
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID1 = os.getenv("STRIPE_PRICE_ID1") or os.getenv("STRIPE_PRICE_ID")
STRIPE_PRICE_ID2 = os.getenv("STRIPE_PRICE_ID2")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Credenciales de administración ocultas en Render
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS = os.getenv("ADMIN_PASS")

# Kernel volátil para control de sesión y planes
VOLATILE_KERNEL = {
    "session_active": False,
    "is_premium": False,
    "expires_at": 0.0
}

# Inicialización segura de Gemini
try:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception:
    gemini_client = None

AUTHORIZED_DEVICES = set()

SYSTEM_WELLNESS_PROMPT = """
You are the exclusive wellness advisor for the platform "AL CIELO", designed for adults aged 50 and over.
Your instructions must be direct, extremely concise, warm, and highly effective. The user listens via voice.

ABSOLUTE RULES:
1. LEGAL SAFETY BLOCK: Every session strictly starts by stating that this is a general wellness service, not medical advice, and that each person participates at their own discretion and comfort.
2. DIRECT INSTRUCTION FORMAT: Short, clear movements or breathing steps suitable for active people, wheelchair users, or bedridden individuals.
3. Zero medical jargon. Speak as a lifestyle and wellness specialist.
"""

class StripeSessionRequest(BaseModel):
    price_tier: int

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    return "index.html"

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request: Request):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    device_id = body.get("device_id", "").strip()

    if not ADMIN_USER or not ADMIN_PASS:
        raise HTTPException(status_code=500, detail="Admin credentials not configured in environment variables.")

    if username == ADMIN_USER and password == ADMIN_PASS and device_id:
        AUTHORIZED_DEVICES.add(device_id)
        VOLATILE_KERNEL["session_active"] = True
        return {"status": "success"}
    
    raise HTTPException(status_code=401, detail="Invalid credentials.")

# ==========================================
# STRIPE CHECKOUT
# ==========================================
@app.post("/api/stripe/create-checkout")
async def create_checkout_session(req: StripeSessionRequest, request: Request):
    if req.price_tier not in (1, 2):
        raise HTTPException(status_code=400, detail="Invalid price tier.")

    price_id = STRIPE_PRICE_ID1 if req.price_tier == 1 else STRIPE_PRICE_ID2

    if not price_id:
        raise HTTPException(
            status_code=500,
            detail="Stripe Price ID is not configured in Render environment variables."
        )

    origin = request.headers.get("origin")
    if not origin:
        host = request.headers.get("host")
        origin = f"https://{host}" if host else "https://al-cielo.onrender.com"

    mode = "payment" if req.price_tier == 1 else "subscription"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode=mode,
            success_url=f"{origin}/?stripe_status=success",
            cancel_url=f"{origin}/?stripe_status=cancel",
            metadata={"tier": str(req.price_tier)}
        )
        return {"url": session.url}

    except Exception as e:
        print(f"[STRIPE ERROR] {e}")
        raise HTTPException(
            status_code=500,
            detail="Unable to create Stripe checkout session."
        )

# ==========================================
# STRIPE WEBHOOK
# ==========================================
@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        tier = metadata.get("tier", "1")

        VOLATILE_KERNEL["session_active"] = True

        if tier == "2":
            VOLATILE_KERNEL["is_premium"] = True
            VOLATILE_KERNEL["expires_at"] = time.time() + 2592000.0
        else:
            VOLATILE_KERNEL["is_premium"] = False
            VOLATILE_KERNEL["expires_at"] = time.time() + 600.0

        return {"status": "success"}

    return {"status": "event_unhandled"}

# ==========================================
# ESTADO DE SESIÓN
# ==========================================
@app.get("/api/auth/session-status")
async def get_session_status():
    now = time.time()
    active = VOLATILE_KERNEL.get("session_active", False)
    premium = VOLATILE_KERNEL.get("is_premium", False)
    expires = VOLATILE_KERNEL.get("expires_at", 0.0)

    if active and (premium or now <= expires):
        return {
            "active": True,
            "is_premium": premium,
            "time_left": 2592000 if premium else max(0, int(expires - now))
        }
    return {
        "active": False,
        "is_premium": False,
        "time_left": 0
    }

@app.get("/success", response_class=HTMLResponse)
async def payment_success():
    VOLATILE_KERNEL["session_active"] = True
    return """
    <html><body style="background:#0f172a; color:white; text-align:center; padding-top:60px; font-family:sans-serif;">
        <h1 style="color:#4ade80;">Payment Successful!</h1>
        <p>Your session has been authorized.</p>
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
        language = body.get("language", "es")
        is_hook = body.get("is_hook", False)

        now = time.time()
        active = VOLATILE_KERNEL.get("session_active", False)
        premium = VOLATILE_KERNEL.get("is_premium", False)
        expires = VOLATILE_KERNEL.get("expires_at", 0.0)

        is_authorized = active and (premium or now <= expires)
        if not is_hook and not is_authorized:
            raise HTTPException(status_code=403, detail="Subscription required.")

        duration_desc = "30-second free preview" if is_hook else "full 10-minute guided wellness session"
        lang_names = {"es": "Spanish", "en": "English", "pt": "Portuguese"}
        selected_lang_name = lang_names.get(language, "Spanish")

        prompt = f"""
        Generate a [{duration_desc}] strictly in [{selected_lang_name}] for adults aged 50 and over.
        Direct, warm, human instructions focusing on gentle mobility and breathing. 
        CRITICAL: Output ONLY plain conversational sentences in {selected_lang_name}. Do NOT mix languages. Do NOT include any intro text.
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

        if not response_text:
            if language == 'en':
                response_text = "Welcome to AL CIELO. This session is for general well-being. Please take a comfortable posture. Inhale deeply through your nose, and exhale slowly through your mouth. Gently move your toes and ankles, feeling a soft, natural circulation."
            elif language == 'pt':
                response_text = "Bem-vindo ao AL CIELO. Esta sessão é para o seu bem-estar geral. Por favor, adote uma postura confortável. Inspire profundamente pelo nariz e expire devagar pela boca."
            else:
                response_text = "Bienvenido a AL CIELO. Esta sesión es de bienestar general. Tome una postura cómoda. Inhale profundamente por la nariz y exhale despacio por la boca."

        return {
            "status": "success",
            "session_content": response_text
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
