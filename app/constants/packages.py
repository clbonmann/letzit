# app/constants/packages.py

# Dicionário de pacotes disponíveis
PACKAGES = {
    "PKG_TRIAL": {
        "name": "Pacote Teste",
        "targets": 10,
        "price": 0.00, # Grátis (Só pode usar 1x - lógica futura)
    },
    "PKG_STARTER": {
        "name": "Pacote Iniciante (100km)",
        "targets": 100,
        "price": 300.00, # R$ 3,00 por km
    },
    "PKG_PRO": {
        "name": "Pacote Profissional (200km)",
        "targets": 200,
        "price": 500.00, # R$ 2,50 por km (Mais barato!)
    }
}