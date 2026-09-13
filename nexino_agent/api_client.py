"""Backend API client for the Nexino PrintFlow agent."""

import time
import logging
import hashlib
import hmac
from typing import Optional, Dict, Any, List
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import AgentConfig
from .models import PrintJob, PrinterStatus, JobStatus

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Exception raised when an API call fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class NexinoAPIClient:
    """Client for communicating with the Nexino PrintFlow backend.

    Handles registration, heartbeat, job polling, status updates, and file downloads
    with proper error handling, retries, and exponential backoff.
    """

    def __init__(self, config: AgentConfig):
        """Initialize the API client.

        Args:
            config: Agent configuration.
        """
        self.config = config
        self.base_url = config.backend_url.rstrip("/")
        self.session = self._create_session()
        self.access_token: Optional[str] = None

    def _create_session(self) -> requests.Session:
        """Create an HTTP session with retry logic.

        Returns:
            Configured requests.Session.
        """
        session = requests.Session()
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_base_delay,
            backoff_max=self.config.retry_max_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _sign_request(self, method: str, path: str, timestamp: str) -> str:
        """Generate HMAC signature for request authentication.

        Args:
            method: HTTP method.
            path: Request path.
            timestamp: ISO timestamp.

        Returns:
            Hex digest of HMAC signature.
        """
        message = f"{method.upper()}\n{path}\n{timestamp}"
        signature = hmac.new(
            self.config.agent_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return signature.hexdigest()

    def _get_headers(self, include_auth: bool = True) -> Dict[str, str]:
        """Get standard request headers.

        Args:
            include_auth: Whether to include authorization header.

        Returns:
            Dictionary of headers.
        """
        headers = {
            "Content-Type": "application/json",
        }
        if include_auth:
            headers["Authorization"] = f"Bearer {self.config.agent_secret}"
            headers["X-Agent-ID"] = self.config.agent_id
        return headers

    def register(self) -> Dict[str, Any]:
        """Register this agent with the Nexino backend.

        Returns:
            Registration response data.

        Raises:
            APIError: If registration fails.
        """
        path = "/api/agent/register"
        payload = {
            "agentId": self.config.agent_id,
            "stationId": self.config.station_id,
            "hostname": "nexino-agent",
            "platform": "python",
        }

        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.config.api_timeout,
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"Agent registered successfully. Agent ID: {self.config.agent_id}")
            return data
        except requests.exceptions.RequestException as e:
            raise APIError(f"Registration failed: {e}", getattr(e.response, "status_code", None))

    def heartbeat(self, printers: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Send a heartbeat to the backend to indicate agent is alive.

        Args:
            printers: Optional list of printer status dicts.

        Returns:
            Heartbeat response data.

        Raises:
            APIError: If heartbeat fails.
        """
        path = "/api/agent/heartbeat"
        payload = {
            "agentId": self.config.agent_id,
            "printers": printers or [],
        }

        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.config.api_timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise APIError(f"Heartbeat failed: {e}", getattr(e.response, "status_code", None))

    def get_pending_jobs(self) -> List[PrintJob]:
        """Poll for new authorized print jobs scoped to this agent's station.

        Returns:
            List of PrintJob instances waiting to be processed.

        Raises:
            APIError: If the request fails.
        """
        path = "/api/agent/jobs/poll"
        params = {}
        if self.config.station_id:
            params["stationId"] = self.config.station_id

        try:
            url = f"{self.base_url}{path}"
            response = self.session.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=self.config.api_timeout,
            )
            response.raise_for_status()
            data = response.json()
            jobs = [PrintJob.from_dict(j) for j in data.get("data", [])]
            if jobs:
                logger.info(f"Retrieved {len(jobs)} pending job(s).")
            return jobs
        except requests.exceptions.RequestException as e:
            raise APIError(f"Failed to get pending jobs: {e}", getattr(e.response, "status_code", None))

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Report a job status change to the backend.

        Args:
            job_id: The job ID.
            status: New status.
            error_message: Optional error message if status is FAILED.

        Returns:
            Response data.

        Raises:
            APIError: If the request fails.
        """
        path = f"/api/agent/jobs/{job_id}/status"
        payload: Dict[str, Any] = {
            "agentId": self.config.agent_id,
            "status": status.value,
        }
        if error_message:
            payload["errorMessage"] = error_message

        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.config.api_timeout,
            )
            response.raise_for_status()
            logger.info(f"Job {job_id} status updated to {status.value}.")
            return response.json()
        except requests.exceptions.RequestException as e:
            raise APIError(f"Failed to update job status: {e}", getattr(e.response, "status_code", None))

    def update_printer_status(self, printer_id: str, printer_status: PrinterStatus) -> Dict[str, Any]:
        """Report current printer status to the backend.

        Args:
            printer_id: The printer ID.
            printer_status: Current printer status.

        Returns:
            Response data.

        Raises:
            APIError: If the request fails.
        """
        path = f"/api/agent/printers/{printer_id}/status"
        payload = {
            "status": printer_status.state.value,
            "paperStatus": printer_status.paper_status.value if printer_status.paper_status else "UNKNOWN",
            "paperLevel": printer_status.paper_level,
            "tonerStatus": printer_status.toner_status.value if printer_status.toner_status else "UNKNOWN",
            "tonerLevel": printer_status.toner_level,
        }

        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.config.api_timeout,
            )
            response.raise_for_status()
            logger.debug(f"Printer status reported: {printer_status.state.value}")
            return response.json()
        except requests.exceptions.RequestException as e:
            raise APIError(f"Failed to update printer status: {e}", getattr(e.response, "status_code", None))

    def download_file(self, file_url: str, destination: str) -> str:
        """Download a PDF file from the backend.

        Args:
            file_url: URL to download from.
            destination: Local path to save the file.

        Returns:
            Path to the downloaded file.

        Raises:
            APIError: If download fails.
        """
        try:
            url = file_url if file_url.startswith("http") else f"{self.base_url}{file_url}"
            response = self.session.get(
                url,
                headers=self._get_headers(),
                timeout=self.config.download_timeout,
                stream=True,
            )
            response.raise_for_status()

            dest_path = Path(destination)
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"File downloaded to {destination}")
            return str(dest_path)
        except requests.exceptions.RequestException as e:
            raise APIError(f"File download failed: {e}", getattr(e.response, "status_code", None))


class AgentApiClient:
    """Lightweight API client for agent auto-registration and job operations."""

    def __init__(self, backend_url: str, agent_id: str, agent_secret: str, station_id: str = None):
        self.base_url = backend_url.rstrip("/")
        self.agent_id = agent_id
        self.agent_secret = agent_secret
        self.station_id = station_id
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {agent_secret}",
            "X-Agent-ID": agent_id,
        })

    def auto_register(self, hostname: str, platform: str, printers: List[Dict]) -> Dict:
        """Register all detected printers as stations with the backend.

        Args:
            hostname: PC hostname.
            platform: OS platform string.
            printers: List of detected printer dicts.

        Returns:
            Registration response.
        """
        path = "/api/agent/auto-register"
        payload = {
            "agentId": self.agent_id,
            "hostname": hostname,
            "platform": platform,
            "printers": printers,
        }
        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Auto-registration failed: {e}")
            return {"success": False, "error": str(e)}

    def get_authorized_jobs(self) -> List[Dict]:
        """Poll for authorized jobs scoped to this agent's station.

        Returns:
            List of job dicts for this agent's station only.
        """
        path = "/api/agent/jobs/poll"
        params = {}
        if self.station_id:
            params["stationId"] = self.station_id
        try:
            url = f"{self.base_url}{path}"
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to poll jobs: {e}")
            return []

    def claim_job(self, job_id: str, authorization_token: str) -> Dict:
        """Claim a job for printing.

        Args:
            job_id: The job ID.
            authorization_token: Authorization token from the job.

        Returns:
            Claim response.
        """
        path = f"/api/agent/jobs/{job_id}/claim"
        payload = {"authorizationToken": authorization_token}
        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to claim job {job_id}: {e}")
            return {"success": False, "error": str(e)}

    def complete_job(self, job_id: str, status: str, pages_printed: int = 0, error_message: str = None) -> Dict:
        """Mark a job as completed.

        Args:
            job_id: The job ID.
            status: Final status (COMPLETED or PRINT_FAILED).
            pages_printed: Number of pages printed.
            error_message: Error message if failed.

        Returns:
            Completion response.
        """
        path = f"/api/agent/jobs/{job_id}/complete"
        payload = {
            "status": status,
            "pagesPrinted": pages_printed,
        }
        if error_message:
            payload["errorMessage"] = error_message
        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to complete job {job_id}: {e}")
            return {"success": False, "error": str(e)}

    def download_file(self, file_url: str, destination: str) -> str:
        """Download a PDF file from the backend.

        Args:
            file_url: URL to download from.
            destination: Local path to save.

        Returns:
            Path to downloaded file.
        """
        try:
            url = file_url if file_url.startswith("http") else f"{self.base_url}{file_url}"
            response = self.session.get(url, timeout=120, stream=True)
            response.raise_for_status()

            dest_path = Path(destination)
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"File downloaded to {destination}")
            return str(dest_path)
        except requests.exceptions.RequestException as e:
            logger.error(f"File download failed: {e}")
            raise

    def send_heartbeat(self, printers: List[Dict]) -> Dict:
        """Send heartbeat with printer statuses.

        Args:
            printers: List of printer status dicts. Each must include:
                - printerId: UUID of the printer in the backend
                - status: IDLE | PRINTING | PAUSED | ERROR | OFFLINE
                - paperStatus: OK | LOW | EMPTY | UNKNOWN (optional)
                - paperLevel: 0-100 (optional)
                - tonerStatus: OK | LOW | EMPTY | UNKNOWN (optional)
                - tonerLevel: 0-100 (optional)

        Returns:
            Heartbeat response.
        """
        path = "/api/agent/heartbeat"
        payload = {
            "agentId": self.agent_id,
            "stationId": self.station_id,
            "printers": printers,
        }
        try:
            url = f"{self.base_url}{path}"
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Heartbeat failed: {e}")
            return {"success": False, "error": str(e)}
