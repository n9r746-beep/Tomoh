/* Direct editing over backgrounds exported from the approved PowerPoint template. */
window.TomohSlideEditor = (() => {
  async function mount({container, data, api, onDirty, onError}) {
    const source = container.querySelector("#editor-inputs");
    if (!source) return;
    const wk = data.reporting_week.id, pid = data.project.id;
    let meta;
    try { meta = await api("/api/v1/weeks/"+encodeURIComponent(wk)+"/projects/"+encodeURIComponent(pid)+"/slides"); }
    catch (err) { onError("تعذر تحميل الشرائح. نموذج التعبئة متاح، وتحديثك محفوظ كما هو."); return; }
    if (!source.isConnected) return;
    const host = document.createElement("section");
    host.className = "ppt-editor";
    host.setAttribute("aria-label", "تحرير تحديث القسم داخل الشرائح");
    host.innerHTML = '<div class="ppt-toolbar"><div><strong>تحديث القسم داخل الشرائح</strong><p>اضغط على الخانات المحددة واكتب تحديثك، ثم اضغط إرسال التحديث.</p></div><div class="ppt-tools"><label>حجم العرض <select class="select ppt-zoom" aria-label="حجم الشريحة"><option value="fit">ملاءمة الشاشة</option><option value="1">١٠٠٪</option><option value="1.25">١٢٥٪</option></select></label><button type="button" class="btn btn-outline ppt-form-mode">نموذج التعبئة</button></div></div><div class="ppt-workspace"><nav class="ppt-rail" aria-label="شرائح القسم"></nav><div class="ppt-main"><div class="ppt-scroll"><div class="ppt-pages"></div></div><div class="ppt-page-footer"><button type="button" class="btn btn-outline ppt-prev">الشريحة السابقة</button><span class="ppt-page-label" aria-live="polite"></span><button type="button" class="btn btn-outline ppt-next">الشريحة التالية</button></div><div class="ppt-field-help" aria-live="polite">الخانات ذات الإطار الأزرق قابلة للتعبئة. الحفظ والإرسال من الأزرار أسفل الصفحة.</div></div></div>';
    source.before(host);
    const pages = host.querySelector(".ppt-pages"), rail = host.querySelector(".ppt-rail");
    const moves = [], seen = new Map();
    let active = 0, formMode = false;
    const escape = value => String(value ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    const find = key => {
      const [kind, code, slot] = key.split(".");
      const all = selector => Array.from(source.querySelectorAll(selector));
      if (kind === "kpi") return all(".kpi-val-input").find(n=>n.dataset.code===code);
      if (kind === "achievement" && code===data.project.project_code) return all(".ach-input").find(n=>n.dataset.slot===slot);
      if (kind === "task" && code===data.project.project_code) return all(".task-input").find(n=>n.dataset.seq===slot);
      if (kind === "challenge" && code===data.project.project_code) return source.querySelector("#ed-challenges");
      if (kind === "status" && code===data.project.project_code) return source.querySelector("#ed-project-status");
      if (kind === "deliverables" && code===data.project.project_code) return source.querySelector("#ed-deliverables");
      if (kind === "event") return all(".event-row").find(n=>n.dataset.slotKey===code);
      if (kind === "news" && code.startsWith("ITEM_")) return all(".news-body").find(n=>n.dataset.slot===code.slice(5));
      if (kind === "action_items") return source.querySelector("#action-items-tbody")?.closest(".table-wrap");
      return null;
    };
    function labelFor(node,field) {
      if (node.dataset.code) return data.kpi_definitions.find(k=>k.kpi_code===node.dataset.code)?.label_ar || "قيمة المؤشر";
      return node.closest(".form-group")?.querySelector("label")?.textContent || node.getAttribute("placeholder") || ({
        challenge:"التحديات",status:"حالة المشروع",deliverables:"المخرجات",event:"بيانات الفعالية",action_items:"مهام الاجتماع"
      })[field.key.split(".")[0]] || "تحديث القسم";
    }
    const editable = Boolean(data.editable);
    for (const slide of meta.slides) {
      const page = document.createElement("div"); page.className="ppt-page";page.dataset.number=slide.number;
      const canvas = document.createElement("div");canvas.className="ppt-canvas";canvas.style.aspectRatio=meta.width+"/"+meta.height;
      const bg=document.createElement("img");bg.src=slide.image_url;bg.alt="قالب شريحة "+slide.number+" من التقرير";bg.className="ppt-background";bg.draggable=false;
      bg.onerror=()=>{ page.classList.add("ppt-image-error"); page.querySelector(".ppt-load-error")?.remove();const note=document.createElement("p");note.className="ppt-load-error";note.textContent="تعذر تحميل خلفية الشريحة. استخدم نموذج التعبئة أو أعد تحميل الصفحة.";canvas.appendChild(note); };
      canvas.appendChild(bg);page.appendChild(canvas);
      for (const field of slide.fields) {
        const node=find(field.key);
        if (!node) continue;
        const label=labelFor(node,field);
        const box=document.createElement("div");box.className="ppt-field";
        const minH=node.matches("textarea") ? 3.4 : 2.8;
        const width=Math.max(field.w,3.5),height=Math.max(field.h,minH);
        box.style.cssText="left:"+Math.max(0,Math.min(field.x,100-width))+"%;top:"+Math.max(0,Math.min(field.y,100-height))+"%;width:"+Math.min(width,100)+"%;height:"+Math.min(height,100)+"%;--field-font:"+Math.max(14,Math.min(field.font||20,34))+"px;";
        box.dataset.key=field.key;box.title=label;
        if (seen.has(node)) {
          const mirror=document.createElement("div");mirror.className="ppt-mirror";
          const update=()=>{mirror.textContent=node.value || "غير محدث";};update();node.addEventListener("input",update);box.appendChild(mirror);box.classList.add("ppt-readonly");box.title=label+" (يُعدّل في الشريحة الأخرى)";
        } else {
          const placeholder=document.createComment("slide-field "+field.key);node.before(placeholder);
          moves.push({node,placeholder,box});seen.set(node,box);
          if (node.matches("input,textarea,select")) {
            node.setAttribute("aria-label",label);node.classList.add("ppt-inline-input");
            if(node.matches("textarea"))node.setAttribute("spellcheck","true");
          } else box.classList.add("ppt-composite-field");
          node.querySelectorAll?.("input,textarea,select").forEach((el,i)=>{if(!el.getAttribute("aria-label"))el.setAttribute("aria-label",el.placeholder || label+" "+(i+1));});
          node.addEventListener("focusin",()=>{host.querySelector(".ppt-field-help").textContent=label;});
          node.addEventListener("input",()=>{onDirty(); host.querySelector(".ppt-save-state").textContent="تغييرات لم تُحفظ بعد";});
          box.appendChild(node);
          if(!editable)box.classList.add("ppt-readonly");
        }
        canvas.appendChild(box);
      }
      const tab=document.createElement("button");tab.type="button";tab.className="ppt-tab";
      tab.innerHTML='<img alt="" src="'+escape(slide.image_url)+'"/><span>الشريحة '+slide.number+'</span>';
      tab.onclick=()=>select(Array.from(pages.children).indexOf(page));rail.appendChild(tab);
      pages.appendChild(page);
    }
    // Keep every original input and its event handlers, including overflow and uploads.
    // Unmapped/extra fields are edited on the continuation page and use the same payload.
    const extra=document.createElement("div");extra.className="ppt-page ppt-continuation";
    const extraHead=document.createElement("header");
    extraHead.innerHTML="<span>طموح</span><div><h2>بنود إضافية ومتابعة</h2><p>أضف الإنجازات والمهام أو أكمل الحقول التي تتجاوز مساحة الشريحة.</p></div>";
    extra.appendChild(extraHead);
    const extraBody=document.createElement("div");extraBody.className="ppt-extra-body";extra.appendChild(extraBody);
    pages.appendChild(extra);extraBody.appendChild(source);
    const extraTab=document.createElement("button");extraTab.type="button";extraTab.className="ppt-tab ppt-extra-tab";extraTab.innerHTML="<span>＋</span><span>بنود إضافية</span>";extraTab.onclick=()=>select(pages.children.length-1);rail.appendChild(extraTab);
    function tidy() {
      source.querySelectorAll(".form-group").forEach(group=>{
        group.classList.toggle("ppt-empty-source",!group.querySelector("input:not([type=hidden]),textarea,select,button"));
      });
      source.querySelectorAll("tr").forEach(row=>{
        if(row.querySelector("th"))return;
        row.classList.toggle("ppt-empty-source",!row.querySelector("input,textarea,select,button"));
      });
      Array.from(source.children).forEach(card=>{
        card.classList.toggle("ppt-empty-source",!card.querySelector("input:not([type=hidden]),textarea,select,button"));
      });
    }
    tidy();
    const observer=new MutationObserver(tidy);observer.observe(source,{childList:true,subtree:true});
    const saveNote=document.createElement("span");saveNote.className="ppt-save-state";saveNote.textContent=data.current.submission ? "آخر حفظ: "+new Date(data.current.submission.updated_at).toLocaleString("ar-SA") : "لم يتم حفظ تحديث بعد";
    host.querySelector(".ppt-toolbar").appendChild(saveNote);
    function select(index) {
      active=Math.max(0,Math.min(index,pages.children.length-1));
      Array.from(pages.children).forEach((p,i)=>{p.hidden=i!==active;});
      Array.from(rail.children).forEach((b,i)=>{b.classList.toggle("is-active",i===active);b.setAttribute("aria-current",i===active?"page":"false");});
      host.querySelector(".ppt-page-label").textContent=(active+1)+" / "+pages.children.length;
      host.querySelector(".ppt-prev").disabled=active===0;
      host.querySelector(".ppt-next").disabled=active===pages.children.length-1;
      host.querySelector(".ppt-scroll").scrollTop=0;
    }
    host.querySelector(".ppt-prev").onclick=()=>select(active-1);
    host.querySelector(".ppt-next").onclick=()=>select(active+1);
    host.querySelector(".ppt-zoom").onchange=e=>{pages.style.minWidth=e.target.value==="fit"?"0":(meta.width*Number(e.target.value))+"px";};
    host.querySelector(".ppt-form-mode").onclick=e=>{
      formMode=!formMode;
      if(formMode) {
        for(const m of moves)m.placeholder.after(m.node);
        host.after(source);source.classList.add("ppt-form-visible");
        host.querySelector(".ppt-workspace").hidden=true;e.target.textContent="العودة إلى الشرائح";
      } else {
        for(const m of moves)m.box.appendChild(m.node);
        extraBody.appendChild(source);source.classList.remove("ppt-form-visible");
        host.querySelector(".ppt-workspace").hidden=false;e.target.textContent="نموذج التعبئة";tidy();select(active);
      }
    };
    container.querySelectorAll("#btn-add-achievement,#btn-add-task,#btn-add-action-row").forEach(btn=>btn.addEventListener("click",()=>{onDirty();if(!formMode)select(pages.children.length-1);}));
    if(window.matchMedia("(max-width:760px)").matches){host.querySelector(".ppt-zoom").value="1";pages.style.minWidth=meta.width+"px";}
    select(meta.slides.length>1 && meta.slides[0].fields.length===0 ? 1 : 0);
  }
  return {mount};
})();
