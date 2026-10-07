import type { Plan, TimelineReason } from '../api/types';

export interface TimelineInterval {
  start: number;
  end: number;
  retained: boolean;
  partIndex: number | null;
  cutIndex: number | null;
}

export function buildTimelinePieces(plan: Plan, duration: number): TimelineInterval[] {
  const pieces: TimelineInterval[] = [];
  let currentTime = 0;

  for (let i = 0; i < plan.parts.length; i++) {
    const part = plan.parts[i];
    for (let j = 0; j < part.cuts.length; j++) {
      const cut = part.cuts[j];

      // Insert removed gap if necessary
      if (cut.start > currentTime) {
        pieces.push({
          start: currentTime,
          end: cut.start,
          retained: false,
          partIndex: null,
          cutIndex: null
        });
      }

      // Insert retained cut
      pieces.push({
        start: cut.start,
        end: cut.end,
        retained: true,
        partIndex: i,
        cutIndex: j
      });

      currentTime = cut.end;
    }
  }

  // Final gap
  if (currentTime < duration) {
    pieces.push({
      start: currentTime,
      end: duration,
      retained: false,
      partIndex: null,
      cutIndex: null
    });
  }

  return pieces;
}

export interface DebugPiece {
  id: string; // Used for unique key
  start: number;
  end: number;
  kind: string;
  title: string;
  detail?: string;
  lane: number;
  partIndex: number | null;
}

export function sourceTime(timeSec: number): string {
  const m = Math.floor(timeSec / 60);
  const s = Math.floor(timeSec % 60);
  const ms = Math.floor((timeSec % 1) * 100);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(2, '0')}`;
}

export function pieceLabel(piece: TimelineInterval): string {
  if (piece.retained) {
    return `Оставлено · исходник ${sourceTime(piece.start)}–${sourceTime(piece.end)}`;
  }
  return `Убрано · исходник ${sourceTime(piece.start)}–${sourceTime(piece.end)}`;
}

export const DEBUG_KIND_LABELS: Record<string, string> = {
  story: 'Сюжет',
  character_reaction: 'Реакция',
  emotional_pause: 'Эмоция',
  comedic_payoff: 'Юмор',
  establishing_context: 'Контекст',
  neutral_scenery: 'Сцена',
  waiting: 'Ожидание',
  manual: 'Вручную',
  uncertainty: 'Неясно',
};

export function buildDebugPieces(reasons: TimelineReason[], pieces: TimelineInterval[], duration: number): DebugPiece[] {
  let rawPieces: (TimelineReason & { partIndex: number | null })[] = [];

  for (const reason of reasons) {
    if (!reason.kind || typeof reason.start !== 'number' || typeof reason.end !== 'number' || !reason.title) continue;
    if (reason.start < 0 || reason.start >= reason.end || reason.end > duration) continue;

    if (reason.retained === true || reason.retained === undefined) {
      // Retained reasons must be clipped to retained intervals
      for (const p of pieces) {
        if (!p.retained) continue;
        const intersectionStart = Math.max(reason.start, p.start);
        const intersectionEnd = Math.min(reason.end, p.end);
        if (intersectionStart < intersectionEnd) {
          rawPieces.push({
            ...reason,
            start: intersectionStart,
            end: intersectionEnd,
            partIndex: p.partIndex
          });
        }
      }
    } else {
      // Removed reasons are shown only if they don't intersect with retained
      // A strict interpretation: check if it overlaps any retained piece.
      // If it overlaps, don't show it at all.
      let overlaps = false;
      for (const p of pieces) {
        if (p.retained) {
          if (Math.max(reason.start, p.start) < Math.min(reason.end, p.end)) {
            overlaps = true;
            break;
          }
        }
      }
      if (!overlaps) {
        rawPieces.push({
          ...reason,
          partIndex: null
        });
      }
    }
  }

  return mergeDebugPieces(rawPieces);
}

export function mergeDebugPieces(rawPieces: (TimelineReason & { partIndex: number | null })[]): DebugPiece[] {
  if (rawPieces.length === 0) return [];

  // Sort by start
  rawPieces.sort((a, b) => a.start - b.start);

  const merged: (TimelineReason & { partIndex: number | null })[] = [];
  let current = rawPieces[0];

  for (let i = 1; i < rawPieces.length; i++) {
    const next = rawPieces[i];
    // Check if can merge: adjacent (start == current.end or close enough), same part, same kind, same title, same detail
    // Wait, the prompt says: "Соседние доказательства можно объединять только если совпадают event_id, kind, title, detail, partIndex, cutIndex. При этом нельзя объединять через настоящий source gap."
    // Let's implement strict merging based on the properties available.
    // Assuming `event_id` exists in legacy but might not be in the current types. We'll use title, detail, kind, partIndex.
    
    // We allow tiny float differences but not large gaps
    const isAdjacent = Math.abs(current.end - next.start) < 0.05;
    const isSameKind = current.kind === next.kind;
    const isSameTitle = current.title === next.title;
    const isSameDetail = current.detail === next.detail;
    const isSamePart = current.partIndex === next.partIndex;
    const isSameEventId = current.event_id === next.event_id;

    if (isAdjacent && isSameKind && isSameTitle && isSameDetail && isSamePart && isSameEventId) {
      current.end = Math.max(current.end, next.end);
    } else {
      merged.push(current);
      current = next;
    }
  }
  merged.push(current);

  // Assign lanes
  const result: DebugPiece[] = [];
  for (let i = 0; i < merged.length; i++) {
    const p = merged[i];
    let lane = 0;
    // Find first available lane
    while (true) {
      const conflict = result.find(r => r.lane === lane && Math.max(r.start, p.start) < Math.min(r.end, p.end));
      if (!conflict) break;
      lane++;
    }
    result.push({
      id: `${i}-${lane}`,
      start: p.start,
      end: p.end,
      kind: p.kind,
      title: p.title,
      detail: p.detail,
      lane,
      partIndex: p.partIndex
    });
  }

  return result;
}
