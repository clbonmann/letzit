from __future__ import annotations

from datetime import datetime, timezone
from typing import List,Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
# Certifique-se que estes utilitários existem no seu projeto:
from app.utils.cnpj import normalize_cnpj 
from app.services.storage import upload_image 
# IMPORTANDO SCHEMAS 
from app.schemas.staff import RestaurantRead, RestaurantUpdate, RestaurantFeaturesResponse, RestaurantFeaturesUpdateRequest, RestaurantFeaturesUpdateResponse, TaxGroup,TaxItem

router = APIRouter(prefix="/staff/restaurant", tags=["staff-restaurant"])

GroupCode = Literal["CUISINE_TYPE", "CUISINE_FEATURE", "SPACE_FEATURE"]

def _is_internal_admin(staff: dict) -> bool:
    # ajuste se necessário
    return staff.get("role") == "INTERNAL_ADMIN" or int(staff.get("restaurant_id", 0)) == 1


def _require_can_manage_restaurant(staff: dict, restaurant_id: int) -> None:
    if _is_internal_admin(staff):
        return
    if int(staff["restaurant_id"]) != int(restaurant_id):
        raise HTTPException(status_code=403, detail="Not allowed for this restaurant")

def _require_admin_role(staff: dict) -> None:
    # Se você tiver require_admin(staff), pode usar ele.
    role = staff.get("role")
    if role not in ("INTERNAL_ADMIN", "CLIENT_ADMIN"):
        raise HTTPException(status_code=403, detail="Admin role required")
    

@router.get("", response_model=List[RestaurantRead])
async def list_my_restaurants(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Lista dados do restaurante.
    - INTERNAL_ADMIN: Vê todos.
    - Staff Normal: Vê apenas o seu.
    """
    role = str(staff.get("role") or "")
    rid = int(staff.get("restaurant_id") or 0)

    base_sql = """
        SELECT id, name, cnpj, logo_url,
               NULLIF(COALESCE(city, ''), '') AS city,
               address_street, address_number, address_district,
               address_city, address_state, address_zip, address_country,
               ST_Y(geog::geometry) as lat,
               ST_X(geog::geometry) as long
        FROM restaurants
    """

    if role == "INTERNAL_ADMIN":
        query = text(f"{base_sql} ORDER BY id DESC")
        params = {}
    else:
        query = text(f"{base_sql} WHERE id = :rid")
        params = {"rid": rid}

    rows = (await db.execute(query, params)).mappings().all()
    
    if role != "INTERNAL_ADMIN" and not rows:
        raise HTTPException(404, "Restaurante vinculado não encontrado.")

    return [RestaurantRead(**row) for row in rows]


@router.patch("", response_model=RestaurantRead)
async def update_restaurant_details(
    payload: RestaurantUpdate,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Atualiza dados textuais (Nome, Endereço, CNPJ).
    """
    role = str(staff.get("role") or "")
    
    # Define ID alvo
    if role == "INTERNAL_ADMIN":
        if not payload.id:
            raise HTTPException(400, "Admin deve informar o 'id' do restaurante.")
        rid = payload.id
    else:
        rid = int(staff["restaurant_id"])

    # Carrega dados atuais
    cur = (await db.execute(text("SELECT id, cnpj FROM restaurants WHERE id = :rid"), {"rid": rid})).mappings().first()
    if not cur:
        raise HTTPException(404, "Restaurante não encontrado.")

    # Valida CNPJ
    new_cnpj = normalize_cnpj(payload.cnpj) if payload.cnpj is not None else cur["cnpj"]
    if new_cnpj and len(new_cnpj) != 14:
        raise HTTPException(400, "CNPJ deve conter 14 dígitos.")

    # Update
    try:
        row = (await db.execute(
            text("""
                UPDATE restaurants
                SET
                  name = COALESCE(:name, name),
                  cnpj = :cnpj,
                  address_street = COALESCE(:address_street, address_street),
                  address_number = COALESCE(:address_number, address_number),
                  address_district = COALESCE(:address_district, address_district),
                  address_city = COALESCE(:address_city, address_city),
                  address_state = COALESCE(:address_state, address_state),
                  address_zip = COALESCE(:address_zip, address_zip),
                  address_country = COALESCE(:address_country, address_country),
                  logo_url = COALESCE(:logo_url, logo_url),
                  logo_updated_at = CASE WHEN :logo_url IS NOT NULL THEN :now ELSE logo_updated_at END
                WHERE id = :rid
                RETURNING id, name, cnpj, logo_url,
                          NULLIF(COALESCE(city, ''), '') AS city,
                          address_street, address_number, address_district,
                          address_city, address_state, address_zip, address_country,
                          ST_Y(geog::geometry) as lat,
                          ST_X(geog::geometry) as long
            """),
            {
                "rid": rid,
                "name": payload.name,
                "cnpj": new_cnpj,
                "address_street": payload.address_street,
                "address_number": payload.address_number,
                "address_district": payload.address_district,
                "address_city": payload.address_city,
                "address_state": payload.address_state,
                "address_zip": payload.address_zip,
                "address_country": payload.address_country,
                "logo_url": payload.logo_url,
                "now": datetime.now(timezone.utc),
            },
        )).mappings().first()

        await db.commit()
        return RestaurantRead(**row)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "CNPJ já registrado.")


@router.post("/logo")
async def upload_restaurant_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    """Upload de Logo para Cloudinary + Update no Banco."""
    restaurant_id = int(staff["restaurant_id"])

    try:
        # Definimos a transformação aqui:
        # width/height 500: Garante boa qualidade (retina) mas leve.Otptei por 150 para as logos.
        # crop="fill": Corta o excesso para preencher o quadrado (não estica).
        # gravity="center": Tenta manter o centro da imagem.
        transformations = {
            "width": 150, 
            "height": 150, 
            "crop": "pad",       # <--- MUDOU DE 'fill' PARA 'pad'
            "background": "white", # <--- Cor do fundo para preencher o espaço vazio
            "gravity": "center",
            "quality": "auto",
            "fetch_format": "auto"
        }

        # ATENÇÃO: Verifique se sua função upload_image aceita **kwargs ou um parametro 'transformation'
        # Se não aceitar, veja o Passo 1.1 abaixo.
        url = upload_image(
            file, 
            folder=f"restaurants/{restaurant_id}",
            transformation=transformations 
        )
        
    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(500, "Falha no upload da imagem.")

    await db.execute(
        text("UPDATE restaurants SET logo_url = :url, logo_updated_at = NOW() WHERE id = :rid"),
        {"url": url, "rid": restaurant_id}
    )
    await db.commit()

    return {"status": "success", "logo_url": url}

@router.get("/features/taxonomy", response_model=RestaurantFeaturesResponse)
async def get_features_taxonomy(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RestaurantFeaturesResponse:
    # Qualquer staff logado pode ler a taxonomia
    restaurant_id = int(staff["restaurant_id"])
    selections: dict[str, list[int]] = {"CUISINE_TYPE": [], "CUISINE_FEATURE": [], "SPACE_FEATURE": []}

    groups = (await db.execute(text("""
        SELECT id, code, name, max_select
        FROM feature_groups
        ORDER BY id
    """))).mappings().all()

    items = (await db.execute(text("""
        SELECT id, group_id, slug, name
        FROM features
        WHERE is_active = true
        ORDER BY group_id, name
    """))).mappings().all()

    # agrupa
    by_gid: dict[int, list[TaxItem]] = {}
    for it in items:
        by_gid.setdefault(int(it["group_id"]), []).append(
            TaxItem(id=int(it["id"]), slug=str(it["slug"]), name=str(it["name"]))
        )

    out_groups: list[TaxGroup] = []
    for g in groups:
        gid = int(g["id"])
        out_groups.append(
            TaxGroup(
                id=gid,
                code=str(g["code"]),
                name=str(g["name"]),
                max_select=(int(g["max_select"]) if g["max_select"] is not None else None),
                items=by_gid.get(gid, []),
            )
        )

    return RestaurantFeaturesResponse(restaurant_id=restaurant_id, selections=selections)


# ---------------------------
# GET seleção do restaurante
# ---------------------------

@router.get("/{restaurant_id}/features", response_model=RestaurantFeaturesResponse)
async def get_restaurant_features(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RestaurantFeaturesResponse:
    _require_can_manage_restaurant(staff, restaurant_id)

    rows = (await db.execute(text("""
        SELECT fg.code, rf.feature_id
        FROM restaurant_features rf
        JOIN features f ON f.id = rf.feature_id
        JOIN feature_groups fg ON fg.id = f.group_id
        WHERE rf.restaurant_id = :rid
        ORDER BY fg.code, rf.feature_id
    """), {"rid": restaurant_id})).mappings().all()

    selections: dict[str, list[int]] = {"CUISINE_TYPE": [], "CUISINE_FEATURE": [], "SPACE_FEATURE": []}
    for r in rows:
        code = str(r["code"])
        fid = int(r["feature_id"])
        selections.setdefault(code, []).append(fid)

    return RestaurantFeaturesResponse(restaurant_id=restaurant_id, selections=selections)


# ---------------------------
# PATCH (replace) seleção
# ---------------------------

@router.patch("/{restaurant_id}/features", response_model=RestaurantFeaturesUpdateResponse)
async def update_restaurant_features(
    restaurant_id: int,
    payload: RestaurantFeaturesUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
) -> RestaurantFeaturesUpdateResponse:
    _require_admin_role(staff)
    _require_can_manage_restaurant(staff, restaurant_id)

    # Normaliza: garante que existam chaves, remove duplicados
    selections: dict[str, list[int]] = {}
    for k, v in (payload.selections or {}).items():
        if v is None:
            continue
        selections[str(k)] = list(dict.fromkeys([int(x) for x in v]))  # unique preservando ordem

    cuisine_type_ids = selections.get("CUISINE_TYPE", [])
    cuisine_feature_ids = selections.get("CUISINE_FEATURE", [])
    space_feature_ids = selections.get("SPACE_FEATURE", [])

    # Busca max_select do grupo CUISINE_TYPE (ou usa 5)
    max_select = (await db.execute(text("""
        SELECT COALESCE(max_select, 5)::int
        FROM feature_groups
        WHERE code = 'CUISINE_TYPE'
    """))).scalar_one_or_none()
    max_select = int(max_select or 5)

    if len(cuisine_type_ids) > max_select:
        raise HTTPException(status_code=400, detail=f"CUISINE_TYPE max_select is {max_select}")

    # Valida se IDs pertencem ao grupo correto e estão ativos
    async def _validate_ids(group_code: str, ids: list[int]) -> None:
        if not ids:
            return
        ok = (await db.execute(text("""
            SELECT COUNT(*)::int
            FROM features f
            JOIN feature_groups fg ON fg.id = f.group_id
            WHERE fg.code = :code
              AND f.is_active = true
              AND f.id = ANY(:ids)
        """), {"code": group_code, "ids": ids})).scalar_one()
        if int(ok) != len(set(ids)):
            raise HTTPException(status_code=400, detail=f"Invalid feature ids for {group_code}")

    await _validate_ids("CUISINE_TYPE", cuisine_type_ids)
    await _validate_ids("CUISINE_FEATURE", cuisine_feature_ids)
    await _validate_ids("SPACE_FEATURE", space_feature_ids)

    # Replace: deleta tudo e reinsere as selections
    async with db.begin():
        await db.execute(
            text("DELETE FROM restaurant_features WHERE restaurant_id = :rid"),
            {"rid": restaurant_id},
        )

        # insere em lote via unnest
        def _insert_many(ids: list[int]) -> None:
            # helper só pra organização
            return None

        all_ids = cuisine_type_ids + cuisine_feature_ids + space_feature_ids
        if all_ids:
            await db.execute(text("""
                INSERT INTO restaurant_features (restaurant_id, feature_id)
                SELECT :rid, x
                FROM unnest(:ids::bigint[]) AS x
            """), {"rid": restaurant_id, "ids": all_ids})

    # Retorna seleção persistida (releitura)
    rows = (await db.execute(text("""
        SELECT fg.code, rf.feature_id
        FROM restaurant_features rf
        JOIN features f ON f.id = rf.feature_id
        JOIN feature_groups fg ON fg.id = f.group_id
        WHERE rf.restaurant_id = :rid
        ORDER BY fg.code, rf.feature_id
    """), {"rid": restaurant_id})).mappings().all()

    out: dict[str, list[int]] = {"CUISINE_TYPE": [], "CUISINE_FEATURE": [], "SPACE_FEATURE": []}
    for r in rows:
        out.setdefault(str(r["code"]), []).append(int(r["feature_id"]))

    return RestaurantFeaturesUpdateResponse(
        status="OK",
        restaurant_id=restaurant_id,
        selections=out,
    )