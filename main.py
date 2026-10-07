import os
import sqlite3
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types

app = FastAPI(title="AL CIELO - Production Engine", version="3.5.0")
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

try:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception:
    gemini_client = None

# INSTRUCCIÓN MAESTRA: ENTRENADOR HUMANO DE 10 MINUTOS (EXCLUSIVO PARA ACCESO COMPLETO)
SYSTEM_WELLNESS_PROMPT = """
You are the exclusive, professional human-like wellness coach for the platform "AL CIELO", designed for adults aged 50 and over (active, seated, or resting).
Your tone must be warm, direct, calm, and conversational. You act as an expert companion right beside the user.

STRICT OPERATIONAL RULES:
1. NEVER mention words like "phase", "fase", "auditoría", "IA", or "ChatGPT". Be purely action-oriented and professional.
2. IF THIS IS A FREE 30-SECOND PREVIEW (is_hook=true):
   - Provide a quick, light greeting and a single simple breathing or hand movement exercise that lasts about 30 seconds when read aloud. Give just a small sample so the user understands the dynamic.
3. IF THIS IS THE FULL 10-MINUTE SESSION (is_hook=false) - APPLIES TO BOTH STRIPE SUBSCRIBERS AND USERNAME/PASSWORD LOGINS:
   - Act purely as the live personal trainer and wellness specialist. 
   - DO NOT divide the text with robotic labels like "Phase 1" or "Phase 2". Instead, transition smoothly as a human coach would.
   - Flow naturally through gentle joint activation, comfort positioning, and deep breathing, writing rich, continuous, and paced instructions designed to provide a complete 10-minute active experience with pauses and direct coaching cues.
"""


@app.get("/", response_class=FileResponse)
async def serve_frontend():
    return "index.html"


@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request: Request):
    """Acceso mediante Username y Password. Autoriza el dispositivo para recibir los 10 minutos completos."""
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
            
        # REGLA DE ORO LEGAL: Si NO es hook (es decir, entró por Stripe O por Username/Password autorizado), 
        # se le exige obligatoriamente el pase de autorización en la BD. Si está autorizado, recibe los 10 minutos completos.
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(
                status_code=403, detail="Subscription or login required for full session."
            )

        lang_names = {"es": "Spanish", "en": "English", "pt": "Portuguese"}
        selected_lang_name = lang_names.get(language, "Spanish")
        
        if is_hook:
            # PRUEBA GRATUITA: Estricta y corta de 30 segundos
            prompt = f"""
Generate a strict 30-SECOND FREE PREVIEW in [{selected_lang_name}].
Keep it extremely brief (max 50 words): a warm greeting and one single gentle breathing action. Do not say the word phase.
Output ONLY plain conversational text in {selected_lang_name}. No titles.
"""
            max_tokens = 150
        else:
            # SESIÓN COMPLETA DE 10 MINUTOS (Aplica tanto a pago Stripe como a Login Username/Password)
            prompt = f"""
Generate a full, continuous, professional 10-MINUTE GUIDED WELLNESS SESSION strictly in [{selected_lang_name}]
for adults aged 50 and over (active, seated, or resting).
Act strictly as a live human personal wellness trainer guiding the user step by step in real time. 
DO NOT use the word 'fase' or 'phase' or any robotic section labels. 
Instead, write a rich, continuous, deeply detailed coaching routine that flows naturally from gentle joint movements and posture adjustments into deep breathing exercises, providing enough descriptive pacing, pauses, and actionable coaching cues to comfortably fill 10 full minutes of calm spoken practice.
Output ONLY plain conversational text in {selected_lang_name}. No meta-commentary or titles.
"""
            max_tokens = 2500  # Tokenaje alto para garantizar los 10 minutos completos de texto

        response_text = ""
        if gemini_client:
            try:
                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=0.75,
                        max_output_tokens=max_tokens,
                    ),
                )
                response_text = response.text or ""
            except Exception:
                response_text = ""

        if not response_text:
            if is_hook:
                if language == "en":
                    response_text = "Free Preview (30s): Welcome to AL CIELO. Take a comfortable posture, inhale deeply through your nose, and gently relax your shoulders."
                elif language == "pt":
                    response_text = "Amostra Gratuita (30s): Bem-vindo ao AL CIELO. Adote uma postura confortável, inspire profundamente pelo nariz e relaxe os ombros."
                else:
                    response_text = "Muestra Gratuita (30s): Bienvenido a AL CIELO. Adopte una postura cómoda, inhale hondo por la nariz y relaje suavemente sus hombros."
            else:
                if language == "en":
                    response_text = "Welcome to your complete wellness session. Wherever you are resting today, take a moment to settle into a comfortable, supported position... Let's begin by bringing gentle awareness to your hands and feet, moving your fingers and toes slowly... Now, let's focus on posture and comfort, gently rolling your shoulders backward... Finally, let's settle into deep, calm breathing..."
                elif language == "pt":
                    response_text = "Bem-vindo à sua sessão completa de bem-estar. Onde quer que esteja descansando hoje, acomode-se em uma posição confortável... Vamos começar movendo suavemente os dedos das mãos e dos pés... Agora, vamos focar no conforto postural, girando os ombros para trás... Finalmente, vamos nos concentrar na respiração profunda..."
                else:
                    response_text = "Bienvenido a su sesión completa de bienestar. Dondequiera que esté descansando hoy, tómese un instante para acomodarse en una postura cómoda y apoyada... Vamos a comenzar llevando una suave atención a sus manos y pies, moviendo lentamente los dedos... Ahora, enfoquémonos en el confort postural, rotando suavemente los hombros hacia atrás... Finalmente, centremos la atención en la respiración profunda y pausada..."

        return {"status": "success", "session_content": response_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
