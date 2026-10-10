import os
from typing import Any, Dict, List
import httpx

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")


async def verify_solana_payment(tx_signature: str, my_wallet: str, min_lamports: int) -> bool:
    """
    Verifica una transacción en la red principal de Solana mediante llamada JSON-RPC cruda a getTransaction.
    
    Valida:
    1. Existencia y confirmación de la transacción.
    2. Ejecución exitosa (meta.err is None).
    3. Que el destinatario coincida con my_wallet.
    4. Que los lamports transferidos sean >= min_lamports.
    """
    if not tx_signature or not my_wallet or min_lamports <= 0:
        return False

    payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_signature.strip(),
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(
                SOLANA_RPC_URL,
                json=payload,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                return False

            data = response.json()
            result = data.get("result")

            if not result or not isinstance(result, dict):
                return False

            meta = result.get("meta")
            transaction = result.get("transaction")

            # 1. Comprobar que la transacción no tenga errores
            if not meta or meta.get("err") is not None or not transaction:
                return False

            # 2. Comprobación mediante variación neta de balances en cuenta destinataria
            message = transaction.get("message", {})
            account_keys = message.get("accountKeys", [])
            target_idx = -1

            for idx, key_entry in enumerate(account_keys):
                pubkey = key_entry.get("pubkey") if isinstance(key_entry, dict) else str(key_entry)
                if pubkey == my_wallet:
                    target_idx = idx
                    break

            pre_balances: List[int] = meta.get("preBalances", [])
            post_balances: List[int] = meta.get("postBalances", [])

            if target_idx != -1 and target_idx < len(pre_balances) and target_idx < len(post_balances):
                net_received = post_balances[target_idx] - pre_balances[target_idx]
                if net_received >= min_lamports:
                    return True

            # 3. Comprobación de respaldo inspeccionando instrucciones SystemProgram transfer
            instructions = message.get("instructions", [])
            for inst in instructions:
                if isinstance(inst, dict) and inst.get("program") == "system":
                    parsed = inst.get("parsed")
                    if isinstance(parsed, dict) and parsed.get("type") == "transfer":
                        info = parsed.get("info", {})
                        destination = info.get("destination")
                        lamports = int(info.get("lamports", 0))
                        if destination == my_wallet and lamports >= min_lamports:
                            return True

            # Revisar innerInstructions (transacciones complejas o CPI)
            inner_instructions = meta.get("innerInstructions", [])
            for inner_group in inner_instructions:
                for inst in inner_group.get("instructions", []):
                    if isinstance(inst, dict) and inst.get("program") == "system":
                        parsed = inst.get("parsed")
                        if isinstance(parsed, dict) and parsed.get("type") == "transfer":
                            info = parsed.get("info", {})
                            destination = info.get("destination")
                            lamports = int(info.get("lamports", 0))
                            if destination == my_wallet and lamports >= min_lamports:
                                return True

            return False

    except (httpx.RequestError, ValueError, KeyError):
        return False
