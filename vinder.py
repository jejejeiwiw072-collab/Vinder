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

def pilih_url_video(data_video, mode='1080p'):
    """
    LOGIKA GAP BENTO:
    HYPE v1.2 -> HD Tanpa Batas (hdplay)
    Standard -> Max 720p (play)
    """
    hd_url = data_video.get('hdplay', '').strip()
    sd_url = data_video.get('play', '').strip()

    if mode == 'HYPE v1.2':
        url = hd_url if hd_url.startswith('http') else sd_url
        return url, 'HYPE_V1.2_ULTRA'
    else:
        # Standard: Ambil kualitas biasa (play link umumnya terkompresi)
        url = sd_url if sd_url.startswith('http') else hd_url
        return url, 'STANDARD_720p'

def _do_download(video_obj, mode='1080p'):
    folder = 'downloads/'
    os.makedirs(folder, exist_ok=True)

    video_url, engine = pilih_url_video(video_obj, mode)
    if not video_url:
        raise ValueError("URL video tidak ditemukan")

    safe_title = re.sub(r'[\\/*?:"<>|]', '', video_obj.get('title', 'video'))[:50].strip() or 'video'
    prefix = "[HYPE]_" if mode == 'HYPE v1.2' else "[STD]_"
    safe_filename = f"{prefix}{safe_title}_{video_obj.get('id', 'id')}.mp4"
    filepath = os.path.join(folder, safe_filename)

    # HYPE v1.2: Timeout lebih panjang & Turbo Chunking
    timeout_val = (15, 120) if mode == 'HYPE v1.2' else (5, 60)
    chunk_size = 1024 * 1024 if mode == 'HYPE v1.2' else 128 * 1024 # 1MB vs 128KB

    r = requests.get(video_url, stream=True, timeout=timeout_val, headers=DOWNLOAD_HEADERS)
    r.raise_for_status()

    with open(filepath, 'wb') as f:
        for chunk in r.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)

    return filepath, safe_filename

@app.route('/api/search', methods=['POST'])
def search_videos_api():
    data = request.json
    query = data.get('keyword', '')
    limit = int(data.get('limit', 5))
    
    try:
        resp = requests.post("https://www.tikwm.com/api/feed/search", 
                             data={"keywords": query, "count": limit, "HD": 1}, timeout=15)
        api_data = resp.json()
        videos = api_data.get('data', {}).get('videos', [])
        
        results = []
        for v in videos:
            results.append({
                'title': v.get('title', 'Video TikTok'),
                'id': v.get('id', ''),
                'link': f"https://www.tiktok.com/@{v.get('author',{}).get('unique_id')}/video/{v.get('id')}",
                'duration': format_durasi(v.get('duration')),
                'channel': v.get('author', {}).get('nickname', 'Unknown'),
                'play': v.get('play', ''),
                'hdplay': v.get('hdplay', '')
            })
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/api/download', methods=['POST'])
def download_video_api():
    data = request.json
    mode = data.get('resolution', '1080p')
    try:
        filepath, safe_filename = _do_download(data, mode)
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

    @after_this_request
    def remove_file(response):
        if os.path.exists(filepath): os.remove(filepath)
        return response

    return send_file(filepath, as_attachment=True, download_name=safe_filename, mimetype='video/mp4')

@app.route('/api/download_url', methods=['POST'])
def download_url_api():
    data = request.json
    url = data.get('url', '').strip()
    mode = data.get('resolution', '1080p')
    
    try:
        resp = requests.post("https://www.tikwm.com/api/", data={"url": url, "hd": 1}, timeout=15)
        d = resp.json().get('data', {})
        video_obj = {'title': d.get('title', 'Video'), 'id': d.get('id', ''), 'play': d.get('play', ''), 'hdplay': d.get('hdplay', '')}
        filepath, safe_filename = _do_download(video_obj, mode)
        
        @after_this_request
        def remove_file(response):
            if os.path.exists(filepath): os.remove(filepath)
            return response
        return send_file(filepath, as_attachment=True, download_name=safe_filename, mimetype='video/mp4')
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
