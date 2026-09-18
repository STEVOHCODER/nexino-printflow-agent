"""Tests for the Nexino PrintFlow agent."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from nexino_agent.agent import NexinoAgent
from nexino_agent.config import AgentConfig
from nexino_agent.models import (
    PrintJob,
    JobStatus,
    PrinterStatus,
    PrinterState,
    ColorMode,
    DuplexMode,
)


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
def agent(config: AgentConfig) -> NexinoAgent:
    """Create a test agent."""
    return NexinoAgent(config)


class TestAgentInit:
    """Tests for agent initialization."""

    def test_agent_creation(self, config: AgentConfig):
        """Test that agent is created with correct config."""
        agent = NexinoAgent(config)
        assert agent.config == config
        assert agent._running is False
        assert agent._jobs_processed == 0
        assert agent._jobs_failed == 0

    def test_agent_with_virtual_mode(self, config: AgentConfig):
        """Test that virtual mode uses VirtualAdapter."""
        agent = NexinoAgent(config)
        from nexino_agent.adapters.virtual_adapter import VirtualAdapter
        assert isinstance(agent.adapter, VirtualAdapter)

    def test_processed_jobs_initialized_empty(self, agent: NexinoAgent):
        """Test that processed jobs set starts empty."""
        assert len(agent._processed_jobs) == 0


class TestJobToken:
    """Tests for job token generation."""

    def test_generate_job_token(self, agent: NexinoAgent):
        """Test that token generation is deterministic."""
        job = PrintJob(
            job_id="JOB-001",
            file_url="http://example.com/file.pdf",
            authorization_token="auth-token-123",
        )
        token1 = agent._generate_job_token(job)
        token2 = agent._generate_job_token(job)
        assert token1 == token2
        assert len(token1) == 64  # SHA-256 hex

    def test_different_jobs_different_tokens(self, agent: NexinoAgent):
        """Test that different jobs produce different tokens."""
        job1 = PrintJob(
            job_id="JOB-001",
            file_url="http://example.com/file.pdf",
            authorization_token="token-1",
        )
        job2 = PrintJob(
            job_id="JOB-002",
            file_url="http://example.com/file.pdf",
            authorization_token="token-2",
        )
        token1 = agent._generate_job_token(job1)
        token2 = agent._generate_job_token(job2)
        assert token1 != token2


class TestProcessJob:
    """Tests for job processing."""

    @patch("nexino_agent.agent.NexinoAPIClient.update_job_status")
    @patch("nexino_agent.agent.NexinoAPIClient.download_file")
    def test_process_job_success(
        self,
        mock_download: Mock,
        mock_update_status: Mock,
        agent: NexinoAgent,
        tmp_path,
    ):
        """Test successful job processing."""
        # Create a downloads directory and test PDF
        downloads_dir = tmp_path / "downloads"
        downloads_dir.mkdir()
        pdf_path = downloads_dir / "JOB-001.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 test content")

        # Mock download to write to the expected path
        def fake_download(url, dest):
            dest_path = Path(dest)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"%PDF-1.4 test content")
            return str(dest_path)

        mock_download.side_effect = fake_download

        job = PrintJob(
            job_id="JOB-001",
            file_url="http://example.com/file.pdf",
            authorization_token="auth-token-123",
            station_id="STATION-001",
        )

        agent.process_job(job)

        assert agent._jobs_processed == 1
        assert agent._jobs_failed == 0
        assert mock_update_status.call_count == 3  # printing, printing, completed

    @patch("nexino_agent.agent.NexinoAPIClient.update_job_status")
    def test_process_job_no_token(
        self,
        mock_update_status: Mock,
        agent: NexinoAgent,
    ):
        """Test that job without authorization token fails."""
        job = PrintJob(
            job_id="JOB-001",
            file_url="http://example.com/file.pdf",
            authorization_token="",
            station_id="STATION-001",
        )

        with pytest.raises(ValueError, match='authorization token'):
            agent.process_job(job)

    @patch("nexino_agent.agent.NexinoAPIClient.update_job_status")
    @patch("nexino_agent.agent.NexinoAPIClient.download_file")
    def test_process_job_download_failure(
        self,
        mock_download: Mock,
        mock_update_status: Mock,
        agent: NexinoAgent,
    ):
        """Test that download failure is handled gracefully."""
        mock_download.side_effect = Exception("Download failed")

        job = PrintJob(
            job_id="JOB-001",
            file_url="http://example.com/file.pdf",
            authorization_token="auth-token-123",
        )

        # Failures are counted by the retry wrapper, not process_job()
        agent._process_job_with_retry(job)

        assert agent._jobs_failed == 1


class TestDuplicatePrevention:
    """Tests for duplicate job prevention."""

    @patch("nexino_agent.agent.NexinoAPIClient.get_pending_jobs")
    @patch("nexino_agent.agent.NexinoAPIClient.update_job_status")
    @patch("nexino_agent.agent.NexinoAPIClient.download_file")
    def test_prevent_duplicate_jobs(
        self,
        mock_download: Mock,
        mock_update_status: Mock,
        mock_get_jobs: Mock,
        agent: NexinoAgent,
        tmp_path,
    ):
        """Test that duplicate jobs are not processed twice."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 test content")
        mock_download.return_value = str(pdf_path)

        job = PrintJob(
            job_id="JOB-001",
            file_url="http://example.com/file.pdf",
            authorization_token="auth-token-123",
        )

        # First poll - should process
        mock_get_jobs.return_value = [job]
        agent.poll_for_jobs()

        # Second poll - should skip
        mock_get_jobs.return_value = [job]
        agent.poll_for_jobs()

        # Wait for threads to complete
        import time
        time.sleep(0.1)

        # Job should only be processed once
        assert agent._jobs_processed <= 1


class TestGetStatus:
    """Tests for agent status retrieval."""

    def test_get_status_returns_dict(self, agent: NexinoAgent):
        """Test that status is returned as a dictionary."""
        status = agent.get_status()
        assert isinstance(status, dict)
        assert "agent_id" in status
        assert "station_id" in status
        assert "is_running" in status
        assert "jobs_processed" in status
        assert "jobs_failed" in status

    def test_get_status_values(self, agent: NexinoAgent):
        """Test that status contains correct values."""
        status = agent.get_status()
        assert status["agent_id"] == "test-agent-001"
        assert status["station_id"] == "STATION-001"
        assert status["is_running"] is False
        assert status["virtual_mode"] is True


class TestStop:
    """Tests for agent stopping."""

    def test_stop_sets_running_false(self, agent: NexinoAgent):
        """Test that stop sets running to False."""
        agent._running = True
        agent.stop()
        assert agent._running is False

    def test_stop_is_idempotent(self, agent: NexinoAgent):
        """Test that calling stop multiple times is safe."""
        agent._running = True
        agent.stop()
        agent.stop()  # Should not raise
        assert agent._running is False


class TestTestConnection:
    """Tests for connection testing."""

    @patch("nexino_agent.agent.NexinoAPIClient.heartbeat")
    def test_test_connection_success(self, mock_heartbeat: Mock, agent: NexinoAgent):
        """Test successful connection test."""
        mock_heartbeat.return_value = {"status": "ok"}
        assert agent.test_connection() is True

    @patch("nexino_agent.agent.NexinoAPIClient.heartbeat")
    def test_test_connection_failure(self, mock_heartbeat: Mock, agent: NexinoAgent):
        """Test failed connection test."""
        from nexino_agent.api_client import APIError
        mock_heartbeat.side_effect = APIError("Connection refused")
        assert agent.test_connection() is False
