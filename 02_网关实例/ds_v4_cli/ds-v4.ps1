param(
    [Parameter(Position=0, Mandatory=$false)]
    [string]$Prompt,

    [Alias("p")]
    [string]$Provider = "siliconflow",

    [Alias("m")]
    [string]$Model,

    [Alias("k")]
    [string]$Key
)

$scriptPath = Join-Path $PSScriptRoot "ds-v4.py"

if (-not $Prompt) {
    python $scriptPath
} else {
    $argsList = @($scriptPath, "`"$Prompt`"", "-p", $Provider)
    if ($Model) { $argsList += @("-m", $Model) }
    if ($Key) { $argsList += @("-k", $Key) }
    
    python @argsList
}
