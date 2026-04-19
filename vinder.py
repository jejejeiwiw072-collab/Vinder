<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>VidFinder System</title>
<style>
  body { background: #0f0f0f; color: #e8e8e8; font-family: sans-serif; padding: 20px; }
  .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
  input { width: 100%; padding: 10px; margin: 10px 0; background: #111; color: #fff; border: 1px solid #333; }
  button { width: 100%; padding: 10px; background: #2563eb; color: #fff; border: none; cursor: pointer; }
  .video-item { border-bottom: 1px solid #333; padding: 10px 0; }
  select { background: #222; color: #fff; padding: 5px; margin-bottom: 10px; }
</style>
</head>
<body>
  <h2>VidFinder System</h2>

  <div class="card">
    <h3>Cari Video</h3>
    <label>Pilih Mode:</label>
    <select id="modeSearch">
      <option value="HYPE v1.2">HYPE v1.2 (No Limit)</option>
      <option value="1080p">Standard (Max 720p)</option>
    </select>
    <input id="kw" type="text" placeholder="Keyword..."/>
    <button onclick="doSearch()">Cari</button>
    <div id="results"></div>
  </div>

  <div class="card">
    <h3>Download by URL</h3>
    <label>Pilih Mode:</label>
    <select id="modeUrl">
      <option value="HYPE v1.2">HYPE v1.2 (No Limit)</option>
      <option value="1080p">Standard (Max 720p)</option>
    </select>
    <input id="dl-url" type="text" placeholder="https://tiktok.com/..."/>
    <button onclick="doUrlDownload()">Download</button>
  </div>

<script>
  async function doSearch() {
    const kw = document.getElementById('kw').value;
    const resp = await fetch('/api/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({keyword: kw, limit: 5})
    });
    const json = await resp.json();
    const resEl = document.getElementById('results');
    resEl.innerHTML = '';
    json.data.forEach(v => {
      const div = document.createElement('div');
      div.className = 'video-item';
      div.innerHTML = `
        <p>${v.title}</p>
        <button onclick='downloadSingle(${JSON.stringify(v)})'>Download</button>
      `;
      resEl.appendChild(div);
    });
  }

  async function downloadSingle(v) {
    const mode = document.getElementById('modeSearch').value;
    const resp = await fetch('/api/download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...v, resolution: mode})
    });
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = `${v.title}.mp4`;
    a.click();
  }

  async function doUrlDownload() {
    const url = document.getElementById('dl-url').value;
    const mode = document.getElementById('modeUrl').value;
    const resp = await fetch('/api/download_url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: url, resolution: mode})
    });
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = `video_download.mp4`;
    a.click();
  }
</script>
</body>
</html>
