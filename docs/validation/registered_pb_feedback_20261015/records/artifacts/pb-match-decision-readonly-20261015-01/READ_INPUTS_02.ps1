$ErrorActionPreference = 'Stop'
$taskRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$taskAudit = Join-Path $taskRepo 'artifacts/pb-match-behavior-audit-20261014-01'
$taskInputs = [ordered]@{}
$taskChecks = @()
foreach ($taskName in @('pb2025_sentry_behavior', 'BehaviorTree.ROS2', 'pb_rm_interfaces_protocol_v1_7_0')) {
    $taskManifest = Join-Path $taskAudit ($taskName + '.FILES.json')
    if ($taskName -eq 'pb_rm_interfaces_protocol_v1_7_0') { $taskManifest = Join-Path $taskAudit 'pb_rm_interfaces_protocol.FILES.json' }
    $taskFiles = Get-Content -LiteralPath $taskManifest -Raw | ConvertFrom-Json
    $taskMismatch = @()
    foreach ($taskItem in $taskFiles.PSObject.Properties) {
        $taskPath = Join-Path (Join-Path $taskAudit $taskName) $taskItem.Name
        $taskDigest = (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $taskInputs[$taskPath] = $taskDigest
        if ($taskDigest -cne $taskItem.Value) { $taskMismatch += $taskItem.Name }
    }
    $taskChecks += [ordered]@{name=$taskName; prior_file_manifest=$taskManifest; files=@($taskFiles.PSObject.Properties).Count; mismatch=$taskMismatch; unchanged=($taskMismatch.Count -eq 0)}
}
$taskExtra = @(
'artifacts/pb-match-behavior-audit-20261014-01/AUDIT.md',
'artifacts/pb-match-behavior-audit-20261014-01/FINAL_AUDIT.json',
'artifacts/pb-match-behavior-audit-20261014-01/FETCH_RESULT.json',
'artifacts/pb-match-behavior-audit-20261014-01/BT_FETCH_RESULT.json',
'artifacts/pb-match-behavior-audit-20261014-01/PROTOCOL_FETCH_RESULT.json',
'artifacts/pb-match-behavior-audit-20261014-01/INTERFACE_REUSE_RESULT.json',
'artifacts/pb-match-behavior-audit-20261014-01/BehaviorTree.CPP/CMakeLists.txt',
'artifacts/pb-match-behavior-audit-20261014-01/BehaviorTree.CPP/cmake/ament_build.cmake',
'artifacts/pb-match-behavior-audit-20261014-01/pb2025_sentry_ws/src/pb2025_sentry_bringup/params/node_params.yaml',
'artifacts/pb-match-behavior-audit-20261014-01/pb2025_sentry_ws/src/pb2025_sentry_bringup/launch/bringup.launch.py',
'artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json',
'artifacts/pb2025-humble-environment-20261013/prefix/opt/ros/humble/share/behaviortree_cpp_v3/package.xml',
'artifacts/registered-pb-goal-actual-20261015-03/RESULT.json',
'rm_match/platform_v2/decision_contracts.py',
'rm_match/platform_v2/navigation_feedback_contracts.py',
'rm_match/integrations/pb_goal_plugin_peer.py',
'rm_match/integrations/goal_navigation_compute.py',
'rm_match/integrations/navigation_goal_lifecycle.py',
'tools/pb_navigation_stack.py')
foreach ($taskName in $taskExtra) {
    $taskPath = Join-Path $taskRepo $taskName
    $taskInputs[$taskPath] = (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
$taskPrefix = Join-Path $taskRepo 'artifacts/pb2025-humble-environment-20261013/prefix/opt/ros/humble/share/ament_index/resource_index/packages'
$taskPackages = @(Get-ChildItem -LiteralPath $taskPrefix -Name | Sort-Object)
[ordered]@{schema='polar.pb-match-decision-readonly-inputs.v1'; scope='read_and_hash_existing_files_only_no_build_ros_or_test'; paths=$taskInputs} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'INPUTS.json') -Encoding utf8NoBOM
$taskChecks | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'SOURCE_CHECKS.json') -Encoding utf8NoBOM
$taskPackages | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'PREFIX_PACKAGE_INDEX.txt') -Encoding utf8NoBOM
[ordered]@{input_files=$taskInputs.Count; original_sources_unchanged=(@($taskChecks | Where-Object { -not $_.unchanged }).Count -eq 0); package_index_entries=$taskPackages.Count; read_only=$true} | ConvertTo-Json
