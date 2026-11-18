# DVAP command line for Windows PowerShell. Usage: .\dvap.ps1 <command>, e.g. .\dvap.ps1 doctor
# (WSL2 users: run ./dvap from the WSL shell instead.) Lifecycle commands need only Python 3.9+.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($args.Count -gt 0 -and $args[0] -eq "bench" -and (Get-Command uv -ErrorAction SilentlyContinue)) {
    & uv run --quiet dvap @args; exit $LASTEXITCODE
}
foreach ($py in @("py", "python", "python3")) {
    if (Get-Command $py -ErrorAction SilentlyContinue) {
        & $py -c "import sys; sys.exit(sys.version_info < (3, 9))" 2>$null
        if ($LASTEXITCODE -eq 0) { & $py -m bench @args; exit $LASTEXITCODE }
    }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run --quiet --no-project --python 3.12 python -m bench @args; exit $LASTEXITCODE
}
Write-Error "dvap needs Python 3.9+ or uv (https://docs.astral.sh/uv/getting-started/installation/)."
exit 1
