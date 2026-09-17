# Create self-signed code signing certificate
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=Nexino PrintFlow' -CertStoreLocation 'Cert:\CurrentUser\My' -NotAfter (Get-Date).AddYears(5) -HashAlgorithm SHA256
Write-Host "Certificate created:"
Write-Host "  Thumbprint: $($cert.Thumbprint)"
Write-Host "  Subject: $($cert.Subject)"
Write-Host "  Expires: $($cert.NotAfter)"

# Export to .pfx file
$password = ConvertTo-SecureString -String 'NexinoPrint2026' -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath 'D:\MOVIE\Video\Video\Xl\library\nexino_printflow\print-agent\nexino-signing.pfx' -Password $password
Write-Host "Certificate exported to nexino-signing.pfx"
