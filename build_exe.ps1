param(
    [string]$Entry = "ui_app.py",
    [string]$Name = "vcbot-ui",
    [string]$Version = "v1.0.1"
)

# Start the timer
$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "Starting build process for $Name..." -ForegroundColor Cyan

# Clean previous build output
Write-Host "`nCleaning previous build..." -ForegroundColor Yellow
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "release") { Remove-Item "release" -Recurse -Force }
Write-Host "Previous build removed." -ForegroundColor Green

# Run PyInstaller
Write-Host "`n[1/3] Running PyInstaller..." -ForegroundColor Yellow
pyinstaller --clean --noconfirm vcbot-ui.spec --log-level INFO
$pyinstallerTime = $Stopwatch.Elapsed.ToString('hh\:mm\:ss')
Write-Host "PyInstaller completed in $pyinstallerTime" -ForegroundColor Green

# Determine output app folder
$APP_DIR = Join-Path "dist" $Name

# Copy templates
Write-Host "`n[2/3] Copying templates..." -ForegroundColor Yellow
$TEMPLATE_TARGET_DIR = Join-Path $APP_DIR "templates"
if (-Not (Test-Path $TEMPLATE_TARGET_DIR)) { New-Item -ItemType Directory -Path $TEMPLATE_TARGET_DIR | Out-Null }
Copy-Item -Path "templates\*" -Destination $TEMPLATE_TARGET_DIR -Recurse -Force
Write-Host "Templates copied." -ForegroundColor Green

# Trim unneeded Qt junk
Write-Host "Trimming unneeded Qt components..." -ForegroundColor Yellow
$APP = $APP_DIR
$INTERNAL = Join-Path $APP "_internal"
$PYSIDE = Join-Path $INTERNAL "PySide6"

# We target both possible locations (root or _internal) just in case
foreach ($base in $APP, $INTERNAL) {
    if (Test-Path $base) {
        Remove-Item "$base\PySide6\Qt6WebEngine*" -Force -Recurse -ErrorAction SilentlyContinue
        Remove-Item "$base\PySide6\resources\qtwebengine*" -Force -Recurse -ErrorAction SilentlyContinue
        Remove-Item "$base\PySide6\Qt6Multimedia*" -Force -Recurse -ErrorAction SilentlyContinue
        Remove-Item "$base\PySide6\plugins\mediaservice" -Force -Recurse -ErrorAction SilentlyContinue
        Remove-Item "$base\PySide6\plugins\audio" -Force -Recurse -ErrorAction SilentlyContinue
        Remove-Item "$base\PySide6\plugins\bearer" -Force -Recurse -ErrorAction SilentlyContinue
        Get-ChildItem $base -Recurse -Include *.pdb,*.debug | Remove-Item -Force
    }
}
Write-Host "Cleanup complete." -ForegroundColor Green

# Create release zip
Write-Host "`n[3/3] Creating release zip..." -ForegroundColor Yellow
$RELEASE_DIR = "release"
$ZIP_NAME = "$($Name)_$($Version).zip"
if (-Not (Test-Path $RELEASE_DIR)) { New-Item -ItemType Directory -Path $RELEASE_DIR | Out-Null }

$ZIP_PATH = Join-Path $RELEASE_DIR $ZIP_NAME
if (Test-Path $ZIP_PATH) { Remove-Item $ZIP_PATH -Force }

Compress-Archive -Path "$APP_DIR\*" -DestinationPath $ZIP_PATH
$compressionTime = $Stopwatch.Elapsed.ToString('hh\:mm\:ss')

# Final summary
$Stopwatch.Stop()
Write-Host "`nBuild completed successfully!" -ForegroundColor Green
Write-Host "`nTime Summary:" -ForegroundColor Cyan
Write-Host "- PyInstaller: $pyinstallerTime"
Write-Host "- Compression: $compressionTime"
Write-Host "`nTotal Time: $($Stopwatch.Elapsed.ToString('hh\:mm\:ss'))" -ForegroundColor Yellow
