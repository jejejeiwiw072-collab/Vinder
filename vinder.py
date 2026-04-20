import os
import re
import time
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
        return hd_url if hd_url.startswith('http') else sd_url
    return sd_url if sd_url.startswith('http') else hd_url

def _do_download(video_obj, mode='HYPE v1.2'):
    folder = 'downloads/'
    if not os.path.exists(folder):
        os.makedirs(folder)
        
    video_url = pilih_url_video(video_obj, mode)
    if not video_url:
        raise ValueError("URL video tidak ditemukan")

    # Nama file unik pake timestamp biar gak bentrok pas download barengan
    safe_title = re.sub(r'[\\/*?:"<>|]', '', video_obj.get('title', 'video'))[:30].strip() or 'video'
    timestamp = int(time.time())
    prefix = "HYPE" if mode == 'HYPE v1.2' else "STD"
    safe_filename = f"[{prefix}]_{safe_title}_{timestamp}.mp4"
    filepath = os.path.join(folder, safe_filename)

    chunk_size = 1024 * 1024 # 1MB biar kenceng
    
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
            cover_url = v.get('origin_cover') or v.get('cover') or ''
            size_bytes = v.get('size', 0)
            size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes else "?"
            
            results.append({
                'title': v.get('title', 'Video TikTok'),
                'id': v.get('id', ''),
                'link': f"https://www.tiktok.com/@{v.get('author',{}).get('unique_id')}/video/{v.get('id')}",
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

@app.route('/api/download', methods=['POST'])
def download_api():
    data = request.json
    mode = data.get('resolution', 'HYPE v1.2')
    try:
        filepath, safe_filename = _do_download(data, mode)
        
        @after_this_request
        def remove_file(response):
            # Kita kasih delay dikit atau pastiin file ada sebelum hapus
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
            return response
            
        return send_file(filepath, as_attachment=True, download_name=safe_filename)
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/download_url', methods=['POST'])
def download_url_api():
    data = request.json
    mode = data.get('resolution', 'HYPE v1.2')
    try:
        resp = requests.post("https://www.tikwm.com/api/", data={"url": data.get('url'), "hd": 1})
        d = resp.json().get('data', {})
        v_obj = {'title': d.get('title'), 'id': d.get('id'), 'play': d.get('play'), 'hdplay': d.get('hdplay')}
        
        filepath, safe_filename = _do_download(v_obj, mode)
        
        @after_this_request
        def remove_file(response):
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
            return response
            
        return send_file(filepath, as_attachment=True, download_name=safe_filename)
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    # Gunakan threaded=True supaya bisa handle banyak download sekaligus
    app.run(host='0.0.0.0', port=port, threaded=True)
