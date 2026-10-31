"""Read-only bridge to Genesis's bundled Apple PDFKit / Vision helper."""
import json
import os
import subprocess
from pathlib import Path

def extract(paths, ocr=False):
    helper = os.environ.get('GENESIS_PDF_HELPER', '')
    if not helper or not Path(helper).is_file():
        raise RuntimeError('The Genesis PDF helper is missing. Reinstall a complete Mac build.')
    result = subprocess.run([helper, 'ocr' if ocr else 'text'], input=json.dumps([str(p) for p in paths]),
                            capture_output=True, text=True, timeout=900 if ocr else 300, check=True)
    return json.loads(result.stdout)

def document(path):
    value = extract([path]).get(str(path), {})
    if 'pages' not in value:
        raise ValueError(value.get('error', 'PDF extraction failed'))
    return value
