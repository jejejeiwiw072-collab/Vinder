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

# Global Session untuk performa dan konsistensi
session = requests.Session()
DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Accept": "video/mp4,video/*;q=0.9,audio/*;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Referer": "https://www.tiktok.com/",
    "Origin": "https://www.tiktok.com/"
}
session.headers.update(DOWNLOAD_HEADERS)

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    if 'refresh' in request.args:
        response.headers['Clear-Site-Data'] = '"cache", "cookies", "storage"'
    return response

def format_durasi(detik):
    if detik is None: return "?"
    try:
        m, s = divmod(int(detik), 60)
        return f"{m}m{s:02d}s"
    except: return "?"

@app.route('/')
def index():
    return send_file('vinder.html')

@app.route('/api/search', methods=['POST'])
def search_videos_api():
    data = request.json
    keyword = data.get('keyword')
    limit = data.get('limit', 10)
    logger.info(f"🔍 Searching: {keyword}")
    try:
        resp = session.post("https://www.tikwm.com/api/feed/search", 
                           data={"keywords": keyword, "count": limit, "HD": 1},
                           timeout=30)
        resp.raise_for_status()
        json_data = resp.json()
        
        if json_data.get('code') != 0:
            return jsonify({"status": "error", "msg": f"TikWM: {json_data.get('msg')}"})

        videos = json_data.get('data', {}).get('videos', [])
        results = []
        for v in videos:
            results.append({
                'title': v.get('title', 'Video TikTok'),
                'duration': format_durasi(v.get('duration')),
                'play': v.get('play', ''),
                'hdplay': v.get('hdplay', '') or v.get('play', ''),
                'cover': v.get('origin_cover') or v.get('cover') or '',
                'size': f"{round(v.get('size', 0)/(1024*1024), 2)} MB" if v.get('size') else "?"
            })
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/api/get_video')
def get_video_api():
    video_url = request.args.get('url')
    title = request.args.get('title', 'video')
    
    if not video_url: return "URL Kosong", 400

    logger.info(f"📥 Proxying video: {video_url[:60]}...")
    try:
        # Coba request pertama
        r = session.get(video_url, stream=True, timeout=60, allow_redirects=True)
        
        # Fallback jika 403/404 (Sering terjadi jika CDN token kadaluarsa)
        if r.status_code in [403, 404]:
            logger.warning(f"⚠️ {r.status_code} detected, retrying with fresh session...")
            r = requests.get(video_url, stream=True, timeout=60, allow_redirects=True, headers=DOWNLOAD_HEADERS)
            
        r.raise_for_status()

        # Pastikan kita mengirimkan MP4
        safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title)[:40] or 'video'
        filename = f"VidFinder_{safe_title}_{int(time.time())}.mp4"

        def generate():
            # Chunk size 512KB seimbang antara speed dan kestabilan
            for chunk in r.iter_content(chunk_size=512*1024):
                if chunk: yield chunk

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "video/mp4",
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Expose-Headers": "Content-Length"
        }
        
        cl = r.headers.get('Content-Length')
        if cl: headers["Content-Length"] = cl

        return Response(stream_with_context(generate()), headers=headers)
    except Exception as e:
        logger.error(f"💥 Proxy Error: {str(e)}")
        return f"Gagal mengambil video: {str(e)}", 500

@app.route('/api/download_url', methods=['POST'])
def download_url_api():
    data = request.json
    url_input = data.get('url')
    logger.info(f"🔗 Processing URL: {url_input}")
    try:
        resp = session.post("https://www.tikwm.com/api/", data={"url": url_input, "hd": 1}, timeout=30)
        resp.raise_for_status()
        json_data = resp.json()
        
        if json_data.get('code') != 0:
            return jsonify({"status": "error", "msg": f"TikWM: {json_data.get('msg')}"})

        d = json_data.get('data', {})
        target_url = d.get('hdplay') or d.get('play')
        
        if not target_url:
            return jsonify({"status": "error", "msg": "Video URL tidak ditemukan"})

        return jsonify({
            "status": "success",
            "url": target_url,
            "play": d.get('play'),
            "hdplay": d.get('hdplay'),
            "title": d.get('title', 'video'),
            "author": d.get('author', {}).get('nickname', 'User'),
            "duration": format_durasi(d.get('duration')),
            "size": f"{round(d.get('size', 0)/(1024*1024), 2)} MB" if d.get('size') else "?",
            "cover": d.get('origin_cover') or d.get('cover') or ''
        })
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
