# Local static server for development and testing.
# Usage: powershell -ExecutionPolicy Bypass -File start.ps1
$port = 8765
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootFull = [IO.Path]::GetFullPath($root).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar

$mime = @{
  '.html' = 'text/html; charset=utf-8'
  '.js'   = 'text/javascript'
  '.mjs'  = 'text/javascript'
  '.css'  = 'text/css'
  '.wasm' = 'application/wasm'
  '.tflite' = 'application/octet-stream'
  '.pdf'  = 'application/pdf'
  '.json' = 'application/json'
  '.png'  = 'image/png'
  '.jpg'  = 'image/jpeg'
  '.svg'  = 'image/svg+xml'
}

$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add("http://127.0.0.1:$port/")
$listener.Start()
Write-Host "Sirviendo $root en http://127.0.0.1:$port  (Ctrl+C para detener)"

while ($listener.IsListening) {
  $ctx = $listener.GetContext()
  try {
    if ($ctx.Request.HttpMethod -notin @('GET', 'HEAD')) {
      $ctx.Response.StatusCode = 405
      $ctx.Response.Headers['Allow'] = 'GET, HEAD'
      continue
    }
    $rel = [Uri]::UnescapeDataString($ctx.Request.Url.AbsolutePath)
    if ($rel -eq '/') { $rel = '/index.html' }
    $path = [IO.Path]::GetFullPath((Join-Path $root ($rel.TrimStart('/').Replace('/', [IO.Path]::DirectorySeparatorChar))))
    if (-not $path.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
      $ctx.Response.StatusCode = 403
      continue
    }
    if (Test-Path -LiteralPath $path -PathType Leaf) {
      $data = [IO.File]::ReadAllBytes($path)
      $ext = [IO.Path]::GetExtension($path).ToLowerInvariant()
      $ct = if ($mime.ContainsKey($ext)) { $mime[$ext] } else { 'application/octet-stream' }
      $ctx.Response.ContentType = $ct
      $ctx.Response.Headers['X-Content-Type-Options'] = 'nosniff'
      $ctx.Response.Headers['Referrer-Policy'] = 'no-referrer'
      $ctx.Response.Headers['Cache-Control'] = 'no-store'
      $ctx.Response.Headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; worker-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
      $ctx.Response.ContentLength64 = $data.Length
      if ($ctx.Request.HttpMethod -ne 'HEAD') { $ctx.Response.OutputStream.Write($data, 0, $data.Length) }
    } else {
      $ctx.Response.StatusCode = 404
    }
  } catch {
    $ctx.Response.StatusCode = 500
  } finally {
    $ctx.Response.Close()
  }
}
