from fastapi import Depends, HTTPException, status


async def get_current_user_id() -> int:
    """
    Placeholder: substitua por JWT/OTP real.
    Para testes, você pode retornar um ID fixo (ex: 1) e criar esse user no banco.
    """
    user_id = 1
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id
