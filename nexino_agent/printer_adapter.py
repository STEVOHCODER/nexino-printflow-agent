"""Abstract base class for printer adapters.

All printer adapters must implement this interface to integrate with the
Nexino PrintFlow agent.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional

from .models import PrinterStatus


class PrinterAdapter(ABC):
    """Abstract base class for printer adapters.

    Printer adapters provide a unified interface for interacting with different
    printing systems (virtual, Windows, CUPS, IPP). To add a new printer type,
    create a subclass that implements all abstract methods.
    """

    @abstractmethod
    def discover(self) -> List[Dict]:
        """Discover available printers.

        Returns:
            List of dictionaries containing printer information.
            Each dict should have at least 'name' and 'status' keys.
        """
        ...

    @abstractmethod
    def get_status(self, printer_name: str) -> PrinterStatus:
        """Get current status of a specific printer.

        Args:
            printer_name: Name of the printer.

        Returns:
            PrinterStatus with current state information.
        """
        ...

    @abstractmethod
    def submit_job(self, printer_name: str, file_path: str, options: Optional[Dict] = None) -> str:
        """Submit a print job to the printer.

        Args:
            printer_name: Name of the printer to send to.
            file_path: Path to the file to print (typically a PDF).
            options: Optional print options (copies, color mode, duplex, etc.).

        Returns:
            Printer job ID or tracking identifier.

        Raises:
            RuntimeError: If the job cannot be submitted.
        """
        ...

    @abstractmethod
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending or in-progress print job.

        Args:
            job_id: The job ID returned by submit_job().

        Returns:
            True if the job was successfully cancelled, False otherwise.
        """
        ...

    @abstractmethod
    def get_job_status(self, job_id: str) -> Dict:
        """Get the status of a specific print job.

        Args:
            job_id: The job ID returned by submit_job().

        Returns:
            Dictionary with job status information including at least
            'status' and 'message' keys.
        """
        ...

    @abstractmethod
    def get_capabilities(self, printer_name: str) -> Dict:
        """Get the capabilities of a printer.

        Args:
            printer_name: Name of the printer.

        Returns:
            Dictionary describing printer capabilities:
            - supported_paper_sizes: List of paper sizes
            - supports_color: Boolean
            - supports_duplex: Boolean
            - max_copies: Integer
            - supports_page_range: Boolean
        """
        ...
