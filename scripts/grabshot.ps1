# Save the image currently on the clipboard to a PNG.
#   powershell -sta -File grabshot.ps1 <name>
# Press PrintScreen in game, alt-tab out, run this. Files land in .\shots\
param([string]$Name = "shot")

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $img) {
    Write-Output "clipboard holds no image"
    exit 1
}

$dir = Join-Path $PSScriptRoot "shots"
if (-not (Test-Path $dir)) { New-Item -ItemType Directory $dir | Out-Null }
$path = Join-Path $dir "$Name.png"
$img.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "$path  $($img.Width)x$($img.Height)"
