# SmoothCast Windows zero-Python bootstrap. Requires only stock Windows PowerShell 5.1.
# All install files are authenticated with a pinned python.org SHA-256.
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Bootstrap,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Forward
)
$ErrorActionPreference = 'Stop'

function Test-Python([string]$Executable) {
    if (-not $Executable) { return $false }
    try {
        & $Executable -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Python {
    $paths = @()
    if ($env:PYTHON) { $paths += $env:PYTHON }
    if ($env:LOCALAPPDATA) {
        foreach ($folder in @('Python315','Python314','Python313','Python312','Python311','Python310')) {
            $paths += (Join-Path $env:LOCALAPPDATA "Programs\Python\$folder\python.exe")
        }
    }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch '\\Microsoft\\WindowsApps\\') { $paths += $cmd.Source }
    $cmd = Get-Command python3.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch '\\Microsoft\\WindowsApps\\') { $paths += $cmd.Source }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        # 'py -0p' enumerates installed interpreters without installing any.
        try {
            $installed = @(& $launcher.Source '-0p' 2>$null)
            if ($LASTEXITCODE -eq 0) {
                foreach ($line in $installed) {
                    # Paths are read-only and checked for a working Python below.
                    if ($line -match '(?i)([A-Z]:\\[^\r\n]+python(?:\.exe)?)\s*$') {
                        $paths += $Matches[1]
                    }
                }
            }
        } catch { }
    }
    foreach ($path in $paths) {
        if (Test-Python $path) { return $path }
    }
    return $null
}

function Install-Python {
    Write-Host '[SmoothCast setup] No Python 3.10+ found; acquiring Python 3.14 for this user.'
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            & $winget.Source install --id Python.Python.3.14 --exact --source winget --scope user --silent --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0 -and (Find-Python)) { return }
            Write-Warning 'WinGet did not provide a working interpreter; trying verified python.org installer.'
        } catch { Write-Warning 'WinGet is unavailable; trying verified python.org installer.' }
    }

    # Python.org 3.14.10, official 64-bit installer released 26 Oct 2026.
    # Update URL and reviewed SHA-256 together when upgrading this fallback.
    $uri = 'https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe'
    $expectedSha256 = '92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965'
    $folder = Join-Path ([IO.Path]::GetTempPath()) ('SmoothCast-Python-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null
    $installer = Join-Path $folder 'python-installer.exe'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $installer -TimeoutSec 120
        $info = Get-Item -LiteralPath $installer
        if ($info.Length -lt 1000000 -or $info.Length -gt 100000000) {
            throw 'Python installer has an implausible file size.'
        }
        $actual = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expectedSha256) { throw 'Python.org installer SHA-256 mismatch: refusing execution.' }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or
            -not $signature.SignerCertificate -or
            $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw 'Python.org installer Authenticode signature is not valid for Python Software Foundation.'
        }
        $process = Start-Process -FilePath $installer -ArgumentList @(
            '/quiet','InstallAllUsers=0','PrependPath=0','Include_pip=1','Include_launcher=1'
        ) -PassThru -Wait
        if ($process.ExitCode -ne 0) {
            throw "Python installer exited with $($process.ExitCode)"
        }
    } finally {
        Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    $python = Find-Python
    if (-not $python) {
        if ($env:PYTHON) { throw 'The explicit PYTHON path is not Python 3.10+; fix or unset it.' }
        if (@($Forward) -contains '--check') {
            throw 'Python 3.10+ is not installed; --check is read-only.'
        }
        Install-Python
        $python = Find-Python
        if (-not $python) { throw 'Python installation finished but no usable interpreter was found.' }
    }

    Write-Host "[SmoothCast setup] Bootstrap interpreter: $python"
    & $python $Bootstrap '--target' 'windows' @Forward
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("[SmoothCast setup] FAILED: $($_.Exception.Message)")
    exit 1
}
) {
                        $paths += $Matches[1]
                    }
                }
            }
        } catch { }
    }
    foreach ($path in $paths) {
        if (Test-Python $path) { return $path }
    }
    return $null
}

function Install-Python {
    Write-Host '[SmoothCast setup] No Python 3.10+ found; acquiring Python 3.14 for this user.'
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            & $winget.Source install --id Python.Python.3.14 --exact --source winget --scope user --silent --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0 -and (Find-Python)) { return }
            Write-Warning 'WinGet did not provide a working interpreter; trying verified python.org installer.'
        } catch { Write-Warning 'WinGet is unavailable; trying verified python.org installer.' }
    }

    # Python.org 3.14.10, official 64-bit installer released 26 Oct 2026.
    # Update URL and reviewed SHA-256 together when upgrading this fallback.
    $uri = 'https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe'
    $expectedSha256 = '92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965'
    $folder = Join-Path ([IO.Path]::GetTempPath()) ('SmoothCast-Python-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null
    $installer = Join-Path $folder 'python-installer.exe'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $installer -TimeoutSec 120
        $info = Get-Item -LiteralPath $installer
        if ($info.Length -lt 1000000 -or $info.Length -gt 100000000) {
            throw 'Python installer has an implausible file size.'
        }
        $actual = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expectedSha256) { throw 'Python.org installer SHA-256 mismatch: refusing execution.' }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or
            -not $signature.SignerCertificate -or
            $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw 'Python.org installer Authenticode signature is not valid for Python Software Foundation.'
        }
        $process = Start-Process -FilePath $installer -ArgumentList @(
            '/quiet','InstallAllUsers=0','PrependPath=0','Include_pip=1','Include_launcher=1'
        ) -PassThru -Wait
        if ($process.ExitCode -ne 0) {
            throw "Python installer exited with $($process.ExitCode)"
        }
    } finally {
        Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    $python = Find-Python
    if (-not $python) {
        if ($env:PYTHON) { throw 'The explicit PYTHON path is not Python 3.10+; fix or unset it.' }
        if (@($Forward) -contains '--check') {
            throw 'Python 3.10+ is not installed; --check is read-only.'
        }
        Install-Python
        $python = Find-Python
        if (-not $python) { throw 'Python installation finished but no usable interpreter was found.' }
    }

    Write-Host "[SmoothCast setup] Bootstrap interpreter: $python"
    & $python $Bootstrap '--target' 'windows' @Forward
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("[SmoothCast setup] FAILED: $($_.Exception.Message)")
    exit 1
}
