param(
    [string]$ExePath,
    [string]$PfxPath = 'D:\MOVIE\Video\Video\Xl\library\nexino_printflow\print-agent\nexino-signing.pfx'
)

$password = 'NexinoPrint2026'

# Load the certificate
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($PfxPath, $password, [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)

# Add to CurrentUser stores
$rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser')
$rootStore.Open('ReadWrite')
$rootStore.Add($cert)
$rootStore.Close()

$pubStore = New-Object System.Security.Cryptography.X509Certificates.X509Store('TrustedPublisher', 'CurrentUser')
$pubStore.Open('ReadWrite')
$pubStore.Add($cert)
$pubStore.Close()

# Sign the exe
$result = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $cert -TimestampServer 'http://timestamp.digicert.com'
Write-Host "Signature status: $($result.Status)"
Write-Host "Status message: $($result.StatusMessage)"

if ($result.Status -ne 'Valid') {
    exit 1
}
