import { describe, it, expect } from 'vitest';
import { buildTimelinePieces, buildDebugPieces, mergeDebugPieces, sourceTime } from './timeline';
import type { Plan, TimelineReason } from '../api/types';

describe('timeline utilities', () => {
  const mockPlan: Plan = {
    source: { duration: 100 },
    parts: [
      {
        index: 0,
        cuts: [{ start: 10, end: 20 }, { start: 25, end: 30 }]
      }
    ]
  };

  it('buildTimelinePieces calculates retained and removed gaps', () => {
    const pieces = buildTimelinePieces(mockPlan, 100);
    expect(pieces).toHaveLength(5);
    
    // gap
    expect(pieces[0]).toMatchObject({ start: 0, end: 10, retained: false, partIndex: null });
    // cut 1
    expect(pieces[1]).toMatchObject({ start: 10, end: 20, retained: true, partIndex: 0, cutIndex: 0 });
    // gap between cuts
    expect(pieces[2]).toMatchObject({ start: 20, end: 25, retained: false, partIndex: null });
    // cut 2
    expect(pieces[3]).toMatchObject({ start: 25, end: 30, retained: true, partIndex: 0, cutIndex: 1 });
    // final gap
    expect(pieces[4]).toMatchObject({ start: 30, end: 100, retained: false, partIndex: null });
  });

  it('sourceTime formats correctly', () => {
    expect(sourceTime(65.5)).toBe('01:05.50');
    expect(sourceTime(9)).toBe('00:09.00');
  });

  it('buildDebugPieces clips retained reasons to retained cuts', () => {
    const pieces = buildTimelinePieces(mockPlan, 100);
    const reasons: TimelineReason[] = [
      { kind: 'story', title: 'Plot', detail: '', start: 4, end: 28, retained: true }
    ];
    const debugPieces = buildDebugPieces(reasons, pieces, 100);
    
    // Should clip to [10, 20] and [25, 28]
    expect(debugPieces).toHaveLength(2);
    expect(debugPieces[0]).toMatchObject({ start: 10, end: 20, kind: 'story' });
    expect(debugPieces[1]).toMatchObject({ start: 25, end: 28, kind: 'story' });
  });

  it('buildDebugPieces filters removed reasons that overlap retained cuts', () => {
    const pieces = buildTimelinePieces(mockPlan, 100);
    const reasons: TimelineReason[] = [
      { kind: 'waiting', title: 'Wait', detail: '', start: 0, end: 10, retained: false }, // OK
      { kind: 'waiting', title: 'Wait', detail: '', start: 15, end: 25, retained: false } // Overlaps [10, 20] -> excluded
    ];
    const debugPieces = buildDebugPieces(reasons, pieces, 100);
    
    expect(debugPieces).toHaveLength(1);
    expect(debugPieces[0]).toMatchObject({ start: 0, end: 10 });
  });

  it('mergeDebugPieces merges adjacent identical items', () => {
    const rawPieces = [
      { kind: 'story', title: 'Plot', detail: '', start: 10, end: 15, retained: true, partIndex: 0 },
      { kind: 'story', title: 'Plot', detail: '', start: 15, end: 20, retained: true, partIndex: 0 }
    ];
    const merged = mergeDebugPieces(rawPieces);
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({ start: 10, end: 20 });
  });
});
