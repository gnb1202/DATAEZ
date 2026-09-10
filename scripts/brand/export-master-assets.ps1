param([string]$ChromePath = '')

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$brandRoot = Join-Path $repositoryRoot 'outputs\brand\gathered-ledger'

# Install once with: npm ci --prefix scripts/ui-eval
& node (Join-Path $PSScriptRoot 'export-master-assets.cjs') $ChromePath
if ($LASTEXITCODE -ne 0) { throw 'Brand PNG export or validation failed.' }

Compress-Archive -Path (Join-Path $brandRoot 'master\*') -DestinationPath (Join-Path $brandRoot 'dataez-brand-master-v1.zip') -Force
Write-Output 'Updated dataez-brand-master-v1.zip from the verified master assets.'
