"""Versioned public exercise presentation; never includes protected checker data."""
import re

def latex(value):
    value=value.replace('²','^2').replace('³','^3').replace('sqrt(',r'\sqrt{')
    # Only balanced simple sqrt groups are converted here; authored LaTeX is preferred.
    value=re.sub(r'\\sqrt\{([^()]*)\)',r'\\sqrt{\1}',value)
    value=re.sub(r'\b(sin|cos|tan|ln|log)\b',r'\\\1',value)
    value=re.sub(r'\^\(([^()]*)\)',r'^{\1}',value)
    return re.sub(r'\^(\d+)',r'^{\1}',value)

def math_blocks(text):
    """Read-only legacy presentation adapter, restricted to calculus prose.

    Existing authored LaTeX is preserved. Only bounded mathematical tokens are
    decorated; no symbolic simplification or changes to a checker/journal.
    """
    if '$' in text or r'\(' in text or r'\[' in text:
        return [{'kind':'paragraph','text':text}]
    # Spaces are accepted only around mathematical operators, never between prose words.
    atom=r"[A-Za-z0-9_²³′'()\[\]^]+"
    pattern=re.compile(r"(?:d/dx\s+)?"+atom+r"(?:\s*[=+*·/−-]\s*"+atom+r")*")
    def decorate(m):
        value=m.group(0)
        identifiers=re.findall(r'[A-Za-z_]+',value.replace('d/dx',''))
        if not identifiers and not any(c.isdigit() for c in value):return value
        if any(w not in {'x','u','k','a','b','f','g','sin','cos','tan','ln','log','sqrt'} for w in identifiers):return value
        if not any(c in value for c in '=+*·/−-^²³()[]'):return value
        formula=latex(value.replace('′',"'").replace('−','-').replace('·',r'\cdot ').replace('*',r'\cdot ').replace('d/dx',r'\frac{d}{dx}'))
        return '$'+formula+'$'
    rendered=pattern.sub(decorate,text)
    if '$' not in rendered:return [{'kind':'paragraph','text':text}]
    result=[]
    # Standalone calculation chains have their own generous display area.
    for part in re.split(r'(?<=\.)\s+(?=[A-Z])|\n',rendered):
        value=part.strip();prefix=''
        if value.startswith('Worked answer: '):prefix='Worked answer:';value=value[len('Worked answer: '):]
        equation=value.rstrip('.').strip()
        if equation.startswith('$') and equation.endswith('$') and equation.count('$')==2 and '=' in equation:
            if prefix:result.append({'kind':'paragraph','text':prefix})
            result.append({'kind':'displayMath','text':equation[1:-1]})
        elif value:result.append({'kind':'paragraph','text':(prefix+' ' if prefix else '')+value})
    return result

def blocks(text,course=''):
    out=[]
    pieces=re.split(r'```([^\n`]*)\n([\s\S]*?)```',text)
    for i in range(0,len(pieces),3):
        prose=pieces[i]
        # Exact source spans: separate simple inline C tracing without rewriting it.
        match=re.search(r'(?:On paper trace:\s*|Trace:\s*|Java:\s*)(int [\s\S]*?;)(?=\s*(?:What|Enter|Write|State|$))',prose)
        if match:
            before=prose[:match.start(1)].strip();after=prose[match.end(1):].strip()
            if before:out.append({'kind':'paragraph','text':before})
            out.append({'kind':'code','text':match[1],'language':__import__('school_hq_connections').language(course) or ('java' if 'Java:' in prose else 'c')})
            prose=after
        for p in re.split(r'\n\s*\n',prose):
            p=p.strip()
            if not p:continue
            if re.match(r'^(?:int|void|class|public class)\s',p) and '\n' in p:
                first,rest=p.split('\n',1)
                out.append({'kind':'code','text':first,'language':__import__('school_hq_connections').language(course) or ('java' if p.startswith(('class','public class')) else 'c')});p=rest
            if __import__('school_hq_connections').subject(course)=='math':
                out.extend(math_blocks(p))
                continue
            out.append({'kind':'paragraph','text':p})
        if i+2<len(pieces):out.append({'kind':'code','text':pieces[i+2],'language':pieces[i+1]})
    return out

def answer_input(checker):
    kind=checker['type']
    return {'kind':{'number':'number','polynomial':'expression','sequence':'sequence','choice':'choice','multi_select':'multi_select','review':'review'}.get(kind,'short_text'),
            'placeholder':{'number':'One number or exact fraction','polynomial':'Expression in x, for example 3*x^2 + 2','sequence':'Numbers in order, separated by spaces'}.get(kind,'Your final answer'),
            **({'choices':checker['choices']} if kind in ('choice','multi_select') else {})}
