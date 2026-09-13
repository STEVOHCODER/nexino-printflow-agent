"""Virtual printer adapter for testing and development.

This adapter simulates a printer by saving PDFs to a local output directory
and tracking jobs in memory. It's useful for development and testing without
a physical printer.
"""

import json
import time
import shutil
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from ..printer_adapter import PrinterAdapter
from ..models import (
    PrinterStatus,
    PrinterState,
    PaperStatus,
    TonerStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


class VirtualAdapter(PrinterAdapter):
    """Virtual printer adapter that saves PDFs to disk.

    Simulates printing by copying PDF files to an output directory and creating
    metadata files alongside them. Useful for development and testing.
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        simulate_delay: bool = True,
        delay_seconds: float = 0.5,
    ) -> None:
        """Initialize the virtual adapter.

        Args:
            output_dir: Directory to save "printed" files. Defaults to ./output.
            simulate_delay: Whether to simulate printing delays.
            delay_seconds: Delay in seconds to simulate printing.
        """
        self.output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.simulate_delay = simulate_delay
        self.delay_seconds = delay_seconds

        # In-memory job tracking
        self._jobs: Dict[str, Dict] = {}
        self._printer_name = "Virtual Printer"
        self._printer_state = PrinterState.IDLE

        logger.info(
            f"Virtual adapter initialized. Output directory: {self.output_dir}"
        )

    def discover(self) -> List[Dict]:
        """Discover the virtual printer.

        Returns:
            List containing a single virtual printer entry.
        """
        return [
            {
                "name": self._printer_name,
                "status": "available",
                "type": "virtual",
                "description": "Virtual printer for testing",
            }
        ]

    def get_status(self, printer_name: str) -> PrinterStatus:
        """Get status of the virtual printer.

        Always returns online status with full paper and toner levels.

        Args:
            printer_name: Name of the printer (ignored for virtual adapter).

        Returns:
            PrinterStatus indicating the virtual printer is ready.
        """
        return PrinterStatus(
            name=printer_name or self._printer_name,
            state=self._printer_state,
            paper_status=PaperStatus.OK,
            paper_level=1.0,
            toner_status=TonerStatus.OK,
            toner_level=1.0,
            error_message=None,
        )

    def submit_job(
        self,
        printer_name: str,
        file_path: str,
        options: Optional[Dict] = None,
    ) -> str:
        """Submit a print job to the virtual printer.

        Copies the PDF file to the output directory and creates a metadata
        JSON file alongside it.

        Args:
            printer_name: Printer name (ignored for virtual adapter).
            file_path: Path to the PDF file to print.
            options: Print options (copies, color_mode, duplex, etc.).

        Returns:
            Virtual job ID for tracking.

        Raises:
            RuntimeError: If the source file doesn't exist or can't be copied.
        """
        source = Path(file_path)
        if not source.exists():
            raise RuntimeError(f"Source file does not exist: {file_path}")

        job_id = f"VJOB-{uuid.uuid4().hex[:12].upper()}"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_name = f"print_{timestamp}_{job_id}"
        output_pdf = self.output_dir / f"{output_name}.pdf"

        if self.simulate_delay:
            time.sleep(self.delay_seconds)

        # Copy the file
        shutil.copy2(source, output_pdf)

        # Create metadata
        metadata = {
            "job_id": job_id,
            "source_file": str(source),
            "output_file": str(output_pdf),
            "printer_name": printer_name,
            "options": options or {},
            "submitted_at": datetime.utcnow().isoformat(),
            "status": "completed",
        }

        metadata_path = self.output_dir / f"{output_name}.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        # Track the job
        self._jobs[job_id] = {
            "id": job_id,
            "status": "completed",
            "file": str(output_pdf),
            "submitted_at": datetime.utcnow().isoformat(),
        }

        logger.info(
            f"Virtual job {job_id} completed. Output: {output_pdf}"
        )
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a virtual print job.

        Only pending jobs can be cancelled. Completed jobs cannot be undone.

        Args:
            job_id: The job ID to cancel.

        Returns:
            True if the job was cancelled, False if not found or already completed.
        """
        if job_id in self._jobs:
            job = self._jobs[job_id]
            if job["status"] == "pending":
                job["status"] = "cancelled"
                logger.info(f"Virtual job {job_id} cancelled.")
                return True
            else:
                logger.warning(
                    f"Cannot cancel virtual job {job_id}: status is {job['status']}"
                )
                return False
        logger.warning(f"Virtual job {job_id} not found.")
        return False

    def get_job_status(self, job_id: str) -> Dict:
        """Get the status of a virtual print job.

        Args:
            job_id: The job ID.

        Returns:
            Dictionary with job status information.
        """
        if job_id in self._jobs:
            return self._jobs[job_id]
        return {
            "id": job_id,
            "status": "unknown",
            "message": "Job not found",
        }

    def get_capabilities(self, printer_name: str) -> Dict:
        """Get capabilities of the virtual printer.

        Returns a comprehensive capability set since the virtual printer
        supports all options.

        Args:
            printer_name: Printer name (ignored).

        Returns:
            Dictionary of supported capabilities.
        """
        return {
            "supported_paper_sizes": [
                "A4", "A3", "Letter", "Legal", "Tabloid",
            ],
            "supports_color": True,
            "supports_duplex": True,
            "max_copies": 999,
            "supports_page_range": True,
            "supports_toner": False,
        }
