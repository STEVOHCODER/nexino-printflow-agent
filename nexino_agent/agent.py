"""Main Nexino PrintFlow agent that orchestrates printing operations.

Fully autonomous: auto-retries failed jobs, auto-reconnects to backend,
no human intervention needed at the print station.
"""

import sys
import time
import signal
import logging
import hashlib
import tempfile
import threading
from pathlib import Path
from typing import Optional, Set
from datetime import datetime

from .config import AgentConfig
from .api_client import NexinoAPIClient, APIError
from .printer_adapter import PrinterAdapter
from .adapters import VirtualAdapter, WindowsAdapter, CupsAdapter, IPPAdapter
from .models import (
    PrintJob,
    JobStatus,
    PrinterStatus,
    PrinterState,
)
from .monitoring import PrinterMonitor

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
RECONNECT_DELAY_SECONDS = 10
MAX_RECONNECT_ATTEMPTS = 60


class NexinoAgent:
    """Main agent class. Fully autonomous print job processing."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.api_client = NexinoAPIClient(config)
        self.adapter: PrinterAdapter = self._create_adapter()
        self.monitor = PrinterMonitor(self.adapter, config)

        self._running = False
        self._processed_jobs: Set[str] = set()
        self._start_time: Optional[datetime] = None
        self._jobs_processed = 0
        self._jobs_failed = 0
        self._lock = threading.Lock()
        self._printer_ids: dict[str, str] = {}
        self._registered_printers: list[dict] = []
        self._consecutive_errors = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _create_adapter(self) -> PrinterAdapter:
        if self.config.virtual_mode:
            logger.info("Using virtual printer adapter (test mode).")
            return VirtualAdapter(
                output_dir=self.config.output_directory or None,
                simulate_delay=True,
                delay_seconds=0.5,
            )

        if sys.platform == "win32":
            logger.info("Using Windows printer adapter.")
            return WindowsAdapter()
        elif sys.platform == "linux":
            try:
                adapter = CupsAdapter()
                printers = adapter.discover()
                if printers:
                    logger.info("Using CUPS printer adapter.")
                    return adapter
                else:
                    logger.info("No CUPS printers found. Using IPP adapter.")
                    return IPPAdapter()
            except Exception as e:
                logger.warning(f"CUPS adapter failed: {e}. Using IPP adapter.")
                return IPPAdapter()
        else:
            logger.warning(f"Unsupported platform '{sys.platform}'. Using IPP adapter.")
            return IPPAdapter()

    def _auto_register(self) -> None:
        import socket
        from .auto_register import AutoRegistrar

        hostname = socket.gethostname()
        platform = sys.platform

        detected = self.adapter.discover()
        if not detected:
            logger.warning("No printers detected. Cannot auto-register.")
            return

        from .api_client import AgentApiClient
        client = AgentApiClient(
            self.config.backend_url,
            self.config.agent_id or "auto",
            self.config.agent_secret,
        )

        result = client.auto_register(hostname, platform, detected)
        if not result.get("success"):
            logger.error(f"Auto-registration failed: {result}")
            return

        data = result.get("data", {})
        self.config.agent_id = data.get("agentId", self.config.agent_id)
        self._registered_printers = data.get("stations", [])

        for station in self._registered_printers:
            station_printers = station.get("printers", [])
            for p in station_printers:
                self._printer_ids[p.get("name", "")] = p.get("id", "")

        if not self.config.station_id and self._registered_printers:
            self.config.station_id = self._registered_printers[0].get("stationId", "")

        self.config.save()
        logger.info(f"Auto-registered: agentId={self.config.agent_id}, printers={list(self._printer_ids.keys())}")

    def _validate_print_options(self, printer_name: str, options: dict) -> None:
        try:
            caps = self.adapter.get_capabilities(printer_name)
        except Exception:
            return

        if not caps:
            return

        paper_size = options.get("paper_size")
        if paper_size and caps.get("supported_paper_sizes"):
            supported = [s.upper() for s in caps["supported_paper_sizes"]]
            if paper_size.upper() not in supported:
                logger.warning(
                    f"Paper size '{paper_size}' may not be supported by {printer_name}. "
                    f"Supported: {caps['supported_paper_sizes']}"
                )

        color_mode = options.get("color_mode")
        if color_mode and caps.get("supports_color") is False:
            if color_mode.upper() not in ("BW", "MONOCHROME"):
                raise ValueError(
                    f"Printer '{printer_name}' does not support color printing. Use BW."
                )

    def _signal_handler(self, signum, frame) -> None:
        logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
        self.stop()

    def _generate_job_token(self, job: PrintJob) -> str:
        data = f"{job.job_id}:{job.authorization_token}:{self.config.agent_secret}"
        return hashlib.sha256(data.encode()).hexdigest()

    def start(self) -> None:
        logger.info("=" * 60)
        logger.info("Nexino PrintFlow Agent starting...")
        logger.info(f"  Agent ID: {self.config.agent_id}")
        logger.info(f"  Station ID: {self.config.station_id}")
        logger.info(f"  Virtual Mode: {self.config.virtual_mode}")
        logger.info(f"  Poll Interval: {self.config.poll_interval_seconds}s")
        logger.info(f"  Backend URL: {self.config.backend_url}")
        logger.info("=" * 60)

        self._running = True
        self._start_time = datetime.utcnow()

        if not self.config.agent_id:
            try:
                logger.info("Auto-registering agent with backend...")
                self._auto_register()
            except Exception as e:
                logger.error(f"Auto-registration failed: {e}")
                logger.error("Will retry on next heartbeat...")

        monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="printer-monitor"
        )
        monitor_thread.start()

        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="heartbeat"
        )
        heartbeat_thread.start()

        logger.info("Agent started. Press Ctrl+C to stop.")

        try:
            while self._running:
                try:
                    self.poll_for_jobs()
                    self._consecutive_errors = 0
                except Exception as e:
                    self._consecutive_errors += 1
                    logger.error(f"Poll error ({self._consecutive_errors}): {e}")

                    if self._consecutive_errors >= 10:
                        logger.warning("Too many consecutive errors. Reconnecting in 30s...")
                        time.sleep(30)
                        self._try_reconnect()
                    else:
                        time.sleep(min(self._consecutive_errors * 2, 30))

                time.sleep(self.config.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received.")
        finally:
            self.stop()

    def _try_reconnect(self) -> None:
        """Attempt to reconnect to the backend."""
        logger.info("Attempting to reconnect to backend...")
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            try:
                self.api_client = NexinoAPIClient(self.config)
                result = self.api_client.heartbeat()
                logger.info(f"Reconnected to backend on attempt {attempt + 1}.")
                self._consecutive_errors = 0
                return
            except Exception as e:
                logger.debug(f"Reconnect attempt {attempt + 1} failed: {e}")
                time.sleep(RECONNECT_DELAY_SECONDS)

        logger.error("Failed to reconnect after maximum attempts. Restart recommended.")

    def stop(self) -> None:
        if not self._running:
            return

        logger.info("Stopping agent...")
        self._running = False

        if self._start_time:
            uptime = (datetime.utcnow() - self._start_time).total_seconds()
            logger.info(
                f"Agent stopped. Uptime: {uptime:.0f}s, "
                f"Jobs processed: {self._jobs_processed}, "
                f"Jobs failed: {self._jobs_failed}"
            )

    def poll_for_jobs(self) -> None:
        try:
            jobs = self.api_client.get_pending_jobs()
        except APIError as e:
            logger.error(f"Failed to poll for jobs: {e}")
            return

        for job in jobs:
            with self._lock:
                if job.job_id in self._processed_jobs:
                    logger.debug(f"Skipping already processed job {job.job_id}.")
                    continue
                self._processed_jobs.add(job.job_id)

            job_thread = threading.Thread(
                target=self._process_job_with_retry,
                args=(job,),
                daemon=True,
                name=f"job-{job.job_id[:12]}",
            )
            job_thread.start()

    def _process_job_with_retry(self, job: PrintJob) -> None:
        """Process a job with automatic retry on transient failures."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self.process_job(job)
                return  # Success
            except Exception as e:
                error_msg = str(e)
                is_transient = any(term in error_msg.lower() for term in [
                    "timeout", "connection", "network", "busy", " unavailable",
                    "could not connect", "remote", "timed out",
                ])

                if is_transient and attempt < MAX_RETRIES:
                    logger.warning(
                        f"Job {job.job_id} attempt {attempt} failed (transient): {error_msg}. "
                        f"Retrying in {RETRY_DELAY_SECONDS}s..."
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    # Non-transient or final attempt
                    logger.error(f"Job {job.job_id} failed permanently: {error_msg}")
                    with self._lock:
                        self._jobs_failed += 1
                    try:
                        self.api_client.update_job_status(
                            job.job_id, JobStatus.PRINT_FAILED, error_message=error_msg
                        )
                    except APIError as api_err:
                        logger.error(f"Failed to report job failure: {api_err}")
                    return

    def process_job(self, job: PrintJob) -> None:
        logger.info(f"Processing job {job.job_id}...")

        if not job.authorization_token:
            raise ValueError("Job has no authorization token.")

        self.api_client.update_job_status(job.job_id, JobStatus.PRINTING)

        download_dir = Path(self.config.output_directory or tempfile.gettempdir()) / "nexino-downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        file_path = download_dir / f"{job.job_id}.pdf"

        logger.info(f"Downloading file for job {job.job_id}...")
        download_url = f"{self.config.backend_url}/api/agent/download/{job.job_id}"
        self.api_client.download_file(download_url, str(file_path))
        job.local_file_path = str(file_path)

        self.api_client.update_job_status(job.job_id, JobStatus.PRINTING)

        options = {
            "copies": job.copies,
            "color_mode": job.color_mode.value,
            "duplex": job.duplex.value,
            "paper_size": job.paper_size,
            "page_range": job.page_range,
        }

        printer_name = self.config.printer_name
        if not printer_name:
            printers = self.adapter.discover()
            real_printers = [p for p in printers if "virtual" not in p.get("name", "").lower()]
            if real_printers:
                printer_name = real_printers[0]["name"]
            elif printers:
                printer_name = printers[0]["name"]
            else:
                raise RuntimeError("No printer available.")

        self._validate_print_options(printer_name, options)

        logger.info(f"Submitting job {job.job_id} to printer '{printer_name}'...")
        printer_job_id = self.adapter.submit_job(
            printer_name, str(file_path), options
        )

        self.api_client.update_job_status(job.job_id, JobStatus.COMPLETED)

        with self._lock:
            self._jobs_processed += 1

        logger.info(
            f"Job {job.job_id} completed successfully. "
            f"Printer job ID: {printer_job_id}"
        )

        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self.monitor.check_status()
            except Exception as e:
                logger.debug(f"Error checking printer status: {e}")

            time.sleep(self.config.status_check_interval_seconds)

    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                printer_list = self._get_printer_heartbeats()
                self.api_client.heartbeat(printers=printer_list)
            except APIError as e:
                logger.debug(f"Heartbeat failed: {e}")
            except Exception as e:
                logger.debug(f"Error in heartbeat loop: {e}")

            time.sleep(self.config.heartbeat_interval_seconds)

    def _get_printer_heartbeats(self) -> list[dict]:
        if not self._printer_ids:
            return []

        heartbeats = []
        for printer_name, printer_uuid in self._printer_ids.items():
            try:
                status = self.adapter.get_status(printer_name)
                heartbeats.append({
                    "printerId": printer_uuid,
                    "status": status.state.value if status.state else "OFFLINE",
                    "paperStatus": status.paper_status.value if status.paper_status else "UNKNOWN",
                    "paperLevel": status.paper_level if status.paper_level is not None else None,
                    "tonerStatus": status.toner_status.value if status.toner_status else "UNKNOWN",
                    "tonerLevel": status.toner_level if status.toner_level is not None else None,
                })
            except Exception as e:
                logger.debug(f"Failed to get status for printer {printer_name}: {e}")
                heartbeats.append({
                    "printerId": printer_uuid,
                    "status": "ERROR",
                })

        return heartbeats

    def get_status(self) -> dict:
        uptime = 0.0
        if self._start_time:
            uptime = (datetime.utcnow() - self._start_time).total_seconds()

        printer_status = self.monitor.last_status
        printer_online = (
            printer_status.state == PrinterState.IDLE if printer_status else False
        )

        return {
            "agent_id": self.config.agent_id,
            "station_id": self.config.station_id,
            "is_running": self._running,
            "uptime_seconds": uptime,
            "jobs_processed": self._jobs_processed,
            "jobs_failed": self._jobs_failed,
            "printer_name": self.config.printer_name,
            "printer_online": printer_online,
            "virtual_mode": self.config.virtual_mode,
        }

    def test_connection(self) -> bool:
        try:
            logger.info(f"Testing connection to {self.config.backend_url}...")
            result = self.api_client.heartbeat()
            logger.info("Connection successful.")
            return True
        except APIError as e:
            logger.error(f"Connection test failed: {e}")
            return False
