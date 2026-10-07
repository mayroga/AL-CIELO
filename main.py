import os
import sqlite3
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types

app = FastAPI(title="AL CIELO - Production Engine", version="3.0.4")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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
    conn.execute("""CREATE TABLE IF NOT EXISTS authorized_devices(
        device_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def authorize_device(device_id, customer_id=None, subscription_id=None):
    if not device_id: return
    conn = get_db()
    conn.execute("""INSERT INTO authorized_devices
        (device_id, status, stripe_customer_id, stripe_subscription_id, updated_at)
        VALUES(?, 'active', ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(device_id) DO UPDATE SET
        status = 'active',
        stripe_customer_id = excluded.stripe_customer_id,
        stripe_subscription_id = excluded.stripe_subscription_id,
        updated_at = CURRENT_TIMESTAMP""", (device_id, customer_id, subscription_id))
    conn.commit()
    conn.close()

def check_device_authorization(device_id):
    if not device_id: return False
    conn = get_db()
    row = conn.execute("SELECT status FROM authorized_devices WHERE device_id=?", (device_id,)).fetchone()
    conn.close()
    return bool(row and row["status"] == "active")

def deactivate_device_by_subscription(subscription_id):
    if not subscription_id: return
    conn = get_db()
    conn.execute("UPDATE authorized_devices SET status='inactive', updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?", (subscription_id,))
    conn.commit()
    conn.close()

init_db()

try:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception:
    gemini_client = None

SYSTEM_WELLNESS_PROMPT = """
You are the exclusive wellness and lifestyle advisor for the platform "AL CIELO", designed comprehensively for adults aged 50 and over. Your sessions are complete, thorough, and structured to guide a full 10-minute wellness and mobility experience.

CORE INSTRUCTION & SCOPE:
1. LEGAL SAFETY BLOCK: Every session strictly starts by stating clearly that this is a general wellness and lifestyle service, not a medical or diagnostic service, and that each person participates at their own personal discretion and comfort.
2. UNIVERSAL INCLUSIVITY & ADAPTATION: You must design and guide the session so it accommodates the diverse real-life conditions of adults 50+, including active individuals, people in wheelchairs, bedridden/encamados individuals, and those with physical limitations or the absence of one, two, or multiple limbs. Offer smooth alternative options for every movement so everyone can participate safely.
3. COMPREHENSIVE LENGTH & PACING: Provide rich, detailed, long-form session content designed to unfold progressively over a complete duration, ensuring deep coverage of breathing, gentle stretching, circulation, and relaxation.
4. EXERCISE FOCUS & REPETITION RULE: When you instruct the user to repeat an exercise, stay entirely focused on that same exercise. Give the user calm space, time, and human conversational pacing to perform the repetition fully before transitioning to anything else.
5. TONE & STYLE: Warm, direct, highly effective, empathetic, and professional. Zero medical jargon. Speak strictly as a lifestyle and wellness specialist.
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
        raise HTTPException(status_code=500, detail="Admin credentials not configured in Render environment variables.")
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
            raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY is missing in Render.")
        if not STRIPE_PRICE_ID:
            raise HTTPException(status_code=500, detail="STRIPE_PRICE_ID is missing in Render.")
        host = request.headers.get("host") or "al-cielo.onrender.com"
        base_url = f"https://{host}"
        checkout_session = stripe.checkout.Session.create(
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/cancel",
            metadata={"device_id": device_id}
        )
        return {"status": "success", "checkout_url": checkout_session.url}
    except HTTPException:
        raise
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Checkout error: {str(e)}")

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default=None)):
    payload = await request.body()
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET is missing in Render.")
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")

    event_type = event.get("type")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata") or {}
        device_id = metadata.get("device_id")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        if device_id:
            authorize_device(device_id, customer_id, subscription_id)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.unpaid"):
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
            raise HTTPException(status_code=400, detail="Device ID required.")
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(status_code=403, detail="Subscription required.")

        duration_desc = "30-second free preview" if is_hook else "comprehensive full 10-minute guided wellness and mobility session"
        lang_names = {"es": "Spanish", "en": "English", "pt": "Portuguese"}
        selected_lang_name = lang_names.get(language, "Spanish")
        prompt = f"""
Generate a [{duration_desc}] strictly in [{selected_lang_name}]
designed specifically for adults aged 50 and over, accommodating all real-life physical conditions (active participants, wheelchair users, bedridden/encamados individuals, and those with partial or complete absence of limbs).
Ensure the session is thorough, comprehensive, and properly paced for the full duration. Include natural human pauses and transitional phrases, and when an exercise is repeated, stay completely focused on that same movement until it is finished.
CRITICAL:
Output ONLY plain conversational sentences in {selected_lang_name}.
Do NOT mix languages.
Do NOT include any intro text.
"""
        response_text = ""
        if gemini_client:
            try:
                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=0.6
                    )
                )
                response_text = response.text or ""
            except Exception:
                response_text = ""

        if not response_text:
            if language == "en":
                response_text = "Welcome to AL CIELO. This is a general wellness and lifestyle session, designed for your personal comfort and participation at your own discretion. Whether you are active, seated, or resting in bed, and adapting to your own physical flexibility, let us begin. Take a comfortable posture. Inhale deeply through your nose, expanding your chest or abdomen gently, and exhale slowly through your mouth. Let us repeat this calming breath once more, taking all the time you need to feel fully relaxed. Now, gently mobilize your available joints, moving fingers, wrists, or shoulders with complete ease, staying right with this movement as you repeat it softly."
            elif language == "pt":
                response_text = "Bem-vindo ao AL CIELO. Este é um serviço de bem-estar geral e estilo de vida, para participação conforme o seu próprio conforto. Seja ativo, sentado ou acamado, adaptando-se às suas condições físicas, vamos iniciar. Adote uma postura confortável. Inspire profundamente pelo nariz e expire lentamente pela boca. Vamos repetir esta respiração relaxante mais uma vez, tomando todo o tempo necessário. Agora, mova suavemente as articulações disponíveis, dedicando atenção plena a este mesmo exercício antes de avançar."
            else:
                response_text = "Bienvenido a AL CIELO. Este es un servicio de bienestar general y estilo de vida; cada participante lo realiza bajo su propia comodidad y criterio personal. Adaptándonos a cada realidad, ya sea que se encuentre activo, en silla de ruedas o en cama, y contemplando cualquier condición de movilidad o extremidades, comencemos. Tome una postura cómoda. Inhale profundamente por la nariz y exhale despacio por la boca. Repitamos esta respiración profunda una vez más, tomándonos el tiempo necesario para sentir una calma absoluta. Ahora, con total tranquilidad, enfoquemos nuestra atención en movilizar suavemente las articulaciones y extremidades disponibles, repitiendo este mismo movimiento con calma y sin prisas."

        return {"status": "success", "session_content": response_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
