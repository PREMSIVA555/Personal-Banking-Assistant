[CmdletBinding(PositionalBinding=$false)]
param([string]$EnvFile = '', [Parameter(Position=0,ValueFromRemainingArguments=$true)][string[]]$ComposeArgs)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
if (-not $EnvFile) { $EnvFile = Join-Path $repo '../../work/runtime/banking.env' }
if (-not (Test-Path -LiteralPath $EnvFile)) { throw 'Create a private environment file from .env.example and pass -EnvFile <path>.' }
Push-Location $repo
try { & docker compose --env-file $EnvFile @ComposeArgs; $result = $LASTEXITCODE } finally { Pop-Location }
exit $result
