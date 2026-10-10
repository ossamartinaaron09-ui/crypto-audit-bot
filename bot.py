import os
import time
import requests
import telebot

# ==========================================
# CONFIGURACIÓN DEL BOT
# ==========================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TU_TELEGRAM_BOT_TOKEN_AQUI")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SOLANA_WALLET = os.getenv("SOLANA_WALLET", "11111111111111111111111111111111")
PRICE_SOL = os.getenv("PRICE_SOL", "0.01 SOL")

bot = telebot.TeleBot(BOT_TOKEN)


# ==========================================
# COMANDO /START
# ==========================================

@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    welcome_text = (
        "🛡️ *Bienvenido a CryptoAudit Bot Web3*\n\n"
        "Este servicio realiza una auditoría automatizada y estricta de seguridad "
        "sobre el código fuente de contratos inteligentes mediante Inteligencia Artificial.\n\n"
        f"💰 *Tarifa por auditoría:* `{PRICE_SOL}`\n"
        f"📬 *Wallet de pago (Solana):*\n`{SOLANA_WALLET}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 *Instrucciones para iniciar:*\n"
        "1. Realiza la transferencia de Solana a la wallet indicada.\n"
        "2. Envía un mensaje con el siguiente formato exacto:\n\n"
        "`<URL_DEL_CONTRATO> <TX_SIGNATURE>`\n\n"
        "📌 *Ejemplo:*\n"
        "`https://raw.githubusercontent.com/usuario/repo/main/Token.sol 5K6...firmadetransaccion`\n\n"
        "⚠️ *Nota:* Solo se permiten URLs alojadas en `raw.githubusercontent.com` (máx. 150 KB)."
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")


# ==========================================
# PROCESAMIENTO DE AUDITORÍA
# ==========================================

@bot.message_handler(func=lambda msg: not msg.text.startswith("/"))
def handle_audit_request(message):
    parts = message.text.strip().split()

    if len(parts) < 2:
        bot.reply_to(
            message,
            "⚠️ *Formato inválido*\n\n"
            "Debes enviar la URL del contrato y la firma de la transacción separadas por un espacio:\n"
            "`<URL_DEL_CONTRATO> <TX_SIGNATURE>`",
            parse_mode="Markdown"
        )
        return

    contract_url = parts[0]
    tx_signature = parts[1]

    bot.reply_to(
        message,
        "🔍 *Verificando transacción on-chain en Solana...* Por favor espera un momento.",
        parse_mode="Markdown"
    )

    # 1. Enviar petición a la API FastAPI
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/v1/process",
            json={
                "message": contract_url,
                "tx_signature": tx_signature
            },
            timeout=15
        )
    except requests.exceptions.RequestException as e:
        bot.reply_to(
            message,
            f"❌ *Error de conexión:* No se pudo contactar con el motor de auditoría (`{str(e)}`).",
            parse_mode="Markdown"
        )
        return

    # 2. Manejo de error de pago (HTTP 402)
    if response.status_code == 402:
        error_detail = response.json().get("detail", "Pago requerido.")
        bot.reply_to(
            message,
            f"💳 *Pago no verificado (HTTP 402)*\n\n"
            f"_{error_detail}_\n\n"
            "Asegúrate de haber completado la transacción en Solana hacia la wallet correcta y con los fondos solicitados.",
            parse_mode="Markdown"
        )
        return

    if response.status_code != 200:
        bot.reply_to(
            message,
            f"❌ *Error en la solicitud (HTTP {response.status_code}):*\n`{response.text}`",
            parse_mode="Markdown"
        )
        return

    process_data = response.json()
    ticket_id = process_data.get("ticket_id")

    status_msg = bot.reply_to(
        message,
        f"✅ *Pago confirmado.*\n"
        f"🎟️ *Ticket ID:* `{ticket_id}`\n"
        "⏳ *Estado:* En cola de procesamiento. Esperando turno de análisis...",
        parse_mode="Markdown"
    )

    # 3. Bucle de sondeo del estado del ticket (Polling)
    max_attempts = 36  # 36 x 5s = 180 segundos máx (3 minutos)
    attempt = 0

    while attempt < max_attempts:
        time.sleep(5)
        attempt += 1

        try:
            status_resp = requests.get(f"{API_BASE_URL}/api/v1/status/{ticket_id}", timeout=10)
            if status_resp.status_code != 200:
                continue

            ticket_data = status_resp.json()
            status = ticket_data.get("status")

            if status == "completado":
                report = ticket_data.get("audit_report", {})
                vulnerabilities_found = report.get("vulnerabilities_found", 0)
                severity_score = report.get("severity_score", "Desconocida")
                issues = report.get("issues", [])

                # Formateo amigable en Markdown
                report_md = [
                    "📑 *REPORTE DE AUDITORÍA WEB3*\n",
                    f"🎯 *Severidad Global:* `{severity_score}`",
                    f"🔍 *Vulnerabilidades Detectadas:* `{vulnerabilities_found}`\n",
                    "━━━━━━━━━━━━━━━━━━━━"
                ]

                if not issues:
                    report_md.append("✅ *No se encontraron vulnerabilidades críticas en el código analizado.*")
                else:
                    for i, issue in enumerate(issues, start=1):
                        line_str = f"Línea {issue.get('line_number')}" if issue.get("line_number") else "Global"
                        report_md.append(
                            f"\n*[{i}] {issue.get('vulnerability_type', 'Vulnerabilidad')}* ({line_str})\n"
                            f"💡 *Sugerencia:* _{issue.get('fix_suggestion', 'N/A')}_"
                        )

                report_text = "\n".join(report_md)
                bot.reply_to(message, report_text, parse_mode="Markdown")
                return

            elif status == "fallido":
                error_msg = ticket_data.get("error", "Error desconocido durante la ejecución.")
                bot.reply_to(
                    message,
                    f"❌ *Auditoría fallida*\n\n*Motivo:* {error_msg}",
                    parse_mode="Markdown"
                )
                return

        except requests.exceptions.RequestException:
            pass

    bot.reply_to(
        message,
        f"⏳ El proceso ha tomado más tiempo del esperado. Puedes consultar más tarde con tu ticket: `{ticket_id}`.",
        parse_mode="Markdown"
    )


# ==========================================
# INICIO DEL BOT
# ==========================================

if __name__ == "__main__":
    print("🤖 Iniciando CryptoAudit Telegram Bot...")
    bot.infinity_polling()
