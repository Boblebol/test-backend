import random
import time


def chunking(text: str) -> list[str]:
    time.sleep(random.uniform(1, 12))
    if random.random() < 1 / 3:
        raise ValueError("chunking failed")
    return ["chunk_1", "chunk_2", "..."]
