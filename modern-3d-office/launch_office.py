#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modern 3D Virtual Executive Office - Backend & AI Video Production Hub (V4)
Hỗ trợ:
- API /api/generate-script: Tạo & Tinh chỉnh kịch bản bằng Model cao nhất (Gemini 2.5 Pro / 3.8 Flash)
- Kịch bản và prompt ảnh/video theo từng phân cảnh
- Tạo ảnh và clip AI bằng Google API, ghép giọng Gemini và phụ đề
- 2 Phong cách: Flow Google API và Whiteboard
- Streaming video chuẩn HTTP 206 Partial Content
"""

import sys
import os
MPT_SITE_PACKAGES = r"C:\Users\Admin\.gemini\antigravity\scratch\MoneyPrinterTurbo\.venv\Lib\site-packages"
if MPT_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, MPT_SITE_PACKAGES)
import json
import uuid
import time
import shutil
import re
import threading
import urllib.parse
import http.server
import socketserver
import logging
from pathlib import Path
import requests

if sys.platform == "win32":
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        elif hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        elif hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PORT = int(os.environ.get("PORT", 8550))
OFFICE_DIR = Path(__file__).resolve().parent
_env_mpt = os.environ.get("MPT_ROOT")
if _env_mpt and Path(_env_mpt).is_dir():
    MPT_ROOT = Path(_env_mpt).resolve()
elif (OFFICE_DIR.parent / "MoneyPrinterTurbo").is_dir():
    MPT_ROOT = (OFFICE_DIR.parent / "MoneyPrinterTurbo").resolve()
else:
    MPT_ROOT = Path("C:/Users/Admin/.gemini/antigravity/scratch/MoneyPrinterTurbo").resolve()

_env_wb = os.environ.get("SKILL_WB_ROOT")
if _env_wb and Path(_env_wb).is_dir():
    SKILL_WB_ROOT = Path(_env_wb).resolve()
elif (OFFICE_DIR / "srt-whiteboard-animation").is_dir():
    SKILL_WB_ROOT = (OFFICE_DIR / "srt-whiteboard-animation").resolve()
elif (OFFICE_DIR.parent / "srt-whiteboard-animation").is_dir():
    SKILL_WB_ROOT = (OFFICE_DIR.parent / "srt-whiteboard-animation").resolve()
else:
    SKILL_WB_ROOT = Path("C:/Users/Admin/.gemini/config/skills/srt-whiteboard-animation").resolve()
EXPORT_DIR = MPT_ROOT / "storage" / "export_ready"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
MPT_API_BASE = "http://127.0.0.1:8080/api/v1"

# Import helper
MPT_SITE_PACKAGES = r"C:\Users\Admin\.gemini\antigravity\scratch\MoneyPrinterTurbo\.venv\Lib\site-packages"
if MPT_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, MPT_SITE_PACKAGES)
sys.path.insert(0, str(MPT_ROOT))
sys.path.insert(0, str(OFFICE_DIR))
try:
    from whiteboard_engine import produce_whiteboard_video
except ImportError:
    produce_whiteboard_video = None

# Flow Engine: Prompt -> ảnh Nano Banana -> video Google API
sys.path.insert(0, str(OFFICE_DIR))
import flow_engine
from storyboard import generate_storyboard, normalize_scene_plan
from flow_compositor import compose_flow_video, prepare_flow_narration
from studio_cancel import (CancelToken, StudioCancelled, cancellation_scope,
                           check_cancelled, cancellable_call, wait_cancelled)
FLOW_DIR = EXPORT_DIR / "flow_assets"
FLOW_DIR.mkdir(parents=True, exist_ok=True)

UPDATE_PROGRESS = {
    "is_updating": False,
    "percent": 0,
    "phase": "idle",
    "message": "",
    "completed": False,
    "error": ""
}

def run_system_update(download_url: str):
    global UPDATE_PROGRESS
    UPDATE_PROGRESS["is_updating"] = True
    UPDATE_PROGRESS["percent"] = 10
    UPDATE_PROGRESS["phase"] = "connecting"
    UPDATE_PROGRESS["message"] = "Đang kết nối tới máy chủ cập nhật..."
    UPDATE_PROGRESS["completed"] = False
    UPDATE_PROGRESS["error"] = ""

    try:
        import tempfile
        import zipfile
        
        if not download_url:
            time.sleep(1)
            UPDATE_PROGRESS["percent"] = 50
            UPDATE_PROGRESS["phase"] = "verifying"
            UPDATE_PROGRESS["message"] = "Đang xác thực hệ thống..."
            time.sleep(1)
            UPDATE_PROGRESS["percent"] = 100
            UPDATE_PROGRESS["phase"] = "completed"
            UPDATE_PROGRESS["message"] = "Hệ thống đã đồng bộ toàn bộ tệp mới nhất!"
            UPDATE_PROGRESS["completed"] = True
            UPDATE_PROGRESS["is_updating"] = False
            return

        UPDATE_PROGRESS["phase"] = "downloading"
        UPDATE_PROGRESS["percent"] = 15
        UPDATE_PROGRESS["message"] = "Đang tải gói cập nhật về máy..."
        
        with requests.get(download_url, stream=True, timeout=60) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Máy chủ trả về HTTP {r.status_code}")
            
            total_length = r.headers.get('content-length')
            total_bytes = int(total_length) if total_length and total_length.isdigit() else 0
            downloaded = 0
            
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        tmp.write(chunk)
                        downloaded += len(chunk)
                        if total_bytes > 0:
                            pct = int(15 + (downloaded / total_bytes) * 70)
                            UPDATE_PROGRESS["percent"] = min(85, pct)
                            mb_down = downloaded / (1024 * 1024)
                            mb_total = total_bytes / (1024 * 1024)
                            UPDATE_PROGRESS["message"] = f"Đang tải bản cập nhật: {mb_down:.1f} MB / {mb_total:.1f} MB ({pct}%)"
                        else:
                            UPDATE_PROGRESS["percent"] = 50
                            UPDATE_PROGRESS["message"] = f"Đang tải: {downloaded / (1024 * 1024):.1f} MB"
                            
        UPDATE_PROGRESS["phase"] = "extracting"
        UPDATE_PROGRESS["percent"] = 90
        UPDATE_PROGRESS["message"] = "Đang cài đặt và cập nhật các tệp ứng dụng..."
        
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            for member in zf.infolist():
                fname = member.filename.lower()
                if "config.toml" in fname or ".env" in fname or "storage/" in fname or "export_ready" in fname:
                    continue
                zf.extract(member, OFFICE_DIR)
                
        tmp_path.unlink(missing_ok=True)
        
        UPDATE_PROGRESS["percent"] = 100
        UPDATE_PROGRESS["phase"] = "completed"
        UPDATE_PROGRESS["message"] = "Cập nhật thành công! Đang tải lại ứng dụng..."
        UPDATE_PROGRESS["completed"] = True
        UPDATE_PROGRESS["is_updating"] = False
        
    except Exception as e:
        logger.error("Lỗi cập nhật tự động: %s", e)
        UPDATE_PROGRESS["is_updating"] = False
        UPDATE_PROGRESS["error"] = str(e)
        UPDATE_PROGRESS["phase"] = "failed"
        UPDATE_PROGRESS["message"] = f"Lỗi cập nhật: {str(e)}"

JOBS = {}
JOB_LOCK = threading.RLock()
CANCEL_TOKENS = {}
REQUEST_JOBS = {}
EARLY_CANCELLED = {}
logger = logging.getLogger(__name__)
EXPORT_LOCK = threading.RLock()


def validate_request_id(value, allow_empty=True):
    if value in (None, "") and allow_empty:
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("Mã yêu cầu không hợp lệ.")
    return value


def register_job(job_id, kind, subject, request_id=""):
    request_id = validate_request_id(request_id) or job_id
    with JOB_LOCK:
        existing_id = REQUEST_JOBS.get(request_id)
        if existing_id in JOBS:
            existing = JOBS[existing_id]
            if existing.get("kind", "video") != kind:
                raise ValueError("Mã yêu cầu đã được sử dụng cho tác vụ khác.")
            return existing, CANCEL_TOKENS.setdefault(existing_id, CancelToken(request_id)), False
        cutoff = time.time() - 3600
        for key, created in list(EARLY_CANCELLED.items()):
            if created < cutoff:
                EARLY_CANCELLED.pop(key, None)
        token = CancelToken(request_id)
        cancelled = request_id in EARLY_CANCELLED
        if cancelled:
            token.cancel()
        job = {
            "job_id": job_id, "request_id": request_id, "kind": kind,
            "subject": subject, "state": "cancelled" if cancelled else "queued",
            "phase": "cancelled" if cancelled else "queued", "progress": 0 if kind == "script" else 5,
            "phase_text": "Đã dừng theo yêu cầu." if cancelled else "Đã tiếp nhận yêu cầu...",
            "created_at": time.time(),
            "started_at": time.time(),
            "audio_status": {"status": "idle", "detail": "Chưa bắt đầu"},
            "visual_status": {"status": "idle", "detail": "Chưa bắt đầu"},
            "compose_status": {"status": "idle", "detail": "Chờ hậu kỳ"},
        }
        JOBS[job_id] = job
        CANCEL_TOKENS[job_id] = token
        REQUEST_JOBS[request_id] = job_id
        return job, token, True


def cancel_studio_job(job_id="", request_id=""):
    try:
        job_id = validate_request_id(job_id)
        request_id = validate_request_id(request_id)
    except ValueError as error:
        return 400, {"error": str(error)}
    if not job_id and not request_id:
        return 400, {"error": "Chưa có mã tác vụ cần dừng."}
    with JOB_LOCK:
        mapped = REQUEST_JOBS.get(request_id) if request_id else None
        if mapped and job_id and mapped != job_id:
            return 400, {"error": "Mã tác vụ không khớp mã yêu cầu cần dừng."}
        key = job_id or mapped
        job = JOBS.get(key)
        if job is None:
            if request_id:
                EARLY_CANCELLED[request_id] = time.time()
                return 200, {"status": "cancelled", "state": "cancelled", "request_id": request_id}
            return 404, {"error": "Không tìm thấy tác vụ cần dừng."}
        if request_id and job.get("request_id") and request_id != job["request_id"]:
            return 400, {"error": "Mã yêu cầu không khớp tác vụ cần dừng."}
        if job.get("state") not in ("completed", "failed", "cancelled"):
            previous_state = job.get("state")
            CANCEL_TOKENS.setdefault(key, CancelToken(job.get("request_id", key))).cancel()
            job.update(state="cancelled" if previous_state == "queued" else "cancelling",
                       cancel_requested=True, phase_text="Đã dừng theo yêu cầu." if previous_state == "queued" else "Đang dừng tác vụ...",
                       cancel_requested_at=time.time())
            if previous_state == "queued":
                job.update(phase="cancelled", finished_at=time.time())
        return 200, {"status": job["state"], "state": job["state"], "job": dict(job),
                     "job_id": job["job_id"], "request_id": job.get("request_id", "")}


def _update_job(job, **values):
    with JOB_LOCK:
        check_cancelled()
        if job.get("state") in ("cancelling", "cancelled"):
            raise StudioCancelled("Tác vụ đã được dừng theo yêu cầu.")
        job.update(**values)


def _mark_cancelled(job):
    with JOB_LOCK:
        if job.get("state") != "completed":
            job.update(state="cancelled", phase="cancelled", phase_text="Đã dừng tác vụ. Bản nháp được giữ lại.",
                       finished_at=time.time())
            job.pop("error", None)


def cancellable_job(worker):
    def run(job_id, brief):
        with JOB_LOCK:
            token = CANCEL_TOKENS.setdefault(job_id, CancelToken(JOBS[job_id].get("request_id", job_id)))
        with cancellation_scope(token):
            try:
                check_cancelled()
                worker(job_id, brief)
            except StudioCancelled:
                _mark_cancelled(JOBS[job_id])
    return run


def publish_video_result(job, result, staged_path, phase_text):
    result = dict(result)
    result.pop("_staged_video_path", None)
    filename = result.get("video_filename", "")
    if not filename or Path(filename).name != filename:
        raise ValueError("Tên video kết quả không hợp lệ.")
    destination = EXPORT_DIR / filename
    metadata_path = EXPORT_DIR / f"{destination.stem}_metadata.json"
    with JOB_LOCK, EXPORT_LOCK:
        check_cancelled()
        if job.get("state") in ("cancelled", "cancelling"):
            raise StudioCancelled("Tác vụ đã được dừng theo yêu cầu.")
        staged_path = Path(staged_path)
        if not staged_path.is_file() or not staged_path.stat().st_size:
            raise RuntimeError("Chưa có video hoàn chỉnh để xuất.")
        if destination.exists() and destination.resolve() != staged_path.resolve():
            raise RuntimeError("Tên video kết quả đã tồn tại; không ghi đè video khác.")
        if destination.resolve() != staged_path.resolve():
            shutil.move(str(staged_path), str(destination))
        try:
            metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # This is the newly produced file, never a pre-existing export.
            destination.unlink(missing_ok=True)
            raise
        job.update(state="completed", phase="completed", progress=100, phase_text=phase_text,
                   finished_at=time.time(), video_url=result["video_url"], result=result,
                   compose_status={"status": "completed", "detail": "Hoàn tất video!"})
        if job.get("auto_shutdown"):
            logger.info("Auto shutdown enabled. Scheduling Windows shutdown in 120 seconds...")
            try:
                os.system('shutdown /s /t 120 /c "Tuấn Blogger Studio: Video đã xuất thành công! Máy tính sẽ tự động tắt sau 2 phút. Để hủy tắt máy, mở cmd gõ: shutdown /a"')
            except Exception as se:
                logger.warning("Could not execute shutdown: %s", se)
    return result


class VideoInUseError(PermissionError):
    pass


def read_deleted_videos():
    registry = EXPORT_DIR / ".studio-state" / "deleted-videos.json"
    if not registry.exists():
        return {"filenames": [], "task_ids": []}
    data = json.loads(registry.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(
        not isinstance(data.get(key), list) or not all(isinstance(value, str) for value in data[key])
        for key in ("filenames", "task_ids")
    ):
        raise ValueError("Danh sách video đã xóa không hợp lệ.")
    return data


def write_deleted_videos(data):
    state_dir = EXPORT_DIR / ".studio-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    registry = state_dir / "deleted-videos.json"
    pending = state_dir / f"{uuid.uuid4().hex}.tmp"
    try:
        pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(registry)
    finally:
        pending.unlink(missing_ok=True)


def delete_exported_video(filename):
    if not isinstance(filename, str):
        raise ValueError("Tên video không hợp lệ.")
    filename = urllib.parse.unquote(filename)
    if not filename or filename != Path(filename).name or Path(filename).suffix.lower() != ".mp4":
        raise ValueError("Vui lòng chọn đúng tên video MP4 cần xóa.")
    with EXPORT_LOCK:
        video_file = EXPORT_DIR / filename
        metadata_file = EXPORT_DIR / f"{video_file.stem}_metadata.json"
        previous = read_deleted_videos()
        updated = {key: list(values) for key, values in previous.items()}
        updated["filenames"] = sorted(set(updated["filenames"]) | {filename})
        if metadata_file.is_file():
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8-sig"))
                task_id = metadata.get("source_task_id") if isinstance(metadata, dict) else None
                if isinstance(task_id, str) and task_id:
                    updated["task_ids"] = sorted(set(updated["task_ids"]) | {task_id})
            except (ValueError, TypeError):
                pass
        # Persist the deletion before unlinking so a later sync cannot restore it.
        write_deleted_videos(updated)
        existed = video_file.exists()
        try:
            video_file.unlink(missing_ok=True)
        except PermissionError as e:
            write_deleted_videos(previous)
            raise VideoInUseError("Video is still in use") from e
        except OSError:
            # A locked video must keep its metadata and remain visible for retry.
            write_deleted_videos(previous)
            raise
        metadata_file.unlink(missing_ok=True)
        return {"filename": filename, "already_deleted": not existed}

def get_gemini_key():
    config_file = MPT_ROOT / "config.toml"
    if config_file.exists():
        c = config_file.read_text(encoding="utf-8")
        m = re.search(r'gemini_api_key\s*=\s*"([^"]+)"', c)
        if m:
            return m.group(1)
    return os.environ.get("GEMINI_API_KEY", "")

def mask_api_key(k: str) -> str:
    k = (k or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "***"
    return k[:4] + "..." + k[-4:]

def read_system_keys():
    config_file = MPT_ROOT / "config.toml"
    gemini_key = ""
    eleven_keys = []
    if config_file.exists():
        try:
            import tomllib
            with open(config_file, "rb") as f:
                data = tomllib.load(f)
            gemini_key = data.get("app", {}).get("gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
            eleven_cfg = data.get("elevenlabs", {})
            eleven_keys = eleven_cfg.get("api_keys", [])
            if not eleven_keys and eleven_cfg.get("api_key"):
                eleven_keys = [eleven_cfg.get("api_key")]
        except Exception as e:
            logger.error("Lỗi đọc config.toml: %s", e)
    if not gemini_key:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
    return {
        "gemini_api_key": gemini_key,
        "gemini_masked": mask_api_key(gemini_key),
        "elevenlabs_api_keys": [str(k) for k in eleven_keys if str(k).strip()],
        "elevenlabs_masked": [mask_api_key(str(k)) for k in eleven_keys if str(k).strip()],
        "has_gemini": bool(gemini_key.strip()),
        "has_elevenlabs": bool(eleven_keys)
    }

def update_system_keys(gemini_key: str = None, eleven_keys: list = None):
    config_file = MPT_ROOT / "config.toml"
    if not config_file.exists():
        return False
    content = config_file.read_text(encoding="utf-8")
    
    if gemini_key is not None:
        gemini_key = gemini_key.strip()
        os.environ["GEMINI_API_KEY"] = gemini_key
        if re.search(r'gemini_api_key\s*=\s*"[^"]*"', content):
            content = re.sub(r'gemini_api_key\s*=\s*"[^"]*"', f'gemini_api_key = "{gemini_key}"', content)
        else:
            content = re.sub(r'(\[app\]\s*)', f'\\1gemini_api_key = "{gemini_key}"\n', content)
            
    if eleven_keys is not None:
        valid_keys = [str(k).strip() for k in eleven_keys if str(k).strip()]
        keys_str = json.dumps(valid_keys)
        first_key = valid_keys[0] if valid_keys else ""
        os.environ["ELEVENLABS_API_KEY"] = first_key
        os.environ["ELEVENLABS_API_KEYS"] = ",".join(valid_keys)
        if re.search(r'api_keys\s*=\s*\[[^\]]*\]', content):
            content = re.sub(r'api_keys\s*=\s*\[[^\]]*\]', f'api_keys = {keys_str}', content)
        elif "[elevenlabs]" in content:
            content = re.sub(r'(\[elevenlabs\]\s*)', f'\\1api_keys = {keys_str}\n', content)
        if re.search(r'(\[elevenlabs\][\s\S]*?api_key\s*=\s*)"[^"]*"', content):
            content = re.sub(r'(\[elevenlabs\][\s\S]*?api_key\s*=\s*)"[^"]*"', f'\\1"{first_key}"', content)
        try:
            from app.config import config
            config.elevenlabs["api_key"] = first_key
            config.elevenlabs["api_keys"] = valid_keys
        except Exception:
            pass
            
    config_file.write_text(content, encoding="utf-8")
    return True

def cleanup_old_videos(max_age_days: int = 3):
    """Tự động xóa video và metadata cũ hơn 3 ngày để giải phóng dung lượng ổ cứng"""
    cutoff = time.time() - (max_age_days * 86400)
    cleaned = 0
    for f in list(EXPORT_DIR.glob("*")):
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink(missing_ok=True)
                cleaned += 1
            except Exception:
                pass
    if cleaned > 0:
        print(f"[Cleanup] Đã tự động dọn dẹp {cleaned} tệp video & metadata cũ hơn {max_age_days} ngày.")

def sync_tasks_to_export():
    """Tự động đồng bộ các video đã hoàn thành trong MoneyPrinterTurbo storage/tasks sang export_ready"""
    with EXPORT_LOCK:
        try:
            deleted = read_deleted_videos()
            tasks_dir = MPT_ROOT / "storage" / "tasks"
            if not tasks_dir.exists():
                return
            exported_tasks = set()
            for metadata_file in EXPORT_DIR.glob("*_metadata.json"):
                try:
                    metadata = json.loads(metadata_file.read_text(encoding="utf-8-sig"))
                    if not isinstance(metadata, dict):
                        continue
                    if metadata.get("source_task_id") and (EXPORT_DIR / Path(metadata.get("video_filename", "")).name).is_file():
                        exported_tasks.add(metadata["source_task_id"])
                except (OSError, ValueError, TypeError):
                    continue
            for tdir in tasks_dir.iterdir():
                if not tdir.is_dir():
                    continue
                tid = tdir.name
                out_video = EXPORT_DIR / f"video_{tid[:8]}.mp4"
                if out_video.name in deleted["filenames"] or tid in deleted["task_ids"] or tid in exported_tasks:
                    continue
                mp4s = sorted(tdir.glob("final-*.mp4"))
                if not mp4s:
                    continue
                out_meta = EXPORT_DIR / f"video_{tid[:8]}_metadata.json"
                if not out_video.exists():
                    shutil.copy2(mp4s[0], out_video)
                if not out_meta.exists():
                    sub_name = f"Video AI ({tid[:8]})"
                    meta_data = {
                        "subject": sub_name,
                        "style": "footage_broll",
                        "aspect": "9:16",
                        "voice": "Giọng đọc AI",
                        "source_task_id": tid,
                        "video_filename": out_video.name,
                        "video_url": f"/export_ready/{out_video.name}",
                        "script": "",
                        "titles": [sub_name],
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(out_video.stat().st_mtime))
                    }
                    out_meta.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"sync_tasks_to_export warning: {e}")


def recent_videos():
    with EXPORT_LOCK:
        sync_tasks_to_export()
        cleanup_old_videos(max_age_days=3)
        deleted = read_deleted_videos()
        recent = []
        for metadata_file in sorted(EXPORT_DIR.glob("*_metadata.json"), key=os.path.getmtime, reverse=True)[:30]:
            try:
                data = json.loads(metadata_file.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    continue
                filename = data.get("video_filename")
                if filename and filename not in deleted["filenames"] and data.get("source_task_id") not in deleted["task_ids"] and (EXPORT_DIR / filename).is_file():
                    data["video_url"] = f"/export_ready/{filename}"
                    data["download_url"] = f"/api/download?file={urllib.parse.quote(filename)}"
                    if not data.get("thumbnails"):
                        try:
                            from thumbnail_generator import generate_youtube_thumbnails
                            data["thumbnails"] = generate_youtube_thumbnails(
                                subject=data.get("subject") or filename,
                                titles=data.get("titles", []),
                                script=data.get("script", ""),
                                export_dir=EXPORT_DIR,
                                task_id=Path(filename).stem
                            )
                            metadata_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception:
                            pass
                    recent.append(data)
            except (OSError, ValueError, TypeError):
                continue
        return recent





def slugify(text: str) -> str:
    """Chuyển tiếng Việt có dấu thành không dấu an toàn tuyệt đối cho URL và Web Browser"""
    patterns = {
        r'[àáạảãâầấậẩẫăằắặẳẵ]': 'a',
        r'[èéẹẻẽêềếệểễ]': 'e',
        r'[ìíịỉĩ]': 'i',
        r'[òóọỏõôồốộổỗơờớợởỡ]': 'o',
        r'[ùúụủũưừứựửữ]': 'u',
        r'[ỳýỵỷỹ]': 'y',
        r'[đ]': 'd',
        r'[ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴ]': 'A',
        r'[ÈÉẸẺẼÊỀẾỆỂỄ]': 'E',
        r'[ÌÍỊỈĨ]': 'I',
        r'[ÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠ]': 'O',
        r'[ÙÚỤỦŨƯỪỨỰỬỮ]': 'U',
        r'[ỲÝỴỶỸ]': 'Y',
        r'[Đ]': 'D'
    }
    for regex, replace in patterns.items():
        text = re.sub(regex, replace, text)
    text = re.sub(r'[^a-zA-Z0-9_\- ]', '', text)
    text = re.sub(r'\s+', '_', text).strip('_')
    return text[:45] or "video"

def map_model(m: str) -> str:
    m_clean = (m or "").strip().lower()
    # gemini-3.1-flash-lite & gemini-3.1-flash-lite-preview là 2 model có quota 200 OK cao nhất và phản hồi tức thì
    if "preview" in m_clean or "3.8" in m_clean or "3.6" in m_clean:
        return "gemini-3.1-flash-lite-preview"
    return "gemini-3.1-flash-lite"

def call_gemini(model_name: str, prompt: str) -> str:
    check_cancelled()
    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError("Chưa cấu hình Gemini API key cho chức năng tạo kịch bản.")
    primary = map_model(model_name)
    fallback_chain = [primary, "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview", "gemini-3.5-flash-lite", "gemini-3.8-flash-lite-tts"]
    seen = set()
    candidate_models = []
    for m in fallback_chain:
        if m and m not in seen:
            candidate_models.append(m)
            seen.add(m)

    last_err = None
    for attempt in range(2):
        for candidate in candidate_models:
            check_cancelled()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate}:generateContent"
            try:
                resp = cancellable_call(requests.post,
                    url,
                    headers={"x-goog-api-key": api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "maxOutputTokens": 16384,
                        }
                    },
                    timeout=(10, 90)
                )
            except StudioCancelled:
                raise
            except Exception as e:
                last_err = f"{candidate}: {type(e).__name__}"
                continue
            if resp.status_code != 200:
                last_err = f"{candidate} HTTP {resp.status_code}"
                continue
            try:
                payload = resp.json()
            except ValueError:
                last_err = f"{candidate}: invalid JSON response"
                continue
            candidates = payload.get("candidates") if isinstance(payload, dict) else None
            if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
                raise RuntimeError("Gemini chưa trả về nội dung cho kịch bản. Phản hồi trống hoặc yêu cầu bị chặn.")
            generated = candidates[0]
            reason = str(generated.get("finishReason") or "").upper()
            # Never pass truncated JSON to the planner or resubmit the entire
            # long request across fallback models. The planner can split it.
            if reason in ("MAX_TOKENS", "CONTINUATION"):
                raise RuntimeError(
                    "Phản hồi Gemini đã chạm giới hạn đầu ra và chưa hoàn tất. "
                    "Cần chia kịch bản thành các phần nhỏ hơn; bản bị cắt chưa được sử dụng."
                )
            if reason and reason != "STOP":
                raise RuntimeError("Gemini chưa hoàn tất nội dung kịch bản. Bản phản hồi chưa được sử dụng.")
            content = generated.get("content")
            parts = content.get("parts", []) if isinstance(content, dict) else []
            raw = "".join(
                part["text"] for part in parts
                if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str)
            ).strip()
            if not raw:
                raise RuntimeError("Gemini chưa trả về lời đọc hoặc phân cảnh trong phản hồi.")
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            return raw
        wait_cancelled(0.4)
    raise RuntimeError(f"Tất cả mô hình đều bận: {last_err}")

def generate_script_and_terms(subject: str, duration_sec: int, tone: str, cta: str, model_name: str,
                              feedback: str = "", current_script: str = "", current_scenes=None,
                              aspect: str = "16:9", style: str = "whiteboard", voice_name: str = "",
                              resume_narration: bool = False) -> dict:
    api_key = get_gemini_key()
    if not api_key:
        logger.info("Chưa cấu hình Gemini API Key - Tự động kích hoạt bộ tạo kịch bản & phân cảnh Offline miễn phí")
        clean_sub = str(subject or "").strip() or "Khám phá video kiến thức"
        clean_cta = str(cta or "").strip() or "Hãy bấm theo dõi kênh và để lại ý kiến thảo luận bên dưới nhé"
        if not current_script:
            current_script = (
                f"[tự hào] Chào mừng các bạn đến với chủ đề: {clean_sub}! "
                f"[kịch tính] Hôm nay chúng ta sẽ cùng khám phá những điểm đặc biệt và giá trị nhất về {clean_sub} mà bạn không nên bỏ lỡ. "
                f"[thì thầm] Đây chính là chìa khóa giúp bạn thấu hiểu vấn đề một cách dễ dàng, nhanh chóng và áp dụng được ngay vào thực tế. "
                f"[tự hào] {clean_cta}!"
            )
        from whiteboard_story import local_scene_plan
        scenes = local_scene_plan(current_script, duration_sec, voice_name)
        return {
            "script": current_script,
            "scenes": scenes,
            "titles": [f"Bí Quyết Về {clean_sub}", f"Khám Phá {clean_sub} Triệu View"],
            "description": f"Video chia sẻ về {clean_sub} được sản xuất hoàn toàn tự động bởi Tuấn Blogger AI Studio.",
            "hashtags": ["#AI", "#TuanBlogger", "#VideoAI", "#Whiteboard"]
        }
    return generate_storyboard(call_gemini, subject, duration_sec, tone, cta, model_name,
                               feedback, current_script, current_scenes, aspect, style, voice_name,
                               **({"resume_narration": True} if resume_narration else {}))


def parse_duration(value, default: int = 35) -> int:
    try:
        duration = int(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Thời lượng phải là số giây từ 15 đến 600.") from None
    if not 15 <= duration <= 600:
        raise ValueError("Thời lượng phải từ 15 đến 600 giây.")
    return duration

@cancellable_job
def run_video_job(job_id: str, brief: dict):
    job = JOBS[job_id]
    try:
        subject = str(brief.get("subject") or "").strip()
        duration_sec = parse_duration(brief.get("duration"))
        style = brief.get("style", "whiteboard")
        model_name = brief.get("model", "gemini-2.5-pro")
        aspect = brief.get("aspect", "16:9")
        tone = brief.get("tone", "Tri thức, phân tích logic và cuốn hút")
        voice_name = brief.get("voice", "adam:neural-vietnamese:Adam")
        cta = brief.get("cta", "Follow kênh và để lại ý kiến")
        script = str(brief.get("script") or "").strip()
        metadata = dict(brief.get("metadata")) if isinstance(brief.get("metadata"), dict) else {}
        for field in ("titles", "description", "hashtags"):
            if brief.get(field):
                metadata[field] = brief[field]
        job["auto_shutdown"] = bool(brief.get("auto_shutdown"))
        _update_job(job, state="running", phase="script", progress=8, started_at=time.time(),
                   phase_text="Đang chuẩn bị kịch bản và phân cảnh...")

        if style == "whiteboard":
            if not produce_whiteboard_video:
                raise RuntimeError("Chưa tải được engine Whiteboard. Kiểm tra môi trường Python và các thư viện render.")
            if isinstance(brief.get("scenes"), list):
                metadata["scenes"] = brief["scenes"]
            def whiteboard_progress(phase, text, pct, **extra):
                updates = {"phase": phase, "phase_text": text, "progress": pct}
                if "audio_status" in extra:
                    updates["audio_status"] = extra["audio_status"]
                if "visual_status" in extra:
                    updates["visual_status"] = extra["visual_status"]
                if "compose_status" in extra:
                    updates["compose_status"] = extra["compose_status"]
                _update_job(job, **updates)
            def whiteboard_storyboard(approved_script, previous_scenes):
                return generate_script_and_terms(
                    subject, duration_sec, tone, cta, model_name,
                    current_script=approved_script, current_scenes=previous_scenes,
                    aspect="16:9", style="whiteboard", voice_name=voice_name)
            result = produce_whiteboard_video(
                subject=subject, model_name=model_name, duration_sec=duration_sec,
                voice_name=voice_name, tone=tone, cta=cta,
                progress_callback=whiteboard_progress, script=script, custom_meta=metadata,
                defer_publish=True, storyboard_callback=whiteboard_storyboard)
            publish_video_result(job, result, result["_staged_video_path"], "Hoàn tất video Whiteboard!")
            return

        if aspect not in ("9:16", "16:9"):
            raise ValueError("Flow hỗ trợ khung hình 9:16 hoặc 16:9.")
        api_key = get_gemini_key()
        if not api_key:
            raise RuntimeError("Chưa cấu hình Google API key cho chức năng tạo ảnh và video.")
        scenes = brief.get("scenes")
        if not script:
            planned = generate_script_and_terms(subject, duration_sec, tone, cta, model_name,
                                                aspect=aspect, style="flow", voice_name=voice_name)
            script = planned["script"]
            scenes = planned["scenes"]
            metadata = {**planned, **metadata}
        elif not scenes:
            planned = generate_script_and_terms(
                subject, duration_sec, tone, cta, model_name,
                current_script=script, aspect=aspect, style="flow", voice_name=voice_name)
            scenes = planned["scenes"]
            metadata = {**planned, **metadata}
        scenes = normalize_scene_plan(scenes, duration_sec)
        def narration_progress(phase, text, pct=10, **extra):
            audio_st = extra.get("audio_status") or {
                "status": "working",
                "voice": voice_name,
                "stage": phase,
                "detail": text
            }
            _update_job(job, phase="audio", phase_text=text, progress=max(8, int(pct)), audio_status=audio_st)
        # Measure the selected voice before submitting billable image/video jobs.
        # An old short draft must never consume those jobs and produce a tiny video.
        _update_job(job, script=script, scenes=scenes, metadata=metadata)
        narration = prepare_flow_narration(
            script, voice_name, mpt_root=MPT_ROOT, api_base=MPT_API_BASE,
            progress_callback=narration_progress, total_duration_sec=duration_sec)
        audio_dur = narration.get("original_narration_duration_sec") or narration.get("narration_duration_sec", 0)
        _update_job(job, script=script, scenes=scenes, metadata=metadata,
                   phase="images", progress=18,
                   phase_text=f"Đang tạo ảnh AI và video cho {len(scenes)} phân cảnh...",
                   audio_status={"status": "completed", "voice": voice_name, "duration_sec": audio_dur, "detail": f"Đã thu âm xong ({audio_dur:.1f}s)"},
                   visual_status={"status": "working", "type": "flow", "current": 0, "total": len(scenes), "stage": "start", "detail": f"0/{len(scenes)} phân cảnh"})

        image_model = os.environ.get("STUDIO_GOOGLE_IMAGE_MODEL") or flow_engine.DEFAULT_IMAGE_MODEL
        video_model = os.environ.get("STUDIO_GOOGLE_VIDEO_MODEL") or flow_engine.DEFAULT_VIDEO_MODEL
        scene_dir = FLOW_DIR / "jobs" / job_id
        scene_dir.mkdir(parents=True, exist_ok=True)
        def media_progress(phase, text, pct, **extra):
            curr = extra.get("current", 0)
            tot = extra.get("total", len(scenes))
            stg = extra.get("stage", "working")
            visual_st = {
                "status": "completed" if (curr >= tot and stg == "ready") else "working",
                "type": "flow",
                "current": curr,
                "total": tot,
                "stage": stg,
                "detail": text
            }
            _update_job(job, phase=phase, phase_text=text, progress=18 + int(max(0, min(100, pct)) * 0.58),
                       visual_status=visual_st)
        scene_media = flow_engine.create_scene_media(
            api_key, scenes, aspect, scene_dir, progress_callback=media_progress,
            image_model=image_model, video_model=video_model)
        check_cancelled()
        if len(scene_media) != len(scenes):
            raise RuntimeError("Chưa tạo đủ clip AI cho tất cả phân cảnh. Video chưa được xuất.")

        output_name = f"Flow_{slugify(subject)}_{int(time.time())}_{job_id}.mp4"
        output_path = scene_dir / output_name
        def composition_progress(phase, text, pct, **extra):
            compose_st = {"status": "working", "detail": text}
            _update_job(job, phase=phase, phase_text=text, progress=76 + int(max(0, min(100, pct)) * 0.23),
                       visual_status={"status": "completed", "type": "flow", "current": len(scenes), "total": len(scenes), "detail": f"Đã hoàn thành {len(scenes)}/{len(scenes)} cảnh"},
                       compose_status=compose_st)
        check_cancelled()
        composed = compose_flow_video(
            scene_media, script, voice_name, aspect, output_path,
            progress_callback=composition_progress, mpt_root=MPT_ROOT, api_base=MPT_API_BASE,
            bgm_type=brief.get("bgm", "none"), total_duration_sec=duration_sec,
            prepared_narration=narration)
        if not output_path.is_file() or not output_path.stat().st_size:
            raise RuntimeError("Chưa tìm thấy video hoàn chỉnh sau khi ghép giọng và phụ đề.")
        result = {
            "subject": subject, "style": "flow", "production_method": "google_api",
            "model": model_name, "image_model": image_model, "video_model": video_model,
            "aspect": aspect, "voice": voice_name, "requested_duration_sec": duration_sec,
            "duration_sec": composed.get("duration_sec"),
            "narration_duration_sec": composed.get("narration_duration_sec"),
            "original_narration_duration_sec": composed.get("original_narration_duration_sec"),
            "video_filename": output_name, "video_url": f"/export_ready/{output_name}",
            "script": script, "scenes": scenes,
            "titles": metadata.get("titles") or [subject],
            "description": metadata.get("description") or "",
            "hashtags": metadata.get("hashtags") or [],
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if composed.get("source_task_id"):
            result["source_task_id"] = composed["source_task_id"]
        if composed.get("bgm_applied") is not None:
            result["bgm_applied"] = composed["bgm_applied"]
        publish_video_result(job, result, output_path, "Hoàn tất video AI với giọng Gemini và phụ đề!")
    except StudioCancelled:
        raise
    except Exception as error:
        with JOB_LOCK:
            check_cancelled()
            job.update(state="failed", phase="failed", error=str(error), finished_at=time.time())



@cancellable_job
def run_flow_video_job(job_id: str, brief: dict):
    """Tạo một clip AI từ ảnh bằng Google API."""
    job = JOBS[job_id]
    try:
        image_name = Path(brief.get("image_filename", "")).name
        image_path = FLOW_DIR / image_name
        if not image_name or not image_path.exists():
            raise flow_engine.FlowError("Không tìm thấy ảnh nguồn, vui lòng tạo hoặc tải ảnh lên trước.")

        aspect = brief.get("aspect", "16:9")
        duration = int(brief.get("duration", 6))
        motion = brief.get("motion", "zoom")
        motion_prompt = brief.get("motion_prompt", "").strip() or "Slow cinematic camera dolly-in, warm volumetric sunset lighting"
        title = brief.get("title", "").strip() or "Flow clip"

        _update_job(job, state="running", phase="render", progress=30,
                   phase_text="Đang tạo clip AI từ ảnh bằng Google API...")

        safe_title = slugify(title)
        out_name = f"Flow_{safe_title}_{int(time.time())}.mp4"
        stage_dir = FLOW_DIR / "jobs" / job_id
        stage_dir.mkdir(parents=True, exist_ok=True)
        out_file = stage_dir / out_name

        _update_job(job, progress=60, phase_text="Đang tạo và tải clip AI từ Google...")
        flow_engine.render_flow_video(image_path, out_file, duration_sec=duration, motion=motion,
                                      api_key=get_gemini_key(), prompt=motion_prompt, aspect=aspect)

        meta = {
            "subject": title,
            "style": "flow",
            "aspect": aspect,
            "voice": "Cinematic Ambient Motion",
            "duration_render_sec": duration,
            "video_filename": out_name,
            "video_url": f"/export_ready/{out_name}",
            "download_url": f"/api/download?file={urllib.parse.quote(out_name)}",
            "source_image": f"/flow_assets/{image_name}",
            "image_prompt": brief.get("image_prompt", ""),
            "script": motion_prompt,
            "titles": [title],
            "description": brief.get("image_prompt", "") or motion_prompt,
            "hashtags": ["#googleflow", "#aivideo", "#antigravity"],
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        publish_video_result(job, meta, out_file, "Video Google Flow đã xuất bản thành công!")
    except StudioCancelled:
        raise
    except Exception as e:
        with JOB_LOCK:
            check_cancelled()
            job.update(state="failed", phase="failed", error=str(e), finished_at=time.time())


class OfficeHubHandler(http.server.SimpleHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        try:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            return {}

    def handle_flow_post(self, path: str) -> bool:
        """Các API của quy trình Google Flow. Trả về True nếu đã xử lý."""
        if not path.startswith("/api/flow/"):
            return False
        params = self._read_json()
        api_key = get_gemini_key()
        try:
            if path == "/api/flow/prompts":
                idea = params.get("idea", "").strip()
                if not idea:
                    return self._send_json(400, {"error": "Vui lòng nhập ý tưởng"}) or True
                data = flow_engine.build_flow_prompts(idea, params.get("aspect", "16:9"),
                                                      params.get("style", ""), call_gemini)
                self._send_json(200, {"status": "success", "data": data})
            elif path == "/api/flow/generate-image":
                prompt = params.get("prompt", "").strip()
                if not prompt:
                    return self._send_json(400, {"error": "Vui lòng nhập prompt hình ảnh"}) or True
                images = flow_engine.generate_images(api_key, prompt, params.get("aspect", "16:9"),
                                                     params.get("model", ""), params.get("count", 1), FLOW_DIR)
                self._send_json(200, {"status": "success", "images": images})
            elif path == "/api/flow/upload-image":
                img = flow_engine.save_uploaded_image(params.get("data_url", ""), FLOW_DIR)
                self._send_json(200, {"status": "success", "image": img})
            elif path == "/api/flow/generate-video":
                job_id = str(uuid.uuid4())[:8]
                job, token, created = register_job(job_id, "video", params.get("title", "Flow clip"), params.get("request_id", ""))
                if created and not token.cancelled:
                    threading.Thread(target=run_flow_video_job, args=(job["job_id"], params), daemon=True).start()
                self._send_json(200, {"status": "cancelled" if token.cancelled else "started", "job_id": job["job_id"],
                                      "request_id": job["request_id"], "state": job["state"]})
            else:
                self._send_json(404, {"error": "Flow endpoint not found"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})
        return True

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        decoded_path = urllib.parse.unquote(parsed.path)
        if decoded_path.startswith("/flow_assets/"):
            asset = FLOW_DIR / Path(decoded_path.replace("/flow_assets/", "")).name
            if asset.exists() and asset.is_file():
                self.send_response(200)
                self.send_header("Content-Length", str(asset.stat().st_size))
                self.end_headers()
            else:
                self.send_error(404, "Asset not found")
            return

        if decoded_path.startswith("/export_ready/"):
            filename = decoded_path.replace("/export_ready/", "")
            target_file = EXPORT_DIR / filename
            if target_file.exists() and target_file.is_file():
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4" if filename.endswith(".mp4") else "application/octet-stream")
                self.send_header("Content-Length", str(target_file.stat().st_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
            else:
                self.send_error(404, "File not found")
                return
        super().do_HEAD()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        raw_path = parsed.path
        decoded_path = urllib.parse.unquote(raw_path)
        query = urllib.parse.parse_qs(parsed.query)

        if decoded_path.startswith("/api/tts/audio/"):
            filename = os.path.basename(decoded_path)
            target = OFFICE_DIR / "tts_storage" / filename
            if target.exists() and target.is_file():
                self.serve_video_file(target, as_attachment=False)
                return
            else:
                self.send_error(404, "Audio file not found")
                return

        if decoded_path.startswith("/api/tts/srt/"):
            filename = os.path.basename(decoded_path)
            target = OFFICE_DIR / "tts_storage" / filename
            if target.exists() and target.is_file():
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
            else:
                self.send_error(404, "SRT file not found")
                return

        if decoded_path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "time": time.time()}).encode("utf-8"))
            return

        if decoded_path == "/api/tts/auto-emotions":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Dữ liệu không hợp lệ."})
                return
            raw_text = params.get("text", "").strip()
            if not raw_text:
                self._send_json(400, {"error": "Vui lòng nhập văn bản cần gắn thẻ cảm xúc."})
                return
            gemini_key = get_gemini_key()
            if not gemini_key:
                self._send_json(400, {"error": "Chưa có Google Gemini API Key trong hệ thống."})
                return

            prompt = f"""Bạn là đạo diễn âm thanh lồng tiếng chuyên nghiệp.
Hãy phân tích đoạn kịch bản sau và chèn các thẻ cảm xúc ngữ điệu (meta-tags) để người lồng tiếng / AI đọc diễn cảm và lôi cuốn nhất.
Các thẻ cảm xúc cho phép sử dụng: [kịch tính], [thì thầm], [dồn dập], [thở dài], [ngạc nhiên], [nhấn mạnh], [chậm rãi], [bí ẩn], [tự hào].
Quy tắc:
- Giữ nguyên 100% nội dung chữ và câu từ gốc, tuyệt đối KHÔNG được tự ý viết thêm hay bớt chữ.
- Chỉ chèn các thẻ vuông [...] vào đầu câu hoặc giữa các vế câu cần đổi cảm xúc.
- Chỉ trả về đoạn văn bản đã chèn thẻ, không giải thích gì thêm.

Kịch bản:
{raw_text}"""
            enriched = None
            from google import genai
            for model in ["gemini-3.1-flash-lite", "gemini-2.5-pro", "gemini-3.8-flash"]:
                try:
                    with genai.Client(api_key=gemini_key) as client:
                        res = client.models.generate_content(model=model, contents=prompt)
                        if res and res.text:
                            enriched = res.text.strip()
                            break
                except Exception as e:
                    logger.warning(f"Auto emotion model {model} error: {e}")

            if enriched:
                self._send_json(200, {"success": True, "enriched_text": enriched})
            else:
                self._send_json(500, {"error": "Không thể phân tích cảm xúc lúc này, vui lòng thử lại."})
            return

        if decoded_path == "/api/tts/parse-srt":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Dữ liệu không hợp lệ."})
                return
            srt_content = params.get("srt_content", "").strip()
            if not srt_content:
                self._send_json(400, {"error": "Nội dung phụ đề SRT trống."})
                return
            lines = srt_content.splitlines()
            text_lines = []
            for l in lines:
                l = l.strip()
                if not l or l.isdigit() or "-->" in l:
                    continue
                text_lines.append(l)
            plain_text = " ".join(text_lines)
            self._send_json(200, {
                "success": True,
                "plain_text": plain_text,
                "lines_count": len(text_lines)
            })
            return

        if decoded_path == "/api/config/keys":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            info = read_system_keys()
            resp = {
                "has_gemini": info["has_gemini"],
                "gemini_masked": info["gemini_masked"],
                "has_elevenlabs": info["has_elevenlabs"],
                "elevenlabs_count": len(info["elevenlabs_api_keys"]),
                "elevenlabs_masked": info["elevenlabs_masked"],
                "is_configured": info["has_gemini"]
            }
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        if decoded_path == "/api/system/version":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            version_file = OFFICE_DIR / "version.json"
            vinfo = {"version": "4.2.0", "app_name": "TuanBlogger AI Studio", "release_date": "2026-11-01"}
            if version_file.exists():
                try:
                    vinfo = json.loads(version_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            current_v = vinfo.get("version", "4.1.0")
            do_check = query.get("check", ["false"])[0].lower() in ("true", "1")
            has_update = False
            remote_v = current_v
            changelog = vinfo.get("changelog", "")
            release_notes = vinfo.get("release_notes", [])
            download_url = ""
            msg = f"Bạn đang dùng phiên bản mới nhất (v{current_v})!"
            
            if do_check:
                manifest_url = vinfo.get("update_manifest_url")
                if manifest_url:
                    try:
                        r = requests.get(manifest_url, timeout=4)
                        if r.status_code == 200:
                            rem_data = r.json()
                            remote_v = rem_data.get("version", current_v)
                            curr_parts = [int(x) for x in re.findall(r'\d+', current_v)]
                            rem_parts = [int(x) for x in re.findall(r'\d+', remote_v)]
                            if rem_parts > curr_parts:
                                has_update = True
                                changelog = rem_data.get("changelog", "Bản cập nhật tính năng mới")
                                release_notes = rem_data.get("release_notes", [changelog] if changelog else [])
                                download_url = rem_data.get("download_url", "")
                                msg = f"Phát hiện bản cập nhật mới v{remote_v}!"
                    except Exception as e:
                        logger.warning("Không thể kiểm tra update từ remote: %s", e)
                        msg = f"Đang ở phiên bản v{current_v}. (Không có kết nối tới server update)"
            
            if not release_notes and changelog:
                release_notes = [changelog]

            resp = {
                "app_name": vinfo.get("app_name", "TuanBlogger AI Studio"),
                "title": vinfo.get("title", f"Phiên bản v{remote_v}"),
                "current_version": current_v,
                "latest_version": remote_v,
                "has_update": has_update,
                "changelog": changelog,
                "release_notes": release_notes,
                "download_url": download_url,
                "release_date": vinfo.get("release_date", "2026-11-01"),
                "message": msg
            }
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            return

        if decoded_path == "/api/system/update-progress":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(UPDATE_PROGRESS, ensure_ascii=False).encode("utf-8"))
            return

        if decoded_path == "/api/active-job":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            active_job = None
            script_job = None
            now = time.time()
            with JOB_LOCK:
                snapshot = [dict(job) for job in JOBS.values()]
            # Ưu tiên lấy job đang chạy hoặc đang đợi
            for j in sorted(snapshot, key=lambda x: x.get("created_at", 0), reverse=True):
                if j.get("kind") == "script":
                    if script_job is None and j.get("state") in ("running", "queued", "cancelling"):
                        script_job = j
                    continue
                if active_job is None and j.get("state") in ("running", "queued", "cancelling"):
                    active_job = j
            # Nếu không có job chạy, lấy job vừa hoàn thành trong 180s gần nhất
            if not active_job:
                for j in sorted(snapshot, key=lambda x: x.get("created_at", 0), reverse=True):
                    if j.get("kind") != "script" and now - j.get("finished_at", j.get("created_at", 0)) < 180 and j.get("state") in ("completed", "failed", "cancelled"):
                        active_job = j
                        break
            self.wfile.write(json.dumps({"job": active_job, "script_job": script_job}, ensure_ascii=False).encode("utf-8"))
            return

        if decoded_path == "/api/video-status":
            job_id = query.get("job_id", [""])[0]
            with JOB_LOCK:
                stored = JOBS.get(job_id)
                job = dict(stored) if stored else None
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if job:
                started = job.get("started_at") or job.get("created_at") or time.time()
                if job.get("state") in ("running", "queued", "cancelling"):
                    job["elapsed_sec"] = max(0, int(time.time() - started))
                elif job.get("finished_at"):
                    job["elapsed_sec"] = max(0, int(job["finished_at"] - started))
                else:
                    job["elapsed_sec"] = max(0, int(time.time() - started))
                self.wfile.write(json.dumps(job, ensure_ascii=False).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"state": "not_found"}).encode("utf-8"))
            return

        if decoded_path == "/api/flow/gallery":
            imgs = []
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                for f in FLOW_DIR.glob(f"*{ext}"):
                    imgs.append({"filename": f.name, "url": f"/flow_assets/{f.name}", "time": f.stat().st_mtime})
            imgs.sort(key=lambda x: x["time"], reverse=True)
            self._send_json(200, {"images": imgs[:30]})
            return

        if decoded_path == "/api/recent-videos":
            try:
                self._send_json(200, {"videos": recent_videos()})
            except (OSError, ValueError) as e:
                self._send_json(500, {"error": "Không thể tải lịch sử video: " + str(e)})
            return

        if decoded_path == "/api/download":
            file_param = query.get("file", [""])[0]
            if not file_param:
                self.send_error(400, "Missing file parameter")
                return
            target_name = Path(urllib.parse.unquote(file_param)).name
            target_file = EXPORT_DIR / target_name
            if not target_file.exists():
                ts_m = re.search(r"(\d{9,12})", target_name)
                if ts_m:
                    cand = list(EXPORT_DIR.glob(f"*{ts_m.group(1)}*.mp4"))
                    if cand:
                        target_file = cand[0]
            if not target_file.exists():
                cand = list(EXPORT_DIR.glob(f"*{target_name}*"))
                if cand:
                    target_file = cand[0]

            if target_file.exists() and target_file.is_file():
                self.serve_video_file(target_file, as_attachment=True)
                return
            else:
                self.send_error(404, "Video not found")
                return

        if decoded_path.startswith("/flow_assets/"):
            asset = FLOW_DIR / Path(decoded_path.replace("/flow_assets/", "")).name
            if asset.exists() and asset.is_file():
                self.serve_video_file(asset, as_attachment=query.get("download", ["0"])[0] == "1")
            else:
                self.send_error(404, "Asset not found")
            return

        if decoded_path.startswith("/export_ready/"):
            filename = decoded_path.replace("/export_ready/", "")
            target_file = EXPORT_DIR / filename
            if not target_file.exists():
                ts_m = re.search(r"(\d{9,12})", filename)
                if ts_m:
                    cand = list(EXPORT_DIR.glob(f"*{ts_m.group(1)}*.mp4"))
                    if cand:
                        target_file = cand[0]
            if not target_file.exists():
                candidates = list(EXPORT_DIR.glob(f"*{filename}*"))
                if candidates:
                    target_file = candidates[0]
            
            if target_file.exists() and target_file.is_file():
                self.serve_video_file(target_file, as_attachment=False)
                return
            else:
                self.send_error(404, "Video not found")
                return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        decoded_path = urllib.parse.unquote(parsed.path)

        if decoded_path == "/api/cancel-job":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Yêu cầu dừng không hợp lệ."})
                return
            code, result = cancel_studio_job(params.get("job_id", ""), params.get("request_id", ""))
            self._send_json(code, result)
            return

        if decoded_path == "/api/tts/auto-emotions":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Dữ liệu không hợp lệ."})
                return
            raw_text = params.get("text", "").strip()
            if not raw_text:
                self._send_json(400, {"error": "Vui lòng nhập văn bản cần gắn thẻ cảm xúc."})
                return
            gemini_key = get_gemini_key()
            if not gemini_key:
                self._send_json(400, {"error": "Chưa có Google Gemini API Key trong hệ thống."})
                return

            prompt = f"""Bạn là đạo diễn âm thanh lồng tiếng chuyên nghiệp.
Hãy phân tích đoạn kịch bản sau và chèn các thẻ cảm xúc ngữ điệu (meta-tags) để người lồng tiếng / AI đọc diễn cảm và lôi cuốn nhất.
Các thẻ cảm xúc cho phép sử dụng: [kịch tính], [thì thầm], [dồn dập], [thở dài], [ngạc nhiên], [nhấn mạnh], [chậm rãi], [bí ẩn], [tự hào].
Quy tắc:
- Giữ nguyên 100% nội dung chữ và câu từ gốc, tuyệt đối KHÔNG được tự ý viết thêm hay bớt chữ.
- Chỉ chèn các thẻ vuông [...] vào đầu câu hoặc giữa các vế câu cần đổi cảm xúc.
- Chỉ trả về đoạn văn bản đã chèn thẻ, không giải thích gì thêm.

Kịch bản:
{raw_text}"""
            enriched = None
            from google import genai
            for model in ["gemini-3.1-flash-lite", "gemini-2.5-pro", "gemini-3.8-flash"]:
                try:
                    with genai.Client(api_key=gemini_key) as client:
                        res = client.models.generate_content(model=model, contents=prompt)
                        if res and res.text:
                            enriched = res.text.strip()
                            break
                except Exception as e:
                    logger.warning(f"Auto emotion model {model} error: {e}")

            if enriched:
                self._send_json(200, {"success": True, "enriched_text": enriched})
            else:
                self._send_json(500, {"error": "Không thể phân tích cảm xúc lúc này, vui lòng thử lại."})
            return

        if decoded_path == "/api/tts/parse-srt":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Dữ liệu không hợp lệ."})
                return
            srt_content = params.get("srt_content", "").strip()
            if not srt_content:
                self._send_json(400, {"error": "Nội dung phụ đề SRT trống."})
                return
            lines = srt_content.splitlines()
            text_lines = []
            for l in lines:
                l = l.strip()
                if not l or l.isdigit() or "-->" in l:
                    continue
                text_lines.append(l)
            plain_text = " ".join(text_lines)
            self._send_json(200, {
                "success": True,
                "plain_text": plain_text,
                "lines_count": len(text_lines)
            })
            return

        if decoded_path == "/api/tts/generate":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Dữ liệu không hợp lệ."})
                return
            raw_text = params.get("text", "").strip()
            voice_name = params.get("voice", "elevenlabs:pNInz6obpgDQGcFmaJgB:Adam").strip()
            voice_rate = float(params.get("voice_rate", 1.0))
            voice_volume = float(params.get("voice_volume", 1.0))
            eleven_custom_key = params.get("elevenlabs_api_key", "").strip()
            gemini_custom_key = params.get("gemini_api_key", "").strip()

            if not raw_text:
                self._send_json(400, {"error": "Nội dung kịch bản không được để trống."})
                return

            if gemini_custom_key:
                update_system_keys(gemini_key=gemini_custom_key)
            if eleven_custom_key:
                update_system_keys(eleven_keys=[eleven_custom_key])

            clean_text = raw_text
            if "-->" in raw_text:
                lines = raw_text.splitlines()
                clean_lines = []
                for l in lines:
                    l = l.strip()
                    if not l or l.isdigit() or "-->" in l:
                        continue
                    clean_lines.append(l)
                clean_text = " ".join(clean_lines)

            # Lọc bỏ các thẻ cảm xúc [tự hào], [thì thầm], [kịch tính]... khỏi văn bản đọc
            speech_text = re.sub(r'\[.*?\]', '', clean_text)
            speech_text = re.sub(r'\s+', ' ', speech_text).strip()
            if not speech_text:
                speech_text = clean_text

            # Tự động điều chỉnh nếu chọn giọng không tồn tại trên Edge-TTS miễn phí (ví dụ DaLat)
            if "dalat" in voice_name.lower():
                voice_name = "vi-VN-NamMinhNeural-Male"

            if MPT_SITE_PACKAGES not in sys.path:
                sys.path.insert(0, MPT_SITE_PACKAGES)
            sys.path.append(str(MPT_ROOT))
            from app.services import voice

            # Nếu chọn giọng ElevenLabs nhưng chưa có API key
            if voice_name.startswith("elevenlabs:"):
                keys = voice.get_elevenlabs_api_keys()
                if not keys and not eleven_custom_key:
                    self._send_json(400, {
                        "error": "Chưa có ElevenLabs API Key! Vui lòng vào Cài Đặt để nhập Key hoặc chọn 2 giọng miễn phí 'vi-VN-NamMinh' / 'vi-VN-HoaiMy' (Edge-TTS) để sử dụng ngay không cần API."
                    })
                    return

            tts_id = f"tts_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            tts_dir = OFFICE_DIR / "tts_storage"
            tts_dir.mkdir(parents=True, exist_ok=True)
            audio_path = str(tts_dir / f"{tts_id}.mp3")
            srt_path = str(tts_dir / f"{tts_id}.srt")

            try:
                sub_maker = voice.tts(
                    text=speech_text,
                    voice_name=voice_name,
                    voice_rate=voice_rate,
                    voice_file=audio_path,
                    voice_volume=voice_volume
                )
            except Exception as e:
                logger.error(f"TTS generation error: {e}")
                self._send_json(500, {"error": f"Lỗi thu giọng: {str(e)}"})
                return

            if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                err_msg = "Không thể tạo file âm thanh."
                if voice_name.startswith("elevenlabs:"):
                    err_msg = "Lỗi ElevenLabs API: Key không hợp lệ hoặc tài khoản ElevenLabs của bạn đã hết Quota (ký tự). Vui lòng kiểm tra lại Key."
                self._send_json(500, {"error": err_msg})
                return

            srt_content = ""
            if sub_maker:
                try:
                    voice.create_subtitle(sub_maker, speech_text, srt_path)
                    if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
                        with open(srt_path, "r", encoding="utf-8", errors="ignore") as fp:
                            srt_content = fp.read()
                except Exception as se:
                    logger.warning(f"Error saving SRT via create_subtitle: {se}")

                if not srt_content:
                    try:
                        raw_srt = sub_maker.get_srt() if hasattr(sub_maker, "get_srt") else ""
                        if raw_srt:
                            with open(srt_path, "w", encoding="utf-8") as fp:
                                fp.write(raw_srt)
                            srt_content = raw_srt
                    except Exception as fe:
                        logger.warning(f"Fallback sub_maker.get_srt error: {fe}")

            dur = voice.get_audio_duration(audio_path)

            if not srt_content and speech_text and dur > 0:
                try:
                    dur_ms = int(dur * 1000)
                    end_str = f"{dur_ms // 3600000:02d}:{(dur_ms % 3600000) // 60000:02d}:{(dur_ms % 60000) // 1000:02d},{dur_ms % 1000:03d}"
                    srt_content = f"1\n00:00:00,100 --> {end_str}\n{speech_text}\n\n"
                    with open(srt_path, "w", encoding="utf-8") as fp:
                        fp.write(srt_content)
                except Exception:
                    pass

            self._send_json(200, {
                "success": True,
                "tts_id": tts_id,
                "audio_url": f"/api/tts/audio/{tts_id}.mp3",
                "srt_url": f"/api/tts/srt/{tts_id}.srt",
                "srt_content": srt_content,
                "duration_sec": round(dur, 1),
                "voice": voice_name,
                "clean_text": clean_text
            })
            return

        if decoded_path == "/api/config/test-elevenlabs":
            params = self._read_json()
            test_key = params.get("elevenlabs_api_key", "").strip() if isinstance(params, dict) else ""
            if not test_key:
                info = read_system_keys()
                keys = info.get("elevenlabs_api_keys", [])
                test_key = keys[0] if keys else ""
            if not test_key:
                self._send_json(400, {"valid": False, "error": "Chưa có ElevenLabs API Key để kiểm tra."})
                return
            try:
                res = requests.get(
                    "https://api.elevenlabs.io/v1/user/subscription",
                    headers={"xi-api-key": test_key},
                    timeout=8
                )
                if res.status_code == 200:
                    data = res.json()
                    used = data.get("character_count", 0)
                    limit = data.get("character_limit", 0)
                    tier = data.get("tier", "free")
                    self._send_json(200, {
                        "valid": True,
                        "message": f"Kết nối ElevenLabs thành công! (Gói {tier}: Đã dùng {used:,}/{limit:,} ký tự)",
                        "tier": tier,
                        "used": used,
                        "limit": limit
                    })
                else:
                    self._send_json(400, {"valid": False, "error": f"Lỗi ElevenLabs ({res.status_code}): {res.text[:120]}"})
            except Exception as e:
                self._send_json(500, {"valid": False, "error": f"Lỗi kết nối: {str(e)}"})
            return

        if decoded_path == "/api/config/keys":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Dữ liệu không hợp lệ."})
                return
            gemini_key = params.get("gemini_api_key")
            eleven_keys = params.get("elevenlabs_api_keys")
            if isinstance(eleven_keys, str):
                eleven_keys = [k.strip() for k in re.split(r"[,;\n\r]+", eleven_keys) if k.strip()]
            success = update_system_keys(gemini_key=gemini_key, eleven_keys=eleven_keys)
            if success:
                self._send_json(200, {"status": "success", "message": "Đã cập nhật API Keys thành công!"})
            else:
                self._send_json(500, {"error": "Không thể cập nhật cấu hình."})
            return

        if decoded_path == "/api/config/test-gemini":
            params = self._read_json()
            test_key = params.get("gemini_api_key", "").strip() if isinstance(params, dict) else ""
            if not test_key:
                test_key = get_gemini_key()
            if not test_key:
                self._send_json(400, {"valid": False, "error": "Chưa có Google Gemini API Key để kiểm tra."})
                return
            try:
                res = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={test_key}",
                    json={"contents": [{"parts": [{"text": "ping"}]}]},
                    timeout=8
                )
                if res.status_code == 200:
                    self._send_json(200, {"valid": True, "message": "Kết nối Gemini API thành công!"})
                else:
                    self._send_json(400, {"valid": False, "error": f"Lỗi Google API ({res.status_code}): {res.text[:120]}"})
            except Exception as e:
                self._send_json(500, {"valid": False, "error": f"Lỗi kết nối: {str(e)}"})
            return

        if decoded_path == "/api/system/update":
            if UPDATE_PROGRESS.get("is_updating"):
                self._send_json(400, {"status": "error", "error": "Hệ thống đang trong quá trình cập nhật."})
                return
            params = self._read_json()
            download_url = params.get("download_url", "").strip() if isinstance(params, dict) else ""
            if not download_url:
                version_file = OFFICE_DIR / "version.json"
                if version_file.exists():
                    try:
                        vinfo = json.loads(version_file.read_text(encoding="utf-8"))
                        m_url = vinfo.get("update_manifest_url")
                        if m_url:
                            r = requests.get(m_url, timeout=5)
                            if r.status_code == 200:
                                download_url = r.json().get("download_url", "")
                    except Exception:
                        pass

            threading.Thread(target=run_system_update, args=(download_url,), daemon=True).start()
            self._send_json(200, {
                "status": "started",
                "message": "Quá trình cập nhật hệ thống đã được bắt đầu trong nền."
            })
            return

        # 0. Quy trình Google Flow: Prompt -> Ảnh -> Video
        if self.handle_flow_post(decoded_path):
            return

        # API Xóa video đã tạo
        if decoded_path == "/api/delete-video":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                params = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                params = {}
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Yêu cầu xóa video không hợp lệ."})
                return
            try:
                result = delete_exported_video(params.get("filename") or params.get("video_filename") or "")
                self._send_json(200, {"status": "success", "message": "Đã xóa video khỏi lịch sử.", **result})
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except VideoInUseError:
                self._send_json(409, {"error": "Video đang được phát hoặc tải xuống. Hãy đóng video ở các tab/ứng dụng khác rồi thử xóa lại."})
            except OSError as e:
                logger.warning("delete video failed: %s", e)
                self._send_json(500, {"error": "Không thể xóa video trên ổ đĩa. Vui lòng thử lại."})
            return

        # 0.5. API AI Tự Động Thêm Thẻ Cảm Xúc vào Kịch bản
        if decoded_path == "/api/ai-emotion-tags":
            params = self._read_json()
            if not isinstance(params, dict):
                self._send_json(400, {"error": "Dữ liệu không hợp lệ."})
                return
            script = params.get("script", "").strip()
            if not script:
                self._send_json(400, {"error": "Vui lòng nhập hoặc tạo kịch bản trước khi thêm thẻ cảm xúc."})
                return
            tone = params.get("tone", "")
            model_name = params.get("model", "gemini-3.1-flash-lite")
            try:
                from emotion_tags import add_emotion_tags_with_ai
                tagged_script = add_emotion_tags_with_ai(call_gemini, script, tone=tone, model_name=model_name)
                self._send_json(200, {"status": "success", "tagged_script": tagged_script})
            except Exception as e:
                logger.error("Lỗi thêm thẻ cảm xúc: %s", e)
                self._send_json(500, {"error": f"Lỗi AI thêm thẻ cảm xúc: {str(e)}"})
            return

        # 1. API Tạo hoặc Cải thiện Kịch bản bằng Model cao nhất
        if decoded_path == "/api/generate-script":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                params = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                params = {}

            subject = params.get("subject", "").strip()
            if not subject:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Vui lòng nhập chủ đề video"}).encode("utf-8"))
                return

            try:
                duration_sec = parse_duration(params.get("duration"))
                request_id = validate_request_id(params.get("request_id")) or "script-" + uuid.uuid4().hex
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            tone = params.get("tone", "Tri thức, phân tích logic và cuốn hút")
            cta = params.get("cta", "Follow kênh và để lại ý kiến thảo luận")
            model_name = params.get("model", "gemini-2.5-pro")
            feedback = params.get("feedback", "").strip()
            current_script = (params.get("current_script") or params.get("existing_script") or "").strip()

            try:
                job, token, created = register_job(request_id, "script", subject, request_id)
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return
            if not created:
                if job["state"] == "completed":
                    self._send_json(200, {"status": "success", "data": job["result"], "job_id": job["job_id"], "request_id": request_id})
                elif job["state"] in ("cancelling", "cancelled"):
                    self._send_json(200, {"status": job["state"], "state": job["state"], "job_id": job["job_id"], "request_id": request_id})
                else:
                    self._send_json(409, {"error": "Yêu cầu này đang được xử lý.", "job_id": job["job_id"]})
                return
            try:
                with cancellation_scope(token):
                    _update_job(job, state="running", phase="script", phase_text="Đang viết kịch bản và phân cảnh...")
                    data = cancellable_call(generate_script_and_terms,
                        subject=subject,
                        duration_sec=duration_sec,
                        tone=tone,
                        cta=cta,
                        model_name=model_name,
                        feedback=feedback,
                        current_script=current_script,
                        current_scenes=params.get("current_scenes"),
                        aspect=params.get("aspect", "16:9"),
                        style=params.get("style", "whiteboard"),
                        voice_name=params.get("voice", ""),
                        **({"resume_narration": True} if params.get("resume_narration") is True and current_script else {}))
                    if params.get("auto_emotions") and data.get("script"):
                        try:
                            from emotion_tags import add_emotion_tags_with_ai
                            data["script"] = add_emotion_tags_with_ai(call_gemini, data["script"], tone=tone, model_name=model_name)
                        except Exception as tag_err:
                            logger.warning("Auto emotion tagging warning: %s", tag_err)
                    with JOB_LOCK:
                        check_cancelled()
                        job.update(state="completed", phase="completed", progress=100, result=data, finished_at=time.time())
                self._send_json(200, {"status": "success", "data": data, "job_id": job["job_id"], "request_id": request_id})
            except StudioCancelled:
                _mark_cancelled(job)
                self._send_json(200, {"status": "cancelled", "state": "cancelled", "job_id": job["job_id"], "request_id": request_id})
            except Exception as e:
                partial = getattr(e, "partial_data", None)
                partial = dict(partial) if isinstance(partial, dict) and isinstance(partial.get("script"), str) else None
                if partial:
                    partial.update(narration_incomplete=True, partial_subject=subject,
                                   partial_duration=duration_sec, partial_style=params.get("style", "whiteboard"), scenes=[])
                with JOB_LOCK:
                    cancelled = token.cancelled
                    if cancelled:
                        _mark_cancelled(job)
                    else:
                        job.update(state="failed", phase="failed", error=str(e), finished_at=time.time())
                        if partial:
                            job["result"] = partial
                self._send_json(200 if cancelled else 422 if partial else 500,
                                {"status": "cancelled", "state": "cancelled", "request_id": request_id}
                                if cancelled else {"error": str(e), "job_id": job["job_id"], "request_id": request_id,
                                                   **({"partial_data": partial} if partial else {})})
            return

        # 2. API Sản Xuất Video
        if decoded_path == "/api/produce-video":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                brief = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                brief = {}

            subject = brief.get("subject", "").strip()
            gem_key = brief.get("gemini_api_key", "").strip()
            elv_key = brief.get("elevenlabs_api_key", "").strip()
            if gem_key:
                update_system_keys(gemini_key=gem_key)
            if elv_key:
                update_system_keys(eleven_keys=[elv_key])

            if not subject:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Vui lòng nhập chủ đề video"}).encode("utf-8"))
                return

            try:
                brief["duration"] = parse_duration(brief.get("duration"))
                request_id = validate_request_id(brief.get("request_id"))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return

            job_id = str(uuid.uuid4())[:8]
            try:
                job, token, created = register_job(job_id, "video", subject, request_id)
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return
            if created and not token.cancelled:
                t = threading.Thread(target=run_video_job, args=(job["job_id"], brief), daemon=True)
                t.start()
            self._send_json(200, {"job_id": job["job_id"], "request_id": job["request_id"],
                                  "state": job["state"], "status": "cancelled" if token.cancelled else "started"})
            return

        self.send_error(404, "Endpoint not found")

    def serve_video_file(self, file_path: Path, as_attachment: bool = False):
        """Hỗ trợ HTTP 206 Partial Content (Range requests) cho Chrome/Edge/Safari & Download sạch"""
        try:
            file_size = file_path.stat().st_size
            content_type = {
                ".mp4": "video/mp4", ".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp",
            }.get(file_path.suffix.lower(), "application/octet-stream")
            range_header = self.headers.get("Range")
            
            disposition = "attachment" if as_attachment else "inline"
            safe_ascii_name = file_path.name.encode("ascii", "ignore").decode("ascii") or "video.mp4"
            disp_header = f'{disposition}; filename="{safe_ascii_name}"; filename*=UTF-8\'\'{urllib.parse.quote(file_path.name)}'

            if range_header:
                match = re.match(r"bytes=(\d+)-(\d*)", range_header)
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else file_size - 1
                    end = min(end, file_size - 1)
                    length = end - start + 1

                    self.send_response(206)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Content-Disposition", disp_header)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()

                    with open(file_path, "rb") as f:
                        f.seek(start)
                        rem = length
                        chunk_size = 64 * 1024
                        while rem > 0:
                            chunk = f.read(min(rem, chunk_size))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            rem -= len(chunk)
                    return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.send_header("Content-Disposition", disp_header)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            try:
                self.send_error(500, "Error streaming video")
            except Exception:
                pass


def main():
    os.chdir(OFFICE_DIR)
    host = os.environ.get("HOST", "0.0.0.0")
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer((host, PORT), OfficeHubHandler) as httpd:
        url = f"http://{host}:{PORT}/index.html"
        print("="*60)
        print("   MODERN 3D EXECUTIVE OFFICE & VIDEO HUB V4 IS LIVE (Multi-Threaded)!")
        print("="*60)
        print(f"URL: {url}")
        print("="*60)
        httpd.serve_forever()

if __name__ == "__main__":
    main()
