[CmdletBinding()]
param([switch]$SkipVpnTask, [switch]$VpnTaskOnly)

$ErrorActionPreference = 'Stop'
if ($SkipVpnTask -and $VpnTaskOnly) { throw 'Choose only one of -SkipVpnTask and -VpnTaskOnly.' }
$InstallDirectory = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'WorkStartup'))
if (-not (Test-Path -LiteralPath $InstallDirectory -PathType Container)) { throw 'WorkStartup is not installed.' }
if ((Get-Item -LiteralPath $InstallDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installation directory must not be a reparse point.' }
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$OwnerSid = $Identity.User.Value
$IsAdministrator = ([Security.Principal.WindowsPrincipal]$Identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$TaskName = 'WorkStartup - Skyline VPN'
$TaskMarker = 'WorkStartup.Managed.v1;OwnerSid=' + $OwnerSid
$VpnExecutable = 'C:\ProgramData\Skyline\skyline.exe'
$PythonExecutable = 'C:\Users\yxh\AppData\Local\Programs\Python\Python39\pythonw.exe'
$BackupPath = Join-Path $InstallDirectory 'startup-backup.json'
$TaskBackupPath = Join-Path $InstallDirectory 'vpn-task-backup.json'
$StartupDirectory = [Environment]::GetFolderPath('Startup')
$WorkShortcut = Join-Path $StartupDirectory 'Work Startup.lnk'
$OldShortcut = Join-Path $StartupDirectory 'Bitcoin Terminal.lnk'
$RunPath = 'Software\Microsoft\Windows\CurrentVersion\Run'
$ApprovedPath = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'

function Write-JsonFile([string]$Path, $Data) {
    $Full = [IO.Path]::GetFullPath($Path)
    if (-not $Full.StartsWith($InstallDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Output path is outside the installation directory.' }
    $Temporary = $Full + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $Data | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Temporary -Encoding UTF8
        Move-Item -LiteralPath $Temporary -Destination $Full -Force
    } finally { if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force } }
}

function Test-OwnedTask($Task) {
    if ($null -eq $Task -or $Task.Description -ne $TaskMarker) { return $false }
    $Actions = @($Task.Actions)
    $PrincipalSid = [string]$Task.Principal.UserId
    if ($PrincipalSid -notmatch '^S-1-') {
        try {
            $Account = New-Object Security.Principal.NTAccount($PrincipalSid)
            $PrincipalSid = $Account.Translate([Security.Principal.SecurityIdentifier]).Value
        } catch { return $false }
    }
    return ($Actions.Count -eq 1 -and $Actions[0].Execute -ieq $VpnExecutable -and
        [string]::IsNullOrWhiteSpace($Actions[0].Arguments) -and
        $PrincipalSid -eq $OwnerSid)
}

function Restore-VpnTask {
    if (-not (Test-Path -LiteralPath $TaskBackupPath -PathType Leaf)) { Write-Output 'No VPN task backup exists; no task was changed.'; return }
    try {
        if (-not $IsAdministrator) { throw 'VPN task restoration requires an administrator token. No UAC prompt was opened.' }
        $Saved = Get-Content -LiteralPath $TaskBackupPath -Raw | ConvertFrom-Json
        if ($Saved.OwnerSid -ne $OwnerSid -or $Saved.Version -ne 1 -or $Saved.TaskName -ne $TaskName -or $Saved.TaskPath -ne '\') { throw 'VPN task backup ownership or version does not match.' }
        $Existing = Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName }
        $RestoredXml = $null
        if ($null -ne $Existing) { $RestoredXml = Export-ScheduledTask -TaskName $TaskName -TaskPath '\' }
        $AlreadyOriginal = $Saved.Exists -and ($null -ne $Existing) -and ($RestoredXml -eq $Saved.Xml)
        if ($null -ne $Existing -and -not (Test-OwnedTask $Existing) -and -not $AlreadyOriginal) { throw 'The current VPN task is unrelated or changed; it will not be modified.' }
        if ($Saved.Exists) {
            if (-not $AlreadyOriginal) { Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Xml ([string]$Saved.Xml) -Force | Out-Null }
        } elseif ($null -ne $Existing) { Unregister-ScheduledTask -TaskName $TaskName -TaskPath '\' -Confirm:$false }
        Write-JsonFile (Join-Path $InstallDirectory 'vpn-task-status.json') ([pscustomobject]@{ Success = $true; State = 'Restored'; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
        Write-Output 'Skyline logon task restored to its original state.'
    } catch {
        Write-JsonFile (Join-Path $InstallDirectory 'vpn-task-status.json') ([pscustomobject]@{ Success = $false; State = 'RestoreFailed'; Error = $_.Exception.Message; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
        throw
    }
}

function Assert-BackupFile([string]$Path, [string]$ExpectedName, [string]$Hash) {
    $Expected = Join-Path $InstallDirectory $ExpectedName
    if ([IO.Path]::GetFullPath($Path) -ine $Expected) { throw 'Unexpected shortcut backup path.' }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Shortcut backup is missing: $ExpectedName" }
    if ((Get-Item -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Shortcut backup must not be a reparse point.' }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Hash) { throw "Shortcut backup hash does not match: $ExpectedName" }
}

function Restore-RegistryValue($Saved) {
    if ($Saved.Name -notin @('Steam', 'Feishu') -or $Saved.Path -notin @($RunPath, $ApprovedPath)) { throw 'Unexpected registry target in backup.' }
    if ($Saved.Exists) {
        $Kind = [Microsoft.Win32.RegistryValueKind][Enum]::Parse([Microsoft.Win32.RegistryValueKind], [string]$Saved.Kind)
        $Value = $Saved.Value
        switch ([string]$Saved.Kind) {
            'Binary' { $Value = [Convert]::FromBase64String([string]$Saved.Value) }
            'DWord' { $Value = [int]$Saved.Value }
            'QWord' { $Value = [long]$Saved.Value }
            'MultiString' { $Value = [string[]]$Saved.Value }
            'String' { $Value = [string]$Saved.Value }
            'ExpandString' { $Value = [string]$Saved.Value }
            default { throw 'Unsupported registry value type in backup.' }
        }
        $Key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey([string]$Saved.Path)
        try { $Key.SetValue([string]$Saved.Name, $Value, $Kind) } finally { $Key.Dispose() }
    } else {
        $Key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey([string]$Saved.Path, $true)
        try { if ($null -ne $Key) { $Key.DeleteValue([string]$Saved.Name, $false) } } finally { if ($null -ne $Key) { $Key.Dispose() } }
    }
}

if ($VpnTaskOnly) { Restore-VpnTask; return }

try {
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) { throw 'No ordinary startup backup exists; no ordinary startup settings were restored.' }
    $Saved = Get-Content -LiteralPath $BackupPath -Raw | ConvertFrom-Json
    if ($Saved.OwnerSid -ne $OwnerSid -or $Saved.Version -ne 1) { throw 'Startup backup ownership or version does not match.' }
    if ($Saved.WorkShortcut.Path -ine $WorkShortcut -or $Saved.OldShortcut.Path -ine $OldShortcut) { throw 'Shortcut paths in backup do not match the current user startup folder.' }
    if ($Saved.WorkShortcut.Exists) { Assert-BackupFile $Saved.WorkShortcut.BackupPath 'Work Startup.original.lnk' $Saved.WorkShortcut.SHA256 }
    if ($Saved.OldShortcut.Exists) { Assert-BackupFile $Saved.OldShortcut.BackupPath 'Bitcoin Terminal.original.lnk' $Saved.OldShortcut.SHA256 }
    $CanChangeWorkShortcut = $true
    if (Test-Path -LiteralPath $WorkShortcut -PathType Leaf) {
        if ((Get-Item -LiteralPath $WorkShortcut).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Startup shortcut must not be a reparse point.' }
        $AlreadyOriginal = $Saved.WorkShortcut.Exists -and ((Get-FileHash -LiteralPath $WorkShortcut -Algorithm SHA256).Hash -eq $Saved.WorkShortcut.SHA256)
        if ($AlreadyOriginal) { $CanChangeWorkShortcut = $false }
        else {
            $Shell = New-Object -ComObject WScript.Shell
            $Link = $Shell.CreateShortcut($WorkShortcut)
            $LauncherPath = Join-Path $InstallDirectory 'start_workspace.py'
            $ConfigPath = Join-Path $InstallDirectory 'config.json'
            $ExpectedArguments = '"' + $LauncherPath + '" --config "' + $ConfigPath + '"'
            if ($Link.TargetPath -ine $PythonExecutable -or $Link.Arguments -cne $ExpectedArguments -or $Link.Description -ne 'WorkStartup managed workspace launcher') { throw 'Work Startup.lnk is unrelated or changed; it will not be modified.' }
        }
    }
    if ($Saved.OldShortcut.Exists -and (Test-Path -LiteralPath $OldShortcut -PathType Leaf)) {
        if ((Get-Item -LiteralPath $OldShortcut).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Bitcoin shortcut must not be a reparse point.' }
        if ((Get-FileHash -LiteralPath $OldShortcut -Algorithm SHA256).Hash -ne $Saved.OldShortcut.SHA256) { throw 'Bitcoin Terminal.lnk is unrelated or changed; it will not be overwritten.' }
    }
    foreach ($Entry in @($Saved.Registry)) {
        if ($Entry.Name -notin @('Steam', 'Feishu') -or $Entry.Path -notin @($RunPath, $ApprovedPath)) { throw 'Unexpected registry target in backup.' }
    }
    $PolicyScript = Join-Path $InstallDirectory 'startup_policy.ps1'
    if (Test-Path -LiteralPath $PolicyScript -PathType Leaf) { & $PolicyScript -Mode Restore }
    foreach ($Entry in @($Saved.Registry)) { Restore-RegistryValue $Entry }
    foreach ($RegistryPath in @($RunPath, $ApprovedPath)) {
        $Entries = @($Saved.Registry | Where-Object { $_.Path -eq $RegistryPath })
        if ($Entries.Count -eq 2 -and -not ($Entries | Where-Object { $_.KeyExists })) {
            $Key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($RegistryPath, $false)
            $Empty = $false
            try { if ($null -ne $Key) { $Empty = $Key.ValueCount -eq 0 -and $Key.SubKeyCount -eq 0 } } finally { if ($null -ne $Key) { $Key.Dispose() } }
            if ($Empty) { [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKey($RegistryPath, $false) }
        }
    }
    if ($CanChangeWorkShortcut) {
        if ($Saved.WorkShortcut.Exists) { Copy-Item -LiteralPath $Saved.WorkShortcut.BackupPath -Destination $WorkShortcut -Force }
        elseif (Test-Path -LiteralPath $WorkShortcut -PathType Leaf) { Remove-Item -LiteralPath $WorkShortcut }
    }
    if ($Saved.OldShortcut.Exists -and -not (Test-Path -LiteralPath $OldShortcut)) { Copy-Item -LiteralPath $Saved.OldShortcut.BackupPath -Destination $OldShortcut }
    $VpnState = 'Skipped'
    if (-not $SkipVpnTask) { if ($IsAdministrator) { $VpnState = 'PendingRestore' } else { $VpnState = 'RequiresAdministrator' } }
    Write-JsonFile (Join-Path $InstallDirectory 'status.json') ([pscustomobject]@{ Success = $true; State = 'Restored'; VpnTask = $VpnState; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
    Write-Output 'Original Steam, Feishu, and startup shortcuts restored. Runtime files and backups retained.'
} catch {
    Write-JsonFile (Join-Path $InstallDirectory 'status.json') ([pscustomobject]@{ Success = $false; State = 'RestoreFailed'; Error = $_.Exception.Message; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
    throw
}
if (-not $SkipVpnTask -and $IsAdministrator) { Restore-VpnTask }
elseif (-not $SkipVpnTask -and (Test-Path -LiteralPath $TaskBackupPath)) { Write-Output 'VPN task restoration requires an elevated run with -VpnTaskOnly. No UAC prompt was opened.' }
