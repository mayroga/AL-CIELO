import os,sqlite3,random,asyncio
from fastapi import FastAPI,HTTPException,Request,Header
from fastapi.responses import HTMLResponse,FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
import openai

app=FastAPI(title="AL CIELO - Production Engine",version="3.9.3")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

stripe.api_key=os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID=os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET")
ADMIN_USER=os.getenv("ADMIN_USER") or os.getenv("ADMIN_USERNAME")
ADMIN_PASS=os.getenv("ADMIN_PASS") or os.getenv("ADMIN_PASSWORD")
BASE_URL="https://al-cielo.onrender.com"
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
    conn.execute("""CREATE TABLE IF NOT EXISTS fallback_rotation(
        device_id TEXT NOT NULL,
        language TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(device_id,language)
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

def next_fallback_index(device_id,total):
    if not device_id or total<=0:return 0
    language="__all__"
    conn=get_db()
    row=conn.execute("SELECT position FROM fallback_rotation WHERE device_id=? AND language=?",(device_id,language)).fetchone()
    if row is None:
        position=0
        new_position=1%total
        conn.execute("INSERT INTO fallback_rotation(device_id,language,position,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",(device_id,language,new_position))
    else:
        position=int(row["position"])%total
        new_position=(position+1)%total
        conn.execute("UPDATE fallback_rotation SET position=?,updated_at=CURRENT_TIMESTAMP WHERE device_id=? AND language=?",(new_position,device_id,language))
    conn.commit()
    conn.close()
    return position

init_db()

SYSTEM_WELLNESS_PROMPT="""
You are the exclusive professional human-like wellness coach and lifestyle companion for AL CIELO, designed for adults aged 50 and over, including active people, seated people, resting people, people remaining in bed, people with limited mobility, and people with missing limbs.
Your tone must be warm, direct, calm, compassionate and conversational.

STRICT RULES:
1. Never mention phase, fase, auditoría, IA, AI, ChatGPT, Gemini, OpenAI or internal technology.
2. Never use medical terminology, clinical terminology, diagnosis, treatment, therapy or medical authority.
3. Never repeat the exact same session twice. Vary wording, sequence, focus and guidance.
4. Never include IDs, codes, technical tags or internal information.
5. For a free preview, provide only a short warm greeting and one simple breathing action.
6. For a full session, provide an extensive guided wellness and lifestyle session intended to take approximately 10 minutes when spoken slowly.
7. Instructions must be inclusive. A person may be seated, resting, in bed, have limited mobility or have missing limbs. Never require a movement that the person cannot comfortably perform. When appropriate, offer an alternative such as imagining the movement or focusing on available movement.
8. Output ONLY the requested language.
9. Do not include headings, titles, labels or numbered sections inside the spoken session.
10. Separate natural paragraphs with a blank line between paragraphs.
11. Do not mix languages.
"""

FALLBACK_SESSIONS_ES=[
"Bienvenido a su espacio personal de bienestar y armonía diaria. Tómese un instante para acomodarse con absoluta comodidad, ya sea sentado plácidamente en su sillón favorito o descansando de forma reposada en su cama. Vamos a comenzar este momento de pausa centrando toda nuestra atención en el ritmo natural de la respiración. Sienta cómo el aire fresco ingresa suavemente a través de su nariz, recorre su interior y sale despacio. Permita que sus hombros desciendan de manera completamente natural, soltando el peso de la jornada y encontrando un punto de apoyo firme y seguro en la superficie que lo sostiene. Si le es posible y cuenta con movilidad en sus manos y dedos, hágalo de forma sumamente pausada, disfrutando del tacto y la presencia de su propio cuerpo. Si prefiere el reposo absoluto o la quietud, acompañe este proceso sintiendo el calor y el equilibrio de su postura. Inhale despacio contando mentalmente hasta cuatro y exhale con suavidad mientras recorre este momento de calma. Permítase desconectarse de las distracciones externas y habitar este presente lleno de tranquilidad. Su postura debe sentirse cómoda, sin forzar absolutamente nada. Continúe manteniendo este flujo de aire constante, notando cómo cada exhalación regala una sensación de descanso renovador.",
"Comenzamos este momento especial dedicado enteramente a su descanso, equilibrio físico y confort cotidiano. Ubíquese en la posición que hoy le brinde mayor seguridad y bienestar general. Vamos a dirigir la atención hacia el área del cuello y la cabeza, realizando un movimiento imperceptible y muy delicado de lado a lado solo si su cuerpo se lo permite de manera natural, o bien visualizando ese movimiento con total serenidad en su mente. Sienta cómo la mandíbula se afloja, cómo la frente se despeja y cómo la expresión del rostro se vuelve apacible. Tome el control consciente del ritmo de la respiración: inhale profundamente, mantenga el aire con suavidad y exhale muy despacio. Si se encuentra recostado o descansando en su cama, sienta el soporte completo de su espalda y permita que los brazos reposen cómodamente. Mantenga esta cadencia pausada, permitiendo que el tiempo transcurra sin prisa.",
"Un cordial saludo en esta nueva sesión de cuidado personal y bienestar. Conéctese con su comodidad adoptando una postura que le ofrezca un soporte firme, relajado y completamente seguro. Hoy centraremos nuestra atención en la apertura del pecho y en la expansión de una respiración amplia y fluida. Si tiene movilidad en sus brazos, deslícelos con delicadeza hacia una posición de mayor comodidad; de lo contrario, concéntrese en percibir la expansión y contracción natural del cuerpo al compás del aire. Note el punto exacto de contacto de su espalda con el respaldo o la superficie de descanso. Cada exhalación representa una oportunidad para soltar las preocupaciones cotidianas. Mantenga su mente enfocada en este instante presente y siga respirando de manera lenta.",
"Le damos la más cordial bienvenida a su pausa activa y restaurativa de hoy. Sin importar si se encuentra realizando sus actividades, sentado con comodidad o descansando en cama, la prioridad absoluta es su confort. Lleve una suave conciencia hacia los puntos de apoyo principales de su cuerpo, reconociendo el espacio físico que habita con tranquilidad. Perciba el ritmo calmado de su respiración, acompañándolo con respiraciones largas y sin exigencia. Si le es posible dentro de su comodidad actual, mueva muy suavemente las muñecas o los dedos; si prefiere la quietud, permita que la imaginación y la respiración consciente acompañen el momento. Permítase permanecer en esta atmósfera de tranquilidad, donde el objetivo es su bienestar y comodidad.",
"Iniciamos este momento de profunda conexión con su bienestar personal y equilibrio. Acomódese con absoluta libertad y cierre los ojos si le apetece. Vamos a relajar suavemente la parte superior del cuerpo. Relaje los músculos de la cara, separe ligeramente los dientes, deje caer los hombros y respire profundamente. Si alguna zona corporal presenta limitaciones de movimiento, no la fuerce; simplemente obsérvela con aceptación y continúe respirando. Sienta cómo una sensación de bienestar recorre su cuerpo. Este espacio está pensado para brindarle estabilidad y tranquilidad. Siga disfrutando de este compás pausado, sabiendo que cada inhalación y cada exhalación pueden acompañar su sensación de descanso.",
"Bienvenido a su rutina de relajación y movimiento adaptado para el bienestar general. Tome aire de manera natural, profunda y dosificada. Vamos a realizar un recorrido mental consciente por todo su cuerpo, reconociendo cada parte con afecto y respeto por su estado actual. Si posee movilidad en sus extremidades, realice pequeños movimientos sumamente lentos; si se encuentra en reposo, imagine ese movimiento fluyendo con armonía. Mantenga una respiración constante, disfrutando del silencio y de la seguridad de este entorno. Permanezca receptivo a esta sensación de descanso, dejando que el cuerpo encuentre su propia naturalidad sin prisas ni presiones.",
"Es un verdadero placer acompañarle en este espacio de bienestar creado para su comodidad. Sintonice con el momento presente ajustando su postura hasta hallar el punto exacto de reposo. Enfoque la atención en el centro de su cuerpo, permitiendo que cada inhalación traiga una sensación agradable y que cada exhalación se lleve cualquier tensión superficial. Mantenga los brazos y las piernas en la posición que hoy le otorgue mayor comodidad. Este tiempo le pertenece por completo. Sienta el respaldo que lo sostiene y entregue el peso de su cuerpo a la superficie con confianza. Continúe respirando lento y profundo mientras acompañamos cada instante con serenidad.",
"Comenzamos una nueva práctica enfocada en su paz interior, estabilidad y confort físico general. Adopte una postura que le proporcione un soporte óptimo y seguridad. Vamos a relajar paulatinamente los dedos de las manos, los brazos y el cuerpo mediante respiraciones profundas y pausadas. Si alguna extremidad carece de movimiento, recuerde que puede concentrarse en la respiración o imaginar el movimiento. Permítase desconectarse temporalmente del exterior y habitar este instante de tranquilidad. Cada ciclo de aire puede acompañar una sensación de renovación. Disfrute de la estabilidad y la paz que este espacio le ofrece.",
"Bienvenido a su sesión de revitalización, descanso y equilibrio. Busque la postura más cómoda disponible. Dirigiremos la atención hacia los hombros y la parte alta de la espalda, imaginando que una brisa ligera y cálida disuelve cualquier rigidez presente. Tome una inspiración profunda, llene sus pulmones sin prisa y deje salir el aire lentamente. Sienta cómo el cuerpo se afloja y se entrega a un descanso tranquilo. Mantenga siempre una práctica segura, libre de exigencias y adaptada enteramente a su ritmo. Siga respirando de este modo, permitiendo que la tranquilidad acompañe su mente y su cuerpo.",
"Cerramos nuestro ciclo de recomendaciones de bienestar con una sesión centrada en la serenidad y el confort. Acomódese con la certeza de que este tiempo le pertenece. Vamos a unificar la respiración con pequeños movimientos conscientes o con una visualización profunda de ligereza y bienestar. Sienta el soporte que lo sostiene, relaje cada músculo del rostro y permita que el aire fluya naturalmente. Disfrute de la estabilidad y la paz que este espacio proporciona. Permanezca unos instantes disfrutando de esta sensación. Inhale profundamente y prepárese para continuar su día con una renovada sensación de tranquilidad.",
"Iniciamos un nuevo espacio dedicado por completo a su bienestar cotidiano y a la relajación tranquila. Adopte una postura agradable. Lleve su mente hacia las manos, imaginando una sensación agradable de calor. Si descansa en cama, permita que el colchón soporte enteramente su peso. Realice una inspiración lenta, sintiendo cómo el abdomen se mueve suavemente, y al expirar deje que cualquier preocupación se aleje. Esta práctica está diseñada para propiciar un remanso de paz en medio de su jornada. Permita que la tranquilidad le envuelva por completo.",
"Le damos la bienvenida a esta sesión orientada al equilibrio y la distensión. Ajuste su posición corporal para garantizar que cuello, espalda y extremidades se encuentren cómodamente respaldados. Concentre su atención en el simple acto de respirar. Perciba la temperatura del aire al entrar y la sensación al salir. Si nota tensión en el rostro o en la mandíbula, relájela suavemente. Cada inhalación puede acompañar una sensación de serenidad y cada exhalación una sensación de estabilidad. Disfrute de este tiempo de cuidado y descanso.",
"Comenzamos una pausa restaurativa centrada en el alivio y la comodidad. Relaje los brazos a los lados de su cuerpo o sobre su regazo de la manera más cómoda posible. Visualice una suave onda de bienestar que desciende lentamente por el cuerpo, dejando atrás la rigidez. Acompañe este recorrido mental con respiraciones rítmicas, profundas y calmadas. Evite cualquier prisa o exigencia. Este espacio es suyo para descansar, encontrar tranquilidad y disfrutar de comodidad.",
"Saludamos este instante de pausa y armonía enfocado en su bienestar personal. Conéctese con la firmeza del suelo, la silla o la cama que sostiene su cuerpo. Permita que la respiración se vuelva cada vez más lenta y profunda. Si lo prefiere, mantenga los ojos cerrados mientras su atención descansa en el flujo constante del aire. Disfrute de la estabilidad y el sosiego que esta práctica puede ofrecer.",
"Nos adentramos en una sesión pensada para brindarle un respiro profundo y una sensación de distensión. Colóquese en la postura que le aporte mayor comodidad. Dirija su atención hacia la espalda y los hombros, permitiendo que el peso sea recibido por la superficie de apoyo. Respire con absoluta calma, llenando este momento de tranquilidad y ligereza. Este es su momento para permanecer en el presente con seguridad.",
"Bienvenido a este momento de armonización y cuidado de su estilo de vida. Tome una posición que le permita relajarse cómodamente. Inhale aire fresco con tranquilidad, permanezca un instante sin esfuerzo y expúlselo lentamente. Permita que la quietud fortalezca su sensación de paz. Disfrute plenamente de cada minuto de este descanso.",
"Iniciamos una práctica destinada a cultivar el confort, el equilibrio y la paz en su día a día. Sienta el soporte de la almohada o del respaldo adaptándose a su cuerpo. Realice respiraciones profundas y pausadas, centrando la atención en el bienestar que surge al soltar las tensiones cotidianas. Disfrute de este espacio exclusivo de tranquilidad y permita que su energía se renueve naturalmente.",
"Comenzamos un espacio de descanso y relajación profunda para acompañar su rutina de bienestar. Adopte una postura cómoda, libre de presiones y exigencias. Sienta el flujo rítmico de su respiración y cómo cada ciclo puede aportar una mayor sensación de ligereza y estabilidad. Permanezca en este refugio de paz, disfrutando del silencio y de una total comodidad.",
"Le saludamos en esta sesión de pausa y armonía diseñada para su confort diario. Ubíquese en el sitio que le ofrezca mayor apoyo y bienestar. Conecte con su respiración natural, permitiendo que el aire entre y salga de manera apacible y constante. Disfrute de este momento de tregua, estabilidad y cuidado personal sin prisas.",
"Finalizamos nuestro repertorio de bienestar con una sesión orientada al equilibrio y la paz interior. Acomódese con la certeza de que este tiempo es suyo. Respire profundamente, relaje los músculos del rostro y entregue su peso corporal a la superficie con confianza y serenidad. Disfrute de esta sensación de plenitud y prepárese para continuar su jornada con armonía."
]

FALLBACK_SESSIONS_EN=[
"Welcome to your personal space for daily wellness and harmony. Take a moment to make yourself completely comfortable, whether you are sitting peacefully in your favorite chair or resting comfortably in bed. We will begin by bringing our attention to the natural rhythm of your breathing. Feel the air gently enter through your nose and slowly leave your body. Allow your shoulders to drop naturally and let the surface supporting you carry your weight. If you have comfortable movement in your hands and fingers, move them very slowly. If you prefer complete stillness, simply notice the comfort of your position. Breathe in slowly and breathe out gently. Allow yourself to step away from outside distractions and remain in this peaceful moment. Your position should feel comfortable, without forcing anything. Continue this steady breathing and notice how each exhalation can bring a renewed sense of rest.",
"We begin this special moment dedicated entirely to your rest, balance and everyday comfort. Choose the position that gives you the greatest sense of safety and comfort today. Bring your attention toward your neck and head. If it feels comfortable, make a very small and gentle movement from side to side, or simply imagine that movement in your mind. Let your jaw relax and allow your face to become calm. Now follow your breathing: breathe in slowly, pause gently and breathe out slowly. If you are resting in bed, notice the support beneath your back and head and allow your arms to rest comfortably. Continue with this calm rhythm and allow time to pass without hurry.",
"Warm greetings in this new personal wellness session. Find a comfortable position with firm and safe support. Today we will bring attention to the natural opening and closing of the chest as you breathe. If you have comfortable movement in your arms, move them gently toward a more relaxed position. If you do not, simply notice the natural movement of your body while breathing. Notice where your back meets the chair or resting surface. Each exhalation is an opportunity to let the concerns of the day move farther away. Keep your attention in the present moment and continue breathing slowly.",
"Welcome to your active and restorative pause today. Whether you are active, comfortably seated or resting in bed, your comfort comes first. Notice the main areas supporting your body, such as your back, legs or arms. Breathe slowly and comfortably without demanding anything from yourself. If it feels comfortable, make very small movements with your wrists or fingers. If you prefer stillness, simply imagine the movement while continuing to breathe. Allow yourself to remain in this calm atmosphere. The purpose of this moment is your comfort and well-being.",
"We begin this moment of connection with your personal comfort and well-being. Make yourself comfortable and close your eyes if you wish. We will gently relax the upper part of the body. Relax your face, separate your teeth slightly, let your shoulders move away from your ears and breathe slowly. If any part of your body has limited movement, do not force it. Simply notice it calmly and continue breathing. Imagine a comfortable sense of ease moving through your body. This space is here to offer you calm and stability. Continue at this peaceful pace, allowing each breath to accompany your rest.",
"Welcome to your relaxation and adapted movement routine for general well-being. Breathe naturally and calmly, allowing your abdomen to move freely. Take a gentle mental journey through your body, noticing each area with respect for your current situation. If you have comfortable movement in your limbs, make very small and slow movements. If you are resting, imagine those movements gently in your mind. Keep your breathing steady and enjoy the quiet. Remain open to the feeling of rest and allow your body to find its own comfortable rhythm without pressure.",
"It is a pleasure to accompany you in this wellness space created for your comfort. Adjust your position until you find a pleasant place to rest. Bring your attention to the center of your body and notice each breath. Keep your arms and legs in whatever position feels most comfortable today. This time belongs to you. Feel the support beneath you and allow your body weight to rest on that surface. Continue breathing slowly while we remain together in a moment of calm, harmony and respect for your comfort.",
"We begin a new practice focused on your inner peace, stability and physical comfort. Choose a position that gives you good support and a sense of safety. Slowly relax your fingers, arms and body through calm breathing. If any limb does not move, simply focus on your breathing or imagine a comfortable movement. Allow yourself to temporarily step away from outside distractions. Each breathing cycle can accompany a sense of renewal while you remain seated or resting. Enjoy the stability and peace of this moment.",
"Welcome to your session of renewal, rest and balance. Find the most comfortable position available to you. Bring your attention to your shoulders and upper back, imagining a gentle warm breeze easing any sense of stiffness. Take a deep but comfortable breath and slowly let the air leave your body. Feel yourself becoming more relaxed and allow the supporting surface to carry your weight. Keep everything comfortable and free from pressure. This is a valuable moment of rest from the demands of the day. Continue breathing calmly and allow the peaceful feeling to remain with you.",
"We close this cycle of wellness recommendations with a session centered on calm and comfort. Settle into your position knowing that this time belongs to you. Combine your breathing with small comfortable movements or simply imagine a feeling of lightness. Feel the support beneath you, relax your face and allow the air to move naturally. Enjoy the stability and peace of this moment. Remain here for a few quiet breaths. Take one final comfortable breath and prepare to continue your day with a renewed sense of calm.",
"We begin a new space dedicated completely to your everyday well-being and quiet relaxation. Choose a pleasant position. Bring your attention to your hands and imagine a comfortable warmth moving through them. If you are resting in bed, allow the mattress to fully support your weight. Breathe in slowly and notice the gentle movement of your abdomen. As you breathe out, allow any concern to move farther away. This practice creates a peaceful pause in the middle of your day. Let the calm atmosphere surround you.",
"Welcome to this session focused on balance and relaxation. Adjust your position so your neck, back and arms or legs are comfortably supported. Bring your attention to the simple act of breathing. Notice the temperature of the air as it enters and the sensation as it leaves. If you notice tension in your face or jaw, gently relax it. Each breath can accompany a greater sense of calm and stability. Enjoy this time of personal care and rest.",
"We begin a restorative pause centered on comfort. Let your arms rest beside your body or on your lap in the most comfortable position available. Imagine a gentle wave of well-being moving slowly through your body and leaving stiffness behind. Follow this image with calm, steady breathing. Avoid rushing or demanding anything from yourself. This space is yours to rest, regain energy and enjoy comfort.",
"We welcome this moment of pause and harmony dedicated to your well-being. Notice the support of the floor, chair or bed beneath you. Allow your breathing to become slower and calmer, giving your attention a steady point to follow. If you wish, close your eyes while you notice the steady movement of the air. Enjoy the stability and quiet of this moment.",
"We enter a session designed to give you a deep breath and a comfortable sense of relaxation. Choose the position that gives you the greatest comfort. Bring your attention to your back and shoulders and allow the surface beneath you to receive your weight. Breathe calmly and fill this moment with peace and lightness. This is your time to remain present with comfort and safety.",
"Welcome to this moment of harmony and lifestyle care. Choose a position that allows you to relax comfortably. Breathe in fresh air calmly, pause for a moment without effort and slowly breathe out. Allow the quiet around you to support your sense of peace. Enjoy every minute of this restful moment.",
"We begin a practice intended to cultivate comfort, balance and peace in your day. Feel the support of your pillow, bed or chair adapting to your body. Breathe deeply and calmly while focusing your attention on the comfortable feeling that comes when everyday tension is released. Enjoy this private space of quiet and allow your energy to renew naturally.",
"We begin a space of deep rest and relaxation to accompany your wellness routine. Choose a comfortable position without pressure or demands. Notice the rhythm of your breathing and how each cycle can bring a greater sense of lightness and inner stability. Remain in this peaceful space and enjoy the quiet and physical comfort.",
"We welcome you to this pause and harmony session created for your everyday comfort. Find the place that gives you the greatest support and well-being. Connect with your natural breathing and allow each breath to enter and leave calmly. Enjoy this moment of pause, stability and personal care without rushing.",
"We finish our collection of wellness sessions with a moment dedicated to balance and inner peace. Settle comfortably knowing that this time belongs to you. Breathe deeply, relax the muscles of your face and allow the surface beneath you to support your body with confidence. Enjoy this sense of calm and prepare to continue your day with greater harmony."
]

FALLBACK_SESSIONS_PT=[
"Bem-vindo ao seu espaço pessoal de bem-estar e harmonia diária. Reserve um instante para se acomodar com absoluto conforto, sentado tranquilamente em sua poltrona ou descansando em sua cama. Vamos começar concentrando a atenção no ritmo natural da respiração. Sinta o ar entrando suavemente pelo nariz e saindo devagar. Permita que os ombros desçam naturalmente e deixe a superfície que sustenta você carregar seu peso. Se tiver movimento confortável nas mãos e nos dedos, mova-os lentamente. Se preferir permanecer quieto, simplesmente perceba o conforto da sua posição. Inspire devagar e expire suavemente. Permita-se afastar das distrações externas e permanecer neste momento tranquilo. Sua posição deve ser confortável, sem forçar nada. Continue respirando e perceba como cada expiração pode trazer uma sensação renovada de descanso.",
"Começamos este momento especial dedicado ao seu descanso, equilíbrio e conforto cotidiano. Escolha a posição que ofereça maior segurança e conforto hoje. Leve sua atenção para o pescoço e a cabeça. Se for confortável, faça um pequeno movimento delicado de um lado para o outro ou simplesmente imagine esse movimento. Relaxe a mandíbula e suavize o rosto. Agora acompanhe sua respiração: inspire lentamente, faça uma pequena pausa e expire devagar. Se estiver descansando na cama, perceba o apoio das costas e da cabeça e deixe os braços repousarem confortavelmente. Continue nesse ritmo tranquilo e permita que o tempo passe sem pressa.",
"Saudações nesta nova sessão de bem-estar pessoal. Encontre uma posição confortável com apoio firme e seguro. Hoje vamos prestar atenção ao movimento natural do peito durante a respiração. Se tiver movimento confortável nos braços, leve-os suavemente para uma posição mais relaxada. Se não tiver, simplesmente perceba o movimento natural do corpo enquanto respira. Observe onde suas costas encontram a cadeira ou a superfície de descanso. Cada expiração é uma oportunidade para deixar as preocupações do dia mais distantes. Mantenha sua atenção no presente e continue respirando lentamente.",
"Seja muito bem-vindo à sua pausa restauradora de hoje. Esteja ativo, sentado confortavelmente ou descansando na cama, seu conforto vem primeiro. Perceba as principais áreas que apoiam seu corpo, como costas, pernas ou braços. Respire lentamente e sem exigência. Se for confortável, faça movimentos muito pequenos com os pulsos ou dedos. Se preferir ficar parado, imagine o movimento enquanto continua respirando. Permita-se permanecer nesta atmosfera tranquila. O objetivo deste momento é seu conforto e bem-estar.",
"Começamos este momento de conexão com seu conforto e bem-estar. Acomode-se e feche os olhos se desejar. Vamos relaxar suavemente a parte superior do corpo. Relaxe o rosto, deixe os dentes ligeiramente separados, afaste os ombros das orelhas e respire devagar. Se alguma parte do corpo tiver movimento limitado, não force. Apenas observe com tranquilidade e continue respirando. Imagine uma sensação agradável percorrendo seu corpo. Este espaço oferece calma e estabilidade. Continue neste ritmo tranquilo.",
"Bem-vindo à sua rotina de relaxamento e movimento adaptado para o bem-estar. Respire naturalmente e com calma, permitindo que o abdômen se mova livremente. Faça uma pequena caminhada mental pelo corpo, percebendo cada região com respeito pela sua situação atual. Se tiver movimento confortável nos membros, faça movimentos pequenos e lentos. Se estiver descansando, imagine esses movimentos suavemente. Mantenha a respiração constante e aproveite o silêncio. Permita que o corpo encontre seu próprio ritmo confortável sem pressão.",
"É um prazer acompanhar você neste espaço de bem-estar criado para seu conforto. Ajuste sua posição até encontrar um lugar agradável para descansar. Leve a atenção para o centro do corpo e perceba cada respiração. Mantenha braços e pernas na posição que for mais confortável hoje. Este tempo pertence a você. Sinta o apoio abaixo do corpo e permita que seu peso descanse sobre essa superfície. Continue respirando lentamente neste momento de calma e harmonia.",
"Começamos uma nova prática focada na sua paz interior, estabilidade e conforto. Escolha uma posição com bom apoio e sensação de segurança. Relaxe lentamente os dedos, braços e corpo através de uma respiração tranquila. Se alguma parte não tiver movimento, concentre-se simplesmente na respiração ou imagine um movimento confortável. Afaste-se temporariamente das distrações externas. Cada ciclo da respiração pode acompanhar uma sensação de renovação. Aproveite a estabilidade e a tranquilidade deste momento.",
"Bem-vindo à sua sessão de renovação, descanso e equilíbrio. Encontre a posição mais confortável disponível. Leve a atenção para os ombros e a parte superior das costas, imaginando uma brisa suave e agradável diminuindo qualquer sensação de rigidez. Inspire profundamente sem pressa e solte o ar lentamente. Sinta o corpo relaxar e permita que a superfície de apoio receba seu peso. Mantenha tudo confortável e sem pressão. Este é um momento valioso de descanso.",
"Encerramos este ciclo de recomendações de bem-estar com uma sessão centrada na calma e no conforto. Acomode-se sabendo que este tempo pertence a você. Combine sua respiração com pequenos movimentos confortáveis ou simplesmente imagine uma sensação de leveza. Sinta o apoio abaixo de você, relaxe o rosto e permita que o ar se mova naturalmente. Aproveite a estabilidade e a tranquilidade. Permaneça por alguns momentos respirando calmamente e prepare-se para continuar seu dia com serenidade.",
"Iniciamos um novo espaço dedicado ao seu bem-estar cotidiano e ao relaxamento tranquilo. Escolha uma posição agradável. Leve sua atenção para as mãos e imagine uma sensação confortável de calor passando por elas. Se estiver na cama, permita que o colchão sustente completamente seu peso. Inspire lentamente e perceba o movimento suave do abdômen. Ao expirar, permita que qualquer preocupação fique mais distante. Esta prática cria uma pausa tranquila durante o dia. Deixe a calma envolver você.",
"Seja bem-vindo a esta sessão voltada ao equilíbrio e ao relaxamento. Ajuste sua posição para que pescoço, costas e braços ou pernas estejam confortavelmente apoiados. Concentre a atenção no simples ato de respirar. Perceba a temperatura do ar ao entrar e a sensação ao sair. Se perceber tensão no rosto ou na mandíbula, relaxe suavemente. Cada respiração pode acompanhar uma sensação maior de calma e estabilidade. Aproveite este tempo de cuidado e descanso.",
"Começamos uma pausa restauradora centrada no conforto. Deixe os braços repousarem ao lado do corpo ou sobre o colo da maneira mais confortável. Imagine uma onda suave de bem-estar percorrendo lentamente o corpo e deixando a rigidez para trás. Acompanhe essa imagem com uma respiração calma e constante. Evite pressa ou exigência. Este espaço é seu para descansar, recuperar energia e desfrutar de conforto.",
"Saudamos este momento de pausa e harmonia dedicado ao seu bem-estar. Perceba o apoio do chão, da cadeira ou da cama abaixo de você. Permita que a respiração fique mais lenta e tranquila. Se desejar, feche os olhos enquanto percebe o movimento constante do ar. Aproveite a estabilidade e a tranquilidade deste momento.",
"Entramos em uma sessão criada para oferecer uma respiração profunda e uma sensação confortável de relaxamento. Escolha a posição que ofereça maior conforto. Direcione a atenção para as costas e os ombros e permita que a superfície abaixo de você receba seu peso. Respire com calma e preencha este momento com tranquilidade e leveza. Este é o seu momento para permanecer no presente com conforto e segurança.",
"Bem-vindo a este momento de harmonia e cuidado com seu estilo de vida. Escolha uma posição que permita relaxar confortavelmente. Inspire o ar fresco com calma, faça uma pequena pausa sem esforço e expire lentamente. Permita que o silêncio apoie sua sensação de paz. Aproveite cada minuto deste momento de descanso.",
"Iniciamos uma prática destinada a cultivar conforto, equilíbrio e paz no seu dia. Sinta o apoio do travesseiro, da cama ou da cadeira acompanhando seu corpo. Respire profundamente e com tranquilidade enquanto concentra sua atenção na sensação agradável que surge quando as tensões diminuem. Aproveite este espaço de tranquilidade e permita que sua energia seja renovada naturalmente.",
"Começamos um espaço de descanso e relaxamento profundo para acompanhar sua rotina de bem-estar. Escolha uma posição confortável, sem pressão ou exigência. Perceba o ritmo da respiração e como cada ciclo pode trazer uma sensação maior de leveza e estabilidade. Permaneça neste espaço de paz e aproveite o silêncio e o conforto físico.",
"Saudamos você nesta sessão de pausa e harmonia criada para seu conforto diário. Encontre o local que oferece maior apoio e bem-estar. Conecte-se com sua respiração natural e permita que cada respiração entre e saia calmamente. Aproveite este momento de pausa, estabilidade e cuidado pessoal sem pressa.",
"Finalizamos nosso repertório de bem-estar com um momento dedicado ao equilíbrio e à paz interior. Acomode-se sabendo que este tempo pertence a você. Respire profundamente, relaxe os músculos do rosto e permita que a superfície abaixo sustente seu corpo com confiança. Aproveite esta sensação de tranquilidade e prepare-se para continuar seu dia com maior harmonia."
]

LANG_NAMES={"es":"Spanish","en":"English","pt":"Portuguese"}
FALLBACK_BANKS={"es":FALLBACK_SESSIONS_ES,"en":FALLBACK_SESSIONS_EN,"pt":FALLBACK_SESSIONS_PT}

def get_fallback(device_id,language):
    bank=FALLBACK_BANKS.get(language,FALLBACK_SESSIONS_ES)
    index=next_fallback_index(device_id,len(bank))
    return bank[index%len(bank)]

@app.get("/",response_class=FileResponse)
async def serve_frontend():
    return FileResponse("index.html",media_type="text/html")

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
        checkout_session=stripe.checkout.Session.create(
            line_items=[{"price":STRIPE_PRICE_ID,"quantity":1}],
            mode="subscription",
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}&device_id={device_id}",
            cancel_url=f"{BASE_URL}/cancel",
            metadata={"device_id":device_id}
        )
        return {"status":"success","checkout_url":checkout_session.url}
    except HTTPException:raise
    except stripe.error.StripeError as e:raise HTTPException(status_code=502,detail=f"Stripe error: {str(e)}")
    except Exception as e:raise HTTPException(status_code=500,detail=f"Checkout error: {str(e)}")

@app.post("/webhook/stripe")
async def stripe_webhook(request:Request,stripe_signature:str=Header(default=None)):
    payload=await request.body()
    if not STRIPE_WEBHOOK_SECRET:raise HTTPException(status_code=500,detail="STRIPE_WEBHOOK_SECRET is missing in Render.")
    if not stripe_signature:raise HTTPException(status_code=400,detail="Missing Stripe-Signature header.")
    try:
        event=stripe.Webhook.construct_event(payload,stripe_signature,STRIPE_WEBHOOK_SECRET)
    except ValueError:raise HTTPException(status_code=400,detail="Invalid webhook payload.")
    except stripe.error.SignatureVerificationError:raise HTTPException(status_code=400,detail="Invalid Stripe webhook signature.")
    except Exception as e:raise HTTPException(status_code=400,detail=f"Webhook error: {str(e)}")
    event_type=event.get("type")
    if event_type=="checkout.session.completed":
        session=event["data"]["object"]
        metadata=session.get("metadata") or {}
        device_id=metadata.get("device_id")
        customer_id=session.get("customer")
        subscription_id=session.get("subscription")
        payment_status=session.get("payment_status")
        if device_id and payment_status in ("paid","no_payment_required"):
            authorize_device(device_id,customer_id,subscription_id)
    elif event_type in ("customer.subscription.deleted","customer.subscription.unpaid"):
        subscription=event["data"]["object"]
        deactivate_device_by_subscription(subscription.get("id"))
    elif event_type=="customer.subscription.updated":
        subscription=event["data"]["object"]
        status=subscription.get("status")
        subscription_id=subscription.get("id")
        conn=get_db()
        if status in ("active","trialing"):
            conn.execute("UPDATE authorized_devices SET status='active',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",(subscription_id,))
        elif status in ("canceled","unpaid","incomplete_expired","past_due"):
            conn.execute("UPDATE authorized_devices SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",(subscription_id,))
        conn.commit()
        conn.close()
    return {"status":"success"}

@app.get("/api/v1/access-status")
async def access_status(device_id:str=""):
    return {"authorized":check_device_authorization(device_id.strip())}

@app.get("/success",response_class=HTMLResponse)
async def payment_success(session_id:str=None,device_id:str=None):
    verified=False
    if session_id and stripe.api_key:
        try:
            session=stripe.checkout.Session.retrieve(session_id)
            verified=session.get("payment_status") in ("paid","no_payment_required")
        except Exception:
            verified=False
    if verified:
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>AL CIELO</title></head><body style="background:#0f172a;color:white;text-align:center;padding:60px 20px;font-family:Arial,sans-serif"><h1 style="color:#4ade80">Payment Received</h1><p>Stripe received your payment.</p><p>Returning to AL CIELO and confirming your access.</p><script>setTimeout(function(){{window.location.replace("{BASE_URL}/?session_id="+encodeURIComponent("{session_id or ""}")+"&device_id="+encodeURIComponent("{device_id or ""}"));}},1200);</script><a href="{BASE_URL}" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold">Return to AL CIELO</a></body></html>"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>AL CIELO</title></head><body style="background:#0f172a;color:white;text-align:center;padding:60px 20px;font-family:Arial,sans-serif"><h1 style="color:#f87171">Payment Not Confirmed</h1><p>We could not verify the payment with Stripe.</p><a href="{BASE_URL}" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold">Return to AL CIELO</a></body></html>"""

@app.get("/cancel",response_class=HTMLResponse)
async def payment_cancel():
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>AL CIELO</title></head><body style="background:#0f172a;color:white;text-align:center;padding:60px 20px;font-family:Arial,sans-serif"><h1 style="color:#f87171">Payment Canceled</h1><p>No subscription was activated.</p><a href="{BASE_URL}" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold">Return Home</a></body></html>"""

@app.post("/api/v1/generate-session")
async def generate_session(request:Request):
    try:
        body=await request.json()
        device_id=str(body.get("device_id","")).strip()
        language=str(body.get("language","es")).lower().strip()
        is_hook=bool(body.get("is_hook",False))
        if language not in ("es","en","pt"):language="es"
        if not device_id:raise HTTPException(status_code=400,detail="Device id required.")
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(status_code=403,detail="Subscription or login required for full session.")
        selected_lang_name=LANG_NAMES[language]
        unique_prompt_modifier=random.choice([
            "Focus on shoulder relaxation, upper body comfort and peaceful pacing.",
            "Focus on comfortable hand, finger and wrist micro-movements combined with calm breathing.",
            "Focus on breathing rhythm, comfortable posture and a peaceful pace.",
            "Focus on deep relaxation, quiet attention and comfortable resting support.",
            "Focus on gentle neck comfort, facial relaxation and total body grounding."
        ])
        if is_hook:
            prompt=f"""Generate a strict 30-SECOND FREE PREVIEW ONLY in {selected_lang_name}.
Maximum 50 words.
Give a warm greeting and one single gentle breathing action.
Output ONLY plain conversational {selected_lang_name}.
Do not use any other language.
No title.
No heading.
No labels."""
            max_tokens=150
        else:
            prompt=f"""{unique_prompt_modifier}

Generate a completely unique, extensive, detailed 10-MINUTE GUIDED WELLNESS AND LIFESTYLE SESSION ONLY in {selected_lang_name} for adults aged 50 and over.

The person may be active, seated, resting, in bed, have limited mobility or have missing limbs.
Guide the person in a warm, calm and practical manner.
Never require a movement that may be impossible for the person.
Offer comfortable alternatives when appropriate.

DO NOT use the words phase, fase, stage, IA, AI, ChatGPT, Gemini or OpenAI.
DO NOT use medical or clinical terminology.
DO NOT include diagnoses, treatments, therapy or medical authority.
DO NOT include IDs, codes, numbers used as labels or technical tags.
DO NOT include headings, titles or numbered sections.

Use multiple separate natural paragraphs.
Each paragraph must contain complete spoken content.
Output ONLY conversational {selected_lang_name}.
DO NOT MIX LANGUAGES.
The entire response must remain in {selected_lang_name}.
"""
            max_tokens=5000
        response_text=""
        if gemini_client:
            try:
                task=asyncio.to_thread(
                    gemini_client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=.98,
                        max_output_tokens=max_tokens
                    )
                )
                result=await asyncio.wait_for(task,timeout=20)
                response_text=(result.text or "").strip()
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
                    temperature=.98,
                    max_tokens=max_tokens
                )
                result=await asyncio.wait_for(task,timeout=20)
                response_text=(result.choices[0].message.content or "").strip()
            except Exception:
                response_text=""
        if not response_text or (not is_hook and len(response_text)<400):
            if is_hook:
                hooks={
                    "es":"Bienvenido a AL CIELO. Adopte una postura cómoda, inhale lentamente por la nariz y deje que sus hombros se relajen mientras exhala.",
                    "en":"Welcome to AL CIELO. Find a comfortable position, breathe in slowly through your nose, and let your shoulders relax as you breathe out.",
                    "pt":"Bem-vindo ao AL CIELO. Encontre uma posição confortável, inspire lentamente pelo nariz e deixe os ombros relaxarem ao expirar."
                }
                response_text=hooks[language]
            else:
                response_text=get_fallback(device_id,language)
        return {"status":"success","session_content":response_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500,detail=str(e))
