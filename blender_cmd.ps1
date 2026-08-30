param(
    [Parameter(Mandatory=$true)][string]$Type,
    [string]$ParamsJson,
    [string]$CodeFile,
    [int]$TimeoutSec = 120
)

if ($CodeFile) {
    $code = [System.IO.File]::ReadAllText($CodeFile)
    $payload = @{ type = $Type; params = @{ code = $code } } | ConvertTo-Json -Depth 5 -Compress
} elseif ($ParamsJson) {
    $payload = '{"type":"' + $Type + '","params":' + $ParamsJson + '}'
} else {
    $payload = '{"type":"' + $Type + '","params":{}}'
}

$client = New-Object System.Net.Sockets.TcpClient
$client.Connect("localhost", 9876)
$stream = $client.GetStream()
$bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
$stream.Write($bytes, 0, $bytes.Length)
$stream.Flush()

$buf = New-Object byte[] 65536
$sb = New-Object System.Text.StringBuilder
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$stream.ReadTimeout = 2000
while ((Get-Date) -lt $deadline) {
    $n = 0
    try { $n = $stream.Read($buf, 0, $buf.Length) } catch {}
    if ($n -gt 0) {
        [void]$sb.Append([System.Text.Encoding]::UTF8.GetString($buf, 0, $n))
        $s = $sb.ToString()
        try { $null = $s | ConvertFrom-Json -ErrorAction Stop; break } catch {}
    }
}
$client.Close()
$sb.ToString()
