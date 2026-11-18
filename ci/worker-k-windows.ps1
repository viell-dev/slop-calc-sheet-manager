# Focused research for #220 and #219. Run only on the disposable hosted desktop.
Add-Type @"
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ContrastProbe {
    [StructLayout(LayoutKind.Sequential)]
    public struct State { public uint size; public uint flags; public IntPtr scheme; }
    [DllImport("user32", EntryPoint="SystemParametersInfoW", SetLastError=true)]
    private static extern bool Spi(uint action, uint size, ref State state, uint flags);
    [DllImport("user32")] public static extern uint GetSysColor(int color);
    public static State Read() {
        var state = new State { size = (uint)Marshal.SizeOf<State>() };
        if (!Spi(0x42, state.size, ref state, 0)) throw new Win32Exception();
        return state;
    }
    public static void Set(uint flags, string scheme) {
        var state = new State { size = (uint)Marshal.SizeOf<State>(), flags = flags };
        state.scheme = scheme == null ? IntPtr.Zero : Marshal.StringToHGlobalUni(scheme);
        try {
            if (!Spi(0x43, state.size, ref state, 3)) throw new Win32Exception();
        } finally { Marshal.FreeHGlobal(state.scheme); }
    }
}
"@
$python = 'C:\Program Files\LibreOffice\program\python.exe'
$root = (Get-Location).Path
$output = Join-Path $root 'test-results/windows-desktop'
New-Item -ItemType Directory -Force -Path $output | Out-Null

function Measure-Contrast {
    $state = [ContrastProbe]::Read()
    @{
        flags = $state.flags
        scheme = [Runtime.InteropServices.Marshal]::PtrToStringUni($state.scheme)
        window = [ContrastProbe]::GetSysColor(5)
        windowText = [ContrastProbe]::GetSysColor(8)
    }
}

function Invoke-Probe($mode) {
    & $python ci/worker-k-windows.py $mode | Tee-Object -FilePath (Join-Path $output "$mode-input.log")
    if ($LASTEXITCODE -ne 0) { throw "$mode real-input probe exited $LASTEXITCODE" }
}

$failures = @()
$baseline = Measure-Contrast
$baseline | ConvertTo-Json | Set-Content (Join-Path $output 'contrast-baseline.json')
try { Invoke-Probe 'default' } catch { $failures += "$_" }
try {
    [ContrastProbe]::Set(($baseline.flags -bor 1), 'High Contrast Black')
    Start-Sleep -Seconds 3
    $active = Measure-Contrast
    $active | ConvertTo-Json | Set-Content (Join-Path $output 'contrast-active.json')
    if (($active.flags -band 1) -eq 0 -or $active.window -eq $baseline.window) {
        throw 'Windows did not report both the high-contrast flag and a changed window colour'
    }
    Invoke-Probe 'contrast'
} catch {
    $failures += "$_"
} finally {
    [ContrastProbe]::Set($baseline.flags, $baseline.scheme)
    Start-Sleep -Seconds 2
    Measure-Contrast | ConvertTo-Json | Set-Content (Join-Path $output 'contrast-restored.json')
}

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
