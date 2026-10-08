import os
import sqlite3
import random
import asyncio
from fastapi import FastAPI,HTTPException,Request,Header
from fastapi.responses import HTMLResponse,FileResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
import openai

app=FastAPI(title="AL CIELO - Production Engine",version="3.9.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
if openai_api_key:
    openai_client=openai.OpenAI(api_key=openai_api_key)
else:
    openai_client=None


def get_db():
    conn=sqlite3.connect(DB_FILE)
    conn.row_factory=sqlite3.Row
    return conn


def init_db():
    conn=get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS authorized_devices(
        device_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'active',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS fallback_rotation(
        device_id TEXT NOT NULL,
        language TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(device_id,language)
    )"""
    )
    conn.commit()
    conn.close()


def authorize_device(device_id,customer_id=None,subscription_id=None):
    if not device_id:
        return
    conn=get_db()
    conn.execute(
        """INSERT INTO authorized_devices
        (device_id,status,stripe_customer_id,stripe_subscription_id,updated_at)
        VALUES(?,'active',?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(device_id) DO UPDATE SET
        status='active',
        stripe_customer_id=excluded.stripe_customer_id,
        stripe_subscription_id=excluded.stripe_subscription_id,
        updated_at=CURRENT_TIMESTAMP""",
        (device_id,customer_id,subscription_id),
    )
    conn.commit()
    conn.close()


def check_device_authorization(device_id):
    if not device_id:
        return False
    conn=get_db()
    row=conn.execute(
        "SELECT status FROM authorized_devices WHERE device_id=?",
        (device_id,)
    ).fetchone()
    conn.close()
    return bool(row and row["status"]=="active")


def deactivate_device_by_subscription(subscription_id):
    if not subscription_id:
        return
    conn=get_db()
    conn.execute(
        "UPDATE authorized_devices SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",
        (subscription_id,)
    )
    conn.commit()
    conn.close()


def next_fallback_index(device_id,language,total):
    if total<=0:
        return 0
    conn=get_db()
    row=conn.execute(
        "SELECT position FROM fallback_rotation WHERE device_id=? AND language=?",
        (device_id,language)
    ).fetchone()
    if row is None:
        position=0
        conn.execute(
            """INSERT INTO fallback_rotation
            (device_id,language,position,updated_at)
            VALUES(?,?,?,CURRENT_TIMESTAMP)""",
            (device_id,language,1 if total>1 else 0)
        )
    else:
        position=int(row["position"])%total
        new_position=(position+1)%total
        conn.execute(
            """UPDATE fallback_rotation
            SET position=?,updated_at=CURRENT_TIMESTAMP
            WHERE device_id=? AND language=?""",
            (new_position,device_id,language)
        )
    conn.commit()
    conn.close()
    return position


init_db()

SYSTEM_WELLNESS_PROMPT="""
You are the exclusive, professional human-like wellness coach and lifestyle companion for the platform "AL CIELO", designed for adults aged 50 and over, encompassing active individuals, seated, resting, or poststrated in bed, including those with limited mobility or missing limbs.
Your tone must be warm, direct, calm, compassionate, and conversational.

STRICT LEGAL & OPERATIONAL RULES:
1. NEVER mention words like "phase", "fase", "auditoría", "IA", or "ChatGPT". Be purely action-oriented and professional.
2. NEVER use medical terminology, clinical terms, diagnoses, or anything implying medical treatment or authority. This is strictly a lifestyle, comfort, relaxation, and physical wellbeing guidance service.
3. NEVER repeat the exact same session twice. Always introduce fresh phrasing, varied exercise sequences, and unique restorative focuses while maintaining absolute safety.
4. NEVER include internal ID numbers, random codes, or technical tags in the text output.
5. IF THIS IS A FREE 30-SECOND PREVIEW (is_hook=true):
   - Provide a quick, light greeting and a single simple breathing action that lasts about 30 seconds when read aloud.
6. IF THIS IS THE FULL 10-MINUTE SESSION (is_hook=false) - APPLIES TO STRIPE AND USERNAME/PASSWORD:
   - Act as a live personal wellness trainer.
   - Write an extensive, deep, continuous, highly detailed routine designed to take a full 10 minutes of calm, slow spoken practice.
   - Include inclusive instructions: if a user lacks limbs or mobility, guide them to perform the movements mentally or focus on available joints, fingers, neck, shoulders and breathing.
   - Break down the flow naturally into separate paragraphs with clear pauses.
7. Output only the requested language.
8. Do not place headings or titles inside the spoken session.
"""


FALLBACK_SESSIONS_ES=[
"Bienvenido a su espacio personal de bienestar y armonía diaria. Tómese un instante para acomodarse con absoluta comodidad, ya sea sentado plácidamente en su sillón favorito o descansando de forma reposada en su cama. Vamos a comenzar este momento de pausa centrando toda nuestra atención en el ritmo natural de la respiración. Sienta cómo el aire fresco ingresa suavemente a través de su nariz, recorre su interior y sale despacio, aliviando cualquier rastro de tensión acumulada en el día. Permita que sus hombros desciendan de manera completamente natural, soltando el peso de la jornada y encontrando un punto de apoyo firme y seguro en la superficie que lo sostiene. Si le es posible y cuenta con movilidad en sus manos y dedos, hágalo de forma sumamente pausada, disfrutando del tacto y la presencia de su propio cuerpo. Si prefiere el reposo absoluto o la quietud, acompañe este proceso sintiendo el calor y el equilibrio de su postura. Inhale despacio contando mentalmente hasta cuatro, sostenga el aire con total serenidad durante un instante, y exhale con suavidad infinita mientras recorremos juntos este sendero de calma profunda. Permítase un momento para desconectarse de las distracciones externas y habitar este presente lleno de tranquilidad. Su postura debe sentirse cómoda, sin forzar absolutamente nada; simplemente deje que el cuerpo encuentre su propio estado de relajación natural. Continuamos manteniendo este flujo de aire constante, notando cómo cada exhalación regala una sensación de descanso renovador a cada fibra de su ser, brindándole estabilidad, esperanza y un profundo bienestar interior en este espacio diseñado exclusivamente para usted.",
"Comenzamos este momento especial dedicado enteramente a su descanso, equilibrio físico y confort cotidiano. Ubíquese en la posición que hoy le brinde mayor seguridad y bienestar general. Vamos a dirigir la atención hacia el área del cuello y la cabeza, realizando un movimiento imperceptible y muy delicado de lado a lado solo si su cuerpo se lo permite de manera natural, o bien visualizando ese movimiento con total serenidad en su mente. Sienta cómo los músculos de la mandíbula se aflojan, cómo la frente se despeja y cómo la expresión del rostro se vuelve apacible. Tomaremos el control consciente del ritmo de la respiración: inhalamos profundamente llenando el pecho con energía renovada, retenemos el aire con extrema suavidad, y exhalamos muy despacio liberando cualquier carga del entorno. Disfrute de esta atención plena orientada a su comodidad. Cada segundo invertido en esta práctica es un regalo para su calidad de vida y su tranquilidad mental. Si se encuentra recostado o descansando en su cama, sienta el soporte completo de su espalda, la almohada sosteniendo su cabeza con firmeza y los brazos reposando en un ángulo de total comodidad. Vamos a mantener esta cadencia de respiración pausada, permitiendo que el tiempo transcurra con suavidad, sin prisa, acompañando cada minuto con una actitud abierta, positiva y reconfortante.",
"Un cordial saludo en esta nueva sesión de cuidado personal y bienestar integral. Conéctese con su comodidad adoptando una postura que le ofrezca un soporte firme, relajado y completamente seguro. Hoy centraremos nuestra atención en la apertura del pecho y en la expansión de una respiración amplia y fluida. Si tiene movilidad en sus brazos, deslícelos con delicadeza hacia una posición de mayor holgura; de lo contrario, concéntrese por completo en percibir la expansión y contracción natural del tórax al compás del aire. Note de manera consciente el punto exacto de contacto de su espalda con el respaldo o la superficie de descanso, sintiendo cómo el cuerpo se afianza con confianza. Cada exhalación representa una magnífica oportunidad para soltar las preocupaciones cotidianas y regalarle a su organismo un respiro profundo, ordenado y armónico. Mantenga su mente enfocada en este instante presente, disfrutando del silencio constructivo y de la compañía de esta guía diseñada para propiciar un estado óptimo de relajación y estabilidad. Siga respirando de manera lenta, permitiendo que la calma se expanda desde el centro de su pecho hacia los brazos, las manos y el resto de su cuerpo, consolidando un refugio de paz interior.",
"Le damos la más cordial bienvenida a su pausa activa y restaurativa de hoy. Sin importar si se encuentra en plena actividad cotidiana, sentado con comodidad o descansando plácidamente en cama, la prioridad absoluta es su confort. Vamos a llevar una suave conciencia hacia los puntos de apoyo principales de su cuerpo: la espalda, las piernas o los brazos, reconociendo el espacio físico que habita con total gratitud. Comience a percibir el latido calmado y constante de su corazón, acompañándolo con respiraciones largas, profundas y sin ningún tipo de exigencia. Si le es posible dentro de su comodidad actual, mueva milimétricamente las muñecas o los dedos de los pies; si prefiere la quietud, permita que la visualización y la respiración consciente cumplan la labor de relajar cada rincón de su anatomía. Este ejercicio promueve una sensación inigualable de ligereza y descanso profundo. Permítase flotar en esta atmósfera de tranquilidad, donde el único objetivo es su bienestar y su comodidad absoluta. Continuamos respirando con suavidad, dejando que los minutos transcurran en un entorno de paz, equilibrio y seguridad inquebrantable.",
"Iniciamos este momento de profunda conexión con su bienestar personal y equilibrio físico. Acomódese con absoluta libertad y cierre los ojos si le apetece, permitiendo que la voz le acompañe paso a paso en este recorrido de relajación. Hoy trabajaremos en la disolución de tensiones acumuladas en la parte superior del cuerpo. Relaje los músculos de la cara, despegue ligeramente los dientes, deje caer los hombros alejándolos de las orejas y respire profundamente. Si alguna zona corporal presenta rigidez o limitaciones de movimiento, evite forzarla por completo; simplemente obsérvela con aceptación y envíele una bocanada de aire cálido y reconfortante. Sienta cómo una corriente de bienestar recorre su organismo de pies a cabeza en un flujo constante, apacible y revitalizador. Este espacio está pensado para brindarle estabilidad y esperanza, permitiéndole reconectar con su centro de energía y tranquilidad. Siga disfrutando de este compás pausado, sabiendo que cada inhalación fortalece su equilibrio y cada exhalación borra cualquier rastro de prisa o inquietud.",
"Bienvenido a su rutina de relajación y movimiento adaptado para el bienestar general. Tome aire de manera natural, profunda y dosificada, permitiendo que el área del abdomen se expanda con total libertad. Vamos a realizar un recorrido mental consciente por todo su cuerpo, reconociendo cada parte con afecto y respeto por su estado actual. Si posee movilidad en sus extremidades, realice pequeños círculos sumamente lentos con las manos; si se encuentra en reposo absoluto, imagine ese movimiento fluyendo con perfecta armonía en su imaginación. Mantenga una respiración compasiva y constante, disfrutando del silencio y de la seguridad de este entorno creado para su cuidado. La constancia en estos pequeños hábitos de pausa aporta una gran estabilidad emocional y física, ayudando a que su día transcurra con mayor fluidez y serenidad. Permanezca receptivo a esta sensación de descanso, dejando que el cuerpo se recupere y encuentre su propia naturalidad sin prisas ni presiones de ninguna índole.",
"Es un verdadero placer acompañarle en este espacio de bienestar estructurado exclusivamente para su comodidad. Sintonice con el momento presente ajustando su postura hasta hallar el punto exacto de reposo y confort. Vamos a enfocar la atención en el centro de su cuerpo, permitiendo que cada inhalación traiga una bocanada de energía renovada y que cada exhalación se lleve cualquier molestia superficial. Mantenga los brazos y las piernas en la posición que hoy le otorgue mayor alivio, guiándose únicamente por el compás pausado de una respiración consciente y deliberada. Este tiempo le pertenece por completo; es un compromiso con su propia calidad de vida y su equilibrio diario. Sienta el respaldo firme que lo sostiene y entregue el peso de su cuerpo a la superficie con total confianza, sabiendo que se encuentra en un entorno seguro y protector. Continúe respirando lento y profundo mientras acompañamos cada instante con serenidad, armonía y un profundo respeto por su comodidad.",
"Comenzamos una nueva práctica enfocada en su paz interior, estabilidad y confort físico general. Adopte una postura que le proporcione un soporte óptimo y una sensación inquebrantable de seguridad. Vamos a relajar paulatinamente los dedos de las manos, los brazos y la columna vertebral mediante respiraciones profundas, pausadas y bien dirigidas. Si alguna extremidad carece de movimiento, recuerde que su mente y su respiración cumplen el rol principal de activar la relajación profunda y la circulación armónica. Permítase desconectarse temporalmente del exterior y habitar este instante de tranquilidad absoluta, donde las tensiones simplemente se desvanecen. Cada ciclo de aire fresco limpia su mente y revitaliza su postura, permitiéndole experimentar una profunda renovación desde la comodidad de su asiento o cama. Disfrute de la estabilidad y la paz que este espacio le otorga en cada segundo, manteniendo una actitud de calma y bienestar duradero.",
"Bienvenido a su sesión de revitalización, descanso y equilibrio armónico. Busque la postura más cómoda y favorable disponible para usted en este preciso momento. Dirigiremos la atención hacia la zona de los hombros y la parte alta de la espalda, imaginando que una brisa ligera y cálida disuelve cualquier rigidez presente. Tome una inspiración profunda, llene sus pulmones sin prisa alguna y deje salir el aire de forma prolongada y suave a través de sus labios. Sienta cómo el cuerpo se afloja notablemente y se entrega a un descanso reparador, manteniendo siempre una práctica segura, libre de exigencias y adaptada enteramente a su ritmo. Este proceso favorece la distensión muscular y le otorga un valioso momento de tregua frente a las exigencias del día a día. Siga respirando de este modo, permitiendo que la tranquilidad inunde cada espacio de su mente y su cuerpo con total naturalidad.",
"Cerramos nuestro ciclo de recomendaciones de bienestar con una sesión centrada en la serenidad absoluta y el confort restaurador. Acomódese con la absoluta certeza de que este tiempo le pertenece por completo. Vamos a unificar la respiración con pequeños movimientos conscientes o con una visualización profunda de ligereza y bienestar en todo su entorno. Sienta el soporte firme que lo sostiene, relaje cada músculo de su rostro y permita que el aire fluya sin ningún tipo de obstáculo ni restricción. Disfrute de la estabilidad y la paz que este espacio le proporciona, sabiendo que cuidar de su descanso es la mejor manera de honrar su vitalidad. Permanezca unos instantes disfrutando de esta sensación de plenitud, con la tranquilidad de haber dedicado un espacio genuino a su armonía personal. Inhale profundo por última vez en esta sesión, sonría con suavidad y prepárese para continuar su día con una renovada sensación de paz y bienestar.",
"Iniciamos un nuevo espacio dedicado por completo a su bienestar cotidiano y a la paulatina relajación de todo su sistema físico. Adopte una postura que le resulte sumamente agradable y placentera. Lleve su mente hacia las palmas de las manos, imaginando que una agradable sensación de calor las recorre suavemente. Si descansa en cama, permita que el colchón soporte enteramente su peso sin que usted deba realizar esfuerzo alguno. Realice una inspiración lenta, sintiendo cómo el aire expande suavemente el área del abdomen, y al expirar, suelte cualquier pensamiento o preocupación del momento. Esta práctica está diseñada para propiciar un remanso de paz en medio de su jornada, ayudándole a recuperar la energía vital mediante la quietud y la respiración consciente. Permita que la tranquilidad le envuelva por completo, disfrutando de cada instante en este refugio de confort y armonía personal.",
"Le damos la bienvenida a esta sesión orientada al equilibrio y la distensión integral. Ajuste su posición corporal para garantizar que su cuello, espalda y extremidades se encuentren plenamente respaldados. Concentre su atención en el simple acto de respirar: perciba la temperatura del aire al entrar y la calidez al salir de su cuerpo. Si nota alguna pequeña tensión en el rostro o en la mandíbula, relájela intencionalmente permitiendo que los labios se entreabran con total naturalidad. Cada inhalación le aporta serenidad y cada exhalación afianza una profunda sensación de estabilidad en su entorno. Disfrute de este valioso tiempo de cuidado y descanso.",
"Comenzamos una pausa restaurativa centrada en el alivio y la comodidad física. Relaje los brazos a los lados de su cuerpo o sobre su regazo de la manera más cómoda posible. Visualice una suave onda de bienestar que desciende lentamente desde la coronilla hasta la punta de los pies, disipando cualquier rigidez a su paso. Acompañe este recorrido mental con respiraciones rítmicas, profundas y sumamente calmadas, evitando cualquier prisa o exigencia. Este espacio seguro es suyo para recargar energías, encontrar paz mental y disfrutar de un confort duradero.",
"Saludamos este instante de pausa y armonía enfocado en su bienestar personal. Conéctese con la firmeza del suelo o de la cama que sostiene su cuerpo en este momento. Permita que la respiración se vuelva cada vez más lenta y profunda, sirviendo como un ancla segura para mantener la mente tranquila y despejada. Si lo prefiere, mantenga los ojos cerrados mientras su atención descansa apaciblemente en el flujo constante del aire. Disfrute de la estabilidad y el sosiego que esta práctica le otorga, consolidando un estado óptimo de relajación y descanso.",
"Nos adentramos en una sesión pensada para brindarle un respiro profundo y una total distensión corporal. Colóquese en la postura que le aporte mayor desahogo y confort. Dirija su mirada interior hacia la zona de la espalda y los hombros, permitiendo que el peso de los mismos se deslice hacia la superficie de apoyo. Respire con absoluta calma, llenando su interior de esperanza, bienestar y una agradable sensación de liviandad. Este es su momento para habitar el presente con total tranquilidad y seguridad.",
"Bienvenido a este momento de armonización y cuidado de su estilo de vida. Tome una posición que le permita relajar por completo la columna y la zona lumbar. Inhale aire fresco con alegría, sosténgalo unos segundos con suavidad, y expúlselo lentamente dejando ir cualquier rigidez del entorno. Permita que la quietud y el silencio fortalezcan su paz interior, disfrutando plenamente de cada minuto de este descanso enriquecedor.",
"Iniciamos una práctica destinada a cultivar el confort, el equilibrio y la paz en su día a día. Sienta el soporte de la almohada o el respaldar adaptándose a su forma. Realice respiraciones profundas y pausadas, centrando toda su atención en el bienestar que surge al soltar las tensiones cotidianas. Disfrute de este espacio exclusivo de tranquilidad, diseñado para restaurar su energía vital con absoluta naturalidad y seguridad.",
"Comenzamos un espacio de descanso y relajación profunda para acompañar su rutina de bienestar. Adopte una postura cómoda, libre de presiones y exigencias. Sienta el flujo rítmico de su respiración y cómo cada ciclo le otorga una mayor sensación de ligereza y estabilidad interior. Permanezca en este refugio de paz, disfrutando del silencio constructivo y de una total comodidad física.",
"Le saludamos en esta sesión de pausa y armonía diseñada para su confort diario. Ubíquese en el sitio que le ofrezca mayor solidez y bienestar. Conecte con su respiración natural, permitiendo que el aire limpie y relaje cada rincón de su cuerpo de manera apacible y constante. Disfrute de este momento de tregua, estabilidad y cuidado personal sin prisas.",
"Finalizamos nuestro repertorio de bienestar con una sesión orientada al equilibrio absoluto y la paz interior. Acomódese con la certeza de que este tiempo es suyo. Respire hondo, relaje los músculos del rostro y entregue su peso corporal a la superficie con absoluta confianza y serenidad. Disfrute de esta profunda sensación de plenitud y prepárese para continuar su jornada con total armonía."
]


FALLBACK_SESSIONS_PT=[
"Bem-vindo ao seu espaço pessoal de bem-estar e harmonia diária. Reserve um instante para se acomodar com absoluto conforto, sentado tranquilamente em sua poltrona favorita ou descansando de forma tranquila em sua cama. Vamos começar este momento de pausa concentrando toda a atenção no ritmo natural da respiração. Sinta o ar entrando suavemente pelo nariz e saindo devagar. Permita que os ombros desçam naturalmente, deixando o peso do dia repousar sobre a superfície que sustenta você. Se tiver mobilidade nas mãos e nos dedos, mova-os muito lentamente. Se preferir permanecer quieto, simplesmente perceba o conforto da sua posição. Inspire devagar, conte mentalmente até quatro e expire suavemente. Permita-se desligar das distrações externas e permanecer neste momento de tranquilidade. Sua posição deve ser confortável, sem forçar absolutamente nada. Continue respirando com calma, percebendo como cada expiração traz uma agradável sensação de descanso e bem-estar.",
"Começamos este momento especial dedicado inteiramente ao seu descanso, equilíbrio e conforto cotidiano. Coloque-se na posição que hoje ofereça maior segurança e bem-estar. Direcione sua atenção para o pescoço e a cabeça. Se for confortável, faça um movimento muito pequeno e delicado de um lado para o outro, ou simplesmente imagine esse movimento em sua mente. Relaxe a mandíbula e suavize a expressão do rosto. Agora acompanhe conscientemente o ritmo da respiração: inspire devagar, mantenha o ar por um instante sem esforço e expire lentamente. Se estiver deitado, perceba o apoio das costas e da cabeça sobre a cama e deixe os braços repousarem confortavelmente. Continue com uma respiração tranquila, permitindo que o tempo passe sem pressa.",
"Saudações nesta nova sessão de cuidado pessoal e bem-estar. Encontre uma posição confortável, com apoio firme e seguro. Hoje vamos prestar atenção à abertura do peito e ao movimento natural da respiração. Se tiver mobilidade nos braços, mova-os suavemente para uma posição mais confortável. Se não tiver, simplesmente perceba o movimento natural do corpo enquanto respira. Observe o ponto onde suas costas encontram o apoio e permita que o corpo se acomode. Cada expiração é uma oportunidade para deixar as preocupações do dia um pouco mais distantes. Mantenha a mente neste momento presente e respire lentamente, permitindo que uma sensação de calma se espalhe pelo corpo.",
"Seja muito bem-vindo à sua pausa de hoje. Não importa se você está ativo, sentado confortavelmente ou descansando na cama: a prioridade é o seu conforto. Perceba os principais pontos de apoio do corpo, como costas, pernas ou braços. Respire de forma longa e tranquila, sem qualquer exigência. Se for confortável, mova muito suavemente os pulsos ou os dedos dos pés. Se preferir permanecer quieto, imagine o movimento e acompanhe tudo com a respiração. Permita-se permanecer nesta atmosfera de tranquilidade, onde o único objetivo é o seu bem-estar. Continue respirando suavemente e deixe os minutos passarem com paz e segurança.",
"Começamos este momento de conexão profunda com seu bem-estar pessoal. Acomode-se livremente e feche os olhos se desejar. Hoje vamos liberar suavemente as tensões da parte superior do corpo. Relaxe o rosto, deixe os dentes ligeiramente separados, afaste os ombros das orelhas e respire profundamente. Se alguma região apresentar limitação de movimento, não force. Apenas observe essa região com tranquilidade e continue respirando. Imagine uma sensação agradável percorrendo o corpo da cabeça aos pés. Este espaço foi criado para oferecer estabilidade, conforto e serenidade. Continue nesse ritmo tranquilo, percebendo cada inspiração e cada expiração.",
"Bem-vindo à sua rotina de relaxamento e movimento adaptado para o bem-estar geral. Respire de maneira natural e tranquila, permitindo que o abdômen se mova livremente. Faça uma pequena caminhada mental por todo o corpo, reconhecendo cada parte com respeito e atenção. Se tiver mobilidade nas mãos, faça pequenos círculos muito lentos. Se estiver em repouso, imagine esse movimento acontecendo suavemente. Mantenha uma respiração calma e constante. Pequenos momentos de pausa podem trazer mais tranquilidade ao seu dia. Permaneça receptivo à sensação de descanso e deixe o corpo encontrar seu próprio ritmo sem pressa.",
"É um prazer acompanhar você neste espaço de bem-estar criado para seu conforto. Ajuste sua posição até encontrar um ponto agradável de repouso. Direcione a atenção para o centro do corpo e perceba cada inspiração e cada expiração. Mantenha braços e pernas na posição que hoje ofereça maior conforto. Este tempo pertence a você. Sinta o apoio firme que sustenta seu corpo e permita que seu peso descanse sobre a superfície. Continue respirando lentamente enquanto permanecemos neste momento de serenidade, harmonia e respeito pelo seu conforto.",
"Começamos uma nova prática voltada para sua paz interior, estabilidade e conforto. Adote uma posição com bom apoio e sensação de segurança. Relaxe aos poucos os dedos das mãos, os braços e o corpo por meio de uma respiração lenta e tranquila. Se alguma parte do corpo não tiver movimento, concentre-se na respiração e imagine o movimento de maneira confortável. Permita-se afastar temporariamente as distrações externas. Cada ciclo de respiração pode trazer uma sensação de renovação enquanto você permanece sentado ou deitado. Aproveite esta sensação de estabilidade e paz.",
"Bem-vindo à sua sessão de revitalização, descanso e equilíbrio. Encontre a posição mais confortável disponível neste momento. Direcione sua atenção para os ombros e para a parte superior das costas, imaginando uma brisa leve e agradável dissolvendo qualquer sensação de rigidez. Inspire profundamente sem pressa e solte o ar lentamente pelos lábios. Sinta o corpo relaxar e entregar seu peso ao apoio. Mantenha tudo confortável e sem esforço. Este é um momento valioso de pausa diante das exigências do dia. Continue respirando dessa maneira, permitindo que a tranquilidade acompanhe sua mente e seu corpo.",
"Encerramos este ciclo de recomendações de bem-estar com uma sessão dedicada à serenidade e ao conforto. Acomode-se sabendo que este tempo pertence a você. Una a respiração a pequenos movimentos confortáveis ou simplesmente imagine uma sensação de leveza. Sinta o apoio que sustenta seu corpo, relaxe o rosto e deixe o ar entrar e sair naturalmente. Aproveite a estabilidade e a paz deste momento. Permaneça alguns instantes desfrutando dessa sensação de tranquilidade. Faça uma última inspiração profunda, sorria suavemente e prepare-se para continuar seu dia com uma sensação renovada de paz.",
"Iniciamos um novo espaço dedicado ao seu bem-estar cotidiano e à relaxação tranquila do corpo. Adote uma posição agradável. Direcione sua atenção para as palmas das mãos e imagine uma sensação agradável de calor passando por elas. Se estiver na cama, permita que o colchão sustente completamente seu peso. Inspire lentamente, percebendo o movimento suave do abdômen, e ao expirar deixe qualquer preocupação ficar um pouco mais distante. Esta prática oferece um espaço de paz no meio do dia. Permita que a tranquilidade envolva você e aproveite cada instante neste ambiente de conforto e harmonia.",
"Seja bem-vindo a esta sessão voltada ao equilíbrio e ao relaxamento. Ajuste sua posição para que pescoço, costas e braços ou pernas estejam confortavelmente apoiados. Concentre sua atenção no simples ato de respirar. Perceba a temperatura do ar ao entrar e a sensação ao sair. Se notar alguma tensão no rosto ou na mandíbula, relaxe suavemente. Cada inspiração traz serenidade e cada expiração ajuda a criar uma sensação de estabilidade. Aproveite este tempo de cuidado e descanso.",
"Começamos uma pausa restauradora centrada no conforto. Relaxe os braços ao lado do corpo ou sobre o colo da maneira mais agradável possível. Imagine uma onda suave de bem-estar descendo lentamente pelo corpo, levando consigo qualquer sensação de rigidez. Acompanhe essa imagem com respirações ritmadas, profundas e tranquilas. Evite qualquer pressa. Este espaço é seu para recuperar energia, encontrar tranquilidade e desfrutar de conforto.",
"Saudamos este instante de pausa e harmonia dedicado ao seu bem-estar. Perceba a firmeza do chão, da cadeira ou da cama que sustenta seu corpo. Deixe a respiração ficar cada vez mais lenta e tranquila, servindo como uma âncora para manter a mente serena. Se desejar, mantenha os olhos fechados enquanto sua atenção acompanha o fluxo constante do ar. Aproveite a estabilidade e o sossego deste momento.",
"Entramos em uma sessão pensada para oferecer uma respiração profunda e uma sensação de relaxamento. Coloque-se na posição que ofereça maior conforto. Direcione sua atenção para as costas e os ombros e permita que o peso do corpo seja recebido pela superfície de apoio. Respire com calma, preenchendo o momento com esperança, tranquilidade e leveza. Este é o seu momento para permanecer no presente com segurança e serenidade.",
"Bem-vindo a este momento de harmonia e cuidado com seu estilo de vida. Encontre uma posição que permita relaxar confortavelmente. Inspire o ar fresco com tranquilidade, permaneça por um instante sem esforço e solte o ar lentamente, deixando qualquer rigidez ficar para trás. Permita que a quietude fortaleça sua paz interior. Aproveite plenamente cada minuto deste descanso.",
"Iniciamos uma prática destinada a cultivar conforto, equilíbrio e paz no seu dia. Sinta o apoio do travesseiro, da cama ou do encosto acompanhando seu corpo. Respire profundamente e de forma tranquila, concentrando toda a atenção na sensação agradável que surge quando as tensões diminuem. Aproveite este espaço exclusivo de tranquilidade e permita que sua energia seja renovada naturalmente.",
"Começamos um espaço de descanso e relaxamento profundo para acompanhar sua rotina de bem-estar. Adote uma posição confortável, livre de pressão e exigências. Perceba o ritmo da respiração e como cada ciclo pode trazer uma sensação maior de leveza e estabilidade interior. Permaneça neste espaço de paz, aproveitando o silêncio e o conforto físico.",
"Saudamos você nesta sessão de pausa e harmonia criada para seu conforto diário. Encontre o local que ofereça maior apoio e bem-estar. Conecte-se com sua respiração natural, permitindo que cada entrada e saída de ar acompanhe seu momento de tranquilidade. Aproveite esta pausa, este equilíbrio e este cuidado pessoal sem pressa.",
"Finalizamos nosso repertório de bem-estar com uma sessão dedicada ao equilíbrio e à paz interior. Acomode-se com a certeza de que este tempo pertence a você. Respire profundamente, relaxe os músculos do rosto e entregue o peso do corpo à superfície que o sustenta. Aproveite esta sensação de tranquilidade e prepare-se para continuar seu dia com harmonia."
]


@app.get("/",response_class=FileResponse)
async def serve_frontend():
    return FileResponse("index.html",media_type="text/html")


@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request:Request):
    body=await request.json()
    username=body.get("username","").strip()
    password=body.get("password","").strip()
    device_id=body.get("device_id","").strip()
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
        if not device_id:
            raise HTTPException(status_code=400,detail="Device ID required.")
        if not stripe.api_key:
            raise HTTPException(status_code=500,detail="STRIPE_SECRET_KEY is missing in Render.")
        if not STRIPE_PRICE_ID:
            raise HTTPException(status_code=500,detail="STRIPE_PRICE_ID is missing in Render.")
        checkout_session=stripe.checkout.Session.create(
            line_items=[{"price":STRIPE_PRICE_ID,"quantity":1}],
            mode="subscription",
            success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}&device_id={device_id}",
            cancel_url=f"{BASE_URL}/cancel",
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
        if status in ("active","trialing"):
            conn=get_db()
            conn.execute(
                "UPDATE authorized_devices SET status='active',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",
                (subscription_id,)
            )
            conn.commit()
            conn.close()
        elif status in ("canceled","unpaid","incomplete_expired"):
            deactivate_device_by_subscription(subscription_id)

    return {"status":"success"}


@app.get("/api/v1/access-status")
async def access_status(device_id:str=""):
    return {
        "authorized":check_device_authorization(device_id.strip())
    }


@app.get("/success",response_class=HTMLResponse)
async def payment_success(session_id:str=None,device_id:str=None):
    verified=False
    if session_id and stripe.api_key:
        try:
            session=stripe.checkout.Session.retrieve(session_id)
            if session.get("payment_status") in ("paid","no_payment_required"):
                verified=True
        except Exception:
            verified=False

    if verified:
        return f"""<!doctype html><html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;">
<h1 style="color:#4ade80;">Payment Received</h1>
<p>Stripe received your payment.</p>
<p>Returning to AL CIELO and waiting for subscription activation.</p>
<script>
setTimeout(function(){{
window.location.replace("{BASE_URL}/?session_id="+encodeURIComponent("{session_id or ""}")+"&device_id="+encodeURIComponent("{device_id or ""}"));
}},1200);
</script>
<a href="/" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return to AL CIELO</a>
</body></html>"""

    return f"""<!doctype html><html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;">
<h1 style="color:#f87171;">Payment Not Confirmed</h1>
<p>We could not verify the payment with Stripe.</p>
<a href="{BASE_URL}" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return to AL CIELO</a>
</body></html>"""


@app.get("/cancel",response_class=HTMLResponse)
async def payment_cancel():
    return f"""<!doctype html><html><body style="background:#0f172a;color:white;text-align:center;padding-top:60px;font-family:sans-serif;">
<h1 style="color:#f87171;">Payment Canceled</h1>
<p>No subscription was activated.</p>
<a href="{BASE_URL}" style="display:inline-block;margin-top:20px;padding:12px 24px;background:#0284c7;color:white;text-decoration:none;border-radius:8px;font-weight:bold;">Return Home</a>
</body></html>"""


@app.post("/api/v1/generate-session")
async def generate_session(request:Request):
    try:
        body=await request.json()
        device_id=str(body.get("device_id","")).strip()
        language=body.get("language","es")
        is_hook=bool(body.get("is_hook",False))

        if language not in ("es","en","pt"):
            language="es"

        if not device_id:
            raise HTTPException(status_code=400,detail="Device id required.")

        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(status_code=403,detail="Subscription or login required for full session.")

        lang_names={
            "es":"Spanish",
            "en":"English",
            "pt":"Portuguese"
        }
        selected_lang_name=lang_names[language]

        unique_prompt_modifier=random.choice([
            "Focus heavily on shoulder relaxation, upper body comfort, and peaceful pacing.",
            "Focus heavily on hand, finger, and wrist gentle micro-movements combined with deep serenity.",
            "Focus heavily on breathing rhythm, chest expansion, and comfortable posture.",
            "Focus heavily on deep mental relaxation, emotional stability, and physical resting support.",
            "Focus heavily on gentle neck comfort, facial tension release, and total body grounding."
        ])

        if is_hook:
            prompt=f"""
Generate a strict 30-SECOND FREE PREVIEW in [{selected_lang_name}].
Keep it extremely brief, maximum 50 words.
Provide a warm greeting and one single gentle breathing action.
No medical terms, no codes, no IDs.
Output ONLY plain conversational text in {selected_lang_name}.
No title.
"""
            max_tokens=150
        else:
            prompt=f"""
{unique_prompt_modifier}

Generate a completely unique, extensive, deep, continuous and professional 10-MINUTE GUIDED WELLNESS AND LIFESTYLE SESSION strictly in [{selected_lang_name}]
for adults aged 50 and over, inclusive of active, seated, resting, or poststrated individuals, including people with limited mobility or missing limbs.

Act strictly as a live human personal wellness trainer and lifestyle companion guiding the user step by step in real time.

DO NOT use the word 'fase' or 'phase'.
DO NOT use medical or clinical terminology.
DO NOT include random numbers, IDs or technical tags.
Vary the exercise sequence, phrasing and focus so it feels fresh and unique.

Write a rich and detailed coaching routine with separate natural paragraphs.
Use gentle movements, comfortable posture adjustments, sensory awareness, breathing and calm spoken pacing.
Provide enough descriptive pauses and actionable wellness guidance to comfortably fill approximately 10 minutes.

Output ONLY plain conversational text in {selected_lang_name}.
Do not include headings or titles.
"""
            max_tokens=3500

        response_text=""

        if gemini_client:
            try:
                response_task=asyncio.to_thread(
                    gemini_client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_WELLNESS_PROMPT,
                        temperature=0.98,
                        max_output_tokens=max_tokens
                    )
                )
                gemini_response=await asyncio.wait_for(response_task,timeout=20.0)
                response_text=gemini_response.text or ""
            except Exception:
                response_text=""

        if not response_text and openai_client:
            try:
                openai_task=asyncio.to_thread(
                    openai_client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=[
                        {"role":"system","content":SYSTEM_WELLNESS_PROMPT},
                        {"role":"user","content":prompt}
                    ],
                    temperature=0.98,
                    max_tokens=max_tokens
                )
                openai_response=await asyncio.wait_for(openai_task,timeout=20.0)
                response_text=openai_response.choices[0].message.content or ""
            except Exception:
                response_text=""

        if not response_text or len(response_text)<400:
            if is_hook:
                hooks={
                    "es":"Bienvenido a AL CIELO. Adopte una postura cómoda, inhale lentamente por la nariz y deje que sus hombros se relajen mientras exhala.",
                    "en":"Welcome to AL CIELO. Find a comfortable position, breathe in slowly through your nose, and let your shoulders relax as you breathe out.",
                    "pt":"Bem-vindo ao AL CIELO. Encontre uma posição confortável, inspire lentamente pelo nariz e deixe os ombros relaxarem ao expirar."
                }
                response_text=hooks[language]
            else:
                banks={
                    "es":FALLBACK_SESSIONS_ES,
                    "pt":FALLBACK_SESSIONS_PT,
                    "en":FALLBACK_SESSIONS_ES
                }
                bank=banks[language]
                index=next_fallback_index(device_id,language,len(bank))
                response_text=bank[index]

        return {
            "status":"success",
            "session_content":response_text
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500,detail=str(e))
