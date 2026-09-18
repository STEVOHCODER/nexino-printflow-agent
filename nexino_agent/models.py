"""Data models for the Nexino PrintFlow agent."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime


class PaperStatus(Enum):
    """Paper status for a printer."""
    OK = "OK"
    LOW = "LOW"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


class TonerStatus(Enum):
    """Toner/ink status for a printer."""
    OK = "OK"
    LOW = "LOW"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


class PrinterState(Enum):
    """Printer state — must match backend PrinterState enum."""
    IDLE = "IDLE"
    # UNKNOWN is agent-side only; it is mapped to OFFLINE before being
    # sent to the backend, whose schema accepts only the 5 states above.
    UNKNOWN = "UNKNOWN"
    PRINTING = "PRINTING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"


class JobStatus(Enum):
    """Print job status — must match backend PrintJobStatus enum."""
    QUEUED = "QUEUED"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    PRINT_FAILED = "PRINT_FAILED"
    PRINTER_OFFLINE = "PRINTER_OFFLINE"
    PRINTER_ERROR = "PRINTER_ERROR"
    CANCELLED = "CANCELLED"


class ColorMode(Enum):
    """Print color mode — must match backend ColorMode enum."""
    BW = "BW"
    COLOR = "COLOR"


class DuplexMode(Enum):
    """Duplex (double-sided) printing mode."""
    OFF = "OFF"
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"


@dataclass
class PrintJob:
    """Represents a print job to be processed by the agent.

    Attributes:
        job_id: Unique identifier for this print job.
        file_url: URL to download the PDF file from the backend.
        copies: Number of copies to print.
        page_range: Page range to print (e.g., "1-5" or "all").
        color_mode: Color mode for printing.
        paper_size: Paper size (e.g., "A4", "Letter").
        duplex: Duplex printing mode.
        authorization_token: Token verifying this job was authorized by the backend.
        station_id: Station ID this job is assigned to.
    """

    job_id: str
    file_url: str
    copies: int = 1
    page_range: str = "all"
    color_mode: ColorMode = ColorMode.BW
    paper_size: str = "A4"
    duplex: DuplexMode = DuplexMode.OFF
    authorization_token: str = ""
    station_id: str = ""
    status: JobStatus = JobStatus.QUEUED
    created_at: Optional[datetime] = None
    error_message: Optional[str] = None
    local_file_path: Optional[str] = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrintJob":
        """Create a PrintJob from a dictionary (e.g., API response).

        Args:
            data: Dictionary with job data (backend camelCase format).

        Returns:
            PrintJob instance.
        """
        # Use downloadUrl if provided (Cloudinary), otherwise construct from file data
        file_url = data.get("downloadUrl", "")
        if not file_url:
            file_data = data.get("file", {})
            stored_filename = file_data.get("storedFilename", "")
            file_url = f"/uploads/{stored_filename}" if stored_filename else ""

        color_str = data.get("colorMode", "BW")
        try:
            color_mode = ColorMode(color_str.upper())
        except ValueError:
            color_mode = ColorMode.BW

        duplex_raw = data.get("duplex", False)
        if isinstance(duplex_raw, bool):
            duplex = DuplexMode.DOUBLE if duplex_raw else DuplexMode.OFF
        else:
            try:
                duplex = DuplexMode(duplex_raw.upper())
            except (ValueError, AttributeError):
                duplex = DuplexMode.OFF

        return cls(
            job_id=data.get("jobId", data.get("job_id", "")),
            file_url=file_url,
            copies=data.get("copies", 1),
            page_range=data.get("pageRange", data.get("page_range", "all")),
            color_mode=color_mode,
            paper_size=data.get("paperSize", data.get("paper_size", "A4")),
            duplex=duplex,
            authorization_token=data.get("authorizationToken", data.get("authorization_token", "")),
            station_id=data.get("stationId", data.get("station_id", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation.
        """
        return {
            "job_id": self.job_id,
            "file_url": self.file_url,
            "copies": self.copies,
            "page_range": self.page_range,
            "color_mode": self.color_mode.value,
            "paper_size": self.paper_size,
            "duplex": self.duplex.value,
            "authorization_token": self.authorization_token,
            "station_id": self.station_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "error_message": self.error_message,
            "local_file_path": self.local_file_path,
        }


@dataclass
class PrinterStatus:
    """Current status of a printer.

    Attributes:
        name: Printer name as known to the OS.
        state: Current printer state.
        paper_status: Paper level status.
        paper_level: Approximate paper level (0.0-1.0) if known, else None.
        toner_status: Toner/ink level status.
        toner_level: Approximate toner level (0.0-1.0) if known, else None.
        error_message: Current error message if any.
    """

    name: str
    state: PrinterState = PrinterState.OFFLINE
    paper_status: PaperStatus = PaperStatus.UNKNOWN
    paper_level: Optional[float] = None
    toner_status: TonerStatus = TonerStatus.UNKNOWN
    toner_level: Optional[float] = None
    error_message: Optional[str] = None
    last_checked: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.last_checked is None:
            self.last_checked = datetime.utcnow()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrinterStatus":
        """Create PrinterStatus from a dictionary.

        Args:
            data: Dictionary with status data.

        Returns:
            PrinterStatus instance.
        """
        return cls(
            name=data.get("name", ""),
            state=PrinterState(data.get("state", "OFFLINE").upper()),
            paper_status=PaperStatus(data.get("paper_status", "UNKNOWN").upper()),
            paper_level=data.get("paper_level"),
            toner_status=TonerStatus(data.get("toner_status", "UNKNOWN").upper()),
            toner_level=data.get("toner_level"),
            error_message=data.get("error_message"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation.
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "paper_status": self.paper_status.value,
            "paper_level": self.paper_level,
            "toner_status": self.toner_status.value,
            "toner_level": self.toner_level,
            "error_message": self.error_message,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
        }


@dataclass
class AgentStatus:
    """Status of the print agent itself.

    Attributes:
        agent_id: Unique identifier for this agent.
        station_id: Station this agent serves.
        is_running: Whether the agent is currently running.
        uptime_seconds: How long the agent has been running.
        jobs_processed: Total jobs processed since startup.
        jobs_failed: Total jobs that failed since startup.
        last_heartbeat: Timestamp of last heartbeat.
        printer_name: Name of the configured printer.
        printer_online: Whether the printer is currently online.
    """

    agent_id: str = ""
    station_id: str = ""
    is_running: bool = False
    uptime_seconds: float = 0.0
    jobs_processed: int = 0
    jobs_failed: int = 0
    last_heartbeat: Optional[datetime] = None
    printer_name: str = ""
    printer_online: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation.
        """
        return {
            "agent_id": self.agent_id,
            "station_id": self.station_id,
            "is_running": self.is_running,
            "uptime_seconds": self.uptime_seconds,
            "jobs_processed": self.jobs_processed,
            "jobs_failed": self.jobs_failed,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "printer_name": self.printer_name,
            "printer_online": self.printer_online,
        }
