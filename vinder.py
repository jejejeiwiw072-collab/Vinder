import os
import re
import time
import requests
import logging
import traceback
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS

# Setup Mata-mata (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = 'downloads/'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.tikwm.com/",
}

def format_durasi(detik):
    if detik is None: return "?"
    m, s = divmod(int(detik), 60)
    return f"{m}m{s:02d}s"

@app.route('/')
def index():
    return send_file('vinder.html')

@app.route('/api/search', methods=['POST'])
def search_videos_api():
    data = request.json
    keyword = data.get('keyword')
    logger.info(f"🔍 Searching for: {keyword}")
    try:
        resp = requests.post("https://www.tikwm.com/api/feed/search", 
                             data={"keywords": keyword, "count": data.get('limit', 10), "HD": 1},
                             timeout=30)
        resp.raise_for_status()
        json_data = resp.json()
        
        if json_data.get('code') != 0:
            msg = json_data.get('msg', 'API TikWM return non-zero code')
            logger.error(f"❌ TikWM API Error: {msg}")
            return jsonify({"status": "error", "msg": f"TikWM API: {msg}"})

        videos = json_data.get('data', {}).get('videos', [])
        results = []
        for v in videos:
            cover_url = v.get('origin_cover') or v.get('cover') or ''
            size_bytes = v.get('size', 0)
            size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes else "?"
            
            results.append({
                'title': v.get('title', 'Video TikTok'),
                'id': v.get('id', ''),
                'duration': format_durasi(v.get('duration')),
                'channel': v.get('author', {}).get('nickname', 'User'),
                'play': v.get('play', ''),
                'hdplay': v.get('hdplay', ''),
                'cover': cover_url,
                'size': f"{size_mb} MB"
            })
        logger.info(f"✅ Found {len(results)} videos")
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        err_msg = f"Search Error: {str(e)}"
        logger.error(f"💥 {err_msg}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "msg": err_msg})

@app.route('/api/get_video')
def get_video_api():
    video_url = request.args.get('url')
    title = request.args.get('title', 'video')
    mode = request.args.get('mode', 'HYPE v1.2')
    
    if not video_url:
        logger.warning("⚠️ Download failed: No URL provided")
        return "URL tidak ditemukan", 400

    logger.info(f"📥 Starting download: {title} ({mode})")
    try:
        safe_title = re.sub(r'[\\/*?:"<>|]', '', title)[:30].strip() or 'video'
        timestamp = int(time.time() * 1000)
        prefix = "HYPE" if "HYPE" in mode else "STD"
        safe_filename = f"[{prefix}]_{safe_title}_{timestamp}.mp4"
        filepath = os.path.join(DOWNLOAD_FOLDER, safe_filename)

        # Download dari TikTok ke Server
        logger.info(f"🔗 Fetching from TikTok: {video_url[:50]}...")
        r = requests.get(video_url, stream=True, timeout=120, headers=DOWNLOAD_HEADERS)
        r.raise_for_status()

        with open(filepath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk: f.write(chunk)
        
        logger.info(f"💾 File saved locally: {filepath} ({os.path.getsize(filepath)} bytes)")

        def generate():
            try:
                with open(filepath, 'rb') as f:
                    yield from f
                logger.info(f"📤 Stream to client finished: {safe_filename}")
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    logger.info(f"🗑️ Temporary file deleted: {filepath}")

        return Response(
            stream_with_context(generate()),
            headers={
                "Content-Disposition": f'attachment; filename="{safe_filename}"',
                "Content-Type": "video/mp4",
                "Content-Length": os.path.getsize(filepath)
            }
        )
    except Exception as e:
        err_msg = f"Download Error: {str(e)}"
        logger.error(f"💥 {err_msg}\n{traceback.format_exc()}")
        return err_msg, 500

@app.route('/api/download_url', methods=['POST'])
def download_url_api():
    data = request.json
    url_input = data.get('url')
    logger.info(f"🔗 Processing URL download: {url_input}")
    try:
        resp = requests.post("https://www.tikwm.com/api/", data={"url": url_input, "hd": 1}, timeout=30)
        resp.raise_for_status()
        json_data = resp.json()
        
        if json_data.get('code') != 0:
            msg = json_data.get('msg', 'API TikWM return non-zero code')
            logger.error(f"❌ TikWM URL Error: {msg}")
            return jsonify({"status": "error", "msg": f"TikWM: {msg}"})

        d = json_data.get('data', {})
        target_url = d.get('hdplay') or d.get('play')
        
        if not target_url:
            logger.error("❌ No play URL found in TikWM response")
            return jsonify({"status": "error", "msg": "Video URL tidak ditemukan dalam respon API"})

        logger.info(f"✅ URL Resolved: {target_url[:50]}...")
        return jsonify({
            "status": "success",
            "url": target_url,
            "title": d.get('title', 'video')
        })
    except Exception as e:
        err_msg = f"URL Resolve Error: {str(e)}"
        logger.error(f"💥 {err_msg}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "msg": err_msg})

if __name__ == "__main__":
    logger.info("🚀 VidFinder System Backend Started on port 5000")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), threaded=True)
