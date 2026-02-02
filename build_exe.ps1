param(
    [string]$Entry = "ui_app.py",
    [string]$Name = "vcbot-ui"
)

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$distDir = "dist\$Name-$timestamp"

pyinstaller `
  --onefile `
  --name $Name `
  --distpath $distDir `
  $Entry
