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
  cutIndex: number | null;
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
  atmosphere: 'Атмосфера',
  reaction: 'Реакция'
};

export function buildDebugPieces(reasons: TimelineReason[], pieces: TimelineInterval[], duration: number): DebugPiece[] {
  let rawPieces: (TimelineReason & { partIndex: number | null, cutIndex: number | null })[] = [];

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
            partIndex: p.partIndex,
            cutIndex: p.cutIndex
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
          partIndex: null,
          cutIndex: null
        });
      }
    }
  }

  return mergeDebugPieces(rawPieces);
}

export function mergeDebugPieces(rawPieces: (TimelineReason & { partIndex: number | null, cutIndex: number | null })[]): DebugPiece[] {
  if (rawPieces.length === 0) return [];

  // Sort by start
  rawPieces.sort((a, b) => a.start - b.start);

  const merged: (TimelineReason & { partIndex: number | null, cutIndex: number | null })[] = [];
  let current = rawPieces[0];

  for (let i = 1; i < rawPieces.length; i++) {
    const next = rawPieces[i];
    
    // We allow tiny float differences but not large gaps
    const isAdjacent = Math.abs(current.end - next.start) < 0.05;
    const isSameKind = current.kind === next.kind;
    const isSameTitle = current.title === next.title;
    const isSameDetail = current.detail === next.detail;
    const isSamePart = current.partIndex === next.partIndex;
    const isSameCut = current.cutIndex === next.cutIndex;
    const isSameEventId = current.event_id === next.event_id;

    if (isAdjacent && isSameKind && isSameTitle && isSameDetail && isSamePart && isSameCut && isSameEventId) {
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
      partIndex: p.partIndex,
      cutIndex: p.cutIndex
    });
  }

  return result;
}

export type LimitedPlaybackAction = { kind: 'continue' } | { kind: 'seek'; time: number } | { kind: 'pause' };

/** Review retained cuts only; never play footage removed from the selected Shorts. */
export function limitedSourcePlaybackAction(
  cuts: Array<{ start: number; end: number }>,
  time: number,
  selection: { start: number; end: number; retained: boolean },
): LimitedPlaybackAction {
  const tolerance = 0.02;
  if (time >= selection.end - tolerance) return { kind: 'pause' };
  if (time < selection.start - tolerance) return { kind: 'seek', time: selection.start };
  // A removed/debug source interval should remain independently previewable.
  if (!selection.retained) return { kind: 'continue' };
  for (const cut of cuts) {
    const start = Math.max(cut.start, selection.start);
    const end = Math.min(cut.end, selection.end);
    if (end <= start) continue;
    if (time < start - tolerance) return { kind: 'seek', time: start };
    if (time < end - tolerance) return { kind: 'continue' };
  }
  return { kind: 'pause' };
}
