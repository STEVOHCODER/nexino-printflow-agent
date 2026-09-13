"""Windows printer adapter using PowerShell and system commands.

Supports real printing via SumatraPDF (auto-detected) or Windows Shell.
Falls back to .NET print spooler if needed.
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

# Common SumatraPDF locations on Windows
SUMATRA_SEARCH_PATHS = [
    r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
    r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
    r"C:\Users\*\AppData\Local\SumatraPDF\SumatraPDF.exe",
    r"D:\Program Files\SumatraPDF\SumatraPDF.exe",
    r"D:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
]


class WindowsAdapter(PrinterAdapter):
    """Windows printer adapter with auto-detection of SumatraPDF."""

    def __init__(self, sumatra_pdf_path: Optional[str] = None) -> None:
        self.sumatra_pdf_path = sumatra_pdf_path or self._find_sumatra_pdf()
        self._jobs: Dict[str, Dict] = {}
        self._check_availability()

    def _find_sumatra_pdf(self) -> Optional[str]:
        """Auto-detect SumatraPDF installation."""
        import glob
        for pattern in SUMATRA_SEARCH_PATHS:
            matches = glob.glob(pattern)
            if matches:
                path = matches[0]
                logger.info(f"Found SumatraPDF at: {path}")
                return path

        # Try where command
        try:
            result = subprocess.run(
                "where SumatraPDF.exe",
                capture_output=True, text=True, timeout=5, shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip().split('\n')[0]
                logger.info(f"Found SumatraPDF via 'where': {path}")
                return path
        except Exception:
            pass

        logger.info("SumatraPDF not found. Will use Windows built-in printing.")
        return None

    def _check_availability(self) -> None:
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Write-Output 'ok'"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if result.returncode == 0:
                logger.info("Windows adapter initialized. PowerShell available.")
            else:
                logger.warning("PowerShell may not be fully functional.")
        except FileNotFoundError:
            logger.error("PowerShell not found.")
        except Exception as e:
            logger.warning(f"Error checking PowerShell: {e}")

    def _run_powershell(self, command: str, timeout: int = 10) -> Dict:
        try:
            full_command = f"powershell -NoProfile -Command \"{command}\""
            result = subprocess.run(
                full_command,
                capture_output=True, text=True, timeout=timeout, shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": "PowerShell command timed out"}
        except Exception as e:
            return {"success": False, "output": "", "error": str(e)}

    def discover(self) -> List[Dict]:
        command = (
            "Get-Printer | Select-Object Name, DriverName, PortName, "
            "PrinterStatus, Type | ConvertTo-Json"
        )
        result = self._run_powershell(command)

        if not result["success"]:
            logger.error(f"Failed to discover printers: {result['error']}")
            return []

        try:
            raw = result["output"]
            if not raw or raw.strip() == "":
                return []

            printers_data = json.loads(raw)
            if isinstance(printers_data, dict):
                printers_data = [printers_data]

            printers = []
            skip_names = {"Microsoft XPS Document Writer", "Microsoft Print to PDF",
                          "Fax", "OneNote", "AnyDesk Printer"}
            for p in printers_data:
                name = p.get("Name", "")
                if any(skip in name for skip in skip_names):
                    continue
                status_code = p.get("PrinterStatus", 8)
                status_map = {
                    0: "normal", 1: "paused", 2: "error", 3: "deleting",
                    4: "paper_jam", 5: "paper_out", 8: "offline",
                }
                printers.append({
                    "name": name,
                    "driver": p.get("DriverName", ""),
                    "port": p.get("PortName", ""),
                    "type": p.get("Type", 0),
                    "status": status_map.get(status_code, "unknown"),
                    "status_code": status_code,
                })

            logger.info(f"Discovered {len(printers)} printer(s).")
            return printers
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse printer list: {e}")
            return []

    def get_status(self, printer_name: str) -> PrinterStatus:
        command = (
            f'Get-Printer -Name "{printer_name}" | '
            "Select-Object Name, PrinterStatus | ConvertTo-Json"
        )
        result = self._run_powershell(command)

        if not result["success"]:
            return PrinterStatus(
                name=printer_name,
                state=PrinterState.UNKNOWN,
                error_message=result.get("error"),
            )

        try:
            data = json.loads(result["output"])
            status_code = data.get("PrinterStatus", 8)

            state_map = {
                0: PrinterState.IDLE, 1: PrinterState.IDLE,
                2: PrinterState.ERROR, 3: PrinterState.ERROR,
                4: PrinterState.ERROR, 5: PrinterState.ERROR,
                8: PrinterState.OFFLINE,
            }
            state = state_map.get(status_code, PrinterState.UNKNOWN)

            paper_status, paper_level = self._get_paper_level(printer_name)
            toner_status, toner_level = self._get_toner_level(printer_name)

            error_msg = None
            if status_code in (2, 4, 5):
                error_codes = {2: "Printer error", 4: "Paper jam", 5: "Paper out"}
                error_msg = error_codes.get(status_code, "Unknown error")

            return PrinterStatus(
                name=printer_name, state=state,
                paper_status=paper_status, paper_level=paper_level,
                toner_status=toner_status, toner_level=toner_level,
                error_message=error_msg,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse printer status: {e}")
            return PrinterStatus(name=printer_name, state=PrinterState.UNKNOWN)

    def _get_paper_level(self, printer_name: str) -> tuple:
        command = (
            f'Get-CimInstance -ClassName Win32_Printer -Filter "Name=\'{printer_name}\'" | '
            "Select-Object DetectedErrorState, PrinterStatus | ConvertTo-Json"
        )
        result = self._run_powershell(command)
        if not result["success"]:
            return PaperStatus.UNKNOWN, None

        try:
            data = json.loads(result["output"])
            error_state = data.get("DetectedErrorState", 0)
            if error_state == 4:
                return PaperStatus.EMPTY, 0.0
            elif error_state == 3:
                return PaperStatus.LOW, 0.2
            elif error_state == 2:
                return PaperStatus.OK, 0.8
            return PaperStatus.UNKNOWN, None
        except (json.JSONDecodeError, KeyError):
            return PaperStatus.UNKNOWN, None

    def _get_toner_level(self, printer_name: str) -> tuple:
        command = (
            f"Get-CimInstance -ClassName Win32_Printer -Filter \"Name='{printer_name}'\" | "
            "Select-Object DetectedErrorState | ConvertTo-Json"
        )
        result = self._run_powershell(command)
        if not result["success"]:
            return TonerStatus.UNKNOWN, None

        try:
            data = json.loads(result["output"])
            error_state = data.get("DetectedErrorState", 0)
            if error_state == 2:
                return TonerStatus.OK, None
            return TonerStatus.UNKNOWN, None
        except (json.JSONDecodeError, KeyError):
            return TonerStatus.UNKNOWN, None

    def submit_job(
        self, printer_name: str, file_path: str, options: Optional[Dict] = None,
    ) -> str:
        job_id = f"WIN-{uuid.uuid4().hex[:12].upper()}"
        options = options or {}
        file_path_str = str(file_path)

        if not Path(file_path_str).exists():
            raise RuntimeError(f"File not found: {file_path_str}")

        cmd = None

        # Try SumatraPDF first for PDF files
        if file_path_str.lower().endswith(".pdf") and self.sumatra_pdf_path:
            if Path(self.sumatra_pdf_path).exists():
                cmd = self._build_sumatra_command(printer_name, file_path_str, options)

        # Fallback: try .NET PrintDocument via PowerShell
        if not cmd:
            cmd = self._build_dotnet_print_command(printer_name, file_path_str, options)

        logger.info(f"Submitting print job to '{printer_name}': {Path(file_path_str).name}")

        result = self._run_powershell(cmd, timeout=60)

        if not result["success"]:
            # Last resort: use Shell Execute verb
            logger.warning(f"Primary print method failed, trying ShellExecute fallback")
            fallback_cmd = self._build_shellexecute_command(printer_name, file_path_str)
            result = self._run_powershell(fallback_cmd, timeout=30)

        if not result["success"]:
            raise RuntimeError(f"Failed to submit print job: {result['error']}")

        self._jobs[job_id] = {
            "id": job_id,
            "status": "submitted",
            "printer": printer_name,
            "file": file_path_str,
            "submitted_at": time.time(),
        }

        logger.info(f"Print job {job_id} submitted to '{printer_name}'.")
        return job_id

    def _build_sumatra_command(self, printer_name: str, file_path: str, options: Dict) -> str:
        settings_parts = [f"print-to {printer_name}"]

        copies = options.get("copies", 1)
        if copies > 1:
            settings_parts.append(f"print-copies {copies}")

        duplex = options.get("duplex", "")
        if duplex in ("double", "duplex", "true", True):
            settings_parts.append("print-duplex")
        elif duplex in ("single", "simplex", "false", False):
            settings_parts.append("print-no-duplex")

        color_mode = options.get("color_mode", "")
        if color_mode in ("bw", "monochrome", "MONOCHROME", "BW"):
            settings_parts.append("print-color-mode 1")
        elif color_mode in ("color", "COLOR"):
            settings_parts.append("print-color-mode 2")

        paper_size = options.get("paper_size", "A4")
        if paper_size:
            paper_map = {"A3": "A3", "A4": "A4", "A5": "A5", "LETTER": "Letter"}
            mapped = paper_map.get(paper_size.upper(), paper_size)
            settings_parts.append(f"print-paper {mapped}")

        settings = ", ".join(settings_parts)
        escaped_path = file_path.replace("'", "''")
        escaped_sumatra = self.sumatra_pdf_path.replace("'", "''")

        return (
            f"& '{escaped_sumatra}' -print-settings \"{settings}\" "
            f"-print-to \"{printer_name}\" \"{escaped_path}\""
        )

    def _build_dotnet_print_command(self, printer_name: str, file_path: str, options: Dict) -> str:
        """Use .NET System.Drawing.Printing for reliable Windows printing."""
        copies = options.get("copies", 1)
        duplex = options.get("duplex", "")
        color_mode = options.get("color_mode", "")

        ps_code = f'''
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Drawing.Printing

$printer = New-Object System.Drawing.Printing.PrinterSettings
$printer.PrinterName = "{printer_name}"
$printer.Copies = {copies}
'''

        if duplex in ("double", "duplex", "true", True):
            ps_code += '$printer.Duplex = [System.Drawing.Printing.Duplex]::Vertical\n'
        else:
            ps_code += '$printer.Duplex = [System.Drawing.Printing.Duplex]::Simplex\n'

        if color_mode in ("bw", "monochrome", "MONOCHROME", "BW"):
            ps_code += '$printer.Color = [System.Drawing.Printing.PrinterColor]::Monochrome\n'

        escaped_path = file_path.replace("'", "''")
        ps_code += f'''
$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.PrinterSettings = $printer
$doc.DocumentName = "Nexino PrintJob"
$script:path = "{escaped_path}"
$doc.add_PrintPage({{
    param($sender, $e)
    $img = [System.Drawing.Image]::FromFile($script:path)
    $e.Graphics.DrawImage($img, $e.MarginBounds)
    $img.Dispose()
}})
$doc.Print()
Write-Output "PRINTED"
'''
        escaped_ps = ps_code.replace('"', '`"').replace("'", "''")
        return f"powershell -NoProfile -Command \"{escaped_ps}\""

    def _build_shellexecute_command(self, printer_name: str, file_path: str) -> str:
        escaped_path = file_path.replace("'", "''")
        return (
            f'$p = Start-Process -FilePath "{escaped_path}" '
            f'-Verb Print -PassThru -Wait; '
            f'if ($p) {{ Write-Output "PRINTED" }}'
        )

    def cancel_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False

        job = self._jobs[job_id]
        printer_name = job.get("printer", "")

        command = (
            f"Get-PrintJob -PrinterName \"{printer_name}\" | "
            "Remove-PrintJob -Confirm:$false"
        )
        result = self._run_powershell(command)

        if result["success"]:
            job["status"] = "cancelled"
            logger.info(f"Windows job {job_id} cancelled.")
            return True

        return False

    def get_job_status(self, job_id: str) -> Dict:
        if job_id in self._jobs:
            return self._jobs[job_id]
        return {"id": job_id, "status": "unknown", "message": "Job not found"}

    def get_capabilities(self, printer_name: str) -> Dict:
        command = (
            f'Get-Printer -Name "{printer_name}" | '
            "Select-Object DriverName | ConvertTo-Json"
        )
        result = self._run_powershell(command)

        capabilities = {
            "supported_paper_sizes": ["A4", "Letter", "Legal", "A3"],
            "supports_color": True,
            "supports_duplex": True,
            "max_copies": 99,
            "supports_page_range": True,
            "driver_name": "Unknown",
        }

        if result["success"]:
            try:
                data = json.loads(result["output"])
                capabilities["driver_name"] = data.get("DriverName", "Unknown")
            except json.JSONDecodeError:
                pass

        return capabilities
