import random
import time
import uuid


def external_call(doc_id: str, ocr_text: str, meta: dict, chunks: list[str]) -> str:
    """Simule l'appel HTTP sortant vers le partenaire.
    Retourne un job_id opaque. Le resultat reel arrive plus tard via webhook.
    """
    time.sleep(random.uniform(1, 5))
    if random.random() < 1 / 3:
        raise ConnectionError("partner unreachable")
    return f"j_{uuid.uuid4().hex[:16]}"
