# React Migration Parity Checklist

| Legacy function | React equivalent | Status | Test | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Projects & Library** | | | | |
| List projects | `ProjectsPage` | DONE | DONE | |
| Create project | `ProjectsPage` | DONE | DONE | |
| Delete project | `ProjectsPage` / `EpisodesPage` | DONE | DONE | Moves to trash |
| List episodes | `EpisodesPage` | DONE | DONE | |
| Create episode | `EpisodesPage` | DONE | DONE | |
| Delete episode | `EpisodesPage` / `EditEpisodePage` | DONE | DONE | Moves to trash |
| Trash (Restore project/episode) | `TrashPage` | DONE | DONE | |
| **Edit Episode (Settings)** | | | | |
| Upload video | `SourceSelect` | DONE | DONE | XHR upload with progress |
| Select source | `SourceSelect` | DONE | DONE | |
| Select provider/layout/captions | `EditEpisodePage` | DONE | DONE | |
| DeepSeek check/balance panel | `DeepSeekPanel` | DONE | DONE | |
| Music settings panel | `MusicPanel` | DONE | DONE | |
| Save settings & Launch | `EditEpisodePage` | DONE | DONE | Checkbox and button |
| **Job Polling & Progress** | | | | |
| Job polling | `useJobPolling` | DONE | JobProgressPanel.test.tsx | Independent hook |
| Progress UI & Stages | `JobProgressPanel` | DONE | JobProgressPanel.test.tsx | Matches old HTML structure |
| Cancel job | `JobProgressPanel` | DONE | DONE | |
| Retry job | `JobProgressPanel` | DONE | DONE | For failed jobs |
| **Review (Player & Playlist)** | | | | |
| Select completed job | `ReviewEpisodePage` | DONE | DONE | Dropdown for attempts |
| Shorts Player | `VideoPlayer` | DONE | DONE | |
| Playlist (select part) | `Playlist` | DONE | DONE | |
| Download Video/Subtitle | `DownloadControls` | DONE | DONE | |
| Part Context (prompt/copy) | `PartContext` | DONE | DONE | |
| Music Track Info | `ReviewEpisodePage` | DONE | DONE | Music badge |
| **Review (Timeline)** | | | | |
| Timeline Ruler | `Timeline` | DONE | DONE | |
| Retained/Removed ranges | `Timeline` | DONE | DONE | |
| Click to seek in source | `Timeline` | DONE | DONE | |
| Source Player (Preview) | `Timeline` | DONE | DONE | |
| **Review (Debug & Quality)** | | | | |
| Debug Categories / Detail | `Timeline` | DONE | DONE | Integrated into Timeline track |
| Quality Warnings | `QualityWarnings` | DONE | DONE | |
| Quality Notes | `QualityWarnings` | DONE | DONE | |

_Not completely DONE until all statuses are DONE and Tests are written._
