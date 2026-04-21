import os
import re
import time
import requests
import logging
import yt_dlp
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS

# Setup Mata-mata (Logging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Global Session untuk streaming CDN
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

# =============================================
# MESIN BARU: yt-dlp (gantikan tikwm untuk download)
# =============================================

YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'skip_download': True,         # Hanya ambil info, tidak download ke disk
    'noplaylist': True,
}

def extract_info_ytdlp(url):
    """
    Ekstrak info video TikTok pakai yt-dlp.
    Return dict: { url_video, title, thumbnail, duration, filesize, author }
    Raise Exception kalau gagal.
    """
    with yt_dlp.YoutubeDL(YDL_OPTS_BASE) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise Exception("yt-dlp tidak bisa mengambil info video")

    # Pilih format terbaik: video+audio, no watermark, mp4 lebih diutamakan
    formats = info.get('formats', [])
    
    best_url = None
    best_filesize = 0

    # Prioritas 1: format mp4 dengan video dan audio sekaligus (no watermark)
    for f in formats:
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        ext = f.get('ext', '')
        url_f = f.get('url', '')
        fsize = f.get('filesize') or f.get('filesize_approx') or 0
        
        if vcodec != 'none' and acodec != 'none' and ext == 'mp4' and url_f:
            if fsize > best_filesize:
                best_url = url_f
                best_filesize = fsize

    # Prioritas 2: format apapun yang punya video+audio
    if not best_url:
        for f in formats:
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            url_f = f.get('url', '')
            fsize = f.get('filesize') or f.get('filesize_approx') or 0
            if vcodec != 'none' and acodec != 'none' and url_f:
                if fsize > best_filesize:
                    best_url = url_f
                    best_filesize = fsize

    # Prioritas 3: format dengan video saja (fallback terakhir)
    if not best_url:
        for f in formats:
            vcodec = f.get('vcodec', 'none')
            url_f = f.get('url', '')
            if vcodec != 'none' and url_f:
                best_url = url_f
                break

    if not best_url:
        raise Exception("Tidak ada format video yang bisa diunduh (mungkin kreator menonaktifkan download atau video private)")

    # Ambil info author
    uploader = info.get('uploader') or info.get('creator') or info.get('channel') or 'User'

    # Thumbnail terbaik
    thumbnails = info.get('thumbnails', [])
    thumbnail = ''
    if thumbnails:
        thumbnail = thumbnails[-1].get('url', '') or info.get('thumbnail', '')
    if not thumbnail:
        thumbnail = info.get('thumbnail', '')

    return {
        'url_video': best_url,
        'title': info.get('title', 'Video TikTok'),
        'author': uploader,
        'thumbnail': thumbnail,
        'duration': info.get('duration'),
        'filesize': best_filesize,
    }

# =============================================
# ENDPOINTS
# =============================================

@app.route('/')
def index():
    return send_file('vinder.html')

@app.route('/api/search', methods=['POST'])
def search_videos_api():
    # Search tetap pakai tikwm — yt-dlp tidak support keyword search
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
            # Simpan video_id agar bisa di-resolve ulang via yt-dlp saat download
            vid_id = v.get('video_id') or v.get('id') or ''
            results.append({
                'title': v.get('title', 'Video TikTok'),
                'duration': format_durasi(v.get('duration')),
                'play': v.get('play', ''),
                'hdplay': v.get('hdplay', '') or v.get('play', ''),
                'video_id': vid_id,
                'tiktok_url': f"https://www.tiktok.com/video/{vid_id}" if vid_id else '',
                'cover': v.get('origin_cover') or v.get('cover') or '',
                'size': f"{round(v.get('size', 0)/(1024*1024), 2)} MB" if v.get('size') else "?"
            })
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/api/get_video')
def get_video_api():
    video_url = request.args.get('url')       # bisa CDN URL atau tiktok.com URL
    tiktok_url = request.args.get('tiktok_url', '')  # URL tiktok.com asli untuk fallback yt-dlp
    title = request.args.get('title', 'video')

    if not video_url: return "URL Kosong", 400

    logger.info(f"📥 Proxying video: {video_url[:60]}...")
    r = None
    try:
        # Coba stream CDN URL langsung dulu (cepat)
        r = session.get(video_url, stream=True, timeout=60, allow_redirects=True)

        # Kalau CDN expired (403/404) → pakai yt-dlp untuk dapat URL fresh
        if r.status_code in [403, 404]:
            logger.warning(f"⚠️ {r.status_code} — CDN expired, switching to yt-dlp...")
            
            # Gunakan tiktok_url kalau ada, fallback ke video_url
            resolve_url = tiktok_url if tiktok_url else video_url
            info = extract_info_ytdlp(resolve_url)
            fresh_url = info['url_video']
            
            logger.info(f"🔄 yt-dlp fresh URL didapat, retrying stream...")
            r = session.get(fresh_url, stream=True, timeout=60, allow_redirects=True)

        r.raise_for_status()

        safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title)[:40] or 'video'
        filename = f"VidFinder_{safe_title}_{int(time.time())}.mp4"

        def generate():
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
        logger.error(f"💥 Download Error: {str(e)}")
        return f"Gagal mengambil video: {str(e)}", 500

@app.route('/api/download_url', methods=['POST'])
def download_url_api():
    data = request.json
    url_input = data.get('url')
    logger.info(f"🔗 Processing URL via yt-dlp: {url_input}")
    try:
        # yt-dlp langsung resolve TikTok URL — dapat URL CDN fresh tiap saat
        info = extract_info_ytdlp(url_input)

        filesize_mb = f"{round(info['filesize'] / (1024*1024), 2)} MB" if info['filesize'] else "?"

        return jsonify({
            "status": "success",
            "url": info['url_video'],
            "play": info['url_video'],
            "hdplay": info['url_video'],
            "title": info['title'],
            "author": info['author'],
            "duration": format_durasi(info['duration']),
            "size": filesize_mb,
            "cover": info['thumbnail'],
            # Sertakan tiktok_url asli untuk fallback di get_video jika CDN expired
            "tiktok_url": url_input,
        })
    except Exception as e:
        logger.error(f"💥 Download URL Error: {str(e)}")
        return jsonify({"status": "error", "msg": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
