<#
  Build the Microsoft Store package from an existing PyInstaller onedir build.

  Run AFTER the normal build has produced dist-onedir\Lavrentiy\:

      pyinstaller --noconfirm --distpath dist-onedir Lavrentiy-onedir.spec
      powershell -File store\build-msix.ps1 -Version 1.7.10

  Produces store\out\Lavrentiy-1.7.10.0.msix.

  The package is UNSIGNED. That is correct for a Store submission - the Store
  signs it on the way in, which is the entire reason for going through the
  Store. To install it locally for testing you must sign it yourself with a
  self-signed certificate and trust that certificate; see -SelfSign below.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [string]$DistDir = "dist-onedir\Lavrentiy",
  [string]$OutDir  = "store\out",
  # Self-sign so the package can be installed on this machine for testing.
  # Never used for the Store copy.
  [switch]$SelfSign
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# MSIX versions are four parts and the Store reserves the last one, so it must
# be 0. A three-part version is padded; anything else is rejected at upload
# with a message that does not name the version as the cause.
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must be x.y.z (got '$Version')" }
$pkgVersion = "$Version.0"

$dist = Join-Path $repo $DistDir
if (-not (Test-Path (Join-Path $dist "Lavrentiy.exe"))) {
  throw "No build found at $dist - run pyinstaller first"
}

# MakeAppx ships with the Windows SDK. Take the newest one present.
$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName | Select-Object -Last 1
if (-not $makeappx) { throw "makeappx.exe not found - install the Windows 10/11 SDK" }

# Stage: the manifest and assets sit alongside the app payload, not inside it.
$stage = Join-Path $repo "store\stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

Write-Host "Staging payload from $dist ..."
Copy-Item "$dist\*" $stage -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot "assets") (Join-Path $stage "assets") -Recurse -Force

$manifest = Get-Content (Join-Path $PSScriptRoot "AppxManifest.xml") -Raw
$manifest = $manifest -replace 'Version="[\d\.]+"', "Version=`"$pkgVersion`""
if ($manifest -match 'PARTNER_CENTER_') {
  Write-Warning "Manifest still holds PARTNER_CENTER_ placeholders. The package will build and can be self-signed for local testing, but the Store will reject it. Fill them from Partner Center -> Product identity."
}
Set-Content -Path (Join-Path $stage "AppxManifest.xml") -Value $manifest -Encoding utf8

New-Item -ItemType Directory -Path (Join-Path $repo $OutDir) -Force | Out-Null
$msix = Join-Path $repo "$OutDir\Lavrentiy-$pkgVersion.msix"
Remove-Item $msix -ErrorAction SilentlyContinue

Write-Host "Packing $msix ..."
& $makeappx.FullName pack /d $stage /p $msix /o
if ($LASTEXITCODE -ne 0) { throw "makeappx failed ($LASTEXITCODE)" }

$mb = [math]::Round((Get-Item $msix).Length / 1MB)
Write-Host "Built $msix ($mb MB)"

if ($SelfSign) {
  # Local testing only. The Identity/Publisher in the manifest and the
  # certificate subject must match exactly or signing succeeds and installing
  # fails with a mismatch error that does not say so.
  $subject = ([regex]'Publisher="([^"]+)"').Match($manifest).Groups[1].Value
  Write-Host "Self-signing as $subject (local testing only)"
  $cert = New-SelfSignedCertificate -Type Custom -Subject $subject `
    -KeyUsage DigitalSignature -FriendlyName "Lavrentiy test signing" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
  $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName | Select-Object -Last 1
  if (-not $signtool) { throw "signtool.exe not found" }
  & $signtool.FullName sign /fd SHA256 /sha1 $cert.Thumbprint $msix
  Write-Host "Signed. To install: trust the cert in Cert:\LocalMachine\TrustedPeople, then Add-AppxPackage $msix"
}
