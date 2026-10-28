"""Download a consistent database snapshot and the original document files."""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from cerberus import database

router = APIRouter()


@router.get("/backup")
def backup():
    folder = tempfile.TemporaryDirectory(prefix="cerberus-backup-")
    root = Path(folder.name)
    try:
        documents = database.snapshot(root / "cerberus.db")
        with ZipFile(root / "backup.zip", "w", ZIP_DEFLATED) as archive:
            archive.write(root / "cerberus.db", "cerberus.db")
            manifest = []
            for doc in documents:
                if not doc["path"]:
                    continue  # workspace content and versions are in the snapshot
                path = Path(doc["path"])
                if not path.is_file():
                    raise HTTPException(409, "A document file is missing or changed during backup. Check your documents and try again.")
                member = f"documents/{doc['id']}_{path.name}"
                archive.write(path, member)
                manifest.append({"id": doc["id"], "original_path": str(path), "archive_path": member})
            archive.writestr("documents.json", json.dumps(manifest, indent=2))
            archive.writestr("RESTORE.txt", """Cerberus backup

This archive includes private conversations, settings, images and documents.
Editable Markdown documents, version history and edit proposals are stored
inside cerberus.db. Only original uploaded files need separate copying.

To restore on the same computer:
1. Stop Cerberus. Keep a copy of your current database and documents.
2. Replace cerberus.db in your Cerberus data folder (Settings > Your data
   shows where it is) with this database.
   Delete cerberus.db-wal and cerberus.db-shm there too, if they exist:
   they belong to the old database.
3. Read documents.json. Copy each archive_path file to its original_path
   (relative paths are relative to that same data folder).
4. Start Cerberus with one server worker.

On another computer, use the same data-folder-relative document paths. If an
original_path is absolute, update that document's path in the restored
database to its new location before starting the app.

Ollama models and application code are not included in this backup.
""")
        return FileResponse(root / "backup.zip", media_type="application/zip",
                            filename=f"cerberus-backup-{datetime.now():%Y%m%d-%H%M%S}.zip",
                            background=BackgroundTask(folder.cleanup))
    except BaseException:
        folder.cleanup()
        raise
