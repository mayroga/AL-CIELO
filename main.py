import os
import re
import json
import time
import uuid
import sqlite3
import asyncio
from pathlib import Path
from typing import Optional

import stripe
from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

try:
    import google.generativeai as genai
except Exception:
    genai=None

try:
    from openai import OpenAI
except Exception:
    OpenAI=None

APP_VERSION="4.2.0"
BASE_URL=os.getenv("BASE_URL","https://al-cielo.onrender.com").rstrip("/")
STRIPE_SECRET_KEY=os.getenv("STRIPE_SECRET_KEY","").strip()
STRIPE_PRICE_ID=os.getenv("STRIPE_PRICE_ID","").strip()
STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET","").strip()
ADMIN_USER=os.getenv("ADMIN_USER",os.getenv("ADMIN_USERNAME","")).strip()
ADMIN_PASS=os.getenv("ADMIN_PASS",os.getenv("ADMIN_PASSWORD","")).strip()
GEMINI_API_KEY=os.getenv("GEMINI_API_KEY","").strip()
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","").strip()
GEMINI_MODEL=os.getenv("GEMINI_MODEL","gemini-2.5-flash").strip()
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-4o-mini").strip()
DB_PATH=Path(os.getenv("AL_CIELO_DB","alcielo_licences.db"))

if STRIPE_SECRET_KEY:
    stripe.api_key=STRIPE_SECRET_KEY

app=FastAPI(title="AL CIELO - Production Engine",version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

def db():
    con=sqlite3.connect(DB_PATH)
    con.row_factory=sqlite3.Row
    return con

def init_db():
    con=db()
    con.execute("""
    CREATE TABLE IF NOT EXISTS authorized_devices(
        device_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        updated_at REAL NOT NULL
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS fallback_rotation(
        device_id TEXT PRIMARY KEY,
        position INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL
    )
    """)
    con.commit()
    con.close()

init_db()

def clean_text(value):
    if value is None:
        return ""
    value=str(value)
    value=value.replace("\r\n","\n").replace("\r","\n")
    value=re.sub(r"[ \t]+"," ",value)
    value=re.sub(r"\n{3,}","\n\n",value)
    return value.strip()

def device_clean(value):
    value=clean_text(value)
    if len(value)>200:
        value=value[:200]
    return value

def authorize_device(device_id,customer_id=None,subscription_id=None):
    device_id=device_clean(device_id)
    if not device_id:
        return False
    con=db()
    con.execute("""
    INSERT INTO authorized_devices
    (device_id,status,stripe_customer_id,stripe_subscription_id,updated_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(device_id) DO UPDATE SET
    status='active',
    stripe_customer_id=excluded.stripe_customer_id,
    stripe_subscription_id=excluded.stripe_subscription_id,
    updated_at=excluded.updated_at
    """,(device_id,"active",customer_id,subscription_id,time.time()))
    con.commit()
    con.close()
    return True

def check_device_authorization(device_id):
    device_id=device_clean(device_id)
    if not device_id:
        return False
    con=db()
    row=con.execute(
        "SELECT status FROM authorized_devices WHERE device_id=?",
        (device_id,)
    ).fetchone()
    con.close()
    return bool(row and row["status"]=="active")

def deactivate_device_by_subscription(subscription_id):
    if not subscription_id:
        return
    con=db()
    con.execute("""
    UPDATE authorized_devices
    SET status='inactive',updated_at=?
    WHERE stripe_subscription_id=?
    """,(time.time(),subscription_id))
    con.commit()
    con.close()

def next_fallback_index(device_id):
    device_id=device_clean(device_id) or "anonymous"
    con=db()
    row=con.execute(
        "SELECT position FROM fallback_rotation WHERE device_id=?",
        (device_id,)
    ).fetchone()
    if row is None:
        position=0
        con.execute(
            "INSERT INTO fallback_rotation(device_id,position,updated_at) VALUES(?,?,?)",
            (device_id,0,time.time())
        )
    else:
        position=(int(row["position"])+1)%20
        con.execute(
            "UPDATE fallback_rotation SET position=?,updated_at=? WHERE device_id=?",
            (position,time.time(),device_id)
        )
    con.commit()
    con.close()
    return position

def B(title,*instructions):
    return {
        "title":clean_text(title),
        "exercises":[
            {"title":f"Parte {i+1}","instruction":clean_text(x)}
            for i,x in enumerate(instructions)
        ]
    }

FALLBACK_SESSIONS_ES=[
B("Empieza con calma",
  "Siéntate o permanece en una posición cómoda. Deja que tu cuerpo descanse y toma una respiración tranquila.",
  "Lleva lentamente los hombros hacia arriba y después déjalos bajar. Hazlo sin apuro.",
  "Abre y cierra las manos varias veces. Nota el movimiento y mantén los brazos relajados.",
  "Mueve suavemente los pies o los tobillos dentro de lo que te resulte cómodo.",
  "Gira la cabeza lentamente hacia un lado y vuelve al centro. Después hazlo hacia el otro lado.",
  "Coloca la espalda de una manera cómoda y deja caer los hombros. Respira con tranquilidad.",
  "Permanece unos momentos sin hacer nada. Escucha tu respiración y permite que el cuerpo se calme.",
  "Termina despacio. Respira una vez más y continúa con tu día a tu propio ritmo."
),
B("Un momento para ti",
  "Busca una posición cómoda. No necesitas apresurarte; solamente comienza respirando con tranquilidad.",
  "Mueve los hombros hacia atrás suavemente y después déjalos descansar.",
  "Estira y relaja los dedos de las manos varias veces, sin hacer fuerza.",
  "Mueve lentamente los pies. Puedes hacerlo sentado o acostado, según te resulte más cómodo.",
  "Mira hacia un lado lentamente y regresa al centro. Después mira hacia el otro lado.",
  "Deja los brazos descansando y siente cómo cambia tu postura cuando aflojas los hombros.",
  "Haz una pausa tranquila. No necesitas conseguir nada en este momento.",
  "Respira cómodamente y termina esta parte con calma."
),
B("Movimiento tranquilo",
  "Comienza en la posición en la que estés más cómodo. Respira lentamente y prepara el cuerpo para moverse.",
  "Eleva un poco los hombros y suéltalos. Repite el movimiento con suavidad.",
  "Mueve las manos abriendo los dedos y cerrándolos lentamente.",
  "Haz pequeños movimientos con los tobillos o los pies, sin forzar.",
  "Lleva la mirada lentamente hacia un lado y vuelve al centro.",
  "Acomoda la espalda y deja que los hombros se relajen.",
  "Quédate quieto unos instantes y disfruta de la pausa.",
  "Finaliza respirando cómodamente y vuelve poco a poco a lo que estabas haciendo."
),
B("Respira y continúa",
  "Colócate cómodamente y toma una respiración natural antes de comenzar.",
  "Mueve los hombros hacia arriba y hacia abajo lentamente.",
  "Relaja las manos. Abre los dedos, ciérralos y vuelve a abrirlos.",
  "Haz un pequeño movimiento con los pies o los tobillos.",
  "Gira suavemente la cabeza hacia la derecha y regresa al centro.",
  "Gira suavemente la cabeza hacia la izquierda y regresa al centro.",
  "Descansa unos momentos y permite que el cuerpo permanezca tranquilo.",
  "Toma una respiración cómoda y termina sin prisa."
),
B("Despacio es suficiente",
  "Comienza donde estés. No tienes que cambiar nada rápidamente; solamente encuentra una posición cómoda.",
  "Levanta los hombros lentamente y déjalos caer.",
  "Mueve cada mano con tranquilidad, separando y juntando los dedos.",
  "Mueve los pies de manera suave, solamente hasta donde resulte cómodo.",
  "Mueve la cabeza lentamente hacia un lado y vuelve al centro.",
  "Acomoda el cuerpo y deja los brazos descansar.",
  "Haz una pausa y respira de manera natural.",
  "Cuando estés listo, termina lentamente y continúa con tu día."
),
B("Una pausa agradable",
  "Siéntate, recuéstate o permanece como estés cómodo. Comienza con una respiración tranquila.",
  "Haz un pequeño movimiento con los hombros y después déjalos completamente relajados.",
  "Abre las manos y vuelve a cerrarlas suavemente.",
  "Mueve los pies o los tobillos sin hacer fuerza.",
  "Mira lentamente hacia un lado y regresa al centro.",
  "Mira lentamente hacia el otro lado y regresa al centro.",
  "Permanece quieto unos segundos y disfruta de este momento.",
  "Termina respirando con naturalidad y vuelve a tu actividad."
),
B("Tu propio ritmo",
  "Empieza a tu propio ritmo. Elige una posición cómoda y respira sin cambiar tu forma natural de hacerlo.",
  "Sube un poco los hombros y permite que vuelvan a bajar.",
  "Mueve las manos lentamente y relaja los dedos.",
  "Haz pequeños movimientos con los pies.",
  "Gira la cabeza hacia un lado y vuelve al centro.",
  "Gira hacia el otro lado y vuelve al centro.",
  "Descansa el cuerpo y deja que los movimientos se detengan.",
  "Finaliza con una respiración tranquila."
),
B("Comienza suavemente",
  "Busca comodidad antes de comenzar. Respira tranquilamente y deja que el cuerpo se acomode.",
  "Mueve los hombros hacia arriba y después hacia abajo.",
  "Abre las manos lentamente y relaja los dedos.",
  "Mueve los pies o los tobillos de forma pequeña y cómoda.",
  "Lleva la cabeza lentamente hacia un lado y vuelve al centro.",
  "Lleva la cabeza lentamente hacia el otro lado y vuelve al centro.",
  "Haz una pausa sin movimiento y respira naturalmente.",
  "Termina despacio y vuelve a tu día."
),
B("Un pequeño descanso",
  "Haz una pausa donde estés. Encuentra una posición cómoda y empieza con una respiración tranquila.",
  "Relaja los hombros con un movimiento lento.",
  "Mueve los dedos de las manos varias veces.",
  "Mueve los pies suavemente.",
  "Mira hacia un lado y vuelve al centro.",
  "Mira hacia el otro lado y vuelve al centro.",
  "Permanece tranquilo y deja descansar el cuerpo.",
  "Termina lentamente y continúa cuando te sientas listo."
),
B("Sin prisa",
  "No necesitas hacer nada rápido. Colócate cómodamente y empieza con una respiración natural.",
  "Eleva un poco los hombros y déjalos descansar.",
  "Abre y cierra las manos con suavidad.",
  "Mueve los pies o tobillos lentamente.",
  "Gira la cabeza hacia un lado y vuelve al centro.",
  "Gira hacia el otro lado y vuelve al centro.",
  "Haz una pausa tranquila antes de terminar.",
  "Respira cómodamente y continúa con tu día."
),
B("Un momento tranquilo",
  "Comienza en una posición que te resulte cómoda. Respira naturalmente y permite que el momento sea tranquilo.",
  "Mueve los hombros lentamente y después relájalos.",
  "Mueve las manos y deja los dedos sueltos.",
  "Haz pequeños movimientos con los pies.",
  "Mueve la cabeza lentamente hacia un lado y vuelve al centro.",
  "Repite el movimiento hacia el otro lado.",
  "Quédate tranquilo durante unos momentos.",
  "Finaliza respirando con calma."
),
B("Poco a poco",
  "Comienza lentamente. Quédate sentado, recostado o en la posición que te resulte cómoda.",
  "Mueve los hombros suavemente y vuelve a relajarlos.",
  "Abre y cierra las manos sin hacer fuerza.",
  "Mueve los pies lentamente.",
  "Mira hacia un lado y vuelve al centro.",
  "Mira hacia el otro lado y vuelve al centro.",
  "Haz una pausa cómoda.",
  "Termina despacio."
),
B("Aquí y ahora",
  "Quédate en una posición cómoda y presta atención al momento presente mientras respiras naturalmente.",
  "Mueve los hombros una vez hacia arriba y después relájalos.",
  "Mueve lentamente los dedos de las manos.",
  "Haz un pequeño movimiento con los pies.",
  "Gira la cabeza suavemente hacia un lado y vuelve al centro.",
  "Haz lo mismo hacia el otro lado.",
  "Permanece quieto y disfruta de la pausa.",
  "Respira cómodamente y termina."
),
B("Tiempo para relajarte",
  "Busca una postura cómoda y empieza sin prisa. Deja que tu respiración siga su ritmo natural.",
  "Relaja los hombros con un movimiento lento.",
  "Mueve las manos y los dedos de manera suave.",
  "Mueve los pies o los tobillos dentro de lo cómodo.",
  "Gira lentamente la cabeza hacia un lado.",
  "Regresa al centro y gira lentamente hacia el otro lado.",
  "Haz una pausa sin movimiento.",
  "Termina respirando tranquilamente."
),
B("Movimiento amable",
  "Comienza con una posición cómoda. Respira naturalmente y permite que el cuerpo se mueva con suavidad.",
  "Eleva y baja los hombros lentamente.",
  "Abre y cierra las manos sin apretar.",
  "Mueve los pies suavemente.",
  "Mira hacia un lado y regresa al centro.",
  "Mira hacia el otro lado y regresa al centro.",
  "Descansa durante unos momentos.",
  "Finaliza lentamente."
),
B("Una respiración más",
  "Encuentra una posición cómoda y toma una respiración natural para comenzar.",
  "Mueve los hombros lentamente y déjalos descansar.",
  "Mueve los dedos de las manos con suavidad.",
  "Haz pequeños movimientos con los pies.",
  "Gira la cabeza lentamente hacia un lado y vuelve al centro.",
  "Gira hacia el otro lado y vuelve al centro.",
  "Permanece tranquilo y disfruta de la pausa.",
  "Toma una respiración cómoda y termina."
),
B("Calma sencilla",
  "Comienza cómodamente. No necesitas cambiar tu respiración; solamente deja que sea natural.",
  "Mueve los hombros lentamente hacia arriba y hacia abajo.",
  "Relaja las manos y mueve los dedos.",
  "Mueve los pies o los tobillos de forma suave.",
  "Gira lentamente la cabeza hacia un lado y vuelve al centro.",
  "Gira lentamente hacia el otro lado y vuelve al centro.",
  "Descansa unos instantes.",
  "Termina con tranquilidad."
),
B("Un descanso para el cuerpo",
  "Busca comodidad y permite que el cuerpo descanse mientras comienzas lentamente.",
  "Mueve los hombros y déjalos relajados.",
  "Mueve las manos y los dedos sin hacer fuerza.",
  "Mueve los pies suavemente.",
  "Gira la cabeza lentamente hacia un lado y vuelve al centro.",
  "Gira hacia el otro lado y vuelve al centro.",
  "Haz una pausa tranquila.",
  "Finaliza lentamente."
),
B("Continúa con tranquilidad",
  "Comienza desde la posición en la que estés. Respira naturalmente y toma este momento con calma.",
  "Mueve los hombros suavemente.",
  "Mueve las manos y relaja los dedos.",
  "Haz pequeños movimientos con los pies.",
  "Mira hacia un lado lentamente y vuelve al centro.",
  "Mira hacia el otro lado lentamente y vuelve al centro.",
  "Quédate quieto unos instantes.",
  "Respira cómodamente y continúa."
),
B("Un momento sencillo",
  "Colócate cómodamente y comienza con una respiración natural.",
  "Sube los hombros suavemente y déjalos bajar.",
  "Abre y cierra las manos lentamente.",
  "Mueve los pies o los tobillos suavemente.",
  "Gira la cabeza hacia un lado y vuelve al centro.",
  "Gira hacia el otro lado y vuelve al centro.",
  "Haz una pausa y deja descansar el cuerpo.",
  "Termina con calma."
),
B("Termina a tu ritmo",
  "Comienza lentamente desde una posición cómoda. No hay necesidad de apresurarse.",
  "Mueve los hombros suavemente y relájalos.",
  "Mueve los dedos de las manos lentamente.",
  "Mueve los pies dentro de lo que resulte cómodo.",
  "Gira la cabeza lentamente hacia un lado y regresa al centro.",
  "Gira hacia el otro lado y regresa al centro.",
  "Permanece tranquilo y disfruta de unos segundos de descanso.",
  "Respira naturalmente y termina cuando estés listo."
)
]

if len(FALLBACK_SESSIONS_ES)!=20:
    raise RuntimeError("AL CIELO requiere exactamente 20 respaldos.")

FALLBACK_TEXT={
"es":{
"title":"Un momento para ti",
"hook":"Siéntate o permanece cómodo. Respira naturalmente y comienza lentamente.",
},
"en":{
"title":"A moment for you",
"hook":"Sit comfortably or remain where you are. Breathe naturally and begin slowly.",
},
"pt":{
"title":"Um momento para você",
"hook":"Sente-se confortavelmente ou permaneça onde está. Respire naturalmente e comece devagar."
}
}

def translate_fallback(base,language):
    if language=="es":
        return base
    if language=="en":
        return {
            "title":"A calm moment",
            "exercises":[
                {"title":x["title"],"instruction":x["instruction"]} for x in base["exercises"]
            ]
        }
    return {
        "title":"Um momento tranquilo",
        "exercises":[
            {"title":x["title"],"instruction":x["instruction"]} for x in base["exercises"]
        ]
    }

def fallback_session(device_id,language,is_hook=False):
    if is_hook:
        data=FALLBACK_TEXT.get(language,FALLBACK_TEXT["es"])
        return {
            "title":data["title"],
            "exercises":[
                {"title":"Comenzar" if language=="es" else ("Begin" if language=="en" else "Começar"),
                 "instruction":data["hook"]}
            ]
        }
    index=next_fallback_index(device_id)
    base=FALLBACK_SESSIONS_ES[index]
    return translate_fallback(base,language)

def valid_instruction(value):
    value=clean_text(value)
    if not value:
        return False
    if len(value)<20 or len(value)>700:
        return False
    forbidden=[
        "chatgpt","openai","gemini","artificial intelligence",
        "inteligencia artificial","medical","médico","medicina",
        "diagnosis","diagnóstico","therapy","terapia","treatment",
        "tratamiento"
    ]
    low=value.lower()
    return not any(x in low for x in forbidden)

def normalize_session(data,language,is_hook=False):
    if not isinstance(data,dict):
        return None
    title=clean_text(data.get("title",""))
    exercises=data.get("exercises")
    if not isinstance(exercises,list):
        return None
    result=[]
    for item in exercises:
        if not isinstance(item,dict):
            continue
        instruction=clean_text(item.get("instruction",""))
        item_title=clean_text(item.get("title",""))
        if valid_instruction(instruction):
            result.append({
                "title":item_title[:100] or f"Parte {len(result)+1}",
                "instruction":instruction
            })
    if is_hook:
        if not result:
            return None
        return {
            "title":title[:150] or FALLBACK_TEXT[language]["title"],
            "exercises":result[:1]
        }
    if len(result)<8:
        return None
    return {
        "title":title[:150] or FALLBACK_TEXT[language]["title"],
        "exercises":result[:8]
    }

def parse_ai_session(raw,language,is_hook=False):
    if not raw:
        return None
    raw=clean_text(raw)
    raw=re.sub(r"^```(?:json)?","",raw,flags=re.I).strip()
    raw=re.sub(r"```$","",raw).strip()
    try:
        data=json.loads(raw)
        return normalize_session(data,language,is_hook)
    except Exception:
        match=re.search(r"\{.*\}",raw,re.S)
        if match:
            try:
                data=json.loads(match.group(0))
                return normalize_session(data,language,is_hook)
            except Exception:
                return None
    return None

def session_to_text(session):
    if not session:
        return ""
    parts=[]
    for ex in session.get("exercises",[]):
        parts.append(clean_text(ex.get("instruction","")))
    return "\n\n".join(x for x in parts if x)

def language_quality(session,language):
    if not session:
        return False
    text=session_to_text(session).lower()
    if language=="es":
        markers=[" el "," la "," que "," para "," con ","respira"]
    elif language=="en":
        markers=[" the "," and "," your "," with "," breathe"]
    else:
        markers=[" o "," para "," com "," você "," respire"]
    hits=sum(1 for x in markers if x in f" {text} ")
    return hits>=2

async def call_gemini(language,is_hook=False):
    if not GEMINI_API_KEY or genai is None:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model=genai.GenerativeModel(GEMINI_MODEL)
        lang={"es":"Spanish","en":"English","pt":"Portuguese"}.get(language,"Spanish")
        count=1 if is_hook else 8
        prompt=f"""
Create a spoken wellness routine in {lang}.
Return ONLY valid JSON.
Format:
{{"title":"short title","exercises":[{{"title":"short label","instruction":"one spoken paragraph"}}]}}
Create exactly {count} exercise paragraphs.
Each instruction must be one complete paragraph.
Each paragraph should be short enough to speak comfortably.
Do not number the paragraphs inside instruction.
Do not mention AI, ChatGPT, Gemini, phases, diagnosis, medicine, therapy or treatment.
Do not give medical advice.
Use simple human language.
The title is visual only and must NOT contain instructions.
"""
        response=await asyncio.wait_for(
            asyncio.to_thread(model.generate_content,prompt),
            timeout=25
        )
        return response.text if response else None
    except Exception:
        return None

async def call_openai(language,is_hook=False):
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    try:
        client=OpenAI(api_key=OPENAI_API_KEY)
        lang={"es":"Spanish","en":"English","pt":"Portuguese"}.get(language,"Spanish")
        count=1 if is_hook else 8
        prompt=f"""
Create a spoken wellness routine in {lang}.
Return ONLY valid JSON:
{{"title":"short title","exercises":[{{"title":"short label","instruction":"one complete spoken paragraph"}}]}}
Exactly {count} exercises.
Every instruction must be one complete paragraph.
Keep each paragraph concise.
The title is visual only and must not contain instructions.
Do not mention AI, ChatGPT, Gemini, phases, diagnosis, medicine, therapy or treatment.
Do not give medical advice.
Use simple human language.
"""
        result=await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            temperature=.85,
            messages=[
                {"role":"system","content":"Return only valid JSON."},
                {"role":"user","content":prompt}
            ]
        )
        return result.choices[0].message.content if result and result.choices else None
    except Exception:
        return None

@app.get("/",response_class=HTMLResponse)
async def home():
    path=Path("static/index.html")
    if path.exists():
        return FileResponse(path)
    return HTMLResponse("<h1>AL CIELO</h1><p>Servicio disponible.</p>")

@app.get("/health")
async def health():
    return {
        "status":"ok",
        "service":"AL CIELO",
        "version":APP_VERSION,
        "base_url":BASE_URL
    }

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request:Request):
    try:
        body=await request.json()
    except Exception:
        return JSONResponse({"status":"error","message":"Solicitud inválida."},status_code=400)
    device_id=device_clean(body.get("device_id",""))
    username=clean_text(body.get("username",""))
    password=clean_text(body.get("password",""))
    if not device_id:
        return JSONResponse({"status":"error","message":"Falta el dispositivo."},status_code=400)
    if not ADMIN_USER or not ADMIN_PASS:
        return JSONResponse({"status":"error","message":"Acceso administrativo no configurado."},status_code=503)
    if username!=ADMIN_USER or password!=ADMIN_PASS:
        return JSONResponse({"status":"error","message":"Credenciales no válidas."},status_code=401)
    authorize_device(device_id)
    return {"status":"success","authorized":True,"device_id":device_id}

@app.get("/api/v1/access-status")
async def access_status(device_id:str=""):
    device_id=device_clean(device_id)
    return {
        "status":"success",
        "authorized":check_device_authorization(device_id),
        "device_id":device_id
    }

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request:Request):
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return JSONResponse(
            {"status":"error","message":"Stripe no está configurado correctamente."},
            status_code=503
        )
    try:
        body=await request.json()
    except Exception:
        return JSONResponse({"status":"error","message":"Solicitud inválida."},status_code=400)

    device_id=device_clean(body.get("device_id",""))
    if not device_id:
        return JSONResponse(
            {"status":"error","message":"No se encontró el dispositivo."},
            status_code=400
        )

    try:
        checkout=stripe.checkout.Session.create(
            line_items=[
                {
                    "price":STRIPE_PRICE_ID,
                    "quantity":1
                }
            ],
            mode="subscription",
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}&device_id={device_id}",
            cancel_url=f"{BASE_URL}/cancel?device_id={device_id}",
            metadata={
                "device_id":device_id
            },
            allow_promotion_codes=True
        )
        return {
            "status":"success",
            "checkout_url":checkout.url,
            "session_id":checkout.id,
            "return_url":BASE_URL
        }
    except stripe.error.StripeError as e:
        return JSONResponse(
            {"status":"error","message":str(e)},
            status_code=502
        )
    except Exception as e:
        return JSONResponse(
            {"status":"error","message":str(e)},
            status_code=500
        )

@app.post("/webhook/stripe")
async def stripe_webhook(
    request:Request,
    stripe_signature:Optional[str]=Header(default=None,alias="Stripe-Signature")
):
    payload=await request.body()

    if not STRIPE_WEBHOOK_SECRET:
        return JSONResponse({"status":"error","message":"Webhook no configurado."},status_code=503)

    try:
        event=stripe.Webhook.construct_event(
            payload,
            stripe_signature,
            STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return JSONResponse({"status":"error","message":"Payload inválido."},status_code=400)
    except stripe.error.SignatureVerificationError:
        return JSONResponse({"status":"error","message":"Firma Stripe inválida."},status_code=400)

    event_type=event.get("type","")
    obj=event.get("data",{}).get("object",{})

    if event_type=="checkout.session.completed":
        metadata=obj.get("metadata") or {}
        device_id=device_clean(metadata.get("device_id",""))
        customer_id=obj.get("customer")
        subscription_id=obj.get("subscription")
        payment_status=obj.get("payment_status")

        if device_id and payment_status in ("paid","no_payment_required"):
            authorize_device(
                device_id,
                customer_id,
                subscription_id
            )

    elif event_type in (
        "customer.subscription.deleted",
        "customer.subscription.unpaid"
    ):
        subscription_id=obj.get("id")
        deactivate_device_by_subscription(subscription_id)

    return {"received":True}

@app.get("/success",response_class=HTMLResponse)
async def success(
    session_id:str="",
    device_id:str=""
):
    safe_device=device_clean(device_id)
    paid=False

    if session_id and STRIPE_SECRET_KEY:
        try:
            session=stripe.checkout.Session.retrieve(session_id)
            paid=session.get("payment_status") in ("paid","no_payment_required")
            metadata=session.get("metadata") or {}
            if not safe_device:
                safe_device=device_clean(metadata.get("device_id",""))
        except Exception:
            paid=False

    page=f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AL CIELO</title>
<style>
html,body{{margin:0;background:#000;color:#fff;font-family:Arial,sans-serif;min-height:100%;}}
body{{display:flex;align-items:center;justify-content:center;text-align:center;}}
main{{width:min(700px,92%);padding:40px 20px;}}
h1{{font-size:42px;margin:0 0 24px;}}
p{{font-size:24px;line-height:1.5;}}
button{{margin-top:24px;padding:18px 28px;border:0;border-radius:12px;font-size:22px;cursor:pointer;}}
</style>
</head>
<body>
<main>
<h1>AL CIELO</h1>
<p id="message">Estamos preparando tu acceso.</p>
<button id="open" onclick="openService()" style="display:none">Entrar a AL CIELO</button>
</main>
<script>
const BASE="{BASE_URL}";
const DEVICE={json.dumps(safe_device)};
const PAID={str(paid).lower()};
let tries=0;
function openService(){{
  window.location.replace(BASE+"/");
}}
async function check(){{
  tries++;
  try{{
    const r=await fetch(BASE+"/api/v1/access-status?device_id="+encodeURIComponent(DEVICE),{{cache:"no-store"}});
    const d=await r.json();
    if(d.authorized){{
      document.getElementById("message").textContent="Tu acceso está listo. Abriendo AL CIELO...";
      setTimeout(openService,700);
      return;
    }}
  }}catch(e){{}}
  if(tries<30){{
    document.getElementById("message").textContent="Confirmando tu pago y preparando AL CIELO...";
    setTimeout(check,1000);
  }}else{{
    document.getElementById("message").textContent="El pago fue recibido. Puedes entrar a AL CIELO.";
    document.getElementById("open").style.display="inline-block";
  }}
}}
if(PAID){{check();}}
else{{
  document.getElementById("message").textContent="No pudimos confirmar el pago todavía.";
  document.getElementById("open").style.display="inline-block";
}}
</script>
</body>
</html>
"""
    return HTMLResponse(page)

@app.get("/cancel",response_class=HTMLResponse)
async def cancel():
    return HTMLResponse(f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AL CIELO</title>
<style>
html,body{{margin:0;background:#000;color:#fff;font-family:Arial,sans-serif;}}
body{{display:flex;justify-content:center;text-align:center;}}
main{{width:min(700px,92%);padding:60px 20px;}}
h1{{font-size:42px;}}
p{{font-size:24px;line-height:1.5;}}
a{{display:inline-block;margin-top:24px;padding:18px 28px;background:#fff;color:#000;text-decoration:none;border-radius:12px;font-size:22px;}}
</style>
</head>
<body>
<main>
<h1>AL CIELO</h1>
<p>El pago no fue completado.</p>
<a href="{BASE_URL}/">Volver a AL CIELO</a>
</main>
</body>
</html>
""")

@app.post("/api/v1/generate-session")
async def generate_session(request:Request):
    try:
        body=await request.json()
    except Exception:
        return JSONResponse({"status":"error","message":"Solicitud inválida."},status_code=400)

    device_id=device_clean(body.get("device_id",""))
    language=clean_text(body.get("language","es")).lower()
    is_hook=bool(body.get("is_hook",False))

    if language not in ("es","en","pt"):
        language="es"

    if not is_hook and not check_device_authorization(device_id):
        return JSONResponse(
            {
                "status":"payment_required",
                "authorized":False,
                "message":"Se necesita acceso activo para iniciar la sesión completa."
            },
            status_code=402
        )

    session=None
    source=None

    raw=await call_gemini(language,is_hook)
    if raw:
        candidate=parse_ai_session(raw,language,is_hook)
        if candidate and language_quality(candidate,language):
            session=candidate
            source="gemini"

    if session is None:
        raw=await call_openai(language,is_hook)
        if raw:
            candidate=parse_ai_session(raw,language,is_hook)
            if candidate and language_quality(candidate,language):
                session=candidate
                source="openai"

    if session is None:
        session=fallback_session(device_id,language,is_hook)
        source="fallback"

    return {
        "status":"success",
        "authorized":True if is_hook else check_device_authorization(device_id),
        "language":language,
        "source":source,
        "session":session,
        "session_content":session_to_text(session),
        "speech_rule":"Leer solamente instruction. Nunca leer title.",
        "timing_rule":"El intervalo comienza solamente después de terminar de hablar cada párrafo."
    }

@app.get("/api/v1/config")
async def config():
    return {
        "status":"success",
        "service":"AL CIELO",
        "version":APP_VERSION,
        "base_url":BASE_URL,
        "languages":["es","en","pt"],
        "fallback_backups":20,
        "stripe_enabled":bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)
    }
