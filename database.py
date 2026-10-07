import os
import sqlite3

DB_FILE = "alcielo_licences.db"

def init_db():
    """Inicializa la tabla SQLite para vincular licencias activas al identificador de hardware del dispositivo."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authorized_devices (
            device_id TEXT PRIMARY KEY,
            status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def authorize_device(device_id: str):
    """Registra de forma permanente el dispositivo tras confirmación de pago exitosa."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO authorized_devices (device_id, status)
        VALUES (?, 'active')
    ''', (device_id,))
    conn.commit()
    conn.close()

def check_device_authorization(device_id: str) -> bool:
    """Verifica si el dispositivo tiene una licencia de suscripción activa."""
    if not device_id:
        return False
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM authorized_devices WHERE device_id = ?', (device_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None and row[0] == 'active'

def verify_admin_credentials(username: str, password: str) -> bool:
    """Valida el acceso administrativo con las variables de entorno de Render."""
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "password")
    return username == admin_user and password == admin_pass

# Ejecutar inicialización al importar
init_db()
