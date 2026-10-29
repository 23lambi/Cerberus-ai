# In-app updates: Settings → Updates (see cerberus/core/updates.py).

from fastapi import APIRouter, HTTPException

from cerberus.core import updates
from launcher.manager import LauncherError

router = APIRouter()


@router.get("/updates")
def update_status():
    return updates.status()


# Plain "def" routes: FastAPI runs them in a worker thread, so the network
# check doesn't block the server.
@router.post("/updates/check")
def check():
    try:
        return updates.check()
    except LauncherError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


@router.post("/updates/download")
def download():
    if not updates.start_download():
        raise HTTPException(status_code=409, detail="No update is ready to download. Check for updates first.")
    return updates.status()


@router.post("/updates/restart")
def restart():
    if not updates.restart():
        raise HTTPException(status_code=409, detail="The update is not installed yet.")
    return {"restarting": True}


@router.post("/updates/uninstall")
def uninstall():
    try:
        if not updates.uninstall():
            raise HTTPException(status_code=409, detail="Only the installed app can be uninstalled from here.")
    except LauncherError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    return {"closing": True}
