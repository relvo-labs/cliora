"""Issue #143: worker admission refusal survives Central's upload relay."""
from app.services.files import FileRelayService


def test_upload_busy_is_retryable():
    service = object.__new__(FileRelayService)
    error = service._map_error("NODE_BUSY")
    assert error.code == "NODE_BUSY"
    assert error.status_code == 503
