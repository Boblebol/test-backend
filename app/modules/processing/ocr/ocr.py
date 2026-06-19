import random
import time


def ocr() -> str:
    time.sleep(random.uniform(1, 15))
    if random.random() < 1 / 3:
        raise TimeoutError("OCR provider timeout")
    return "lorem ipsum..."
