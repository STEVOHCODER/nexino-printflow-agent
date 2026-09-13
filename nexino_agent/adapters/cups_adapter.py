"""CUPS printer adapter for Linux/Unix systems.

This adapter communicates with printers through the CUPS printing system
using standard command-line tools (lp, lpstat, lpadmin).
"""

import subprocess
import logging
import json
import re
import time
import uuid
from typing import Dict, List, Optional
from pathlib import Path

from ..printer_adapter import PrinterAdapter
from ..models import (
    PrinterStatus,
    PrinterState,
    PaperStatus,
    TonerStatus,
)

logger = logging.getLogger(__name__)


class CupsAdapter(PrinterAdapter):
    """CUPS printer adapter for Linux/Unix systems.

    Uses standard CUPS command-line tools (lp, lpstat, lpadmin) to
    discover and communicate with printers.
    """

    def __init__(self) -> None:
        """Initialize the CUPS adapter."""
        self._jobs: Dict[str, Dict] = {}
        self._check_availability()

    def _check_availability(self) -> None:
        """Check if CUPS tools are available."""
        try:
            result = subprocess.run(
                ["which", "lpstat"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("CUPS adapter initialized. lpstat is available.")
            else:
                logger.warning("lpstat not found. CUPS adapter may not work.")
        except FileNotFoundError:
            logger.error("CUPS tools not found. CUPS adapter will not work.")
        except Exception as e:
            logger.warning(f"Error checking CUPS availability: {e}")

    def _run_command(self, cmd: List[str], timeout: int = 10) -> Dict:
        """Execute a shell command and return output.

        Args:
            cmd: Command and arguments as a list.
            timeout: Timeout in seconds.

        Returns:
            Dictionary with 'success', 'output', and 'error' keys.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": "Command timed out"}
        except Exception as e:
            return {"success": False, "output": "", "error": str(e)}

    def discover(self) -> List[Dict]:
        """Discover printers available through CUPS.

        Uses lpstat -p -d to list all configured printers.

        Returns:
            List of dictionaries with printer information.
        """
        result = self._run_command(["lpstat", "-p", "-d"])

        if not result["success"]:
            logger.error(f"Failed to discover CUPS printers: {result['error']}")
            return []

        printers = []
        for line in result["output"].splitlines():
            # Parse lines like: "printer PrinterName is idle." or "printer PrinterName disabled since ..."
            match = re.match(r"printer\s+(\S+)\s+(.*)", line)
            if match:
                name = match.group(1)
                status_text = match.group(2)
                is_disabled = "disabled" in status_text.lower()
                printers.append({
                    "name": name,
                    "status": "disabled" if is_disabled else "available",
                    "type": "cups",
                    "status_text": status_text,
                })

        # Get default printer
        default_match = re.search(r"system default destination:\s+(\S+)", result["output"])
        if default_match:
            default_name = default_match.group(1)
            for p in printers:
                if p["name"] == default_name:
                    p["is_default"] = True

        logger.info(f"Discovered {len(printers)} CUPS printer(s).")
        return printers

    def get_status(self, printer_name: str) -> PrinterStatus:
        """Get status of a CUPS printer.

        Uses lpstat -p and lpstat -l to get detailed printer information.

        Args:
            printer_name: Name of the CUPS printer.

        Returns:
            PrinterStatus with current state.
        """
        # Get basic printer status
        result = self._run_command(["lpstat", "-p", printer_name])

        if not result["success"]:
            logger.warning(f"Could not get status for printer '{printer_name}': {result['error']}")
            return PrinterStatus(
                name=printer_name,
                state=PrinterState.UNKNOWN,
                error_message=result.get("error"),
            )

        # Parse status from lpstat output
        state = PrinterState.IDLE
        error_message = None
        output = result["output"].lower()

        if "disabled" in output or "stopped" in output:
            state = PrinterState.OFFLINE
        elif "error" in output or "fault" in output:
            state = PrinterState.ERROR
            error_message = result["output"]

        # Try to get detailed status
        detail_result = self._run_command(["lpstat", "-l", "-p", printer_name])
        paper_status = PaperStatus.UNKNOWN
        paper_level = None
        toner_status = TonerStatus.UNKNOWN
        toner_level = None

        if detail_result["success"]:
            detail_output = detail_result["output"].lower()
            if "paper out" in detail_output or "no paper" in detail_output:
                paper_status = PaperStatus.EMPTY
                paper_level = 0.0
            elif "low paper" in detail_output or "paper low" in detail_output:
                paper_status = PaperStatus.LOW
                paper_level = 0.2
            elif "ready" in detail_output or "idle" in detail_output:
                paper_status = PaperStatus.OK
                paper_level = 0.8

            if "toner low" in detail_output or "ink low" in detail_output:
                toner_status = TonerStatus.LOW
                toner_level = 0.2
            elif "toner out" in detail_output or "ink out" in detail_output:
                toner_status = TonerStatus.EMPTY
                toner_level = 0.0

        return PrinterStatus(
            name=printer_name,
            state=state,
            paper_status=paper_status,
            paper_level=paper_level,
            toner_status=toner_status,
            toner_level=toner_level,
            error_message=error_message,
        )

    def submit_job(
        self,
        printer_name: str,
        file_path: str,
        options: Optional[Dict] = None,
    ) -> str:
        """Submit a print job to a CUPS printer.

        Uses the lp command to submit print jobs.

        Args:
            printer_name: Name of the CUPS printer.
            file_path: Path to the file to print.
            options: Print options (copies, color_mode, duplex, page_range).

        Returns:
            Job ID for tracking.

        Raises:
            RuntimeError: If the job cannot be submitted.
        """
        job_id = f"CUPS-{uuid.uuid4().hex[:12].upper()}"
        options = options or {}

        cmd = ["lp", "-d", printer_name]

        # Add options
        copies = options.get("copies", 1)
        if copies > 1:
            cmd.extend(["-n", str(copies)])

        page_range = options.get("page_range", "all")
        if page_range and page_range != "all":
            cmd.extend(["-P", page_range])

        color_mode = options.get("color_mode", "auto")
        if color_mode == "monochrome":
            cmd.extend(["-o", "ColorModel=Gray"])
        elif color_mode == "color":
            cmd.extend(["-o", "ColorModel=RGB"])

        duplex = options.get("duplex", "auto")
        if duplex == "double":
            cmd.extend(["-o", "sides=two-sided-long-edge"])
        elif duplex == "single":
            cmd.extend(["-o", "sides=one-sided"])

        paper_size = options.get("paper_size", "A4")
        if paper_size:
            cmd.extend(["-o", f"media={paper_size}"])

        # Add the file
        cmd.append(str(file_path))

        logger.info(f"Submitting CUPS job: {' '.join(cmd)}")
        result = self._run_command(cmd, timeout=30)

        if not result["success"]:
            raise RuntimeError(f"Failed to submit CUPS job: {result['error']}")

        # Parse lp output for request ID
        # Output format: "request id is PrinterName-123 (1 file(s))"
        request_match = re.search(r"request id is\s+(\S+)", result["output"])
        cups_request_id = request_match.group(1) if request_match else job_id

        self._jobs[job_id] = {
            "id": job_id,
            "cups_request_id": cups_request_id,
            "status": "submitted",
            "printer": printer_name,
            "file": str(file_path),
            "submitted_at": time.time(),
        }

        logger.info(f"CUPS job {job_id} submitted (CUPS ID: {cups_request_id}).")
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a CUPS print job.

        Uses cancel command to remove the job from the queue.

        Args:
            job_id: The job ID.

        Returns:
            True if cancelled successfully.
        """
        if job_id not in self._jobs:
            return False

        job = self._jobs[job_id]
        cups_request_id = job.get("cups_request_id", "")

        if cups_request_id:
            result = self._run_command(["cancel", cups_request_id])
            if result["success"]:
                job["status"] = "cancelled"
                logger.info(f"CUPS job {job_id} cancelled.")
                return True

        logger.warning(f"Failed to cancel CUPS job {job_id}.")
        return False

    def get_job_status(self, job_id: str) -> Dict:
        """Get the status of a CUPS print job.

        Uses lpstat -W to check job status.

        Args:
            job_id: The job ID.

        Returns:
            Dictionary with job status.
        """
        if job_id not in self._jobs:
            return {"id": job_id, "status": "unknown", "message": "Job not found"}

        job = self._jobs[job_id]
        cups_request_id = job.get("cups_request_id", "")

        if cups_request_id:
            # Check if job is still in queue
            result = self._run_command(["lpstat", "-W", "all"])
            if result["success"] and cups_request_id in result["output"]:
                return {**job, "status": "in_queue"}
            else:
                return {**job, "status": "completed"}

        return job

    def get_capabilities(self, printer_name: str) -> Dict:
        """Get capabilities of a CUPS printer.

        Uses lpoptions to query printer capabilities.

        Args:
            printer_name: Name of the CUPS printer.

        Returns:
            Dictionary of supported capabilities.
        """
        result = self._run_command(["lpoptions", "-p", printer_name, "-l"])

        capabilities = {
            "supported_paper_sizes": ["A4", "Letter", "Legal"],
            "supports_color": True,
            "supports_duplex": True,
            "max_copies": 99,
            "supports_page_range": True,
        }

        if result["success"]:
            # Parse lpoptions output for media sizes
            for line in result["output"].splitlines():
                if "/media" in line.lower():
                    # Format: "MediaSize/media Size1 *Size2 Size3"
                    sizes = line.split("/")[-1].split()
                    clean_sizes = [s.lstrip("*") for s in sizes]
                    capabilities["supported_paper_sizes"] = clean_sizes
                elif "/color" in line.lower():
                    capabilities["supports_color"] = True
                elif "/duplex" in line.lower():
                    capabilities["supports_duplex"] = True

        return capabilities
