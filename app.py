from __future__ import annotations

import hashlib
import importlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from archive import ArchiveError, list_glbs, read_glb_from_zip, replace_glb_in_zip
from preview import preview_html
from manifest import build_manifest
import processor

# A hosted update can rerun this file with the previous processor module still imported.
# Refresh it only when its interface is out of date, not on every rerun.
if getattr(processor, "PROCESSOR_API_VERSION", None) != 1:
    importlib.reload(processor)
from processor import ConversionError, Options, convert_glb, image_bytes, inspect_glb, open_image, parse_glb  # noqa: E402

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
    brighten = st.slider("Brighten colour photographs", 0.0, 4.0, 0.0, 0.5, format="+%.1f stops")
    st.caption("Universal Viewer has no lighting or exposure setting, so this writes the change into the colour textures. "
               "Each stop doubles the light. +2 stops looks like exposure 4 in model-viewer. Highlights past white clip.")
    double_sided = st.checkbox("Show both sides of textured surfaces", value=False)
    z_up = st.checkbox("Rotate Z-up model to Y-up", value=False, help="Use if the model lies on its side. Changes spatial coordinates and may affect existing IIIF annotations.")

uploaded = st.file_uploader("Choose a GLB or ZIP", type=["glb", "zip"])
zip_data = None
zip_name = None
zip_model_path = None
sample = Path(os.environ.get("GLB_SAMPLE_PATH", "artifacts/input.glb"))
use_sample = st.checkbox("Use the supplied bundle-medium.glb", value=True) if sample.is_file() and uploaded is None else False
if uploaded is not None:
    data, name = uploaded.getvalue(), Path(uploaded.name).name
    if name.lower().endswith(".zip"):
        zip_data, zip_name = data, name
        try:
            model_paths = list_glbs(zip_data)
            zip_model_path = st.selectbox("GLB to process", model_paths,
                                          key=f"zip_model_{hashlib.sha256(zip_data).hexdigest()}")
            data = read_glb_from_zip(zip_data, zip_model_path)
            name = Path(zip_model_path).name
        except ArchiveError as exc:
            st.error(str(exc))
            st.stop()
elif use_sample:
    data, name = sample.read_bytes(), "bundle-medium.glb"
else:
    st.info("Upload a GLB or a ZIP containing a GLB to create a version for Universal Viewer.")
    st.stop()

options = Options(mode, size, quality, double_sided, z_up, brighten)
signature = hashlib.sha256(data).hexdigest() + json.dumps(asdict(options), sort_keys=True)

@st.cache_data(max_entries=2, show_spinner=False)
def inspect_cached(raw, processor_version):
    """`processor_version` is part of the cache key, so results from an earlier processor aren't reused."""
    return inspect_glb(raw)


@st.cache_data(max_entries=1, show_spinner=False)
def rebuild_zip_cached(raw, model_path, processed):
    return replace_glb_in_zip(raw, model_path, processed)

try:
    details = inspect_cached(data, processor.PROCESSOR_API_VERSION)
except (ConversionError, KeyError, IndexError, TypeError, ValueError) as exc:
    st.error(f"Cannot inspect this GLB: {exc}")
    st.stop()

cols = st.columns(4)
for col, title, value in zip(cols, ["File size", "Meshes", "Textured materials", "Embedded images"],
                             [f"{len(data) / 1_000_000:.2f} MB", details["meshes"], details["textured_materials"], len(details["images"])]):
    col.metric(title, value)
if details["brighten_stops"]:
    st.info(f"This app already brightened this GLB by {details['brighten_stops']:+g} stops. "
            "Brightening it again adds to that, and the output records the total.")

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
    st.subheader("Updated ZIP bundle")
    if zip_data is None:
        original_zip = st.file_uploader("Original ZIP to update", type=["zip"], key="original_zip")
        if original_zip is not None:
            zip_data, zip_name = original_zip.getvalue(), Path(original_zip.name).name
            try:
                model_paths = list_glbs(zip_data)
                matching_paths = [path for path in model_paths if Path(path).name == name]
                default_index = model_paths.index(matching_paths[0]) if len(matching_paths) == 1 else 0
                zip_model_path = st.selectbox("GLB to replace", model_paths, index=default_index,
                                              key=f"zip_target_{hashlib.sha256(zip_data).hexdigest()}_{name}")
            except ArchiveError as exc:
                st.error(str(exc))
    if zip_data is not None and zip_model_path is not None:
        st.caption(f"Replaces {zip_model_path} with the processed GLB. Other files and folder paths are preserved.")
        try:
            with st.spinner("Building updated ZIP…"):
                updated_zip = rebuild_zip_cached(zip_data, zip_model_path, output)
            st.download_button("Download updated ZIP", updated_zip,
                               file_name=f"{Path(zip_name).stem}-processed.zip", mime="application/zip",
                               type="primary", width="stretch")
        except ArchiveError as exc:
            st.error(str(exc))
    st.subheader("Universal Viewer manifest")
    st.write("Download a manifest that points Universal Viewer to your processed GLB. Enter the URLs where you will host both files.")
    title = st.text_input("Model title", value=stem, key=f"manifest_title_{hashlib.sha256(data).hexdigest()}")
    model_url = st.text_input("Public GLB URL", placeholder=f"https://your-host.org/models/{stem}-uv.glb", key="manifest_model_url")
    manifest_url = st.text_input("Public manifest URL", placeholder=f"https://your-host.org/models/{stem}-manifest.json", key="manifest_url")
    manifest_data = None
    if model_url and manifest_url:
        try:
            manifest_data = build_manifest(model_url, manifest_url, title)
        except ValueError as exc:
            st.error(str(exc))
    st.download_button("Download IIIF manifest", json.dumps(manifest_data, indent=2, ensure_ascii=False) if manifest_data else "",
                       file_name=f"{stem}-manifest.json", mime="application/json", disabled=manifest_data is None, width="stretch")
    if manifest_data:
        with st.expander("Inspect the manifest"):
            st.json(manifest_data)
    st.caption("Upload both files to those URLs, then open the manifest URL in Universal Viewer. Use HTTPS and allow cross-origin requests for both files. URLs are not checked for availability.")
    st.caption("Exports the Presentation 3 Model convention used by Universal Viewer 4. The app's preview loads the GLB directly; it does not load this manifest. This creates a new single-model manifest and does not copy annotations from an existing one.")
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
2. Download a manifest using the public URLs above, or update the model URL in your existing manifest. Keep its format as `model/gltf-binary`.
3. Serve the GLB over HTTPS with `Content-Type: model/gltf-binary` and the manifest with `Content-Type: application/json`. Permit cross-origin requests for both. Open the hosted manifest URL in Universal Viewer.

If this preview shows colour but your viewer remains grey, check the model URL requested by Universal Viewer, cached files, browser errors and the UV version. Replacing the file alone will not fix a manifest that points to a different model.

This app creates downloadable files. Upload them to your host to make them available to Universal Viewer.
""")
