import os
import sqlite3
import random
import asyncio
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
import openai

app = FastAPI(title="AL CIELO - Production Engine", version="3.7.0")
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
ADMIN_USER = os.getenv("ADMIN_USER") or os.getenv("ADMIN_USERNAME")
ADMIN_PASS = os.getenv("ADMIN_PASS") or os.getenv("ADMIN_PASSWORD")
DB_FILE = "alcielo_licences.db"

# Inicializar clientes de IA (Gemini y OpenAI)
try:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception:
    gemini_client = None

openai_api_key = os.getenv("OPENAI_API_KEY")
if openai_api_key:
    openai_client = openai.OpenAI(api_key=openai_api_key)
else:
    openai_client = None


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS authorized_devices(
        device_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
    )
    conn.commit()
    conn.close()


def authorize_device(device_id, customer_id=None, subscription_id=None):
    if not device_id:
        return
    conn = get_db()
    conn.execute(
        """INSERT INTO authorized_devices
        (device_id,status,stripe_customer_id,stripe_subscription_id,updated_at)
        VALUES(?,'active',?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(device_id) DO UPDATE SET
        status='active',
        stripe_customer_id=excluded.stripe_customer_id,
        stripe_subscription_id=excluded.stripe_subscription_id,
        updated_at=CURRENT_TIMESTAMP""",
        (device_id, customer_id, subscription_id),
    )
    conn.commit()
    conn.close()


def check_device_authorization(device_id):
    if not device_id:
        return False
    conn = get_db()
    row = conn.execute(
        "SELECT status FROM authorized_devices WHERE device_id=?", (device_id,)
    ).fetchone()
    conn.close()
    return bool(row and row["status"] == "active")


def deactivate_device_by_subscription(subscription_id):
    if not subscription_id:
        return
    conn = get_db()
    conn.execute(
        "UPDATE authorized_devices SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",
        (subscription_id,),
    )
    conn.commit()
    conn.close()


init_db()

SYSTEM_WELLNESS_PROMPT = """
You are the exclusive, professional human-like wellness coach for the platform "AL CIELO", designed for adults aged 50 and over, encompassing active individuals, seated, resting, or poststrated in bed, including those with limited mobility or missing limbs.
Your tone must be warm, direct, calm, compassionate, and conversational. You act as an expert companion right beside the user.

STRICT OPERATIONAL RULES:
1. NEVER mention words like "phase", "fase", "auditoría", "IA", or "ChatGPT". Be purely action-oriented and professional.
2. NEVER repeat the exact same session twice. Always introduce fresh phrasing, varied exercise sequences, and unique restorative focuses while maintaining absolute safety.
3. IF THIS IS A FREE 30-SECOND PREVIEW (is_hook=true):
   - Provide a quick, light greeting and a single simple breathing action that lasts about 30 seconds when read aloud.
4. IF THIS IS THE FULL 10-MINUTE SESSION (is_hook=false) - APPLIES TO STRIPE AND USERNAME/PASSWORD:
   - Act as a live personal trainer. Write an extensive, deep, continuous, and highly detailed routine designed to take a full 10 minutes of calm, slow spoken practice.
   - Include inclusive instructions: if a user lacks limbs or mobility, guide them to perform the movements mentally or focus on available joints (fingers, neck, shoulders, breathing).
   - Break down the flow naturally into continuous paragraphs with plenty of descriptive pacing and pauses.
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
    if not ADMIN_USER or not ADMIN_PASS:
        raise HTTPException(
            status_code=500,
            detail="Admin credentials not configured in Render environment variables.",
        )
    if username == ADMIN_USER and password == ADMIN_PASS and device_id:
        authorize_device(device_id)
        return {"status": "success"}
    raise HTTPException(status_code=401, detail="Invalid credentials.")


@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request: Request):
    try:
        body = await request.json()
        device_id = str(body.get("device_id", "")).strip()
        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")
        if not stripe.api_key:
            raise HTTPException(
                status_code=500, detail="STRIPE_SECRET_KEY is missing in Render."
            )
        if not STRIPE_PRICE_ID:
            raise HTTPException(
                status_code=500, detail="STRIPE_PRICE_ID is missing in Render."
            )
        host = request.headers.get("host") or "al-cielo.onrender.com"
        base_url = f"https://{host}"
        checkout_session = stripe.checkout.Session.create(
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/cancel",
            metadata={"device_id": device_id},
        )
        return {"status": "success", "checkout_url": checkout_session.url}
    except HTTPException:
        raise
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Checkout error: {str(e)}")


@app.post("/webhook/stripe")
async def stripe_webhook(
    request: Request, stripe_signature: str = Header(default=None)
):
    payload = await request.body()
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500,
            detail="STRIPE_WEBHOOK_SECRET is missing in Render.",
        )
    if not stripe_signature:
        raise HTTPException(
            status_code=400, detail="Missing Stripe-Signature header."
        )
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=400, detail="Invalid Stripe webhook signature."
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Webhook error: {str(e)}"
        )

    event_type = event.get("type")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata") or {}
        device_id = metadata.get("device_id")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        if device_id:
            authorize_device(device_id, customer_id, subscription_id)

    elif event_type in (
        "customer.subscription.deleted",
        "customer.subscription.unpaid",
    ):
        subscription = event["data"]["object"]
        deactivate_device_by_subscription(subscription.get("id"))

    return {"status": "success"}


@app.get("/success", response_class=HTMLResponse)
async def payment_success(session_id: str = None):
    verified = False
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.get("payment_status") == "paid":
                verified = True
        except Exception:
            verified = False

    if verified:
        return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;">
        <h1 style="color:#4ade80;">Payment Received</h1>
        <p>Stripe received your payment.</p>
        <p>Your access will be activated after Stripe confirms the subscription.</p>
        <a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return to AL CIELO</a>
        </body></html>"""

    return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;">
    <h1 style="color:#f87171;">Payment Not Confirmed</h1>
    <p>We could not verify the payment with Stripe.</p>
    <a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return to AL CIELO</a>
    </body></html>"""


@app.get("/cancel", response_class=HTMLResponse)
async def payment_cancel():
    return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;">
    <h1 style="color:#f87171;">Payment Canceled</h1>
    <p>No subscription was activated.</p>
    <a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return Home</a>
    </body></html>"""


@app.post("/api/v1/generate-session")
async def generate_session(request: Request):
    try:
        body = await request.json()
        device_id = str(body.get("device_id", "")).strip()
        language = body.get("language", "es")
        is_hook = bool(body.get("is_hook", False))
        
        if not device_id:
            raise HTTPException(status_code=400, detail="Device id required.")
            
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(
                status_code=403, detail="Subscription or login required for full session."
            )

        lang_names = {"es": "Spanish", "en": "English", "pt": "Portuguese"}
        selected_lang_name = lang_names.get(language, "Spanish")
        
        random_seed = random.randint(1000, 99999)
        
        if is_hook:
            prompt = f"""
[Seed: {random_seed}]
Generate a strict 30-SECOND FREE PREVIEW in [{selected_lang_name}].
Keep it extremely brief (max 50 words): a warm greeting and one single gentle breathing action. Do not say the word phase.
Output ONLY plain conversational text in {selected_lang_name}. No titles.
"""
            max_tokens = 150
        else:
            prompt = f"""
[Seed: {random_seed}]
Generate a completely unique, extensive, deep, continuous, and professional 10-MINUTE GUIDED WELLNESS SESSION strictly in [{selected_lang_name}]
for adults aged 50 and over, inclusive of active, seated, resting, or poststrated individuals (including those with limited mobility or missing limbs).
Act strictly as a live human personal wellness trainer guiding the user step by step in real time. 
DO NOT use the word 'fase' or 'phase' or any robotic section labels. 
Vary the exercise sequence, phrasing, and focus compared to standard routines so it feels completely fresh. 
Write a rich, continuous, deeply detailed coaching routine that flows naturally from gentle joint micro-movements, postural comfort adjustments, and sensory awareness into deep breathing exercises, providing enough descriptive pacing, pauses, and actionable coaching cues to comfortably fill 10 full minutes of calm spoken practice.
Output ONLY plain conversational text in {selected_lang_name}. No meta-commentary or titles.
"""
            max_tokens = 3000

        response_text = ""

        # INTENTO 1: GEMINI (con límite de 20 segundos)
        if gemini_client:
            try:
                # asyncio.wait_for establece exactamente la regla de esperar 20 segundos máximo
                response_task = asyncio.to_thread(
                    gemini_client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=0.95,
                        max_output_tokens=max_tokens,
                    )
                )
                gemini_response = await asyncio.wait_for(response_task, timeout=20.0)
                response_text = gemini_response.text or ""
            except Exception:
                # Si Gemini tarda más de 20 segundos o falla, la ejecución salta automáticamente al respaldo OpenAI
                response_text = ""

        # INTENTO 2: OPENAI COMO RESPALDO AUTOMÁTICO (Si Gemini falló o superó los 20 segundos)
        if not response_text and openai_client:
            try:
                openai_task = asyncio.to_thread(
                    openai_client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_WELLNESS_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.95,
                    max_tokens=max_tokens
                )
                openai_response = await asyncio.wait_for(openai_task, timeout=20.0)
                response_text = openai_response.choices[0].message.content or ""
            except Exception:
                response_text = ""

        # ÚLTIMO RESPALDO DE EMERGENCIA (Si ambos motores tuvieran problemas de red externos)
        if not response_text or len(response_text) < 200:
            if is_hook:
                response_text = "Muestra Gratuita (30s): Bienvenido a AL CIELO. Adopte una postura cómoda, inhale hondo por la nariz y relaje suavemente sus hombros."
            else:
                if language == "en":
                    response_text = f"Welcome to your complete wellness session variant #{random_seed}. Wherever you are resting today—whether seated in your favorite chair or resting comfortably in bed—take a deep, settling breath... Let's begin by bringing gentle, caring awareness to whatever movement is available to you today. If you have full mobility, fingers and toes; if mobility is limited, focus gently on the joints you can feel... Let's move smoothly into upper body comfort, softening your neck, relaxing your jaw, and rolling your shoulders back with infinite gentleness... Take your time here, breathing in calm and releasing all tension... Now, let's transition into our deep restorative breathing cycle, letting each exhale carry away any heaviness..."
                elif language == "pt":
                    response_text = f"Bem-vindo à sua sessão completa de bem-estar variante #{random_seed}. Onde quer que você esteja descansando hoje — sentado ou deitado —, respire fundo... Vamos começar trazendo atenção suave para as articulações disponíveis... Relaxe o pescoço, solte os ombros com total suavidade... Vamos nos concentrar na respiração profunda e restauradora..."
                else:
                    response_text = f"Bienvenido a su sesión completa de bienestar especial #{random_seed}. Dondequiera que esté descansando hoy, ya sea sentado con apoyo o recostado en su cama, tómese un instante para recibir esta pausa dedicada a su bienestar... Vamos a comenzar llevando una suave atención hacia las partes de su cuerpo que tienen movilidad hoy, o visualizando el movimiento con total calma si se encuentra en reposo absoluto... Sienta cómo el aire entra de manera natural, llenando de frescura su pecho... Vamos ahora a liberar cualquier tensión acumulada en el cuello, rotando milimétricamente los hombros hacia atrás si le es posible, o simplemente sintiendo el apoyo de su espalda... Permítase avanzar con paciencia, sin prisa, disfrutando de cada segundo de este espacio diseñado para su comodidad y equilibrio interno... Siga respirando lento y profundo mientras acompañamos cada minuto con serenidad..."

        return {"status": "success", "session_content": response_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
