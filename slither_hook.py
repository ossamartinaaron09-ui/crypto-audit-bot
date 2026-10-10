import asyncio
import json
import os
import tempfile


async def run_slither(code_content: str) -> str:
    """
    Ejecuta el analizador estático Slither sobre el código Solidity proporcionado.
    Guarda el contenido en un archivo temporal .sol, invoca Slither y captura el JSON.
    Garantiza la eliminación del archivo temporal en el bloque finally.
    """
    temp_file_path = None
    fallback_compile_error = json.dumps(
        {"status": "error", "message": "Slither no pudo compilar el contrato. Posible error de sintaxis."},
        ensure_ascii=False
    )

    try:
        # 1. Crear archivo temporal con extensión .sol
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sol", delete=False, encoding="utf-8") as temp_file:
            temp_file.write(code_content)
            temp_file_path = temp_file.name

        # 2. Ejecutar Slither CLI de forma asíncrona: slither <temp_file.sol> --json -
        proc = await asyncio.create_subprocess_exec(
            "slither",
            temp_file_path,
            "--json",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, _ = await proc.communicate()

        # Si no hubo salida en stdout o hubo fallo en la ejecución
        if proc.returncode != 0 and not stdout:
            return fallback_compile_error

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        if not stdout_text:
            return fallback_compile_error

        # Validar si stdout es JSON estructurado
        try:
            parsed = json.loads(stdout_text)
            return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            return stdout_text

    except FileNotFoundError:
        return json.dumps(
            {"status": "warning", "message": "Slither CLI no está instalado en el sistema o no se encuentra en el PATH."},
            ensure_ascii=False
        )
    except Exception:
        return fallback_compile_error
    finally:
        # 3. Limpieza garantizada del archivo temporal
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
