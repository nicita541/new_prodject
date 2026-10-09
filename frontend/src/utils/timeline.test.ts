import { describe, it, expect } from 'vitest';
import { buildTimelinePieces, buildDebugPieces, mergeDebugPieces, sourceTime, limitedSourcePlaybackAction } from './timeline';
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
      { kind: 'story', title: 'Plot', detail: '', start: 10, end: 15, retained: true, partIndex: 0, cutIndex: 0 },
      { kind: 'story', title: 'Plot', detail: '', start: 15, end: 20, retained: true, partIndex: 0, cutIndex: 0 }
    ];
    const merged = mergeDebugPieces(rawPieces);
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({ start: 10, end: 20 });
  });
  it('buildTimelinePieces supports multiple parts and cuts', () => {
    const multiPlan: Plan = {
      source: { duration: 100 },
      parts: [
        { index: 0, cuts: [{ start: 10, end: 20 }, { start: 25, end: 30 }] },
        { index: 1, cuts: [{ start: 40, end: 50 }] }
      ]
    };
    const pieces = buildTimelinePieces(multiPlan, 100);
    expect(pieces).toHaveLength(7); // gap, cut0-0, gap, cut0-1, gap, cut1-0, gap
    expect(pieces[5]).toMatchObject({ start: 40, end: 50, retained: true, partIndex: 1, cutIndex: 0 });
  });

  it('mergeDebugPieces does not merge with different cutIndex', () => {
    const rawPieces = [
      { kind: 'story', title: 'Plot', detail: '', start: 10, end: 15, retained: true, partIndex: 0, cutIndex: 0 },
      { kind: 'story', title: 'Plot', detail: '', start: 15, end: 20, retained: true, partIndex: 0, cutIndex: 1 }
    ] as any;
    const merged = mergeDebugPieces(rawPieces);
    expect(merged).toHaveLength(2);
  });

  it('mergeDebugPieces does not merge through source gap', () => {
    const rawPieces = [
      { kind: 'story', title: 'Plot', detail: '', start: 10, end: 15, retained: true, partIndex: 0, cutIndex: 0 },
      { kind: 'story', title: 'Plot', detail: '', start: 20, end: 25, retained: true, partIndex: 0, cutIndex: 0 }
    ] as any;
    const merged = mergeDebugPieces(rawPieces);
    expect(merged).toHaveLength(2);
  });

  it('buildDebugPieces assigns different lanes to overlapping items', () => {
    const pieces = buildTimelinePieces(mockPlan, 100);
    const reasons: TimelineReason[] = [
      { kind: 'story', title: 'A', detail: '', start: 10, end: 20, retained: true },
      { kind: 'emotional_pause', title: 'B', detail: '', start: 12, end: 18, retained: true }
    ];
    const debugPieces = buildDebugPieces(reasons, pieces, 100);
    expect(debugPieces).toHaveLength(2);
    expect(debugPieces[0].lane).not.toBe(debugPieces[1].lane);
  });

  it('buildDebugPieces ignores invalid intervals', () => {
    const pieces = buildTimelinePieces(mockPlan, 100);
    const reasons: TimelineReason[] = [
      { kind: 'story', title: 'Invalid', detail: '', start: 20, end: 10, retained: true },
      { kind: 'story', title: 'Invalid2', detail: '', start: -5, end: 10, retained: true }
    ];
    const debugPieces = buildDebugPieces(reasons, pieces, 100);
    expect(debugPieces).toHaveLength(0);
  });

  it('buildDebugPieces ignores out of bounds intervals', () => {
    const pieces = buildTimelinePieces(mockPlan, 100);
    const reasons: TimelineReason[] = [
      { kind: 'story', title: 'OutOfBounds', detail: '', start: 10, end: 150, retained: true }
    ];
    const debugPieces = buildDebugPieces(reasons, pieces, 100);
    expect(debugPieces).toHaveLength(0);
  });

  it('buildDebugPieces handles unknown kinds and legacy kinds safely', () => {
    const pieces = buildTimelinePieces(mockPlan, 100);
    const reasons: TimelineReason[] = [
      { kind: 'atmosphere', title: 'Legacy Atmosphere', detail: '', start: 10, end: 20, retained: true },
      { kind: 'weird_alien_kind', title: 'Unknown', detail: '', start: 25, end: 30, retained: true }
    ];
    const debugPieces = buildDebugPieces(reasons, pieces, 100);
    expect(debugPieces).toHaveLength(2);
    expect(debugPieces[0].kind).toBe('atmosphere');
    expect(debugPieces[1].kind).toBe('weird_alien_kind');
  });
});

describe('Source playback across edited cuts', () => {
  const cuts = [{ start: 10, end: 20 }, { start: 30, end: 40 }];
  const whole = { start: 10, end: 40, retained: true };
  it('jumps over removed source frames and stops at the selected end', () => {
    expect(limitedSourcePlaybackAction(cuts, 15, whole)).toEqual({ kind: 'continue' });
    expect(limitedSourcePlaybackAction(cuts, 21, whole)).toEqual({ kind: 'seek', time: 30 });
    expect(limitedSourcePlaybackAction(cuts, 35, whole)).toEqual({ kind: 'continue' });
    expect(limitedSourcePlaybackAction(cuts, 40, whole)).toEqual({ kind: 'pause' });
  });
  it('allows inspecting an intentionally selected removed interval', () => {
    const removed = { start: 20, end: 30, retained: false };
    expect(limitedSourcePlaybackAction(cuts, 25, removed)).toEqual({ kind: 'continue' });
    expect(limitedSourcePlaybackAction(cuts, 30, removed)).toEqual({ kind: 'pause' });
  });
});
