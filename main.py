import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from downloader import DownloadSecurityError, download_code
from payments import verify_solana_payment
from slither_hook import run_slither

# ==========================================
# CONFIGURACIÓN Y PERSISTENCIA SQLITE
# ==========================================

MY_SOLANA_WALLET = os.getenv("SOLANA_WALLET", "11111111111111111111111111111111")
MIN_LAMPORTS_REQUIRED = int(os.getenv("MIN_LAMPORTS_REQUIRED", "10000000"))  # 0.01 SOL por defecto
DB_PATH = os.getenv("DATABASE_PATH", "database.db")


def init_db():
    """Inicializa la base de datos SQLite y crea la tabla si no existe."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_payments (
                tx_signature TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def is_signature_processed(tx_signature: str) -> bool:
    """Comprueba si una firma ya fue registrada previamente."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM processed_payments WHERE tx_signature = ?", (tx_signature,))
        return cursor.fetchone() is not None


def record_processed_signature(tx_signature: str):
    """Inserta una firma confirmada en la base de datos."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO processed_payments (tx_signature) VALUES (?)",
            (tx_signature,)
        )
        conn.commit()


def count_processed_signatures() -> int:
    """Devuelve el total de pagos registrados."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM processed_payments")
        row = cursor.fetchone()
        return row[0] if row else 0

# ==========================================
# MODELOS DE ENTRADA Y SALIDA ESTRUCTURADA
# ==========================================

class ProcessRequest(BaseModel):
    message: str = Field(..., description="Texto o comando que contiene la URL a analizar.")
    tx_signature: str = Field(..., description="Firma de la transacción de pago on-chain en Solana.")

class AnalystExtraction(BaseModel):
    action: Literal["audit_smart_contract", "scrape_website", "unknown"]
    target_url: Optional[str] = None
    is_valid: bool
    error_message: Optional[str] = None

class SecurityIssue(BaseModel):
    line_number: Optional[int] = None
    vulnerability_type: str
    fix_suggestion: str

class AuditReport(BaseModel):
    vulnerabilities_found: int
    severity_score: Literal["Low", "Medium", "High", "Critical"]
    issues: List[SecurityIssue]

# ==========================================
# ESTADO GLOBAL, COLA Y CONTROL DE RATE LIMIT
# ==========================================

work_queue: asyncio.Queue = asyncio.Queue()
tickets_db: Dict[str, Dict[str, Any]] = {}

# Gemini Free Tier: 15 Requests Per Minute -> Mínimo 4.5 segundos entre llamadas
RATE_LIMIT_DELAY_SECONDS = 4.5

async def call_gemini_analyst(user_text: str) -> AnalystExtraction:
    """Invoca al agente analista con formato estructurado."""
    api_key = os.getenv("GEMINI_API_KEY")
    prompt = (
        "Eres un orquestador de datos API. Tu única función es extraer la intención del usuario "
        "y la URL objetivo del texto proporcionado. No asumas ni infieras datos que no estén explícitamente en el texto. "
        "Si la URL no es válida o falta la acción, marca is_valid como false y describe el problema en error_message. "
        "Responde estrictamente con un JSON que cumpla: "
        '{"action": "audit_smart_contract"|"scrape_website"|"unknown", "target_url": str|null, "is_valid": bool, "error_message": str|null}.\n\n'
        f"Texto del usuario:\n{user_text}"
    )

    if api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text)
            return AnalystExtraction(**data)
        except Exception as e:
            return AnalystExtraction(
                action="unknown",
                target_url=None,
                is_valid=False,
                error_message=f"Error en llamada a Gemini Analyst: {str(e)}"
            )

    words = user_text.strip().split()
    found_url = next((w for w in words if w.startswith("http://") or w.startswith("https://")), None)
    if found_url:
        return AnalystExtraction(
            action="audit_smart_contract",
            target_url=found_url,
            is_valid=True,
            error_message=None
        )
    return AnalystExtraction(
        action="unknown",
        target_url=None,
        is_valid=False,
        error_message="No se encontró una URL válida en el mensaje."
    )

async def call_gemini_auditor(source_code: str, slither_json: str) -> AuditReport:
    """Invoca al agente auditor Web3 combinando el código fuente y el reporte estático de Slither."""
    api_key = os.getenv("GEMINI_API_KEY")
    prompt = (
        "Eres un auditor Web3. Analiza este contrato. Aquí tienes también el reporte estático de la herramienta matemática Slither: "
        f"{slither_json}. "
        "Usa los hallazgos reales de Slither y tu propia lógica para redactar el JSON final. "
        "No saludes. No des explicaciones fuera del formato. "
        "Devuelve únicamente el objeto JSON con el siguiente esquema: "
        '{"vulnerabilities_found": int, "severity_score": "Low"|"Medium"|"High"|"Critical", '
        '"issues": [{"line_number": int|null, "vulnerability_type": str, "fix_suggestion": str}]}.\n\n'
        f"Código Fuente del Contrato:\n{source_code}"
    )

    if api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text)
            return AuditReport(**data)
        except Exception:
            pass

    return AuditReport(
        vulnerabilities_found=0,
        severity_score="Low",
        issues=[]
    )

# ==========================================
# WORKER EN SEGUNDO PLANO (CONSUMIDOR DE COLA)
# ==========================================

async def background_worker():
    """Worker continuo que procesa la cola respetando estrictamente el rate limit."""
    while True:
        ticket_id = await work_queue.get()
        try:
            tickets_db[ticket_id]["status"] = "procesando"
            user_message = tickets_db[ticket_id]["input_message"]

            # Paso 1: Agente Analista
            analyst_res = await call_gemini_analyst(user_message)
            tickets_db[ticket_id]["analyst_result"] = analyst_res.model_dump()

            if not analyst_res.is_valid or not analyst_res.target_url:
                tickets_db[ticket_id]["status"] = "fallido"
                tickets_db[ticket_id]["error"] = analyst_res.error_message or "Intención o URL no válida."
                continue

            # Respetar rate limit (15 RPM)
            await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS)

            # Paso 2: Hook intermedio - Descarga segura con whitelist y límite 150 KB
            try:
                code_content = await download_code(analyst_res.target_url)
            except DownloadSecurityError as sec_err:
                tickets_db[ticket_id]["status"] = "fallido"
                tickets_db[ticket_id]["error"] = f"Fallo de seguridad en descarga: {str(sec_err)}"
                continue

            # Hook de análisis estático: Ejecución de Slither
            slither_output = await run_slither(code_content)

            # Paso 3: Agente Auditor Web3 (combinando código y hallazgos de Slither)
            audit_report = await call_gemini_auditor(code_content, slither_output)
            tickets_db[ticket_id]["audit_report"] = audit_report.model_dump()
            tickets_db[ticket_id]["status"] = "completado"

            # Respetar rate limit tras la llamada del auditor
            await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS)

        except Exception as exc:
            tickets_db[ticket_id]["status"] = "fallido"
            tickets_db[ticket_id]["error"] = f"Error inesperado durante la ejecución: {str(exc)}"
        finally:
            work_queue.task_done()

# ==========================================
# LIFESPAN Y APLICACIÓN FASTAPI
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker_task = asyncio.create_task(background_worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Crypto Audit Bot API", version="1.0.0", lifespan=lifespan)

@app.post("/api/v1/process")
async def process_task(payload: ProcessRequest):
    sig = payload.tx_signature.strip()

    # 1. Verificación persistente contra Replay Attacks en SQLite
    if is_signature_processed(sig):
        raise HTTPException(
            status_code=402,
            detail="Payment Required: La firma de transacción ya ha sido utilizada previamente."
        )

    # 2. Verificación on-chain en Solana
    is_paid = await verify_solana_payment(
        tx_signature=sig,
        my_wallet=MY_SOLANA_WALLET,
        min_lamports=MIN_LAMPORTS_REQUIRED
    )

    if not is_paid:
        raise HTTPException(
            status_code=402,
            detail="Payment Required: Transacción inexistente, no confirmada o con importe insuficiente."
        )

    # 3. Registrar firma consumida de forma persistente
    record_processed_signature(sig)

    ticket_id = str(uuid.uuid4())
    tickets_db[ticket_id] = {
        "ticket_id": ticket_id,
        "status": "en cola",
        "tx_signature": sig,
        "input_message": payload.message,
        "analyst_result": None,
        "audit_report": None,
        "error": None
    }
    await work_queue.put(ticket_id)
    return {
        "ticket_id": ticket_id,
        "status": "en cola"
    }

@app.get("/api/v1/status/{ticket_id}")
async def get_status(ticket_id: str):
    ticket = tickets_db.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    return ticket

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "queue_size": work_queue.qsize(),
        "processed_payments_count": count_processed_signatures()
    }
