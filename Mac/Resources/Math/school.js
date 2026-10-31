function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function isCode(t){if(/[(){}\[\];=<>*&|^%#]|->|::|\+\+|--|!=/.test(t))return !/^(Problem|Question|Exercise|Part|Q|p\.|pp\.)\s/i.test(t);if(/\s/.test(t))return false;return /^[a-z]+[A-Z]\w*$|^\w+_\w+$|^[A-Z][a-z]+[A-Z]\w*$|^(int|char|void|NULL|null|true|false|malloc|free|struct|class|new|this|return)$|^\w+\.(c|h|java|py|txt)$/.test(t)}
function inline(s){return esc(s).replace(/`([^`]+)`/g,function(_,t){return isCode(t)?'<code>'+t+'</code>':'<code class="term">'+t+'</code>'}).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')}
function tex(src,display){try{return katex.renderToString(src,{displayMode:display,throwOnError:false,strict:false})}catch(e){return esc(src)}}
function report(){var h=Math.ceil(document.getElementById('c').getBoundingClientRect().height)+4;try{window.webkit.messageHandlers.size.postMessage(h)}catch(e){}}
function render(payload){
 var el=document.getElementById('c');el.innerHTML='';
 (payload.blocks||[]).forEach(function(b){
  var div=document.createElement('div');
  if(b.kind==='displayMath'){div.innerHTML=tex(b.text,true)}
  else{
   var html='';b.text.split(/(\$\$[^$]+\$\$|\$[^$\n]+\$)/g).forEach(function(part){
    if(part.length>4&&part.slice(0,2)==='$$'&&part.slice(-2)==='$$')html+=tex(part.slice(2,-2),true);
    else if(part.length>2&&part[0]==='$'&&part[part.length-1]==='$')html+=tex(part.slice(1,-1),false);
    else html+=inline(part)});
   div.innerHTML=html;div.className='p'}
  el.appendChild(div)});
 requestAnimationFrame(report);setTimeout(report,120)}
window.addEventListener('resize',report);
