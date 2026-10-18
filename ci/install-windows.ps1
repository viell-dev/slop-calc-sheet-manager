$ErrorActionPreference = 'Stop'
$pin = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'libreoffice.json') -Raw |
    ConvertFrom-Json).windows
$installerPath = Join-Path $env:RUNNER_TEMP 'sheet-manager-libreoffice.msi'
$logPath = Join-Path $env:RUNNER_TEMP 'sheet-manager-msi.log'
Invoke-WebRequest -Uri $pin.url -OutFile $installerPath
if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash -ne $pin.sha256) {
    throw 'LibreOffice installer checksum mismatch'
}
$arguments = @('/i', "`"$installerPath`"", '/qn', '/norestart', '/L*v', "`"$logPath`"",
    'REGISTER_ALL_MSO_TYPES=0', 'ISCHECKFORPRODUCTUPDATES=0')
$process = Start-Process msiexec.exe -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -notin @(0, 3010)) {
    throw "LibreOffice MSI failed with exit code $($process.ExitCode); see $logPath"
}
$program = Join-Path $env:ProgramFiles 'LibreOffice\program'
$version = & (Join-Path $program 'soffice.com') --version
if ($version -notlike "*$($pin.version)*") { throw "Unexpected office version: $version" }
Write-Output $version
