import random
import time


def metadata(text: str) -> dict:
    time.sleep(random.uniform(1, 10))
    if random.random() < 1 / 3:
        raise ValueError("metadata extraction failed")
    return {"doc_type": "fake_type"}
