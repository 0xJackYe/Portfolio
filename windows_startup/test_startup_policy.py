"""Offline policy tests: load Library mode and replace all task/registry I/O."""
import base64
import json
import os
from pathlib import Path
import subprocess
import unittest


POLICY = Path(__file__).with_name("startup_policy.ps1").resolve()
FAKE_TASK = r'''
function New-FakeTask {
    [pscustomobject]@{
        TaskName = $WorkspaceTaskName
        Description = $WorkspaceMarker
        Actions = @([pscustomobject]@{Execute = $WorkspacePython; Arguments = $WorkspaceArguments})
        Principal = [pscustomobject]@{UserId = $PolicyOwner; RunLevel = 'Limited'}
        Settings = [pscustomobject]@{Enabled = $true}
    }
}
'''


@unittest.skipUnless(os.name == "nt", "Windows policy helpers")
class StartupPolicyTests(unittest.TestCase):
    def policy(self, body):
        # Library mode defines functions only: no installer branch, task request,
        # registry mutation or application is executed by these tests.
        script = ("$ErrorActionPreference = 'Stop'\n"
                  "[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)\n"
                  ". '" + str(POLICY).replace("'", "''") + "' -Mode Library\n"
                  + FAKE_TASK + "\n" + body)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8-sig", errors="replace", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout.strip())

    def test_owned_task_and_numeric_limited_principal_are_accepted(self):
        result = self.policy(r'''
$task = New-FakeTask
$named = Test-WorkspaceTask $task
$task.Principal.RunLevel = '0'
[pscustomobject]@{NamedLimited = $named; NumericLimited = (Test-WorkspaceTask $task); NullTask = (Test-WorkspaceTask $null)} | ConvertTo-Json -Compress
''')
        self.assertEqual(result, {"NamedLimited": True, "NumericLimited": True, "NullTask": False})

    def test_wrong_owner_or_changed_description_is_never_owned(self):
        result = self.policy(r'''
$task = New-FakeTask
$task.Principal.UserId = 'S-1-5-21-999999999-999999999-999999999-1001'
$ownerResult = Test-WorkspaceTask $task
$task = New-FakeTask
$task.Description = $WorkspaceMarker + ';changed'
$descriptionResult = Test-WorkspaceTask $task
$task.Description = $WorkspaceMarker.ToLowerInvariant()
[pscustomobject]@{OtherOwner = $ownerResult; OtherDescription = $descriptionResult; ChangedCase = (Test-WorkspaceTask $task)} | ConvertTo-Json -Compress
''')
        self.assertEqual(result, {"OtherOwner": False, "OtherDescription": False, "ChangedCase": False})

    def test_executable_case_is_insensitive_but_arguments_are_exact(self):
        result = self.policy(r'''
$task = New-FakeTask
$task.Actions[0].Execute = $WorkspacePython.ToUpperInvariant()
$caseResult = Test-WorkspaceTask $task
$task.Actions[0].Arguments = $WorkspaceArguments + ' --unexpected'
$extraResult = Test-WorkspaceTask $task
$task = New-FakeTask
$task.Actions[0].Execute = 'C:\Other\pythonw.exe'
[pscustomobject]@{CaseOnly = $caseResult; ExtraArguments = $extraResult; OtherExecutable = (Test-WorkspaceTask $task)} | ConvertTo-Json -Compress
''')
        self.assertEqual(result, {"CaseOnly": True, "ExtraArguments": False, "OtherExecutable": False})

    def test_zero_or_multiple_actions_prevent_task_replacement(self):
        result = self.policy(r'''
$task = New-FakeTask
$task.Actions = @()
$empty = Test-WorkspaceTask $task
$task = New-FakeTask
$task.Actions = @($task.Actions[0], [pscustomobject]@{Execute = $WorkspacePython; Arguments = $WorkspaceArguments})
[pscustomobject]@{NoActions = $empty; MultipleActions = (Test-WorkspaceTask $task)} | ConvertTo-Json -Compress
''')
        self.assertEqual(result, {"NoActions": False, "MultipleActions": False})

    def test_elevated_or_missing_runlevel_is_not_an_owned_workspace_task(self):
        result = self.policy(r'''
$results = foreach ($level in @('Highest', '1', '', 'Administrator')) {
    $task = New-FakeTask
    $task.Principal.RunLevel = $level
    [bool](Test-WorkspaceTask $task)
}
[pscustomobject]@{Results = @($results)} | ConvertTo-Json -Compress
''')
        self.assertEqual(result["Results"], [False, False, False, False])

    def test_current_account_name_resolves_to_the_expected_sid(self):
        result = self.policy(r'''
$task = New-FakeTask
$task.Principal.UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
[pscustomobject]@{AccountName = (Test-WorkspaceTask $task)} | ConvertTo-Json -Compress
''')
        self.assertTrue(result["AccountName"])

    def test_task_lookup_is_case_insensitive_and_does_not_match_other_names(self):
        result = self.policy(r'''
function Get-ScheduledTask {
    [CmdletBinding()]param([string]$TaskPath)
    if ($TaskPath -ne '\') { throw 'Unexpected task path.' }
    $owned = New-FakeTask
    $owned.TaskName = $WorkspaceTaskName.ToUpperInvariant()
    $other = New-FakeTask
    $other.TaskName = $WorkspaceTaskName + ' Other'
    $other
    $owned
}
$tasks = @(Get-WorkspaceTask)
[pscustomobject]@{Count = $tasks.Count; Name = $tasks[0].TaskName; Owned = (Test-WorkspaceTask $tasks[0]); QueryError = $script:WorkspaceTaskQueryError} | ConvertTo-Json -Compress
''')
        self.assertEqual(result["Count"], 1)
        self.assertEqual(result["Name"], "WORKSTARTUP - WORKSPACE")
        self.assertTrue(result["Owned"])
        self.assertIsNone(result["QueryError"])

    def test_failed_task_query_is_reported_and_a_later_query_clears_the_error(self):
        result = self.policy(r'''
function Get-ScheduledTask { [CmdletBinding()]param([string]$TaskPath) throw 'Task inspection denied.' }
$missing = Get-WorkspaceTask
$errorText = $script:WorkspaceTaskQueryError
function Get-ScheduledTask { [CmdletBinding()]param([string]$TaskPath) New-FakeTask }
$later = Get-WorkspaceTask
[pscustomobject]@{Missing = ($null -eq $missing); FirstError = $errorText; LaterOwned = (Test-WorkspaceTask $later); LaterError = $script:WorkspaceTaskQueryError} | ConvertTo-Json -Compress
''')
        self.assertTrue(result["Missing"])
        self.assertIn("Task inspection denied", result["FirstError"])
        self.assertTrue(result["LaterOwned"])
        self.assertIsNone(result["LaterError"])

    def test_registry_targets_cover_only_named_apps_in_both_views_and_exact_package(self):
        result = self.policy(r'''
[pscustomobject]@{Targets = @(Get-PolicyTargets)} | ConvertTo-Json -Depth 8 -Compress
''')
        targets = result["Targets"]
        run = r"Software\Microsoft\Windows\CurrentVersion\Run"
        approved = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
        package = (r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
                   r"\AppModel\SystemAppData\MSTeams_8wekyb3d8bbwe\TeamsTfwStartupTask")
        expected = {(view, path, name, action)
                    for view in ("Registry64", "Registry32")
                    for name in ("Steam", "Feishu", "Teams")
                    for path, action in ((run, "Remove"), (approved + r"\Run", "Disable"),
                                         (approved + r"\Run32", "Disable"))}
        expected.update({("Registry64", run, "WorkStartup Workspace", "Launch"),
                         ("Registry64", approved + r"\Run", "WorkStartup Workspace", "Enable"),
                         ("Registry64", approved + r"\StartupFolder", "Work Startup.lnk", "Enable"),
                         ("Registry64", package, "State", "PackageDisable"),
                         ("Registry64", package, "UserEnabledStartupOnce", "PackageDisable")})
        actual = {(t["View"], t["Path"], t["Name"], t["Action"]) for t in targets}
        self.assertEqual(actual, expected)
        self.assertEqual(len(targets), len(expected), "no duplicate or unrelated startup targets")
        self.assertTrue(all("*" not in t["Path"] and "*" not in t["Name"] for t in targets))

    def test_json_output_rejects_outside_and_unapproved_paths_before_any_io(self):
        result = self.policy(r'''
$script:Writes = 0
function Set-Content { param($LiteralPath, $Encoding) $script:Writes++; throw 'Unexpected disk write.' }
function Move-Item { param($LiteralPath, $Destination, [switch]$Force) $script:Writes++; throw 'Unexpected disk move.' }
$rejected = foreach ($path in @((Join-Path $env:TEMP 'unrelated-policy.json'), ($PolicyDirectory + '\..\startup-policy-status.json'), ($PolicyDirectory + '_other\startup-policy-status.json'), ($PolicyDirectory + '\unrelated.json'))) {
    try { Write-PolicyJson $path @{Test = $true}; $false }
    catch { $_.Exception.Message -eq 'Unexpected policy output path.' }
}
[pscustomobject]@{Rejected = @($rejected); Writes = $script:Writes} | ConvertTo-Json -Compress
''')
        self.assertEqual(result["Rejected"], [True, True, True, True])
        self.assertEqual(result["Writes"], 0)

    def test_approved_json_output_is_written_atomically_using_only_approved_destination(self):
        result = self.policy(r'''
$script:Writes = @()
$script:Moves = @()
function Set-Content {
    [CmdletBinding()]param([string]$LiteralPath, [string]$Encoding, [Parameter(ValueFromPipeline = $true)]$Value)
    process { $script:Writes += [pscustomobject]@{Path = $LiteralPath; Encoding = $Encoding; Data = $Value} }
}
function Move-Item { param([string]$LiteralPath, [string]$Destination, [switch]$Force) $script:Moves += [pscustomobject]@{Source = $LiteralPath; Destination = $Destination; Force = [bool]$Force} }
function Test-Path { param([string]$LiteralPath) return $false }
Write-PolicyJson $PolicyStatus @{Test = 37; Nested = @{Value = 'kept'}}
[pscustomobject]@{Writes = @($script:Writes); Moves = @($script:Moves); Allowed = $PolicyStatus} | ConvertTo-Json -Depth 8 -Compress
''')
        self.assertEqual(len(result["Writes"]), 1)
        self.assertEqual(len(result["Moves"]), 1)
        write, move = result["Writes"][0], result["Moves"][0]
        self.assertEqual(move["Destination"], result["Allowed"])
        self.assertEqual(move["Source"], write["Path"])
        self.assertTrue(write["Path"].startswith(result["Allowed"] + "."))
        self.assertTrue(write["Path"].endswith(".tmp"))
        self.assertTrue(move["Force"])
        self.assertEqual(json.loads(write["Data"]), {"Test": 37, "Nested": {"Value": "kept"}})

    def test_status_reads_only_enumerated_targets_and_distinguishes_owned_disabled_task(self):
        result = self.policy(r'''
$script:Reads = @()
function Get-PolicyRegistry($Spec) {
    $script:Reads += $Spec
    [pscustomobject]@{View = $Spec.View; Path = $Spec.Path; Name = $Spec.Name; KeyExists = $true; Exists = $true; Kind = 'String'; Value = 'fixture'}
}
function Get-ScheduledTask {
    [CmdletBinding()]param([string]$TaskPath)
    $task = New-FakeTask
    $task.Settings.Enabled = $false
    $task
}
$status = Get-PolicyStatus
[pscustomobject]@{Status = $status; Reads = @($script:Reads); Targets = @(Get-PolicyTargets)} | ConvertTo-Json -Depth 10 -Compress
''')
        self.assertEqual(result["Reads"], result["Targets"])
        self.assertEqual(len(result["Status"]["Registry"]), 23)
        self.assertTrue(result["Status"]["WorkspaceTaskInstalled"])
        self.assertFalse(result["Status"]["WorkspaceTaskEnabled"])
        self.assertIsNone(result["Status"]["WorkspaceTaskQueryError"])


if __name__ == "__main__":
    unittest.main()
