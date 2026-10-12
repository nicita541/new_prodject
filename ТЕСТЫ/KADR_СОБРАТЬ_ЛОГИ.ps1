param([string]$ProjectRoot = 'F:\new_prodject')
$ErrorActionPreference = 'Stop'

function Read-SafeJson([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}
function Save-Json([string]$Filename, $Data) {
    $path = Join-Path $out $Filename
    ConvertTo-Json -InputObject $Data -Depth 18 | Set-Content -LiteralPath $path -Encoding UTF8
}
function Count-Files([string]$Path, [string]$Filter = '*.json') {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return 0 }
    return @(Get-ChildItem -LiteralPath $Path -Filter $Filter -File -ErrorAction SilentlyContinue).Count
}
function Num($Value) {
    if ($null -eq $Value) { return $null }
    try { return [math]::Round([double]$Value, 4) } catch { return $null }
}
function Safe-Why($Value) {
    if ($null -eq $Value) { return $null }
    $s = [string]$Value
    # Warnings can contain source names, user folders, provider details or secrets.
    $s = $s -replace '(?i)(gh[pousr]_|github_pat_|sk-)[a-z0-9_\-]{10,}', '[SECRET]'
    $s = $s -replace '(?i)(Bearer\s+)\S+', '$1[SECRET]'
    $s = $s -replace '(?i)[a-z]:\\[^\s"\r\n]+', '[LOCAL_PATH]'
    if ($s.Length -gt 180) { $s = $s.Substring(0, 180) }
    return $s
}

$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$reportRoot = Join-Path $root 'temp\verification-reports'
$run = Get-ChildItem -LiteralPath $reportRoot -Directory -ErrorAction Stop |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'real_model_3min\real-job') -PathType Container } |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $run) { throw 'Не найден запуск real_model_3min. Ничего не изменено.' }
$job = Join-Path $run.FullName 'real_model_3min\real-job'
$out = Join-Path (Join-Path $root 'temp') ('KADR_DIAGNOSTICS_' + $run.Name + '_' + (Get-Date -Format yyyyMMdd_HHmmss))
New-Item -ItemType Directory -Force -Path $out | Out-Null

$probe = Read-SafeJson (Join-Path $job 'probe.json')
$scenes = @(Read-SafeJson (Join-Path $job 'scenes.json')) | Where-Object { $null -ne $_ }
$shots = @(Read-SafeJson (Join-Path $job 'shots.json')) | Where-Object { $null -ne $_ }
$events = @(Read-SafeJson (Join-Path $job 'events.json')) | Where-Object { $null -ne $_ }
$visual = Join-Path $job 'visual'
$screen = Join-Path $job 'title_units'
$modelDir = Join-Path $job 'actual-model'
$pipelineDir = Join-Path $job 'diagnostics\pipeline'
$summary = Read-SafeJson (Join-Path $pipelineDir 'summary.json')
$timings = Read-SafeJson (Join-Path $job 'timings.json')
$observed = Read-SafeJson (Join-Path $job 'observed-outcome.json')
$e2e = Read-SafeJson (Join-Path $run.FullName 'real_model_3min\report.json')

$rows = @()
foreach ($scene in $scenes) {
    if ($null -eq $scene.start -or $null -eq $scene.end) { continue }
    $rows += [pscustomobject]@{
        id = $scene.id
        start = Num $scene.start
        end = Num $scene.end
        duration = Num ([double]$scene.end - [double]$scene.start)
        shot_count = @($scene.shot_ids | Where-Object { $null -ne $_ }).Count
        candidate_count = @($scene.candidate_ids | Where-Object { $null -ne $_ }).Count
        confidence = Num $scene.confidence
        uncertain = $scene.uncertain
        boundary_reason = Safe-Why ((@($scene.boundary_reason) -join ','))
    }
}
$rows | Export-Csv -LiteralPath (Join-Path $out 'scene_boundaries.csv') -NoTypeInformation -Encoding UTF8

$eventRows = @()
foreach ($event in $events) {
    if ($null -eq $event.start -or $null -eq $event.end) { continue }
    $eventRows += [pscustomobject]@{
        id = $event.id
        scene_id = $event.scene_id
        start = Num $event.start
        end = Num $event.end
        duration = Num ([double]$event.end - [double]$event.start)
        chunks = @($event.analysis_chunks | Where-Object { $null -ne $_ }).Count
        units = @($event.units | Where-Object { $null -ne $_ }).Count
        uncertain = $event.uncertain
    }
}
$eventRows | Export-Csv -LiteralPath (Join-Path $out 'events_metadata.csv') -NoTypeInformation -Encoding UTF8

$requests = @(Get-ChildItem -LiteralPath $modelDir -Filter 'request-*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name)
$responses = @(Get-ChildItem -LiteralPath $modelDir -Filter 'response-*.json' -File -ErrorAction SilentlyContinue)
$callRows = @()
foreach ($request in $requests) {
    $id = $request.BaseName.Substring('request-'.Length)
    $q = Read-SafeJson $request.FullName
    $answerFile = Join-Path $modelDir ('response-' + $id + '.json')
    $a = Read-SafeJson $answerFile
    $kind = 'other'
    $prompt = if ($null -ne $q) { [string]$q.prompt } else { '' }
    if ($prompt -match 'Look ONLY at these CURRENT frames.*(?:studio|distributor)|visible_production_title') { $kind = 'title_screen' }
    elseif ($prompt -match 'Condense the central story|Condense this episode') { $kind = 'story_condense' }
    elseif ($prompt -match '(?i)title|bumper|credits|production.sequence') { $kind = 'credits_titles' }
    elseif ($prompt -match '(?i)source role|preview|dubbing commentary') { $kind = 'source_roles' }
    elseif ($prompt -match '(?i)scene|CURRENT SCENE|story unit') { $kind = 'scene_story' }
    $callRows += [pscustomobject]@{
        request_id = $id
        class = $kind
        requested_at = $request.LastWriteTime.ToString('s')
        response_status = if (-not (Test-Path -LiteralPath $answerFile)) { 'NO_RESPONSE' } elseif ($null -eq $a) { 'UNREADABLE' } elseif ($a.error_type) { 'ERROR' } else { 'OK' }
        error_type = if ($a) { Safe-Why $a.error_type } else { '' }
        elapsed_seconds = if ($a) { Num $a.elapsed_seconds } else { $null }
        prompt_characters = $prompt.Length
        image_pages = if ($q) { @($q.images | Where-Object { $null -ne $_ }).Count } else { 0 }
        max_tokens = if ($q) { $q.max_tokens } else { $null }
        thinking = if ($q) { $q.thinking } else { $null }
    }
}
$callRows | Export-Csv -LiteralPath (Join-Path $out 'model_calls_metadata.csv') -NoTypeInformation -Encoding UTF8

$progressFile = Join-Path $job 'observed-progress.jsonl'
$progressRows = @()
if (Test-Path -LiteralPath $progressFile) {
    foreach ($line in (Get-Content -LiteralPath $progressFile -Encoding UTF8 -Tail 1200)) {
        try {
            $p = $line | ConvertFrom-Json
            $progressRows += [pscustomobject]@{ stage = $p.stage; progress = Num $p.progress; message = Safe-Why $p.message }
        } catch { }
    }
}
$progressRows | Export-Csv -LiteralPath (Join-Path $out 'progress_last_1200.csv') -NoTypeInformation -Encoding UTF8

$timelineFile = Join-Path $pipelineDir 'timeline.jsonl'
$timeline = @()
if (Test-Path -LiteralPath $timelineFile) {
    foreach ($line in (Get-Content -LiteralPath $timelineFile -Encoding UTF8 -Tail 2500)) {
        try {
            $e = $line | ConvertFrom-Json
            $timeline += [pscustomobject]@{
                time = $e.time; stage = $e.stage; action = $e.action
                elapsed_seconds = Num $e.elapsed_seconds
                scene_id = $e.scene_id; event_id = $e.event_id; attempt = $e.attempt
                error_type = Safe-Why $e.error_type
            }
        } catch { }
    }
}
$timeline | Export-Csv -LiteralPath (Join-Path $out 'pipeline_timeline.csv') -NoTypeInformation -Encoding UTF8

$metrics = [ordered]@{}
if ($summary) {
    foreach ($prop in $summary.PSObject.Properties) {
        if ($prop.Name -match '^(source_duration|shots|semantic_scenes|story_events|uncertain_|duration_after_|globally_omitted|global_corrections|narrative_bridges)' -and $prop.Value -is [ValueType]) {
            $metrics[$prop.Name] = $prop.Value
        }
    }
}
$diag = [ordered]@{
    generated_at = (Get-Date).ToString('o')
    run_id = $run.Name
    real_sample_duration_seconds = if ($probe) { Num $probe.duration } else { $null }
    decoded_shots = $shots.Count
    semantic_scenes = $scenes.Count
    finished_events_file_count = $events.Count
    full_scene_checkpoints = Count-Files $visual 'event_????.json'
    child_chunk_checkpoints = Count-Files $visual '*_chunk_*.checkpoint.json'
    story_refinement_checkpoints = Count-Files (Join-Path $job 'story_refinement') '*.json'
    title_screen_checkpoints = @(Get-ChildItem -LiteralPath $screen -Filter 'screen_*.json' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike '*.storyboard.json' }).Count
    model_requests = $requests.Count
    model_responses = $responses.Count
    request_classes = @($callRows | Group-Object class | ForEach-Object { [pscustomobject]@{ class = $_.Name; count = $_.Count } })
    model_errors = @($callRows | Where-Object { $_.response_status -eq 'ERROR' } | Group-Object error_type | ForEach-Object { [pscustomobject]@{ type = $_.Name; count = $_.Count } })
    progress_rows_included = $progressRows.Count
    timeline_rows_included = $timeline.Count
    source_metrics = $metrics
    final_pipeline_status = if ($timings) { $timings.status } else { 'unfinished_or_unavailable' }
    final_error_type = if ($timings) { $timings.error_type } else { $null }
    observed_completed = if ($observed) { $observed.complete } else { $null }
    observed_error_type = if ($observed) { $observed.error_type } else { $null }
    real_e2e_status = if ($e2e) { $e2e.status } else { $null }
    real_e2e_error_type = if ($e2e) { $e2e.error_type } else { $null }
}
Save-Json 'overview.json' $diag
@'
KADR DIAGNOSTICS: safe source-structure snapshot.
It contains numeric scene/event boundaries, model request durations and classes,
progress and stage names, but NO input video, images, raw prompts,
ASR text, model responses, API keys or vision.log.
This bundle does NOT change the project or start model inference.
'@ | Set-Content -LiteralPath (Join-Path $out 'README.txt') -Encoding UTF8
$zip = $out + '.zip'
Compress-Archive -Path (Join-Path $out '*') -DestinationPath $zip -CompressionLevel Optimal -Force
Write-Host "`nГОТОВО. Прикрепите ZIP к сообщению ChatGPT:" -ForegroundColor Green
Write-Host $zip -ForegroundColor Cyan
Write-Host "Смысловых сцен: $($scenes.Count); запросов: $($requests.Count); ответов: $($responses.Count)"
