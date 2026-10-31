import SwiftUI
import WebKit
import AppKit
import CryptoKit
import PDFKit

@MainActor final class LocalCanvas: NSObject,ObservableObject,WKNavigationDelegate,WKDownloadDelegate {
 @Published var message="Canvas uses its own Genesis browser profile. It does not inherit ChatGPT or Safari sign-ins."
 let web:WKWebView
 private var working=false
 private var runningID:String?
 private var downloadTarget:URL?
 private var downloadFinished=false
 private var downloadError:String?
 private var downloadResponse=""
 func webView(_ webView:WKWebView,navigationAction:WKNavigationAction,didBecome download:WKDownload){download.delegate=self}
 func webView(_ webView:WKWebView,navigationResponse:WKNavigationResponse,didBecome download:WKDownload){download.delegate=self}
 func download(_ download:WKDownload,decideDestinationUsing response:URLResponse,suggestedFilename:String,completionHandler:@escaping(URL?)->Void){downloadResponse="HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0), MIME \(response.mimeType ?? "unknown"), expected \(response.expectedContentLength) bytes, host \(response.url?.host ?? "unknown")";completionHandler(downloadTarget)}
 func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){decisionHandler(downloadTarget != nil && navigationAction.shouldPerformDownload ? .download:.allow)}
 func webView(_ webView:WKWebView,decidePolicyFor navigationResponse:WKNavigationResponse,decisionHandler:@escaping(WKNavigationResponsePolicy)->Void){decisionHandler(downloadTarget != nil ? .download:.allow)}
 func downloadDidFinish(_ download:WKDownload){downloadFinished=true}
 func download(_ download:WKDownload,didFailWithError error:Error,resumeData:Data?){downloadError=error.localizedDescription;downloadFinished=true}
 override init(){let config=WKWebViewConfiguration();config.websiteDataStore = .default();web=WKWebView(frame:.zero,configuration:config);super.init();web.navigationDelegate=self}
 func openSignIn(){UserDefaults.standard.set(true,forKey:"localCanvasApproved");web.load(URLRequest(url:URL(string:"https://webcourses.ucf.edu/")!));message="Sign in on UCF’s official page. Cookies stay in this app’s macOS WebKit profile; Genesis does not extract them."}
 func webView(_ webView:WKWebView,didFinish navigation:WKNavigation!){if !working,webView.url?.host=="webcourses.ucf.edu"{message="Canvas page loaded. Close this panel when your course dashboard is visible, then click Sync."}}
 func js(_ script:String) async throws -> Any {try await withCheckedThrowingContinuation{continuation in web.evaluateJavaScript(script){result,error in if let error{continuation.resume(throwing:error)}else{continuation.resume(returning:result ?? NSNull())}}}}
 func capturedTime()->String{let f=ISO8601DateFormatter();f.formatOptions=[.withInternetDateTime,.withFractionalSeconds];return f.string(from:Date())}
 func issue(_ detail:String)->NSError{NSError(domain:"Canvas",code:1,userInfo:[NSLocalizedDescriptionKey:detail])}
 func load(_ url:URL,kind:String,ident:String,root:String) async throws {
  web.load(URLRequest(url:url,cachePolicy:.reloadIgnoringLocalCacheData,timeoutInterval:25))
  let end=Date().addingTimeInterval(28);var previous="";var stable=0
  while Date()<end {
   try Task.checkCancellation()
   if let d=try? Data(contentsOf:URL(fileURLWithPath:root+"/outputs/School HQ App/Bridge/state.json")),let v=try? JSONSerialization.jsonObject(with:d) as? [String:Any],let r=v["request"] as? [String:Any],r["id"] as? String != ident || r["status"] as? String != "processing"{web.stopLoading();throw issue("Sync cancelled or replaced.")}
   if !web.isLoading,let location=web.url {
    if location.host != "webcourses.ucf.edu" || location.path.contains("/login"){try await Task.sleep(nanoseconds:250_000_000);continue}
    if kind=="detail",location.path != url.path{throw issue("Assignment redirected to another page; assessment content was not opened or started.")}
    if location.path==url.path {
     let probe="""
     (()=>{const m=document.querySelector('main,#content');if(!m)return '';const t=m.innerText.trim();if(!t||[...document.querySelectorAll('[aria-busy="true"]')].some(e=>e.getClientRects().length>0)||/^Loading[.\\s…]*$/.test(t))return '';
     if('\(kind)'==='grades'&&!document.querySelector('#grades_summary tr[id^="submission_"]'))return '';
     if('\(kind)'==='announcements'&&!m.querySelector('a[href*="/discussion_topics/"]')&&!/No announcements|There are no announcements/i.test(t))return '';
     if('\(kind)'==='assignments'&&!m.querySelector('a[href*="/assignments/"]')&&!/No assignments|There are no assignments/i.test(t))return '';
     if('\(kind)'==='files'&&!m.querySelector('tbody tr td,[role="row"] [role="cell"]')&&!/No files|This folder is empty|0 files/i.test(t))return '';
     return t;})()
     """
     let content=try await js(probe) as? String ?? ""
     if !content.isEmpty,content==previous{stable+=1}else{stable=0};previous=content
     if stable>=2{return}
    }
   }
   try await Task.sleep(nanoseconds:250_000_000)
  }
  if web.url?.host != "webcourses.ucf.edu" || web.url?.path.contains("/login")==true{throw issue("Canvas sign-in is required after the UCF redirect did not complete. Open Connect Canvas.")}
  throw issue("Canvas \(kind) page did not finish loading within 28 seconds: \(url.path)")
 }
 func capture(_ url:URL,course:String,kind:String,ident:String,root:String) async throws -> [String:Any] {
  message="Checking \(course)\(Theme.sep)\(kind)…";try await load(url,kind:kind,ident:ident,root:root)
  let script="""
  (()=>{const main=document.querySelector('main,#content');if(!main)throw Error('Course content unavailable');const body=main.innerText.trim();if(/Access Denied|You are not authorized|Log In/.test(body.slice(0,180)))throw Error('Course page denied');
  const links=[...main.querySelectorAll('a[href]')].filter(a=>a.getClientRects().length>0).map(a=>({name:a.innerText.trim(),source:a.href,context:(a.closest('li,tr,.ig-row')?.innerText||a.innerText).trim()}));let grades=null;
  if('\(kind)'==='grades'){
   const table=document.querySelector('#grades_summary');if(!table)throw Error('Grade table unavailable');
   const rows=[...table.querySelectorAll('tr')].filter(r=>r.getClientRects().length>0&&r.id.startsWith('submission_')).map(r=>{const c=[...r.children].filter(x=>['TD','TH'].includes(x.tagName));return {cells:c.map(x=>x.innerText.trim()),name:c[0]?.querySelector('a')?.innerText.trim(),source:c[0]?.querySelector('a')?.href,dropped:r.classList.contains('dropped')||(r.title||'').toLowerCase().includes('dropped')};});
   const assignments=rows.filter(r=>r.name&&r.cells.length>=7).map(r=>({name:r.name,source:r.source,group:r.cells[0].slice(r.name.length).trim(),due:r.cells[1],submitted:r.cells[2],status:r.cells[3],score_displayed:r.cells[4].replace('Click to test a different score','').replace(/\\s+/g,' ').trim()||'unknown',dropped:r.dropped}));
   const total=rows.find(r=>r.cells[0]==='Total')?.cells[4]||document.querySelector('#grade-summary-content .grade')?.innerText.trim();const check=document.querySelector('#only_consider_graded_assignments');grades={assignments,total_displayed:total,based_only_on_graded_assignments:check?check.checked:null};if(!assignments.length||!total)throw Error('Grade rows or posted total missing');
  }
  const files='\(kind)'==='files'?[...main.querySelectorAll('[role="row"],tbody tr')].filter(r=>r.getClientRects().length>0).map(r=>({cells:[...r.querySelectorAll('[role="cell"],td')].map(c=>c.innerText.trim())})):null;return JSON.stringify({body,links,grades,files,authenticated:true,loaded:true,url:location.href});})()
  """
  guard let raw=try await js(script) as? String,let bytes=raw.data(using:.utf8),var row=try JSONSerialization.jsonObject(with:bytes) as? [String:Any]else{throw issue("Canvas returned invalid page content.")}
  row["course"]=course;row["kind"]=kind;row["captured_utc"]=capturedTime();return row
 }
 func practiceFiles(_ row:[String:Any],course:String,ident:String,root:String) async throws -> [[String:Any]] {
  guard course=="COP3502C",let items=row["files"] as? [[String:Any]] else{return []}
  let directory=URL(fileURLWithPath:root+"/outputs/School HQ App/Bridge/Runs/"+ident+"/material");try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
  let indexURL=URL(fileURLWithPath:root+"/outputs/School HQ App/Bridge/canvas-material-cache.json")
  var index=((try? Data(contentsOf:indexURL)).flatMap{try? JSONSerialization.jsonObject(with:$0) as? [String:[String:String]]}) ?? [:];var output:[[String:Any]]=[]
  for item in items {
   let cells=item["cells"] as? [String] ?? [];guard cells.count>=4 else{continue}
   let candidate=cells[0].replacingOccurrences(of:"Name: ",with:"").trimmingCharacters(in:.whitespacesAndNewlines)
   guard candidate.lowercased().hasSuffix(".pdf"),["midterm","mid term","formula","quiz2"].contains(where:{candidate.lowercased().contains($0)}) else{continue}
   let key=course+"|"+candidate;let metadata=cells.joined(separator:"|")
   if let prior=index[key],prior["metadata"]==metadata,let path=prior["path"],FileManager.default.fileExists(atPath:path){output.append(["course":course,"name":candidate,"path":path,"source":prior["source"] ?? "","result":"unchanged"]);continue}
   let encoded=String(data:try JSONSerialization.data(withJSONObject:candidate,options:.fragmentsAllowed),encoding:.utf8)!
   let click="""
   (()=>{const target=\(encoded);const rows=[...document.querySelectorAll('main [role="row"],#content [role="row"],main tbody tr,#content tbody tr')];const r=rows.find(r=>r.innerText.includes(target));if(!r)throw Error('Visible file row changed');const cell=r.querySelector('[role="cell"],td');if(!cell)throw Error('Visible file name cell absent');cell.click();cell.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));return true;})()
   """
   _ = try await js(click);var linkReady=false
   for _ in 0..<50 {if try await js("Boolean([...document.querySelectorAll('a[href]')].find(a=>a.innerText.trim()==='Download'&&a.getClientRects().length>0))") as? Bool == true{linkReady=true;break};try await Task.sleep(nanoseconds:200_000_000)}
   guard linkReady else{throw issue("Practice PDF download link did not appear: "+candidate)}
   let source=web.url?.absoluteString ?? "";let safe=candidate.replacingOccurrences(of:"/",with:"_");downloadTarget=directory.appendingPathComponent(safe);downloadFinished=false;downloadError=nil
   _ = try await js("(()=>{const a=[...document.querySelectorAll('a[href]')].find(a=>a.innerText.trim()==='Download'&&a.getClientRects().length>0);if(!a)throw Error('Download link absent');a.click();return true;})()")
   for _ in 0..<150 {if downloadFinished{break};try await Task.sleep(nanoseconds:200_000_000)}
   guard downloadFinished,downloadError==nil,let target=downloadTarget,let bytes=try? Data(contentsOf:target),bytes.starts(with:Data("%PDF-".utf8))else{throw issue("Practice PDF download failed: "+candidate+" "+(downloadError ?? "timeout or invalid PDF"))}
   index[key]=["metadata":metadata,"path":target.path,"source":source];output.append(["course":course,"name":candidate,"path":target.path,"source":source,"result":"downloaded"])
   try JSONSerialization.data(withJSONObject:index,options:[.prettyPrinted,.sortedKeys]).write(to:indexURL,options:.atomic)
   _ = try await js("(()=>{const b=[...document.querySelectorAll('button')].find(b=>(b.getAttribute('aria-label')==='Close'||b.innerText.trim()==='Close')&&b.getClientRects().length>0);if(b)b.click();return true;})()")
  }
  downloadTarget=nil;return output
 }
 @Published var sessionTesting=false
 @Published var sessionTestResult=""
 // Explicit diagnostic only: one known student course, one read-only GET, no cookie/token extraction.
 // This does not change source readiness or replace the independently verified page collector.
 func testSession(root:String){
  guard !working,!sessionTesting else{sessionTestResult="Wait for Canvas collection to finish before testing.";return}
  guard UserDefaults.standard.bool(forKey:"localCanvasApproved"),web.url?.host=="webcourses.ucf.edu",web.url?.path.contains("/login") != true else{sessionTestResult="Open Connect Canvas and sign in first.";return}
  guard let selected = try? GenesisConfiguration.load(root: root).courses.first else { sessionTestResult="Add your classes in Settings first."; return }
  sessionTesting=true;sessionTestResult="Testing one read-only assignment request…"
  Task {
   defer{sessionTesting=false}
   do{
    let script="""
    const started=performance.now();const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
    try{
     if(location.origin!=='https://webcourses.ucf.edu')throw Error('Canvas origin changed');
     const path='/api/v1/courses/\(selected.canvas_id)/assignments?per_page=100';
     const response=await fetch(path,{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store',headers:{'Accept':'application/json'},signal:controller.signal});
     const type=response.headers.get('content-type')||'';
     if(!response.ok)return JSON.stringify({status:response.status,elapsed_ms:performance.now()-started,error:'Request refused; no alternate authentication attempted',endpoint:path});
     if(!type.includes('json'))throw Error('Expected JSON; session may require sign-in');
     const raw=await response.text();if(raw.length>5000000)throw Error('Response exceeded diagnostic limit');
     const items=JSON.parse(raw.replace(/^while\\s*\\(1\\);\\s*/,''));if(!Array.isArray(items))throw Error('Expected assignment array');
     return JSON.stringify({status:response.status,elapsed_ms:performance.now()-started,endpoint:path,has_more:/rel="next"/.test(response.headers.get('link')||''),assignments:items.map(a=>({id:String(a.id),name:a.name,due_at:a.due_at,html_url:a.html_url,published:a.published}))});
    }finally{clearTimeout(timeout)}
    """
    let value=try await web.callAsyncJavaScript(script,arguments:[:],in:nil,contentWorld:.page)
    guard let raw=value as? String,let data=raw.data(using:.utf8),var result=try JSONSerialization.jsonObject(with:data) as? [String:Any]else{throw issue("Session diagnostic returned invalid data.")}
    result["tested_at"]=capturedTime();result["diagnostic_only"]=true;result["readiness_changed"]=false
    let bridge=URL(fileURLWithPath:root+"/outputs/School HQ App/Bridge")
    if let stateData=try? Data(contentsOf:bridge.appendingPathComponent("state.json")),let state=try? JSONSerialization.jsonObject(with:stateData) as? [String:Any],let request=state["request"] as? [String:Any],let ident=request["id"] as? String,let captureData=try? Data(contentsOf:bridge.appendingPathComponent("LocalCanvas/"+ident+"-result.json")),let capture=try? JSONSerialization.jsonObject(with:captureData) as? [String:Any],let rows=capture["captures"] as? [[String:Any]],let row=rows.first(where:{$0["course"] as? String==selected.id && $0["kind"] as? String=="assignments"}),let links=row["links"] as? [[String:String]]{
     let pageIDs=Set(links.compactMap{item->String? in guard let u=URL(string:item["source"] ?? ""),u.path.range(of:"^/courses/\(selected.canvas_id)/assignments/[0-9]+$",options:.regularExpression) != nil else{return nil};return u.lastPathComponent})
     let apiIDs=Set((result["assignments"] as? [[String:Any]] ?? []).compactMap{$0["id"] as? String})
     result["comparison_request_id"]=ident;result["page_assignment_count"]=pageIDs.count;result["missing_visible_assignment_ids"]=Array(pageIDs.subtracting(apiIDs)).sorted();result["additional_assignment_ids"]=Array(apiIDs.subtracting(pageIDs)).sorted()
    }
    let folder=bridge.appendingPathComponent("Diagnostics");try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
    let file=folder.appendingPathComponent("canvas-session-test.json");try JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]).write(to:file,options:.atomic);try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
    if let error=result["error"] as? String{sessionTestResult="Session test: \(error) (HTTP \(result["status"] ?? "unknown")). Existing collection is unchanged."}
    else{let count=(result["assignments"] as? [Any])?.count ?? 0;let ms=(result["elapsed_ms"] as? Double) ?? 0;let missing=(result["missing_visible_assignment_ids"] as? [String])?.count;sessionTestResult=String(format:"Read-only session request: %d assignments in %.0f ms. ",count,ms)+(missing.map{"\($0) visible assignments missing. "} ?? "Page comparison unavailable. ")+"Diagnostic only; collection and readiness are unchanged."}
   }catch{sessionTestResult="Session test failed: "+error.localizedDescription+". Existing collection is unchanged."}
  }
 }
 func check(root:String,ident:String){
  guard !working,!sessionTesting,runningID != ident else{return};let folder=URL(fileURLWithPath:root+"/outputs/School HQ App/Bridge/LocalCanvas")
  guard let data=try? Data(contentsOf:folder.appendingPathComponent(ident+"-request.json")),let request=try? JSONSerialization.jsonObject(with:data) as? [String:Any],request["request_id"] as? String==ident else{return}
  working=true;runningID=ident
  Task {
   var captures:[[String:Any]]=[];var failure:String?;var limits:[String]=[];var materials:[[String:Any]]=[];var diagnostics:[String:Any]=[:]
   do{
    let courses = try GenesisConfiguration.load(root: root).courses.map { [$0.id, $0.canvas_id] }
    guard !courses.isEmpty else { throw issue("Add your classes and Canvas course IDs in Settings first.") }
    guard UserDefaults.standard.bool(forKey:"localCanvasApproved")else{throw issue("Use Connect Canvas and sign in within Genesis.")}
    // Posted grade totals and their calculation basis stay independently checked in the UI.
    for course in courses {captures.append(try await capture(URL(string:"https://webcourses.ucf.edu/courses/\(course[1])/grades")!,course:course[0],kind:"grades",ident:ident,root:root))}
    message="Checking every accessible assignment, announcement, folder and module…"
    let file=Bundle.main.url(forResource:"CanvasStructured",withExtension:"js")!
    let script=try String(contentsOf:file,encoding:.utf8)
    let value=try await web.callAsyncJavaScript(script,arguments:["required":courses],in:nil,contentWorld:.page)
    guard let raw=value as? String,let data=raw.data(using:.utf8),let result=try JSONSerialization.jsonObject(with:data) as? [String:Any],result["pagination_complete"] as? Bool==true else{throw issue("Structured Canvas collection incomplete")}
    try ensureActive(root,ident)
    captures += result["captures"] as? [[String:Any]] ?? [];diagnostics=result
    var failures=result["failures"] as? [[String:Any]] ?? []
    for resource in result["resources"] as? [[String:Any]] ?? [] {
     try ensureActive(root,ident)
     do{materials.append(try await downloadResource(resource,root:root,ident:ident))}catch{failures.append(["course":resource["course"] ?? "","resource":resource["source"] ?? "","classification":"download_failed","error":error.localizedDescription,"fixable":true])}
    }
    diagnostics["failures"]=failures;diagnostics.removeValue(forKey:"resources");diagnostics.removeValue(forKey:"captures")
    limits=failures.map{String(describing:$0["course"] ?? "")+" "+String(describing:$0["resource"] ?? "")+": "+String(describing:$0["error"] ?? "")}
    limits.append("Paginated assignment descriptions/submission metadata, announcements, course/folder files and module-linked pages checked. Quiz questions, assessment launch and external authenticated tools are excluded; exclusions are enumerated individually.")
   }catch{failure=error.localizedDescription}
   let result:[String:Any]=["request_id":ident,"captures":captures,"materials":materials,"diagnostics":diagnostics,"error":failure as Any? ?? NSNull(),"coverage_limits":limits]
   do{try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true);try JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]).write(to:folder.appendingPathComponent(ident+"-result.json"),options:.atomic);try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:folder.appendingPathComponent(ident+"-result.json").path)}catch{message="Could not save Canvas result: "+error.localizedDescription}
   message=failure ?? "Canvas structured captures saved for independent validation.";working=false
  }
 }
 func ensureActive(_ root:String,_ ident:String)throws {
  let data=try Data(contentsOf:URL(fileURLWithPath:root+"/outputs/School HQ App/Bridge/state.json"));let v=try JSONSerialization.jsonObject(with:data) as? [String:Any];let r=v?["request"] as? [String:Any]
  if r?["id"] as? String != ident || r?["status"] as? String != "processing" {throw issue("Sync cancelled or replaced")}
 }
 func downloadResource(_ resource:[String:Any],root:String,ident:String)async throws->[String:Any]{
  let course=resource["course"] as? String ?? "",id=resource["id"] as? String ?? "",name=resource["name"] as? String ?? "file",size=(resource["size"] as? NSNumber)?.intValue ?? 0
  guard size>0,size<=80*1024*1024,let url=URL(string:resource["download"] as? String ?? ""),url.host=="webcourses.ucf.edu",url.path=="/files/"+id+"/download" else{throw issue("File size/destination outside approved download bounds")}
  let base=URL(fileURLWithPath:root+"/outputs/School HQ App/Bridge"),indexURL=base.appendingPathComponent("canvas-material-cache-v2.json")
  var index=((try? Data(contentsOf:indexURL)).flatMap{try? JSONSerialization.jsonObject(with:$0) as? [String:[String:Any]]}) ?? [:]
  if index[id]==nil,let legacy=index[course+"|"+id],let p=legacy["path"] as? String,let raw=try? Data(contentsOf:URL(fileURLWithPath:p)),raw.count==size {var adopted=legacy;adopted["sha256"]=SHA256.hash(data:raw).map{String(format:"%02x",$0)}.joined();index[id]=adopted;index.removeValue(forKey:course+"|"+id);try JSONSerialization.data(withJSONObject:index,options:[.prettyPrinted,.sortedKeys]).write(to:indexURL,options:.atomic)}
  let key=id,version=String(describing:resource["updated_at"] ?? "")+"|"+String(size)
  if let old=index[key],old["version"] as? String==version,let path=old["path"] as? String,let bytes=try? Data(contentsOf:URL(fileURLWithPath:path)),bytes.count==size,old["sha256"] as? String==SHA256.hash(data:bytes).map({String(format:"%02x",$0)}).joined() {return old.merging(["result":"unchanged","course":course]){_,new in new}}
  let directory=base.appendingPathComponent("Runs/"+ident+"/material");try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
  let target=directory.appendingPathComponent(id+"-"+name.replacingOccurrences(of:"/",with:"_"));downloadTarget=target;downloadFinished=false;downloadError=nil
  defer{downloadTarget=nil}
  message="Downloading "+course+Theme.sep+name
  // A stale CDN redirect can return HTTP 401. Retry once with a fresh same-origin GET;
  // no cookies/tokens are copied and no signed URL query is logged.
  var attempts:[String]=[]
  for attempt in 0..<3 {
   downloadFinished=false;downloadError=nil;downloadResponse=""
   if FileManager.default.fileExists(atPath:target.path){try FileManager.default.moveItem(at:target,to:directory.appendingPathComponent(target.lastPathComponent+".incomplete-"+UUID().uuidString))}
   var resolved=attempt==0 ? url:URL(string:url.absoluteString+"&hq_refresh="+String(Int(Date().timeIntervalSince1970*1000)))!
   if attempt==2 {
    let script="""
    if(location.origin!=='https://webcourses.ucf.edu')throw Error('Canvas origin changed');
    const response=await fetch('/api/v1/files/'+fileID+'?hq_refresh='+Date.now(),{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store',headers:{Accept:'application/json'}});
    if(!response.ok)throw Error('Fresh file metadata HTTP '+response.status);
    const data=JSON.parse((await response.text()).replace(/^while\\s*\\(1\\);\\s*/,''));return data.url;
    """
    guard let value=try await web.callAsyncJavaScript(script,arguments:["fileID":id],in:nil,contentWorld:.page) as? String,let fresh=URL(string:value),fresh.scheme=="https",let host=fresh.host,host=="webcourses.ucf.edu" || host.hasSuffix(".inscloudgate.net") || host.hasSuffix(".instructure.com") else{throw issue("Fresh file URL destination refused")}
    resolved=fresh
   }
   var request=URLRequest(url:resolved,cachePolicy:.reloadIgnoringLocalAndRemoteCacheData,timeoutInterval:30);request.setValue("no-cache",forHTTPHeaderField:"Cache-Control")
   let download=await web.startDownload(using:request);download.delegate=self
   let end=Date().addingTimeInterval(60)
   while !downloadFinished && Date()<end{try ensureActive(root,ident);try await Task.sleep(nanoseconds:100_000_000)}
   attempts.append(downloadResponse+(downloadError.map{"; "+$0} ?? ""))
   if downloadFinished,downloadError==nil,let bytes=try? Data(contentsOf:target),bytes.count==size{break}
   if !downloadResponse.contains("HTTP 401") && !downloadResponse.contains("HTTP 403"){break}
  }
  guard downloadFinished,downloadError==nil,let bytes=try? Data(contentsOf:target),bytes.count==size else{throw issue(name+": download timeout/size mismatch; "+attempts.joined(separator:"; retry: "))}
  if name.lowercased().hasSuffix(".pdf"),(!bytes.starts(with:Data("%PDF-".utf8)) || (PDFDocument(data:bytes)?.pageCount ?? 0)==0){throw issue("Downloaded PDF failed signature/page validation; "+downloadResponse)}
  let output:[String:Any]=["course":course,"id":id,"name":name,"path":target.path,"source":resource["source"] ?? "","version":version,"sha256":SHA256.hash(data:bytes).map({String(format:"%02x",$0)}).joined(),"result":"downloaded","response":attempts.joined(separator:"; retry: ")]
  index[key]=output;try JSONSerialization.data(withJSONObject:index,options:[.prettyPrinted,.sortedKeys]).write(to:indexURL,options:.atomic);return output
 }

}
struct CanvasWebView:NSViewRepresentable{let canvas:LocalCanvas;func makeNSView(context:Context)->WKWebView{canvas.web};func updateNSView(_ view:WKWebView,context:Context){}}
struct CanvasSignIn:View{
 @ObservedObject var canvas:LocalCanvas;var done:()->Void
 var body:some View{VStack(alignment:.leading,spacing:14){HStack{Text("Canvas connection").font(.title2);Spacer();Button("Done"){done()}};Text(canvas.message).font(.system(size:13)).foregroundStyle(.secondary);Button("Open UCF sign-in"){canvas.openSignIn()}.disabled(canvas.message.hasPrefix("Checking"));CanvasWebView(canvas:canvas).frame(minWidth:780,minHeight:570)}.padding(20).frame(width:900,height:730)}
}

struct CanvasSessionDiagnostic:View{
 @ObservedObject var canvas:LocalCanvas;let root:String
 var body:some View{VStack(alignment:.leading,spacing:9){Text("Checks one CS1 assignment endpoint using this app’s existing sign-in. No credentials are extracted; this diagnostic does not change collection readiness.").font(.system(size:12));Button(canvas.sessionTesting ? "Testing…":"Test signed-in request"){canvas.testSession(root:root)}.disabled(canvas.sessionTesting);if !canvas.sessionTestResult.isEmpty{Text(canvas.sessionTestResult).font(.system(size:12)).textSelection(.enabled)}}}
}
