import os
import re
import time
import requests
from flask import Flask, request, jsonify, send_file, after_this_request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Folder buat simpan sementara
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

def pilih_url_video(data_video, mode='HYPE v1.2'):
    hd_url = data_video.get('hdplay', '').strip()
    sd_url = data_video.get('play', '').strip()
    if mode == 'HYPE v1.2':
        return hd_url if hd_url.startswith('http') else sd_url
    return sd_url if sd_url.startswith('http') else hd_url

@app.route('/')
def index():
    return send_file('vinder.html')

@app.route('/api/search', methods=['POST'])
def search_videos_api():
    data = request.json
    try:
        resp = requests.post("https://www.tikwm.com/api/feed/search", 
                             data={"keywords": data.get('keyword'), "count": data.get('limit', 10), "HD": 1})
        videos = resp.json().get('data', {}).get('videos', [])
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
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

# ENDPOINT BARU: Download via GET (Lebih stabil buat browser)
@app.route('/api/get_video')
def get_video_api():
    video_url = request.args.get('url')
    title = request.args.get('title', 'video')
    mode = request.args.get('mode', 'HYPE v1.2')
    
    if not video_url:
        return "URL tidak ditemukan", 400

    try:
        safe_title = re.sub(r'[\\/*?:"<>|]', '', title)[:30].strip() or 'video'
        timestamp = int(time.time())
        prefix = "HYPE" if mode == 'HYPE v1.2' else "STD"
        safe_filename = f"[{prefix}]_{safe_title}_{timestamp}.mp4"
        filepath = os.path.join(DOWNLOAD_FOLDER, safe_filename)

        # Download dari TikTok ke server kita dulu
        r = requests.get(video_url, stream=True, timeout=120, headers=DOWNLOAD_HEADERS)
        r.raise_for_status()

        with open(filepath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk: f.write(chunk)
        
        @after_this_request
        def cleanup(response):
            try:
                if os.path.exists(filepath): os.remove(filepath)
            except: pass
            return response

        return send_file(filepath, as_attachment=True, download_name=safe_filename)
    except Exception as e:
        return str(e), 500

@app.route('/api/download_url', methods=['POST'])
def download_url_api():
    data = request.json
    url_input = data.get('url')
    mode = data.get('resolution', 'HYPE v1.2')
    try:
        resp = requests.post("https://www.tikwm.com/api/", data={"url": url_input, "hd": 1})
        d = resp.json().get('data', {})
        v_url = pilih_url_video(d, mode)
        # Kirim balik URL aslinya biar frontend yang handle download-nya
        return jsonify({
            "status": "success", 
            "url": v_url, 
            "title": d.get('title', 'video')
        })
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
