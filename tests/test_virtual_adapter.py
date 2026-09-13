"""Tests for the virtual printer adapter."""

import json
import pytest
from pathlib import Path
from datetime import datetime

from nexino_agent.adapters.virtual_adapter import VirtualAdapter
from nexino_agent.models import (
    PrinterStatus,
    PrinterState,
    PaperStatus,
    TonerStatus,
)


@pytest.fixture
def adapter(tmp_path) -> VirtualAdapter:
    """Create a virtual adapter with a temporary output directory."""
    return VirtualAdapter(
        output_dir=str(tmp_path),
        simulate_delay=False,  # Speed up tests
    )


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """Create a sample PDF file for testing."""
    pdf_path = tmp_path / "sample.pdf"
    # Create a minimal PDF-like file
    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    pdf_path.write_bytes(pdf_content)
    return pdf_path


class TestDiscover:
    """Tests for printer discovery."""

    def test_discover_returns_printer(self, adapter: VirtualAdapter):
        """Test that discover returns the virtual printer."""
        printers = adapter.discover()
        assert len(printers) == 1
        assert printers[0]["name"] == "Virtual Printer"
        assert printers[0]["type"] == "virtual"

    def test_discover_status_available(self, adapter: VirtualAdapter):
        """Test that discovered printer has available status."""
        printers = adapter.discover()
        assert printers[0]["status"] == "available"


class TestGetStatus:
    """Tests for printer status retrieval."""

    def test_get_status_returns_online(self, adapter: VirtualAdapter):
        """Test that virtual printer shows as online."""
        status = adapter.get_status("Virtual Printer")
        assert isinstance(status, PrinterStatus)
        assert status.state == PrinterState.IDLE

    def test_get_status_full_paper(self, adapter: VirtualAdapter):
        """Test that virtual printer shows full paper."""
        status = adapter.get_status("Virtual Printer")
        assert status.paper_status == PaperStatus.OK
        assert status.paper_level == 1.0

    def test_get_status_full_toner(self, adapter: VirtualAdapter):
        """Test that virtual printer shows full toner."""
        status = adapter.get_status("Virtual Printer")
        assert status.toner_status == TonerStatus.OK
        assert status.toner_level == 1.0

    def test_get_status_no_error(self, adapter: VirtualAdapter):
        """Test that virtual printer has no error."""
        status = adapter.get_status("Virtual Printer")
        assert status.error_message is None


class TestSubmitJob:
    """Tests for submitting print jobs."""

    def test_submit_job_creates_file(self, adapter: VirtualAdapter, sample_pdf: Path):
        """Test that submitting a job creates an output file."""
        job_id = adapter.submit_job("Virtual Printer", str(sample_pdf))
        assert job_id.startswith("VJOB-")

        # Check output files were created
        output_files = list(adapter.output_dir.glob("print_*.pdf"))
        assert len(output_files) == 1

    def test_submit_job_creates_metadata(self, adapter: VirtualAdapter, sample_pdf: Path):
        """Test that submitting a job creates a metadata file."""
        job_id = adapter.submit_job("Virtual Printer", str(sample_pdf))

        metadata_files = list(adapter.output_dir.glob("print_*.json"))
        assert len(metadata_files) == 1

        with open(metadata_files[0]) as f:
            metadata = json.load(f)
        assert metadata["job_id"] == job_id
        assert metadata["status"] == "completed"
        assert "submitted_at" in metadata

    def test_submit_job_with_options(self, adapter: VirtualAdapter, sample_pdf: Path):
        """Test submitting a job with print options."""
        options = {
            "copies": 3,
            "color_mode": "color",
            "duplex": "double",
        }
        job_id = adapter.submit_job("Virtual Printer", str(sample_pdf), options)

        metadata_files = list(adapter.output_dir.glob("print_*.json"))
        with open(metadata_files[0]) as f:
            metadata = json.load(f)
        assert metadata["options"]["copies"] == 3
        assert metadata["options"]["color_mode"] == "color"

    def test_submit_job_nonexistent_file(self, adapter: VirtualAdapter):
        """Test that submitting a nonexistent file raises RuntimeError."""
        with pytest.raises(RuntimeError, match="does not exist"):
            adapter.submit_job("Virtual Printer", "/nonexistent/file.pdf")

    def test_submit_job_returns_unique_ids(self, adapter: VirtualAdapter, sample_pdf: Path):
        """Test that each job gets a unique ID."""
        job_id1 = adapter.submit_job("Virtual Printer", str(sample_pdf))
        job_id2 = adapter.submit_job("Virtual Printer", str(sample_pdf))
        assert job_id1 != job_id2


class TestCancelJob:
    """Tests for cancelling print jobs."""

    def test_cancel_nonexistent_job(self, adapter: VirtualAdapter):
        """Test that cancelling a nonexistent job returns False."""
        assert adapter.cancel_job("NONEXISTENT") is False

    def test_cancel_completed_job(self, adapter: VirtualAdapter, sample_pdf: Path):
        """Test that cancelling a completed job returns False."""
        job_id = adapter.submit_job("Virtual Printer", str(sample_pdf))
        assert adapter.cancel_job(job_id) is False


class TestGetJobStatus:
    """Tests for getting job status."""

    def test_get_job_status_existing(self, adapter: VirtualAdapter, sample_pdf: Path):
        """Test getting status of an existing job."""
        job_id = adapter.submit_job("Virtual Printer", str(sample_pdf))
        status = adapter.get_job_status(job_id)
        assert status["id"] == job_id
        assert status["status"] == "completed"

    def test_get_job_status_nonexistent(self, adapter: VirtualAdapter):
        """Test getting status of a nonexistent job."""
        status = adapter.get_job_status("NONEXISTENT")
        assert status["status"] == "unknown"


class TestGetCapabilities:
    """Tests for printer capabilities."""

    def test_get_capabilities_returns_dict(self, adapter: VirtualAdapter):
        """Test that capabilities is returned as a dictionary."""
        caps = adapter.get_capabilities("Virtual Printer")
        assert isinstance(caps, dict)

    def test_get_capabilities_supports_all(self, adapter: VirtualAdapter):
        """Test that virtual printer supports all features."""
        caps = adapter.get_capabilities("Virtual Printer")
        assert caps["supports_color"] is True
        assert caps["supports_duplex"] is True
        assert caps["supports_page_range"] is True
        assert caps["max_copies"] == 999

    def test_get_capabilities_paper_sizes(self, adapter: VirtualAdapter):
        """Test that virtual printer lists paper sizes."""
        caps = adapter.get_capabilities("Virtual Printer")
        assert "A4" in caps["supported_paper_sizes"]
        assert "Letter" in caps["supported_paper_sizes"]
