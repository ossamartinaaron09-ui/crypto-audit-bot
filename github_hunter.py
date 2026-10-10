import asyncio
from datetime import datetime, timedelta, timezone
import os
import random
from typing import Any, Dict, List
import httpx

# ==========================================
# CONFIGURACIÓN DE BÚSQUEDA Y GITHUB API
# ==========================================

GITHUB_API_SEARCH_URL = "https://api.github.com/search/repositories"
TELEGRAM_BOT_PLACEHOLDER = "[TU_ENLACE_AL_BOT_DE_TELEGRAM]"
OUTPUT_FILE = "clientes_diarios.txt"

# Títulos variados para reducir huella de automatización repetitiva
ISSUE_TITLES = [
    "Quick question regarding recent Solidity updates",
    "Static analysis optimization findings",
    "Potential security review notes on recent commits",
    "Best practice feedback for smart contract logic"
]


def generate_issue_template(repo_name: str, owner_name: str) -> str:
    """
    Genera una plantilla en Markdown profesional en inglés lista para pegar
    o publicar como nuevo Issue en el repositorio objetivo.
    """
    return f"""### 🛡️ Automated Security & Best Practices Scan Advisory

Hi @{owner_name},

While reviewing recent Web3 and Solidity deployments, our automated static analysis pipeline flagged potential areas for optimization and security verification in **{repo_name}**.

Common risk areas in newly updated smart contracts often include:
- **Reentrancy & State Updates:** Checks-effects-interactions violations.
- **Access Control & Permissions:** Missing function visibility or unverified modifiers.
- **Gas Inefficiencies:** Redundant storage reads/writes in tight loops.
- **Solidity 0.8+ Edge Cases:** Unexpected reverts in custom math or external calls.

#### 🔍 Get Your Full Structured Audit Report
We provide on-demand, fast static audits powered by Slither heuristics and LLM logic analysis.

You can verify and inspect the full report for your contract via our automated Telegram Bot:
👉 **[Run Automated Audit on Telegram]({TELEGRAM_BOT_PLACEHOLDER})**

*A symbolic trial fee (~0.01 SOL) is requested to prevent queue spam and support automated compute.*

Best regards,  
*Web3 Security Watch Team*
"""


async def fetch_recent_solidity_repos(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Consulta la REST API pública de GitHub buscando repositorios con lenguaje
    Solidity actualizados en las últimas 24 horas.
    """
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    query = f"language:Solidity pushed:>={yesterday} fork:false"
    params = {
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": limit
    }

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "CryptoAudit-Lead-Hunter/1.0"
    }

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(GITHUB_API_SEARCH_URL, params=params, headers=headers)

        if response.status_code == 403:
            print("⚠️ [github_hunter] Rate limit alcanzado en la API pública de GitHub.")
            return []

        if response.status_code != 200:
            print(f"❌ [github_hunter] Error al consultar GitHub API: HTTP {response.status_code}")
            return []

        data = response.json()
        return data.get("items", [])


async def post_github_issue(owner: str, repo: str, title: str, body: str, token: str) -> bool:
    """
    Publica un nuevo Issue en el repositorio especificado a través de la REST API de GitHub.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "CryptoAudit-Lead-Hunter/1.0"
    }
    payload = {
        "title": title,
        "body": body
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 201:
                return True
            print(
                f"⚠️ [github_hunter] Fallo al publicar Issue en {owner}/{repo}: "
                f"HTTP {response.status_code} - {response.text[:120]}"
            )
            return False
        except Exception as exc:
            print(f"❌ [github_hunter] Error de conexión al crear Issue en {owner}/{repo}: {str(exc)}")
            return False


async def main():
    timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp_now}] [github_hunter] Buscando repositorios recientes de Solidity...")
    repos = await fetch_recent_solidity_repos(limit=10)

    if not repos:
        print(f"[{timestamp_now}] [github_hunter] No se obtuvieron repositorios en esta ejecución.")
        return

    # 1. Guardar siempre todos los leads encontrados en clientes_diarios.txt
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write(f"📅 CAPTACIÓN DE CLIENTES - FECHA: {timestamp_now}\n")
        f.write(f"Total repositorios detectados: {len(repos)}\n")
        f.write("=" * 80 + "\n\n")

        for idx, repo in enumerate(repos, start=1):
            full_name = repo.get("full_name", "Desconocido")
            html_url = repo.get("html_url", "")
            owner_login = repo.get("owner", {}).get("login", "dev")
            stars = repo.get("stargazers_count", 0)
            description = repo.get("description") or "Sin descripción proporcionada."

            issue_content = generate_issue_template(repo_name=full_name, owner_name=owner_login)

            f.write(f"[{idx}/10] REPOSITORIO: {full_name}\n")
            f.write(f"URL: {html_url}\n")
            f.write(f"Stars: {stars} | Info: {description[:100]}\n")
            f.write(f"Crear Issue aquí: {html_url}/issues/new\n")
            f.write("-" * 60 + "\n")
            f.write("TEXTO PARA COPIAR Y PEGAR EN EL ISSUE:\n")
            f.write("-" * 60 + "\n")
            f.write(issue_content.strip() + "\n\n")
            f.write("=" * 80 + "\n\n")

    print(f"[{timestamp_now}] [github_hunter] ✅ Leads registrados en '{OUTPUT_FILE}'.")

    # 2. Comprobar disponibilidad de GITHUB_TOKEN para publicación automática
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print(
            f"[{timestamp_now}] [github_hunter] GITHUB_TOKEN no configurado en variables de entorno. "
            "Se omite la publicación automática de Issues (modo pasivo finalizado)."
        )
        return

    print(f"[{timestamp_now}] [github_hunter] GITHUB_TOKEN detectado. Iniciando publicación con cadencia anti-spam...")

    total_repos = len(repos)
    for idx, repo in enumerate(repos, start=1):
        owner = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")
        full_name = repo.get("full_name", f"{owner}/{repo_name}")

        if not owner or not repo_name:
            continue

        chosen_title = random.choice(ISSUE_TITLES)
        issue_body = generate_issue_template(repo_name=full_name, owner_name=owner)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{idx}/{total_repos}] Publicando Issue en {full_name}...")
        success = await post_github_issue(
            owner=owner,
            repo=repo_name,
            title=chosen_title,
            body=issue_body,
            token=token
        )

        if success:
            print(f"✅ Issue publicado con éxito en {full_name} (Título: '{chosen_title}')")
        else:
            print(f"⚠️ No se pudo publicar en {full_name}")

        # Mecanismo anti-spam: pausa aleatoria entre 300s (5 min) y 900s (15 min)
        if idx < total_repos:
            delay = random.randint(300, 900)
            minutes = delay / 60.0
            print(f"⏳ Pausa de seguridad anti-spam: esperando {delay} segundos (~{minutes:.1f} minutos)...")
            await asyncio.sleep(delay)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [github_hunter] Proceso de prospección finalizado.")


if __name__ == "__main__":
    asyncio.run(main())
