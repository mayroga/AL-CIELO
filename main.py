# main.py — AL CIELO | May Roga LLC
# v3.0.1
# FastAPI + Stripe Checkout + SQLite + Gemini
# Autorización real: Stripe Webhook -> SQLite -> acceso

from __future__ import annotations

import os
import sqlite3
from datetime import datetime,timezone
from typing import Optional

import stripe
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,JSONResponse
from pydantic import BaseModel
from google import genai


VERSION="3.0.1"
APP_NAME="AL CIELO"
DB_FILE=os.getenv("AL_CIELO_DB","alcielo_licences.db")

# ============================================================
# STRIPE
# ============================================================

STRIPE_SECRET_KEY=os.getenv("STRIPE_SECRET_KEY","").strip()
STRIPE_PRICE_ID=os.getenv("STRIPE_PRICE_ID","").strip()
STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET","").strip()

if STRIPE_SECRET_KEY:
    stripe.api_key=STRIPE_SECRET_KEY

# ============================================================
# ADMIN
# Compatible con ADMIN_USER/ADMIN_PASS y
# ADMIN_USERNAME/ADMIN_PASSWORD
# ============================================================

ADMIN_USER=(
    os.getenv("ADMIN_USER")
    or os.getenv("ADMIN_USERNAME")
    or ""
).strip()

ADMIN_PASS=(
    os.getenv("ADMIN_PASS")
    or os.getenv("ADMIN_PASSWORD")
    or ""
).strip()

# ============================================================
# GEMINI
# ============================================================

GEMINI_API_KEY=os.getenv("GEMINI_API_KEY","").strip()
GEMINI_MODEL=os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
).strip()

gemini_client=None

if GEMINI_API_KEY:
    try:
        gemini_client=genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        gemini_client=None

# ============================================================
# FASTAPI
# ============================================================

app=FastAPI(
    title=APP_NAME,
    version=VERSION
)

# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn=sqlite3.connect(DB_FILE,timeout=30)
    conn.row_factory=sqlite3.Row
    return conn


def init_db():
    conn=get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS authorized_devices(
            device_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'active',
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            access_type TEXT NOT NULL DEFAULT 'subscription',
            updated_at TEXT NOT NULL
        )
    """)

    # Migración defensiva para bases creadas con versiones anteriores.
    columns={
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(authorized_devices)"
        ).fetchall()
    }

    if "stripe_customer_id" not in columns:
        conn.execute("""
            ALTER TABLE authorized_devices
            ADD COLUMN stripe_customer_id TEXT
        """)

    if "stripe_subscription_id" not in columns:
        conn.execute("""
            ALTER TABLE authorized_devices
            ADD COLUMN stripe_subscription_id TEXT
        """)

    if "access_type" not in columns:
        conn.execute("""
            ALTER TABLE authorized_devices
            ADD COLUMN access_type TEXT NOT NULL DEFAULT 'subscription'
        """)

    if "updated_at" not in columns:
        conn.execute("""
            ALTER TABLE authorized_devices
            ADD COLUMN updated_at TEXT
        """)

    conn.commit()
    conn.close()


init_db()

# ============================================================
# UTILIDADES
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clean_device_id(device_id:str)->str:
    device_id=(device_id or "").strip()

    if not device_id:
        raise HTTPException(
            status_code=400,
            detail="device_id is required."
        )

    if len(device_id)>200:
        raise HTTPException(
            status_code=400,
            detail="Invalid device_id."
        )

    return device_id


def authorize_device(
    device_id:str,
    stripe_customer_id:Optional[str]=None,
    stripe_subscription_id:Optional[str]=None,
    access_type:str="subscription"
):
    device_id=clean_device_id(device_id)

    conn=get_db()

    conn.execute("""
        INSERT INTO authorized_devices(
            device_id,
            status,
            stripe_customer_id,
            stripe_subscription_id,
            access_type,
            updated_at
        )
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(device_id)
        DO UPDATE SET
            status='active',
            stripe_customer_id=COALESCE(
                excluded.stripe_customer_id,
                authorized_devices.stripe_customer_id
            ),
            stripe_subscription_id=COALESCE(
                excluded.stripe_subscription_id,
                authorized_devices.stripe_subscription_id
            ),
            access_type=excluded.access_type,
            updated_at=excluded.updated_at
    """,(
        device_id,
        "active",
        stripe_customer_id,
        stripe_subscription_id,
        access_type,
        utc_now()
    ))

    conn.commit()
    conn.close()


def check_device_authorization(device_id:str)->bool:
    device_id=clean_device_id(device_id)

    conn=get_db()

    row=conn.execute("""
        SELECT status
        FROM authorized_devices
        WHERE device_id=?
        LIMIT 1
    """,(device_id,)).fetchone()

    conn.close()

    return bool(
        row and row["status"]=="active"
    )


def deactivate_device_by_subscription(subscription_id:str):
    if not subscription_id:
        return

    conn=get_db()

    conn.execute("""
        UPDATE authorized_devices
        SET status='inactive',
            updated_at=?
        WHERE stripe_subscription_id=?
    """,(utc_now(),subscription_id))

    conn.commit()
    conn.close()


def get_device_record(device_id:str):
    device_id=clean_device_id(device_id)

    conn=get_db()

    row=conn.execute("""
        SELECT *
        FROM authorized_devices
        WHERE device_id=?
        LIMIT 1
    """,(device_id,)).fetchone()

    conn.close()

    return row


# ============================================================
# PYDANTIC MODELS
# ============================================================

class DeviceRequest(BaseModel):
    device_id:str


class CourtesyRequest(BaseModel):
    username:str
    password:str
    device_id:str


class SessionRequest(BaseModel):
    device_id:str
    language:str="es"
    is_hook:bool=False


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
def root():
    return {
        "app":APP_NAME,
        "version":VERSION,
        "status":"online"
    }


@app.get("/health")
def health():
    return {
        "status":"ok",
        "app":APP_NAME,
        "version":VERSION
    }


# ============================================================
# ADMIN / CORTESÍA
# ============================================================

@app.post("/api/v1/authorize-courtesy")
def authorize_courtesy(data:CourtesyRequest):

    if not ADMIN_USER or not ADMIN_PASS:
        raise HTTPException(
            status_code=503,
            detail="Admin access is not configured."
        )

    if data.username.strip()!=ADMIN_USER or data.password!=ADMIN_PASS:
        raise HTTPException(
            status_code=401,
            detail="Incorrect credentials."
        )

    device_id=clean_device_id(data.device_id)

    authorize_device(
        device_id=device_id,
        access_type="courtesy"
    )

    return {
        "ok":True,
        "authorized":True,
        "access_type":"courtesy"
    }


# ============================================================
# STRIPE CHECKOUT
# ============================================================

@app.post("/api/v1/create-checkout-session")
def create_checkout_session(
    data:DeviceRequest,
    request:Request
):
    device_id=clean_device_id(data.device_id)

    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured: STRIPE_SECRET_KEY is missing."
        )

    if not STRIPE_PRICE_ID:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured: STRIPE_PRICE_ID is missing."
        )

    if not stripe.api_key:
        stripe.api_key=STRIPE_SECRET_KEY

    # Determina correctamente la URL pública de Render.
    forwarded_proto=request.headers.get(
        "x-forwarded-proto",
        "https"
    )

    host=request.headers.get("host")

    if not host:
        raise HTTPException(
            status_code=500,
            detail="Unable to determine application host."
        )

    base_url=f"{forwarded_proto}://{host}"

    try:
        # IMPORTANTE:
        # NO usar payment_method_types.
        # Stripe administra los métodos de pago desde
        # Dashboard -> Payment methods.
        checkout_session=stripe.checkout.Session.create(
            line_items=[
                {
                    "price":STRIPE_PRICE_ID,
                    "quantity":1
                }
            ],
            mode="subscription",
            success_url=(
                f"{base_url}/success"
                "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{base_url}/cancel",
            metadata={
                "device_id":device_id
            }
        )

        return {
            "ok":True,
            "checkout_url":checkout_session.url,
            "session_id":checkout_session.id
        }

    except stripe.error.StripeError as e:
        message=str(e)

        raise HTTPException(
            status_code=502,
            detail=f"Stripe error: {message}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Checkout error: {str(e)}"
        )


# ============================================================
# STRIPE WEBHOOK
# ============================================================

@app.post("/webhook/stripe")
async def stripe_webhook(request:Request):

    payload=await request.body()

    if not STRIPE_WEBHOOK_SECRET:
        # Nunca conceder acceso sin verificar el webhook.
        raise HTTPException(
            status_code=503,
            detail="STRIPE_WEBHOOK_SECRET is not configured."
        )

    signature=request.headers.get(
        "stripe-signature"
    )

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Stripe signature."
        )

    try:
        event=stripe.Webhook.construct_event(
            payload,
            signature,
            STRIPE_WEBHOOK_SECRET
        )

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook payload."
        )

    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe webhook signature."
        )

    event_type=event["type"]
    obj=event["data"]["object"]

    # --------------------------------------------------------
    # CHECKOUT COMPLETADO
    # --------------------------------------------------------

    if event_type=="checkout.session.completed":

        metadata=obj.get("metadata") or {}
        device_id=metadata.get("device_id")

        if device_id:
            customer_id=obj.get("customer")
            subscription_id=obj.get("subscription")

            authorize_device(
                device_id=device_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                access_type="subscription"
            )

    # --------------------------------------------------------
    # SUSCRIPCIÓN CANCELADA
    # --------------------------------------------------------

    elif event_type=="customer.subscription.deleted":

        subscription_id=obj.get("id")

        if subscription_id:
            deactivate_device_by_subscription(
                subscription_id
            )

    # --------------------------------------------------------
    # SUSCRIPCIÓN SIN PAGO
    # --------------------------------------------------------

    elif event_type=="customer.subscription.unpaid":

        subscription_id=obj.get("id")

        if subscription_id:
            deactivate_device_by_subscription(
                subscription_id
            )

    return {
        "received":True
    }


# ============================================================
# SUCCESS
# ============================================================

@app.get("/success",response_class=HTMLResponse)
def success(session_id:Optional[str]=None):

    if not session_id:
        return HTMLResponse("""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>AL CIELO</title>
</head>
<body style="
font-family:system-ui;
background:#0f172a;
color:white;
padding:40px;
text-align:center;
">
<h1>AL CIELO</h1>
<p>No se recibió el identificador de la sesión de pago.</p>
<p>Regrese a AL CIELO e intente nuevamente.</p>
</body>
</html>
""")

    if not STRIPE_SECRET_KEY:
        return HTMLResponse("""
<!doctype html>
<html>
<body style="
font-family:system-ui;
background:#0f172a;
color:white;
padding:40px;
text-align:center;
">
<h1>AL CIELO</h1>
<p>Stripe no está configurado.</p>
</body>
</html>
""")

    try:
        checkout_session=stripe.checkout.Session.retrieve(
            session_id
        )

        payment_status=checkout_session.get(
            "payment_status"
        )

        if payment_status=="paid":
            message="""
<p>
Stripe recibió correctamente el pago.
</p>
<p>
La activación de AL CIELO se confirma mediante el sistema de Stripe.
Puede regresar a la aplicación y comenzar su sesión.
</p>
"""
        else:
            message="""
<p>
Stripe recibió la sesión, pero el pago todavía no aparece
como confirmado.
</p>
<p>
Regrese a AL CIELO y espere unos segundos antes de intentar
la sesión completa nuevamente.
</p>
"""

    except stripe.error.StripeError as e:
        message=f"""
<p>
No fue posible consultar el estado del pago.
</p>
<p>
{str(e)}
</p>
"""

    return HTMLResponse(f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>AL CIELO - Pago</title>
</head>
<body style="
font-family:system-ui,-apple-system,sans-serif;
background:#0f172a;
color:#f8fafc;
padding:30px;
text-align:center;
min-height:100vh;
">
<div style="
max-width:600px;
margin:50px auto;
background:#1e293b;
padding:35px;
border-radius:16px;
border:1px solid #334155;
">
<h1 style="color:#38bdf8">AL CIELO</h1>
<h2>Estado del pago</h2>
{message}
<p style="margin-top:30px">
<a href="/"
style="
display:inline-block;
padding:14px 24px;
background:#0d9488;
color:white;
text-decoration:none;
border-radius:8px;
font-weight:bold;
">
Regresar a AL CIELO
</a>
</p>
</div>
</body>
</html>
""")


# ============================================================
# CANCEL
# ============================================================

@app.get("/cancel",response_class=HTMLResponse)
def cancel():

    return HTMLResponse("""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>AL CIELO - Pago cancelado</title>
</head>
<body style="
font-family:system-ui,-apple-system,sans-serif;
background:#0f172a;
color:#f8fafc;
padding:30px;
text-align:center;
min-height:100vh;
">
<div style="
max-width:600px;
margin:50px auto;
background:#1e293b;
padding:35px;
border-radius:16px;
border:1px solid #334155;
">
<h1 style="color:#38bdf8">AL CIELO</h1>
<h2>Pago cancelado</h2>
<p>
No se realizó la activación de la suscripción.
</p>
<p>
Puede regresar cuando esté listo.
</p>
<p style="margin-top:30px">
<a href="/"
style="
display:inline-block;
padding:14px 24px;
background:#0284c7;
color:white;
text-decoration:none;
border-radius:8px;
font-weight:bold;
">
Regresar a AL CIELO
</a>
</p>
</div>
</body>
</html>
""")


# ============================================================
# GENERACIÓN DE SESIONES
# ============================================================

def fallback_session(language:str)->str:

    if language=="pt":
        return """AL CIELO — Sessão de Bem-estar

Comece de forma confortável.

Respire lentamente.
Observe como seu corpo se sente neste momento.

Faça movimentos suaves dentro do seu próprio conforto.

Não é necessário forçar o movimento.

Continue respirando com calma.

Finalize a sessão descansando por alguns instantes."""

    if language=="en":
        return """AL CIELO — Wellness Session

Begin in a comfortable position.

Breathe slowly.
Notice how your body feels right now.

Make gentle movements within your own comfort.

There is no need to force any movement.

Continue breathing calmly.

Finish the session by resting for a few moments."""

    return """AL CIELO — Sesión de Bienestar

Comience en una posición cómoda.

Respire lentamente.
Observe cómo se siente su cuerpo en este momento.

Realice movimientos suaves dentro de su propia comodidad.

No es necesario forzar ningún movimiento.

Continúe respirando con calma.

Termine la sesión descansando durante unos momentos."""


def generate_with_gemini(language:str)->str:

    if not gemini_client:
        return fallback_session(language)

    if language=="pt":
        instruction="""
Crie uma sessão simples de bem-estar geral de aproximadamente
10 minutos para uma pessoa com 50 anos ou mais.

Use linguagem humana, tranquila e fácil de seguir.
Inclua respiração e movimentos suaves.
Não faça diagnóstico.
Não faça afirmações médicas.
Não use linguagem clínica.
Não diga que o exercício trata ou cura doenças.

A pessoa pode estar sentada, em pé ou ter mobilidade reduzida.
Ofereça instruções que possam ser adaptadas ao conforto individual.

Responda somente com a sessão.
"""

    elif language=="en":
        instruction="""
Create a simple general wellness session of approximately
10 minutes for a person aged 50 or older.

Use calm, human, easy-to-follow language.
Include breathing and gentle movements.
Do not diagnose.
Do not make medical claims.
Do not use clinical language.
Do not say that an exercise treats or cures diseases.

The person may be seated, standing, or have reduced mobility.
Give instructions that can be adapted to the person's comfort.

Return only the session.
"""

    else:
        instruction="""
Crea una sesión sencilla de bienestar general de aproximadamente
10 minutos para una persona de 50 años o más.

Usa lenguaje humano, tranquilo y fácil de seguir.
Incluye respiración y movimientos suaves.
No hagas diagnósticos.
No hagas afirmaciones médicas.
No uses lenguaje clínico.
No digas que un ejercicio trata o cura enfermedades.

La persona puede estar sentada, de pie o tener movilidad reducida.
Da instrucciones que puedan adaptarse a la comodidad de cada persona.

Responde solamente con la sesión.
"""

    try:
        response=gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=instruction
        )

        text=getattr(response,"text",None)

        if text and text.strip():
            return text.strip()

    except Exception:
        pass

    return fallback_session(language)


@app.post("/api/v1/generate-session")
def generate_session(data:SessionRequest):

    device_id=clean_device_id(data.device_id)

    language=(data.language or "es").lower()

    if language not in {"es","en","pt"}:
        language="es"

    # --------------------------------------------------------
    # MUESTRA GRATUITA
    # --------------------------------------------------------

    if data.is_hook:
        preview={
            "es":"""AL CIELO — Muestra gratuita

Respire lentamente durante unos segundos.

Relaje los hombros.

Realice un movimiento suave y cómodo.

Esta es una pequeña muestra de cómo funciona
una sesión guiada de AL CIELO.""",

            "en":"""AL CIELO — Free Preview

Breathe slowly for a few seconds.

Relax your shoulders.

Make one gentle and comfortable movement.

This is a short preview of how an
AL CIELO guided session works.""",

            "pt":"""AL CIELO — Amostra gratuita

Respire lentamente durante alguns segundos.

Relaxe os ombros.

Faça um movimento suave e confortável.

Esta é uma pequena amostra de como funciona
uma sessão guiada do AL CIELO."""
        }

        return {
            "ok":True,
            "authorized":False,
            "is_hook":True,
            "session_content":preview[language]
        }

    # --------------------------------------------------------
    # SESIÓN COMPLETA
    # --------------------------------------------------------

    if not check_device_authorization(device_id):

        raise HTTPException(
            status_code=403,
            detail=(
                "Este dispositivo no tiene una suscripción activa. "
                "Active la suscripción de $15.99 para iniciar "
                "la sesión completa."
            )
        )

    content=generate_with_gemini(language)

    return {
        "ok":True,
        "authorized":True,
        "is_hook":False,
        "session_content":content,
        "language":language,
        "version":VERSION
    }


# ============================================================
# CONSULTA DE ESTADO DEL DISPOSITIVO
# ============================================================

@app.post("/api/v1/check-access")
def check_access(data:DeviceRequest):

    device_id=clean_device_id(data.device_id)

    row=get_device_record(device_id)

    if not row:
        return {
            "authorized":False,
            "status":"not_found"
        }

    return {
        "authorized":row["status"]=="active",
        "status":row["status"],
        "access_type":row["access_type"]
    }


# ============================================================
# EJECUCIÓN LOCAL
# ============================================================

if __name__=="__main__":
    import uvicorn

    port=int(os.getenv("PORT","8000"))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
