import os,sqlite3,random,asyncio,json,re
from fastapi import FastAPI,HTTPException,Request,Header
from fastapi.responses import FileResponse,HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
import openai

app=FastAPI(title="AL CIELO - Production Engine",version="4.1.0")
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
try:
    openai_client=openai.OpenAI(api_key=openai_api_key) if openai_api_key else None
except Exception:
    openai_client=None

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
    conn.execute("""CREATE TABLE IF NOT EXISTS fallback_rotation(
        device_id TEXT PRIMARY KEY,
        last_index INTEGER NOT NULL DEFAULT -1,
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

def next_fallback_index(device_id):
    conn=get_db()
    row=conn.execute("SELECT last_index FROM fallback_rotation WHERE device_id=?",(device_id,)).fetchone()
    if row is None:
        index=random.randrange(len(FALLBACK_SESSIONS_ES))
        conn.execute("INSERT INTO fallback_rotation(device_id,last_index,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)",(device_id,index))
    else:
        index=(int(row["last_index"])+1)%len(FALLBACK_SESSIONS_ES)
        conn.execute("UPDATE fallback_rotation SET last_index=?,updated_at=CURRENT_TIMESTAMP WHERE device_id=?",(index,device_id))
    conn.commit()
    conn.close()
    return index

init_db()

SYSTEM_WELLNESS_PROMPT="""
You are the exclusive professional human-like wellness and lifestyle companion for AL CIELO.
The service is designed for adults 50 and over and must be inclusive of active people, seated people,
resting people, people in bed, people with limited mobility, and people with missing limbs.

Your language must be warm, direct, calm, respectful, simple and conversational.

STRICT RULES:
1. Never mention AI, ChatGPT, internal systems, codes, IDs, audits or technical processes.
2. Never use medical terminology, diagnosis, treatment or clinical authority.
3. Never create fear or pressure.
4. Never require a movement that the person cannot comfortably perform.
5. Every instruction must allow the person to remain seated, resting or in bed when appropriate.
6. Do not say that the service is medical or therapeutic.
7. Do not create duplicate sessions.
8. Use ONLY the requested language.
9. The output must be valid JSON when the user requests structured exercises.
10. Each exercise must contain only:
   {"title":"short exercise title","instruction":"clear instruction"}
11. The title is displayed on screen and MUST NOT be repeated inside the instruction.
12. Instructions must be suitable for spoken audio.
13. Do not put numbers, IDs, technical labels or internal comments inside the exercise text.
"""

# ============================================================
# 20 RESPALDOS ORIGINALES.
# NO ELIMINAR.
# NO SUSTITUIR.
# NO REDUCIR.
# ============================================================

FALLBACK_SESSIONS_ES=[
("Bienvenido a su espacio personal de bienestar y armonía diaria. Tómese un instante para acomodarse con absoluta comodidad, ya sea sentado plácidamente en su sillón favorito o descansando de forma reposada en su cama. Vamos a comenzar este momento de pausa centrando toda nuestra atención en el ritmo natural de la respiración. Sienta cómo el aire fresco ingresa suavemente a través de su nariz, recorre su interior y sale despacio, aliviando cualquier rastro de tensión acumulada en el día. Permita que sus hombros desciendan de manera completamente natural, soltando el peso de la jornada y encontrando un punto de apoyo firme y seguro en la superficie que lo sostiene. Si le es posible y cuenta con movilidad en sus manos y dedos, hágalo de forma sumamente pausada, disfrutando del tacto y la presencia de su propio cuerpo. Si prefiere el reposo absoluto o la quietud, acompañe este proceso sintiendo el calor y el equilibrio de su postura. Inhale despacio contando mentalmente hasta cuatro, sostenga el aire con total serenidad durante un instante, y exhale con suavidad infinita mientras recorremos juntos este sendero de calma profunda. Permítase un momento para desconectarse de las distracciones externas y habitar este presente lleno de tranquilidad. Su postura debe sentirse cómoda, sin forzar absolutamente nada; simplemente deje que el cuerpo encuentre su propio estado de relajación natural. Continuamos manteniendo este flujo de aire constante, notando cómo cada exhalación regala una sensación de descanso renovador a cada fibra de su ser, brindándole estabilidad, esperanza y un profundo bienestar interior en este espacio diseñado exclusivamente para usted."),
("Comenzamos este momento especial dedicado enteramente a su descanso, equilibrio físico y confort cotidiano. Ubíquese en la posición que hoy le brinde mayor seguridad y bienestar general. Vamos a dirigir la atención hacia el área del cuello y la cabeza, realizando un movimiento imperceptible y muy delicado de lado a lado solo si su cuerpo se lo permite de manera natural, o bien visualizando ese movimiento con total serenidad en su mente. Sienta cómo los músculos de la mandíbula se aflojan, cómo la frente se despeja y cómo la expresión del rostro se vuelve apacible. Tomaremos el control consciente del ritmo de la respiración: inhalamos profundamente llenando el pecho con energía renovada, retenemos el aire con extrema suavidad, y exhalamos muy despacio liberando cualquier carga del entorno. Disfrute de esta atención plena orientada a su comodidad. Cada segundo invertido en esta práctica es un regalo para su calidad de vida y su tranquilidad mental. Si se encuentra recostado o descansando en su cama, sienta el soporte completo de su espalda, la almohada sosteniendo su cabeza con firmeza y los brazos reposando en un ángulo de total comodidad. Vamos a mantener esta cadencia de respiración pausada, permitiendo que el tiempo transcurra con suavidad, sin prisa, acompañando cada minuto con una actitud abierta, positiva y reconfortante."),
("Un cordial saludo en esta nueva sesión de cuidado personal y bienestar integral. Conéctese con su comodidad adoptando una postura que le ofrezca un soporte firme, relajado y completamente seguro. Hoy centraremos nuestra atención en la apertura del pecho y en la expansión de una respiración amplia y fluida. Si tiene movilidad en sus brazos, deslícelos con delicadeza hacia una posición de mayor holgura; de lo contrario, concéntrese por completo en percibir la expansión y contracción natural del tórax al compás del aire. Note de manera consciente el punto exacto de contacto de su espalda con el respaldo o la superficie de descanso, sintiendo cómo el cuerpo se afianza con confianza. Cada exhalación representa una magnífica oportunidad para soltar las preocupaciones cotidianas y regalarle a su organismo un respiro profundo, ordenado y armónico. Mantenga su mente enfocada en este instante presente, disfrutando del silencio constructivo y de la compañía de esta guía diseñada para propiciar un estado óptimo de relajación y estabilidad. Siga respirando de manera lenta, permitiendo que la calma se expanda desde el centro de su pecho hacia los brazos, las manos y el resto de su cuerpo, consolidando un refugio de paz interior."),
("Le damos la más cordial bienvenida a su pausa activa y restaurativa de hoy. Sin importar si se encuentra en plena actividad cotidiana, sentado con comodidad o descansando plácidamente en cama, la prioridad absoluta es su confort. Vamos a llevar una suave conciencia hacia los puntos de apoyo principales de su cuerpo: la espalda, las piernas o los brazos, reconociendo el espacio físico que habita con total gratitud. Comience a percibir el latido calmado y constante de su corazón, acompañándolo con respiraciones largas, profundas y sin ningún tipo de exigencia. Si le es posible dentro de su comodidad actual, mueva milimétricamente las muñecas o los dedos de los pies; si prefiere la quietud, permita que la visualización y la respiración consciente cumplan la labor de relajar cada rincón de su anatomía. Este ejercicio promueve una sensación inigualable de ligereza y descanso profundo. Permítase flotar en esta atmósfera de tranquilidad, donde el único objetivo es su bienestar y su comodidad absoluta. Continuamos respirando con suavidad, dejando que los minutos transcurran en un entorno de paz, equilibrio y seguridad inquebrantable."),
("Iniciamos este momento de profunda conexión con su bienestar personal y equilibrio físico. Acomódese con absoluta libertad y cierre los ojos si le apetece, permitiendo que la voz le acompañe paso a paso en este recorrido de relajación. Hoy trabajaremos en la disolución de tensiones acumuladas en la parte superior del cuerpo. Relaje los músculos de la cara, despegue ligeramente los dientes, deje caer los hombros alejándolos de las orejas y respire profundamente. Si alguna zona corporal presenta rigidez o limitaciones de movimiento, evite forzarla por completo; simplemente obsérvela con aceptación y envíele una bocanada de aire cálido y reconfortante. Sienta cómo una corriente de bienestar recorre su organismo de pies a cabeza en un flujo constante, apacible y revitalizador. Este espacio está pensado para brindarle estabilidad y esperanza, permitiéndole reconectar con su centro de energía y tranquilidad. Siga disfrutando de este compás pausado, sabiendo que cada inhalación fortalece su equilibrio y cada exhalación borra cualquier rastro de prisa o inquietud."),
("Bienvenido a su rutina de relajación y movimiento adaptado para el bienestar general. Tome aire de manera natural, profunda y dosificada, permitiendo que el área del abdomen se expanda con total libertad. Vamos a realizar un recorrido mental consciente por todo su cuerpo, reconociendo cada parte con afecto y respeto por su estado actual. Si posee movilidad en sus extremidades, realice pequeños círculos sumamente lentos con las manos; si se encuentra en reposo absoluto, imagine ese movimiento fluyendo con perfecta armonía en su imaginación. Mantenga una respiración compasiva y constante, disfrutando del silencio y de la seguridad de este entorno creado para su cuidado. La constancia en estos pequeños hábitos de pausa aporta una gran estabilidad emocional y física, ayudando a que su día transcurra con mayor fluidez y serenidad. Permanezca receptivo a esta sensación de descanso, dejando que el cuerpo se recupere y encuentre su propia naturalidad sin prisas ni presiones de ninguna índole."),
("Es un verdadero placer acompañarle en este espacio de bienestar estructurado exclusivamente para su comodidad. Sintonice con el momento presente ajustando su postura hasta hallar el punto exacto de reposo y confort. Vamos a enfocar la atención en el centro de su cuerpo, permitiendo que cada inhalación traiga una bocanada de energía renovada y que cada exhalación se lleve cualquier molestia superficial. Mantenga los brazos y las piernas en la posición que hoy le otorgue mayor alivio, guiándose únicamente por el compás pausado de una respiración consciente y deliberada. Este tiempo le pertenece por completo; es un compromiso con su propia calidad de vida y su equilibrio diario. Sienta el respaldo firme que lo sostiene y entregue el peso de su cuerpo a la superficie con total confianza, sabiendo que se encuentra en un entorno seguro y protector. Continúe respirando lento y profundo mientras acompañamos cada instante con serenidad, armonía y un profundo respeto por su comodidad."),
("Comenzamos una nueva práctica enfocada en su paz interior, estabilidad y confort físico general. Adopte una postura que le proporcione un soporte óptimo y una sensación inquebrantable de seguridad. Vamos a relajar paulatinamente los dedos de las manos, los brazos y la columna vertebral mediante respiraciones profundas, pausadas y bien dirigidas. Si alguna extremidad carece de movimiento, recuerde que su mente y su respiración cumplen el rol principal de activar la relajación profunda y la circulación armónica. Permítase desconectarse temporalmente del exterior y habitar este instante de tranquilidad absoluta, donde las tensiones simplemente se desvanecen. Cada ciclo de aire fresco limpia su mente y revitaliza su postura, permitiéndole experimentar una profunda renovación desde la comodidad de su asiento o cama. Disfrute de la estabilidad y la paz que este espacio le otorga en cada segundo, manteniendo una actitud de calma y bienestar duradero."),
("Bienvenido a su sesión de revitalización, descanso y equilibrio armónico. Busque la postura más cómoda y favorable disponible para usted en este preciso momento. Dirigiremos la atención hacia la zona de los hombros y la parte alta de la espalda, imaginando que una brisa ligera y cálida disuelve cualquier rigidez presente. Tome una inspiración profunda, llene sus pulmones sin prisa alguna y deje salir el aire de forma prolongada y suave a través de sus labios. Sienta cómo el cuerpo se afloja notablemente y se entrega a un descanso reparador, manteniendo siempre una práctica segura, libre de exigencias y adaptada enteramente a su ritmo. Este proceso favorece la distensión muscular y le otorga un valioso momento de tregua frente a las exigencias del día a día. Siga respirando de este modo, permitiendo que la tranquilidad inunde cada espacio de su mente y su cuerpo con total naturalidad."),
("Cerramos nuestro ciclo de recomendaciones de bienestar con una sesión centrada en la serenidad absoluta y el confort restaurador. Acomódese con la absoluta certeza de que este tiempo le pertenece por completo. Vamos a unificar la respiración con pequeños movimientos conscientes o con una visualización profunda de ligereza y bienestar en todo su entorno. Sienta el soporte firme que lo sostiene, relaje cada músculo de su rostro y permita que el aire fluya sin ningún tipo de obstáculo ni restricción. Disfrute de la estabilidad y la paz que este espacio le proporciona, sabiendo que cuidar de su descanso es la mejor manera de honrar su vitalidad. Permanezca unos instantes disfrutando de esta sensación de plenitud, con la tranquilidad de haber dedicado un espacio genuino a su armonía personal. Inhale profundo por última vez en esta sesión, sonría con suavidad y prepárese para continuar su día con una renovada sensación de paz y bienestar."),
("Iniciamos un nuevo espacio dedicado por completo a su bienestar cotidiano y a la paulatina relajación de todo su sistema físico. Adopte una postura que le resulte sumamente agradable y placentera. Lleve su mente hacia las palmas de las manos, imaginando que una agradable sensación de calor las recorre suavemente. Si descansa en cama, permita que el colchón soporte enteramente su peso sin que usted deba realizar esfuerzo alguno. Realice una inspiración lenta, sintiendo cómo el aire expande suavemente el área del abdomen, y al expirar, suelte cualquier pensamiento o preocupación del momento. Esta práctica está diseñada para propiciar un remanso de paz en medio de su jornada, ayudándole a recuperar la energía vital mediante la quietud y la respiración consciente. Permita que la tranquilidad le envuelva por completo, disfrutando de cada instante en este refugio de confort y armonía personal."),
("Le damos la bienvenida a esta sesión orientada al equilibrio y la distensión integral. Ajuste su posición corporal para garantizar que su cuello, espalda y extremidades se encuentren plenamente respaldados. Concentre su atención en el simple acto de respirar: perciba la temperatura del aire al entrar y la calidez al salir de su cuerpo. Si nota alguna pequeña tensión en el rostro o en la mandíbula, relájela intencionalmente permitiendo que los labios se entreabran con total naturalidad. Cada inhalación le aporta serenidad y cada exhalación afianza una profunda sensación de estabilidad en su entorno. Disfrute de este valioso tiempo de cuidado y descanso."),
("Comenzamos una pausa restaurativa centrada en el alivio y la comodidad física. Relaje los brazos a los lados de su cuerpo o sobre su regazo de la manera más cómoda posible. Visualice una suave onda de bienestar que desciende lentamente desde la coronilla hasta la punta de los pies, disipando cualquier rigidez a su paso. Acompañe este recorrido mental con respiraciones rítmicas, profundas y sumamente calmadas, evitando cualquier prisa o exigencia. Este espacio seguro es suyo para recargar energías, encontrar paz mental y disfrutar de un confort duradero."),
("Saludamos este instante de pausa y armonía enfocado en su bienestar personal. Conéctese con la firmeza del suelo o de la cama que sostiene su cuerpo en este momento. Permita que la respiración se vuelva cada vez más lenta y profunda, sirviendo como un ancla segura para mantener la mente tranquila y despejada. Si lo prefiere, mantenga los ojos cerrados mientras su atención descansa apaciblemente en el flujo constante del aire. Disfrute de la estabilidad y el sosiego que esta práctica le otorga, consolidando un estado óptimo de relajación y descanso."),
("Nos adentramos en una sesión pensada para brindarle un respiro profundo y una total distensión corporal. Colóquese en la postura que le aporte mayor desahogo y confort. Dirija su mirada interior hacia la zona de la espalda y los hombros, permitiendo que el peso de los mismos se deslice hacia la superficie de apoyo. Respire con absoluta calma, llenando su interior de esperanza, bienestar y una agradable sensación de liviandad. Este es su momento para habitar el presente con total tranquilidad y seguridad."),
("Bienvenido a este momento de armonización y cuidado de su estilo de vida. Tome una posición que le permita relajar por completo la columna y la zona lumbar. Inhale aire fresco con alegría, sosténgalo unos segundos con suavidad, y expúlselo lentamente dejando ir cualquier rigidez del entorno. Permita que la quietud y el silencio fortalezcan su paz interior, disfrutando plenamente de cada minuto de este descanso enriquecedor."),
("Iniciamos una práctica destinada a cultivar el confort, el equilibrio y la paz en su día a día. Sienta el soporte de la almohada o el respaldar adaptándose a su forma. Realice respiraciones profundas y pausadas, centrando toda su atención en el bienestar que surge al soltar las tensiones cotidianas. Disfrute de este espacio exclusivo de tranquilidad, diseñado para restaurar su energía vital con absoluta naturalidad y seguridad."),
("Comenzamos un espacio de descanso y relajación profunda para acompañar su rutina de bienestar. Adopte una postura cómoda, libre de presiones y exigencias. Sienta el flujo rítmico de su respiración y cómo cada ciclo le otorga una mayor sensación de ligereza y estabilidad interior. Permanezca en este refugio de paz, disfrutando del silencio constructivo y de una total comodidad física."),
("Le saludamos en esta sesión de pausa y armonía diseñada para su confort diario. Ubíquese en el sitio que le ofrezca mayor solidez y bienestar. Conecte con su respiración natural, permitiendo que el aire limpie y relaje cada rincón de su cuerpo de manera apacible y constante. Disfrute de este momento de tregua, estabilidad y cuidado personal sin prisas."),
("Finalizamos nuestro repertorio de bienestar con una sesión orientada al equilibrio absoluto y la paz interior. Acomódese con la certeza de que este tiempo es suyo. Respire hondo, relaje los músculos del rostro y entregue su peso corporal a la superficie con absoluta confianza y serenidad. Disfrute de esta profunda sensación de plenitud y prepárese para continuar su jornada con total armonía.")
]

if len(FALLBACK_SESSIONS_ES)!=20:
    raise RuntimeError("El banco de respaldo debe contener exactamente 20 opciones.")

def clean_text(value):
    if value is None:return ""
    value=str(value).strip()
    value=re.sub(r"```(?:json)?","",value,flags=re.I)
    value=value.replace("```","").strip()
    return value

def valid_instruction(text):
    if not isinstance(text,str):return False
    text=clean_text(text)
    return len(text)>=12 and len(text)<=1800

def normalize_session(obj,is_hook=False):
    if not isinstance(obj,dict):return None
    title=clean_text(obj.get("title") or obj.get("session_title") or "AL CIELO")
    exercises=obj.get("exercises")
    if not isinstance(exercises,list):return None
    normalized=[]
    for item in exercises:
        if not isinstance(item,dict):continue
        instruction=clean_text(item.get("instruction") or item.get("content") or item.get("text"))
        exercise_title=clean_text(item.get("title") or item.get("name") or "Bienestar")
        if not valid_instruction(instruction):continue
        if exercise_title.lower()==instruction.lower():continue
        normalized.append({"title":exercise_title[:120],"instruction":instruction})
    if is_hook:
        if len(normalized)<1:return None
        normalized=normalized[:1]
    else:
        if len(normalized)<4:return None
        normalized=normalized[:10]
    return {"title":title[:160],"exercises":normalized}

def parse_ai_session(text,is_hook=False):
    text=clean_text(text)
    if not text:return None
    candidates=[text]
    match=re.search(r"\{.*\}",text,re.S)
    if match:candidates.append(match.group(0))
    for candidate in candidates:
        try:
            obj=json.loads(candidate)
            session=normalize_session(obj,is_hook)
            if session:return session
        except Exception:
            pass
    return None

def split_backup(text):
    words=text.split()
    if not words:return []
    target=6 if len(words)>=180 else 4
    chunks=[]
    size=max(1,len(words)//target)
    start=0
    for i in range(target):
        end=len(words) if i==target-1 else min(len(words),start+size)
        chunk=" ".join(words[start:end]).strip()
        if chunk:chunks.append(chunk)
        start=end
        if start>=len(words):break
    if len(chunks)<4:
        chunks=[text]
    return chunks

def fallback_session(device_id,is_hook=False):
    index=next_fallback_index(device_id)
    text=FALLBACK_SESSIONS_ES[index]
    chunks=split_backup(text)
    if is_hook:
        instruction=" ".join(text.split()[:65])
        return {"title":"Muestra gratuita","exercises":[{"title":"Respiración tranquila","instruction":instruction}]}
    titles=["Acomodarse","Respirar con calma","Encontrar comodidad","Soltar la tensión","Mantener la calma","Cerrar con tranquilidad"]
    exercises=[]
    for i,chunk in enumerate(chunks[:6]):
        exercises.append({"title":titles[i] if i<len(titles) else "Momento de bienestar","instruction":chunk})
    return {"title":"Sesión de bienestar AL CIELO","exercises":exercises}

def language_name(language):
    return {"es":"Spanish","en":"English","pt":"Portuguese"}.get(language,"Spanish")

def language_ok(session,language):
    if not session:return False
    if language=="es":return True
    text=" ".join(x["instruction"] for x in session["exercises"]).lower()
    spanish_markers=[" para "," con "," una "," los "," las "," que "," respir"," cómoda"," cómodo"," permita "," suavemente "]
    if language=="en":
        return sum(x in text for x in spanish_markers)<3
    portuguese_markers=[" para "," com "," uma "," os "," as "," que "," respira"," confortável"," permita "," suavemente "]
    if language=="pt":
        return sum(x in text for x in portuguese_markers)<3
    return False

def build_prompt(language,is_hook):
    lang=language_name(language)
    if is_hook:
        return f"""Create a free preview in {lang}.
Return ONLY valid JSON:
{{"title":"short session title","exercises":[{{"title":"short exercise title","instruction":"one simple spoken instruction"}}]}}
Exactly one exercise.
The instruction must be about a gentle, comfortable breathing or relaxation action.
Maximum 70 words.
Do not put the title inside the instruction.
No medical language.
No technical language.
No Spanish if the requested language is English or Portuguese."""
    return f"""Create a fresh 10-minute AL CIELO wellness session in {lang}.
Return ONLY valid JSON using exactly this structure:
{{"title":"session title","exercises":[{{"title":"short exercise title","instruction":"clear spoken instruction"}}]}}
Create 8 exercises.
Each instruction must be practical, calm and understandable to an adult 50+.
Exercises must work for active, seated, resting or bed users.
Always provide a comfortable alternative or mental visualization when movement is unavailable.
Do not use medical, clinical or therapeutic language.
Do not mention AI, systems, phases, codes or IDs.
Do not put the exercise title inside the instruction.
Do not use giant paragraphs.
Use ONLY {lang}.
"""

async def call_gemini(prompt):
    if not gemini_client:return ""
    try:
        task=asyncio.to_thread(
            gemini_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_WELLNESS_PROMPT,
                temperature=.92,
                max_output_tokens=3500
            )
        )
        result=await asyncio.wait_for(task,timeout=20)
        return clean_text(result.text or "")
    except Exception:
        return ""

async def call_openai(prompt):
    if not openai_client:return ""
    try:
        task=asyncio.to_thread(
            openai_client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content":SYSTEM_WELLNESS_PROMPT},
                {"role":"user","content":prompt}
            ],
            temperature=.92,
            max_tokens=3500
        )
        result=await asyncio.wait_for(task,timeout=20)
        return clean_text(result.choices[0].message.content or "")
    except Exception:
        return ""

@app.get("/")
async def index():
    return FileResponse("index.html")

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request:Request):
    body=await request.json()
    username=str(body.get("username","")).strip()
    password=str(body.get("password","")).strip()
    device_id=str(body.get("device_id","")).strip()
    if not ADMIN_USER or not ADMIN_PASS:
        raise HTTPException(500,"Admin credentials not configured.")
    if username==ADMIN_USER and password==ADMIN_PASS and device_id:
        authorize_device(device_id)
        return {"status":"success"}
    raise HTTPException(401,"Invalid credentials.")

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request:Request):
    try:
        body=await request.json()
        device_id=str(body.get("device_id","")).strip()
        if not device_id:raise HTTPException(400,"Device ID required.")
        if not stripe.api_key:raise HTTPException(500,"STRIPE_SECRET_KEY is missing.")
        if not STRIPE_PRICE_ID:raise HTTPException(500,"STRIPE_PRICE_ID is missing.")
        host=request.headers.get("host") or "al-cielo.onrender.com"
        base=f"https://{host}"
        checkout=stripe.checkout.Session.create(
            line_items=[{"price":STRIPE_PRICE_ID,"quantity":1}],
            mode="subscription",
            success_url=f"{base}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/cancel",
            metadata={"device_id":device_id}
        )
        return {"status":"success","checkout_url":checkout.url}
    except HTTPException:raise
    except stripe.error.StripeError as e:
        raise HTTPException(502,f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(500,f"Checkout error: {str(e)}")

@app.post("/webhook/stripe")
async def stripe_webhook(request:Request,stripe_signature:str=Header(default=None)):
    payload=await request.body()
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500,"STRIPE_WEBHOOK_SECRET is missing.")
    if not stripe_signature:
        raise HTTPException(400,"Missing Stripe-Signature header.")
    try:
        event=stripe.Webhook.construct_event(payload,stripe_signature,STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(400,"Invalid webhook payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400,"Invalid Stripe webhook signature.")
    event_type=event.get("type")
    if event_type=="checkout.session.completed":
        session=event["data"]["object"]
        metadata=session.get("metadata") or {}
        device_id=metadata.get("device_id")
        if device_id:
            authorize_device(device_id,session.get("customer"),session.get("subscription"))
    elif event_type in ("customer.subscription.deleted","customer.subscription.unpaid"):
        subscription=event["data"]["object"]
        deactivate_device_by_subscription(subscription.get("id"))
    return {"status":"success"}

@app.get("/success",response_class=HTMLResponse)
async def payment_success(session_id:str=None):
    verified=False
    if session_id and stripe.api_key:
        try:
            session=stripe.checkout.Session.retrieve(session_id)
            verified=session.get("payment_status")=="paid"
        except Exception:
            verified=False
    if verified:
        return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif"><h1 style="color:#4ade80">Payment Received</h1><p>Stripe received your payment.</p><p>Your access will be activated after Stripe confirms the subscription.</p><a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold">Return to AL CIELO</a></body></html>"""
    return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif"><h1 style="color:#f87171">Payment Not Confirmed</h1><p>We could not verify the payment with Stripe.</p><a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold">Return to AL CIELO</a></body></html>"""

@app.get("/cancel",response_class=HTMLResponse)
async def payment_cancel():
    return """<html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif"><h1 style="color:#f87171">Payment Canceled</h1><p>No subscription was activated.</p><a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold">Return Home</a></body></html>"""

@app.post("/api/v1/generate-session")
async def generate_session(request:Request):
    try:
        body=await request.json()
        device_id=str(body.get("device_id","")).strip()
        language=str(body.get("language","es")).lower().strip()
        is_hook=bool(body.get("is_hook",False))

        if language not in ("es","en","pt"):
            language="es"
        if not device_id:
            raise HTTPException(400,"Device id required.")
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(403,"Subscription or login required for full session.")

        prompt=build_prompt(language,is_hook)

        # 1. GEMINI
        raw=await call_gemini(prompt)
        session=parse_ai_session(raw,is_hook)
        if session and not language_ok(session,language):
            session=None

        # 2. OPENAI: entra inmediatamente si Gemini falla,
        # excede el tiempo o entrega contenido inválido.
        if session is None:
            raw=await call_openai(prompt)
            session=parse_ai_session(raw,is_hook)
            if session and not language_ok(session,language):
                session=None

        # 3. LOS 20 RESPALDOS ORIGINALES.
        # Se seleccionan de forma rotativa por dispositivo.
        source="gemini" if session and raw else "fallback"
        if session is None:
            session=fallback_session(device_id,is_hook)
            source="fallback"

        text_content=" ".join(x["instruction"] for x in session["exercises"])

        return {
            "status":"success",
            "source":source,
            "language":language,
            "session":session,
            "session_content":text_content
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500,str(e))
