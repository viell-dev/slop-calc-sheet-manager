$ErrorActionPreference = 'Stop'
$sessions = [int]$env:SESSIONS
$iterations = [int]$env:ITERATIONS
if ($sessions -lt 1 -or $sessions -gt 30 -or $iterations -lt 1 -or $iterations -gt 100) {
    throw 'Out-of-range experiment inputs'
}
$program = 'C:\Program Files\LibreOffice\program'
$python = Join-Path $program 'python.exe'
& $python tools/build.py
if ($LASTEXITCODE) { throw 'List package build failed' }
Push-Location control-main
try {
    & $python tools/build.py
    if ($LASTEXITCODE) { throw 'Control package build failed' }
} finally { Pop-Location }
$package = (Get-ChildItem -LiteralPath dist -Filter '*.oxt').FullName
if ($env:MODE -eq 'main') { $package = (Get-ChildItem -LiteralPath control-main/dist -Filter '*.oxt').FullName }
$summary = @()
for ($index = 1; $index -le $sessions; $index++) {
    $out = Join-Path $PWD "test-results/session-$index"
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    $arguments = @('-u', 'ci/windows_probe.py', '--program', $program, '--oxt', $package,
        '--mode', $env:MODE, '--experiment', $env:EXPERIMENT, '--iterations', "$iterations", '--output', $out)
    if ($env:PAINTED -eq 'true') { $arguments += '--painted' }
    $info = [Diagnostics.ProcessStartInfo]::new($python)
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $arguments) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $finished = $process.WaitForExit(900000)
    if (-not $finished) {
        $cdb = Get-Content test-results/debuggers.txt -ErrorAction SilentlyContinue | Where-Object { $_ -like '*\x64\cdb.exe' } | Select-Object -First 1
        # Disposable runner: this sequential experiment owns every office process.
        $offices = Get-CimInstance Win32_Process -Filter "Name='soffice.bin'"
        foreach ($office in $offices) {
            if ($cdb) {
                $dump = Join-Path $PWD "test-results/dumps/hang-$index-$($office.ProcessId).dmp"
                & $cdb -p $office.ProcessId -c ".dump /ma $dump; qd" 2>&1 | Out-File "$out/dump-capture.txt"
            }
            Stop-Process -Id $office.ProcessId -Force -ErrorAction SilentlyContinue
        }
        $process.Kill($true)
        $process.WaitForExit()
    }
    $stdout.GetAwaiter().GetResult() | Set-Content -LiteralPath "$out/stdout.log"
    $stderr.GetAwaiter().GetResult() | Set-Content -LiteralPath "$out/stderr.log"
    $result = $null
    if (Test-Path -LiteralPath "$out/results.json") {
        $result = Get-Content -LiteralPath "$out/results.json" -Raw | ConvertFrom-Json
    }
    $passed = $finished -and $process.ExitCode -eq 0 -and $result.assertions_passed -eq $true
    $summary += [pscustomobject]@{session=$index; passed=$passed; timeout=(-not $finished); exit=$process.ExitCode; result=$result}
    $summary | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath test-results/summary.json
    Write-Output "Session $index/$sessions mode=$env:MODE passed=$passed exit=$($process.ExitCode)"
    Get-Content -LiteralPath "$out/stdout.log" -Tail 4
    if (Test-Path -LiteralPath "$out/stderr.log") { Get-Content -LiteralPath "$out/stderr.log" -Tail 12 }
}
$summary | Format-Table session,passed,timeout,exit | Out-String | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY
if (@($summary | Where-Object { -not $_.passed }).Count) { throw 'One or more measured sessions failed' }
