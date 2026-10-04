param(
    [ValidateSet('Install', 'Enable', 'Disable', 'Remove', 'Status')]
    [string]$Action = 'Status',
    [switch]$Staged
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$taskName = 'LabModelMonitor-Daily'
if ($Action -eq 'Install') {
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Independent Python environment is missing.' }
    $settings = Get-Content -LiteralPath (Join-Path $projectRoot 'runtime\settings.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($settings.timezone -ne 'Asia/Taipei') { throw 'Expected Asia/Taipei timezone.' }
    if ([int]([TimeZoneInfo]::Local.GetUtcOffset([datetime]::Now).TotalMinutes) -ne 480) { throw 'Windows clock must use UTC+8 for this daily schedule.' }
    if (-not $Staged) {
        $preflight = & $pythonPath -m lab_model_monitor status | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or -not ($preflight.credentials.api -and $preflight.credentials.site -and $preflight.credentials.feishu)) { throw 'Required independent credentials are missing.' }
    }
    $launcherDir = Join-Path $projectRoot 'runtime\scheduler'
    New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
    $launcherPath = Join-Path $launcherDir 'run_daily.vbs'
    $scriptPath = Join-Path $projectRoot 'scripts\run_daily.py'
    $vbs = @"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "$($projectRoot.Replace('"', '""'))"
exitCode = shell.Run(Chr(34) & "$($pythonPath.Replace('"', '""'))" & Chr(34) & " " & Chr(34) & "$($scriptPath.Replace('"', '""'))" & Chr(34), 0, True)
WScript.Quit exitCode
"@
    [IO.File]::WriteAllText($launcherPath, $vbs, [Text.Encoding]::Unicode)
    $taskAction = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wscript.exe" -Argument "//B //Nologo `"$launcherPath`"" -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $settings.schedule.daily_time
    $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Settings $taskSettings -Principal $principal -Description 'Independent daily laboratory relay candy-puzzle monitoring' -Force | Out-Null
    if ($Staged) { Disable-ScheduledTask -TaskName $taskName | Out-Null }
} elseif ($Action -eq 'Remove') {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
} elseif ($Action -eq 'Enable') {
    $preflight = & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m lab_model_monitor status | ConvertFrom-Json
    if (-not ($preflight.success -and $preflight.credentials.api -and $preflight.credentials.site -and $preflight.credentials.feishu)) { throw 'Required independent credentials are missing.' }
    Enable-ScheduledTask -TaskName $taskName | Out-Null
} elseif ($Action -eq 'Disable') {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
}
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    [pscustomobject]@{ task_name = $taskName; state = [string]$task.State; next_run = $info.NextRunTime.ToString('s'); last_result = $info.LastTaskResult; hidden_launcher = $task.Actions.Arguments; working_directory = $task.Actions.WorkingDirectory } | ConvertTo-Json
} else {
    [pscustomobject]@{ task_name = $taskName; state = 'not_installed' } | ConvertTo-Json
}
