"""IPP (Internet Printing Protocol) adapter for direct printer communication.

This adapter communicates with printers using the IPP protocol directly
via HTTP requests, without requiring CUPS or other printing systems.
Supports manual printer URI configuration and subnet discovery.
"""

import struct
import logging
import uuid
import time
import socket
from typing import Dict, List, Optional
from pathlib import Path

import requests

from ..printer_adapter import PrinterAdapter
from ..models import (
    PrinterStatus,
    PrinterState,
    PaperStatus,
    TonerStatus,
)

logger = logging.getLogger(__name__)

IPP_PORT = 631
IPP_VERSION = (1, 1)

IPP_OP_PRINT_JOB = 0x0002
IPP_OP_VALIDATE_JOB = 0x0004
IPP_OP_GET_PRINTER_ATTRIBUTES = 0x000B
IPP_OP_GET_JOB_ATTRIBUTES = 0x0009
IPP_OP_CANCEL_JOB = 0x0008

IPP_TAG_OPERATION = 0x01
IPP_TAG_JOB = 0x02
IPP_TAG_PRINTER = 0x04
IPP_TAG_END = 0x03

IPP_TAG_integer = 0x21
IPP_TAG_boolean = 0x22
IPP_TAG_enum = 0x23
IPP_TAG_string = 0x41
IPP_TAG_name = 0x42
IPP_TAG_keyword = 0x44
IPP_TAG_uri = 0x45
IPP_TAG_resolution = 0x32
IPP_TAG_range = 0x33
IPP_TAG_octetstring = 0x40
IPP_TAG_text = 0x71

KNOWN_IPP_PORTS = [631, 9100]


class IPPAdapter(PrinterAdapter):
    """IPP protocol adapter for direct printer communication."""

    def __init__(self, known_uris: Optional[List[str]] = None) -> None:
        self._jobs: Dict[str, Dict] = {}
        self._printers: Dict[str, str] = {}  # printer name -> IPP URI
        self._known_uris = known_uris or []
        logger.info("IPP adapter initialized.")

    # ------------------------------------------------------------------
    # Protocol encoding
    # ------------------------------------------------------------------
    def _encode_ipp_attribute(self, name: str, value, tag: int = IPP_TAG_keyword) -> bytes:
        name_bytes = name.encode("utf-8")
        result = struct.pack("!BH", tag, len(name_bytes)) + name_bytes

        if isinstance(value, bool):
            result += struct.pack("!BI", IPP_TAG_boolean, 1)
            result += struct.pack("!B", 1 if value else 0)
        elif isinstance(value, int):
            result += struct.pack("!BI", IPP_TAG_integer, 4)
            result += struct.pack("!I", value)
        elif isinstance(value, str):
            value_bytes = value.encode("utf-8")
            result += struct.pack("!BH", tag, len(value_bytes))
            result += value_bytes
        elif isinstance(value, bytes):
            result += struct.pack("!BH", tag, len(value))
            result += value

        return result

    def _encode_ipp_request(self, operation_id: int, attributes: Dict[str, any]) -> bytes:
        header = struct.pack("!BBHI", IPP_VERSION[0], IPP_VERSION[1], operation_id, 1)

        op_attrs = struct.pack("!B", IPP_TAG_OPERATION)
        for name, value in attributes.items():
            op_attrs += self._encode_ipp_attribute(name, value)
        op_attrs += struct.pack("!B", IPP_TAG_END)

        return header + op_attrs

    def _decode_ipp_response(self, data: bytes) -> Dict:
        if len(data) < 8:
            return {"error": "Response too short"}

        version_major, version_minor, status_code, request_id = struct.unpack(
            "!BBHI", data[:8]
        )

        result = {
            "version": (version_major, version_minor),
            "status_code": status_code,
            "request_id": request_id,
            "attributes": {},
        }

        pos = 8
        current_tag = None

        while pos < len(data):
            tag = data[pos]
            pos += 1

            if tag == IPP_TAG_END:
                break

            if tag in (IPP_TAG_OPERATION, IPP_TAG_JOB, IPP_TAG_PRINTER):
                current_tag = tag
                continue

            if pos + 2 > len(data):
                break
            name_len = struct.unpack("!H", data[pos:pos + 2])[0]
            pos += 2
            if pos + name_len > len(data):
                break
            name = data[pos:pos + name_len].decode("utf-8", errors="replace")
            pos += name_len

            if pos + 3 > len(data):
                break
            value_tag = data[pos]
            value_len = struct.unpack("!H", data[pos + 1:pos + 3])[0]
            pos += 3
            if pos + value_len > len(data):
                break
            value_data = data[pos:pos + value_len]
            pos += value_len

            if value_tag == IPP_TAG_integer or value_tag == IPP_TAG_enum:
                if value_len == 4:
                    value = struct.unpack("!I", value_data)[0]
                else:
                    value = value_data
            elif value_tag == IPP_TAG_boolean:
                value = value_data[0] == 1 if value_len >= 1 else False
            elif value_tag in (IPP_TAG_string, IPP_TAG_name, IPP_TAG_keyword, IPP_TAG_uri, IPP_TAG_text):
                value = value_data.decode("utf-8", errors="replace")
            else:
                value = value_data

            if name not in result["attributes"]:
                result["attributes"][name] = value
            else:
                existing = result["attributes"][name]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    result["attributes"][name] = [existing, value]

        return result

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_uri(printer_uri: str) -> str:
        """Ensure a URI is a full http(s) IPP endpoint."""
        uri = printer_uri.strip()
        if not uri.startswith("http"):
            uri = f"http://{uri}"
        if "/ipp" not in uri:
            uri = f"{uri.rstrip('/')}/ipp/print"
        return uri

    def _op_attributes(self, printer_uri: str, user: str = "nexino-agent") -> Dict:
        """Required operation attributes, charset/natural-language first.

        IPP requires attributes-charset and attributes-natural-language as the
        first operation attributes; insertion order guarantees that.
        """
        return {
            "attributes-charset": "utf-8",
            "attributes-natural-language": "en",
            "printer-uri": self._normalize_uri(printer_uri),
            "requesting-user-name": user,
        }

    def _send_ipp_request(
        self, printer_uri: str, operation_id: int, attributes: Dict,
        document_data: Optional[bytes] = None
    ) -> Optional[Dict]:
        endpoint = self._normalize_uri(printer_uri)
        request_data = self._encode_ipp_request(operation_id, attributes)

        if document_data:
            request_data += document_data

        headers = {
            "Content-Type": "application/ipp",
        }

        try:
            response = requests.post(
                endpoint,
                data=request_data,
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                return self._decode_ipp_response(response.content)
            else:
                logger.warning(f"IPP request failed with status {response.status_code}")
                return None
        except requests.RequestException as e:
            logger.error(f"IPP communication error: {e}")
            return None

    def _resolve_uri(self, printer_name: str) -> str:
        """Resolve a printer name (or URI) to an IPP endpoint URI.

        The backend stores the printer's URI when the agent auto-registers,
        but callers may pass either the friendly name or the raw URI.
        """
        if printer_name in self._printers:
            return self._printers[printer_name]
        # Otherwise assume the caller already passed a URI / host[:port].
        return printer_name

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def _probe_ipp_printer(self, uri: str) -> Optional[Dict]:
        attributes = self._op_attributes(uri, "nexino-discovery")
        response = self._send_ipp_request(uri, IPP_OP_GET_PRINTER_ATTRIBUTES, attributes)
        if response and response.get("status_code", 1) == 0:
            return response.get("attributes", {})
        return None

    def _discover_network_printers(self) -> List[Dict]:
        """Probe common IPP ports across the local subnet."""
        discovered = []
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            subnet = ".".join(local_ip.split(".")[:-1])
        except Exception:
            subnet = "192.168.1"

        for last_octet in range(1, 255):
            ip = f"{subnet}.{last_octet}"
            for port in KNOWN_IPP_PORTS:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.1)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        uri = f"http://{ip}:{port}/ipp/print"
                        attrs = self._probe_ipp_printer(uri)
                        if attrs:
                            name = attrs.get("printer-name", f"Printer@{ip}")
                            endpoint = self._normalize_uri(uri)
                            self._printers[name] = endpoint
                            discovered.append({
                                "name": name,
                                "port": endpoint,
                                "uri": endpoint,
                                "type": "ipp",
                                "driver": attrs.get("printer-make-and-model", "IPP Generic"),
                            })
                except Exception:
                    pass

        return discovered

    def discover(self) -> List[Dict]:
        discovered = []

        for uri in self._known_uris:
            attrs = self._probe_ipp_printer(uri)
            if attrs:
                name = attrs.get("printer-name", "IPP Printer")
                endpoint = self._normalize_uri(uri)
                self._printers[name] = endpoint
                discovered.append({
                    "name": name,
                    "port": endpoint,
                    "uri": endpoint,
                    "type": "ipp",
                    "driver": attrs.get("printer-make-and-model", "IPP Generic"),
                })

        if not discovered:
            logger.info("Scanning network for IPP printers (this may take a moment)...")
            discovered.extend(self._discover_network_printers())

        if discovered:
            logger.info(f"Discovered {len(discovered)} IPP printer(s).")
        else:
            logger.info("No IPP printers found on network.")

        return discovered

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def get_status(self, printer_name: str) -> PrinterStatus:
        uri = self._resolve_uri(printer_name)

        response = self._send_ipp_request(
            uri, IPP_OP_GET_PRINTER_ATTRIBUTES, self._op_attributes(uri)
        )

        if not response:
            return PrinterStatus(
                name=printer_name,
                state=PrinterState.UNKNOWN,
                error_message="IPP communication failed",
            )

        status_code = response.get("status_code", 0)
        attrs = response.get("attributes", {})

        state = PrinterState.UNKNOWN
        if status_code == 0:
            state = PrinterState.IDLE
        elif status_code in (0x400, 0x401, 0x402):
            state = PrinterState.ERROR
        elif status_code >= 0x500:
            state = PrinterState.OFFLINE

        ipp_state = attrs.get("printer-state", 5)
        state_map = {3: PrinterState.IDLE, 4: PrinterState.IDLE, 5: PrinterState.OFFLINE}
        state = state_map.get(ipp_state, state)

        error_message = None
        state_msg = attrs.get("printer-state-message", "")
        if state_msg and "error" in str(state_msg).lower():
            error_message = str(state_msg)
            state = PrinterState.ERROR

        return PrinterStatus(
            name=printer_name,
            state=state,
            paper_status=PaperStatus.UNKNOWN,
            paper_level=None,
            toner_status=TonerStatus.UNKNOWN,
            toner_level=None,
            error_message=error_message,
        )

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------
    def submit_job(
        self, printer_name: str, file_path: str, options: Optional[Dict] = None,
    ) -> str:
        job_id = f"IPP-{uuid.uuid4().hex[:12].upper()}"
        options = options or {}

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise RuntimeError(f"File not found: {file_path}")

        uri = self._resolve_uri(printer_name)

        file_content = file_path_obj.read_bytes()

        # Detect document format from extension
        ext = file_path_obj.suffix.lower()
        format_map = {
            ".pdf": "application/pdf",
            ".ps": "application/postscript",
            ".txt": "text/plain",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        doc_format = format_map.get(ext, "application/octet-stream")

        attributes = self._op_attributes(uri)
        attributes["document-format"] = doc_format
        attributes["job-name"] = file_path_obj.name

        copies = int(options.get("copies", 1) or 1)
        if copies > 1:
            # IPP 'copies' is an integer attribute — must not be sent as a string.
            attributes["copies"] = copies

        color_mode = options.get("color_mode", "")
        if isinstance(color_mode, str) and color_mode.upper() in ("BW", "MONOCHROME"):
            attributes["print-color-mode"] = "monochrome"
        elif isinstance(color_mode, str) and color_mode.upper() in ("COLOR", "MIXED"):
            attributes["print-color-mode"] = "color"

        duplex = options.get("duplex", "")
        if duplex in ("double", "duplex", "true", True, "DOUBLE"):
            attributes["sides"] = "two-sided-long-edge"
        elif duplex in ("single", "simplex", "false", False, "SINGLE"):
            attributes["sides"] = "one-sided"

        paper_size = options.get("paper_size", "A4")
        if paper_size:
            media_map = {
                "A3": "iso_a3_297x420mm",
                "A4": "iso_a4_210x297mm",
                "A5": "iso_a5_148x210mm",
                "LETTER": "na_letter_8.5x11in",
            }
            attributes["media"] = media_map.get(str(paper_size).upper(), str(paper_size).lower())

        page_range = options.get("page_range", "")
        if page_range and str(page_range).strip().lower() not in ("", "all"):
            attributes["page-ranges"] = str(page_range)

        # Send Print-Job request WITH file content appended to the IPP message
        response = self._send_ipp_request(
            uri, IPP_OP_PRINT_JOB, attributes,
            document_data=file_content
        )

        if not response:
            raise RuntimeError(f"IPP Print-Job failed for {uri}")

        status_code = response.get("status_code", 0)
        if status_code != 0:
            raise RuntimeError(
                f"IPP Print-Job returned error code: 0x{status_code:04x}"
            )

        attrs = response.get("attributes", {})
        ipp_job_id = attrs.get("job-id", job_id)

        self._jobs[job_id] = {
            "id": job_id,
            "ipp_job_id": ipp_job_id,
            "status": "submitted",
            "printer": printer_name,
            "uri": uri,
            "file": str(file_path),
            "submitted_at": time.time(),
        }

        logger.info(f"IPP job {job_id} submitted (IPP job-id: {ipp_job_id}).")
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False

        job = self._jobs[job_id]
        uri = job.get("uri") or self._resolve_uri(job.get("printer", ""))
        ipp_job_id = job.get("ipp_job_id")

        if ipp_job_id is None:
            return False

        attributes = self._op_attributes(uri)
        attributes["job-id"] = int(ipp_job_id)

        response = self._send_ipp_request(
            uri, IPP_OP_CANCEL_JOB, attributes
        )

        if response and response.get("status_code", 1) == 0:
            job["status"] = "cancelled"
            logger.info(f"IPP job {job_id} cancelled.")
            return True

        return False

    def get_job_status(self, job_id: str) -> Dict:
        if job_id not in self._jobs:
            return {"id": job_id, "status": "unknown", "message": "Job not found"}

        job = self._jobs[job_id]
        uri = job.get("uri") or self._resolve_uri(job.get("printer", ""))
        ipp_job_id = job.get("ipp_job_id")

        if ipp_job_id is None:
            return job

        attributes = self._op_attributes(uri)
        attributes["job-id"] = int(ipp_job_id)

        response = self._send_ipp_request(
            uri, IPP_OP_GET_JOB_ATTRIBUTES, attributes
        )

        if response:
            attrs = response.get("attributes", {})
            ipp_job_state = attrs.get("job-state", 9)
            state_map = {
                3: "pending", 4: "pending_held", 5: "processing",
                6: "processing_stopped", 7: "cancelled", 8: "aborted", 9: "completed",
            }
            return {**job, "status": state_map.get(ipp_job_state, "unknown")}

        return job

    def get_capabilities(self, printer_name: str) -> Dict:
        uri = self._resolve_uri(printer_name)

        response = self._send_ipp_request(
            uri, IPP_OP_GET_PRINTER_ATTRIBUTES, self._op_attributes(uri)
        )

        capabilities = {
            "supported_paper_sizes": ["A4", "Letter"],
            "supports_color": True,
            "supports_duplex": False,
            "max_copies": 1,
            "supports_page_range": True,
        }

        if response:
            attrs = response.get("attributes", {})

            color_modes = attrs.get("print-color-mode-supported", [])
            if isinstance(color_modes, str):
                color_modes = [color_modes]
            capabilities["supports_color"] = "color" in color_modes

            sides = attrs.get("sides-supported", [])
            if isinstance(sides, str):
                sides = [sides]
            capabilities["supports_duplex"] = any("two-sided" in s for s in sides)

            max_copies = attrs.get("copies-supported", 1)
            if isinstance(max_copies, int):
                capabilities["max_copies"] = max_copies

        return capabilities