# React Migration Inventory

This document maps all existing vanilla JS/HTML UI elements, states, and functionality to their planned React equivalents as part of the frontend migration strategy.

## 1. Global & Layout Components

| Existing UI Element / State | Current JS Handler | API Endpoint | New React Equivalent |
| --------------------------- | ------------------ | ------------ | -------------------- |
| Sidebar Navigation Menu | `window.addEventListener('hashchange')` | N/A | `<Sidebar>` / `<NavLink>` |
| Connection Status Pill | `renderHealth(health)` | `GET /api/library`, `GET /api/deepseek/check` | `<ConnectionStatus>` |
| Breadcrumbs | `libraryUI.heading()` | N/A | `<Breadcrumbs>` |
| Global Page Title & Context | `libraryUI.heading()` | N/A | `<PageHeader>` |
| Global Alert / Message | `setText('library-message', ...)` | N/A | `<GlobalToast>` / `<Alert>` |
| Footer Storage Info | `renderProvider()` | N/A | `<Footer>` |

## 2. Projects Screen (`#projects-screen`)

| Existing UI Element / State | Current JS Handler | API Endpoint | New React Equivalent |
| --------------------------- | ------------------ | ------------ | -------------------- |
| Create Project Form & Input | `$('project-form').addEventListener('submit')` | `POST /api/projects` | `<CreateProjectForm>` |
| Project Grid | `libraryUI.renderCards()` | `GET /api/library` | `<ProjectGrid>` |
| Project Card | N/A | N/A | `<ProjectCard>` |
| Delete Project Button | `libraryUI.deleteButton()`, `libraryUI.archive()` | `DELETE /api/projects/:id` | `<DeleteButton>` |
| Open Project Action | Href `#project/:id` | N/A | `<Link to="/project/:id">` |
| Empty State | `$('projects-empty').hidden` | N/A | `<EmptyState>` |

## 3. Trash Screen (`#trash-screen`)

| Existing UI Element / State | Current JS Handler | API Endpoint | New React Equivalent |
| --------------------------- | ------------------ | ------------ | -------------------- |
| Trash Grid | `libraryUI.renderCards()` | `GET /api/library` | `<TrashGrid>` |
| Restorable Card (Project/Episode)| N/A | N/A | `<TrashCard>` |
| Restore Button | `libraryUI.restore(kind, id)` | `POST /api/projects/:id/restore` <br/> `POST /api/episodes/:id/restore` | `<RestoreButton>` |
| Empty State | `$('trash-empty').hidden` | N/A | `<EmptyState>` |

## 4. Episodes Screen (`#episodes-screen`)

| Existing UI Element / State | Current JS Handler | API Endpoint | New React Equivalent |
| --------------------------- | ------------------ | ------------ | -------------------- |
| Add Episode Form & Input | `$('episode-form').addEventListener('submit')` | `POST /api/projects/:id/episodes` | `<CreateEpisodeForm>` |
| Delete Current Project Button | `$('delete-current-project').addEventListener('click')` | `DELETE /api/projects/:id` | `<DeleteProjectButton>` |
| Episode Grid | `libraryUI.renderCards()` | `GET /api/library` | `<EpisodeGrid>` |
| Episode Card | N/A | N/A | `<EpisodeCard>` |
| Configure Edit Button | Href `#episode/:id/edit` | N/A | `<Link to="/episode/:id/edit">` |
| Check Shorts Button | Href `#episode/:id/review/:jobId` | N/A | `<Link to="/episode/:id/review/:jobId">` |
| Delete Episode Button | `libraryUI.deleteButton()`, `libraryUI.archive()` | `DELETE /api/episodes/:id` | `<DeleteButton>` |
| Empty State | `$('episodes-empty').hidden` | N/A | `<EmptyState>` |

## 5. Edit (Settings) Screen (`#edit-screen`)

| Existing UI Element / State | Current JS Handler | API Endpoint | New React Equivalent |
| --------------------------- | ------------------ | ------------ | -------------------- |
| Delete Episode Button | `$('delete-current-episode').addEventListener('click')` | `DELETE /api/episodes/:id` | `<DeleteEpisodeButton>` |
| Review Ready Link | `$('edit-review-link').hidden` | N/A | `<Link to="/episode/:id/review">` |
| Video Source Select | `loadSources()`, `sourceChanged()` | `GET /api/sources` | `<SourceSelect>` |
| Refresh Sources Button | Formally part of `loadSources()` logic | `GET /api/sources` | `<IconButton onClick={refreshSources}>` |
| Video Upload Drag&Drop Zone | Listeners in `app.js` (dragover, drop) | `POST /api/import` (multipart) | `<UploadDropzone>` |
| Upload Progress Meter | Progress event listener | N/A | `<ProgressBar>` |
| Layout / Framing Select | `renderEditing()` | `PUT /api/episodes/:id/settings` | `<LayoutSelect>` |
| Caption Style Select | `renderEditing()` | `PUT /api/episodes/:id/settings` | `<CaptionStyleSelect>` |
| Subtitle & Style Preview Box| `renderEditing()` | N/A | `<StylePreview layout={layout} captionStyle={style}>` |
| Analysis Provider Select | `analysisProvider()`, `renderProvider()` | `PUT /api/episodes/:id/settings` | `<ProviderSelect>` |
| DeepSeek Budget/Balance Info| `renderBalance()`, `renderSpending()` | `GET /api/deepseek` | `<DeepSeekPanel>` |
| DeepSeek Refresh Balance | `refreshBalance()` | N/A | `<Button onClick={refreshBalance}>` |
| Hybrid Fallback Checkbox | `renderProvider()` | N/A | `<Checkbox name="hybridFallback">` |
| DeepSeek Connection Check | `checkDeepseek()` | `POST /api/deepseek/check` | `<Button onClick={checkDeepseek}>` |
| Background Music Toggle | `musicUI.render()`, `musicUI.save()` | `PUT /api/music` | `<MusicSettingsToggle>` |
| Music Volume Slider | `musicUI.render()`, `musicUI.save()` | `PUT /api/music` | `<RangeSlider name="volume">` |
| Music Mode Select | `musicUI.render()`, `musicUI.save()` | `PUT /api/music` | `<Select name="musicMode">` |
| Track Select (Single/Random)| `musicUI.populateTracks()` | N/A | `<TrackSelect>` |
| Per-Part Music Assignment | `musicUI.renderPartsList()` | `PUT /api/music` | `<MusicPartsList>` |
| Music Folder Actions (3 btn)| `musicUI.openFolder()`, `copyPath()`, `refresh()`| `POST /api/music/open`, `GET /api/music` | `<MusicFolderControls>` |
| Save Settings Default Check | `$('save-settings').addEventListener('click')` | `PUT /api/episodes/:id/settings` | `<Checkbox name="saveAsDefault">` |
| Start Job Button (Монтировать)| `libraryUI.launch()` | `POST /api/episodes/:id/jobs` | `<StartJobButton>` |
| Job Progress Panel | `renderJob(job)` | WS/Polling (`api(...)`) | `<JobProgressPanel>` |
| Job Checkpoints/Stages List | `renderCheckpoints(job)` | N/A | `<JobStagesList>` |
| Job Cancel / Retry Buttons | `$('cancel-button')`, `$('retry-button')` | `POST /api/jobs/:id/cancel` / `retry` | `<CancelJobButton>` / `<RetryJobButton>` |
| Job Budget/Metadata Display | `renderJob(job)` | N/A | `<JobMetadata>` |
| Plan JSON Download Link | `$('plan-link').href` | `GET /api/jobs/:id/plan` | `<a href="...">` |
| Job History Panel | `renderHistory()` | N/A | `<JobHistoryList>` |

## 6. Review Screen (`#review-screen`)

| Existing UI Element / State | Current JS Handler | API Endpoint | New React Equivalent |
| --------------------------- | ------------------ | ------------ | -------------------- |
| Attempt Select Dropdown | `libraryUI.renderAttempts()` | N/A | `<AttemptSelect>` |
| Edit Config Link | Href `#episode/:id/edit` | N/A | `<Link to="/episode/:id/edit">` |
| Timeline Zoom Select | Change listener | N/A | `<TimelineZoomControl>` |
| Timeline & Ruler | `loadTimeline(job)`, `renderTimelineSelection()` | `GET /api/jobs/:id/plan` | `<Timeline>` |
| Debug Layer Checkbox & Info | `renderDebugTimeline()`, `showDebugReason()` | N/A | `<DebugTimeline>` |
| Source Video Player | `$('source-player').src` | `GET /api/jobs/:id/source` | `<SourcePlayer>` |
| Source Play Controls | `reviewSource(piece)` | N/A | `<SourceControls>` |
| Quality Warnings / Notes | `loadQualityWarnings(job)` | `GET /api/jobs/:id/plan` | `<QualityWarningsPanel>` |
| Shorts Video Player | `selectFile(index, play)` | N/A | `<ShortsPlayer>` |
| Shorts Parts Playlist | `renderFiles(job)` | N/A | `<ShortsPlaylist>` |
| Download Subtitles / Video | `renderDownloadButtons()` | `GET file.url?download=1` | `<DownloadLink>` |
| Save All / Open Folder | `saveVideos(true)`, `openFolder()` | `POST /api/jobs/:id/save-videos`, `POST /api/jobs/:id/open-folder` | `<Button onClick={saveVideos}>` |
| AI Part Context Panel | `renderPartContext()` | N/A | `<PartContextPanel>` |
| Copy AI Prompt Button | `copyPartContext()` | N/A | `<CopyPromptButton>` |
| Review Empty State | `$('review-empty').hidden` | N/A | `<EmptyState>` |
