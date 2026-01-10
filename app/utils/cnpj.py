import re

def normalize_cnpj(cnpj: str) -> str:
    digits = re.sub(r"\D+", "", cnpj or "")
    return digits
