import os,sqlite3,random,asyncio,json,re
from fastapi import FastAPI,HTTPException,Request,Header
from fastapi.responses import HTMLResponse,FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
import openai

app=FastAPI(title="AL CIELO - Production Engine",version="4.0.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

stripe.api_key=os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID=os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET")
ADMIN_USER=os.getenv("ADMIN_USER") or os.getenv("ADMIN_USERNAME")
ADMIN_PASS=os.getenv("ADMIN_PASS") or os.getenv("ADMIN_PASSWORD")
DB_FILE="alcielo_licences.db"

try:
    gemini_client=genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception:
    gemini_client=None

openai_api_key=os.getenv("OPENAI_API_KEY")
openai_client=openai.OpenAI(api_key=openai_api_key) if openai_api_key else None

def get_db():
    conn=sqlite3.connect(DB_FILE)
    conn.row_factory=sqlite3.Row
    return conn

def init_db():
    conn=get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS authorized_devices(
        device_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def authorize_device(device_id,customer_id=None,subscription_id=None):
    if not device_id:return
    conn=get_db()
    conn.execute("""INSERT INTO authorized_devices
        (device_id,status,stripe_customer_id,stripe_subscription_id,updated_at)
        VALUES(?,'active',?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(device_id) DO UPDATE SET
        status='active',
        stripe_customer_id=excluded.stripe_customer_id,
        stripe_subscription_id=excluded.stripe_subscription_id,
        updated_at=CURRENT_TIMESTAMP""",(device_id,customer_id,subscription_id))
    conn.commit()
    conn.close()

def check_device_authorization(device_id):
    if not device_id:return False
    conn=get_db()
    row=conn.execute("SELECT status FROM authorized_devices WHERE device_id=?",(device_id,)).fetchone()
    conn.close()
    return bool(row and row["status"]=="active")

def deactivate_device_by_subscription(subscription_id):
    if not subscription_id:return
    conn=get_db()
    conn.execute("UPDATE authorized_devices SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",(subscription_id,))
    conn.commit()
    conn.close()

init_db()

SYSTEM_WELLNESS_PROMPT="""
You are the professional human-like wellness and lifestyle companion for AL CIELO.
The service is designed for adults 50 and over and must be inclusive of people who are active,
seated, resting, using a bed, have limited mobility, or have different physical abilities.

Your communication must be warm,direct,calm,clear,kind,professional and easy to follow.
The user must never feel overwhelmed.

STRICT RULES:
1. Never mention AI,ChatGPT,internal systems,codes,IDs,audits,phases or technical processes.
2. Never use medical or clinical terminology and never present the service as medical treatment,
diagnosis,therapy,rehabilitation or medical advice.
3. This is lifestyle,comfort,relaxation,gentle movement and personal wellbeing guidance.
4. Every instruction must be adaptable. If a movement is not comfortable or cannot be performed,
the person may remain still,visualize the movement,or use whatever comfortable movement is available.
5. Never force a movement.
6. Never create fear or alarming language.
7. Do not repeat an identical session. Vary the order,focus,wording and exercises.
8. Use the language requested by the user.
9. Do not mix languages.
10. Do not use headings such as Phase,Fase or technical labels inside the exercise instructions.
11. A full session must be divided into short,professional exercises. Each exercise should be
easy to read and perform before continuing.
12. Each exercise should contain a short title and clear instructions.
13. Avoid giant paragraphs.
14. Do not include internal numbers,IDs,JSON commentary or explanations outside the requested format.
"""

LANG_NAMES={"es":"Spanish","en":"English","pt":"Portuguese"}

FALLBACK_TEXT={
"es":{
"title":"Tu momento de bienestar",
"start":"Acomódate en una posición que te resulte cómoda. No necesitas hacer nada con prisa.",
"breath":"Respira lentamente por la nariz y deja salir el aire con suavidad. Repite dos veces a tu propio ritmo.",
"shoulders":"Deja que los hombros descansen. Si te resulta cómodo, muévelos suavemente hacia arriba y déjalos bajar. También puedes imaginar el movimiento.",
"hands":"Si tienes movimiento disponible, abre y cierra lentamente las manos. Si prefieres permanecer quieto, presta atención a la sensación de descanso en tus manos.",
"neck":"Mantén la cabeza en una posición cómoda. Si te resulta natural, gira muy suavemente la mirada hacia un lado y luego hacia el otro. Sin forzar.",
"posture":"Observa cómo te sostiene la silla,el sillón o la cama. Permite que tu cuerpo descanse sobre ese apoyo.",
"pause":"Quédate unos instantes tranquilo. Respira normalmente y disfruta de este pequeño espacio para ti.",
"close":"Haz una última respiración tranquila. Cuando estés preparado, continúa tu día conservando esta sensación de calma."
},
"en":{
"title":"Your wellbeing moment",
"start":"Settle into a position that feels comfortable. There is no need to do anything quickly.",
"breath":"Breathe slowly through your nose and let the air out gently. Repeat twice at your own pace.",
"shoulders":"Let your shoulders rest. If comfortable, gently lift them and allow them to lower. You may also simply imagine the movement.",
"hands":"If movement is available to you, slowly open and close your hands. If you prefer to remain still, notice the feeling of rest in your hands.",
"neck":"Keep your head in a comfortable position. If it feels natural, gently turn your gaze to one side and then the other. Do not force it.",
"posture":"Notice how the chair,the armchair or the bed supports you. Allow your body to rest on that support.",
"pause":"Stay still for a few moments. Breathe normally and enjoy this small space for yourself.",
"close":"Take one final calm breath. When you are ready, continue your day while keeping this sense of calm."
},
"pt":{
"title":"Seu momento de bem-estar",
"start":"Acomode-se em uma posição confortável para você. Não é preciso fazer nada com pressa.",
"breath":"Respire lentamente pelo nariz e solte o ar com suavidade. Repita duas vezes no seu próprio ritmo.",
"shoulders":"Deixe os ombros descansarem. Se for confortável,mova-os suavemente para cima e deixe-os descer. Você também pode apenas imaginar o movimento.",
"hands":"Se tiver movimento disponível,abra e feche as mãos lentamente. Se preferir permanecer parado,perceba a sensação de descanso nas mãos.",
"neck":"Mantenha a cabeça em uma posição confortável. Se for natural para você,gire suavemente o olhar para um lado e depois para o outro. Sem forçar.",
"posture":"Perceba como a cadeira,a poltrona ou a cama sustenta você. Permita que o corpo descanse sobre esse apoio.",
"pause":"Fique tranquilo por alguns instantes. Respire normalmente e aproveite este pequeno espaço para você.",
"close":"Faça uma última respiração tranquila. Quando estiver preparado,continue o seu dia mantendo essa sensação de calma."
}
}

def make_fallback(language,is_hook=False):
    language=language if language in FALLBACK_TEXT else "es"
    t=FALLBACK_TEXT[language]
    if is_hook:
        return {
            "title":t["title"],
            "exercises":[
                {"title":t["title"],"instruction":t["start"]+" "+t["breath"]}
            ]
        }
    variants=[
        [("Acomodarse",t["start"]),("Respirar",t["breath"]),("Soltar los hombros",t["shoulders"]),("Manos",t["hands"]),("Cuello y mirada",t["neck"]),("Encontrar apoyo",t["posture"]),("Pausa tranquila",t["pause"]),("Cerrar el momento",t["close"])],
        [("Comenzar con calma",t["start"]),("Respiración tranquila",t["breath"]),("Descanso de hombros",t["shoulders"]),("Movimiento de manos",t["hands"]),("Mirada cómoda",t["neck"]),("Sentir el apoyo",t["posture"]),("Un instante para ti",t["pause"]),("Finalizar",t["close"])],
        [("Encontrar comodidad",t["start"]),("Tomar aire con calma",t["breath"]),("Hombros relajados",t["shoulders"]),("Dedos y manos",t["hands"]),("Cuello cómodo",t["neck"]),("Apoyo y descanso",t["posture"]),("Respirar y disfrutar",t["pause"]),("Continuar el día",t["close"])]
    ]
    selected=random.choice(variants)
    return {"title":t["title"],"exercises":[{"title":a,"instruction":b} for a,b in selected]}

def clean_text(value):
    if not isinstance(value,str):return ""
    value=value.replace("\r\n","\n").replace("\r","\n")
    value=re.sub(r"```(?:json)?","",value,flags=re.I)
    value=value.replace("```","")
    return value.strip()

def normalize_session(data,language,is_hook=False):
    if not isinstance(data,dict):return None
    title=clean_text(data.get("title",""))
    raw=data.get("exercises")
    if not isinstance(raw,list):return None
    exercises=[]
    for item in raw:
        if not isinstance(item,dict):continue
        et=clean_text(item.get("title",""))
        ei=clean_text(item.get("instruction",""))
        if et and ei:
            exercises.append({"title":et,"instruction":ei})
    if not exercises:return None
    if is_hook:exercises=exercises[:1]
    else:exercises=exercises[:10]
    if len(exercises)<(1 if is_hook else 5):return None
    if not title:title=FALLBACK_TEXT.get(language,FALLBACK_TEXT["es"])["title"]
    return {"title":title,"exercises":exercises}

def session_to_text(session):
    if not session:return ""
    return "\n\n".join(f"{x['title']}\n{x['instruction']}" for x in session.get("exercises",[]))

def parse_ai_session(text,language,is_hook=False):
    text=clean_text(text)
    if not text:return None
    try:
        data=json.loads(text)
        return normalize_session(data,language,is_hook)
    except Exception:
        pass
    match=re.search(r"\{.*\}",text,re.S)
    if match:
        try:
            data=json.loads(match.group(0))
            return normalize_session(data,language,is_hook)
        except Exception:
            pass
    return None

def language_quality(text,language):
    if not text:return False
    low=text.lower()
    if language=="pt":
        forbidden=["bienvenido","respira","acomódate","hombros","ejercicio","puedes","mantén","suavemente"]
        return sum(1 for x in forbidden if x in low)<3
    if language=="en":
        forbidden=["bienvenido","acomódate","hombros","respira","puedes","suavemente"]
        return sum(1 for x in forbidden if x in low)<3
    return True

@app.get("/",response_class=FileResponse)
async def serve_frontend():
    return "index.html"

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request:Request):
    body=await request.json()
    username=str(body.get("username","")).strip()
    password=str(body.get("password","")).strip()
    device_id=str(body.get("device_id","")).strip()
    if not ADMIN_USER or not ADMIN_PASS:
        raise HTTPException(status_code=500,detail="Admin credentials not configured in Render environment variables.")
    if username==ADMIN_USER and password==ADMIN_PASS and device_id:
        authorize_device(device_id)
        return {"status":"success"}
    raise HTTPException(status_code=401,detail="Invalid credentials.")

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request:Request):
    try:
        body=await request.json()
        device_id=str(body.get("device_id","")).strip()
        if not device_id:raise HTTPException(status_code=400,detail="Device ID required.")
        if not stripe.api_key:raise HTTPException(status_code=500,detail="STRIPE_SECRET_KEY is missing in Render.")
        if not STRIPE_PRICE_ID:raise HTTPException(status_code=500,detail="STRIPE_PRICE_ID is missing in Render.")
        host=request.headers.get("host") or "al-cielo.onrender.com"
        base_url=f"https://{host}"
        checkout_session=stripe.checkout.Session.create(
            line_items=[{"price":STRIPE_PRICE_ID,"quantity":1}],
            mode="subscription",
            success_url=f"{base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/cancel",
            metadata={"device_id":device_id}
        )
        return {"status":"success","checkout_url":checkout_session.url}
    except HTTPException:
        raise
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502,detail=f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500,detail=f"Checkout error: {str(e)}")

@app.post("/webhook/stripe")
async def stripe_webhook(request:Request,stripe_signature:str=Header(default=None)):
    payload=await request.body()
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500,detail="STRIPE_WEBHOOK_SECRET is missing in Render.")
    if not stripe_signature:
        raise HTTPException(status_code=400,detail="Missing Stripe-Signature header.")
    try:
        event=stripe.Webhook.construct_event(payload,stripe_signature,STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400,detail="Invalid webhook payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400,detail="Invalid Stripe webhook signature.")
    except Exception as e:
        raise HTTPException(status_code=400,detail=f"Webhook error: {str(e)}")

    event_type=event.get("type")
    if event_type=="checkout.session.completed":
        session=event["data"]["object"]
        metadata=session.get("metadata") or {}
        device_id=metadata.get("device_id")
        customer_id=session.get("customer")
        subscription_id=session.get("subscription")
        if device_id:authorize_device(device_id,customer_id,subscription_id)
    elif event_type in ("customer.subscription.deleted","customer.subscription.unpaid"):
        subscription=event["data"]["object"]
        deactivate_device_by_subscription(subscription.get("id"))
    return {"status":"success"}

@app.get("/success",response_class=HTMLResponse)
async def payment_success(session_id:str=None):
    verified=False
    if session_id:
        try:
            session=stripe.checkout.Session.retrieve(session_id)
            if session.get("payment_status")=="paid":verified=True
        except Exception:
            verified=False
    if verified:
        return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;"><h1 style="color:#4ade80;">Payment Received</h1><p>Stripe received your payment.</p><p>Your access will be activated after Stripe confirms the subscription.</p><a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return to AL CIELO</a></body></html>"""
    return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;"><h1 style="color:#f87171;">Payment Not Confirmed</h1><p>We could not verify the payment with Stripe.</p><a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return to AL CIELO</a></body></html>"""

@app.get("/cancel",response_class=HTMLResponse)
async def payment_cancel():
    return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;"><h1 style="color:#f87171;">Payment Canceled</h1><p>No subscription was activated.</p><a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return Home</a></body></html>"""

@app.post("/api/v1/generate-session")
async def generate_session(request:Request):
    try:
        body=await request.json()
        device_id=str(body.get("device_id","")).strip()
        language=str(body.get("language","es")).lower().strip()
        is_hook=bool(body.get("is_hook",False))

        if language not in LANG_NAMES:language="es"
        if not device_id:raise HTTPException(status_code=400,detail="Device id required.")
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(status_code=403,detail="Subscription or login required for full session.")

        selected_lang_name=LANG_NAMES[language]
        focus=random.choice({
            "es":[
                "centra la sesión en comodidad de hombros y brazos",
                "centra la sesión en manos,dedos y pequeños movimientos disponibles",
                "centra la sesión en respiración tranquila y postura cómoda",
                "centra la sesión en relajación del rostro,cuello y atención tranquila",
                "centra la sesión en una combinación variada de respiración,descanso y movimiento suave"
            ],
            "en":[
                "focus on shoulder and arm comfort",
                "focus on hands,fingers and small available movements",
                "focus on calm breathing and comfortable posture",
                "focus on facial and neck relaxation with calm awareness",
                "use a varied combination of breathing,rest and gentle movement"
            ],
            "pt":[
                "concentre a sessão no conforto dos ombros e braços",
                "concentre a sessão nas mãos,dedos e pequenos movimentos disponíveis",
                "concentre a sessão na respiração tranquila e na postura confortável",
                "concentre a sessão no relaxamento do rosto,pescoço e atenção tranquila",
                "use uma combinação variada de respiração,descanso e movimento suave"
            ]
        }[language])

        if is_hook:
            prompt=f"""
Create a short free preview in {selected_lang_name}.
Return ONLY valid JSON with this exact structure:
{{"title":"short title","exercises":[{{"title":"short title","instruction":"short instruction"}}]}}
Use exactly ONE exercise.
The preview should take about 30 seconds when spoken.
{focus}.
Do not use medical language.
Do not use the words phase or fase.
Do not mix languages.
"""
            max_tokens=250
        else:
            prompt=f"""
Create a professional guided wellbeing session in {selected_lang_name}.
Return ONLY valid JSON. Do not add markdown,comments or text before or after the JSON.

Required structure:
{{
"title":"short welcoming title",
"exercises":[
{{"title":"short exercise title","instruction":"clear concise instruction"}},
{{"title":"short exercise title","instruction":"clear concise instruction"}}
]
}}

Create exactly 8 exercises.
The complete session should comfortably support approximately 10 minutes when the user follows
the pauses and instructions slowly.

{focus}.

Each exercise must be short enough to read without overwhelming the user.
Each exercise must have:
- a clear human title
- one compact instruction section
- simple pacing
- a comfortable action or quiet awareness
- inclusive alternatives for limited movement when appropriate

Do not make one giant paragraph.
Do not repeat the same instruction excessively.
Do not use the words phase or fase.
Do not use medical,clinical,diagnostic or treatment language.
Do not mention AI,ChatGPT,systems,codes,IDs or internal processes.
Do not mix languages.
Do not include exercise numbers in the text.
"""
            max_tokens=2800

        response_text=""

        if gemini_client:
            try:
                task=asyncio.to_thread(
                    gemini_client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=0.85,
                        max_output_tokens=max_tokens
                    )
                )
                result=await asyncio.wait_for(task,timeout=20.0)
                response_text=result.text or ""
            except Exception:
                response_text=""

        if not response_text and openai_client:
            try:
                task=asyncio.to_thread(
                    openai_client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=[
                        {"role":"system","content":SYSTEM_WELLNESS_PROMPT},
                        {"role":"user","content":prompt}
                    ],
                    temperature=0.85,
                    max_tokens=max_tokens
                )
                result=await asyncio.wait_for(task,timeout=20.0)
                response_text=result.choices[0].message.content or ""
            except Exception:
                response_text=""

        session=parse_ai_session(response_text,language,is_hook) if response_text else None

        if session:
            quality_text=session_to_text(session)
            if not language_quality(quality_text,language):
                session=None

        if not session:
            session=make_fallback(language,is_hook)

        session_content=session_to_text(session)

        return {
            "status":"success",
            "language":language,
            "session":session,
            "session_content":session_content
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500,detail=str(e))
