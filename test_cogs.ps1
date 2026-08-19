try {
    $r = Invoke-WebRequest -Uri 'http://localhost:8080/cogs' -UseBasicParsing -MaximumRedirection 0 -ErrorAction Stop
    Write-Output "Status: $($r.StatusCode)"
    Write-Output $r.Content.Substring(0, [Math]::Min(5000, $r.Content.Length))
} catch {
    Write-Output "Error: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        Write-Output "Status: $([int]$_.Exception.Response.StatusCode)"
    }
}
