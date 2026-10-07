# React Migration Parity Checklist

| Legacy function | React equivalent | Status | Test | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Projects & Library** | | | | |
| List projects | `ProjectsPage` | IMPLEMENTED / UNVERIFIED | - | |
| Create project | `ProjectsPage` | IMPLEMENTED / UNVERIFIED | - | |
| Delete project | `ProjectsPage` / `EpisodesPage` | IMPLEMENTED / UNVERIFIED | - | Moves to trash |
| List episodes | `EpisodesPage` | IMPLEMENTED / UNVERIFIED | - | |
| Create episode | `EpisodesPage` | IMPLEMENTED / UNVERIFIED | - | |
| Delete episode | `EpisodesPage` / `EditEpisodePage` | IMPLEMENTED / UNVERIFIED | - | Moves to trash |
| Trash (Restore project/episode) | `TrashPage` | IMPLEMENTED / UNVERIFIED | - | |
| **Edit Episode (Settings)** | | | | |
| Upload video | `SourceSelect` | IMPLEMENTED / UNVERIFIED | - | XHR upload with progress |
| Select source | `SourceSelect` | IMPLEMENTED / UNVERIFIED | - | |
| Select provider/layout/captions | `EditEpisodePage` | IMPLEMENTED / UNVERIFIED | - | |
| DeepSeek check/balance panel | `DeepSeekPanel` | IMPLEMENTED / UNVERIFIED | - | |
| Music settings panel | `MusicPanel` | IMPLEMENTED / UNVERIFIED | - | |
| Save settings & Launch | `EditEpisodePage` | IMPLEMENTED / UNVERIFIED | - | Checkbox and button |
| **Job Polling & Progress** | | | | |
| Job polling | `useJobPolling` | IMPLEMENTED / UNVERIFIED | JobProgressPanel.test.tsx | Independent hook |
| Progress UI & Stages | `JobProgressPanel` | IMPLEMENTED / UNVERIFIED | JobProgressPanel.test.tsx | Matches old HTML structure |
| Cancel job | `JobProgressPanel` | IMPLEMENTED / UNVERIFIED | - | |
| Retry job | `JobProgressPanel` | IMPLEMENTED / UNVERIFIED | - | For failed jobs |
| **Review (Player & Playlist)** | | | | |
| Select completed job | `ReviewEpisodePage` | IMPLEMENTED / UNVERIFIED | - | Dropdown for attempts |
| Shorts Player | `VideoPlayer` | IMPLEMENTED / UNVERIFIED | - | |
| Playlist (select part) | `Playlist` | IMPLEMENTED / UNVERIFIED | - | |
| Download Video/Subtitle | `DownloadControls` | IMPLEMENTED / UNVERIFIED | - | |
| Part Context (prompt/copy) | `PartContext` | IMPLEMENTED / UNVERIFIED | - | |
| Music Track Info | `ReviewEpisodePage` | IMPLEMENTED / UNVERIFIED | - | Music badge |
| **Review (Timeline)** | | | | |
| Timeline Ruler | `Timeline` | IMPLEMENTED / UNVERIFIED | - | |
| Retained/Removed ranges | `Timeline` | IMPLEMENTED / UNVERIFIED | - | |
| Click to seek in source | `Timeline` | IMPLEMENTED / UNVERIFIED | - | |
| Source Player (Preview) | `Timeline` | IMPLEMENTED / UNVERIFIED | - | |
| **Review (Debug & Quality)** | | | | |
| Debug Categories / Detail | `Timeline` | IMPLEMENTED / UNVERIFIED | - | Integrated into Timeline track |
| Quality Warnings | `QualityWarnings` | IMPLEMENTED / UNVERIFIED | - | |
| Quality Notes | `QualityWarnings` | IMPLEMENTED / UNVERIFIED | - | |

_Not completely IMPLEMENTED / UNVERIFIED until all statuses are IMPLEMENTED / UNVERIFIED and Tests are written._
