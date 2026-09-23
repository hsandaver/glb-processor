import base64
import io
import struct

import pytest
from PIL import Image

from processor import ConversionError, Options, convert_glb, image_bytes, parse_glb, write_glb


def fixture_glb(alpha=False, uri=False):
    img = Image.new("RGBA" if alpha else "RGB", (32, 16), (180, 70, 20, 128) if alpha else (180, 70, 20))
    encoded = io.BytesIO()
    img.save(encoded, "PNG")
    geometry = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    uv = struct.pack("<6f", 0, 0, 1, 0, 0, 1)
    raw = geometry + uv + encoded.getvalue()
    image = {"bufferView": 2, "mimeType": "image/png"}
    if uri:
        image = {"uri": "data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode()}
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
           "bufferViews": [{"buffer": 0, "byteLength": len(geometry)}, {"buffer": 0, "byteOffset": len(geometry), "byteLength": len(uv)},
                           {"buffer": 0, "byteOffset": len(geometry + uv), "byteLength": len(encoded.getvalue())}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0,0,0], "max": [1,1,0]},
                         {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"}],
           "images": [image, dict(image)], "textures": [{"source": 0}, {"source": 1}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}, "normalTexture": {"index": 1}}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}]}]}
    return write_glb(doc, raw)


def test_geometry_and_uvs_survive_and_auxiliary_images_are_removed():
    source = fixture_glb()
    out, report = convert_glb(source)
    before, b = parse_glb(source)
    after, a = parse_glb(out)
    for old_acc, new_acc in zip(before["accessors"], after["accessors"]):
        old = before["bufferViews"][old_acc["bufferView"]]
        new = after["bufferViews"][new_acc["bufferView"]]
        assert b[old.get("byteOffset", 0):old.get("byteOffset", 0) + old["byteLength"]] == a[new["byteOffset"]:new["byteOffset"] + new["byteLength"]]
    assert len(after["images"]) == 1
    assert report["retained_images"] == 1
    assert "normalTexture" not in after["materials"][0]
    assert after["materials"][0]["extensions"] == {"KHR_materials_unlit": {}}
    assert len(after["bufferViews"]) == 3


@pytest.mark.parametrize("uri", [False, True])
def test_alpha_and_data_uri_are_preserved(uri):
    out, _ = convert_glb(fixture_glb(alpha=True, uri=uri))
    doc, binary = parse_glb(out)
    im = Image.open(io.BytesIO(image_bytes(doc, binary, 0)))
    assert doc["images"][0]["mimeType"] == "image/png"
    assert im.getpixel((0, 0)) == (180, 70, 20, 128)
    assert "uri" not in doc["images"][0]


def test_preserve_materials_and_rotation():
    out, _ = convert_glb(fixture_glb(), Options(mode="preserve", z_up=True))
    doc, _ = parse_glb(out)
    assert len(doc["images"]) == 2
    assert "normalTexture" in doc["materials"][0]
    assert doc["nodes"][1]["children"] == [0]
    assert doc["scenes"][0]["nodes"] == [1]


@pytest.mark.parametrize("failure", ["uv", "extension", "external", "reference"])
def test_unsupported_input_has_useful_error(failure):
    doc, binary = parse_glb(fixture_glb())
    if failure == "uv":
        del doc["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]
    elif failure == "extension":
        doc["extensionsRequired"] = ["KHR_draco_mesh_compression"]
    elif failure == "external":
        doc["images"][0] = {"uri": "missing.jpg"}
    else:
        doc["textures"][0]["source"] = 99
    with pytest.raises(ConversionError):
        convert_glb(write_glb(doc, binary))


def test_truncation_is_rejected():
    with pytest.raises(ConversionError, match="complete"):
        convert_glb(fixture_glb()[:-1])


def test_quantization_declaration_survives():
    doc, binary = parse_glb(fixture_glb())
    doc["extensionsUsed"] = doc["extensionsRequired"] = ["KHR_mesh_quantization"]
    out, _ = convert_glb(write_glb(doc, binary))
    converted, _ = parse_glb(out)
    assert "KHR_mesh_quantization" in converted["extensionsRequired"]
