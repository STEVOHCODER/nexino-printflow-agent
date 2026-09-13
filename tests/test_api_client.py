"""Tests for the NexinoPrint API client."""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from nexino_agent.api_client import NexinoAPIClient, APIError
from nexino_agent.config import AgentConfig
from nexino_agent.models import PrintJob, JobStatus, PrinterStatus, PrinterState


@pytest.fixture
def config() -> AgentConfig:
    """Create a test configuration."""
    return AgentConfig(
        backend_url="http://localhost:3000",
        agent_id="test-agent-001",
        agent_secret="test-secret",
        station_id="STATION-001",
        poll_interval_seconds=5,
        virtual_mode=True,
        log_level="DEBUG",
    )


@pytest.fixture
def client(config: AgentConfig) -> NexinoAPIClient:
    """Create a test API client."""
    return NexinoAPIClient(config)


class TestAPIClientInit:
    """Tests for API client initialization."""

    def test_client_creation(self, config: AgentConfig):
        """Test that client is created with correct config."""
        client = NexinoAPIClient(config)
        assert client.config == config
        assert client.base_url == "http://localhost:3000"

    def test_base_url_strips_trailing_slash(self, config: AgentConfig):
        """Test that trailing slash is removed from base URL."""
        config.backend_url = "http://localhost:3000/"
        client = NexinoAPIClient(config)
        assert client.base_url == "http://localhost:3000"


class TestHMACSigning:
    """Tests for HMAC request signing."""

    def test_sign_request(self, client: NexinoAPIClient):
        """Test that request signing produces consistent results."""
        sig1 = client._sign_request("GET", "/api/test", "2024-01-01T00:00:00Z")
        sig2 = client._sign_request("GET", "/api/test", "2024-01-01T00:00:00Z")
        assert sig1 == sig2
        assert len(sig1) == 64  # SHA-256 hex digest

    def test_sign_request_differs_by_method(self, client: NexinoAPIClient):
        """Test that different HTTP methods produce different signatures."""
        sig_get = client._sign_request("GET", "/api/test", "2024-01-01T00:00:00Z")
        sig_post = client._sign_request("POST", "/api/test", "2024-01-01T00:00:00Z")
        assert sig_get != sig_post


class TestHeaders:
    """Tests for request header generation."""

    def test_headers_without_auth(self, client: NexinoAPIClient):
        """Test headers without authorization."""
        headers = client._get_headers(include_auth=False)
        assert "Authorization" not in headers
        assert "X-Agent-ID" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_headers_with_auth(self, client: NexinoAPIClient):
        """Test headers with authorization."""
        headers = client._get_headers(include_auth=True)
        assert headers["Authorization"] == "Bearer test-secret"
        assert headers["X-Agent-ID"] == "test-agent-001"


class TestRegister:
    """Tests for agent registration."""

    @patch("nexino_agent.api_client.requests.Session.post")
    def test_register_success(self, mock_post: Mock, client: NexinoAPIClient):
        """Test successful registration."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-token-123",
            "agent_id": "test-agent-001",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = client.register()

        assert result["access_token"] == "new-token-123"
        mock_post.assert_called_once()

    @patch("nexino_agent.api_client.requests.Session.post")
    def test_register_failure(self, mock_post: Mock, client: NexinoAPIClient):
        """Test registration failure."""
        import requests as req
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = req.exceptions.HTTPError("500 Server Error")
        mock_post.return_value = mock_response

        with pytest.raises(APIError) as exc_info:
            client.register()
        assert "Registration failed" in str(exc_info.value)


class TestHeartbeat:
    """Tests for heartbeat functionality."""

    @patch("nexino_agent.api_client.requests.Session.post")
    def test_heartbeat_success(self, mock_post: Mock, client: NexinoAPIClient):
        """Test successful heartbeat."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = client.heartbeat()
        assert result["status"] == "ok"

    @patch("nexino_agent.api_client.requests.Session.post")
    def test_heartbeat_failure(self, mock_post: Mock, client: NexinoAPIClient):
        """Test heartbeat failure."""
        import requests as req
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = req.exceptions.HTTPError("500 Server Error")
        mock_post.return_value = mock_response

        with pytest.raises(APIError):
            client.heartbeat()


class TestGetPendingJobs:
    """Tests for fetching pending jobs."""

    @patch("nexino_agent.api_client.requests.Session.get")
    def test_get_pending_jobs_empty(self, mock_get: Mock, client: NexinoAPIClient):
        """Test getting empty job list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jobs": []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        jobs = client.get_pending_jobs()
        assert jobs == []

    @patch("nexino_agent.api_client.requests.Session.get")
    def test_get_pending_jobs_returns_list(self, mock_get: Mock, client: NexinoAPIClient):
        """Test that jobs are returned as PrintJob instances."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "jobId": "JOB-001",
                    "file": {"storedFilename": "test.pdf"},
                    "authorizationToken": "auth-token-123",
                    "copies": 1,
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        jobs = client.get_pending_jobs()
        assert len(jobs) == 1
        assert isinstance(jobs[0], PrintJob)
        assert jobs[0].job_id == "JOB-001"


class TestUpdateJobStatus:
    """Tests for job status updates."""

    @patch("nexino_agent.api_client.requests.Session.post")
    def test_update_job_status(self, mock_post: Mock, client: NexinoAPIClient):
        """Test job status update."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated": True}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = client.update_job_status("JOB-001", JobStatus.COMPLETED)
        assert result["updated"] is True

    @patch("nexino_agent.api_client.requests.Session.post")
    def test_update_job_status_with_error(self, mock_post: Mock, client: NexinoAPIClient):
        """Test job status update with error message."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated": True}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = client.update_job_status(
            "JOB-001", JobStatus.PRINT_FAILED, error_message="Paper jam"
        )
        assert result["updated"] is True


class TestUpdatePrinterStatus:
    """Tests for printer status updates."""

    @patch("nexino_agent.api_client.requests.Session.post")
    def test_update_printer_status(self, mock_post: Mock, client: NexinoAPIClient):
        """Test printer status update."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated": True}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        status = PrinterStatus(
            name="Test Printer",
            state=PrinterState.IDLE,
        )
        result = client.update_printer_status("PRINTER-UUID-001", status)
        assert result["updated"] is True


class TestDownloadFile:
    """Tests for file downloading."""

    @patch("nexino_agent.api_client.requests.Session.get")
    def test_download_file(self, mock_get: Mock, client: NexinoAPIClient, tmp_path):
        """Test successful file download."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"PDF content here"]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        dest = str(tmp_path / "test.pdf")
        result = client.download_file("http://example.com/file.pdf", dest)

        assert result == dest
        with open(dest, "rb") as f:
            assert f.read() == b"PDF content here"
