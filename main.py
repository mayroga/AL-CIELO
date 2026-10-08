import os,re,json,time,sqlite3,asyncio
from pathlib import Path
from typing import Optional
import stripe
from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse

APP_VERSION="4.4.0"
BASE_URL="https://al-cielo.onrender.com"
DB_PATH=Path("alcielo_licences.db")
INDEX_PATH=Path("index.html")

STRIPE_SECRET_KEY=os.getenv("STRIPE_SECRET_KEY","").strip()
STRIPE_PRICE_ID=os.getenv("STRIPE_PRICE_ID","").strip()
STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET","").strip()
ADMIN_USER=os.getenv("ADMIN_USER",os.getenv("ADMIN_USERNAME","")).strip()
ADMIN_PASS=os.getenv("ADMIN_PASS",os.getenv("ADMIN_PASSWORD","")).strip()
GEMINI_API_KEY=os.getenv("GEMINI_API_KEY","").strip()
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY","").strip()
GEMINI_MODEL=os.getenv("GEMINI_MODEL","gemini-2.5-flash").strip()
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-4o-mini").strip()

if STRIPE_SECRET_KEY:
    stripe.api_key=STRIPE_SECRET_KEY

app=FastAPI(title="AL CIELO",version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

def db():
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    c=db()
    c.execute("""
    CREATE TABLE IF NOT EXISTS authorized_devices(
        device_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        updated_at REAL NOT NULL
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS fallback_rotation(
        device_id TEXT NOT NULL,
        language TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL,
        PRIMARY KEY(device_id,language)
    )
    """)
    c.commit()
    c.close()

init_db()

def authorized(device_id):
    if not device_id:
        return False
    c=db()
    r=c.execute(
        "SELECT status FROM authorized_devices WHERE device_id=?",
        (device_id,)
    ).fetchone()
    c.close()
    return bool(r and r["status"]=="active")

def authorize_device(device_id,customer=None,subscription=None):
    if not device_id:
        return
    c=db()
    c.execute("""
    INSERT INTO authorized_devices
    (device_id,status,stripe_customer_id,stripe_subscription_id,updated_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(device_id) DO UPDATE SET
        status='active',
        stripe_customer_id=excluded.stripe_customer_id,
        stripe_subscription_id=excluded.stripe_subscription_id,
        updated_at=excluded.updated_at
    """,(device_id,"active",customer,subscription,time.time()))
    c.commit()
    c.close()

def deactivate_subscription(subscription_id):
    if not subscription_id:
        return
    c=db()
    c.execute("""
    UPDATE authorized_devices
    SET status='inactive',updated_at=?
    WHERE stripe_subscription_id=?
    """,(time.time(),subscription_id))
    c.commit()
    c.close()

def next_backup(device_id,language):
    language=language if language in ("es","en","pt") else "es"
    c=db()
    r=c.execute("""
    SELECT position FROM fallback_rotation
    WHERE device_id=? AND language=?
    """,(device_id,language)).fetchone()
    if r is None:
        position=0
        c.execute("""
        INSERT INTO fallback_rotation
        (device_id,language,position,updated_at)
        VALUES(?,?,?,?)
        """,(device_id,language,0,time.time()))
    else:
        position=(int(r["position"])+1)%20
        c.execute("""
        UPDATE fallback_rotation
        SET position=?,updated_at=?
        WHERE device_id=? AND language=?
        """,(position,time.time(),device_id,language))
    c.commit()
    c.close()
    return position

def E(es,en,pt):
    return {"es":es,"en":en,"pt":pt}

def S(titles,*rows):
    langs=("es","en","pt")
    result={}
    for i,lang in enumerate(langs):
        result[lang]={
            "title":titles[i],
            "exercises":[
                {
                    "title":f"Parte {n+1}",
                    "instruction":row[lang]
                }
                for n,row in enumerate(rows)
            ]
        }
    return result

BACKUPS=[
S(
("AL CIELO · RESPIRAR","AL CIELO · BREATHE","AL CIELO · RESPIRAR"),
E("Siéntate o descansa cómodamente y permite que tu respiración sea tranquila.","Sit or rest comfortably and allow your breathing to become calm.","Sente-se ou descanse confortavelmente e permita que sua respiração fique tranquila."),
E("Inhala suavemente y después deja salir el aire sin prisa.","Breathe in gently and then let the air out without rushing.","Inspire suavemente e depois solte o ar sem pressa."),
E("Afloja los hombros mientras continúas respirando a tu propio ritmo.","Relax your shoulders while continuing to breathe at your own pace.","Relaxe os ombros enquanto continua respirando no seu próprio ritmo."),
E("Observa durante un momento cómo entra y sale el aire.","For a moment, notice the air coming in and going out.","Por um momento, observe o ar entrando e saindo."),
E("Haz otra respiración cómoda, sin forzarla.","Take another comfortable breath without forcing it.","Faça outra respiração confortável sem forçar."),
E("Permite que tus manos descansen tranquilamente.","Let your hands rest comfortably.","Deixe suas mãos descansarem confortavelmente."),
E("Mantén un ritmo tranquilo durante unos segundos.","Keep a calm rhythm for a few seconds.","Mantenha um ritmo tranquilo por alguns segundos."),
E("Cuando estés listo, continúa con el siguiente paso.","When you are ready, continue to the next step.","Quando estiver pronto, continue para o próximo passo.")
),
S(
("AL CIELO · PAUSA","AL CIELO · PAUSE","AL CIELO · PAUSA"),
E("Haz una pausa y busca una posición cómoda para permanecer unos momentos.","Pause and find a comfortable position to stay in for a few moments.","Faça uma pausa e encontre uma posição confortável para permanecer por alguns momentos."),
E("Mira hacia un punto que te resulte agradable.","Look toward a point that feels pleasant to you.","Olhe para um ponto que seja agradável para você."),
E("Respira de manera natural.","Breathe naturally.","Respire naturalmente."),
E("Deja que tus hombros permanezcan sueltos.","Let your shoulders remain relaxed.","Deixe seus ombros permanecerem relaxados."),
E("Descansa las manos donde te resulte cómodo.","Rest your hands wherever comfortable.","Descanse as mãos onde for confortável."),
E("Permanece así unos segundos.","Stay this way for a few seconds.","Permaneça assim por alguns segundos."),
E("Haz una respiración tranquila.","Take a calm breath.","Faça uma respiração tranquila."),
E("Continúa cuando te sientas preparado.","Continue when you feel ready.","Continue quando se sentir preparado.")
),
S(
("AL CIELO · RITMO","AL CIELO · RHYTHM","AL CIELO · RITMO"),
E("Encuentra un ritmo de respiración que te resulte natural.","Find a breathing rhythm that feels natural to you.","Encontre um ritmo de respiração que seja natural para você."),
E("Toma aire suavemente.","Breathe in gently.","Inspire suavemente."),
E("Suelta el aire poco a poco.","Let the air out slowly.","Solte o ar devagar."),
E("Repite una respiración cómoda.","Repeat a comfortable breath.","Repita uma respiração confortável."),
E("Mantén tu cuerpo en una posición agradable.","Keep your body in a comfortable position.","Mantenha o corpo em uma posição confortável."),
E("No necesitas apresurarte.","There is no need to hurry.","Você não precisa se apressar."),
E("Permanece tranquilo unos segundos.","Stay calm for a few seconds.","Permaneça tranquilo por alguns segundos."),
E("Continúa a tu propio ritmo.","Continue at your own pace.","Continue no seu próprio ritmo.")
),
S(
("AL CIELO · DESCANSO","AL CIELO · REST","AL CIELO · DESCANSO"),
E("Permite que este momento sea simplemente un momento de descanso.","Allow this moment to simply be a moment of rest.","Permita que este momento seja simplesmente um momento de descanso."),
E("Coloca tu cuerpo de la forma que te resulte más cómoda.","Place your body in whatever position feels most comfortable.","Coloque o corpo na posição que for mais confortável."),
E("Respira normalmente.","Breathe normally.","Respire normalmente."),
E("Deja descansar tus brazos.","Let your arms rest.","Deixe os braços descansarem."),
E("Suelta cualquier prisa por unos instantes.","Let go of any hurry for a moment.","Deixe a pressa de lado por alguns instantes."),
E("Observa tu respiración sin cambiarla.","Notice your breathing without changing it.","Observe sua respiração sem mudá-la."),
E("Permanece cómodo.","Remain comfortable.","Permaneça confortável."),
E("Continúa cuando quieras.","Continue when you wish.","Continue quando quiser.")
),
S(
("AL CIELO · TRANQUILIDAD","AL CIELO · CALM","AL CIELO · TRANQUILIDADE"),
E("Busca una postura cómoda y comienza este momento con calma.","Find a comfortable position and begin this moment calmly.","Encontre uma posição confortável e comece este momento com calma."),
E("Respira suavemente.","Breathe gently.","Respire suavemente."),
E("Deja salir el aire sin esfuerzo.","Let the air out without effort.","Solte o ar sem esforço."),
E("Mantén los hombros cómodos.","Keep your shoulders comfortable.","Mantenha os ombros confortáveis."),
E("Permanece tranquilo unos segundos.","Stay calm for a few seconds.","Permaneça tranquilo por alguns segundos."),
E("Haz otra respiración natural.","Take another natural breath.","Faça outra respiração natural."),
E("Descansa un momento.","Rest for a moment.","Descanse por um momento."),
E("Continúa cuando estés listo.","Continue when you are ready.","Continue quando estiver pronto.")
),
S(
("AL CIELO · PRESENTE","AL CIELO · PRESENT","AL CIELO · PRESENTE"),
E("Concéntrate solamente en este momento.","Focus only on this moment.","Concentre-se apenas neste momento."),
E("Siente cómo estás sentado o descansando.","Notice how you are sitting or resting.","Perceba como você está sentado ou descansando."),
E("Respira con naturalidad.","Breathe naturally.","Respire naturalmente."),
E("Mira a tu alrededor tranquilamente.","Look around you calmly.","Olhe ao seu redor com tranquilidade."),
E("Deja que tus manos descansen.","Let your hands rest.","Deixe suas mãos descansarem."),
E("Permanece aquí unos segundos.","Stay here for a few seconds.","Permaneça aqui por alguns segundos."),
E("Haz una respiración cómoda.","Take a comfortable breath.","Faça uma respiração confortável."),
E("Cuando quieras, continúa.","When you wish, continue.","Quando quiser, continue.")
),
S(
("AL CIELO · AIRE","AL CIELO · AIR","AL CIELO · AR"),
E("Toma aire de forma suave y natural.","Breathe in gently and naturally.","Inspire de forma suave e natural."),
E("Suelta el aire lentamente.","Breathe out slowly.","Solte o ar lentamente."),
E("Repite el movimiento sin esfuerzo.","Repeat the movement without effort.","Repita o movimento sem esforço."),
E("Mantén una posición cómoda.","Keep a comfortable position.","Mantenha uma posição confortável."),
E("Permite que los hombros descansen.","Let your shoulders rest.","Permita que os ombros descansem."),
E("Respira a tu propio ritmo.","Breathe at your own pace.","Respire no seu próprio ritmo."),
E("Haz una pausa breve.","Take a short pause.","Faça uma breve pausa."),
E("Continúa cuando estés preparado.","Continue when you are ready.","Continue quando estiver preparado.")
),
S(
("AL CIELO · MOMENTO","AL CIELO · MOMENT","AL CIELO · MOMENTO"),
E("Regálate unos momentos de tranquilidad.","Give yourself a few moments of calm.","Dê a si mesmo alguns momentos de tranquilidade."),
E("Busca una postura que puedas mantener cómodamente.","Find a position you can maintain comfortably.","Encontre uma posição que possa manter confortavelmente."),
E("Respira normalmente.","Breathe normally.","Respire normalmente."),
E("Deja descansar tus manos.","Let your hands rest.","Deixe suas mãos descansarem."),
E("Mira tranquilamente hacia adelante.","Look calmly ahead.","Olhe tranquilamente para frente."),
E("Permanece así unos segundos.","Stay this way for a few seconds.","Permaneça assim por alguns segundos."),
E("Haz una respiración suave.","Take a gentle breath.","Faça uma respiração suave."),
E("Continúa cuando quieras.","Continue when you wish.","Continue quando quiser.")
),
S(
("AL CIELO · CALMA","AL CIELO · CALM","AL CIELO · CALMA"),
E("Comienza lentamente y encuentra una posición agradable.","Begin slowly and find a comfortable position.","Comece devagar e encontre uma posição agradável."),
E("Respira sin cambiar tu ritmo natural.","Breathe without changing your natural rhythm.","Respire sem mudar seu ritmo natural."),
E("Suelta el aire tranquilamente.","Breathe out calmly.","Solte o ar com tranquilidade."),
E("Relaja los hombros.","Relax your shoulders.","Relaxe os ombros."),
E("Permanece cómodo.","Remain comfortable.","Permaneça confortável."),
E("Haz una respiración más.","Take one more breath.","Faça mais uma respiração."),
E("Descansa unos segundos.","Rest for a few seconds.","Descanse por alguns segundos."),
E("Continúa cuando estés listo.","Continue when you are ready.","Continue quando estiver pronto.")
),
S(
("AL CIELO · RESPIRACIÓN","AL CIELO · BREATHING","AL CIELO · RESPIRAÇÃO"),
E("Permite que tu respiración encuentre su propio ritmo.","Let your breathing find its own rhythm.","Permita que sua respiração encontre seu próprio ritmo."),
E("Inhala cómodamente.","Breathe in comfortably.","Inspire confortavelmente."),
E("Exhala sin prisa.","Breathe out without rushing.","Expire sem pressa."),
E("Mantén el cuerpo descansado.","Keep your body relaxed.","Mantenha o corpo relaxado."),
E("Observa el aire durante un momento.","Notice the air for a moment.","Observe o ar por um momento."),
E("Haz otra respiración tranquila.","Take another calm breath.","Faça outra respiração tranquila."),
E("Permanece unos segundos en calma.","Remain calm for a few seconds.","Permaneça alguns segundos em calma."),
E("Continúa cuando quieras.","Continue when you wish.","Continue quando quiser.")
),
S(
("AL CIELO · SILENCIO","AL CIELO · SILENCE","AL CIELO · SILÊNCIO"),
E("Quédate en silencio durante unos instantes.","Stay quiet for a few moments.","Fique em silêncio por alguns instantes."),
E("Respira normalmente.","Breathe normally.","Respire normalmente."),
E("Deja descansar los hombros.","Let your shoulders rest.","Deixe os ombros descansarem."),
E("Mantén las manos cómodas.","Keep your hands comfortable.","Mantenha as mãos confortáveis."),
E("Mira hacia un punto tranquilo.","Look toward a calm point.","Olhe para um ponto tranquilo."),
E("Permanece así unos segundos.","Stay this way for a few seconds.","Permaneça assim por alguns segundos."),
E("Haz una respiración suave.","Take a gentle breath.","Faça uma respiração suave."),
E("Continúa cuando estés preparado.","Continue when you are ready.","Continue quando estiver preparado.")
),
S(
("AL CIELO · DESPACIO","AL CIELO · SLOWLY","AL CIELO · DEVAGAR"),
E("Haz todo este momento sin apresurarte.","Take this whole moment without rushing.","Faça todo este momento sem pressa."),
E("Respira suavemente.","Breathe gently.","Respire suavemente."),
E("Suelta el aire poco a poco.","Let the air out gradually.","Solte o ar aos poucos."),
E("Permanece en una postura cómoda.","Remain in a comfortable position.","Permaneça em uma posição confortável."),
E("Descansa los brazos.","Rest your arms.","Descanse os braços."),
E("Respira una vez más.","Breathe once more.","Respire mais uma vez."),
E("Haz una pequeña pausa.","Take a short pause.","Faça uma pequena pausa."),
E("Continúa cuando quieras.","Continue when you wish.","Continue quando quiser.")
),
S(
("AL CIELO · PAZ","AL CIELO · PEACE","AL CIELO · PAZ"),
E("Busca un momento de paz y permanece cómodo.","Find a peaceful moment and remain comfortable.","Encontre um momento de paz e permaneça confortável."),
E("Respira naturalmente.","Breathe naturally.","Respire naturalmente."),
E("Deja salir el aire suavemente.","Let the air out gently.","Solte o ar suavemente."),
E("Permite que los hombros descansen.","Let your shoulders rest.","Permita que os ombros descansem."),
E("Permanece tranquilo.","Remain calm.","Permaneça tranquilo."),
E("Haz una respiración cómoda.","Take a comfortable breath.","Faça uma respiração confortável."),
E("Descansa unos segundos.","Rest for a few seconds.","Descanse por alguns segundos."),
E("Continúa cuando estés listo.","Continue when you are ready.","Continue quando estiver pronto.")
),
S(
("AL CIELO · AHORA","AL CIELO · NOW","AL CIELO · AGORA"),
E("Permanece atento solamente a este momento.","Stay aware only of this moment.","Permaneça atento apenas a este momento."),
E("Respira de manera cómoda.","Breathe comfortably.","Respire confortavelmente."),
E("Suelta el aire lentamente.","Breathe out slowly.","Solte o ar lentamente."),
E("Mantén una posición agradable.","Keep a comfortable position.","Mantenha uma posição confortável."),
E("Deja descansar las manos.","Let your hands rest.","Deixe as mãos descansarem."),
E("Permanece unos segundos.","Stay for a few seconds.","Permaneça por alguns segundos."),
E("Respira otra vez.","Breathe again.","Respire novamente."),
E("Continúa cuando quieras.","Continue when you wish.","Continue quando quiser.")
),
S(
("AL CIELO · SUAVE","AL CIELO · GENTLE","AL CIELO · SUAVE"),
E("Comienza con movimientos y respiración suaves.","Begin with gentle movements and breathing.","Comece com movimentos e respiração suaves."),
E("Respira sin esfuerzo.","Breathe without effort.","Respire sem esforço."),
E("Deja salir el aire tranquilamente.","Let the air out calmly.","Solte o ar com tranquilidade."),
E("Mantén el cuerpo cómodo.","Keep your body comfortable.","Mantenha o corpo confortável."),
E("Relaja las manos.","Relax your hands.","Relaxe as mãos."),
E("Haz una respiración natural.","Take a natural breath.","Faça uma respiração natural."),
E("Descansa unos segundos.","Rest for a few seconds.","Descanse por alguns segundos."),
E("Continúa cuando estés listo.","Continue when you are ready.","Continue quando estiver pronto.")
),
S(
("AL CIELO · DESCUBRE","AL CIELO · DISCOVER","AL CIELO · DESCUBRA"),
E("Observa cómo te sientes en este momento de descanso.","Notice how you feel during this moment of rest.","Observe como você se sente neste momento de descanso."),
E("Respira con tranquilidad.","Breathe calmly.","Respire com tranquilidade."),
E("Mira a tu alrededor.","Look around you.","Olhe ao seu redor."),
E("Permanece cómodo.","Remain comfortable.","Permaneça confortável."),
E("Deja descansar los hombros.","Let your shoulders rest.","Deixe os ombros descansarem."),
E("Haz una respiración suave.","Take a gentle breath.","Faça uma respiração suave."),
E("Quédate tranquilo unos segundos.","Stay calm for a few seconds.","Fique tranquilo por alguns segundos."),
E("Continúa cuando quieras.","Continue when you wish.","Continue quando quiser.")
),
S(
("AL CIELO · LENTO","AL CIELO · SLOW","AL CIELO · LENTO"),
E("Reduce el ritmo y permanece cómodo.","Slow down and remain comfortable.","Diminua o ritmo e permaneça confortável."),
E("Respira suavemente.","Breathe gently.","Respire suavemente."),
E("Suelta el aire lentamente.","Breathe out slowly.","Solte o ar lentamente."),
E("Descansa los hombros.","Rest your shoulders.","Descanse os ombros."),
E("Mantén las manos tranquilas.","Keep your hands relaxed.","Mantenha as mãos tranquilas."),
E("Permanece unos segundos.","Stay for a few seconds.","Permaneça por alguns segundos."),
E("Respira nuevamente.","Breathe again.","Respire novamente."),
E("Continúa cuando estés preparado.","Continue when you are ready.","Continue quando estiver preparado.")
),
S(
("AL CIELO · A TU RITMO","AL CIELO · YOUR PACE","AL CIELO · SEU RITMO"),
E("Haz este momento a tu propio ritmo.","Take this moment at your own pace.","Faça este momento no seu próprio ritmo."),
E("Busca comodidad.","Find comfort.","Busque conforto."),
E("Respira naturalmente.","Breathe naturally.","Respire naturalmente."),
E("Suelta el aire sin prisa.","Breathe out without rushing.","Solte o ar sem pressa."),
E("Descansa las manos.","Rest your hands.","Descanse as mãos."),
E("Permanece cómodo.","Remain comfortable.","Permaneça confortável."),
E("Haz una pausa breve.","Take a short pause.","Faça uma breve pausa."),
E("Continúa cuando quieras.","Continue when you wish.","Continue quando quiser.")
),
S(
("AL CIELO · MOMENTO TRANQUILO","AL CIELO · QUIET MOMENT","AL CIELO · MOMENTO TRANQUILO"),
E("Permanece tranquilo y cómodo durante este momento.","Remain calm and comfortable during this moment.","Permaneça tranquilo e confortável durante este momento."),
E("Respira suavemente.","Breathe gently.","Respire suavemente."),
E("Deja que el aire salga sin prisa.","Let the air out without rushing.","Deixe o ar sair sem pressa."),
E("Mantén una postura agradable.","Keep a comfortable posture.","Mantenha uma postura agradável."),
E("Descansa los brazos.","Rest your arms.","Descanse os braços."),
E("Observa tu respiración.","Notice your breathing.","Observe sua respiração."),
E("Permanece unos segundos.","Stay for a few seconds.","Permaneça por alguns segundos."),
E("Continúa cuando estés listo.","Continue when you are ready.","Continue quando estiver pronto.")
),
S(
("AL CIELO · FINAL","AL CIELO · FINISH","AL CIELO · FINAL"),
E("Comienza este momento con una respiración tranquila.","Begin this moment with a calm breath.","Comece este momento com uma respiração tranquila."),
E("Respira cómodamente.","Breathe comfortably.","Respire confortavelmente."),
E("Suelta el aire suavemente.","Breathe out gently.","Solte o ar suavemente."),
E("Mantén los hombros cómodos.","Keep your shoulders comfortable.","Mantenha os ombros confortáveis."),
E("Descansa las manos.","Rest your hands.","Descanse as mãos."),
E("Permanece tranquilo unos segundos.","Remain calm for a few seconds.","Permaneça tranquilo por alguns segundos."),
E("Haz una última respiración cómoda.","Take one final comfortable breath.","Faça uma última respiração confortável."),
E("Cuando estés listo, termina este momento tranquilamente.","When you are ready, calmly finish this moment.","Quando estiver pronto, termine este momento tranquilamente.")
)
]

if len(BACKUPS)!=20:
    raise RuntimeError(f"AL CIELO requiere exactamente 20 respaldos y encontró {len(BACKUPS)}.")

for backup in BACKUPS:
    for lang in ("es","en","pt"):
        if len(backup[lang]["exercises"])!=8:
            raise RuntimeError("Cada respaldo debe contener exactamente 8 ejercicios.")

def fallback_session(device_id,language,is_hook=False):
    if is_hook:
        return {
            "title":{
                "es":"AL CIELO",
                "en":"AL CIELO",
                "pt":"AL CIELO"
            }[language],
            "exercises":[{
                "title":"Parte 1",
                "instruction":{
                    "es":"Bienvenido. Cuando estés listo, comienza tranquilamente.",
                    "en":"Welcome. When you are ready, begin calmly.",
                    "pt":"Bem-vindo. Quando estiver pronto, comece com calma."
                }[language]
            }]
        }
    return BACKUPS[next_backup(device_id,language)][language]

def clean_text(v):
    if not isinstance(v,str):
        return ""
    return re.sub(r"\s+"," ",v).strip()

def language_ok(text,language):
    t=text.lower()
    if language=="es":
        return any(x in t for x in (" el "," la "," que "," una "," para "," y "))
    if language=="en":
        return any(x in t for x in (" the "," and "," you "," your "," to "," with "))
    return any(x in t for x in (" o "," a "," que "," para "," você "," com "))
    
def normalize_session(raw,language):
    if isinstance(raw,str):
        try:
            raw=json.loads(raw)
        except:
            return None

    if not isinstance(raw,dict):
        return None

    title=clean_text(raw.get("title","AL CIELO"))
    exercises=raw.get("exercises")

    if not isinstance(exercises,list):
        return None

    valid=[]
    for i,x in enumerate(exercises):
        if not isinstance(x,dict):
            continue
        instruction=clean_text(x.get("instruction",""))
        if not instruction:
            continue
        valid.append({
            "title":clean_text(x.get("title",f"Parte {i+1}")) or f"Parte {i+1}",
            "instruction":instruction
        })

    if len(valid)<8:
        return None

    return {
        "title":title or "AL CIELO",
        "exercises":valid[:8]
    }

async def generate_gemini(language):
    if not GEMINI_API_KEY:
        return None
    try:
        import httpx
        prompt=f"""
Crea una sesión de AL CIELO en idioma {language}.
No uses lenguaje médico, clínico, terapéutico, diagnóstico ni tratamiento.
Debe ser una experiencia sencilla para una persona adulta que está sentada, descansando o acostada.
Devuelve SOLO JSON válido:
{{
"title":"...",
"exercises":[
{{"title":"Parte 1","instruction":"..."}},
{{"title":"Parte 2","instruction":"..."}},
{{"title":"Parte 3","instruction":"..."}},
{{"title":"Parte 4","instruction":"..."}},
{{"title":"Parte 5","instruction":"..."}},
{{"title":"Parte 6","instruction":"..."}},
{{"title":"Parte 7","instruction":"..."}},
{{"title":"Parte 8","instruction":"..."}}
]
}}
Cada instruction debe ser un párrafo claro.
No pongas el título dentro de instruction.
"""
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        async with httpx.AsyncClient(timeout=30) as client:
            r=await client.post(url,json={
                "contents":[{"parts":[{"text":prompt}]}],
                "generationConfig":{"temperature":0.7,"responseMimeType":"application/json"}
            })
        if r.status_code!=200:
            return None
        data=r.json()
        text=data["candidates"][0]["content"]["parts"][0]["text"]
        return normalize_session(text,language)
    except:
        return None

async def generate_openai(language):
    if not OPENAI_API_KEY:
        return None
    try:
        import httpx
        prompt=f"""
Crea una sesión AL CIELO en {language}.
No uses lenguaje médico, clínico, terapéutico, diagnóstico ni tratamiento.
La persona puede estar sentada, descansando o acostada.
Devuelve únicamente JSON válido con un title y exactamente 8 exercises.
Cada exercise debe tener title e instruction.
La instruction es el único contenido que será leído por voz.
No pongas el título dentro de instruction.
"""
        async with httpx.AsyncClient(timeout=30) as client:
            r=await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization":f"Bearer {OPENAI_API_KEY}",
                    "Content-Type":"application/json"
                },
                json={
                    "model":OPENAI_MODEL,
                    "temperature":0.7,
                    "response_format":{"type":"json_object"},
                    "messages":[
                        {
                            "role":"system",
                            "content":"Devuelve solamente JSON válido."
                        },
                        {
                            "role":"user",
                            "content":prompt
                        }
                    ]
                }
            )
        if r.status_code!=200:
            return None
        data=r.json()
        text=data["choices"][0]["message"]["content"]
        return normalize_session(text,language)
    except:
        return None

def session_text(session):
    return "\n".join(
        x["instruction"] for x in session.get("exercises",[])
    )

@app.get("/",response_class=HTMLResponse)
async def home():
    if not INDEX_PATH.exists():
        return HTMLResponse(
            "<h1>AL CIELO</h1><p>No se encontró index.html.</p>",
            status_code=500
        )
    return FileResponse(INDEX_PATH,media_type="text/html")

@app.get("/health")
async def health():
    return {
        "status":"ok",
        "app":"AL CIELO",
        "version":APP_VERSION,
        "base_url":BASE_URL,
        "backups":20,
        "backup_exercises":8,
        "index":"index.html"
    }

@app.get("/api/v1/config")
async def config():
    return {
        "status":"success",
        "app":"AL CIELO",
        "version":APP_VERSION,
        "base_url":BASE_URL,
        "languages":["es","en","pt"],
        "backup_sessions":20,
        "backup_exercises":8,
        "speech":{
            "read":"instruction_only",
            "read_title":False,
            "gap_seconds":6,
            "gap_starts_after_speech":True
        },
        "stripe":bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)
    }

@app.get("/api/v1/access-status")
async def access_status(device_id:Optional[str]=None):
    return {
        "authorized":authorized(device_id),
        "device_id":device_id
    }

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(payload:dict):
    username=str(payload.get("username","")).strip()
    password=str(payload.get("password",""))
    device_id=str(payload.get("device_id","")).strip()

    if not ADMIN_USER or not ADMIN_PASS:
        return JSONResponse(
            {"status":"error","message":"Acceso administrativo no configurado."},
            status_code=503
        )

    if username!=ADMIN_USER or password!=ADMIN_PASS or not device_id:
        return JSONResponse(
            {"status":"error","message":"Datos de acceso incorrectos."},
            status_code=401
        )

    authorize_device(device_id)
    return {
        "status":"success",
        "authorized":True
    }

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(payload:dict):
    device_id=str(payload.get("device_id","")).strip()

    if not device_id:
        return JSONResponse(
            {"status":"error","message":"Falta device_id."},
            status_code=400
        )

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        return JSONResponse(
            {"status":"error","message":"Stripe no está configurado."},
            status_code=503
        )

    try:
        session=stripe.checkout.Session.create(
            line_items=[
                {
                    "price":STRIPE_PRICE_ID,
                    "quantity":1
                }
            ],
            mode="subscription",
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}&device_id={device_id}",
            cancel_url=f"{BASE_URL}/cancel",
            metadata={
                "device_id":device_id
            },
            allow_promotion_codes=True
        )

        return {
            "status":"success",
            "checkout_url":session.url,
            "session_id":session.id
        }
    except Exception as e:
        return JSONResponse(
            {
                "status":"error",
                "message":str(e)
            },
            status_code=500
        )

@app.post("/webhook/stripe")
async def stripe_webhook(request:Request):
    payload=await request.body()
    signature=request.headers.get("stripe-signature","")

    try:
        if STRIPE_WEBHOOK_SECRET:
            event=stripe.Webhook.construct_event(
                payload,
                signature,
                STRIPE_WEBHOOK_SECRET
            )
        else:
            event=json.loads(payload.decode("utf-8"))
    except Exception:
        return JSONResponse(
            {"status":"error","message":"Webhook inválido."},
            status_code=400
        )

    event_type=event.get("type","")
    obj=event.get("data",{}).get("object",{})

    if event_type=="checkout.session.completed":
        metadata=obj.get("metadata") or {}
        device_id=str(metadata.get("device_id","")).strip()
        payment_status=obj.get("payment_status")
        customer=obj.get("customer")
        subscription=obj.get("subscription")

        if device_id and payment_status in ("paid","no_payment_required"):
            authorize_device(
                device_id,
                customer,
                subscription
            )

    elif event_type=="customer.subscription.deleted":
        deactivate_subscription(obj.get("id"))

    elif event_type=="customer.subscription.unpaid":
        deactivate_subscription(obj.get("id"))

    elif event_type=="customer.subscription.updated":
        status=obj.get("status")
        subscription_id=obj.get("id")

        if status in ("active","trialing"):
            c=db()
            c.execute("""
            UPDATE authorized_devices
            SET status='active',updated_at=?
            WHERE stripe_subscription_id=?
            """,(time.time(),subscription_id))
            c.commit()
            c.close()
        elif status in ("unpaid","canceled","incomplete_expired"):
            deactivate_subscription(subscription_id)

    return {
        "status":"success"
    }

@app.get("/success")
async def success(
    session_id:Optional[str]=None,
    device_id:Optional[str]=None
):
    sid=session_id or ""
    did=device_id or ""

    if sid and STRIPE_SECRET_KEY:
        try:
            session=stripe.checkout.Session.retrieve(sid)
            meta=session.get("metadata") or {}
            did=did or str(meta.get("device_id","")).strip()

            if (
                did
                and session.get("payment_status") in ("paid","no_payment_required")
                and not authorized(did)
            ):
                subscription=session.get("subscription")
                customer=session.get("customer")
                authorize_device(
                    did,
                    customer,
                    subscription
                )
        except:
            pass

    html=f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AL CIELO</title>
<style>
html,body{{margin:0;background:#000;color:#fff;font-family:Arial,sans-serif;text-align:center}}
main{{max-width:700px;margin:15vh auto;padding:24px}}
h1{{font-size:42px}}
p{{font-size:22px;line-height:1.5}}
a{{display:inline-block;margin-top:20px;padding:18px 28px;background:#fff;color:#000;text-decoration:none;border-radius:10px;font-size:20px}}
</style>
</head>
<body>
<main>
<h1>AL CIELO</h1>
<p>Estamos verificando tu acceso.</p>
<p id="status">Espera un momento...</p>
<a href="{BASE_URL}">ENTRAR A AL CIELO</a>
</main>
<script>
const base={json.dumps(BASE_URL)};
const device={json.dumps(did)};
let tries=0;
async function check(){{
    tries++;
    try{{
        const r=await fetch(base+"/api/v1/access-status?device_id="+encodeURIComponent(device));
        const d=await r.json();
        if(d.authorized){{
            document.getElementById("status").textContent="Acceso confirmado. Entrando...";
            setTimeout(()=>window.location.replace(base),500);
            return;
        }}
    }}catch(e){{}}
    if(tries<40){{
        setTimeout(check,750);
    }}else{{
        document.getElementById("status").textContent="Si acabas de pagar, pulsa ENTRAR A AL CIELO.";
    }}
}}
check();
</script>
</body>
</html>
"""
    return HTMLResponse(html)

@app.get("/cancel")
async def cancel():
    return HTMLResponse(f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AL CIELO</title>
<style>
html,body{{margin:0;background:#000;color:#fff;font-family:Arial,sans-serif;text-align:center}}
main{{max-width:700px;margin:15vh auto;padding:24px}}
h1{{font-size:42px}}
p{{font-size:22px;line-height:1.5}}
a{{display:inline-block;margin-top:20px;padding:18px 28px;background:#fff;color:#000;text-decoration:none;border-radius:10px;font-size:20px}}
</style>
</head>
<body>
<main>
<h1>AL CIELO</h1>
<p>El proceso de pago no se completó.</p>
<a href="{BASE_URL}">VOLVER A AL CIELO</a>
</main>
</body>
</html>
""")

@app.post("/api/v1/generate-session")
async def generate_session(payload:dict):
    device_id=str(payload.get("device_id","")).strip()
    language=str(payload.get("language","es")).lower().strip()
    is_hook=bool(payload.get("is_hook",False))

    if language not in ("es","en","pt"):
        language="es"

    if not device_id:
        return JSONResponse(
            {"status":"error","message":"Falta device_id."},
            status_code=400
        )

    if is_hook:
        session=fallback_session(
            device_id,
            language,
            True
        )
        return {
            "status":"success",
            "authorized":authorized(device_id),
            "language":language,
            "source":"hook",
            "session":session,
            "session_content":session_text(session),
            "speech_rule":"Leer solamente instruction. Nunca leer title.",
            "timing_rule":"Los 6 segundos comienzan solamente después de terminar completamente la lectura del párrafo."
        }

    if not authorized(device_id):
        return JSONResponse(
            {
                "status":"payment_required",
                "authorized":False,
                "message":"Se requiere acceso."
            },
            status_code=402
        )

    session=await generate_gemini(language)
    source="gemini"

    if session is None:
        session=await generate_openai(language)
        source="openai"

    if session is None:
        session=fallback_session(device_id,language)
        source="backup"

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
