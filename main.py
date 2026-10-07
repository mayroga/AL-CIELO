import os
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import stripe
from google import genai
from google.genai import types
from database import authorize_device, check_device_authorization

app = FastAPI(title="AL CIELO - Production Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Carga estricta de variables de entorno configuradas en Render
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Prompt maestro inmutable estructurado por bloques temporales estrictos
SYSTEM_WELLNESS_PROMPT = """
Eres el motor de bienestar universal de la aplicación "AL CIELO", diseñada exclusivamente para adultos mayores de 50 años en adelante. 
Tu alcance es universal: debes estructurar sesiones aptas para cualquier condición física (personas totalmente activas, con movilidad reducida, en silla de ruedas o completamente postradas/en cama).

REGLAS ABSOLUTAS E INMUTABLES PARA LA DURACIÓN Y ESTRUCTURA DE 10 MINUTOS:
Cada sesión diaria debe entregarse estrictamente estructurada en 4 bloques temporales claros para garantizar una experiencia completa y profesional:
1. BLOQUE 1 (Minuto 0 al 1): Aviso de seguridad obligatorio de 5 segundos, seguido de calibración respiratoria inicial y toma de conciencia corporal (adaptada para cualquier postura, incluso encamados).
2. BLOQUE 2 (Minuto 1 al 4): Movilización articular suave y activación circulatoria por tandas (comenzando desde extremidades superiores o inferiores según el enfoque del día, asegurando micro-movimientos seguros).
3. BLOQUE 3 (Minuto 4 al 8): Tandas principales de bienestar postural, estiramientos de bajo impacto y conexión de movilidad funcional, con instrucciones claras y pausas de respiración.
4. BLOQUE 4 (Minuto 8 al 10): Cierre de relajación profunda, integración de la postura y mensaje de estabilidad y esperanza para el resto del día.

REGLAS DE ORO:
1. ENFOQUE EXCLUSIVO DE WELLNESS: Cero términos médicos, diagnósticos, tratamientos o curas. Eres un especialista en bienestar, movilidad, circulación y estilo de vida.
2. VARIABILIDAD INFINITA: Jamás repites la misma secuencia. Cambias sutilmente el orden, los enfoques, las metáforas de bienestar y las pautas de respiración para que cada sesión diaria sea única y diferente.
3. Tono sumamente cálido, humano, respetuoso, claro, directo y fácil de seguir.
"""

# Interfaz visual interactiva amigable para adultos mayores (50+)
@app.get("/", response_class=HTMLResponse)
async def interactive_ui():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AL CIELO - Bienestar Diario (50+)</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f4f8fb;
                color: #2c3e50;
                margin: 0;
                padding: 20px;
                display: flex;
                flex-direction: column;
                align-items: center;
            }
            .container {
                max-width: 700px;
                width: 100%;
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                text-align: center;
            }
            h1 { color: #1b4f72; font-size: 2.2rem; margin-bottom: 5px; }
            p.subtitle { font-size: 1.2rem; color: #566573; margin-bottom: 25px; }
            .section {
                margin: 20px 0;
                padding: 20px;
                background: #fdfefe;
                border: 1px solid #ebedef;
                border-radius: 8px;
                text-align: left;
            }
            label { font-size: 1.1rem; font-weight: bold; color: #2c3e50; display: block; margin-bottom: 8px; }
            select, button {
                font-size: 1.1rem;
                padding: 12px 15px;
                width: 100%;
                border-radius: 6px;
                border: 1px solid #cbd5e1;
                margin-top: 5px;
                box-sizing: border-box;
            }
            button {
                background-color: #2e86c1;
                color: white;
                font-weight: bold;
                border: none;
                cursor: pointer;
                margin-top: 15px;
                transition: background 0.3s;
            }
            button:hover { background-color: #2471a3; }
            .btn-pay {
                background-color: #27ae60;
            }
            .btn-pay:hover { background-color: #219653; }
            #output {
                margin-top: 20px;
                background: #f8f9fa;
                border-left: 5px solid #2e86c1;
                padding: 15px;
                text-align: left;
                white-space: pre-wrap;
                font-size: 1.05rem;
                line-height: 1.6;
                display: none;
                max-height: 400px;
                overflow-y: auto;
            }
            .disclaimer {
                font-size: 0.9rem;
                color: #7f8c8d;
                margin-top: 25px;
                border-top: 1px solid #eaecee;
                padding-top: 15px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AL CIELO</h1>
            <p class="subtitle">Bienestar Diario Adaptado (50+)</p>

            <div class="section">
                <label for="languageSelect">Seleccione su idioma / Select language:</label>
                <select id="languageSelect">
                    <option value="es">Español</option>
                    <option value="en">English</option>
                    <option value="pt">Português</option>
                </select>

                <button onclick="solicitarSesion(true)">Ver Muestra Gratuita (30 Segundos)</button>
                <button onclick="solicitarSesion(false)">Iniciar Sesión Completa (10 Minutos)</button>
            </div>

            <div class="section" style="background: #eaf2f8; text-align: center;">
                <label>Acceso Completo Permanente ($15.99 / mes)</label>
                <p style="font-size: 0.95rem; color: #515a5a;">Asegure el acceso total diario vinculado a su dispositivo.</p>
                <button class="btn-pay" onclick="iniciarPago()">Suscribirme Ahora con Stripe</button>
            </div>

            <div id="output"></div>

            <div class="disclaimer">
                Aviso de seguridad: Realice únicamente los movimientos que le resulten cómodos y deténgase ante cualquier molestia. Enfoque exclusivo de bienestar.
            </div>
        </div>

        <script>
            // Genera o recupera un identificador de hardware único local para el navegador
            function getDeviceId() {
                let deviceId = localStorage.getItem("al_cielo_device_id");
                if (!deviceId) {
                    deviceId = "web-client-" + Math.random().toString(36).substring(2) + "-" + Date.now();
                    localStorage.setItem("al_cielo_device_id", deviceId);
                }
                return deviceId;
            }

            async function solicitarSesion(isHook) {
                const lang = document.getElementById("languageSelect").value;
                const outputDiv = document.getElementById("output");
                outputDiv.style.display = "block";
                outputDiv.innerText = "Conectando con el motor de bienestar... Por favor espere.";

                try {
                    const response = await fetch('/api/v1/generate-session', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            device_id: getDeviceId(),
                            language: lang,
                            is_hook: isHook
                        })
                    });

                    const data = await response.json();

                    if (response.status === 200) {
                        outputDiv.innerText = data.session_content;
                    } else if (response.status === 403) {
                        outputDiv.innerText = "Acceso restringido: Esta sesión completa requiere una suscripción activa. Utilice el botón verde de pago para desbloquear su dispositivo.";
                    } else {
                        outputDiv.innerText = "Error: " + (data.detail || "No se pudo procesar la solicitud.");
                    }
                } catch (err) {
                    outputDiv.innerText = "Error de conexión técnico: " + err.message;
                }
            }

            async function iniciarPago() {
                try {
                    const response = await fetch('/api/v1/create-checkout-session', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ device_id: getDeviceId() })
                    });
                    const data = await response.json();
                    if (data.checkout_url) {
                        window.location.href = data.checkout_url;
                    } else {
                        alert("No se pudo generar la pasarela de pago.");
                    }
                } catch (err) {
                    alert("Error al conectar con Stripe: " + err.message);
                }
            }
        </script>
    </body>
    </html>
    """

@app.post("/api/v1/create-checkout-session")
async def create_checkout_session(request: Request):
    """Crea la pasarela de pago en Stripe por $15.99 vinculada al hardware del dispositivo."""
    try:
        body = await request.json()
        device_id = body.get("device_id")
        
        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': STRIPE_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"https://al-cielo.onrender.com/success?device_id={device_id}",
            cancel_url="https://al-cielo.onrender.com/cancel",
            metadata={'device_id': device_id}
        )
        return {"checkout_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/success", response_class=HTMLResponse)
async def payment_success(device_id: str = None):
    """Pantalla visual de éxito al retornar de Stripe tras completar el pago."""
    if device_id:
        authorize_device(device_id)
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"><title>Pago Exitoso - AL CIELO</title></head>
    <body style="font-family: Arial; text-align: center; padding-top: 50px; background: #f4f8fb;">
        <div style="max-width: 500px; margin: auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
            <h1 style="color: #27ae60;">¡Suscripción Exitosa!</h1>
            <p style="font-size: 1.1rem;">Su dispositivo ha sido autorizado correctamente.</p>
            <a href="/" style="display: inline-block; margin-top: 20px; padding: 12px 20px; background: #2e86c1; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Volver a la Aplicación</a>
        </div>
    </body>
    </html>
    """

@app.get("/cancel", response_class=HTMLResponse)
async def payment_cancel():
    """Pantalla visual si el usuario cancela el pago en Stripe."""
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"><title>Pago Cancelado - AL CIELO</title></head>
    <body style="font-family: Arial; text-align: center; padding-top: 50px; background: #f4f8fb;">
        <div style="max-width: 500px; margin: auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
            <h1 style="color: #c0392b;">Pago Cancelado</h1>
            <p style="font-size: 1.1rem;">El proceso de suscripción fue cancelado. Puede intentarlo de nuevo cuando lo desee.</p>
            <a href="/" style="display: inline-block; margin-top: 20px; padding: 12px 20px; background: #2e86c1; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">Volver al Inicio</a>
        </div>
    </body>
    </html>
    """

@app.post("/api/v1/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """Webhook oficial de Stripe para activar automáticamente el dispositivo al completarse el pago."""
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature or payload.")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        device_id = session.get("metadata", {}).get("device_id")
        if device_id:
            authorize_device(device_id)

    return {"status": "success"}

@app.post("/api/v1/verify-device")
async def verify_device(request: Request):
    """Verifica si el dispositivo actual posee una licencia activa."""
    body = await request.json()
    device_id = body.get("device_id")
    authorized = check_device_authorization(device_id)
    return {"device_id": device_id, "authorized": authorized}

@app.post("/api/v1/generate-session")
async def generate_session(request: Request):
    """
    Genera la sesión diaria de 10 minutos (o gancho gratuito de 30 segundos) 
    validando obligatoriamente la suscripción del dispositivo bajo la estructura por bloques.
    """
    try:
        body = await request.json()
        device_id = body.get("device_id")
        language = body.get("language", "en") # 'es', 'en', 'pt'
        is_hook = body.get("is_hook", False) # True para la muestra de 30 segundos gratis

        if not device_id:
            raise HTTPException(status_code=400, detail="Device ID required.")

        # Si no es la sesión de gancho de 30 segundos, exige verificación estricta de pago en el dispositivo
        if not is_hook and not check_device_authorization(device_id):
            raise HTTPException(status_code=403, detail="Device not authorized. Subscription required.")

        duration_text = "30 seconds free visual preview hook" if is_hook else "10 minutes complete unique daily session structured in 4 time blocks"
        
        prompt = f"""
        Genera una sesión dirigida a adultos mayores de 50 años en adelante, en idioma [{language}], duración [{duration_text}].
        Sigue estrictamente la estructura de bloques temporales exigida, asegurando el aviso legal inicial de seguridad, activación circulatoria universal, confort postural y tandas de bienestar.
        Tono cálido, directo, sin rodeos, adaptado para cualquier estado físico (desde activos hasta postrados), variabilidad infinita.
        """

        response = geminit_client = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_WELLNESS_PROMPT,
                temperature=0.7,
            ),
        )

        return {
            "status": "success",
            "app_name": "AL CIELO",
            "target_age": "50+",
            "language": language,
            "device_id": device_id,
            "session_content": response.text
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
