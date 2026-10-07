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

app = FastAPI(title="AL CIELO - Production Engine", version="3.8.0")
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
3. NEVER include internal ID numbers, random codes, or technical tags in the text output.
4. IF THIS IS A FREE 30-SECOND PREVIEW (is_hook=true):
   - Provide a quick, light greeting and a single simple breathing action that lasts about 30 seconds when read aloud.
5. IF THIS IS THE FULL 10-MINUTE SESSION (is_hook=false) - APPLIES TO STRIPE AND USERNAME/PASSWORD:
   - Act as a live personal trainer. Write an extensive, deep, continuous, and highly detailed routine designed to take a full 10 minutes of calm, slow spoken practice.
   - Include inclusive instructions: if a user lacks limbs or mobility, guide them to perform the movements mentally or focus on available joints (fingers, neck, shoulders, breathing).
   - Break down the flow naturally into continuous paragraphs with plenty of descriptive pacing and pauses.
"""


# BANCO DE 10 TEXTOS DE RESPALDO VARIADOS Y PROFESIONALES (PARA GARANTIZAR QUE NUNCA SE REPITA LO MISMO)
FALLBACK_SESSIONS_ES = [
    "Bienvenido a su sesión de bienestar de hoy. Tómese un instante para acomodarse con total comodidad, ya sea sentado en su sillón favorito o recostado en su cama. Vamos a comenzar llevando una suave atención a su respiración, sintiendo cómo el aire entra fresco y sale aliviando cualquier tensión. Permita que sus hombros desciendan de forma natural, soltando el peso del día. Si puede mover sus manos y dedos, hágalo de manera muy pausada, y si prefiere el reposo absoluto, acompañe el proceso sintiendo el apoyo firme de su cuerpo. Inhale despacio, sostenga un momento, y exhale con suavidad mientras recorremos juntos este espacio de calma y renovación interior.",
    "Comenzamos este espacio dedicado enteramente a su descanso y equilibrio físico. Ubíquese en la posición que hoy le resulte más placentera y segura. Dirigiremos la atención hacia el cuello y la cabeza, realizando un movimiento imperceptible de lado a lado solo si su cuerpo se lo permite, o visualizando el movimiento con serenidad. Sienta cómo la mandíbula se relaja y la frente se despeja. Vamos a tomar el control del ritmo respiratorio: inhalamos profundamente contando hasta cuatro, retenemos con suavidad y exhalamos lentamente liberando todo el cansancio acumulado. Disfrute de este momento de atención plena diseñado especialmente para usted.",
    "Un cordial saludo en esta nueva sesión de cuidado personal. Conéctese con su bienestar adoptando una postura de apoyo firme y relajada. Hoy nos enfocaremos en la apertura del pecho y la expansión de la respiración. Si tiene movilidad en sus brazos, deslícelos con delicadeza; de lo contrario, concéntrese en la expansión del tórax al compás del aire. Note el contacto de su espalda con el respaldo o la superficie de descanso. Cada exhalación es una oportunidad para soltar las preocupaciones y regalarle a su organismo un respiro profundo, ordenado y completamente seguro.",
    "Le damos la más cordial bienvenida a su pausa activa y restaurativa de hoy. Sin importar si se encuentra en plena actividad, sentado o descansando en cama, la atención está puesta en su confort. Vamos a llevar una suave conciencia hacia los puntos de apoyo de su cuerpo: la espalda, las piernas o los brazos. Comience a notar el latido calmado de su corazón y acompáñelo con respiraciones largas y profundas. Si le es posible, mueva milimétricamente las muñecas o los tobillos; si no, permita que la visualización y la respiración hagan el trabajo de relajar cada fibra muscular.",
    "Iniciamos este momento de conexión y bienestar con total tranquilidad. Acomódese y cierre los ojos si le apetece, dejando que la voz le guíe paso a paso. Hoy trabajaremos la liberación de tensiones en la parte superior del cuerpo. Relaje los músculos de la cara, deje caer los hombros alejándolos de las orejas y respire hondo. Si alguna zona del cuerpo presenta rigidez o limitaciones, no la force; simplemente obsérvela con bondad y envíele una respiración cálida. Sienta cómo el bienestar recorre su organismo de pies a cabeza en un flujo constante y apacible.",
    "Bienvenido a su rutina de relajación y movilidad adaptada. Tome aire de manera natural y profunda, permitiendo que el abdomen se expanda suavemente. Vamos a realizar un recorrido mental por todo su cuerpo, reconociendo cada parte con gratitud y cuidado. Si tiene movilidad en sus extremidades, haga pequeños círculos muy lentos con las manos o los pies; si se encuentra en reposo, imagine el movimiento fluyendo con total armonía. Mantenga una respiracióncompasiva y constante, disfrutando del silencio y de la compañía de este espacio de salud.",
    "Es un placer acompañarle en este espacio de bienestar estructurado para su comodidad. Sintonice con el momento presente ajustando su postura hasta encontrar el punto exacto de descanso. Vamos a enfocar la atención en el centro de su cuerpo, el área del pecho, permitiendo que cada inhalación traiga energía renovada y cada exhalación se lleve cualquier molestia. Mantenga los brazos y las piernas en la posición que le brinde mayor alivio, guiándose únicamente por el ritmo pausado de una respiración consciente.",
    "Comenzamos una nueva práctica enfocada en su paz interior y confort físico. Adopte una postura que le otorgue soporte y seguridad. Vamos a relajar los dedos de las manos, los brazos y la columna vertebral mediante respiraciones profundas y dirigidas. Si alguna extremidad no tiene movilidad, su mente y su respiración cumplen el rol principal activando la circulación y la relajación profunda. Permítase desconectarse del exterior y habitar este instante de tranquilidad absoluta.",
    "Bienvenido a su sesión de revitalización y calma. Busque la postura más cómoda disponible para usted en este momento. Dirigiremos la atención hacia la zona de los hombros y la espalda alta, imaginando que una brisa suave disuelve cualquier rigidez. Tome una inspiración profunda, llene sus pulmones sin prisa y deje salir el aire lentamente por la boca. Sienta cómo el cuerpo se afloja y se entrega al descanso reparador, manteniendo siempre una práctica segura, libre de exigencias y diseñada a su medida.",
    "Cerramos nuestro ciclo de recomendaciones de bienestar con una sesión centrada en la serenidad absoluta. Acomódese con la certeza de que este tiempo le pertenece por completo. Vamos a unificar la respiración con pequeños movimientos conscientes o con una visualización profunda de ligereza. Sienta el soporte que lo sostiene, relaje cada músculo facial y permita que el aire fluya sin obstáculos. Disfrute de la estabilidad y la paz que este espacio le otorga en cada segundo."
]


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
        
        # Semilla completamente limpia basada en tiempo para garantizar variedad pura en la IA
        unique_prompt_modifier = random.choice([
            "Focus heavily on shoulder relaxation and upper body comfort.",
            "Focus heavily on hand, finger, and wrist gentle micro-movements.",
            "Focus heavily on breathing rhythm and spine posture alignment.",
            "Focus heavily on deep mental relaxation and physical resting support.",
            "Focus heavily on gentle neck relief and facial tension release."
        ])
        
        if is_hook:
            prompt = f"""
Generate a strict 30-SECOND FREE PREVIEW in [{selected_lang_name}].
Keep it extremely brief (max 50 words): a warm greeting and one single gentle breathing action. Do not say the word phase. No codes or IDs.
Output ONLY plain conversational text in {selected_lang_name}. No titles.
"""
            max_tokens = 150
        else:
            prompt = f"""
{unique_prompt_modifier}
Generate a completely unique, extensive, deep, continuous, and professional 10-MINUTE GUIDED WELLNESS SESSION strictly in [{selected_lang_name}]
for adults aged 50 and over, inclusive of active, seated, resting, or poststrated individuals (including those with limited mobility or missing limbs).
Act strictly as a live human personal wellness trainer guiding the user step by step in real time. 
DO NOT use the word 'fase' or 'phase' or any robotic section labels. DO NOT include any random numbers, IDs, or tags.
Vary the exercise sequence, phrasing, and focus compared to standard routines so it feels completely fresh and unique. 
Write a rich, continuous, deeply detailed coaching routine that flows naturally from gentle joint micro-movements, postural comfort adjustments, and sensory awareness into deep breathing exercises, providing enough descriptive pacing, pauses, and actionable coaching cues to comfortably fill 10 full minutes of calm spoken practice.
Output ONLY plain conversational text in {selected_lang_name}. No meta-commentary or titles.
"""
            max_tokens = 3000

        response_text = ""

        # INTENTO 1: GEMINI (con límite de 20 segundos)
        if gemini_client:
            try:
                response_task = asyncio.to_thread(
                    gemini_client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=0.98,
                        max_output_tokens=max_tokens,
                    )
                )
                gemini_response = await asyncio.wait_for(response_task, timeout=20.0)
                response_text = gemini_response.text or ""
            except Exception:
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
                    temperature=0.98,
                    max_tokens=max_tokens
                )
                openai_response = await asyncio.wait_for(openai_task, timeout=20.0)
                response_text = openai_response.choices[0].message.content or ""
            except Exception:
                response_text = ""

        # BANCO DE RESPALDO ROTATIVO (10 OPCIONES DIFERENTES SELECCIONADAS AL AZAR)
        if not response_text or len(response_text) < 200:
            if is_hook:
                response_text = "Muestra Gratuita (30s): Bienvenido a AL CIELO. Adopte una postura cómoda, inhale hondo por la nariz y relaje suavemente sus hombros."
            else:
                # Selecciona aleatoriamente uno de los 10 textos largos diferentes del banco
                response_text = random.choice(FALLBACK_SESSIONS_ES)

        return {"status": "success", "session_content": response_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
