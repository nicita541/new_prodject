"""Optional editorial refinements; source/selection/export gates stay mandatory."""
from pathlib import Path
from .json_store import read_json

OPTIONAL_CHECKS = frozenset({'global_visual_verification', 'pacing', 'silent_sequences',
                             'endings', 'ending_selection_adjudication'})


def economy_mode(directory):
    return read_json(Path(directory) / 'analysis-settings.json', {}).get('economy_mode', True) is True


class AnalysisChecks:
    def __init__(self, directory, journal, diagnostics, report):
        self.economy = economy_mode(directory)
        self.journal, self.diagnostics, self.report = journal, diagnostics, report
        self.prepared = {}

    def targeted(self, name, events, callback, producer, *, task):
        """Specialists inspect detected regions, with ordinary native validation."""
        if name in self.prepared:
            return self.run(name,events,lambda:callback(events),producer)
        from .review_scope import check_regions
        regions = check_regions(events)
        chosen = [e for e in events if (task in e['review_targets'] if 'review_targets' in e else
            any(task in r['checks'] and e['start'] < r['end'] and r['start'] < e['end'] for r in regions))]
        if not chosen:
            self.diagnostics.event(name,'skipped',reason='not_needed')
            return events
        def apply():
            import copy
            targets = copy.deepcopy(chosen)
            for event in targets:
                event['review_target_ranges'] = ([{'start':event['start'],'end':event['end'],'checks':[task]}]
                    if 'review_targets' in event else [
                        {'start':max(event['start'],r['start']),'end':min(event['end'],r['end']),'checks':[task]}
                        for r in regions if task in r['checks'] and event['start'] < r['end'] and r['start'] < event['end']])
            checked = callback(targets)
            before = [(e['id'],e['start'],e['end']) for e in chosen]
            if [(e['id'],e['start'],e['end']) for e in checked] != before:
                raise ValueError('Targeted check changed source ownership')
            by_id = {e['id']:e for e in checked}
            for event in by_id.values():
                event.pop('review_target_ranges', None)
            return [by_id.get(e['id'],e) for e in events]
        self.diagnostics.event(name,'targeted',selected=len(chosen),total=len(events),reason=task)
        return self.run(name,events,apply,producer)

    def run(self, name, inputs, callback, producer):
        if name in self.prepared:
            self.diagnostics.event(name, 'cache_hit', scope='stage', producer=self.prepared[name],
                                   source='accepted_full_pass_prefix')
            return inputs['events'] if isinstance(inputs, dict) else inputs
        if self.economy and name in OPTIONAL_CHECKS:
            # Previously accepted optional work costs no new tokens. Keep it
            # when its input/code identity matches, rather than undoing it.
            saved = self.journal.load(name, inputs)
            if saved is not None:
                self.report('analyze', .49, 'Используем сохранённую дополнительную проверку')
                return saved
            self.diagnostics.event(name, 'skipped', reason='economy_mode')
            return inputs['events'] if isinstance(inputs, dict) else inputs
        return self.journal.run(name, inputs, callback, producer)
