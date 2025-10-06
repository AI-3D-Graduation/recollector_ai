import os
import io
import json
import base64
import logging
from datetime import datetime
from uuid import uuid4

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flasgger import Swagger
from dotenv import load_dotenv
import requests
import trimesh


# --------------------------------------
# App config
# --------------------------------------
load_dotenv()

APP_PORT = int(os.getenv("PORT", "5001"))
MESHY_API_KEY = os.getenv("MESHY_API_KEY")
MESHY_API_URL = os.getenv("MESHY_API_URL", "https://api.meshy.ai/openapi/v1/image-to-3d")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Swagger configuration
swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "이미지를 3D로 변환하는 API",
        "description": "Meshy.ai를 통해 이미지를 3D 모델로 변환하는 REST API입니다. 파일 업로드 및 JSON 입력을 지원합니다.",
        "version": "1.0.0",
    },
    "basePath": "/",
}
Swagger(app, template=swagger_template)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app_flask")


def _meshy_headers():
    if not MESHY_API_KEY:
        raise RuntimeError(
            "MESHY_API_KEY가 설정되지 않았습니다. 환경 변수나 .env 파일에 키를 추가해주세요."
        )
    return {"Authorization": f"Bearer {MESHY_API_KEY}"}


def _save_meta(task_id: str, meta: dict):
    task_dir = os.path.join(OUTPUTS_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    meta_path = os.path.join(task_dir, "meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to write meta for %s: %s", task_id, e)

# 단순히 백엔드가 살아있는지 확인하는 API
@app.get("/health")
def health():
    """Health check
    ---
    tags:
      - misc
    responses:
      200:
        description: Service is healthy
        schema:
          type: object
          properties:
            status:
              type: string
            service:
              type: string
    """
    return jsonify({"status": "ok", "service": "image-to-3d-backend"})

# 이미지를 3D로 변환하는 작업 생성 API
@app.post("/api/process-image")
def process_image():
    """Create a Meshy image-to-3D job.

    Accepts:
      - multipart/form-data with file field 'image' and optional flags
      - application/json with fields: image_base64 or image_url, and flags

    Returns: { task_id: string }
    ---
    tags:
      - processing
    consumes:
      - multipart/form-data
      - application/json
    parameters:
      - in: formData
        name: image
        type: file
        required: false
        description: Image file (jpg/png)
      - in: formData
        name: enable_pbr
        type: boolean
        required: false
        default: true
      - in: formData
        name: should_remesh
        type: boolean
        required: false
        default: true
      - in: formData
        name: should_texture
        type: boolean
        required: false
        default: true
      - in: formData
        name: ai_model
        type: string
        enum: [latest, meshy-5]
        required: false
        default: latest
        description: AI model to use (latest is recommended)
      - in: body
        name: json
        required: false
        schema:
          type: object
          properties:
            image_base64:
              type: string
              description: Base64 image string (optionally prefixed with data:image/*;base64,)
            image_url:
              type: string
              description: Directly accessible image URL
            enable_pbr:
              type: boolean
            should_remesh:
              type: boolean
            should_texture:
              type: boolean
            ai_model:
              type: string
              enum: [latest, meshy-5]
              default: latest
              description: AI model to use (latest is recommended)
    responses:
      202:
        description: Job created
        schema:
          type: object
          properties:
            task_id:
              type: string
      4XX:
        description: Client error
      5XX:
        description: Server error
    """
    try:
        # Parse flags (default True to match Streamlit defaults)
        def get_flag(name: str, default=True):
            if request.is_json:
                val = (request.json or {}).get(name, default)
            else:
                val = request.form.get(name, str(default)).lower() if name in request.form else default
                if isinstance(val, str):
                    val = val in ("1", "true", "on", "yes")
            return bool(val)

        enable_pbr = get_flag("enable_pbr", True)
        should_remesh = get_flag("should_remesh", True)
        should_texture = get_flag("should_texture", True)
        
        # Parse ai_model (default to "latest")
        if request.is_json:
            ai_model = (request.json or {}).get("ai_model", "latest")
        else:
            ai_model = request.form.get("ai_model", "latest")
        # Validate ai_model
        if ai_model not in ["latest", "meshy-5"]:
            ai_model = "latest"

        # Parse image input
        image_bytes = None
        image_data_url = None
        original_filename = None

        if request.content_type and request.content_type.startswith("multipart/form-data"):
            file = request.files.get("image")
            if file and getattr(file, "filename", ""):
                image_bytes = file.read()
                original_filename = file.filename
        elif request.is_json:
            data = request.get_json(silent=True) or {}
            b64 = data.get("image_base64")
            image_url_direct = data.get("image_url")
            if b64:
                # Allow optional prefix like data:image/png;base64,....
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                image_bytes = base64.b64decode(b64)
            elif image_url_direct:
                # If caller provides a remote URL, pass it straight through
                image_data_url = image_url_direct
        else:
            return jsonify({"error": "Unsupported content type"}), 415

        if image_bytes is None and image_data_url is None:
            return jsonify({"error": "No image provided. Use multipart 'image' or JSON 'image_base64'/'image_url'."}), 400

        # Form data URL if needed
        if image_data_url is None and image_bytes is not None:
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")
            image_data_url = f"data:image/png;base64,{img_b64}"

        # Optionally persist upload
        if image_bytes is not None:
            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            up_id = f"{stamp}_{uuid4().hex[:8]}"
            try:
                with open(os.path.join(UPLOADS_DIR, f"{up_id}_{original_filename or 'upload'}.bin"), "wb") as f:
                    f.write(image_bytes)
            except Exception:
                pass

        # Call Meshy
        payload = {
            "image_url": image_data_url,
            "enable_pbr": enable_pbr,
            "should_remesh": should_remesh,
            "should_texture": should_texture,
            "ai_model": ai_model,
        }

        resp = requests.post(MESHY_API_URL, headers=_meshy_headers(), json=payload, timeout=60)
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = {"text": resp.text}
            return jsonify({"error": "Meshy create failed", "detail": detail}), resp.status_code

        task_id = (resp.json() or {}).get("result")
        if not task_id:
            return jsonify({"error": "Invalid Meshy response", "detail": resp.json()}), 502

        _save_meta(
            task_id,
            {
                "original_filename": original_filename,
                "options": {
                    "enable_pbr": enable_pbr,
                    "should_remesh": should_remesh,
                    "should_texture": should_texture,
                    "ai_model": ai_model,
                },
            },
        )

        return jsonify({"task_id": task_id}), 202
    except RuntimeError as re:
        return jsonify({"error": str(re)}), 500
    except Exception as e:
        logger.exception("/api/process-image failed")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500

# 3D 작업 상태 조회 API
@app.get("/api/status/<task_id>")
def get_status(task_id: str):
    """Get job status
    ---
    tags:
      - processing
    parameters:
      - in: path
        name: task_id
        type: string
        required: true
        description: Meshy task identifier returned by create API
    responses:
      200:
        description: Current job status
        schema:
          type: object
          properties:
            status:
              type: string
            progress:
              type: number
            message:
              type: string
            model_urls:
              type: object
              properties:
                glb:
                  type: string
      4XX:
        description: Client error
      5XX:
        description: Server error
    """
    try:
        url = f"{MESHY_API_URL}/{task_id}"
        resp = requests.get(url, headers=_meshy_headers(), timeout=30)
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = {"text": resp.text}
            return jsonify({"error": "Meshy status failed", "detail": detail}), resp.status_code
        data = resp.json() or {}
        # Pass through relevant fields
        return jsonify({
            "status": data.get("status"),
            "progress": data.get("progress"),
            "message": data.get("message"),
            "model_urls": data.get("model_urls"),
        })
    except RuntimeError as re:
        return jsonify({"error": str(re)}), 500
    except Exception as e:
        logger.exception("/api/status failed")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500

# 3D 모델 다운로드 및 포맷 변환 API
@app.get("/api/result/<task_id>")
def get_result(task_id: str):
    """Get the generated model
    Download the generated model in desired format.

    ---
    tags:
      - processing
    parameters:
      - in: path
        name: task_id
        type: string
        required: true
      - in: query
        name: format
        type: string
        enum: [glb, obj, ply]
        default: glb
        description: Model format to return
    produces:
      - application/octet-stream
      - model/gltf-binary
    responses:
      200:
        description: Model file stream
      409:
        description: Job not completed
      5XX:
        description: Server error
    """
    fmt = (request.args.get("format") or "glb").lower()
    if fmt not in {"glb", "obj", "ply"}:
        return jsonify({"error": "Unsupported format", "allowed": ["glb", "obj", "ply"]}), 400

    try:
        # Check status to get model URL
        status_url = f"{MESHY_API_URL}/{task_id}"
        sresp = requests.get(status_url, headers=_meshy_headers(), timeout=30)
        if not sresp.ok:
            return jsonify({"error": "Failed to get status from Meshy"}), sresp.status_code
        sdata = sresp.json() or {}
        if sdata.get("status") != "SUCCEEDED":
            return jsonify({"error": "Job not completed", "status": sdata.get("status")}), 409

        model_url = (sdata.get("model_urls") or {}).get("glb")
        if not model_url:
            return jsonify({"error": "GLB URL missing in Meshy response"}), 502

        glb_bytes = requests.get(model_url, timeout=180).content

        if fmt == "glb":
            return send_file(
                io.BytesIO(glb_bytes),
                mimetype="model/gltf-binary",
                as_attachment=False,
                download_name=f"{task_id}.glb",
                max_age=0,
                last_modified=datetime.utcnow(),
            )

        # Convert to other formats
        try:
            scene_or_mesh = trimesh.load(io.BytesIO(glb_bytes), file_type="glb")
            buf = io.BytesIO()
            scene_or_mesh.export(buf, file_type=fmt)
            out_bytes = buf.getvalue()
        except Exception as ce:
            logger.exception("Conversion to %s failed", fmt)
            return jsonify({"error": f"Conversion to {fmt} failed", "detail": str(ce)}), 500

        return send_file(
            io.BytesIO(out_bytes),
            mimetype="application/octet-stream",
            as_attachment=False,
            download_name=f"{task_id}.{fmt}",
            max_age=0,
            last_modified=datetime.utcnow(),
        )

    except RuntimeError as re:
        return jsonify({"error": str(re)}), 500
    except Exception as e:
        logger.exception("/api/result failed")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500

# 앱 실행
if __name__ == "__main__":
    # Use 0.0.0.0 so the React dev server can reach it from another host if needed
    # Disable debug/reloader in this run mode for stability during smoke tests
    app.run(host="0.0.0.0", port=APP_PORT, debug=False)

# 실행 후 Swagger UI에서 테스트: http://127.0.0.1:5001/apidocs

