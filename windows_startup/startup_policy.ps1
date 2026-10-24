[CmdletBinding()]
param([ValidateSet('Install', 'Status', 'Restore', 'Library')][string]$Mode = 'Status')

$ErrorActionPreference = 'Stop'
$PolicyDirectory = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'WorkStartup'))
$PolicyBackup = Join-Path $PolicyDirectory 'startup-policy-backup.json'
$PolicyStatus = Join-Path $PolicyDirectory 'startup-policy-status.json'
$PolicyOwner = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$WorkspaceTaskName = 'WorkStartup - Workspace'
$WorkspaceRunName = 'WorkStartup Workspace'
$WorkspaceMarker = 'WorkStartup.Workspace.v2;OwnerSid=' + $PolicyOwner
$WorkspacePython = 'C:\Users\yxh\AppData\Local\Programs\Python\Python39\pythonw.exe'
$WorkspaceScript = Join-Path $PolicyDirectory 'start_workspace.py'
$WorkspaceArguments = '"' + $WorkspaceScript + '" --config "' + (Join-Path $PolicyDirectory 'config.json') + '"'
$WorkspaceCommand = '"' + $WorkspacePython + '" ' + $WorkspaceArguments
$PolicyRun = 'Software\Microsoft\Windows\CurrentVersion\Run'
$PolicyApproved = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'
$TeamsStartup = 'Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData\MSTeams_8wekyb3d8bbwe\TeamsTfwStartupTask'

function Get-PolicyTargets {
    foreach ($View in @('Registry64', 'Registry32')) {
        foreach ($Name in @('Steam', 'Feishu', 'Teams')) {
            foreach ($Path in @($PolicyRun, ($PolicyApproved + '\Run'), ($PolicyApproved + '\Run32'))) {
                [pscustomobject]@{ View = $View; Path = $Path; Name = $Name; Action = $(if ($Path -eq $PolicyRun) { 'Remove' } else { 'Disable' }) }
            }
        }
    }
    [pscustomobject]@{ View = 'Registry64'; Path = $PolicyRun; Name = $WorkspaceRunName; Action = 'Launch' }
    [pscustomobject]@{ View = 'Registry64'; Path = ($PolicyApproved + '\Run'); Name = $WorkspaceRunName; Action = 'Enable' }
    [pscustomobject]@{ View = 'Registry64'; Path = ($PolicyApproved + '\StartupFolder'); Name = 'Work Startup.lnk'; Action = 'Enable' }
    [pscustomobject]@{ View = 'Registry64'; Path = $TeamsStartup; Name = 'State'; Action = 'PackageDisable' }
    [pscustomobject]@{ View = 'Registry64'; Path = $TeamsStartup; Name = 'UserEnabledStartupOnce'; Action = 'PackageDisable' }
}

function Get-PolicyRegistry($Spec) {
    $Hive = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::$($Spec.View))
    $Key = $null
    try {
        $Key = $Hive.OpenSubKey([string]$Spec.Path, $false)
        $Exists = $null -ne $Key -and $Key.GetValueNames() -contains [string]$Spec.Name
        $Value = $null; $Kind = $null
        if ($Exists) {
            $Kind = [string]$Key.GetValueKind([string]$Spec.Name)
            $Value = $Key.GetValue([string]$Spec.Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            if ($Kind -eq 'Binary') { $Value = [Convert]::ToBase64String([byte[]]$Value) }
        }
        [pscustomobject]@{ View = $Spec.View; Path = $Spec.Path; Name = $Spec.Name; KeyExists = ($null -ne $Key); Exists = $Exists; Kind = $Kind; Value = $Value }
    } finally { if ($null -ne $Key) { $Key.Dispose() }; $Hive.Dispose() }
}

function Set-PolicyRegistry($Spec, $Value, [string]$Kind = 'Binary', [switch]$Remove) {
    $Hive = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::$($Spec.View))
    $Key = $null
    try {
        if ($Remove) {
            $Key = $Hive.OpenSubKey([string]$Spec.Path, $true)
            if ($null -ne $Key) { $Key.DeleteValue([string]$Spec.Name, $false) }
        } else {
            $Key = $Hive.CreateSubKey([string]$Spec.Path)
            $Key.SetValue([string]$Spec.Name, $Value, [Microsoft.Win32.RegistryValueKind]::$Kind)
        }
    } finally { if ($null -ne $Key) { $Key.Dispose() }; $Hive.Dispose() }
}

function Write-PolicyJson([string]$Path, $Value) {
    if ([IO.Path]::GetFullPath($Path) -notin @($PolicyBackup, $PolicyStatus)) { throw 'Unexpected policy output path.' }
    $Temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Temporary -Encoding UTF8
        Move-Item -LiteralPath $Temporary -Destination $Path -Force
    } finally { if (Test-Path -LiteralPath $Temporary) { Remove-Item -LiteralPath $Temporary -Force } }
}

function Test-WorkspaceTask($Task) {
    if ($null -eq $Task -or $Task.Description -cne $WorkspaceMarker) { return $false }
    $Actions = @($Task.Actions)
    $UserSid = [string]$Task.Principal.UserId
    if ($UserSid -notmatch '^S-1-') {
        try { $UserSid = (New-Object Security.Principal.NTAccount($UserSid)).Translate([Security.Principal.SecurityIdentifier]).Value }
        catch { return $false }
    }
    return ($Actions.Count -eq 1 -and $Actions[0].Execute -ieq $WorkspacePython -and
        $Actions[0].Arguments -ceq $WorkspaceArguments -and $UserSid -eq $PolicyOwner -and
        [string]$Task.Principal.RunLevel -in @('Limited', '0'))
}

function Get-WorkspaceTask {
    $script:WorkspaceTaskQueryError = $null
    try { Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -ieq $WorkspaceTaskName } }
    catch { $script:WorkspaceTaskQueryError = $_.Exception.Message; return $null }
}

function Get-PolicyStatus {
    $Entries = @(foreach ($Target in @(Get-PolicyTargets)) { Get-PolicyRegistry $Target })
    $Task = Get-WorkspaceTask
    [pscustomobject]@{ Version = 2; OwnerSid = $PolicyOwner; WorkspaceTaskInstalled = (Test-WorkspaceTask $Task);
        WorkspaceTaskEnabled = ($null -ne $Task -and $Task.Settings.Enabled); WorkspaceTaskName = $WorkspaceTaskName;
        WorkspaceTaskQueryError = $script:WorkspaceTaskQueryError; Registry = $Entries; UpdatedUtc = [DateTime]::UtcNow.ToString('o') }
}

if ($Mode -eq 'Library') { return }
if (-not (Test-Path -LiteralPath $PolicyDirectory -PathType Container) -or
    (Get-Item -LiteralPath $PolicyDirectory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Policy directory is missing or is a reparse point.' }
if ($Mode -eq 'Status') { Get-PolicyStatus | ConvertTo-Json -Depth 20; return }

$Targets = @(Get-PolicyTargets)
$Task = Get-WorkspaceTask
$TaskLookupFailure = $script:WorkspaceTaskQueryError
if ($null -ne $Task -and -not (Test-WorkspaceTask $Task)) { throw 'Workspace task belongs to another application; it will not be changed.' }

if ($Mode -eq 'Restore') {
    if ($TaskLookupFailure) { throw ('Cannot safely inspect the workspace task for restoration: ' + $TaskLookupFailure) }
    if (-not (Test-Path -LiteralPath $PolicyBackup -PathType Leaf)) { Write-Output 'No policy backup exists.'; return }
    $Saved = Get-Content -LiteralPath $PolicyBackup -Raw | ConvertFrom-Json
    if ($Saved.Version -ne 2 -or $Saved.OwnerSid -ne $PolicyOwner -or $Saved.TaskName -cne $WorkspaceTaskName) { throw 'Policy backup ownership does not match.' }
    foreach ($Entry in @($Saved.Registry)) {
        if (-not ($Targets | Where-Object { $_.View -ceq $Entry.View -and $_.Path -ceq $Entry.Path -and $_.Name -ceq $Entry.Name })) { throw 'Unexpected registry target in policy backup.' }
    }
    if ($Saved.TaskCaptured -ne $false) {
        if ($null -ne $Task) { Unregister-ScheduledTask -TaskName $WorkspaceTaskName -TaskPath '\' -Confirm:$false }
        if ($Saved.TaskExists) { Register-ScheduledTask -TaskName $WorkspaceTaskName -TaskPath '\' -Xml ([string]$Saved.TaskXml) -Force | Out-Null }
    }
    foreach ($Entry in @($Saved.Registry)) {
        if (-not $Entry.Exists) { Set-PolicyRegistry $Entry $null -Remove; continue }
        $Value = $Entry.Value
        switch ([string]$Entry.Kind) {
            'Binary' { $Value = [Convert]::FromBase64String([string]$Value) }
            'DWord' { $Value = [int]$Value }
            'QWord' { $Value = [long]$Value }
            'String' { $Value = [string]$Value }
            'ExpandString' { $Value = [string]$Value }
            'MultiString' { $Value = [string[]]$Value }
            default { throw 'Unexpected registry type in policy backup.' }
        }
        Set-PolicyRegistry $Entry $Value ([string]$Entry.Kind)
    }
    Write-PolicyJson $PolicyStatus ([pscustomobject]@{ Success = $true; State = 'Restored'; UpdatedUtc = [DateTime]::UtcNow.ToString('o') })
    Write-Output 'Workspace login triggers and Teams startup settings restored.'
    return
}

foreach ($Required in @($WorkspacePython, $WorkspaceScript, (Join-Path $PolicyDirectory 'config.json'))) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) { throw 'Required workspace runtime file is missing.' }
}
$ExistingRun = Get-PolicyRegistry ($Targets | Where-Object { $_.Action -eq 'Launch' })
if ($ExistingRun.Exists -and $ExistingRun.Value -cne $WorkspaceCommand) { throw 'Workspace Run entry is unrelated; it will not be changed.' }
if (-not (Test-Path -LiteralPath $PolicyBackup)) {
    $Snapshots = @(foreach ($Target in $Targets) { Get-PolicyRegistry $Target })
    $TaskXml = $null
    if ($null -ne $Task) { $TaskXml = Export-ScheduledTask -TaskName $WorkspaceTaskName -TaskPath '\' }
    Write-PolicyJson $PolicyBackup ([pscustomobject]@{ Version = 2; OwnerSid = $PolicyOwner; TaskName = $WorkspaceTaskName;
        TaskCaptured = (-not [bool]$TaskLookupFailure); TaskExists = ($null -ne $Task); TaskXml = $TaskXml; Registry = $Snapshots; CreatedUtc = [DateTime]::UtcNow.ToString('o') })
} else {
    $Saved = Get-Content -LiteralPath $PolicyBackup -Raw | ConvertFrom-Json
    if ($Saved.Version -ne 2 -or $Saved.OwnerSid -ne $PolicyOwner -or $Saved.TaskName -cne $WorkspaceTaskName) { throw 'Policy backup ownership does not match.' }
}
$Disabled = New-Object byte[] 12; $Disabled[0] = 3
[BitConverter]::GetBytes([DateTime]::UtcNow.ToFileTimeUtc()).CopyTo($Disabled, 4)
$Enabled = New-Object byte[] 12; $Enabled[0] = 2
foreach ($Target in $Targets) {
    switch ($Target.Action) {
        'Remove' { Set-PolicyRegistry $Target $null -Remove }
        'Disable' { Set-PolicyRegistry $Target $Disabled }
        'Enable' { Set-PolicyRegistry $Target $Enabled }
        'Launch' { Set-PolicyRegistry $Target $WorkspaceCommand 'String' }
        'PackageDisable' {
            if ((Get-PolicyRegistry $Target).KeyExists) {
                $State = 0; if ($Target.Name -eq 'State') { $State = 1 }
                Set-PolicyRegistry $Target $State 'DWord'
            }
        }
    }
}
$TaskError = $null
try {
    if ($TaskLookupFailure) { throw ('Task inspection unavailable; preserving task definitions: ' + $TaskLookupFailure) }
    $Action = New-ScheduledTaskAction -Execute $WorkspacePython -Argument $WorkspaceArguments -WorkingDirectory $PolicyDirectory
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $PolicyOwner; $Trigger.Delay = 'PT10S'
    $Principal = New-ScheduledTaskPrincipal -UserId $PolicyOwner -LogonType Interactive -RunLevel Limited
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $Definition = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $WorkspaceMarker
    Register-ScheduledTask -TaskName $WorkspaceTaskName -TaskPath '\' -InputObject $Definition -Force | Out-Null
    if (-not (Test-WorkspaceTask (Get-WorkspaceTask))) { throw 'Workspace scheduled task verification failed.' }
} catch { $TaskError = $_.Exception.Message }
$Status = Get-PolicyStatus
$Status | Add-Member -NotePropertyName Success -NotePropertyValue $true
$Status | Add-Member -NotePropertyName State -NotePropertyValue 'Installed'
$Status | Add-Member -NotePropertyName WorkspaceTaskError -NotePropertyValue $TaskError
Write-PolicyJson $PolicyStatus $Status
if ($TaskError) { Write-Output ('Workspace Run fallback installed; scheduled task unavailable: ' + $TaskError) }
else { Write-Output 'Workspace login task and Run fallback installed; Steam, Feishu and Teams startup disabled.' }
