"""Version-2 outcome and decision contracts; never judge optimality or run checks."""
import math


DIMENSIONS = {'scalability', 'speed', 'correctness', 'efficiency', 'maintainability', 'other'}
QUANTITATIVE = {'scalability', 'speed', 'efficiency'}


def validate(report, data, audit):
    complete = report['review_state'] == 'complete'
    objectives = report['objectives']
    decisions = report['recommendations']
    if not isinstance(objectives, list) or not isinstance(decisions, list):
        raise audit.AuditError('Objectives and recommendations must be lists')
    if complete and (not objectives or not decisions):
        raise audit.AuditError('Complete v2 review requires an objective and a change/keep/investigate decision')
    goals = {}
    for goal in objectives:
        audit.require_keys(goal, {'id', 'dimension', 'operation', 'desired_outcome', 'direction', 'workload', 'constraints', 'baseline', 'verification'}, 'Objective')
        for key in ('id', 'operation', 'desired_outcome', 'workload'):
            audit.nonempty(goal[key], 'Objective ' + key)
        if goal['id'] in goals or goal['dimension'] not in DIMENSIONS or goal['direction'] not in {'lower', 'higher', 'contract'}:
            raise audit.AuditError('Duplicate objective or invalid dimension/direction')
        if goal['dimension'] in QUANTITATIVE and goal['direction'] == 'contract':
            raise audit.AuditError('Quantitative objective needs a lower/higher direction')
        audit.string_list(goal['constraints'], 'Objective constraints')
        baseline = goal['baseline']
        audit.require_keys(baseline, {'state', 'description', 'evidence'}, 'Baseline')
        if baseline['state'] not in {'observed', 'unknown'}:
            raise audit.AuditError('Baseline must be observed or explicitly unknown')
        audit.nonempty(baseline['description'], 'Baseline description')
        audit.check_evidence(baseline['evidence'], data, 'Baseline', baseline['state'] == 'observed')
        audit.require_keys(goal['verification'], {'method', 'expected_outcome', 'boundary'}, 'Objective verification')
        for key, value in goal['verification'].items():
            audit.nonempty(value, 'Objective verification ' + key)
        goals[goal['id']] = goal
    findings = {(row['id'], index) for row in report['assessments'] for index, _ in enumerate(row['findings'])}
    covered, seen = set(), set()
    for decision in decisions:
        audit.require_keys(decision, {'id', 'decision', 'priority', 'principles', 'objective_refs', 'finding_refs', 'best_practice', 'preferred_approach', 'why_preferred', 'code_impact', 'user_impact', 'tradeoff', 'alternatives', 'revisit_when', 'evidence', 'verification', 'result', 'measurements'}, 'Recommendation')
        for key in ('id', 'best_practice', 'preferred_approach', 'why_preferred', 'tradeoff', 'revisit_when'):
            audit.nonempty(decision[key], 'Recommendation ' + key)
        if decision['id'] in seen or decision['decision'] not in {'change', 'keep', 'investigate'} or decision['priority'] not in {'now', 'next', 'later'}:
            raise audit.AuditError('Duplicate recommendation or invalid decision/priority')
        seen.add(decision['id'])
        audit.string_list(decision['principles'], 'Recommendation principles', True)
        audit.string_list(decision['objective_refs'], 'Recommendation objectives', True)
        if len(set(decision['principles'])) != len(decision['principles']) or any(p not in audit.RULE_IDS for p in decision['principles']):
            raise audit.AuditError('Unknown or duplicate recommendation principle')
        if len(set(decision['objective_refs'])) != len(decision['objective_refs']) or any(g not in goals for g in decision['objective_refs']):
            raise audit.AuditError('Unknown or duplicate recommendation objective')
        if not isinstance(decision['finding_refs'], list):
            raise audit.AuditError('Finding references must be a list')
        local_refs = set()
        for ref in decision['finding_refs']:
            audit.require_keys(ref, {'rule_id', 'finding_index'}, 'Finding reference')
            if not isinstance(ref['rule_id'], str) or type(ref['finding_index']) is not int:
                raise audit.AuditError('Invalid finding reference')
            key = (ref['rule_id'], ref['finding_index'])
            if key not in findings or key in local_refs or ref['rule_id'] not in decision['principles']:
                raise audit.AuditError('Missing, duplicate or unrelated finding reference')
            if decision['decision'] == 'keep':
                raise audit.AuditError('Keep decision cannot dispose of an unresolved violation')
            local_refs.add(key)
        covered.update(local_refs)
        for key in ('code_impact', 'user_impact'):
            impact = decision[key]
            audit.require_keys(impact, {'claim', 'basis', 'evidence'}, key)
            audit.nonempty(impact['claim'], key + ' claim')
            if impact['basis'] not in {'observed', 'expected', 'unknown'}:
                raise audit.AuditError('Impact must distinguish observed, expected and unknown')
            audit.check_evidence(impact['evidence'], data, key, impact['basis'] == 'observed')
        if not isinstance(decision['alternatives'], list):
            raise audit.AuditError('Alternatives must be a list')
        for alternative in decision['alternatives']:
            audit.require_keys(alternative, {'approach', 'prefer_when', 'benefit', 'cost'}, 'Alternative')
            for key, value in alternative.items():
                audit.nonempty(value, 'Alternative ' + key)
        audit.check_evidence(decision['evidence'], data, 'Recommendation', decision['decision'] != 'investigate')
        verification = decision['verification']
        audit.require_keys(verification, {'plan', 'expected_outcome', 'boundary', 'checks_run'}, 'Recommendation verification')
        for key in ('plan', 'expected_outcome', 'boundary'):
            audit.nonempty(verification[key], 'Recommendation verification ' + key)
        audit.check_evidence(verification['checks_run'], data, 'Recommendation executed checks')
        result = decision['result']
        audit.require_keys(result, {'state', 'explanation', 'before_evidence', 'after_evidence'}, 'Recommendation result')
        if result['state'] not in {'proposed', 'implemented_unverified', 'verified', 'blocked', 'not_applicable'}:
            raise audit.AuditError('Invalid improvement result state')
        audit.nonempty(result['explanation'], 'Result explanation')
        verified = result['state'] == 'verified'
        if verified and decision['decision'] != 'change':
            raise audit.AuditError('Only an actual change can claim a verified improvement')
        audit.check_evidence(result['before_evidence'], data, 'Before result', verified)
        audit.check_evidence(result['after_evidence'], data, 'After result', verified)
        if verified and (not verification['checks_run'] or any(goals[g]['baseline']['state'] != 'observed' for g in decision['objective_refs'])):
            raise audit.AuditError('Verified improvement needs executed checks and observed baselines')
        if not isinstance(decision['measurements'], list):
            raise audit.AuditError('Measurements must be a list')
        measured = set()
        for measure in decision['measurements']:
            audit.require_keys(measure, {'objective_id', 'unit', 'workload', 'method', 'boundary', 'before', 'after', 'uncertainty', 'evidence_before', 'evidence_after'}, 'Measurement')
            if measure['objective_id'] not in decision['objective_refs'] or measure['objective_id'] in measured:
                raise audit.AuditError('Measurement needs a unique linked objective')
            measured.add(measure['objective_id'])
            for key in ('unit', 'workload', 'method', 'boundary', 'uncertainty'):
                audit.nonempty(measure[key], 'Measurement ' + key)
            for key in ('before', 'after'):
                if type(measure[key]) not in (int, float) or (type(measure[key]) is float and not math.isfinite(measure[key])):
                    raise audit.AuditError('Measurement values must be finite numbers, not booleans')
            audit.check_evidence(measure['evidence_before'], data, 'Before measurement', True)
            audit.check_evidence(measure['evidence_after'], data, 'After measurement', True)
            goal = goals[measure['objective_id']]
            if measure['workload'] != goal['workload']:
                raise audit.AuditError('Measurement workload differs from its objective')
            gain = measure['after'] < measure['before'] if goal['direction'] == 'lower' else measure['after'] > measure['before']
            if verified and goal['direction'] != 'contract' and not gain:
                raise audit.AuditError('Verified improvement does not improve the declared numeric direction')
        if verified and any(goals[g]['direction'] != 'contract' and g not in measured for g in decision['objective_refs']):
            raise audit.AuditError('Verified speed/scalability/efficiency improvement needs before/after measurements')
    if complete and findings - covered:
        raise audit.AuditError('Complete v2 review needs a recommendation for every finding')


def render(report, audit, titles):
    text = ['## Outcomes and recommended decisions', '',
            'Observed effects, expected benefits and unknowns are separate. Structural checks cannot prove optimality, authentic execution, representative workloads or statistical significance.', '']
    for goal in report['objectives']:
        text += [f"### Objective {audit.md(goal['id'])} — {audit.md(goal['dimension'])}", '',
                 '**Operation:** ' + audit.md(goal['operation']), '',
                 '**Desired outcome:** ' + audit.md(goal['desired_outcome']), '',
                 '**Workload:** ' + audit.md(goal['workload']), '',
                 '**Constraints:** ' + audit.md('; '.join(goal['constraints']) or 'None stated'), '',
                 '**Baseline (' + goal['baseline']['state'] + '):** ' + audit.md(goal['baseline']['description']), '',
                 '**Verification:** ' + audit.md(goal['verification']['method'] + ' Expected: ' + goal['verification']['expected_outcome'] + ' Boundary: ' + goal['verification']['boundary']), '']
        text += evidence_lines(goal['baseline']['evidence'], audit)
    for decision in report['recommendations']:
        text += [f"### {audit.md(decision['id'])} — {decision['decision']} ({decision['priority']})", '',
                 '**Principles:** ' + '; '.join(p + ' — ' + audit.md(titles[p]) for p in decision['principles']), '',
                 '**Applicable best practice:** ' + audit.md(decision['best_practice']), '',
                 '**Objectives:** ' + audit.md(', '.join(decision['objective_refs'])), '',
                 '**Recommended approach:** ' + audit.md(decision['preferred_approach']), '',
                 '**Why preferred here:** ' + audit.md(decision['why_preferred']), '']
        for key in ('code_impact', 'user_impact'):
            impact = decision[key]
            text += ['**' + key.replace('_', ' ').capitalize() + ' (' + impact['basis'] + '):** ' + audit.md(impact['claim']), '']
            text += evidence_lines(impact['evidence'], audit)
        text += ['**Tradeoff:** ' + audit.md(decision['tradeoff']), '', '**Alternatives:**', '']
        text += ['- ' + audit.md(a['approach'] + ' Prefer when: ' + a['prefer_when'] + ' Benefit: ' + a['benefit'] + ' Cost: ' + a['cost']) for a in decision['alternatives']]
        if not decision['alternatives']:
            text += ['No additional viable alternative stated; do not invent one for completeness.']
        text += ['', '**Revisit when:** ' + audit.md(decision['revisit_when']), '',
                 '**Verification planned:** ' + audit.md(decision['verification']['plan'] + ' Expected: ' + decision['verification']['expected_outcome'] + ' Boundary: ' + decision['verification']['boundary']), '',
                 '**Result (' + decision['result']['state'] + ('; host-attested' if decision['result']['state'] == 'verified' else '') + '):** ' + audit.md(decision['result']['explanation']), '']
        text += evidence_lines(decision['evidence'] + decision['verification']['checks_run'] + decision['result']['before_evidence'] + decision['result']['after_evidence'], audit)
        for measure in decision['measurements']:
            text += ['- **Recorded measurement:** ' + audit.md(str(measure['before']) + ' → ' + str(measure['after']) + ' ' + measure['unit'] + '; workload: ' + measure['workload'] + '; method: ' + measure['method'] + '; boundary: ' + measure['boundary'] + '; uncertainty: ' + measure['uncertainty']), '']
            text += evidence_lines(measure['evidence_before'] + measure['evidence_after'], audit)
    return text


def evidence_lines(items, audit):
    return [f"- Evidence: {audit.md(e['path'])}:{e['start_line']}-{e['end_line']}; file SHA256 `{e['file_sha256']}`; content SHA256 `{e['content_sha256']}`" for e in items] + ([''] if items else [])
