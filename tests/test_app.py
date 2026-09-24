"""Check that the Streamlit app survives a hosted update that leaves the previous processor imported."""
import io
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import processor
from test_processor import fixture_glb

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_hot_update_refreshes_old_processor_and_reports_earlier_brightening():
    brightened, _ = processor.convert_glb(fixture_glb(), processor.Options(brighten_stops=2))
    upload = io.BytesIO(brightened)
    upload.name = "bundle-medium.glb"
    current_inspect = processor.inspect_glb

    def old_inspect(data):
        """What inspect_glb returned before the processor recorded brightening."""
        details = current_inspect(data)
        del details["brighten_stops"]
        return details

    # The app reloads the module, which makes new classes such as ConversionError. Put the originals back
    # afterwards, because other tests imported them.
    original = dict(vars(processor))
    try:
        with patch("streamlit.file_uploader", return_value=upload), \
                patch.object(processor, "PROCESSOR_API_VERSION", None), \
                patch.object(processor, "inspect_glb", old_inspect):
            app = AppTest.from_file(APP, default_timeout=20).run()
            assert not app.exception
            assert processor.PROCESSOR_API_VERSION == 1
            assert processor.inspect_glb is not old_inspect
    finally:
        vars(processor).clear()
        vars(processor).update(original)
    assert "already brightened this GLB by +2 stops" in app.info[0].value
