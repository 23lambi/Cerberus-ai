from fastapi import APIRouter

from cerberus import settings

router = APIRouter(prefix="/settings")


@router.get("")
def get_settings():
    return settings.get_all()


@router.put("")
def update_settings(values: dict[str, str]):
    settings.update(values)
    return settings.get_all()


@router.post("/reset")
def reset_settings():
    settings.reset()
    return settings.get_all()
