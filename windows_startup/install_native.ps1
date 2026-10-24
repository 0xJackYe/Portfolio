[CmdletBinding()]
param([string]$SourceDirectory)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($SourceDirectory)) {
    $SourceDirectory = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($SourceDirectory)) { $SourceDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path }
}
$ProofDirectory = Join-Path (Split-Path -Parent $SourceDirectory) 'verification\startup-repair-20261021'
if (-not (Test-Path -LiteralPath $ProofDirectory)) { New-Item -ItemType Directory -Path $ProofDirectory | Out-Null }
$ResultPath = Join-Path $ProofDirectory 'native-install-result.json'
$TranscriptStarted = $false
try {
    Start-Transcript -LiteralPath (Join-Path $ProofDirectory 'native-install.log') -Append | Out-Null
    $TranscriptStarted = $true
    & (Join-Path $SourceDirectory 'install_startup.ps1') -SkipVpnTask -SourceDirectory $SourceDirectory
    $State = Join-Path $env:LOCALAPPDATA 'WorkStartup'
    # The repair's first diagnostic task was created before the native files
    # could be installed. Preserve that capture but restore the real pre-repair
    # task state when an explicit, current-user origin journal establishes it.
    $OriginPath = Join-Path $ProofDirectory 'workspace-task-origin.json'
    if (Test-Path -LiteralPath $OriginPath -PathType Leaf) {
        $Origin = Get-Content -LiteralPath $OriginPath -Raw | ConvertFrom-Json
        $PolicyPath = Join-Path $State 'startup-policy-backup.json'
        $Policy = Get-Content -LiteralPath $PolicyPath -Raw | ConvertFrom-Json
        $Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        if ($Origin.OwnerSid -ceq $Sid -and $Origin.TaskName -ceq 'WorkStartup - Workspace' -and
            $Origin.ExistedBeforeRepair -eq $false -and $Policy.OwnerSid -ceq $Sid -and
            $Policy.TaskName -ceq $Origin.TaskName -and $Policy.TaskExists) {
            if ([string]$Policy.TaskXml -notlike ('*WorkStartup.Workspace.v2;OwnerSid=' + $Sid + '*')) { throw 'Diagnostic task origin does not match the backup.' }
            $OriginalCapture = Join-Path $State 'startup-policy-task-origin-backup.json'
            if (-not (Test-Path -LiteralPath $OriginalCapture)) { Copy-Item -LiteralPath $PolicyPath -Destination $OriginalCapture }
            Copy-Item -LiteralPath $OriginalCapture -Destination (Join-Path $ProofDirectory 'native-policy-backup-before-task-origin.json') -Force
            $Policy.TaskExists = $false
            $Policy.TaskXml = $null
            $Policy | Add-Member -NotePropertyName TaskOrigin -NotePropertyValue 'Absent before this repair; diagnostic capture retained separately.' -Force
            $Policy | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $PolicyPath -Encoding UTF8
        }
    }
    Copy-Item -LiteralPath (Join-Path $State 'startup-backup.json') -Destination (Join-Path $ProofDirectory 'native-startup-backup.json') -Force
    Copy-Item -LiteralPath (Join-Path $State 'startup-policy-backup.json') -Destination (Join-Path $ProofDirectory 'native-policy-backup.json') -Force
    & (Join-Path $State 'startup_policy.ps1') -Mode Status | Set-Content -LiteralPath (Join-Path $ProofDirectory 'native-after.json') -Encoding UTF8
    [pscustomobject]@{ Success = $true; RuntimeDirectory = $State; OwnerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value; UpdatedUtc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
} catch {
    [pscustomobject]@{ Success = $false; Error = $_.Exception.Message; UpdatedUtc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    throw
} finally { if ($TranscriptStarted) { Stop-Transcript | Out-Null } }
