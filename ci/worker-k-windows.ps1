# Focused research for #220 and #219. Run only on the disposable hosted desktop.
$python = 'C:\Program Files\LibreOffice\program\python.exe'
$root = (Get-Location).Path
$output = Join-Path $root 'test-results/windows-desktop'
New-Item -ItemType Directory -Force -Path $output | Out-Null

function Invoke-Probe($mode) {
    & $python ci/worker-k-windows.py $mode | Tee-Object -FilePath (Join-Path $output "$mode-input.log")
    if ($LASTEXITCODE -ne 0) { throw "$mode real-input probe exited $LASTEXITCODE" }
}

$failures = @()
$portable = Join-Path $env:RUNNER_TEMP 'nvda-2026.3.1-portable'
$nvda = Join-Path $portable 'nvda.exe'
try {
    $installer = Join-Path $env:RUNNER_TEMP 'nvda_2026.3.1.exe'
    Invoke-WebRequest -Uri 'https://download.nvaccess.org/releases/2026.3.1/nvda_2026.3.1.exe' -OutFile $installer -TimeoutSec 120
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
    if ($hash -ne '6f80a5b0ca720a7d0d314b5be212f37388bbe81a1107ac3298c1821a1cd3f052') {
        throw 'NVDA installer SHA-256 differs from the NV Access release receipt'
    }
    $setup = Start-Process -FilePath $installer -ArgumentList "--create-portable-silent --portable-path=`"$portable`"" -PassThru -WindowStyle Hidden
    if (!$setup.WaitForExit(120000)) { Stop-Process -Id $setup.Id; throw 'NVDA portable preparation timed out' }
    if ($setup.ExitCode -ne 0 -or !(Test-Path -LiteralPath $nvda)) { throw "NVDA portable preparation failed ($($setup.ExitCode))" }
    $log = Join-Path $env:RUNNER_TEMP 'worker-k-nvda.log'
    $config = Join-Path $env:RUNNER_TEMP 'worker-k-nvda-config'
    New-Item -ItemType Directory -Force -Path $config | Out-Null
    $reader = Start-Process -FilePath $nvda -ArgumentList "--minimal --disable-addons --lang=en --log-level=12 --log-file=`"$log`" --config-path=`"$config`"" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    $running = Start-Process -FilePath $nvda -ArgumentList '--check-running' -PassThru -Wait -WindowStyle Hidden
    if ($running.ExitCode -ne 0 -or !(Test-Path -LiteralPath $log)) { throw 'NVDA did not start in the interactive runner' }
    Invoke-Probe 'nvda'
} catch {
    $failures += "$_"
} finally {
    if (Test-Path -LiteralPath $nvda) {
        Start-Process -FilePath $nvda -ArgumentList '--quit' -Wait -WindowStyle Hidden
    }
    if ($log -and (Test-Path -LiteralPath $log)) {
        # Keep speech output from the bounded synthetic test, without verbose system diagnostics.
        Select-String -LiteralPath $log -Pattern 'Speaking \[|NVDA version' |
            ForEach-Object Line | Set-Content (Join-Path $output 'nvda-speech.log')
    }
}
if ($failures) {
    $failures | Set-Content (Join-Path $output 'probe-errors.txt')
    throw ($failures -join [Environment]::NewLine)
}
