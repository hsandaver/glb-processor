"""Conservative GLB texture conversion. Geometry buffers are copied verbatim."""
from __future__ import annotations

import base64
import copy
import io
import json
import math
import struct
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError


# Bump when app.py needs a new processor interface or inspection result, so a hosted update
# refreshes a cached import and cached inspections.
PROCESSOR_API_VERSION = 1
GENERATOR = "GLB texture processor"


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class Options:
    mode: str = "unlit"
    max_texture_size: int = 2048
    jpeg_quality: int = 92
    double_sided: bool = False
    z_up: bool = False
    brighten_stops: float = 0.0


def parse_glb(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 20:
        raise ConversionError("The file is too short to be a GLB.")
    magic, version, length = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or length != len(data):
        raise ConversionError("Expected a complete glTF 2.0 binary file.")
    chunks = []
    offset = 12
    while offset < length:
        if offset + 8 > length:
            raise ConversionError("The GLB chunk header is truncated.")
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if size % 4 or offset + size > length:
            raise ConversionError("The GLB contains an invalid chunk length.")
        chunks.append((kind, data[offset:offset + size]))
        offset += size
    if not chunks or chunks[0][0] != 0x4E4F534A:
        raise ConversionError("The GLB must start with a JSON chunk.")
    if len(chunks) > 2 or (len(chunks) == 2 and chunks[1][0] != 0x004E4942):
        raise ConversionError("This converter supports the standard JSON and BIN chunks only.")
    try:
        doc = json.loads(chunks[0][1])
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConversionError("The GLB metadata is not valid JSON.") from exc
    if not isinstance(doc, dict) or doc.get("asset", {}).get("version") != "2.0":
        raise ConversionError("Expected glTF 2.0 metadata.")
    binary = chunks[1][1] if len(chunks) > 1 else b""
    buffers = doc.get("buffers", [])
    if len(buffers) != 1 or "uri" in buffers[0]:
        raise ConversionError("Use a self-contained GLB with one embedded binary buffer.")
    declared = buffers[0].get("byteLength", -1)
    if not isinstance(declared, int) or not 0 <= len(binary) - declared <= 3:
        raise ConversionError("The embedded buffer length is invalid.")
    for view in doc.get("bufferViews", []):
        start, size = view.get("byteOffset", 0), view.get("byteLength", 0)
        if view.get("buffer", 0) != 0 or not isinstance(start, int) or not isinstance(size, int) or start < 0 or size <= 0 or start + size > declared:
            raise ConversionError("A buffer view points outside the embedded data.")
    return doc, binary


def write_glb(doc: dict, binary: bytes) -> bytes:
    doc = copy.deepcopy(doc)
    doc["buffers"] = [{"byteLength": len(binary)}]
    metadata = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode()
    metadata += b" " * (-len(metadata) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(metadata) + len(binary))
            + struct.pack("<II", len(metadata), 0x4E4F534A) + metadata
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def image_bytes(doc: dict, binary: bytes, index: int) -> bytes:
    img = doc["images"][index]
    if "bufferView" in img:
        view = doc["bufferViews"][img["bufferView"]]
        start = view.get("byteOffset", 0)
        return binary[start:start + view["byteLength"]]
    uri = img.get("uri", "")
    if uri.startswith("data:") and ";base64," in uri:
        try:
            return base64.b64decode(uri.split(",", 1)[1], validate=True)
        except ValueError as exc:
            raise ConversionError("An embedded image has invalid base64 data.") from exc
    raise ConversionError("External texture files are not included. Export a GLB with embedded textures first.")


def open_image(raw: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(raw))
        if im.width * im.height > 40_000_000:
            raise ConversionError("A texture exceeds the 40 megapixel processing limit.")
        im.load()
        return im
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ConversionError("A texture cannot be decoded as a standard image. Re-export it as PNG or JPEG.") from exc


def recorded_stops(doc: dict) -> float:
    """Return the brightening this app recorded in a GLB it made, or 0 for any other GLB."""
    asset = doc.get("asset", {})
    extras = asset.get("extras")
    if asset.get("generator") != GENERATOR or not isinstance(extras, dict):
        return 0.0
    stops = extras.get("brightenStops", 0)
    return float(stops) if isinstance(stops, (int, float)) and not isinstance(stops, bool) and math.isfinite(stops) else 0.0


def inspect_glb(data: bytes) -> dict:
    doc, binary = parse_glb(data)
    images = []
    for i, image in enumerate(doc.get("images", [])):
        im = open_image(image_bytes(doc, binary, i))
        images.append({"image": i, "width": im.width, "height": im.height,
                       "format": im.format, "declared_type": image.get("mimeType", "data URI")})
    return {"bytes": len(data), "meshes": len(doc.get("meshes", [])),
            "materials": len(doc.get("materials", [])), "images": images,
            "extensions": doc.get("extensionsUsed", []), "brighten_stops": recorded_stops(doc),
            "textured_materials": sum("baseColorTexture" in m.get("pbrMetallicRoughness", {}) for m in doc.get("materials", []))}


def exposure_table(stops: float) -> list[int]:
    """Map 8-bit sRGB values through a linear-light gain of 2**stops, as viewer exposure does."""
    table = []
    for value in range(256):
        c = value / 255
        linear = min(1.0, (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) * 2 ** stops)
        c = linear * 12.92 if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055
        table.append(round(c * 255))
    return table


def walk(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key != "extras":
                yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def convert_glb(data: bytes, options: Options = Options()) -> tuple[bytes, dict]:
    try:
        return _convert(data, options)
    except (KeyError, IndexError, TypeError, struct.error) as exc:
        raise ConversionError("The model contains invalid or unsupported glTF references.") from exc


def _convert(data: bytes, options: Options) -> tuple[bytes, dict]:
    if options.mode not in {"unlit", "pbr", "preserve"}:
        raise ConversionError("Unknown material mode.")
    if options.max_texture_size not in {1024, 2048, 4096, 8192} or not 1 <= options.jpeg_quality <= 100:
        raise ConversionError("Invalid texture size or JPEG quality.")
    if not 0 <= options.brighten_stops <= 4:
        raise ConversionError("Brightening must be between 0 and 4 stops.")
    doc, binary = parse_glb(data)
    # Avoid pruning extension resources whose reference semantics are unknown.
    supported = {"KHR_materials_unlit", "KHR_texture_transform", "KHR_mesh_quantization"}
    used = set(doc.get("extensionsUsed", [])) | set(doc.get("extensionsRequired", []))
    used |= {k for obj in walk(doc) for k in obj.get("extensions", {})}
    if used - supported:
        raise ConversionError("Re-export without these unsupported extensions before converting: " + ", ".join(sorted(used - supported)))
    doc = copy.deepcopy(doc)
    changes = []
    textured = 0
    for material in doc.get("materials", []):
        pbr = material.get("pbrMetallicRoughness", {})
        if "baseColorTexture" not in pbr:
            continue
        textured += 1
        if options.mode != "preserve":
            pbr["metallicFactor"], pbr["roughnessFactor"] = 0, 1
            pbr.pop("metallicRoughnessTexture", None)
            for key in ("normalTexture", "occlusionTexture", "emissiveTexture", "emissiveFactor"):
                material.pop(key, None)
            if options.mode == "unlit":
                material.setdefault("extensions", {})["KHR_materials_unlit"] = {}
            else:
                material.get("extensions", {}).pop("KHR_materials_unlit", None)
                if not material.get("extensions"):
                    material.pop("extensions", None)
        if options.double_sided:
            material["doubleSided"] = True
    if not textured:
        raise ConversionError("No base-colour textures are assigned. This app cannot reconstruct missing photographs.")
    # Check that each textured draw has the UV set its material references.
    for mesh in doc.get("meshes", []):
        for primitive in mesh["primitives"]:
            if "material" not in primitive:
                continue
            material = doc["materials"][primitive["material"]]
            for obj in walk(material):
                for key, info in obj.items():
                    if key.endswith("Texture") and isinstance(info, dict) and "index" in info:
                        uv = info.get("extensions", {}).get("KHR_texture_transform", {}).get("texCoord", info.get("texCoord", 0))
                        if f"TEXCOORD_{uv}" not in primitive.get("attributes", {}):
                            raise ConversionError(f"A textured mesh is missing TEXCOORD_{uv}. Re-export with UV coordinates.")
    slots = [(key, info) for material in doc.get("materials", []) for obj in walk(material)
             for key, info in obj.items() if key.endswith("Texture") and isinstance(info, dict) and "index" in info]
    infos = [info for _, info in slots]
    texture_ids = sorted({info["index"] for info in infos})
    texture_map = {old: new for new, old in enumerate(texture_ids)}
    textures = [doc["textures"][i] for i in texture_ids]
    for info in infos:
        info["index"] = texture_map[info["index"]]
    colour_ids = {textures[info["index"]]["source"] for key, info in slots if key == "baseColorTexture"}
    if options.brighten_stops and colour_ids & {textures[info["index"]]["source"] for key, info in slots if key != "baseColorTexture"}:
        raise ConversionError("A colour texture is also used as another map, so it cannot be brightened on its own.")
    image_ids = sorted({t["source"] for t in textures})
    image_map = {old: new for new, old in enumerate(image_ids)}
    images = [doc["images"][i] for i in image_ids]
    replacements = {}
    for old_id, img in zip(image_ids, images):
        im = open_image(image_bytes(doc, binary, old_id))
        original_size = im.size
        alpha = "A" in im.getbands() or "transparency" in im.info
        im = im.convert("RGBA" if alpha else "RGB")
        im.thumbnail((options.max_texture_size, options.max_texture_size), Image.Resampling.LANCZOS)
        brightened = bool(options.brighten_stops) and old_id in colour_ids
        if brightened:
            im = im.point(exposure_table(options.brighten_stops) * 3 + (list(range(256)) if alpha else []))
        encoded = io.BytesIO()
        fmt = "PNG" if alpha else "JPEG"
        im.save(encoded, format=fmt, **({"quality": options.jpeg_quality, "subsampling": 0} if fmt == "JPEG" else {}))
        # Each image gets a dedicated view so shared input views remain safe.
        img["bufferView"] = len(doc.setdefault("bufferViews", []))
        doc["bufferViews"].append({"buffer": 0, "byteLength": len(encoded.getvalue())})
        img.pop("uri", None)
        img["mimeType"] = "image/png" if alpha else "image/jpeg"
        replacements[img["bufferView"]] = encoded.getvalue()
        changes.append(f"Image {old_id}: {original_size[0]} × {original_size[1]} → {im.width} × {im.height}, {fmt}"
                       + (f", brightened {options.brighten_stops:+g} stops." if brightened else "."))
    for texture in textures:
        texture["source"] = image_map[texture["source"]]
    sampler_ids = sorted({t["sampler"] for t in textures if "sampler" in t})
    sampler_map = {old: new for new, old in enumerate(sampler_ids)}
    samplers = [doc.get("samplers", [])[i] for i in sampler_ids]
    for texture in textures:
        if "sampler" in texture:
            texture["sampler"] = sampler_map[texture["sampler"]]
    if samplers:
        doc["samplers"] = samplers
    else:
        doc.pop("samplers", None)
    doc["images"], doc["textures"] = images, textures
    # Buffer-view references occur in accessors, sparse accessors and images.
    # Extras are application metadata and must never be rewritten as glTF.
    def schema_walk(value):
        if isinstance(value, dict):
            yield value
            for key, child in value.items():
                if key != "extras":
                    yield from schema_walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from schema_walk(child)
    refs = [obj for obj in schema_walk(doc) if "bufferView" in obj]
    view_ids = sorted({obj["bufferView"] for obj in refs})
    output = bytearray()
    views = []
    mapping = {}
    for old in view_ids:
        view = copy.deepcopy(doc["bufferViews"][old])
        start = view.get("byteOffset", 0)
        raw = replacements.get(old, binary[start:start + view["byteLength"]])
        output.extend(b"\0" * (-len(output) % 4))
        view.update(buffer=0, byteOffset=len(output), byteLength=len(raw))
        mapping[old] = len(views)
        views.append(view)
        output.extend(raw)
    for obj in refs:
        obj["bufferView"] = mapping[obj["bufferView"]]
    doc["bufferViews"] = views
    if options.z_up:
        if not doc.get("scenes"):
            raise ConversionError("The model has no scene to rotate.")
        for scene in doc["scenes"]:
            index = len(doc.setdefault("nodes", []))
            doc["nodes"].append({"name": "Z-up to Y-up", "rotation": [-2 ** -0.5, 0, 0, 2 ** -0.5], "children": scene.get("nodes", [])})
            scene["nodes"] = [index]
        changes.append("Rotated the scene from Z-up to Y-up. Existing spatial annotations need the same transform.")
    actual = {k for obj in schema_walk(doc) for k in obj.get("extensions", {})}
    actual |= used & {"KHR_mesh_quantization"}
    for key in ("extensionsUsed", "extensionsRequired"):
        entries = sorted(actual if key == "extensionsUsed" else set(doc.get(key, [])) & actual)
        if entries:
            doc[key] = entries
        else:
            doc.pop(key, None)
    # Record the total brightening since the original scan. Brightening a GLB this app made adds to its earlier stops.
    stops = recorded_stops(doc) + options.brighten_stops
    asset = doc.setdefault("asset", {})
    extras = asset.setdefault("extras", {})
    if isinstance(extras, dict):
        extras["brightenStops"] = stops
        if stops != options.brighten_stops:
            changes.append(f"The input was already brightened {stops - options.brighten_stops:+g} stops, "
                           f"so the output records {stops:+g} stops in total.")
    asset["generator"] = GENERATOR
    result = write_glb(doc, bytes(output))
    return result, {"input_bytes": len(data), "output_bytes": len(result), "material_mode": options.mode,
                    "textured_materials": textured, "retained_images": len(images), "changes": changes,
                    "geometry": "Accessor and geometry buffer data preserved without re-meshing.",
                    "limitation": "Hosting, manifest URLs and the target Universal Viewer installation still need checking."}
