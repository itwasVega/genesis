"""Read-only extraction with the bundled native PDF helper."""
import json,sys
from genesis_pdf import document
value=document(sys.argv[1])
pages=[{'page':i+1,'text':text} for i,text in enumerate(value['pages'])]
print(json.dumps({'pages':pages,'page_count':len(pages),'text_available':any(p['text'].strip() for p in pages)}))
