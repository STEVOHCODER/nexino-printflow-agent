param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$PfxPath
)

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($PfxPath, 'NexinoPrint2026', [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)
$result = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $cert -TimestampServer 'http://timestamp.digicert.com'

if ($result.Status -ne 'Valid') {
    Write-Host "Signing FAILED: $($result.Status)" -ForegroundColor Red
    exit 1
}

Write-Host "Signed successfully: $ExePath" -ForegroundColor Green
