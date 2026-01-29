import re

def normalize_cnpj(cnpj: str) -> str:
    digits = re.sub(r"\D+", "", cnpj or "")
    return digits

def validate_cnpj(cnpj: str) -> bool:
    # 1. Remove caracteres não numéricos
    cnpj = re.sub(r'[^0-9]', '', cnpj)

    # 2. Verifica tamanho e se não são todos iguais (ex: 00000000000000)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False

    # 3. Define os pesos
    # Pesos para o 1º dígito: 5,4,3,2,9,8,7,6,5,4,3,2
    weight1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    # Pesos para o 2º dígito: 6,5,4,3,2,9,8,7,6,5,4,3,2
    weight2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def calculate_digit(number_body, weights):
        soma = sum(int(digit) * weight for digit, weight in zip(number_body, weights))
        remainder = soma % 11
        if remainder < 2:
            return 0
        else:
            return 11 - remainder

    # 4. Calcula o primeiro dígito verificador
    body = cnpj[:12]
    digit1 = calculate_digit(body, weight1)

    # 5. Calcula o segundo dígito verificador (adicionando o 1º dígito ao corpo)
    body = cnpj[:12] + str(digit1)
    digit2 = calculate_digit(body, weight2)

    # 6. Verifica se os dígitos calculados batem com os fornecidos
    calculated_ends = f"{digit1}{digit2}"
    provided_ends = cnpj[-2:]

    return calculated_ends == provided_ends
