param([string]$EnvFile = '')
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
if (-not $EnvFile) { $EnvFile=Join-Path $repo '../../work/runtime/banking.env' }
if (-not (Test-Path -LiteralPath $EnvFile)) { throw 'Provide a private environment file with -EnvFile.' }
Push-Location $repo
try {
  & docker compose --env-file $EnvFile -p aurora-bank-test up -d --wait db queue bank tools
  if ($LASTEXITCODE -ne 0) { throw 'Test dependencies did not start.' }
  & docker compose --env-file $EnvFile -p aurora-bank-test run --rm test
  $result=$LASTEXITCODE
} finally {
  # This project contains only disposable synthetic test data, never the development volume.
  & docker compose --env-file $EnvFile -p aurora-bank-test down -v --remove-orphans
  Pop-Location
}
exit $result
