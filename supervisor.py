import asyncio
import os
import signal
import sys
from datetime import datetime

# ==========================================
# CONFIGURACIÓN DEL SUPERVISOR
# ==========================================

PYTHON_BIN = sys.executable

PORT = os.getenv("PORT", "8000")

SERVICES = [
    {
        "name": "FastAPI Server",
        "command": [PYTHON_BIN, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(PORT)]
    },
    {
        "name": "Telegram Bot",
        "command": [PYTHON_BIN, "bot.py"]
    }
]

HUNTER_COMMAND = [PYTHON_BIN, "github_hunter.py"]
CRON_INTERVAL_SECONDS = 24 * 60 * 60  # 24 horas

active_processes = []


def log(section: str, message: str):
    """Genera logs con marca de tiempo precisa."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] [{section}] {message}", flush=True)


async def supervise_service(service_name: str, command: list):
    """
    Ejecuta y monitorea un servicio demonio. Si finaliza o crashea,
    lo reinicia automáticamente tras una pausa de 5 segundos.
    """
    while True:
        log("SUPERVISOR", f"Iniciando servicio: {service_name} -> {' '.join(command)}")
        try:
            proc = await asyncio.create_subprocess_exec(*command)
            active_processes.append(proc)
            
            returncode = await proc.wait()
            
            if proc in active_processes:
                active_processes.remove(proc)

            log(
                "SUPERVISOR",
                f"⚠️ El servicio '{service_name}' se detuvo inesperadamente con código {returncode}."
            )
        except Exception as exc:
            log("SUPERVISOR", f"❌ Error al intentar ejecutar '{service_name}': {str(exc)}")

        log("SUPERVISOR", f"Reiniciando '{service_name}' en 5 segundos...")
        await asyncio.sleep(5)


async def cron_hunter_task():
    """
    Ejecuta el script de prospección github_hunter.py exactamente una vez cada 24 horas.
    """
    while True:
        log("CRON-HUNTER", "Iniciando ejecución programada de captación (github_hunter.py)...")
        try:
            proc = await asyncio.create_subprocess_exec(*HUNTER_COMMAND)
            active_processes.append(proc)
            await proc.wait()
            if proc in active_processes:
                active_processes.remove(proc)
            log("CRON-HUNTER", "✅ Captación diaria completada. Leads guardados en clientes_diarios.txt.")
        except Exception as exc:
            log("CRON-HUNTER", f"❌ Error durante la ejecución de github_hunter: {str(exc)}")

        log("CRON-HUNTER", "Próxima búsqueda programada en 24 horas.")
        await asyncio.sleep(CRON_INTERVAL_SECONDS)


def handle_shutdown(signum, frame):
    """Cierre limpio de todos los subprocesos hijos ante CTRL+C o SIGTERM."""
    log("SUPERVISOR", "Recibida señal de detención. Terminando subprocesos activos...")
    for proc in active_processes:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    sys.exit(0)


async def main():
    log("SUPERVISOR", "🚀 Arrancando Process Manager del sistema Web3 Audit...")

    # Registrar manejadores de señales para terminación limpia
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Lanzar tareas concurrentes
    tasks = [
        asyncio.create_task(supervise_service(svc["name"], svc["command"]))
        for svc in SERVICES
    ]
    tasks.append(asyncio.create_task(cron_hunter_task()))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        handle_shutdown(None, None)
