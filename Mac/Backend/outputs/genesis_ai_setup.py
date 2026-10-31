"""Explicit AI onboarding. Account/model discovery only; never reads credentials."""
import json
import os
from pathlib import Path
from genesis_connections import read, ROOT

def executable():
    configured = read().get('codex_path', '')
    if not configured:
        raise RuntimeError('Choose your Codex executable in Settings > Models, then sign in to Codex.')
    path = Path(configured).expanduser()
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError('The selected Codex executable is unavailable. Select it again in Settings > Models.')
    return path

def check(client_factory=None):
    from genesis_direct import Client
    client = None
    try:
        client = (client_factory or Client)()
        account = client.call('account/read', {'refreshToken': False})
        if account.get('requiresOpenaiAuth', True) and not account.get('account'):
            raise RuntimeError('Open Codex and sign in, then test this connection again.')
        available = []; cursor = None
        for _ in range(10):
            result = client.call('model/list', {'limit': 100, 'includeHidden': False, **({'cursor': cursor} if cursor else {})})
            available += result.get('data', [])
            cursor = result.get('nextCursor')
            if not cursor: break
        else: raise RuntimeError('Model listing did not finish; no configuration was changed.')
        models = {x.get('model'): x for x in available if isinstance(x.get('model'), str)}
        if not models: raise RuntimeError('Codex returned no available models for this account.')
        from genesis_coaching import atomic
        atomic(ROOT/'Genesis Study/ai-available.json', {'models': list(models), 'details': available})
        config_path = ROOT/'genesis_models.json'
        config = json.loads(config_path.read_text())
        if config.get('mode') != 'manual':
            # Auto: Genesis picks per job from this list every time; nothing to rewrite.
            return {'ok': True, 'detail': 'Connected. Genesis picks the right model and strength for each job automatically.', 'models': list(models)}
        selected = next((x['model'] for x in available if x.get('isDefault')), next(iter(models)))
        alternate = next((m for m in models if m != selected), selected)
        changed = False
        for name, job in config.get('jobs', {}).items():
            if job.get('model') == 'auto':
                job['model'] = alternate if name == 'verify' else selected; changed = True
            info = models.get(job.get('model'))
            if info:
                efforts = [x['reasoningEffort'] for x in info.get('supportedReasoningEfforts', [])]
                if efforts and job.get('effort') not in efforts:
                    job['effort'] = info.get('defaultReasoningEffort', efforts[0]); changed = True
        if config.get('fallback_model') == 'auto': config['fallback_model'] = selected; changed = True
        if changed: atomic(config_path, config)
        missing = sorted({x.get('model') for x in config.get('jobs', {}).values()} - models.keys())
        detail = 'Connected. Your account offers '+str(len(models))+' models.'
        if missing: detail += ' Update unavailable model choices: '+', '.join(missing)+'.'
        if len(models)<2: detail += ' Independent verification will use a separate session of the same available model.'
        return {'ok': True, 'detail': detail, 'models': list(models)}
    except Exception as exc:
        return {'ok': False, 'detail': str(exc)[:350]}
    finally:
        if client: client.close()

if __name__ == '__main__': print(json.dumps(check()))
