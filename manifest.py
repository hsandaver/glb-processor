"""Export the Presentation 3 Model convention used by Universal Viewer 4."""
from urllib.parse import urlsplit


def _resource_url(value: str, label: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"https", "http"} and parsed.hostname
                 and not parsed.username and not parsed.password
                 and not parsed.fragment and not any(c.isspace() for c in value))
        parsed.port  # Reject malformed ports before writing a broken resource ID.
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a complete HTTP or HTTPS URL without credentials, spaces or a fragment.")
    return value


def build_manifest(model_url: str, manifest_url: str, title: str) -> dict:
    model_url = _resource_url(model_url, "Model URL")
    manifest_url = _resource_url(manifest_url, "Manifest URL")
    if model_url == manifest_url:
        raise ValueError("The model and manifest must have different URLs.")
    if not title.strip():
        raise ValueError("Enter a title for the model.")
    canvas = manifest_url + "#canvas"
    label = {"en": [title.strip()]}
    return {
        "@context": ["http://www.w3.org/ns/anno.jsonld", "http://iiif.io/api/presentation/3/context.json"],
        "id": manifest_url,
        "type": "Manifest",
        "label": label,
        "items": [{
            "id": canvas,
            "type": "Canvas",
            "label": label,
            "items": [{
                "id": manifest_url + "#page",
                "type": "AnnotationPage",
                "items": [{
                    "id": manifest_url + "#annotation",
                    "type": "Annotation",
                    "motivation": "painting",
                    "target": canvas,
                    "body": {"id": model_url, "type": "Model", "format": "model/gltf-binary"},
                }],
            }],
        }],
    }
