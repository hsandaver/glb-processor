from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from preview import preview_html
from processor import ConversionError, Options, convert_glb, image_bytes, inspect_glb, open_image, parse_glb

st.set_page_config(page_title="GLB texture processor", page_icon="◈", layout="wide")
st.title("GLB texture processor")
st.write("Prepare a textured GLB for Universal Viewer. Inspect the embedded photographs, compare the result, and download a self-contained model.")

with st.sidebar:
    st.header("Conversion settings")
    mode_label = st.selectbox("Appearance", ["Photographed colour", "Simple shaded surface", "Keep original materials"])
    mode = {"Photographed colour": "unlit", "Simple shaded surface": "pbr", "Keep original materials": "preserve"}[mode_label]
    st.caption({"unlit": "Shows the colour texture without scene lighting. Removes normal, occlusion and metallic maps from textured materials.",
                "pbr": "Keeps light and shade, with a matte surface. Removes normal, occlusion and metallic maps from textured materials.",
                "preserve": "Keeps all material properties and used textures. Only repacks and resizes images."}[mode])
    size = st.select_slider("Maximum texture edge", options=[1024, 2048, 4096, 8192], value=2048, format_func=lambda x: f"{x} px")
    quality = st.slider("JPEG quality", 70, 100, 92)
    st.caption("Images are re-encoded. Transparent images remain PNG. Geometry is kept at its original resolution.")
    double_sided = st.checkbox("Show both sides of textured surfaces", value=False)
    z_up = st.checkbox("Rotate Z-up model to Y-up", value=False, help="Use if the model lies on its side. Changes spatial coordinates and may affect existing IIIF annotations.")

uploaded = st.file_uploader("Choose a GLB", type=["glb"])
sample = Path(os.environ.get("GLB_SAMPLE_PATH", "artifacts/input.glb"))
use_sample = st.checkbox("Use the supplied bundle-medium.glb", value=True) if sample.is_file() and uploaded is None else False
if uploaded is not None:
    data, name = uploaded.getvalue(), Path(uploaded.name).name
elif use_sample:
    data, name = sample.read_bytes(), "bundle-medium.glb"
else:
    st.info("Upload a GLB to inspect its textures and create a version for Universal Viewer.")
    st.stop()

options = Options(mode, size, quality, double_sided, z_up)
signature = hashlib.sha256(data).hexdigest() + json.dumps(asdict(options), sort_keys=True)

@st.cache_data(max_entries=2, show_spinner=False)
def inspect_cached(raw):
    return inspect_glb(raw)

try:
    details = inspect_cached(data)
except (ConversionError, KeyError, IndexError, TypeError, ValueError) as exc:
    st.error(f"Cannot inspect this GLB: {exc}")
    st.stop()

cols = st.columns(4)
for col, title, value in zip(cols, ["File size", "Meshes", "Textured materials", "Embedded images"],
                             [f"{len(data) / 1_000_000:.2f} MB", details["meshes"], details["textured_materials"], len(details["images"])]):
    col.metric(title, value)

with st.expander("Inspect the input textures"):
    st.dataframe(details["images"], hide_index=True, width="stretch")
    if st.checkbox("Show texture thumbnails"):
        doc, binary = parse_glb(data)
        columns = st.columns(3)
        for i in range(len(doc.get("images", []))):
            im = open_image(image_bytes(doc, binary, i))
            im.thumbnail((400, 400))
            columns[i % 3].image(im, caption=f"Image {i}")

if st.button("Process GLB", type="primary", width="stretch"):
    try:
        with st.spinner("Processing embedded textures…"):
            output, report = convert_glb(data, options)
            st.session_state.result = (signature, output, report)
    except (ConversionError, ValueError) as exc:
        st.error(str(exc))

result = st.session_state.get("result")
if result and result[0] == signature:
    _, output, report = result
    st.success(f"Ready. {len(output) / 1_000_000:.2f} MB with {report['retained_images']} embedded textures. Mesh and UV data preserved.")
    left, right = st.columns([3, 1])
    stem = Path(name).stem
    left.download_button("Download processed GLB", output, file_name=f"{stem}-uv.glb", mime="model/gltf-binary", type="primary", width="stretch")
    right.download_button("Download conversion report", json.dumps(report, indent=2), file_name=f"{stem}-report.json", mime="application/json", width="stretch")
    with st.expander("Conversion details"):
        st.json(report)
elif result:
    st.info("Settings or input changed. Process again to update the output.")

st.subheader("3D preview")
st.caption("Uses model-viewer 4.1, also used by Universal Viewer 4. Your installed UV version may differ. The preview library loads from a CDN; model data stays in this app and your browser.")
choices = ["Original", "Processed"] if result and result[0] == signature else ["Original"]
selection = st.radio("Preview model", choices, index=len(choices) - 1, horizontal=True)
if st.checkbox("Load interactive preview", value=True):
    st.iframe(preview_html(result[1] if selection == "Processed" else data), height=510)

with st.expander("Use the output in Universal Viewer"):
    st.markdown("""1. Upload the processed GLB to your model host using a new filename.
2. Change the model URL in the IIIF manifest to that file. Keep its format as `model/gltf-binary`.
3. Serve the GLB over HTTPS with `Content-Type: model/gltf-binary` and permit cross-origin requests from your viewer. Reload the viewer with the updated manifest.

If this preview shows colour but your viewer remains grey, check the model URL requested by Universal Viewer, cached files, browser errors and the UV version. Replacing the file alone will not fix a manifest that points to a different model.

This app processes GLB assets. It does not publish files or change your IIIF manifest.
""")
