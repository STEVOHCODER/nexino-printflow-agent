$pfxPath = 'D:\MOVIE\Video\Video\Xl\library\nexino_printflow\print-agent\nexino-signing.pfx'
$password = 'NexinoPrint2026'
$exePath = 'D:\MOVIE\Video\Video\Xl\library\nexino_printflow\print-agent\electron\dist-installer\NexinoPrintAgent-1.1.10-Setup.exe'

# Load the certificate
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($pfxPath, $password, [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)

# Add to CurrentUser trusted root store
$store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser')
$store.Open('ReadWrite')
$store.Add($cert)
$store.Close()
Write-Host "Certificate added to CurrentUser Trusted Root store"

# Also add to trusted publishers store
$store2 = New-Object System.Security.Cryptography.X509Certificates.X509Store('TrustedPublisher', 'CurrentUser')
$store2.Open('ReadWrite')
$store2.Add($cert)
$store2.Close()
Write-Host "Certificate added to CurrentUser Trusted Publisher store"

# Now sign the exe
$result = Set-AuthenticodeSignature -FilePath $exePath -Certificate $cert -TimestampServer 'http://timestamp.digicert.com'
Write-Host "Signature status: $($result.Status)"
Write-Host "Status message: $($result.StatusMessage)"
