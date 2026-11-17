<#
.SYNOPSIS
    Build the PDFMend Windows desktop app and a ZIP for GitHub Releases.

.DESCRIPTION
    Run from the repository root:

        powershell -ExecutionPolicy Bypass -File packaging\build.ps1

    Steps: install desktop + build extras, run the test suite, freeze with
    PyInstaller (one folder), then zip dist\PDFMend and print its SHA256.
    It never deletes anything outside dist\ and build\.
#>
param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path $Python)) {
    throw "找不到 Python：$Python。先建 venv 并 pip install -e `".[desktop,build]`"。"
}

$version = (& $Python -c "import pdfmend; print(pdfmend.__version__)").Trim()
Write-Host "PDFMend $version  ($root)"

Write-Host "== 安装依赖 =="
& $Python -m pip install -q -e ".[desktop,build]"

if (-not $SkipTests) {
    Write-Host "== 运行测试 =="
    $env:QT_QPA_PLATFORM = "offscreen"
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "测试失败，停止打包" }
}

Write-Host "== PyInstaller =="
& $Python -m PyInstaller packaging\pdfmend.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }

$exe = Join-Path $root "dist\PDFMend\PDFMend.exe"
if (-not (Test-Path $exe)) { throw "没有生成 $exe" }

$target = Join-Path $root "dist\PDFMend-$version-windows-x64.zip"
if (Test-Path $target) { Remove-Item $target }

Write-Host "== 压缩 =="
Compress-Archive -Path (Join-Path $root "dist\PDFMend\*") -DestinationPath $target -CompressionLevel Optimal

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLower()
$size = [math]::Round((Get-Item -LiteralPath $target).Length / 1MB, 1)
Write-Host ""
Write-Host "完成：$target  ($size MB)"
Write-Host "SHA256: $hash"
Write-Host "把这个 zip 和 sha256 一起放进 GitHub Release。"
