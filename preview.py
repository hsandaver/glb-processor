"""Browser preview using the renderer embedded by Universal Viewer 4."""
import base64


def preview_html(data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return """<!doctype html><html><head><meta charset="utf-8">
<style>
body{margin:0;background:#edf2ef;font:14px system-ui;color:#18332f}
model-viewer{width:100%;height:465px}#status{padding:8px 14px}
</style></head><body>
<model-viewer camera-controls interaction-prompt="none" alt="Textured 3D model"></model-viewer>
<div id="status" role="status">Loading 3D preview…</div>
<script type="module">
const status=document.getElementById('status');
const viewer=document.querySelector('model-viewer');
const timeout=setTimeout(()=>{status.textContent='Preview is taking longer than expected. Check your connection and WebGL support.'},30000);
try {
 await import('https://cdn.jsdelivr.net/npm/@google/model-viewer@4.1.0/dist/model-viewer.min.js');
 const bytes=Uint8Array.from(atob('""" + encoded + """'), c=>c.charCodeAt(0));
 const url=URL.createObjectURL(new Blob([bytes],{type:'model/gltf-binary'}));
 viewer.addEventListener('load',()=>{clearTimeout(timeout);status.textContent='Drag to rotate · Scroll to zoom';URL.revokeObjectURL(url)},{once:true});
 viewer.addEventListener('error',()=>{clearTimeout(timeout);status.textContent='Could not render this GLB. Try another browser with WebGL enabled.'});
 viewer.src=url;
} catch(error) {clearTimeout(timeout);status.textContent='Preview library could not load. An internet connection is needed for the preview.'}
</script></body></html>"""
