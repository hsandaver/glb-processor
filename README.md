# GLB texture processor

A Streamlit app for preparing textured GLB files for Universal Viewer. It reads embedded colour maps, resizes images, and writes a self-contained GLB while copying geometry and UV buffers without re-meshing.

## Run

Requires Python 3.10 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the localhost URL printed by Streamlit. Upload a GLB, choose the appearance, and click **Process GLB**. The original file stays untouched. A supplied sample at `artifacts/input.glb` appears automatically. Set `GLB_SAMPLE_PATH` to use another local sample.

## Settings

- **Photographed colour** uses `KHR_materials_unlit`. It displays the base-colour photographs without lighting and removes normal, occlusion, metallic and emissive maps from textured materials. This is the default for scanned objects.
- **Simple shaded surface** retains viewer lighting with matte materials and the same texture simplification.
- **Keep original materials** preserves material settings and all used images. Images still get resized and re-encoded.
- **Maximum texture edge** defaults to 2048 pixels. Images retain their aspect ratio and are never enlarged. RGB images become JPEG and images with alpha become PNG.
- **Rotate Z-up model to Y-up** is optional and off by default. It changes scene coordinates. Existing spatial annotations must be transformed to match.

The app preserves material colour factors, UV transforms, transparency, scene structure and animation data. It rejects external images and unsupported extensions, including Draco, Meshopt and Basis/KTX2 compression, rather than silently removing them. It cannot reconstruct absent textures or UV coordinates. Built-in checks are not a full glTF specification validator.

## The supplied file

`bundle-medium.glb` contains two colour maps, two normal maps and two occlusion maps, all 4096 × 4096 JPEGs. The default conversion retains two colour maps at 2048 × 2048 and reduces the file from 13.52 MB to 4.23 MB. This is a compatibility and appearance conversion, not proof of the cause of a particular hosted viewer failure.

## Universal Viewer

Upload the output under a new filename and update the existing manifest's model URL. Keep `format: "model/gltf-binary"`. The host must serve the GLB with the corresponding content type and allow cross-origin requests from the viewer. Public viewers normally need publicly accessible HTTPS assets. Check caching if the old model persists.

The preview uses model-viewer 4.1.0, loaded from jsDelivr. Conversion runs locally and does not need the CDN. Model data is passed to the browser as an embedded blob. The app does not upload models to a third-party service, publish an IIIF manifest, or guarantee support in all IIIF viewers.

If the preview has textures but your Universal Viewer does not, check the fetched model URL, UV version and browser console. A manifest pointing to an untextured derivative cannot be fixed by modifying a different GLB.

References: [UV model renderer](https://github.com/UniversalViewer/universalviewer/blob/dev/src/content-handlers/iiif/modules/uv-modelviewercenterpanel-module/ModelViewerCenterPanel.ts), [glTF unlit materials](https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_unlit), [model-viewer documentation](https://modelviewer.dev/).

## Tests

```sh
pip install pytest
python -m pytest -q
```

Tests cover geometry preservation, resource pruning, alpha, embedded data URIs, missing UVs, unsupported extensions, invalid references, rotation and truncated files.

The supplied converted file was also checked with Khronos glTF Validator 2.0.0-dev.3.10, with zero errors, warnings or informational messages, and visually verified with colour textures in a local Universal Viewer 4.4.4 instance. All five original accessor buffers were compared byte for byte against the output. These checks do not test your hosted manifest or UV installation.
