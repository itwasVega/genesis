'use strict';
// Native arguments are data; never HTML or JavaScript. No answer keys enter here.
window.renderMath = function(parts,fontSize=17) {
 document.body.style.fontSize=String(Math.min(40,Math.max(14,Number(fontSize)||17)))+'px';
 const el=document.getElementById('content'); el.replaceChildren(); let errors=0;
 for (const part of parts) {
  const span=document.createElement('span'); el.appendChild(span);
  if (part.kind==='math') {
   try { katex.render(part.text,span,{displayMode:part.display===true,throwOnError:true,trust:false,strict:'error',output:'htmlAndMathml',maxExpand:200,maxSize:20}); }
   catch (_) { errors++; span.className='error'; span.textContent='Equation could not be typeset. Use the original source reference.'; }
  } else {
   span.className='text';const text=String(part.text||'');let cursor=0;
   for(const range of (Array.isArray(part.emphasis)?part.emphasis:[]).slice(0,4)){
    const start=range.start,end=start+range.length;
    if(!Number.isInteger(start)||!Number.isInteger(range.length)||start<cursor||range.length<=0||end>text.length)continue;
    span.appendChild(document.createTextNode(text.slice(cursor,start)));
    const strong=document.createElement('strong');strong.className='instruction-emphasis';strong.textContent=text.slice(start,end);span.appendChild(strong);cursor=end;
   }
   span.appendChild(document.createTextNode(text.slice(cursor)));
  }
 }
 function size(){window.webkit.messageHandlers.layout.postMessage({height:Math.ceil(document.documentElement.scrollHeight),errors});}
 document.fonts.ready.then(size); requestAnimationFrame(size);
};
new ResizeObserver(()=>{if(window.webkit)window.webkit.messageHandlers.layout.postMessage({height:Math.ceil(document.getElementById('content').scrollHeight+16)});}).observe(document.getElementById('content'));
