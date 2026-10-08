import os,re,json,time,sqlite3,asyncio
from pathlib import Path
from typing import Optional
import stripe
from fastapi import FastAPI,Request,Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse

try:
    import google.generativeai as genai
except Exception:
    genai=None
try:
    from openai import OpenAI
except Exception:
    OpenAI=None

APP_VERSION="4.3.0"
BASE_URL="https://al-cielo.onrender.com"
STRIPE_SECRET_KEY=os.getenv("STRIPE_SECRET_KEY","").strip()
STRIPE_PRICE_ID=os.getenv("STRIPE_PRICE_ID","").strip()
STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET","").strip()
ADMIN_USER=os.getenv("ADMIN_USER",os.getenv("ADMIN_USERNAME","")).strip()
ADMIN_PASS=os.getenv("ADMIN_PASS",os.getenv("ADMIN_PASSWORD","")).strip()
GEMINI_API_KEY=os.getenv("GEMINI_API_KEY","").strip()
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","").strip()
GEMINI_MODEL=os.getenv("GEMINI_MODEL","gemini-2.5-flash").strip()
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-4o-mini").strip()
DB_PATH=Path("alcielo_licences.db")
INDEX_PATH=Path("index.html")

if STRIPE_SECRET_KEY:
    stripe.api_key=STRIPE_SECRET_KEY

app=FastAPI(title="AL CIELO - Production Engine",version=APP_VERSION)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

def db():
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS authorized_devices(
    device_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'active',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    updated_at REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS fallback_rotation(
    device_id TEXT NOT NULL,
    language TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY(device_id,language))""")
    c.commit()
    c.close()

init_db()

def clean(v):
    if v is None:return ""
    v=str(v).replace("\r\n","\n").replace("\r","\n")
    v=re.sub(r"[ \t]+"," ",v)
    v=re.sub(r"\n{3,}","\n\n",v)
    return v.strip()

def device(v):
    return clean(v)[:200]

def authorize_device(device_id,customer_id=None,subscription_id=None):
    device_id=device(device_id)
    if not device_id:return False
    c=db()
    c.execute("""INSERT INTO authorized_devices
    (device_id,status,stripe_customer_id,stripe_subscription_id,updated_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(device_id) DO UPDATE SET
    status='active',
    stripe_customer_id=excluded.stripe_customer_id,
    stripe_subscription_id=excluded.stripe_subscription_id,
    updated_at=excluded.updated_at""",
    (device_id,"active",customer_id,subscription_id,time.time()))
    c.commit()
    c.close()
    return True

def authorized(device_id):
    device_id=device(device_id)
    if not device_id:return False
    c=db()
    r=c.execute("SELECT status FROM authorized_devices WHERE device_id=?",(device_id,)).fetchone()
    c.close()
    return bool(r and r["status"]=="active")

def deactivate_subscription(subscription_id):
    if not subscription_id:return
    c=db()
    c.execute("UPDATE authorized_devices SET status='inactive',updated_at=? WHERE stripe_subscription_id=?",(time.time(),subscription_id))
    c.commit()
    c.close()

def next_backup(device_id,language):
    device_id=device(device_id) or "anonymous"
    language=language if language in ("es","en","pt") else "es"
    c=db()
    r=c.execute("SELECT position FROM fallback_rotation WHERE device_id=? AND language=?",(device_id,language)).fetchone()
    if r is None:
        p=0
        c.execute("INSERT INTO fallback_rotation(device_id,language,position,updated_at) VALUES(?,?,?,?)",(device_id,language,p,time.time()))
    else:
        p=(int(r["position"])+1)%20
        c.execute("UPDATE fallback_rotation SET position=?,updated_at=? WHERE device_id=? AND language=?",(p,time.time(),device_id,language))
    c.commit()
    c.close()
    return p

def E(title,es,en,pt):
    return {
        "es":{"title":title[0],"instruction":es},
        "en":{"title":title[1],"instruction":en},
        "pt":{"title":title[2],"instruction":pt}
    }

FALLBACK_SESSIONS=[
E(
("Comienza con calma","Begin calmly","Comece com calma"),
"Busca una posición cómoda, sentado o recostado. Deja que tu cuerpo descanse y toma una respiración natural antes de continuar.",
"Find a comfortable position, seated or resting. Let your body settle and take a natural breath before continuing.",
"Encontre uma posição confortável, sentado ou descansando. Deixe o corpo relaxar e respire naturalmente antes de continuar."
),
E(
("Un momento para ti","A moment for you","Um momento para você"),
"Permanece cómodo y permite que este momento sea solamente para ti. Respira a tu propio ritmo y no tengas prisa por comenzar.",
"Stay comfortable and let this moment be just for you. Breathe at your own pace and do not rush to begin.",
"Permaneça confortável e deixe este momento ser somente para você. Respire no seu próprio ritmo e não tenha pressa para começar."
),
E(
("Hombros tranquilos","Relaxed shoulders","Ombros tranquilos"),
"Lleva lentamente los hombros un poco hacia arriba y después déjalos bajar. Haz el movimiento con suavidad y vuelve a una posición cómoda.",
"Slowly bring your shoulders slightly upward and then let them drop. Move gently and return to a comfortable position.",
"Levante os ombros suavemente e depois deixe-os baixar. Faça o movimento devagar e volte a uma posição confortável."
),
E(
("Manos relajadas","Relaxed hands","Mãos relaxadas"),
"Abre las manos lentamente, separa los dedos y después vuelve a relajarlos. Repite el movimiento sin apretar ni hacer fuerza.",
"Slowly open your hands, spread your fingers, and then relax them again. Repeat without squeezing or forcing the movement.",
"Abra as mãos devagar, afaste os dedos e depois relaxe novamente. Repita sem apertar nem fazer força."
),
E(
("Pies en movimiento","Moving your feet","Movendo os pés"),
"Mueve suavemente los pies o los tobillos dentro de lo que te resulte cómodo. Haz movimientos pequeños y tranquilos.",
"Gently move your feet or ankles within a comfortable range. Keep the movements small and easy.",
"Mova suavemente os pés ou os tornozelos dentro do que for confortável. Faça movimentos pequenos e tranquilos."
),
E(
("Mira lentamente","Look slowly","Olhe devagar"),
"Mueve lentamente la mirada hacia un lado y después regresa al centro. Quédate cómodo y deja que el movimiento sea natural.",
"Slowly turn your gaze to one side and then return to the center. Stay comfortable and let the movement feel natural.",
"Mova lentamente o olhar para um lado e depois volte ao centro. Permaneça confortável e deixe o movimento ser natural."
),
E(
("Al otro lado","The other side","Para o outro lado"),
"Ahora lleva lentamente la mirada hacia el otro lado y vuelve al centro. Hazlo con tranquilidad y sin necesidad de llegar más lejos.",
"Now slowly turn your gaze to the other side and return to the center. Take your time and do not try to go farther.",
"Agora mova lentamente o olhar para o outro lado e volte ao centro. Faça com calma e sem tentar ir além."
),
E(
("Descansa","Rest","Descanse"),
"Deja los brazos y las manos descansando. Permanece unos momentos sin hacer ningún movimiento y respira de manera natural.",
"Let your arms and hands rest. Stay still for a few moments and breathe naturally.",
"Deixe os braços e as mãos descansarem. Fique alguns momentos sem se mover e respire naturalmente."
),
E(
("Acomódate","Get comfortable","Acomode-se"),
"Acomoda tu cuerpo de la manera que te resulte más agradable. No necesitas cambiar mucho; solamente busca comodidad.",
"Adjust your body in whatever way feels most comfortable. You do not need to change much; simply find a comfortable position.",
"Acomode o corpo da maneira que for mais agradável. Você não precisa mudar muito; apenas encontre uma posição confortável."
),
E(
("Respira tranquilo","Breathe calmly","Respire com calma"),
"Permite que tu respiración siga su ritmo natural. No necesitas hacerla más profunda ni más rápida; solamente continúa con tranquilidad.",
"Let your breathing follow its natural rhythm. You do not need to make it deeper or faster; simply continue calmly.",
"Deixe a respiração seguir seu ritmo natural. Você não precisa respirar mais fundo ou mais rápido; apenas continue com calma."
),
E(
("Movimiento pequeño","Small movement","Movimento pequeno"),
"Elige un movimiento pequeño que te resulte cómodo y hazlo lentamente. Después regresa a una posición de descanso.",
"Choose a small movement that feels comfortable and do it slowly. Then return to a resting position.",
"Escolha um pequeno movimento que seja confortável e faça-o devagar. Depois volte a uma posição de descanso."
),
E(
("Sin prisa","No rush","Sem pressa"),
"Continúa a tu propio ritmo. No hay necesidad de apresurarse; permite que cada movimiento termine antes de comenzar otro.",
"Continue at your own pace. There is no need to hurry; let each movement finish before beginning another.",
"Continue no seu próprio ritmo. Não há necessidade de pressa; deixe cada movimento terminar antes de começar outro."
),
E(
("Pausa tranquila","Quiet pause","Pausa tranquila"),
"Haz una pausa y permanece cómodo. Observa cómo se siente estar tranquilo durante unos momentos.",
"Take a pause and remain comfortable. Notice what it feels like to be still for a few moments.",
"Faça uma pausa e permaneça confortável. Perceba como é ficar tranquilo por alguns momentos."
),
E(
("Vuelve al centro","Return to center","Volte ao centro"),
"Regresa suavemente a una posición cómoda y centrada. Deja que los hombros y las manos descansen.",
"Return gently to a comfortable centered position. Let your shoulders and hands rest.",
"Volte suavemente para uma posição confortável e centralizada. Deixe os ombros e as mãos descansarem."
),
E(
("Un poco más","A little more","Mais um pouco"),
"Continúa unos momentos más con movimientos suaves. Elige solamente aquello que se sienta cómodo para ti.",
"Continue for a few more moments with gentle movements. Choose only what feels comfortable for you.",
"Continue por mais alguns momentos com movimentos suaves. Escolha apenas aquilo que for confortável para você."
),
E(
("Quédate cómodo","Stay comfortable","Fique confortável"),
"Permanece en la posición que te resulte cómoda. Respira naturalmente y deja que el cuerpo tenga un momento de descanso.",
"Remain in the position that feels comfortable. Breathe naturally and give your body a moment to rest.",
"Permaneça na posição que for confortável. Respire naturalmente e dê ao corpo um momento de descanso."
),
E(
("Presta atención","Pay attention","Preste atenção"),
"Presta atención a los movimientos que estás haciendo, sin intentar cambiarlos demasiado. Mantén todo sencillo y tranquilo.",
"Notice the movements you are making without trying to change them too much. Keep everything simple and calm.",
"Perceba os movimentos que está fazendo sem tentar mudá-los demais. Mantenha tudo simples e tranquilo."
),
E(
("Última pausa","Final pause","Última pausa"),
"Quédate tranquilo durante unos momentos. Permite que la pausa termine de manera natural antes de continuar.",
"Stay quiet for a few moments. Let the pause finish naturally before continuing.",
"Fique tranquilo por alguns momentos. Deixe a pausa terminar naturalmente antes de continuar."
),
E(
("Termina a tu ritmo","Finish at your pace","Termine no seu ritmo"),
"Termina lentamente. Toma una respiración natural, permanece cómodo y continúa con tu día cuando estés listo.",
"Finish slowly. Take a natural breath, remain comfortable, and continue with your day when you are ready.",
"Termine devagar. Respire naturalmente, permaneça confortável e continue seu dia quando estiver pronto."
),
E(
("Un último momento","One last moment","Um último momento"),
"Antes de terminar, permanece cómodo unos segundos más. Respira naturalmente y deja que este momento concluya sin prisa.",
"Before finishing, stay comfortable for a few more seconds. Breathe naturally and let this moment end without rushing.",
"Antes de terminar, fique confortável por mais alguns segundos. Respire naturalmente e deixe este momento terminar sem pressa."
)
]

if len(FALLBACK_SESSIONS)!=20:
    raise RuntimeError(f"AL CIELO requiere exactamente 20 respaldos y encontró {len(FALLBACK_SESSIONS)}.")

def fallback_session(device_id,language,is_hook=False):
    if is_hook:
        hooks={
            "es":{"title":"Comienza","instruction":"Busca una posición cómoda y toma una respiración natural. Comienza lentamente."},
            "en":{"title":"Begin","instruction":"Find a comfortable position and take a natural breath. Begin slowly."},
            "pt":{"title":"Comece","instruction":"Encontre uma posição confortável e respire naturalmente. Comece devagar."}
        }
        return {"title":hooks[language]["title"],"exercises":[{"title":hooks[language]["title"],"instruction":hooks[language]["instruction"]}]}
    p=next_backup(device_id,language)
    data=[x[language] for x in FALLBACK_SESSIONS[p]]
    return {
        "title":data[0]["title"],
        "exercises":[
            {"title":x["title"],"instruction":x["instruction"]} for x in data
        ]
    }

def valid_instruction(v):
    v=clean(v)
    if len(v)<20 or len(v)>700:return False
    bad=("chatgpt","openai","gemini","inteligencia artificial","artificial intelligence","diagnóstico","diagnosis","terapia","therapy","tratamiento","treatment")
    return not any(x in v.lower() for x in bad)

def normalize_session(data,language,is_hook=False):
    if not isinstance(data,dict):return None
    exs=data.get("exercises")
    if not isinstance(exs,list):return None
    result=[]
    for x in exs:
        if not isinstance(x,dict):continue
        instruction=clean(x.get("instruction",""))
        title=clean(x.get("title",""))
        if valid_instruction(instruction):
            result.append({"title":title[:100] or f"Parte {len(result)+1}","instruction":instruction})
    needed=1 if is_hook else 8
    if len(result)<needed:return None
    return {"title":clean(data.get("title",""))[:150] or "AL CIELO","exercises":result[:needed]}

def parse_session(raw,language,is_hook=False):
    if not raw:return None
    raw=clean(raw)
    raw=re.sub(r"^```json","",raw,flags=re.I).strip()
    raw=re.sub(r"^```","",raw).strip()
    raw=re.sub(r"```$","",raw).strip()
    try:
        return normalize_session(json.loads(raw),language,is_hook)
    except Exception:
        m=re.search(r"\{.*\}",raw,re.S)
        if not m:return None
        try:return normalize_session(json.loads(m.group(0)),language,is_hook)
        except Exception:return None

def language_ok(session,language):
    if not session:return False
    text=" ".join(x["instruction"] for x in session["exercises"]).lower()
    markers={
        "es":[" el "," la "," que "," para "," con "," y "],
        "en":[" the "," and "," your "," with "," to "],
        "pt":[" o "," a "," para "," com "," você "," e "]
    }[language]
    return sum(1 for m in markers if m in f" {text} ")>=2

def session_text(session):
    return "\n\n".join(x["instruction"] for x in session.get("exercises",[]))

async def gemini_session(language,is_hook=False):
    if not GEMINI_API_KEY or genai is None:return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model=genai.GenerativeModel(GEMINI_MODEL)
        lang={"es":"Spanish","en":"English","pt":"Portuguese"}[language]
        n=1 if is_hook else 8
        prompt=f"""Create a simple spoken wellness routine in {lang}.
Return ONLY JSON.
{{"title":"short visual title","exercises":[{{"title":"short visual label","instruction":"complete spoken paragraph"}}]}}
Exactly {n} exercises.
Every instruction must be one complete paragraph.
Each paragraph must be concise enough to speak comfortably.
The title is visual only and must never contain the spoken instruction.
Do not mention AI, ChatGPT, Gemini, phases, diagnosis, medicine, therapy or treatment.
Do not give medical advice.
Use simple human language."""
        r=await asyncio.wait_for(asyncio.to_thread(model.generate_content,prompt),timeout=25)
        return r.text if r else None
    except Exception:return None

async def openai_session(language,is_hook=False):
    if not OPENAI_API_KEY or OpenAI is None:return None
    try:
        client=OpenAI(api_key=OPENAI_API_KEY)
        lang={"es":"Spanish","en":"English","pt":"Portuguese"}[language]
        n=1 if is_hook else 8
        prompt=f"""Create a simple spoken wellness routine in {lang}.
Return ONLY valid JSON:
{{"title":"short visual title","exercises":[{{"title":"short visual label","instruction":"complete spoken paragraph"}}]}}
Exactly {n} exercises.
Each instruction is one complete paragraph.
Keep every paragraph concise.
The title is visual only.
Do not mention AI, ChatGPT, Gemini, phases, diagnosis, medicine, therapy or treatment.
Do not give medical advice."""
        r=await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            temperature=.85,
            messages=[
                {"role":"system","content":"Return only valid JSON."},
                {"role":"user","content":prompt}
            ])
        return r.choices[0].message.content if r and r.choices else None
    except Exception:return None

@app.get("/")
async def index():
    if not INDEX_PATH.exists():
        return HTMLResponse("<h1>AL CIELO</h1><p>No se encontró index.html.</p>",status_code=500)
    return FileResponse(INDEX_PATH,media_type="text/html")

@app.get("/health")
async def health():
    return {"status":"ok","service":"AL CIELO","version":APP_VERSION,"base_url":BASE_URL,"backups":20}

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

@app.get("/api/v1/access-status")
async def access_status(device_id:str=""):
    device_id=device(device_id)
    return {"status":"success","authorized":authorized(device_id),"device_id":device_id}

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request:Request):
    try:b=await request.json()
    except Exception:return JSONResponse({"status":"error","message":"Solicitud inválida."},status_code=400)
    device_id=device(b.get("device_id",""))
    username=clean(b.get("username",""))
    password=clean(b.get("password",""))
    if not ADMIN_USER or not ADMIN_PASS:
        return JSONResponse({"status":"error","message":"Acceso administrativo no configurado."},status_code=503)
    if username!=ADMIN_USER or password!=ADMIN_PASS:
        return JSONResponse({"status":"error","message":"Credenciales no válidas."},status_code=401)
    authorize_device(device_id)
    return {"status":"success","authorized":True,"device_id":device_id}

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request:Request):
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return JSONResponse({"status":"error","message":"Stripe no está configurado correctamente."},status_code=503)
    try:b=await request.json()
    except Exception:return JSONResponse({"status":"error","message":"Solicitud inválida."},status_code=400)
    device_id=device(b.get("device_id",""))
    if not device_id:
        return JSONResponse({"status":"error","message":"No se encontró el dispositivo."},status_code=400)
    try:
        checkout=stripe.checkout.Session.create(
            line_items=[{"price":STRIPE_PRICE_ID,"quantity":1}],
            mode="subscription",
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}&device_id={device_id}",
            cancel_url=f"{BASE_URL}/cancel",
            metadata={"device_id":device_id},
            allow_promotion_codes=True
        )
        return {"status":"success","checkout_url":checkout.url,"session_id":checkout.id,"return_url":BASE_URL}
    except stripe.error.StripeError as e:
        return JSONResponse({"status":"error","message":str(e)},status_code=502)
    except Exception as e:
        return JSONResponse({"status":"error","message":str(e)},status_code=500)

@app.post("/webhook/stripe")
async def stripe_webhook(request:Request,stripe_signature:Optional[str]=Header(default=None,alias="Stripe-Signature")):
    payload=await request.body()
    if not STRIPE_WEBHOOK_SECRET:
        return JSONResponse({"status":"error","message":"Webhook no configurado."},status_code=503)
    try:
        event=stripe.Webhook.construct_event(payload,stripe_signature,STRIPE_WEBHOOK_SECRET)
    except ValueError:return JSONResponse({"status":"error","message":"Payload inválido."},status_code=400)
    except stripe.error.SignatureVerificationError:return JSONResponse({"status":"error","message":"Firma Stripe inválida."},status_code=400)

    typ=event.get("type","")
    obj=event.get("data",{}).get("object",{})

    if typ=="checkout.session.completed":
        metadata=obj.get("metadata") or {}
        did=device(metadata.get("device_id",""))
        payment=obj.get("payment_status")
        customer=obj.get("customer")
        subscription=obj.get("subscription")
        if did and payment in ("paid","no_payment_required"):
            authorize_device(did,customer,subscription)

    elif typ in ("customer.subscription.deleted","customer.subscription.unpaid"):
        deactivate_subscription(obj.get("id"))

    return {"received":True}

@app.get("/success",response_class=HTMLResponse)
async def success(session_id:str="",device_id:str=""):
    did=device(device_id)
    paid=False
    if session_id and STRIPE_SECRET_KEY:
        try:
            s=stripe.checkout.Session.retrieve(session_id)
            paid=s.get("payment_status") in ("paid","no_payment_required")
            meta=s.get("metadata") or {}
            if not did:did=device(meta.get("device_id",""))
        except Exception:pass

    html=f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AL CIELO</title>
<style>
*{{box-sizing:border-box}}html,body{{margin:0;background:#000;color:#fff;font-family:Arial,sans-serif}}body{{min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center}}main{{width:min(700px,92%);padding:30px}}h1{{font-size:52px}}p{{font-size:25px;line-height:1.5}}button{{font-size:23px;padding:18px 28px;border:0;border-radius:12px;cursor:pointer}}
</style>
</head>
<body>
<main>
<h1>AL CIELO</h1>
<p id="msg">Estamos preparando tu acceso.</p>
<button id="go" onclick="go()" style="display:none">ENTRAR A AL CIELO</button>
</main>
<script>
const BASE="{BASE_URL}";
const DID={json.dumps(did)};
const PAID={str(paid).lower()};
let tries=0;
function go(){{window.location.replace(BASE+"/");}}
async function verify(){{
tries++;
try{{
const r=await fetch(BASE+"/api/v1/access-status?device_id="+encodeURIComponent(DID),{{cache:"no-store"}});
const d=await r.json();
if(d.authorized){{
document.getElementById("msg").textContent="Tu acceso está listo. Abriendo AL CIELO...";
setTimeout(go,600);
return;
}}
}}catch(e){{}}
if(tries<40){{
document.getElementById("msg").textContent="Confirmando tu pago y preparando AL CIELO...";
setTimeout(verify,750);
}}else{{
document.getElementById("msg").textContent="El pago fue recibido. Puedes entrar a AL CIELO.";
document.getElementById("go").style.display="inline-block";
}}
}}
if(PAID)verify();
else{{
document.getElementById("msg").textContent="No pudimos confirmar el pago todavía.";
document.getElementById("go").style.display="inline-block";
}}
</script>
</body>
</html>"""
    return HTMLResponse(html)

@app.get("/cancel",response_class=HTMLResponse)
async def cancel():
    return HTMLResponse(f"""<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AL CIELO</title>
<style>
html,body{{margin:0;background:#000;color:#fff;font-family:Arial,sans-serif}}body{{min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center}}main{{width:min(700px,92%);padding:30px}}h1{{font-size:50px}}p{{font-size:25px;line-height:1.5}}a{{display:inline-block;padding:18px 28px;background:#fff;color:#000;text-decoration:none;border-radius:12px;font-size:23px}}
</style></head>
<body><main><h1>AL CIELO</h1><p>El pago no fue completado.</p><a href="{BASE_URL}/">VOLVER A AL CIELO</a></main></body></html>""")

@app.post("/api/v1/generate-session")
async def generate_session(request:Request):
    try:b=await request.json()
    except Exception:return JSONResponse({"status":"error","message":"Solicitud inválida."},status_code=400)

    did=device(b.get("device_id",""))
    language=clean(b.get("language","es")).lower()
    is_hook=bool(b.get("is_hook",False))
    if language not in ("es","en","pt"):language="es"

    if not is_hook and not authorized(did):
        return JSONResponse({"status":"payment_required","authorized":False,"message":"Se necesita acceso activo."},status_code=402)

    session=None
    source=None

    raw=await gemini_session(language,is_hook)
    if raw:
        candidate=parse_session(raw,language,is_hook)
        if candidate and language_ok(candidate,language):
            session=candidate
            source="gemini"

    if session is None:
        raw=await openai_session(language,is_hook)
        if raw:
            candidate=parse_session(raw,language,is_hook)
            if candidate and language_ok(candidate,language):
                session=candidate
                source="openai"

    if session is None:
        session=fallback_session(did,language,is_hook)
        source="fallback"

    return {
        "status":"success",
        "authorized":True,
        "language":language,
        "source":source,
        "session":session,
        "session_content":session_text(session),
        "speech_rule":"Leer solamente instruction. Nunca leer title.",
        "timing_rule":"Los 6 segundos comienzan solamente después de terminar completamente la lectura del párrafo."
    }
