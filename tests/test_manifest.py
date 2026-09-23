import json

import pytest

from manifest import build_manifest


def test_model_url_and_annotation_references_round_trip():
    model = "https://example.org/model.glb?version=2&quality=medium"
    manifest = "https://example.org/manifest.json?version=2"
    doc = json.loads(json.dumps(build_manifest(model, manifest, 'Object "A"')))
    canvas = doc["items"][0]
    annotation = canvas["items"][0]["items"][0]
    assert doc["id"] == manifest
    assert annotation["target"] == canvas["id"]
    assert annotation["body"] == {"id": model, "type": "Model", "format": "model/gltf-binary"}
    assert doc["label"]["en"] == ['Object "A"']


@pytest.mark.parametrize("url", ["", "model.glb", "file:///model.glb", "https://host/model file.glb", "https://user:pass@host/model.glb", "https://host/model.glb#part", "https://host:invalid/model.glb"])
def test_invalid_resource_urls_are_rejected(url):
    with pytest.raises(ValueError):
        build_manifest(url, "https://example.org/manifest.json", "Object")
    with pytest.raises(ValueError):
        build_manifest("https://example.org/model.glb", url, "Object")
