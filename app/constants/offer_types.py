# app/constants/offer_types.py

OFFER_TYPE_METADATA = {
    "DISCOUNT_OVER_BILL": {
        "label": "Desconto na Conta",
        "description": "O cliente recebe um desconto percentual ou fixo no valor total do consumo.",
        "icon": "🧾"
    },
    "PRODUCT_DISCOUNT": {
        "label": "Desconto no Produto",
        "description": "Desconto específico em um prato ou drink.",
        "icon": "🍔"
    },
    "FREE_PRODUCT": {
        "label": "Produto Grátis",
        "description": "Ganhe um item (ex: sobremesa) na compra de outro.",
        "icon": "🎁"
    },
    "TABLE_GUARANTEE": {
        "label": "Reserva Garantida",
        "description": "Garante uma mesa disponível no horário agendado.",
        "icon": "📅"
    },
    "GIFT": {
        "label": "Brinde Físico",
        "description": "Ganhe um objeto (boné, copo, chaveiro).",
        "icon": "🧢"
    },
    "2GO_DISCOUNT": {
        "label": "Desconto Retirada",
        "description": "Desconto exclusivo para pedidos 'To Go' (Pegar e Levar).",
        "icon": "🥡"
    },
    "2GO_FREE_PRODUCT": {
        "label": "Brinde na Retirada",
        "description": "Item grátis exclusivo para pedidos 'To Go'.",
        "icon": "🛍️"
    }
}