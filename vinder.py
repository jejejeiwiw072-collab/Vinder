#!/usr/bin/env python3
"""
VidFinder — Flask API Server
Jalankan: python vinder_server.py
Akses UI  : http://localhost:5000
"""

import os
import re
import requests
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app)  # Fix CORS biar HTML bisa connect ke API

# Folder penyimpanan download (di server, bukan sdcard)
DOWNLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

DOWNLOAD_HEADERS = {
    "User-Agent"     : "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Referer"        : "https://www.tikwm.com/",
    "Accept"         : "video/mp4,video/*;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}


# ─────────────────────────────────────────
#  HELPER: FORMAT DURASI
# ─────────────────────────────────────────
def format_durasi(detik):
    if detik is None:
        return "?"
    detik = int(detik)
    m, s = divmod(detik, 60)
    return f"{m}m{s:02d}s"


def parse_filter(filter_str):
    if not filter_str or not filter_str.strip():
        return None
    filter_str = filter_str.strip()
    m1 = re.match(r'^>(\d+)m$', filter_str)
    if m1:
        return ('gt', int(m1.group(1)) * 60)
    m2 = re.match(r'^<(\d+)m$', filter_str)
    if m2:
        return ('lt', int(m2.group(1)) * 60)
    m3 = re.match(r'^(\d+)m-(\d+)m$', filter_str)
    if m3:
        return ('range', int(m3.group(1)) * 60, int(m3.group(2)) * 60)
    return None


def lolos_filter(durasi_detik, filter_parsed):
    if filter_parsed is None:
        return True
    if durasi_detik is None:
        return False
    t = filter_parsed[0]
    if t == 'gt':
        return durasi_detik > filter_parsed[1]
    if t == 'lt':
        return durasi_detik < filter_parsed[1]
    if t == 'range':
        return filter_parsed[1] <= durasi_detik <= filter_parsed[2]
    return True


def pilih_url_video(data_video):
    for key in ['play', 'hdplay', 'wmplay']:
        url = data_video.get(key, '').strip()
        if url and url.startswith('http'):
            return url, key
    return None, None


# ─────────────────────────────────────────
#  CORE: SEARCH via tikwm
# ─────────────────────────────────────────
def search_videos(query, limit=5, filter_parsed=None):
    results = []
    cursor = 0
    page = 0
    max_page = 5

    while len(results) < limit and page < max_page:
        try:
            resp = requests.post(
                "https://www.tikwm.com/api/feed/search",
                data={"keywords": query, "count": 20, "cursor": cursor, "HD": 1},
                timeout=15
            )
            data = resp.json()
        except Exception as e:
            return None, f"Gagal request ke tikwm: {str(e)}"

        if data.get('code') != 0:
            return None, f"API error: {data.get('msg', 'Unknown')}"

        videos = data.get('data', {}).get('videos', [])
        if not videos:
            break

        for v in videos:
            durasi = v.get('duration')
            try:
                durasi = int(durasi) if durasi else None
            except Exception:
                durasi = None

            if not lolos_filter(durasi, filter_parsed):
                continue

            uid = v.get('author', {}).get('unique_id', '')
            vid_id = v.get('id', '')

            results.append({
                'title'       : v.get('title', 'Tanpa Judul'),
                'id'          : vid_id,
                'link'        : f"https://www.tiktok.com/@{uid}/video/{vid_id}",
                'duration'    : format_durasi(durasi),
                'durasi_detik': durasi,
                'channel'     : v.get('author', {}).get('nickname', 'Unknown'),
                'play'        : v.get('play', ''),
                'hdplay'      : v.get('hdplay', ''),
                'wmplay'      : v.get('wmplay', '')
            })

            if len(results) >= limit:
                break

        cursor = data.get('data', {}).get('cursor', 0)
        page += 1

    return results, None


# ─────────────────────────────────────────
#  CORE: DOWNLOAD VIDEO
# ─────────────────────────────────────────
def do_download(video):
    video_url, url_source = pilih_url_video(video)

    # Fallback: ambil ulang dari API pakai link TikTok
    if not video_url and video.get('link'):
        try:
            resp = requests.post(
                "https://www.tikwm.com/api/",
                data={"url": video['link'], "hd": 1},
                timeout=15
            )
            data = resp.json()
            if data.get('code') == 0:
                video_url, url_source = pilih_url_video(data['data'])
        except Exception as e:
            return False, f"Gagal ambil link download: {str(e)}"

    if not video_url:
        return False, "URL video tidak ditemukan di response API."

    safe_title = re.sub(r'[\\/*?:"<>|]', '', video.get('title', 'video'))[:50].strip()
    vid_id = video.get('id', 'unknown')
    filename = os.path.join(DOWNLOAD_FOLDER, f"{safe_title}_{vid_id}.mp4")

    try:
        r = requests.get(video_url, stream=True, timeout=60, headers=DOWNLOAD_HEADERS)
        r.raise_for_status()

        content_type = r.headers.get('Content-Type', '')
        if 'text/html' in content_type or 'application/json' in content_type:
            # Coba fallback URL lain
            for key in ['play', 'hdplay', 'wmplay']:
                fallback = video.get(key, '').strip()
                if fallback and fallback != video_url and fallback.startswith('http'):
                    r2 = requests.get(fallback, stream=True, timeout=60, headers=DOWNLOAD_HEADERS)
                    r2.raise_for_status()
                    ct2 = r2.headers.get('Content-Type', '')
                    if 'text/html' not in ct2 and 'application/json' not in ct2:
                        r = r2
                        break
            else:
                return False, "Server mengembalikan halaman error, semua URL fallback gagal."

        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)

        file_size = os.path.getsize(filename)
        if file_size < 10 * 1024:
            os.remove(filename)
            return False, f"File terlalu kecil ({file_size} bytes), kemungkinan corrupt."

        size_mb = file_size / (1024 * 1024)
        return True, f"Download selesai: {safe_title}.mp4 ({size_mb:.1f} MB)"

    except Exception as e:
        return False, f"Error saat download: {str(e)}"


# ─────────────────────────────────────────
#  ROUTES: SERVE HTML
# ─────────────────────────────────────────
@app.route('/')
def index():
    """Serve halaman utama HTML"""
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vinder.html')
    if os.path.exists(html_path):
        return send_file(html_path)
    return "<h2>vinder.html tidak ditemukan. Taruh vinder.html di folder yang sama.</h2>", 404


@app.route('/downloads/<path:filename>')
def serve_download(filename):
    """Endpoint untuk akses file yang sudah didownload"""
    return send_from_directory(DOWNLOAD_FOLDER, filename)


# ─────────────────────────────────────────
#  ROUTES: API
# ─────────────────────────────────────────
@app.route('/api/search', methods=['POST'])
def api_search():
    body = request.get_json(silent=True) or {}
    keyword = body.get('keyword', '').strip()
    filter_str = body.get('filter', '').strip()
    limit = body.get('limit', 5)

    if not keyword:
        return jsonify({'status': 'error', 'msg': 'Keyword tidak boleh kosong.'}), 400

    try:
        limit = max(1, min(20, int(limit)))
    except (TypeError, ValueError):
        limit = 5

    filter_parsed = parse_filter(filter_str)
    results, err = search_videos(keyword, limit=limit, filter_parsed=filter_parsed)

    if err:
        return jsonify({'status': 'error', 'msg': err}), 502

    return jsonify({'status': 'success', 'msg': f'{len(results)} video ditemukan.', 'data': results})


@app.route('/api/download', methods=['POST'])
def api_download():
    video = request.get_json(silent=True)
    if not video or not video.get('id'):
        return jsonify({'status': 'error', 'msg': 'Data video tidak valid.'}), 400

    ok, msg = do_download(video)
    status = 'success' if ok else 'error'
    http_code = 200 if ok else 502

    # Kalau berhasil, beri link download file
    if ok:
        safe_title = re.sub(r'[\\/*?:"<>|]', '', video.get('title', 'video'))[:50].strip()
        vid_id = video.get('id', 'unknown')
        fname = f"{safe_title}_{vid_id}.mp4"
        download_url = f"/downloads/{fname}"
        return jsonify({'status': status, 'msg': msg, 'file': fname, 'download_url': download_url})

    return jsonify({'status': status, 'msg': msg}), http_code


@app.route('/api/download_url', methods=['POST'])
def api_download_url():
    body = request.get_json(silent=True) or {}
    url = body.get('url', '').strip()

    if not url:
        return jsonify({'status': 'error', 'msg': 'URL tidak boleh kosong.'}), 400

    # Ambil info video dari tikwm
    try:
        resp = requests.post(
            "https://www.tikwm.com/api/",
            data={"url": url, "hd": 1},
            timeout=15
        )
        data = resp.json()
    except Exception as e:
        return jsonify({'status': 'error', 'msg': f'Gagal connect ke tikwm: {str(e)}'}), 502

    if data.get('code') != 0:
        return jsonify({'status': 'error', 'msg': f"API error: {data.get('msg', 'Unknown')}"}), 502

    d = data['data']
    video = {
        'title'  : d.get('title', 'Tanpa Judul'),
        'id'     : d.get('id', 'unknown'),
        'link'   : url,
        'channel': d.get('author', {}).get('nickname', 'Unknown'),
        'hdplay' : d.get('hdplay', ''),
        'play'   : d.get('play', ''),
        'wmplay' : d.get('wmplay', '')
    }

    ok, msg = do_download(video)
    status = 'success' if ok else 'error'

    if ok:
        safe_title = re.sub(r'[\\/*?:"<>|]', '', video['title'])[:50].strip()
        fname = f"{safe_title}_{video['id']}.mp4"
        return jsonify({'status': status, 'msg': msg, 'file': fname, 'download_url': f"/downloads/{fname}"})

    return jsonify({'status': status, 'msg': msg}), 502


@app.route('/api/files', methods=['GET'])
def api_files():
    """List semua file yang sudah didownload"""
    files = []
    for f in os.listdir(DOWNLOAD_FOLDER):
        if f.endswith('.mp4'):
            fpath = os.path.join(DOWNLOAD_FOLDER, f)
            size_mb = os.path.getsize(fpath) / (1024 * 1024)
            files.append({'name': f, 'size_mb': round(size_mb, 2), 'url': f'/downloads/{f}'})
    return jsonify({'status': 'success', 'files': files})


# ─────────────────────────────────────────
if __name__ == '__main__':
    print("═" * 46)
    print("  🎵  VidFinder — Web Service")
    print("  🌐  http://localhost:5000")
    print("  📁  Downloads: ./downloads/")
    print("═" * 46)
    app.run(host='0.0.0.0', port=5000, debug=False)

