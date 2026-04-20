import os
import re
import requests
from flask import Flask, request, jsonify, send_file, after_this_request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

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
        # Prioritas HD Asli (No Limit)
        url = hd_url if hd_url.startswith('http') else sd_url
        return url
    else:
        # Standard: Paksa pakai link 'play' (Max 720p compressed)
        url = sd_url if sd_url.startswith('http') else hd_url
        return url

def _do_download(video_obj, mode='HYPE v1.2'):
    folder = 'downloads/'
    os.makedirs(folder, exist_ok=True)
    video_url = pilih_url_video(video_obj, mode)

    if not video_url:
        raise ValueError("URL video tidak ditemukan")

    safe_title = re.sub(r'[\\/*?:"<>|]', '', video_obj.get('title', 'video'))[:50].strip() or 'video'
    prefix = "[HYPE]_" if mode == 'HYPE v1.2' else "[STD]_"
    safe_filename = f"{prefix}{safe_title}_{video_obj.get('id', 'id')}.mp4"
    filepath = os.path.join(folder, safe_filename)

    # Speed Gap: HYPE 1MB Chunk, STD 128KB
    chunk_size = 1024 * 1024 if mode == 'HYPE v1.2' else 128 * 1024
    
    r = requests.get(video_url, stream=True, timeout=120, headers=DOWNLOAD_HEADERS)
    r.raise_for_status()

    with open(filepath, 'wb') as f:
        for chunk in r.iter_content(chunk_size=chunk_size):
            if chunk: f.write(chunk)
    return filepath, safe_filename

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
            # === TAMBAHAN: Ambil URL cover (origin_cover prioritas) ===
            cover_url = v.get('origin_cover') or v.get('cover') or ''
            # =========================================================
            results.append({
                'title': v.get('title', 'Video TikTok'),
                'id': v.get('id', ''),
                'link': f"https://www.tiktok.com/@{v.get('author',{}).get('unique_id')}/video/{v.get('id')}",
                'duration': format_durasi(v.get('duration')),
                'channel': v.get('author', {}).get('nickname', 'User'),
                'play': v.get('play', ''),
                'hdplay': v.get('hdplay', ''),
                'cover': cover_url   # <-- tambahan field
            })
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/api/download', methods=['POST'])
def download_api():
    data = request.json
    mode = data.get('resolution', 'HYPE v1.2')
    try:
        filepath, safe_filename = _do_download(data, mode)
        @after_this_request
        def remove_file(response):
            if os.path.exists(filepath): os.remove(filepath)
            return response
        return send_file(filepath, as_attachment=True, download_name=safe_filename)
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/download_url', methods=['POST'])
def download_url_api():
    data = request.json
    try:
        resp = requests.post("https://www.tikwm.com/api/", data={"url": data.get('url'), "hd": 1})
        d = resp.json().get('data', {})
        v_obj = {'title': d.get('title'), 'id': d.get('id'), 'play': d.get('play'), 'hdplay': d.get('hdplay')}
        filepath, safe_filename = _do_download(v_obj, data.get('resolution', 'HYPE v1.2'))
        @after_this_request
        def remove_file(response):
            if os.path.exists(filepath): os.remove(filepath)
            return response
        return send_file(filepath, as_attachment=True, download_name=safe_filename)
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)