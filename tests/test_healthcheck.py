import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import healthcheck
from config.settings import Settings

class DummySettings(Settings):
    def __init__(self):
        self._initialized = True
        self.supabase_url = "https://dummy.supabase.co"
        self.supabase_key = "dummy-key"
        self.medium_integration_token = "dummy-token"
        self.slack_bot_token = "xoxb-dummy"

@patch('healthcheck.get_supabase_client_from_settings')
def test_supabase_health_ok(mock_get_client):
    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    mock_client.ping.return_value = True
    mock_get_client.return_value = mock_client
    
    settings = DummySettings()
    assert healthcheck.test_supabase(settings) is True

@patch('healthcheck.urllib.request.urlopen')
@patch('os.getenv')
def test_firecrawl_health_reachable(mock_getenv, mock_urlopen):
    mock_getenv.return_value = "dummy-firecrawl-key"
    # Mocking an HTTP Error that signifies API is reachable
    from urllib.error import HTTPError
    mock_urlopen.side_effect = HTTPError(url="https://api.firecrawl.dev", code=401, msg="", hdrs={}, fp=None)
    
    settings = DummySettings()
    assert healthcheck.test_firecrawl(settings) is True

def test_medium_health_ok():
    settings = DummySettings()
    assert healthcheck.test_medium(settings) is True

@patch('healthcheck.urllib.request.urlopen')
def test_slack_health_ok(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"ok": true}'
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response
    
    settings = DummySettings()
    assert healthcheck.test_slack(settings) is True

@patch('healthcheck.urllib.request.urlopen')
def test_slack_health_failed(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"ok": false, "error": "invalid_auth"}'
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response
    
    settings = DummySettings()
    assert healthcheck.test_slack(settings) is False
