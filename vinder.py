import os
import re
import time
import requests
import logging
import traceback
import io
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
    # Accept-Encoding SENGAJA DIHAPUS — biarkan requests handle decompression otomatis
    # Kalau dipaksa 'identity', CDN TikTok kadang kirim data corrupt/incomplete
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

def is_audio_only(response):
    """Deteksi apakah response dari CDN adalah audio-only."""
    ct = response.headers.get('Content-Type', '').lower()
    if ct.startswith('audio/'):
        return True
    cd = response.headers.get('Content-Disposition', '').lower()
    if any(ext in cd for ext in ['.m4a', '.aac', '.mp3']):
        return True
    return False

def download_full(url, max_retries=3):
    """
    Download FULL video ke memory buffer terlebih dahulu.
    - Tidak pakai stream langsung ke client agar tidak ada data terpotong
    - Validasi total bytes vs Content-Length CDN (harus >= 90%)
    - Retry otomatis jika bytes tidak lengkap
    Returns: (BytesIO buffer, content_type) atau raise Exception
    """
    for attempt in range(1, max_retries + 1):
        logger.info(f"📥 Download attempt {attempt}/{max_retries}: {url[:60]}...")
        try:
            r = session.get(url, stream=True, timeout=120, allow_redirects=True)

            # Retry dengan fresh session jika 403/404
            if r.status_code in [403, 404]:
                logger.warning(f"⚠️ {r.status_code} on attempt {attempt}, retrying with fresh session...")
                r = requests.get(url, stream=True, timeout=120, allow_redirects=True, headers=DOWNLOAD_HEADERS)

            r.raise_for_status()

            if is_audio_only(r):
                raise ValueError(f"URL mengembalikan audio-only. Content-Type: {r.headers.get('Content-Type')}")

            # Ambil Content-Length dari CDN sebagai referensi validasi
            expected_size = None
            cl_header = r.headers.get('Content-Length')
            if cl_header:
                try:
                    expected_size = int(cl_header)
                except:
                    pass

            # Download FULL ke buffer — jangan stream langsung ke client
            buffer = io.BytesIO()
            for chunk in r.iter_content(chunk_size=512 * 1024):
                if chunk:
                    buffer.write(chunk)

            actual_size = buffer.tell()
            logger.info(f"📦 Downloaded: {actual_size} bytes (expected: {expected_size})")

            # Validasi kelengkapan data — harus >= 90% dari Content-Length CDN
            if expected_size and actual_size < expected_size * 0.90:
                logger.warning(f"⚠️ Incomplete! Got {actual_size}/{expected_size} bytes ({round(actual_size/expected_size*100)}%). Retrying...")
                buffer.close()
                continue  # Retry

            # Data lengkap, kembalikan buffer dari awal
            buffer.seek(0)
            content_type = r.headers.get('Content-Type', 'video/mp4')
            logger.info(f"✅ Download complete: {actual_size} bytes")
            return buffer, content_type

        except ValueError:
            raise  # Audio-only, jangan retry
        except Exception as e:
            logger.error(f"💥 Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                raise
            time.sleep(1)

    raise Exception(f"Gagal download setelah {max_retries} percobaan")

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
    fallback_url = request.args.get('fallback')  # URL fallback (play SD) jika utama gagal
    title = request.args.get('title', 'video')

    if not video_url: return "URL Kosong", 400

    logger.info(f"📥 Processing video: {video_url[:60]}...")
    try:
        # Coba download URL utama (hdplay/wmplay) dulu
        try:
            buffer, content_type = download_full(video_url)
            logger.info(f"✅ Berhasil dari URL utama")
        except Exception as e:
            # Jika gagal dan ada fallback, coba fallback (play SD)
            if fallback_url and fallback_url != video_url:
                logger.warning(f"⚠️ URL utama gagal ({e}), mencoba fallback...")
                buffer, content_type = download_full(fallback_url)
                logger.info(f"✅ Berhasil dari fallback URL")
            else:
                raise

        safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title)[:40] or 'video'
        filename = f"VidFinder_{safe_title}_{int(time.time())}[vinder].mp4"

        # Kirim file dari buffer yang sudah lengkap
        # Content-Length sekarang akurat karena dari buffer nyata, bukan dari CDN
        return send_file(
            buffer,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=filename
        )

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

        # Prioritas URL: hdplay > wmplay > play
        hdplay = d.get('hdplay') or ''
        wmplay = d.get('wmplay') or ''
        play   = d.get('play') or ''

        target_url = hdplay or wmplay or play

        # Fallback ke play (SD) jika URL utama gagal di get_video
        if target_url == hdplay and play and play != hdplay:
            fallback_url = play
        elif target_url == wmplay and play and play != wmplay:
            fallback_url = play
        else:
            fallback_url = ''

        if not target_url:
            return jsonify({"status": "error", "msg": "Video URL tidak ditemukan"})

        return jsonify({
            "status": "success",
            "url": target_url,
            "fallback": fallback_url,
            "play": play,
            "hdplay": hdplay,
            "wmplay": wmplay,
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
