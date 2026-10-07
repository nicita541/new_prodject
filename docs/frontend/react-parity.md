# React Migration Parity Checklist

| Legacy function | React equivalent | Status | Test | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Projects & Library** | | | | |
| List projects | `ProjectsPage` | DONE | - | |
| Create project | `ProjectsPage` | DONE | - | |
| Delete project | `ProjectsPage` / `EpisodesPage` | DONE | - | Moves to trash |
| List episodes | `EpisodesPage` | DONE | - | |
| Create episode | `EpisodesPage` | DONE | - | |
| Delete episode | `EpisodesPage` / `EditEpisodePage` | DONE | - | Moves to trash |
| Trash (Restore project/episode) | `TrashPage` | DONE | - | |
| **Edit Episode (Settings)** | | | | |
| Upload video | `SourceSelect` | DONE | - | XHR upload with progress |
| Select source | `SourceSelect` | DONE | - | |
| Select provider/layout/captions | `EditEpisodePage` | DONE | - | |
| DeepSeek check/balance panel | `DeepSeekPanel` | DONE | - | |
| Music settings panel | `MusicPanel` | DONE | - | |
| Save settings & Launch | `EditEpisodePage` | DONE | - | Checkbox and button |
| **Job Polling & Progress** | | | | |
| Job polling | `useJobPolling` | DONE | JobProgressPanel.test.tsx | Independent hook |
| Progress UI & Stages | `JobProgressPanel` | DONE | JobProgressPanel.test.tsx | Matches old HTML structure |
| Cancel job | `JobProgressPanel` | DONE | - | |
| Retry job | `JobProgressPanel` | DONE | - | For failed jobs |
| **Review (Player & Playlist)** | | | | |
| Select completed job | `ReviewEpisodePage` | DONE | - | Dropdown for attempts |
| Shorts Player | `VideoPlayer` | DONE | - | |
| Playlist (select part) | `Playlist` | DONE | - | |
| Download Video/Subtitle | `DownloadControls` | DONE | - | |
| Part Context (prompt/copy) | `PartContext` | DONE | - | |
| Music Track Info | `ReviewEpisodePage` | DONE | - | Music badge |
| **Review (Timeline)** | | | | |
| Timeline Ruler | `Timeline` | DONE | - | |
| Retained/Removed ranges | `Timeline` | DONE | - | |
| Click to seek in source | `Timeline` | DONE | - | |
| Source Player (Preview) | `Timeline` | DONE | - | |
| **Review (Debug & Quality)** | | | | |
| Debug Categories / Detail | `Timeline` | DONE | - | Integrated into Timeline track |
| Quality Warnings | `QualityWarnings` | DONE | - | |
| Quality Notes | `QualityWarnings` | DONE | - | |

_Not completely done until all statuses are DONE and Tests are written._
