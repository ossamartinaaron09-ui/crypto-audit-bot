import urllib.parse
import httpx

MAX_FILE_SIZE_BYTES = 150 * 1024  # 150 KB
ALLOWED_HOST = "raw.githubusercontent.com"


class DownloadSecurityError(Exception):
    """Excepción lanzada ante violaciones de whitelist, tamaño o seguridad."""
    pass


async def download_code(url: str) -> str:
    """
    Descarga código fuente aplicando una whitelist estricta y límite de tamaño.
    - Whitelist: Exclusivamente https://raw.githubusercontent.com
    - Límite de tamaño: Máximo 150 KB procesados en streaming para proteger la RAM.
    """
    if not url or not isinstance(url, str):
        raise DownloadSecurityError("URL no válida o vacía.")

    parsed = urllib.parse.urlparse(url.strip())

    if parsed.scheme != "https":
        raise DownloadSecurityError(
            f"Protocolo inseguro '{parsed.scheme}'. Solo se permite HTTPS."
        )

    if parsed.netloc.lower() != ALLOWED_HOST:
        raise DownloadSecurityError(
            f"Dominio denegado '{parsed.netloc}'. Whitelist restringida a '{ALLOWED_HOST}'."
        )

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        try:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise DownloadSecurityError(
                        f"Error de descarga: Servidor retornó código HTTP {response.status_code}"
                    )

                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
                    raise DownloadSecurityError(
                        f"Archivo rechazado: Tamaño en cabecera ({content_length} bytes) "
                        f"supera el límite de {MAX_FILE_SIZE_BYTES} bytes (150 KB)."
                    )

                chunks = []
                total_bytes = 0

                async for chunk in response.aiter_bytes(chunk_size=8192):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_FILE_SIZE_BYTES:
                        raise DownloadSecurityError(
                            f"Descarga abortada: El flujo superó el límite de {MAX_FILE_SIZE_BYTES} bytes (150 KB)."
                        )
                    chunks.append(chunk)

                return b"".join(chunks).decode("utf-8", errors="replace")

        except httpx.RequestError as exc:
            raise DownloadSecurityError(f"Error de conexión con el host de descarga: {str(exc)}")
