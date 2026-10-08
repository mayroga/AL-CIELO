import os,sqlite3,random,asyncio,re
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

try: gemini_client=genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception: gemini_client=None
openai_api_key=os.getenv("OPENAI_API_KEY")
openai_client=openai.OpenAI(api_key=openai_api_key) if openai_api_key else None

def get_db():
    conn=sqlite3.connect(DB_FILE);conn.row_factory=sqlite3.Row;return conn

def init_db():
    conn=get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS authorized_devices(device_id TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'active',stripe_customer_id TEXT,stripe_subscription_id TEXT,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fallback_rotation(device_id TEXT NOT NULL,language TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(device_id,language))""")
    conn.commit();conn.close()
init_db()

def authorize_device(device_id,customer_id=None,subscription_id=None):
    if not device_id:return
    conn=get_db()
    conn.execute("""INSERT INTO authorized_devices(device_id,status,stripe_customer_id,stripe_subscription_id,updated_at) VALUES(?,'active',?,?,CURRENT_TIMESTAMP) ON CONFLICT(device_id) DO UPDATE SET status='active',stripe_customer_id=excluded.stripe_customer_id,stripe_subscription_id=excluded.stripe_subscription_id,updated_at=CURRENT_TIMESTAMP""",(device_id,customer_id,subscription_id))
    conn.commit();conn.close()

def check_device_authorization(device_id):
    if not device_id:return False
    conn=get_db();row=conn.execute("SELECT status FROM authorized_devices WHERE device_id=?",(device_id,)).fetchone();conn.close()
    return bool(row and row["status"]=="active")

def deactivate_device_by_subscription(subscription_id):
    if not subscription_id:return
    conn=get_db();conn.execute("UPDATE authorized_devices SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",(subscription_id,));conn.commit();conn.close()

def next_fallback_index(device_id,language,total):
    if total<=0:return 0
    conn=get_db();rotation_language="__all__"
    row=conn.execute("SELECT position FROM fallback_rotation WHERE device_id=? AND language=?",(device_id,rotation_language)).fetchone()
    if row is None:
        position=0
        conn.execute("""INSERT INTO fallback_rotation(device_id,language,position,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)""",(device_id,rotation_language,1 if total>1 else 0))
    else:
        position=int(row["position"])%total;new_position=(position+1)%total
        conn.execute("""UPDATE fallback_rotation SET position=?,updated_at=CURRENT_TIMESTAMP WHERE device_id=? AND language=?""",(new_position,device_id,rotation_language))
    conn.commit();conn.close();return position

SYSTEM_WELLNESS_PROMPT="""You are the exclusive, professional human-like wellness coach and lifestyle companion for the platform "AL CIELO", designed for adults aged 50 and over, encompassing active individuals, seated, resting, or poststrated in bed, including those with limited mobility or missing limbs.
Your tone must be warm, direct, calm, compassionate, and conversational.

STRICT LEGAL & OPERATIONAL RULES:
1. NEVER mention words like "phase", "fase", "auditoría", "IA", or "ChatGPT". Be purely action-oriented and professional.
2. NEVER use medical terminology, clinical terms, diagnoses, or anything implying medical treatment or authority. This is strictly a lifestyle, comfort, relaxation, and physical wellbeing guidance service.
3. NEVER repeat the exact same session twice. Always introduce fresh phrasing, varied exercises, and unique restorative focuses while maintaining absolute safety.
4. NEVER include internal ID numbers, random codes, or technical tags in the text output.
5. IF THIS IS A FREE 30-SECOND PREVIEW:
   - Provide a quick, light greeting and a single simple breathing action.
6. IF THIS IS THE FULL SESSION:
   - Act as a live personal wellness trainer.
   - Use many short, separate spoken instructions instead of long paragraphs.
   - Each instruction must contain preferably one action or one simple idea.
   - After one action, leave a natural pause before the next action.
   - Never combine several exercises or commands into one long sentence.
   - Use blank lines between instruction units.
   - Include inclusive instructions for people with limited mobility or missing limbs.
   - If a movement is not possible, offer a comfortable mental visualization or use only available movement.
7. The COMPLETE response must be ONLY in the selected language.
8. NEVER mix Spanish, English, Portuguese, or any other language.
9. Do not place headings, titles, labels, numbers, codes, or technical markers inside the spoken session.
10. Preserve clear paragraph breaks. Each paragraph must be short enough to be spoken as one direct instruction or one brief piece of guidance.
"""

FALLBACK_SESSIONS_ES=[
"""Bienvenido a su espacio personal de bienestar y armonía diaria.

Acomódese con absoluta comodidad, ya sea sentado o descansando en su cama.

Sienta el apoyo de la superficie que sostiene su cuerpo.

Inhale lentamente por la nariz.

Exhale suavemente.

Deje que sus hombros bajen de manera natural.

Permita que su rostro se relaje.

Si puede mover las manos y los dedos, hágalo muy lentamente.

Si prefiere permanecer quieto, simplemente imagine ese movimiento.

Continúe respirando con calma.

Permítase permanecer unos instantes en este momento de tranquilidad.""",
"""Comenzamos este momento especial dedicado a su descanso, equilibrio y comodidad cotidiana.

Adopte la posición que le resulte más segura y agradable.

Dirija suavemente su atención hacia el cuello.

Si puede hacerlo cómodamente, gire muy poco la cabeza hacia un lado.

Regrese lentamente al centro.

Ahora mire suavemente hacia el otro lado.

Si no desea mover la cabeza, imagine el movimiento.

Relaje la mandíbula.

Suavice la expresión de su rostro.

Inhale despacio.

Exhale lentamente.

Permanezca tranquilo durante unos instantes.""",
"""Le damos la bienvenida a esta nueva sesión de bienestar.

Encuentre una posición que le proporcione buen apoyo.

Observe cómo su espalda descansa sobre la silla o la cama.

Inhale lentamente.

Sienta cómo el pecho se mueve de manera natural.

Exhale sin prisa.

Si tiene movilidad en los brazos, muévalos suavemente hacia una posición cómoda.

Si no puede hacerlo, simplemente imagine ese movimiento.

Deje que los hombros descansen.

Mantenga su atención en este momento.

Respire lentamente y continúe con tranquilidad.""",
"""Bienvenido a su pausa de hoy.

No importa si está activo, sentado o descansando en la cama.

Lo primero es encontrar comodidad.

Sienta los puntos donde su cuerpo recibe apoyo.

Observe sus piernas.

Observe sus brazos.

Respire lentamente.

Si le resulta agradable, mueva suavemente los dedos de las manos.

También puede mover ligeramente los pies si puede hacerlo con comodidad.

Si prefiere permanecer quieto, imagine esos pequeños movimientos.

No fuerce ninguna parte de su cuerpo.

Continúe respirando con serenidad.""",
"""Comenzamos este momento dedicado a su bienestar personal.

Acomódese libremente.

Cierre los ojos si desea hacerlo.

Relaje el rostro.

Separe ligeramente los dientes.

Deje caer los hombros.

Inhale lentamente.

Exhale con suavidad.

Si alguna parte de su cuerpo tiene poco movimiento, no la fuerce.

Simplemente perciba esa zona.

Continúe respirando tranquilamente.

Permita que este momento sea solamente suyo.""",
"""Bienvenido a su rutina de relajación y movimiento adaptado.

Respire de manera natural.

Observe cómo se mueve suavemente el abdomen al respirar.

Recorra mentalmente su cuerpo desde la cabeza hasta los pies.

Reconozca cada parte con respeto.

Si tiene movilidad en las manos, haga pequeños movimientos circulares.

Hágalos muy lentamente.

Si está en reposo, imagine esos movimientos.

Mantenga una respiración tranquila.

Permita que su cuerpo encuentre su propio ritmo.

Continúe sin prisa.""",
"""Es un placer acompañarle en este espacio de bienestar.

Ajuste su posición hasta encontrar un punto agradable de descanso.

Sienta el apoyo que recibe su cuerpo.

Inhale lentamente.

Exhale suavemente.

Mantenga los brazos y las piernas en la posición más cómoda para usted.

No necesita hacer ningún movimiento que resulte incómodo.

Permita que el peso de su cuerpo descanse sobre la superficie.

Continúe respirando lentamente.

Permanezca tranquilo unos instantes.""",
"""Comenzamos una nueva práctica dedicada a su paz y comodidad.

Adopte una posición con buen apoyo.

Sienta que está seguro y cómodo.

Relaje lentamente los dedos de las manos si puede moverlos.

Relaje los brazos.

Si alguna parte del cuerpo no tiene movimiento, no intente forzarla.

Concéntrese en su respiración.

Imagine un movimiento suave y cómodo.

Inhale lentamente.

Exhale lentamente.

Permita que la calma permanezca con usted.""",
"""Bienvenido a su sesión de descanso y equilibrio.

Encuentre la posición más cómoda disponible para usted.

Dirija su atención hacia los hombros.

Observe la parte superior de su espalda.

Imagine una brisa suave pasando por esa zona.

Inhale profundamente sin esfuerzo.

Exhale lentamente.

Sienta cómo su cuerpo se entrega al apoyo que lo sostiene.

No apresure ningún movimiento.

Permanezca cómodo.

Continúe respirando con tranquilidad.""",
"""Llegamos a un momento de serenidad y confort.

Acomódese sabiendo que este tiempo le pertenece.

Respire lentamente.

Si puede realizar pequeños movimientos cómodos, hágalos sin prisa.

Si no desea moverse, imagine una sensación de ligereza.

Relaje el rostro.

Sienta el apoyo debajo de su cuerpo.

Inhale una vez más.

Exhale lentamente.

Permanezca unos instantes disfrutando de esta tranquilidad.""",
"""Iniciamos un nuevo espacio dedicado a su bienestar cotidiano.

Adopte una posición agradable.

Dirija su atención hacia las manos.

Si puede moverlas, permita que los dedos se relajen.

Si no puede moverlos, simplemente imagine una agradable sensación de calor.

Si está descansando en cama, permita que la superficie sostenga su peso.

Inhale lentamente.

Exhale y deje que cualquier preocupación quede un poco más lejos.

Permanezca tranquilo.

Disfrute de este momento.""",
"""Bienvenido a esta sesión de equilibrio y relajación.

Ajuste su posición para sentirse cómodo.

Sienta el apoyo de su cuello.

Sienta el apoyo de su espalda.

Permita que sus brazos y piernas descansen.

Concéntrese en el simple acto de respirar.

Perciba el aire al entrar.

Perciba el aire al salir.

Relaje suavemente el rostro.

Suelte la mandíbula.

Continúe respirando con calma.""",
"""Comenzamos una pausa restauradora centrada en su comodidad.

Coloque los brazos de la manera que le resulte más agradable.

Siéntalos descansar sobre su regazo o junto al cuerpo.

Imagine una sensación suave recorriendo lentamente su cuerpo.

Acompañe esa imagen con una respiración tranquila.

Inhale despacio.

Exhale lentamente.

No tenga prisa.

Permita que este espacio sea suyo.

Continúe descansando con serenidad.""",
"""Saludamos este instante de pausa y armonía.

Sienta la superficie que sostiene su cuerpo.

Puede ser una silla, un sillón o una cama.

Permita que la respiración se vuelva lenta.

Inhale con tranquilidad.

Exhale suavemente.

Mantenga su atención en el aire que entra y sale.

Si desea cerrar los ojos, puede hacerlo.

Permanezca cómodo.

Disfrute de unos instantes de sosiego.""",
"""Entramos en una sesión pensada para ofrecerle descanso y tranquilidad.

Colóquese en la posición que le aporte mayor comodidad.

Dirija su atención hacia la espalda.

Observe sus hombros.

Permita que el peso de su cuerpo descanse sobre la superficie.

Respire con calma.

Inhale lentamente.

Exhale suavemente.

Imagine que cada respiración le permite soltar un poco de tensión cotidiana.

Permanezca en el presente.

Continúe con serenidad.""",
"""Bienvenido a este momento de armonía y cuidado de su estilo de vida.

Encuentre una posición cómoda.

Permita que su espalda descanse.

Inhale aire lentamente.

Mantenga el aire un instante sin esfuerzo.

Exhale despacio.

Deje que cualquier rigidez se reduzca de manera natural.

No necesita apresurarse.

Disfrute del silencio.

Continúe respirando tranquilamente.""",
"""Iniciamos una práctica destinada al confort y la paz de su día.

Sienta el apoyo de la almohada, la cama o el respaldo.

Acomode su cuerpo de la manera que le resulte más agradable.

Respire profundamente pero sin esfuerzo.

Observe cómo se siente al soltar las tensiones del día.

Relaje los hombros.

Relaje el rostro.

Permanezca cómodo.

Deje que la tranquilidad acompañe cada respiración.""",
"""Comenzamos un espacio de descanso y relajación.

Adopte una postura cómoda y libre de presión.

Sienta el ritmo natural de su respiración.

Inhale lentamente.

Exhale lentamente.

Observe cómo cada respiración puede traer una sensación de ligereza.

No necesita hacer nada más.

Permanezca en esta posición.

Disfrute del silencio y del apoyo que recibe su cuerpo.

Continúe respirando con tranquilidad.""",
"""Finalizamos este repertorio de bienestar con un momento dedicado al equilibrio y la paz.

Acomódese con la certeza de que este tiempo es suyo.

Sienta la superficie que sostiene su cuerpo.

Relaje el rostro.

Respire profundamente sin esfuerzo.

Exhale lentamente.

Deje descansar sus hombros.

Permanezca unos instantes en calma.

Cuando esté preparado, continúe su jornada lentamente y con tranquilidad."""
]

FALLBACK_SESSIONS_PT=[
"""Bem-vindo ao seu espaço pessoal de bem-estar e harmonia diária.

Reserve um instante para se acomodar com absoluto conforto.

Sinta o apoio da superfície que sustenta seu corpo.

Inspire lentamente pelo nariz.

Expire suavemente.

Permita que os ombros desçam naturalmente.

Relaxe o rosto.

Se tiver mobilidade nas mãos e nos dedos, mova-os muito devagar.

Se preferir permanecer quieto, simplesmente imagine esse movimento.

Continue respirando com calma.

Permita-se permanecer alguns instantes neste momento de tranquilidade.""",
"""Começamos este momento especial dedicado ao seu descanso, equilíbrio e conforto cotidiano.

Coloque-se na posição que ofereça maior segurança e conforto.

Direcione suavemente sua atenção para o pescoço.

Se for confortável, gire muito pouco a cabeça para um lado.

Volte lentamente ao centro.

Agora olhe suavemente para o outro lado.

Se não quiser movimentar a cabeça, apenas imagine o movimento.

Relaxe a mandíbula.

Suavize a expressão do rosto.

Inspire devagar.

Expire lentamente.

Permaneça tranquilo por alguns instantes.""",
"""Seja bem-vindo a esta nova sessão de bem-estar.

Encontre uma posição que ofereça bom apoio.

Observe suas costas descansando na cadeira ou na cama.

Inspire lentamente.

Perceba o peito se movimentando naturalmente.

Expire sem pressa.

Se tiver mobilidade nos braços, mova-os suavemente para uma posição confortável.

Se não puder fazer isso, simplesmente imagine o movimento.

Deixe os ombros descansarem.

Mantenha sua atenção neste momento.

Respire lentamente e continue com tranquilidade.""",
"""Bem-vindo à sua pausa de hoje.

Não importa se você está ativo, sentado ou descansando na cama.

O primeiro passo é encontrar conforto.

Perceba os pontos onde seu corpo recebe apoio.

Observe suas pernas.

Observe seus braços.

Respire lentamente.

Se for agradável, mova suavemente os dedos das mãos.

Também pode movimentar levemente os pés se isso for confortável.

Se preferir ficar quieto, imagine esses pequenos movimentos.

Não force nenhuma parte do corpo.

Continue respirando com serenidade.""",
"""Começamos este momento dedicado ao seu bem-estar pessoal.

Acomode-se livremente.

Feche os olhos se desejar.

Relaxe o rosto.

Deixe os dentes ligeiramente separados.

Deixe os ombros descansarem.

Inspire lentamente.

Expire suavemente.

Se alguma parte do corpo tiver pouco movimento, não force.

Apenas perceba essa região.

Continue respirando tranquilamente.

Permita que este momento seja somente seu.""",
"""Bem-vindo à sua rotina de relaxamento e movimento adaptado.

Respire naturalmente.

Observe o movimento suave do abdômen enquanto respira.

Percorra mentalmente seu corpo da cabeça aos pés.

Reconheça cada parte com respeito.

Se tiver mobilidade nas mãos, faça pequenos movimentos circulares.

Faça tudo muito lentamente.

Se estiver em repouso, imagine esses movimentos.

Mantenha uma respiração tranquila.

Permita que seu corpo encontre seu próprio ritmo.

Continue sem pressa.""",
"""É um prazer acompanhar você neste espaço de bem-estar.

Ajuste sua posição até encontrar um ponto agradável de descanso.

Sinta o apoio que recebe seu corpo.

Inspire lentamente.

Expire suavemente.

Mantenha braços e pernas na posição mais confortável para você.

Não precisa fazer nenhum movimento que cause desconforto.

Permita que o peso do corpo descanse sobre a superfície.

Continue respirando lentamente.

Permaneça tranquilo por alguns instantes.""",
"""Começamos uma nova prática dedicada à sua paz e conforto.

Adote uma posição com bom apoio.

Sinta que está seguro e confortável.

Relaxe lentamente os dedos das mãos se puder movimentá-los.

Relaxe os braços.

Se alguma parte do corpo não tiver movimento, não tente forçá-la.

Concentre-se na respiração.

Imagine um movimento suave e confortável.

Inspire lentamente.

Expire lentamente.

Permita que a calma permaneça com você.""",
"""Bem-vindo à sua sessão de descanso e equilíbrio.

Encontre a posição mais confortável disponível para você.

Direcione sua atenção para os ombros.

Observe a parte superior das costas.

Imagine uma brisa suave passando por essa região.

Inspire profundamente sem esforço.

Expire lentamente.

Sinta seu corpo descansando sobre o apoio.

Não apresse nenhum movimento.

Permaneça confortável.

Continue respirando com tranquilidade.""",
"""Chegamos a um momento de serenidade e conforto.

Acomode-se sabendo que este tempo pertence a você.

Respire lentamente.

Se puder fazer pequenos movimentos confortáveis, faça-os sem pressa.

Se não quiser se movimentar, imagine uma sensação de leveza.

Relaxe o rosto.

Sinta o apoio sob seu corpo.

Inspire mais uma vez.

Expire lentamente.

Permaneça alguns instantes aproveitando esta tranquilidade.""",
"""Iniciamos um novo espaço dedicado ao seu bem-estar cotidiano.

Adote uma posição agradável.

Direcione sua atenção para as mãos.

Se puder movimentá-las, permita que os dedos relaxem.

Se não puder movimentá-los, apenas imagine uma agradável sensação de calor.

Se estiver descansando na cama, permita que a superfície sustente seu peso.

Inspire lentamente.

Expire e deixe qualquer preocupação ficar um pouco mais distante.

Permaneça tranquilo.

Aproveite este momento.""",
"""Bem-vindo a esta sessão de equilíbrio e relaxamento.

Ajuste sua posição para se sentir confortável.

Sinta o apoio do pescoço.

Sinta o apoio das costas.

Permita que braços e pernas descansem.

Concentre-se no simples ato de respirar.

Perceba o ar entrando.

Perceba o ar saindo.

Relaxe suavemente o rosto.

Solte a mandíbula.

Continue respirando com calma.""",
"""Começamos uma pausa restauradora centrada no seu conforto.

Coloque os braços da maneira mais agradável para você.

Deixe-os descansar sobre o colo ou ao lado do corpo.

Imagine uma sensação suave percorrendo lentamente seu corpo.

Acompanhe essa imagem com uma respiração tranquila.

Inspire devagar.

Expire lentamente.

Não tenha pressa.

Permita que este espaço seja seu.

Continue descansando com serenidade.""",
"""Saudamos este instante de pausa e harmonia.

Sinta a superfície que sustenta seu corpo.

Pode ser uma cadeira, uma poltrona ou uma cama.

Permita que a respiração fique lenta.

Inspire com tranquilidade.

Expire suavemente.

Mantenha sua atenção no ar entrando e saindo.

Se quiser fechar os olhos, pode fazê-lo.

Permaneça confortável.

Aproveite alguns instantes de tranquilidade.""",
"""Entramos em uma sessão pensada para oferecer descanso e tranquilidade.

Coloque-se na posição que ofereça maior conforto.

Direcione sua atenção para as costas.

Observe os ombros.

Permita que o peso do corpo descanse sobre a superfície.

Respire com calma.

Inspire lentamente.

Expire suavemente.

Imagine que cada respiração permite deixar um pouco da tensão cotidiana para trás.

Permaneça no presente.

Continue com serenidade.""",
"""Bem-vindo a este momento de harmonia e cuidado com seu estilo de vida.

Encontre uma posição confortável.

Permita que suas costas descansem.

Inspire lentamente.

Mantenha o ar por um instante sem esforço.

Expire devagar.

Deixe qualquer rigidez diminuir naturalmente.

Não precisa ter pressa.

Aproveite o silêncio.

Continue respirando tranquilamente.""",
"""Iniciamos uma prática destinada ao conforto e à paz do seu dia.

Sinta o apoio do travesseiro, da cama ou do encosto.

Acomode o corpo da maneira mais agradável para você.

Respire profundamente sem esforço.

Observe como é sentir as tensões diminuírem.

Relaxe os ombros.

Relaxe o rosto.

Permaneça confortável.

Deixe a tranquilidade acompanhar cada respiração.""",
"""Começamos um espaço de descanso e relaxamento.

Adote uma posição confortável e livre de pressão.

Sinta o ritmo natural da sua respiração.

Inspire lentamente.

Expire lentamente.

Observe como cada respiração pode trazer uma sensação de leveza.

Você não precisa fazer mais nada.

Permaneça nessa posição.

Aproveite o silêncio e o apoio que recebe seu corpo.

Continue respirando com tranquilidade.""",
"""Finalizamos este repertório de bem-estar com um momento dedicado ao equilíbrio e à paz.

Acomode-se sabendo que este tempo pertence a você.

Sinta a superfície que sustenta seu corpo.

Relaxe o rosto.

Respire profundamente sem esforço.

Expire lentamente.

Deixe os ombros descansarem.

Permaneça alguns instantes em calma.

Quando estiver preparado, continue seu dia lentamente e com tranquilidade."""
]

FALLBACK_SESSIONS_EN=[
"""Welcome to your personal space for daily wellbeing and harmony.

Take a moment to settle into a comfortable position.

Feel the surface supporting your body.

Breathe in slowly through your nose.

Breathe out gently.

Allow your shoulders to drop naturally.

Relax your face.

If you can comfortably move your hands and fingers, move them very slowly.

If you prefer to remain still, simply imagine the movement.

Continue breathing calmly.

Remain here for a few quiet moments.""",
"""We begin this special moment devoted to your rest, balance, and everyday comfort.

Choose the position that feels safest and most comfortable.

Bring your gentle attention to your neck.

If it feels comfortable, turn your head slightly to one side.

Slowly return to the center.

Now gently look toward the other side.

If you do not want to move your head, simply imagine the movement.

Relax your jaw.

Soften your facial expression.

Breathe in slowly.

Breathe out gently.

Remain calm for a few moments.""",
"""Welcome to this new wellbeing session.

Find a position that gives you good support.

Notice your back resting against the chair or the bed.

Breathe in slowly.

Notice the natural movement of your chest.

Breathe out without rushing.

If you have comfortable movement in your arms, move them gently into a comfortable position.

If you cannot do that, simply imagine the movement.

Let your shoulders rest.

Keep your attention on this moment.

Breathe slowly and continue calmly.""",
"""Welcome to your pause for today.

Whether you are active, seated, or resting in bed, comfort comes first.

Notice the places where your body receives support.

Notice your legs.

Notice your arms.

Breathe slowly.

If it feels pleasant, gently move your fingers.

You may also move your feet slightly if that feels comfortable.

If you prefer to remain still, imagine those small movements.

Do not force any part of your body.

Continue breathing calmly.""",
"""We begin this moment devoted to your personal wellbeing.

Settle in freely.

Close your eyes if you wish.

Relax your face.

Let your teeth separate slightly.

Allow your shoulders to rest.

Breathe in slowly.

Breathe out gently.

If any part of your body has limited movement, do not force it.

Simply notice that area.

Continue breathing calmly.

Allow this moment to belong entirely to you.""",
"""Welcome to your adapted relaxation and movement routine.

Breathe naturally.

Notice the gentle movement of your abdomen as you breathe.

Take a quiet mental journey from your head to your feet.

Notice each part with respect.

If your hands can move comfortably, make very small circles.

Move very slowly.

If you are resting, imagine those movements.

Keep your breathing calm.

Allow your body to find its own rhythm.

Continue without rushing.""",
"""It is a pleasure to accompany you in this wellbeing space.

Adjust your position until you find a comfortable place to rest.

Feel the support beneath your body.

Breathe in slowly.

Breathe out gently.

Keep your arms and legs in the position that feels most comfortable.

You do not need to make any movement that feels uncomfortable.

Allow your body weight to rest on the supporting surface.

Continue breathing slowly.

Remain peaceful for a few moments.""",
"""We begin a new practice devoted to your peace and comfort.

Choose a position with good support.

Feel safe and comfortable.

Slowly relax your fingers if you can move them.

Relax your arms.

If any part of your body does not move, do not try to force it.

Focus on your breathing.

Imagine a gentle and comfortable movement.

Breathe in slowly.

Breathe out slowly.

Allow calmness to remain with you.""",
"""Welcome to your session of rest and balance.

Find the most comfortable position available to you.

Bring your attention to your shoulders.

Notice your upper back.

Imagine a soft, pleasant breeze passing through that area.

Breathe in deeply without effort.

Breathe out slowly.

Feel your body resting into the support beneath you.

Do not rush any movement.

Remain comfortable.

Continue breathing peacefully.""",
"""We arrive at a moment of serenity and comfort.

Settle in knowing that this time belongs to you.

Breathe slowly.

If you can make small comfortable movements, make them without rushing.

If you do not want to move, simply imagine a feeling of lightness.

Relax your face.

Feel the support beneath your body.

Take one more slow breath in.

Breathe out gently.

Remain here for a few moments and enjoy the quiet.""",
"""We begin a new space devoted to your everyday wellbeing.

Choose a comfortable position.

Bring your attention to your hands.

If you can move them, allow your fingers to relax.

If you cannot move them, simply imagine a pleasant feeling of warmth.

If you are resting in bed, allow the surface to support your weight.

Breathe in slowly.

As you breathe out, allow any worry to feel a little farther away.

Remain calm.

Enjoy this moment.""",
"""Welcome to this session of balance and relaxation.

Adjust your position until you feel comfortable.

Notice the support beneath your neck.

Notice the support beneath your back.

Allow your arms and legs to rest.

Focus on the simple act of breathing.

Notice the air coming in.

Notice the air going out.

Gently relax your face.

Let your jaw loosen.

Continue breathing calmly.""",
"""We begin a restorative pause centered on your comfort.

Place your arms in the way that feels most pleasant.

Let them rest on your lap or beside your body.

Imagine a gentle feeling moving slowly through your body.

Follow that image with calm breathing.

Breathe in slowly.

Breathe out gently.

There is no need to hurry.

Allow this space to be yours.

Continue resting peacefully.""",
"""We welcome this moment of pause and harmony.

Feel the surface supporting your body.

It may be a chair, an armchair, or a bed.

Allow your breathing to become slower.

Breathe in calmly.

Breathe out gently.

Keep your attention on the air moving in and out.

If you wish to close your eyes, you may do so.

Remain comfortable.

Enjoy a few quiet moments.""",
"""We enter a session created to offer rest and tranquility.

Place yourself in the position that gives you the greatest comfort.

Bring your attention to your back.

Notice your shoulders.

Allow your body weight to rest on the supporting surface.

Breathe calmly.

Breathe in slowly.

Breathe out gently.

Imagine each breath allowing a little of the day's tension to move farther away.

Remain in the present moment.

Continue peacefully.""",
"""Welcome to this moment of harmony and care for your everyday lifestyle.

Find a comfortable position.

Allow your back to rest.

Breathe in slowly.

Hold the breath for a brief moment without effort.

Breathe out gently.

Allow any stiffness to ease naturally.

There is no need to hurry.

Enjoy the quiet.

Continue breathing calmly.""",
"""We begin a practice devoted to comfort and peace during your day.

Feel the support of your pillow, bed, or chair.

Arrange your body in the way that feels most pleasant.

Breathe deeply without forcing the breath.

Notice what it feels like to let everyday tension soften.

Relax your shoulders.

Relax your face.

Remain comfortable.

Let calmness accompany every breath.""",
"""We begin a space for rest and relaxation.

Choose a comfortable position free from pressure.

Notice the natural rhythm of your breathing.

Breathe in slowly.

Breathe out slowly.

Notice how each breath can bring a feeling of lightness.

You do not need to do anything else right now.

Remain in this position.

Enjoy the quiet and the support beneath your body.

Continue breathing peacefully.""",
"""We finish this wellbeing collection with a moment devoted to balance and peace.

Settle in knowing that this time belongs to you.

Feel the surface supporting your body.

Relax your face.

Breathe deeply without forcing the breath.

Breathe out slowly.

Let your shoulders rest.

Remain calm for a few moments.

When you are ready, continue your day slowly and peacefully."""
]

def normalize_session_units(text):
    if not text:return ""
    text=text.replace("\r\n","\n").replace("\r","\n")
    text=re.sub(r"[ \t]+"," ",text)
    paragraphs=[p.strip() for p in re.split(r"\n\s*\n+",text) if p.strip()]
    if len(paragraphs)>1:return "\n\n".join(paragraphs)
    sentences=re.split(r"(?<=[.!?])\s+",text.strip());units=[];current=[]
    for sentence in sentences:
        sentence=sentence.strip()
        if not sentence:continue
        current.append(sentence)
        if len(current)>=1:
            units.append(" ".join(current));current=[]
    if current:units.append(" ".join(current))
    return "\n\n".join(units)

@app.get("/",response_class=FileResponse)
async def serve_frontend():return FileResponse("index.html",media_type="text/html")

@app.post("/api/v1/authorize-courtesy")
async def authorize_courtesy(request:Request):
    body=await request.json();username=body.get("username","").strip();password=body.get("password","").strip();device_id=body.get("device_id","").strip()
    if not ADMIN_USER or not ADMIN_PASS:raise HTTPException(status_code=500,detail="Admin credentials not configured in Render environment variables.")
    if username==ADMIN_USER and password==ADMIN_PASS and device_id:
        authorize_device(device_id);return {"status":"success"}
    raise HTTPException(status_code=401,detail="Invalid credentials.")

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request:Request):
    try:
        body=await request.json();device_id=str(body.get("device_id","")).strip()
        if not device_id:raise HTTPException(status_code=400,detail="Device ID required.")
        if not stripe.api_key:raise HTTPException(status_code=500,detail="STRIPE_SECRET_KEY is missing in Render.")
        if not STRIPE_PRICE_ID:raise HTTPException(status_code=500,detail="STRIPE_PRICE_ID is missing in Render.")
        checkout_session=stripe.checkout.Session.create(line_items=[{"price":STRIPE_PRICE_ID,"quantity":1}],mode="subscription",success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}&device_id={device_id}",cancel_url=f"{BASE_URL}/cancel",metadata={"device_id":device_id})
        return {"status":"success","checkout_url":checkout_session.url}
    except HTTPException:raise
    except stripe.error.StripeError as e:raise HTTPException(status_code=502,detail=f"Stripe error: {str(e)}")
    except Exception as e:raise HTTPException(status_code=500,detail=f"Checkout error: {str(e)}")

@app.post("/webhook/stripe")
async def stripe_webhook(request:Request,stripe_signature:str=Header(default=None)):
    payload=await request.body()
    if not STRIPE_WEBHOOK_SECRET:raise HTTPException(status_code=500,detail="STRIPE_WEBHOOK_SECRET is missing in Render.")
    if not stripe_signature:raise HTTPException(status_code=400,detail="Missing Stripe-Signature header.")
    try:event=stripe.Webhook.construct_event(payload,stripe_signature,STRIPE_WEBHOOK_SECRET)
    except ValueError:raise HTTPException(status_code=400,detail="Invalid webhook payload.")
    except stripe.error.SignatureVerificationError:raise HTTPException(status_code=400,detail="Invalid Stripe webhook signature.")
    except Exception as e:raise HTTPException(status_code=400,detail=f"Webhook error: {str(e)}")
    event_type=event.get("type")
    if event_type=="checkout.session.completed":
        session=event["data"]["object"];metadata=session.get("metadata") or {};device_id=metadata.get("device_id");customer_id=session.get("customer");subscription_id=session.get("subscription");payment_status=session.get("payment_status")
        if device_id and payment_status in ("paid","no_payment_required"):authorize_device(device_id,customer_id,subscription_id)
    elif event_type in ("customer.subscription.deleted","customer.subscription.unpaid"):
        subscription=event["data"]["object"];deactivate_device_by_subscription(subscription.get("id"))
    elif event_type=="customer.subscription.updated":
        subscription=event["data"]["object"];status=subscription.get("status");subscription_id=subscription.get("id")
        if status in ("active","trialing"):
            conn=get_db();conn.execute("UPDATE authorized_devices SET status='active',updated_at=CURRENT_TIMESTAMP WHERE stripe_subscription_id=?",(subscription_id,));conn.commit();conn.close()
        elif status in ("canceled","unpaid","incomplete_expired"):deactivate_device_by_subscription(subscription_id)
    return {"status":"success"}

@app.get("/api/v1/access-status")
async def access_status(device_id:str=""):return {"authorized":check_device_authorization(device_id.strip())}

@app.get("/success",response_class=HTMLResponse)
async def payment_success(session_id:str="",device_id:str=""):
    authorized=False
    if session_id and stripe.api_key:
        try:
            session=stripe.checkout.Session.retrieve(session_id);metadata=session.get("metadata") or {};session_device=metadata.get("device_id") or device_id;payment_status=session.get("payment_status")
            if session_device and payment_status in ("paid","no_payment_required"):authorized=check_device_authorization(session_device)
        except Exception:authorized=False
    if authorized:
        return HTMLResponse(f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AL CIELO</title></head>
<body style="margin:0;background:#0f172a;color:white;font-family:Arial,sans-serif;text-align:center;padding:40px"><h2>Pago recibido</h2><p>Estamos preparando su acceso a AL CIELO.</p><script>setTimeout(function(){{location.href="{BASE_URL}?device_id={device_id}";}},1200);</script></body></html>""")
    return HTMLResponse("""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AL CIELO</title></head>
<body style="margin:0;background:#0f172a;color:white;font-family:Arial,sans-serif;text-align:center;padding:40px"><h2>Pago recibido</h2><p>Estamos verificando su acceso. Espere unos instantes y vuelva a AL CIELO.</p><script>setTimeout(function(){location.href="/";},3000);</script></body></html>""")

@app.get("/cancel",response_class=HTMLResponse)
async def payment_cancel():
    return HTMLResponse(f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AL CIELO</title></head>
<body style="margin:0;background:#0f172a;color:white;font-family:Arial,sans-serif;text-align:center;padding:40px"><h2>Pago cancelado</h2><p>No se realizó ningún cobro.</p><p>Puede regresar a AL CIELO cuando lo desee.</p><a href="{BASE_URL}" style="color:white">Volver a AL CIELO</a></body></html>""")

@app.post("/api/v1/generate-session")
async def generate_session(request:Request):
    try:
        body=await request.json();device_id=str(body.get("device_id","")).strip();language=str(body.get("language","es")).lower().strip();is_hook=bool(body.get("is_hook",False))
        if language not in ("es","en","pt"):language="es"
        if not device_id:raise HTTPException(status_code=400,detail="Device id required.")
        if not is_hook and not check_device_authorization(device_id):raise HTTPException(status_code=403,detail="Subscription or login required for full session.")
        lang_names={"es":"Spanish","en":"English","pt":"Portuguese"};selected_lang_name=lang_names[language]
        unique_prompt_modifier=random.choice(["Focus on shoulder relaxation, upper body comfort, and peaceful pacing.","Focus on hand, finger, and wrist gentle movements combined with calm breathing.","Focus on breathing rhythm, chest comfort, and a relaxed supported posture.","Focus on deep mental relaxation, quiet attention, and comfortable resting.","Focus on gentle neck comfort, facial relaxation, and total body grounding.","Focus on small movements that can be adapted to the person's available mobility.","Focus on calm transitions between breathing, posture, and simple comfortable movement."])
        if is_hook:
            prompt=f"""Generate a strict 30-SECOND FREE PREVIEW in [{selected_lang_name}].

Keep it extremely brief.

Provide a warm greeting and one single gentle breathing action.

Output ONLY plain conversational text in {selected_lang_name}.

The entire response must be ONLY {selected_lang_name}.
Do not mix languages.
Do not include a title.
"""
            max_tokens=150
        else:
            prompt=f"""{unique_prompt_modifier}

Generate a completely unique, extensive guided wellness and lifestyle session in {selected_lang_name}
for adults aged 50 and over, including active, seated, resting, bedridden, limited-mobility, or missing-limb users.

Act as a calm live human wellness companion guiding the person one action at a time.

IMPORTANT STRUCTURE:

Do NOT write long paragraphs containing several actions.

Every individual instruction or exercise must be separated into its own short paragraph.

Prefer one direct action per paragraph.

Examples of the required style:

Adopt a comfortable position.

Breathe in slowly through your nose.

Breathe out gently.

Relax your shoulders.

Remain comfortable for a few moments.

Then continue with the next instruction.

Every instruction must be simple enough for a person aged 50 or older to understand immediately.

Do not combine multiple exercises into one paragraph.

Use natural pauses between instructions.

Vary the sequence, wording, movement, breathing, posture, sensory attention, and resting focus so the session feels fresh.

Every movement must be optional and comfortable.

If a movement is not possible, provide a simple mental visualization or another comfortable option.

DO NOT use the word 'fase' or 'phase'.

DO NOT use medical or clinical terminology.

DO NOT include diagnoses, treatment, medical authority, IDs, codes, technical tags, headings, titles, numbering, or labels.

The complete response must be ONLY in {selected_lang_name}.

NEVER mix Spanish, English, Portuguese, or another language.

Do not translate only the first paragraph while leaving other paragraphs in another language.

Every paragraph must remain in {selected_lang_name}.

Output ONLY the spoken session.
"""
            max_tokens=3500
        response_text=""
        if gemini_client:
            try:
                response_task=asyncio.to_thread(gemini_client.models.generate_content,model="gemini-2.5-flash",contents=prompt,config=types.GenerateContentConfig(system_instruction=SYSTEM_WELLNESS_PROMPT,temperature=0.98,max_output_tokens=max_tokens))
                gemini_response=await asyncio.wait_for(response_task,timeout=20.0);response_text=gemini_response.text or ""
            except Exception:response_text=""
        if not response_text and openai_client:
            try:
                openai_task=asyncio.to_thread(openai_client.chat.completions.create,model="gpt-4o-mini",messages=[{"role":"system","content":SYSTEM_WELLNESS_PROMPT},{"role":"user","content":prompt}],temperature=0.98,max_tokens=max_tokens)
                openai_response=await asyncio.wait_for(openai_task,timeout=20.0);response_text=openai_response.choices[0].message.content or ""
            except Exception:response_text=""
        if is_hook:
            hooks={"es":"Bienvenido a AL CIELO. Adopte una postura cómoda, inhale lentamente por la nariz y deje que sus hombros se relajen mientras exhala.","en":"Welcome to AL CIELO. Find a comfortable position, breathe in slowly through your nose, and let your shoulders relax as you breathe out.","pt":"Bem-vindo ao AL CIELO. Encontre uma posição confortável, inspire lentamente pelo nariz e deixe os ombros relaxarem ao expirar."}
            if not response_text or len(response_text.strip())<40:response_text=hooks[language]
            response_text=normalize_session_units(response_text)
        else:
            if not response_text or len(response_text.strip())<400:
                banks={"es":FALLBACK_SESSIONS_ES,"en":FALLBACK_SESSIONS_EN,"pt":FALLBACK_SESSIONS_PT};bank=banks[language];index=next_fallback_index(device_id,language,len(bank));response_text=bank[index]
            else:response_text=normalize_session_units(response_text)
        return {"status":"success","session_content":response_text}
    except HTTPException:raise
    except Exception as e:raise HTTPException(status_code=500,detail=str(e))
