from pydantic import BaseModel
from typing import Dict

class DashboardStatsResponse(BaseModel):
    active_offers_count: int
    active_offers_breakdown: Dict[str, int] # Ex: {"NORMAL": 2, "CITY_HOME": 1}
    
    # KPIs de Hoje (UTC ou Local do Restaurante)
    today_accepted: int
    today_redeemed: int
    today_conversion_rate: float # % de quem aceitou e foi validar
    today_expired_no_show: int   # Aceitou hoje, expirou hoje e não foi
