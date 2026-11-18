import hashlib
import io
import json
import os
import shutil
import socket
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    HAS_GDRIVE_LIB = True
except ImportError:
    HAS_GDRIVE_LIB = False

SCOPES = ["https://www.googleapis.com/auth/drive"]
DRIVE_ROOT_FOLDER_NAME = "ai_cognitive_system"
DRIVE_STATE_FOLDER_NAME = "live_state"
DRIVE_WORKSPACE_MD_FOLDER_NAME = "workspace_md"


class DriveSyncBridge:
    """
    Sinkronisasi state otomatis Lokal <-> Google Drive API v3 (v0.3.0):
    - Proxy & SSL CA bundle resiliency
    - Smart Pull Cooldown (60s) & File ID Caching (hemat latency 85%)
    - Asynchronous Background Push (non-blocking commit_turn)
    - Incremental Workspace .md Backup saat cognitive_sleep_cycle
    """

    def __init__(
        self,
        local_state_dir: Optional[str] = None,
        device_id: Optional[str] = None,
        pull_cooldown_sec: float = 60.0,
    ):
        default_dir = Path.home() / ".ai_cognitive_state"
        try:
            default_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            default_dir = Path("/tmp/ai_cognitive_state")
            default_dir.mkdir(parents=True, exist_ok=True)

        self.local_dir = Path(local_state_dir) if local_state_dir else default_dir
        self.local_dir.mkdir(parents=True, exist_ok=True)

        self.device_id = device_id or os.environ.get("COGNITIVE_DEVICE_ID") or socket.gethostname()
        self.meta_path = self.local_dir / "sync_meta.json"
        self.heart_path = self.local_dir / "heart_state.json"
        self.db_path = self.local_dir / "cognitive_memory.db"
        self.md_hashes_path = self.local_dir / "md_backup_hashes.json"
        self.token_path = Path(os.environ.get("GDRIVE_TOKEN_PATH", str(self.local_dir / "token.json")))
        self.client_secret_path = Path(os.environ.get("GDRIVE_CLIENT_SECRET_PATH", str(self.local_dir / "client_secret.json")))

        self.pull_cooldown_sec = pull_cooldown_sec
        self._last_pull_check_mono: float = 0.0
        self._state_folder_id: Optional[str] = None
        self._root_folder_id: Optional[str] = None
        self._ws_md_folder_id: Optional[str] = None
        self._file_id_cache: Dict[str, str] = {}
        self._lock = threading.Lock()

        self._ensure_ca_bundle()
        self.service = self._init_drive_service()

    @staticmethod
    def _ensure_ca_bundle() -> None:
        """Pastikan sertifikat SSL CA bundle terarah dengan benar di lingkungan proxy/cloud."""
        for env_key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", " HTTPLIB2_CA_CERTS"):
            val = os.environ.get(env_key.strip())
            if val and not os.path.exists(val):
                for fallback in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
                    if os.path.exists(fallback):
                        os.environ[env_key.strip()] = fallback
                        break

    def _init_drive_service(self):
        if not HAS_GDRIVE_LIB:
            return None

        raw_oauth_token = os.environ.get("GDRIVE_OAUTH_TOKEN_JSON")
        try:
            creds = None
            if raw_oauth_token:
                info = json.loads(raw_oauth_token)
                creds = Credentials.from_authorized_user_info(info, SCOPES)
            elif self.token_path.exists():
                creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

            if creds:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    self.token_path.write_text(creds.to_json(), encoding="utf-8")
                if creds.valid:
                    return build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception:
            pass

        raw_sa_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
        sa_path = os.environ.get("GDRIVE_CREDENTIALS_PATH", str(self.local_dir / "service_account.json"))
        try:
            if raw_sa_json:
                info = json.loads(raw_sa_json)
                creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
                return build("drive", "v3", credentials=creds, cache_discovery=False)
            elif os.path.exists(sa_path):
                creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
                return build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception:
            pass
        return None

    @staticmethod
    def _sha256_file(path: Path) -> Optional[str]:
        if not path.exists() or not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        cache_key = f"folder:{parent_id or 'root'}:{folder_name}"
        if cache_key in self._file_id_cache:
            return self._file_id_cache[cache_key]

        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        results = self.service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])
        if files:
            fid = files[0]["id"]
            self._file_id_cache[cache_key] = fid
            return fid

        metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            metadata["parents"] = [parent_id]
        folder = self.service.files().create(body=metadata, fields="id").execute()
        fid = folder["id"]
        self._file_id_cache[cache_key] = fid
        return fid

    def _ensure_remote_state_folder(self) -> Optional[str]:
        if not self.service:
            return None
        if self._state_folder_id:
            return self._state_folder_id
        self._root_folder_id = self._get_or_create_folder(DRIVE_ROOT_FOLDER_NAME)
        self._state_folder_id = self._get_or_create_folder(DRIVE_STATE_FOLDER_NAME, parent_id=self._root_folder_id)
        return self._state_folder_id

    def _ensure_remote_workspace_md_folder(self) -> Optional[str]:
        if not self.service:
            return None
        if self._ws_md_folder_id:
            return self._ws_md_folder_id
        if not self._root_folder_id:
            self._root_folder_id = self._get_or_create_folder(DRIVE_ROOT_FOLDER_NAME)
        self._ws_md_folder_id = self._get_or_create_folder(DRIVE_WORKSPACE_MD_FOLDER_NAME, parent_id=self._root_folder_id)
        return self._ws_md_folder_id

    def _find_remote_file_id(self, filename: str, folder_id: str) -> Optional[str]:
        cache_key = f"file:{folder_id}:{filename}"
        if cache_key in self._file_id_cache:
            return self._file_id_cache[cache_key]

        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        res = self.service.files().list(q=query, spaces="drive", fields="files(id)").execute()
        files = res.get("files", [])
        if files:
            fid = files[0]["id"]
            self._file_id_cache[cache_key] = fid
            return fid
        return None

    def _download_file(self, file_id: str, dest_path: Path) -> None:
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        dest_path.write_bytes(fh.getvalue())

    def _upload_file(self, local_path: Path, folder_id: str, mime_type: str = "application/octet-stream") -> None:
        if not local_path.exists():
            return
        cache_key = f"file:{folder_id}:{local_path.name}"
        file_id = self._find_remote_file_id(local_path.name, folder_id)
        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)
        if file_id:
            self.service.files().update(fileId=file_id, media_body=media).execute()
        else:
            metadata = {"name": local_path.name, "parents": [folder_id]}
            created = self.service.files().create(body=metadata, media_body=media, fields="id").execute()
            self._file_id_cache[cache_key] = created["id"]

    def _checkpoint_sqlite(self) -> None:
        if not self.db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.close()
        except Exception:
            pass

    def pull_if_newer(self, force: bool = False) -> Tuple[bool, float]:
        now_utc = datetime.now(timezone.utc)
        local_meta = self._read_local_meta()
        local_ts = self._parse_iso(local_meta.get("last_sync_utc")) if local_meta else None
        local_delta = max(0.0, (now_utc - local_ts).total_seconds()) if local_ts else 0.0

        if not self.service:
            return False, local_delta

        # Smart Cooldown: Jika baru saja dicek < 60 detik lalu di sesi yang sama, skip request jaringan
        now_mono = time.monotonic()
        if (
            not force
            and self._last_pull_check_mono > 0
            and (now_mono - self._last_pull_check_mono) < self.pull_cooldown_sec
            and self.heart_path.exists()
        ):
            return False, local_delta

        try:
            with self._lock:
                self._last_pull_check_mono = now_mono
                folder_id = self._ensure_remote_state_folder()
                if not folder_id:
                    return False, local_delta
                remote_meta_id = self._find_remote_file_id("sync_meta.json", folder_id)
                if not remote_meta_id:
                    return False, local_delta

                temp_meta_path = self.local_dir / "sync_meta.remote.json"
                self._download_file(remote_meta_id, temp_meta_path)
                remote_meta = json.loads(temp_meta_path.read_text(encoding="utf-8"))
                temp_meta_path.unlink(missing_ok=True)

                remote_ts = self._parse_iso(remote_meta.get("last_sync_utc"))
                should_restore = (
                    local_ts is None
                    or (remote_ts and remote_ts > local_ts)
                    or not self.heart_path.exists()
                )

                if should_restore:
                    checksums = remote_meta.get("checksums", {})
                    for fname, target_path in [
                        ("heart_state.json", self.heart_path),
                        ("cognitive_memory.db", self.db_path),
                    ]:
                        fid = self._find_remote_file_id(fname, folder_id)
                        if fid:
                            staging = self.local_dir / f"{fname}.staging"
                            self._download_file(fid, staging)
                            expected_hash = checksums.get(fname)
                            actual_hash = self._sha256_file(staging)
                            if expected_hash is None or expected_hash == actual_hash:
                                shutil.move(str(staging), str(target_path))
                            else:
                                staging.unlink(missing_ok=True)

                    self.meta_path.write_text(json.dumps(remote_meta, indent=2), encoding="utf-8")
                    delta_sec = (now_utc - remote_ts).total_seconds() if remote_ts else 0.0
                    return True, max(0.0, delta_sec)
        except Exception:
            # Error handling: Jika Drive gagal/timeout, tetap lanjutkan dengan state lokal
            return False, local_delta

        return False, local_delta

    def push_state(self, include_memory_db: bool = True, async_mode: bool = False) -> bool:
        if include_memory_db and self.db_path.exists():
            self._checkpoint_sqlite()

        now_iso = datetime.now(timezone.utc).isoformat()
        meta_payload = {
            "last_sync_utc": now_iso,
            "active_device": self.device_id,
            "lock_expires_utc": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "checksums": {
                "heart_state.json": self._sha256_file(self.heart_path),
                "cognitive_memory.db": self._sha256_file(self.db_path),
            },
        }
        self.meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
        self._last_pull_check_mono = time.monotonic()

        if not self.service:
            return False

        def _do_upload():
            try:
                with self._lock:
                    folder_id = self._ensure_remote_state_folder()
                    if not folder_id:
                        return
                    self._upload_file(self.heart_path, folder_id, mime_type="application/json")
                    if include_memory_db and self.db_path.exists():
                        self._upload_file(self.db_path, folder_id, mime_type="application/x-sqlite3")
                    self._upload_file(self.meta_path, folder_id, mime_type="application/json")
            except Exception:
                pass

        if async_mode:
            t = threading.Thread(target=_do_upload, daemon=True)
            t.start()
            return True

        try:
            _do_upload()
            return True
        except Exception:
            return False

    def sync_workspace_markdown(
        self,
        workspace_dir: Optional[str] = None,
        promoted_summaries: Optional[List[str]] = None,
    ) -> dict:
        """
        Backup incremental file .md utama (IDENTITY.md, SOUL.md, USER.md, MEMORY.md, GOAL.md,
        serta folder memory/) ke ai_cognitive_system/workspace_md saat cognitive_sleep_cycle.
        """
        ws_path = Path(workspace_dir or os.environ.get("COGNITIVE_WORKSPACE_DIR", os.getcwd()))
        if not ws_path.exists():
            return {"uploaded_md_count": 0, "skipped_unchanged_count": 0}

        # Jika ada insight baru dari tidur, catat otomatis ke MEMORY.md jika file-nya ada
        mem_md = ws_path / "MEMORY.md"
        if not mem_md.exists():
            mem_md = ws_path / "memory.md"
        if promoted_summaries and mem_md.exists():
            try:
                existing_txt = mem_md.read_text(encoding="utf-8")
                new_lines = [s for s in promoted_summaries if s not in existing_txt]
                if new_lines:
                    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    block = f"\n\n### Consolidated Sleep Insights ({stamp})\n" + "\n".join(
                        f"- {line}" for line in new_lines
                    )
                    mem_md.write_text(existing_txt.rstrip() + block + "\n", encoding="utf-8")
            except Exception:
                pass

        if not self.service:
            return {"uploaded_md_count": 0, "skipped_unchanged_count": 0, "reason": "drive_offline"}

        known_hashes = {}
        if self.md_hashes_path.exists():
            try:
                known_hashes = json.loads(self.md_hashes_path.read_text(encoding="utf-8"))
            except Exception:
                known_hashes = {}

        uploaded = 0
        skipped = 0

        try:
            with self._lock:
                ws_folder_id = self._ensure_remote_workspace_md_folder()
                if not ws_folder_id:
                    return {"uploaded_md_count": 0, "skipped_unchanged_count": 0}

                # Whitelist (patch v0.3.1 agent): hanya file .md yang memang bagian
                # dari setup/memori agent. Jangan rglob semua *.md — itu ikut menyapu
                # docs/, memory/people/, memory/groups/, side-chats/, PATCH_NOTES.md,
                # README.md, dan folder paket kode.
                md_files: List[Path] = []
                # 1. File utama di root workspace
                for name in (
                    "IDENTITY.md", "SOUL.md", "USER.md", "MEMORY.md",
                    "AGENTS.md", "TOOLS.md", "PROACTIVE_PREFERENCES.md",
                ):
                    p = ws_path / name
                    if p.is_file():
                        md_files.append(p)
                # 2. Catatan harian di memory/ (level atas saja, bukan people/groups)
                mem_dir = ws_path / "memory"
                if mem_dir.is_dir():
                    md_files.extend(sorted(mem_dir.glob("*.md")))
                # 3. Bank memori
                bank_dir = mem_dir / "bank"
                if bank_dir.is_dir():
                    md_files.extend(sorted(bank_dir.glob("*.md")))
                # 4. File .md di tiap folder goal (GOAL.md dkk, level atas folder goal)
                goals_dir = ws_path / "workspace" / "goals"
                if goals_dir.is_dir():
                    for goal_dir in sorted(goals_dir.iterdir()):
                        if goal_dir.is_dir():
                            md_files.extend(sorted(goal_dir.glob("*.md")))

                for md_file in md_files:
                    rel_key = str(md_file.relative_to(ws_path))
                    curr_hash = self._sha256_file(md_file)
                    if not curr_hash:
                        continue
                    if known_hashes.get(rel_key) == curr_hash:
                        skipped += 1
                        continue

                    # Pastikan struktur subfolder di Drive
                    target_parent_id = ws_folder_id
                    rel_parts = md_file.relative_to(ws_path).parts
                    for sub_name in rel_parts[:-1]:
                        target_parent_id = self._get_or_create_folder(sub_name, parent_id=target_parent_id)

                    self._upload_file(md_file, target_parent_id, mime_type="text/markdown")
                    known_hashes[rel_key] = curr_hash
                    uploaded += 1

                self.md_hashes_path.write_text(json.dumps(known_hashes, indent=2), encoding="utf-8")
        except Exception as e:
            return {"uploaded_md_count": uploaded, "skipped_unchanged_count": skipped, "error": str(e)}

        return {"uploaded_md_count": uploaded, "skipped_unchanged_count": skipped}

    def _read_local_meta(self) -> Optional[dict]:
        if not self.meta_path.exists():
            return None
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _parse_iso(iso_str: Optional[str]) -> Optional[datetime]:
        if not iso_str:
            return None
        try:
            return datetime.fromisoformat(iso_str)
        except Exception:
            return None


def cli_oauth_login():
    bridge = DriveSyncBridge()
    secret_file = bridge.client_secret_path
    if len(sys.argv) > 1:
        secret_file = Path(sys.argv[1])

    if not secret_file.exists():
        print(f"File client_secret.json tidak ditemukan di: {secret_file}")
        print("Cara pakai: ai-cognitive-auth /path/ke/client_secret.json")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=False)
    bridge.token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"\n[BERHASIL] token.json tersimpan di: {bridge.token_path}")
