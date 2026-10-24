[CmdletBinding()]
param(
    [switch]$SkipVpnTask,
    [switch]$VpnTaskOnly,
    [string]$SourceDirectory
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($SourceDirectory)) {
    $SourceDirectory = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($SourceDirectory)) {
        $SourceDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
}
if ($SkipVpnTask -and $VpnTaskOnly) { throw 'Choose only one of -SkipVpnTask and -VpnTaskOnly.' }

$InstallDirectory = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'WorkStartup'))
$ExpectedDirectory = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'WorkStartup'))
if ($InstallDirectory -ne $ExpectedDirectory) { throw 'Unexpected installation directory.' }
if (-not (Test-Path -LiteralPath $InstallDirectory)) { New-Item -ItemType Directory -Path $InstallDirectory | Out-Null }
if ((Get-Item -LiteralPath $InstallDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installation directory must not be a reparse point.' }
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$OwnerSid = $Identity.User.Value
$IsAdministrator = ([Security.Principal.WindowsPrincipal]$Identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$TaskName = 'WorkStartup - Skyline VPN'
$TaskMarker = 'WorkStartup.Managed.v1;OwnerSid=' + $OwnerSid
$VpnExecutable = 'C:\ProgramData\Skyline\skyline.exe'
$PythonExecutable = 'C:\Users\yxh\AppData\Local\Programs\Python\Python39\pythonw.exe'
$LauncherPath = Join-Path $InstallDirectory 'start_workspace.py'
$ConfigPath = Join-Path $InstallDirectory 'config.json'
$BackupPath = Join-Path $InstallDirectory 'startup-backup.json'
$TaskBackupPath = Join-Path $InstallDirectory 'vpn-task-backup.json'
$StatusPath = Join-Path $InstallDirectory 'status.json'
$TaskStatusPath = Join-Path $InstallDirectory 'vpn-task-status.json'
$RunPath = 'Software\Microsoft\Windows\CurrentVersion\Run'
$ApprovedPath = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
$StartupDirectory = [Environment]::GetFolderPath('Startup')
$WorkShortcut = Join-Path $StartupDirectory 'Work Startup.lnk'
$OldShortcut = Join-Path $StartupDirectory 'Bitcoin Terminal.lnk'

function Write-JsonFile([string]$Path, $Data) {
    $Full = [IO.Path]::GetFullPath($Path)
    if (-not $Full.StartsWith($InstallDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Output path is outside the installation directory.' }
    $Temporary = $Full + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $Data | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Temporary -Encoding UTF8
        Move-Item -LiteralPath $Temporary -Destination $Full -Force
    } finally { if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force } }
}

function Get-RegistrySnapshot([string]$Path, [string]$Name) {
    $Key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($Path, $false)
    try {
        $KeyExists = $null -ne $Key
        $Exists = $KeyExists -and ($Key.GetValueNames() -contains $Name)
        $Kind = $null
        $Value = $null
        if ($Exists) {
            $Kind = [string]$Key.GetValueKind($Name)
            $Value = $Key.GetValue($Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            if ($Kind -eq 'Binary') { $Value = [Convert]::ToBase64String([byte[]]$Value) }
        }
        return [pscustomobject]@{ Path = $Path; Name = $Name; KeyExists = $KeyExists; Exists = $Exists; Kind = $Kind; Value = $Value }
    } finally { if ($null -ne $Key) { $Key.Dispose() } }
}

function Backup-Shortcut([string]$Path, [string]$FileName) {
    $Exists = Test-Path -LiteralPath $Path -PathType Leaf
    $SavedPath = Join-Path $InstallDirectory $FileName
    $Hash = $null
    if ($Exists) {
        if ((Get-Item -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Shortcut must not be a reparse point.' }
        $Hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        if (Test-Path -LiteralPath $SavedPath) {
            if ((Get-Item -LiteralPath $SavedPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Shortcut backup must not be a reparse point.' }
            if ((Get-FileHash -LiteralPath $SavedPath -Algorithm SHA256).Hash -ne $Hash) { throw "An unrelated backup already exists: $FileName" }
        } else { Copy-Item -LiteralPath $Path -Destination $SavedPath }
    }
    return [pscustomobject]@{ Path = $Path; Exists = $Exists; BackupPath = $SavedPath; SHA256 = $Hash }
}

function Quote-WindowsArgument([string]$Value) {
    $Result = '"'
    $Slashes = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq '\') { $Slashes++; continue }
        if ($Character -eq '"') { $Result += ('\' * (2 * $Slashes + 1)) + '"' }
        else { $Result += ('\' * $Slashes) + $Character }
        $Slashes = 0
    }
    return $Result + ('\' * (2 * $Slashes)) + '"'
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

function Install-VpnTask {
    try {
        if (-not $IsAdministrator) { throw 'VPN task installation requires an administrator token. No UAC prompt was opened.' }
        if (-not (Test-Path -LiteralPath $VpnExecutable -PathType Leaf)) { throw 'Skyline executable was not found.' }
        $Existing = Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName }
        if ($null -ne $Existing -and -not (Test-OwnedTask $Existing)) { throw 'An unrelated task has the requested VPN task name; it will not be overwritten.' }
        if (-not (Test-Path -LiteralPath $TaskBackupPath)) {
            $Xml = $null
            if ($null -ne $Existing) { $Xml = Export-ScheduledTask -TaskName $TaskName -TaskPath '\' }
            Write-JsonFile $TaskBackupPath ([pscustomobject]@{ Version = 1; OwnerSid = $OwnerSid; TaskName = $TaskName; TaskPath = '\'; Exists = ($null -ne $Existing); Xml = $Xml })
        } else {
            $Saved = Get-Content -LiteralPath $TaskBackupPath -Raw | ConvertFrom-Json
            if ($Saved.OwnerSid -ne $OwnerSid -or $Saved.TaskName -ne $TaskName -or $Saved.TaskPath -ne '\') { throw 'VPN task backup ownership does not match.' }
        }
        $Action = New-ScheduledTaskAction -Execute $VpnExecutable -WorkingDirectory 'C:\ProgramData\Skyline'
        $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $OwnerSid
        $Trigger.Delay = 'PT5S'
        $Principal = New-ScheduledTaskPrincipal -UserId $OwnerSid -LogonType Interactive -RunLevel Highest
        $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
        $Definition = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $TaskMarker
        Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -InputObject $Definition -Force | Out-Null
        $Installed = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
        if (-not (Test-OwnedTask $Installed)) { throw 'VPN task verification failed.' }
        Write-JsonFile $TaskStatusPath ([pscustomobject]@{ Success = $true; State = 'Installed'; TaskName = $TaskName; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
        Write-Output 'Skyline logon task installed. The task launches the application only.'
    } catch {
        Write-JsonFile $TaskStatusPath ([pscustomobject]@{ Success = $false; State = 'Failed'; Error = $_.Exception.Message; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
        throw
    }
}

if ($VpnTaskOnly) { Install-VpnTask; return }

try {
    foreach ($FileName in @('start_workspace.py', 'config.json', 'startup_policy.ps1')) {
        $Source = [IO.Path]::GetFullPath((Join-Path $SourceDirectory $FileName))
        if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "Required runtime file is missing: $FileName" }
    }
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'The configured pythonw.exe was not found.' }
    if (-not (Test-Path -LiteralPath $StartupDirectory -PathType Container)) { New-Item -ItemType Directory -Path $StartupDirectory | Out-Null }
    if (-not (Test-Path -LiteralPath $BackupPath)) {
        $Snapshots = @()
        foreach ($Name in @('Steam', 'Feishu')) {
            $Snapshots += Get-RegistrySnapshot $RunPath $Name
            $Snapshots += Get-RegistrySnapshot $ApprovedPath $Name
        }
        $WorkBackup = Backup-Shortcut $WorkShortcut 'Work Startup.original.lnk'
        $OldBackup = Backup-Shortcut $OldShortcut 'Bitcoin Terminal.original.lnk'
        $Backup = [pscustomobject]@{ Version = 1; OwnerSid = $OwnerSid; CreatedUtc = [DateTime]::UtcNow.ToString('o'); Registry = $Snapshots; WorkShortcut = $WorkBackup; OldShortcut = $OldBackup }
        Write-JsonFile $BackupPath $Backup
    } else {
        $Backup = Get-Content -LiteralPath $BackupPath -Raw | ConvertFrom-Json
        if ($Backup.OwnerSid -ne $OwnerSid -or $Backup.Version -ne 1) { throw 'Startup backup ownership or version does not match.' }
    }
    if ($Backup.WorkShortcut.Path -ine $WorkShortcut -or $Backup.OldShortcut.Path -ine $OldShortcut -or
        [IO.Path]::GetFullPath([string]$Backup.WorkShortcut.BackupPath) -ine (Join-Path $InstallDirectory 'Work Startup.original.lnk') -or
        [IO.Path]::GetFullPath([string]$Backup.OldShortcut.BackupPath) -ine (Join-Path $InstallDirectory 'Bitcoin Terminal.original.lnk')) { throw 'Unexpected shortcut paths in backup.' }
    if (Test-Path -LiteralPath $WorkShortcut) {
        if ((Get-Item -LiteralPath $WorkShortcut).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Startup shortcut must not be a reparse point.' }
        $IsOriginal = $Backup.WorkShortcut.Exists -and ((Get-FileHash -LiteralPath $WorkShortcut -Algorithm SHA256).Hash -eq $Backup.WorkShortcut.SHA256)
        if (-not $IsOriginal) {
            $ExistingShell = New-Object -ComObject WScript.Shell
            $ExistingShortcut = $ExistingShell.CreateShortcut($WorkShortcut)
            $ExpectedArguments = (Quote-WindowsArgument $LauncherPath) + ' --config ' + (Quote-WindowsArgument $ConfigPath)
            if ($ExistingShortcut.TargetPath -ine $PythonExecutable -or $ExistingShortcut.Arguments -cne $ExpectedArguments -or $ExistingShortcut.Description -ne 'WorkStartup managed workspace launcher') { throw 'Work Startup.lnk changed after the first backup; it will not be overwritten.' }
        }
    }
    foreach ($FileName in @('start_workspace.py', 'config.json', 'install_startup.ps1', 'restore_startup.ps1', 'startup_policy.ps1')) {
        $Source = [IO.Path]::GetFullPath((Join-Path $SourceDirectory $FileName))
        $Destination = Join-Path $InstallDirectory $FileName
        if ((Test-Path -LiteralPath $Destination) -and ((Get-Item -LiteralPath $Destination).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Runtime destination must not be a reparse point: $FileName" }
        if ((Test-Path -LiteralPath $Source -PathType Leaf) -and $Source -ine $Destination) { Copy-Item -LiteralPath $Source -Destination $Destination -Force }
    }
    if (Test-Path -LiteralPath $OldShortcut -PathType Leaf) {
        if (-not $Backup.OldShortcut.Exists -or (Get-FileHash -LiteralPath $OldShortcut -Algorithm SHA256).Hash -ne $Backup.OldShortcut.SHA256) { throw 'Bitcoin Terminal.lnk changed after the original backup; it will not be removed.' }
        if (-not (Test-Path -LiteralPath $Backup.OldShortcut.BackupPath -PathType Leaf)) { throw 'The original Bitcoin shortcut backup is missing.' }
        if ((Get-FileHash -LiteralPath $Backup.OldShortcut.BackupPath -Algorithm SHA256).Hash -ne $Backup.OldShortcut.SHA256) { throw 'The original Bitcoin shortcut backup hash does not match.' }
        Remove-Item -LiteralPath $OldShortcut
    }
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($WorkShortcut)
    $Shortcut.TargetPath = $PythonExecutable
    $Shortcut.Arguments = (Quote-WindowsArgument $LauncherPath) + ' --config ' + (Quote-WindowsArgument $ConfigPath)
    $Shortcut.WorkingDirectory = $InstallDirectory
    $Shortcut.Description = 'WorkStartup managed workspace launcher'
    $Shortcut.WindowStyle = 7
    $Shortcut.Save()
    foreach ($Name in @('Steam', 'Feishu')) {
        $Key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($RunPath, $true)
        try { if ($null -ne $Key) { $Key.DeleteValue($Name, $false) } } finally { if ($null -ne $Key) { $Key.Dispose() } }
        $Key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($ApprovedPath)
        try {
            $Disabled = New-Object byte[] 12
            $Disabled[0] = 3
            [BitConverter]::GetBytes([DateTime]::UtcNow.ToFileTimeUtc()).CopyTo($Disabled, 4)
            $Key.SetValue($Name, $Disabled, [Microsoft.Win32.RegistryValueKind]::Binary)
        } finally { $Key.Dispose() }
    }
    & (Join-Path $InstallDirectory 'startup_policy.ps1') -Mode Install
    $VpnState = 'Skipped'
    if (-not $SkipVpnTask) { if ($IsAdministrator) { $VpnState = 'Pending' } else { $VpnState = 'RequiresAdministrator' } }
    Write-JsonFile $StatusPath ([pscustomobject]@{ Success = $true; State = 'Installed'; StartupShortcut = $WorkShortcut; DisabledRunNames = @('Steam', 'Feishu', 'Teams'); WorkspacePolicyStatus = (Join-Path $InstallDirectory 'startup-policy-status.json'); VpnTask = $VpnState; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
    Write-Output 'Workspace startup installed; Steam, Feishu and Teams automatic startup disabled.'
} catch {
    Write-JsonFile $StatusPath ([pscustomobject]@{ Success = $false; State = 'Failed'; Error = $_.Exception.Message; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
    throw
}

if (-not $SkipVpnTask -and $IsAdministrator) { Install-VpnTask }
elseif (-not $SkipVpnTask) { Write-Output 'VPN task still requires an elevated run with -VpnTaskOnly. No UAC prompt was opened.' }
