# OCR page images with the OCR engine built into Windows 10/11 (no downloads, no admin rights).
# Started by ocr.py; not meant to be run by hand.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File winocr.ps1 -Languages
#       prints the installed OCR languages as a JSON array, e.g. ["en-US"]
#   powershell -NoProfile -ExecutionPolicy Bypass -File winocr.ps1 -List paths.txt -Out out.jsonl [-Lang en-US]
#              [-WaitSeconds 120] [-StopFile stop.txt] [-ParentPid 1234]
#       reads every image listed in paths.txt and appends one JSON line per image as soon as it is read:
#       {"image": path, "width": w, "height": h, "angle": a, "lines": [{"text": "...", "x0":..,"y0":..,"x1":..,"y1":..}]}
#       Images are PNG/JPEG/BMP/TIFF files, or ".gray" files: an 8-byte header (width, height as little-endian
#       int32) followed by raw 8-bit gray pixels - no encoding or decoding, which makes big scans much faster.
#       With -WaitSeconds, an image that does not exist yet is waited for (the caller renders pages while this runs).
#       The worker stops early when the stop file appears (after finishing the images that exist) or its parent exits.
param(
    [string]$List = "",
    [string]$Out = "",
    [string]$Lang = "",
    [int]$WaitSeconds = 0,
    [string]$StopFile = "",
    [int]$ParentPid = 0,
    [switch]$Languages
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

if ($Languages) {
    $tags = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
    [Console]::Out.WriteLine((ConvertTo-Json -Compress -InputObject $tags))
    exit 0
}

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
}

if ($Lang) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang))
} else {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    $have = ([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }) -join ', '
    [Console]::Error.WriteLine("No Windows OCR language '$Lang' installed. Installed: $have")
    exit 3
}

$script:quit = $false
function Test-Parent {
    if ($ParentPid -le 0) { return $true }
    try { $null = [System.Diagnostics.Process]::GetProcessById($ParentPid); return $true } catch { return $false }
}
function Wait-Image([string]$path) {
    if ([System.IO.File]::Exists($path)) { return $true }
    if ($StopFile -and [System.IO.File]::Exists($StopFile)) { $script:quit = $true; return $false }
    if ($WaitSeconds -le 0) { return $false }
    $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
    $n = 0
    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 60
        if ([System.IO.File]::Exists($path)) { return $true }
        if ($StopFile -and [System.IO.File]::Exists($StopFile)) { $script:quit = $true; return $false }
        $n++
        if (($n % 15) -eq 0 -and -not (Test-Parent)) { $script:quit = $true; return $false }
    }
    return $false
}

function Read-Bitmap([string]$path) {
    if ($path.EndsWith(".gray")) {
        $bytes = [System.IO.File]::ReadAllBytes($path)
        $w = [BitConverter]::ToInt32($bytes, 0)
        $h = [BitConverter]::ToInt32($bytes, 4)
        $buf = [System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeBufferExtensions]::AsBuffer($bytes, 8, $w * $h)
        return [Windows.Graphics.Imaging.SoftwareBitmap]::CreateCopyFromBuffer($buf,
            [Windows.Graphics.Imaging.BitmapPixelFormat]::Gray8, $w, $h)
    }
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        return Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    } finally {
        $stream.Dispose()
    }
}

$writer = New-Object System.IO.StreamWriter($Out, $true, (New-Object System.Text.UTF8Encoding($false)))
$writer.AutoFlush = $true
try {
    foreach ($item in [System.IO.File]::ReadAllLines($List)) {
        $path = [string]$item.Trim()
        if (-not $path) { continue }
        if (-not (Wait-Image $path)) {
            if ($script:quit) { break }
            $writer.WriteLine((ConvertTo-Json -Compress -InputObject ([ordered]@{ image = $path; error = "image not found" })))
            continue
        }
        try {
            $bitmap = Read-Bitmap $path
            $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $lines = New-Object System.Collections.ArrayList
            foreach ($ln in $result.Lines) {
                $x0 = [double]::MaxValue; $y0 = [double]::MaxValue; $x1 = 0.0; $y1 = 0.0
                foreach ($w in $ln.Words) {
                    $r = $w.BoundingRect
                    if ($r.X -lt $x0) { $x0 = $r.X }
                    if ($r.Y -lt $y0) { $y0 = $r.Y }
                    if ($r.X + $r.Width -gt $x1) { $x1 = $r.X + $r.Width }
                    if ($r.Y + $r.Height -gt $y1) { $y1 = $r.Y + $r.Height }
                }
                [void]$lines.Add([ordered]@{ text = $ln.Text; x0 = [math]::Round($x0, 1); y0 = [math]::Round($y0, 1);
                        x1 = [math]::Round($x1, 1); y1 = [math]::Round($y1, 1) })
            }
            $angle = 0.0
            if ($null -ne $result.TextAngle) { $angle = [math]::Round([double]$result.TextAngle, 2) }
            $rec = [ordered]@{ image = $path; width = $bitmap.PixelWidth; height = $bitmap.PixelHeight; angle = $angle;
                lines = $lines }
            $writer.WriteLine((ConvertTo-Json -Compress -Depth 5 -InputObject $rec))
            $bitmap.Dispose()
        } catch {
            $writer.WriteLine((ConvertTo-Json -Compress -InputObject ([ordered]@{ image = $path; error = [string]$_.Exception.Message })))
        }
    }
} finally {
    $writer.Close()
}
