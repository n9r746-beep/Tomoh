/* TOMOH Weekly Report Automation — Phase 2 Arabic RTL SPA Client
 * Connects directly to FastAPI /api/v1 endpoints with session cookies, RBAC views,
 * dynamic per-project forms, coordinator dashboard, reminders, and PPTX generation.
 */
(() => {
  const state = {
    user: null,
    view: "login", // login | employee_home | project_editor | coord_dashboard | coord_reminders | coord_settings
    selectedWeekId: null,
    selectedProjectId: null,
    dirty: false,
    aiEnabled: false,
    editorReturnView: "employee_home",
  };

  const STATUS_OPTIONS = [
    { code: "on_track", label: "وفق المخطط", color: "#00B050" },
    { code: "delayed", label: "متأخر", color: "#FFC000" },
    { code: "critically_delayed", label: "متأخر جدًا", color: "#FF0000" },
    { code: "on_hold", label: "معلق", color: "#7030A0" },
    { code: "completed", label: "مكتمل", color: "#007094" },
    { code: "not_started", label: "لم يبدأ", color: "#A6A6A6" },
  ];

  const TASK_STATUSES = ["جاري", "مكتمل", "متأخر", "معلق", "ملغي"];

  const $ = (id) => document.getElementById(id);

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showToast(message, type = "info") {
    const el = document.createElement("div");
    el.className = `toast ${type === "error" ? "toast-error" : type === "success" ? "toast-success" : ""}`;
    el.textContent = message;
    $("toast-container").appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  async function api(path, options = {}) {
    const opts = {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", ...(options.headers || {}) },
      ...options,
    };
    if (opts.body && !(opts.body instanceof FormData) && !opts.headers["Content-Type"]) {
      opts.headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, opts);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok) {
      const msg = data?.error?.message || `خطأ في الاتصال (${res.status})`;
      throw new Error(msg);
    }
    return data;
  }

  function openModal(title, htmlContent) {
    $("modal-title").textContent = title;
    $("modal-body").innerHTML = htmlContent;
    $("modal-backdrop").classList.remove("hidden");
  }

  function closeModal() {
    $("modal-backdrop").classList.add("hidden");
    $("modal-body").innerHTML = "";
  }

  $("modal-close").addEventListener("click", closeModal);
  $("modal-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "modal-backdrop") closeModal();
  });

  window.addEventListener("beforeunload", (e) => {
    if (state.dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  function formatDateShort(iso) {
    if (!iso) return "—";
    return iso.replace("T", " ").slice(0, 16);
  }

  function renderTopbar() {
    if (!state.user) {
      $("topbar").classList.add("hidden");
      return;
    }
    $("topbar").classList.remove("hidden");
    $("user-name-label").textContent = state.user.full_name_ar;
    const isCoord = state.user.role === "coordinator" || state.user.role === "admin";
    $("user-role-badge").textContent = isCoord ? "منسق التقرير" : "موظف";

    const nav = $("topnav");
    nav.innerHTML = "";
    const tabs = isCoord
      ? [
          { id: "coord_dashboard", label: "لوحة المتابعة والتوليد" },
          { id: "coord_reminders", label: "التذكيرات والمواعيد" },
          { id: "coord_settings", label: "إدارة المشاريع والتكليفات" },
          { id: "employee_home", label: "تحديثاتي الأسبوعية" },
        ]
      : [{ id: "employee_home", label: "تحديثاتي الأسبوعية" }];

    tabs.forEach((t) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `nav-tab ${state.view === t.id ? "active" : ""}`;
      btn.textContent = t.label;
      btn.onclick = () => navigate(t.id);
      nav.appendChild(btn);
    });
  }

  $("btn-password").addEventListener("click", () => {
    openModal("تغيير كلمة المرور", `<form id="password-form">
      <div class="form-group"><label class="form-label">كلمة المرور الحالية</label><input class="input" type="password" id="current-password" autocomplete="current-password" required /></div>
      <div class="form-group"><label class="form-label">كلمة المرور الجديدة (١٢ حرفًا على الأقل)</label><input class="input" type="password" id="new-password" autocomplete="new-password" minlength="12" required /></div>
      <button type="submit" class="btn btn-primary">حفظ وتسجيل الخروج</button></form>`);
    $("password-form").onsubmit=async(e)=>{e.preventDefault();try{
      await api("/api/v1/auth/password",{method:"POST",body:JSON.stringify({current_password:$("current-password").value,new_password:$("new-password").value})});
      closeModal();state.user=null;state.dirty=false;state.view="login";render();showToast("تم تغيير كلمة المرور. سجل الدخول مجددًا.","success");
    }catch(err){showToast(err.message,"error");}};
  });

  $("btn-logout").addEventListener("click", async () => {
    try {
      await api("/api/v1/auth/logout", { method: "POST" });
    } catch (_) {}
    state.user = null;
    state.dirty = false;
    state.view = "login";
    render();
  });

  function navigate(view, params = {}) {
    if (state.dirty && !confirm("لديك تعديلات غير محفوظة، هل تريد المغادرة دون حفظ؟")) {
      return;
    }
    state.dirty = false;
    state.view = view;
    if (params.weekId) state.selectedWeekId = params.weekId;
    if (params.projectId) state.selectedProjectId = params.projectId;
    if (params.returnView) state.editorReturnView = params.returnView;
    render();
  }

  async function render() {
    renderTopbar();
    const main = $("main-content");
    main.innerHTML = `<div class="card">جاري تحميل البيانات...</div>`;
    try {
      if (!state.user || state.view === "login") {
        await renderLogin(main);
      } else if (state.view === "employee_home") {
        await renderEmployeeHome(main);
      } else if (state.view === "project_editor") {
        await renderProjectEditor(main);
      } else if (state.view === "coord_dashboard") {
        await renderCoordinatorDashboard(main);
      } else if (state.view === "coord_reminders") {
        await renderCoordinatorReminders(main);
      } else if (state.view === "coord_settings") {
        await renderCoordinatorSettings(main);
      }
    } catch (err) {
      main.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
    }
  }

  /* ==================== 1. LOGIN VIEW ==================== */
  async function renderLogin(container) {
    container.innerHTML = `
      <div class="login-wrap">
        <img src="/assets/monshaat-logo.png" alt="منشآت" class="login-logo" />
        <h1 class="login-title">التقرير الأسبوعي — طموح</h1>
        <p class="login-sub">إدارة علاقات نمو المنشآت</p>
        <form id="login-form" style="text-align:right">
          <div class="form-group"><label class="form-label" for="login-email">البريد الإلكتروني</label>
          <input id="login-email" class="input" type="email" autocomplete="username" dir="ltr" required /></div>
          <div class="form-group"><label class="form-label" for="login-password">كلمة المرور</label>
          <input id="login-password" class="input" type="password" autocomplete="current-password" dir="ltr" required /></div>
          <button type="submit" id="btn-login-submit" class="btn btn-primary" style="width:100%">تسجيل الدخول</button>
        </form>
      </div>`;
    $("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const button = $("btn-login-submit"); button.disabled = true;
      try {
        const res = await api("/api/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({ email: $("login-email").value, password: $("login-password").value }),
        });
        state.user = res.user;
        const isCoord = res.user.role === "coordinator" || res.user.role === "admin";
        state.view = isCoord ? "coord_dashboard" : "employee_home";
        showToast(`مرحباً أ. ${res.user.full_name_ar}`, "success");
        render();
      } catch (err) {
        showToast(err.message, "error");
        button.disabled = false;
      }
    });
  }

  /* ==================== 2. EMPLOYEE HOMEPAGE ==================== */
  async function renderEmployeeHome(container) {
    const q = state.selectedWeekId ? `?week_id=${encodeURIComponent(state.selectedWeekId)}` : "";
    const data = await api(`/api/v1/my-dashboard${q}`);
    state.aiEnabled = Boolean(data.ai_assistant_enabled);
    const wk = data.reporting_week;
    if (wk) state.selectedWeekId = wk.id;

    if (!wk) {
      container.innerHTML = `
        <div class="page-header">
          <div>
            <h1 class="page-title">تحديثاتي الأسبوعية</h1>
            <p class="page-subtitle">لا يوجد أسبوع تقرير مفتوح حالياً، يرجى التواصل مع منسق التقرير.</p>
          </div>
        </div>
      `;
      return;
    }

    const total = data.assigned_sections.length;
    const done = data.assigned_sections.filter((s) => s.status === "submitted" || s.status === "approved").length;
    const remReq = data.assigned_sections.reduce((acc, s) => acc + s.remaining_required_count, 0);

    const cardsHtml = data.assigned_sections
      .map(
        (s) => `
      <div class="section-card" data-project-code="${escapeHtml(s.project_code)}">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;">
            <h3>${escapeHtml(s.title_ar)}</h3>
            <span class="badge badge-${escapeHtml(s.status)}">${escapeHtml(s.status_ar)}</span>
          </div>
          <div class="meta-row">
            <span>الشرائح المرتبطة: ${s.slides.length ? s.slides.join("، ") : "—"}</span>
            <span>آخر تحديث: ${formatDateShort(s.last_updated)}</span>
            <span>الحقول الإلزامية المتبقية: <strong>${s.remaining_required_count}</strong></span>
          </div>
          ${
            s.reviewer_notes_ar
              ? `<div class="alert alert-warn" style="margin-top:10px;margin-bottom:0;"><strong>ملاحظة المنسق:</strong> ${escapeHtml(s.reviewer_notes_ar)}</div>`
              : ""
          }
        </div>
        <div style="margin-top:8px;">
          <button type="button" class="btn btn-primary btn-sm btn-open-project" data-pid="${escapeHtml(s.project_id)}">
            ${wk.status === "locked" ? "عرض التحديث (مقفل)" : "تحديث القسم"}
          </button>
        </div>
      </div>`
      )
      .join("");

    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">تحديثاتي الأسبوعية</h1>
          <p class="page-subtitle">
            التقرير الأسبوعي رقم (${wk.week_number}) — الفترة: ${escapeHtml(wk.start_date)} إلى ${escapeHtml(wk.end_date)}
            ${wk.submission_deadline ? ` | الموعد النهائي للتسليم: <strong>${escapeHtml(wk.submission_deadline)}</strong>` : ""}
          </p>
        </div>
        <div class="btn-group">
          <select id="emp-week-select" class="select" style="width:auto">
            ${data.weeks
              .map(
                (w) =>
                  `<option value="${escapeHtml(w.id)}" ${w.id === wk.id ? "selected" : ""}>الأسبوع ${w.week_number} (${w.fiscal_year})</option>`
              )
              .join("")}
          </select>
        </div>
      </div>

      ${wk.status === "locked" ? `<div class="alert alert-warn">هذا الأسبوع مقفل من قِبل المنسق، لا يمكن تعديل البيانات حالياً.</div>` : ""}

      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">رقم التقرير الحالي</div><div class="kpi-value">${wk.week_number}</div></div>
        <div class="kpi-card"><div class="kpi-label">الأقسام المسندة إليك</div><div class="kpi-value">${total}</div></div>
        <div class="kpi-card"><div class="kpi-label">تم تسليمها</div><div class="kpi-value">${done} / ${total}</div></div>
        <div class="kpi-card"><div class="kpi-label">الحقول الإلزامية المتبقية</div><div class="kpi-value">${remReq}</div></div>
      </div>

      <div class="sections-grid">${cardsHtml || `<div class="card">لا توجد أقسام مسندة لحسابك حالياً.</div>`}</div>
    `;

    $("emp-week-select").addEventListener("change", (e) => {
      state.selectedWeekId = e.target.value;
      render();
    });

    container.querySelectorAll(".btn-open-project").forEach((btn) => {
      btn.addEventListener("click", () => {
        navigate("project_editor", {
          weekId: wk.id,
          projectId: btn.dataset.pid,
          returnView: "employee_home",
        });
      });
    });
  }

  /* ==================== 3. SCOPED PROJECT EDITOR ==================== */
  async function renderProjectEditor(container) {
    const data = await api(
      `/api/v1/weeks/${encodeURIComponent(state.selectedWeekId)}/projects/${encodeURIComponent(state.selectedProjectId)}`
    );
    const wk = data.reporting_week;
    const proj = data.project;
    const cfg = proj.section_config || {};
    const inputs = cfg.inputs || [];
    const editable = Boolean(data.editable);
    const cur = data.current;
    const prev = data.previous;
    const curVersion = cur.submission ? cur.submission.version : null;

    // Build ONLY the input blocks relevant to this project's manifest
    let blocksHtml = "";

    // A. Numerical KPIs
    if (inputs.includes("kpis") && data.kpi_definitions.length) {
      const kpiMap = {};
      (cur.kpis || []).forEach((k) => (kpiMap[k.kpi_code] = k));
      const rows = data.kpi_definitions
        .map((kd) => {
          const kv = kpiMap[kd.kpi_code];
          const val = kv && kv.numeric_value !== null && kv.numeric_value !== undefined ? kv.numeric_value : "";
          const den = kv && kv.denominator_value !== null && kv.denominator_value !== undefined ? kv.denominator_value : kd.annual_target || "";
          const isRatio = kd.aggregation_type === "ratio";
          return `
            <tr>
              <td>
                <strong>${escapeHtml(kd.label_ar)}</strong>
                <div class="form-hint">${escapeHtml(kd.kpi_code)} ${kd.auto_accumulate_from ? "• تراكمي آلي" : ""}</div>
              </td>
              <td style="width:140px">
                <input type="number" step="any" min="0" class="input kpi-val-input"
                  data-code="${escapeHtml(kd.kpi_code)}"
                  data-ratio="${isRatio ? "1" : "0"}"
                  value="${escapeHtml(val)}"
                  placeholder="فارغ = غير محدث" ${editable ? "" : "disabled"} />
              </td>
              <td style="width:120px">
                ${
                  isRatio
                    ? `<input type="number" step="any" min="1" class="input kpi-den-input" data-code="${escapeHtml(kd.kpi_code)}" value="${escapeHtml(den)}" ${editable ? "" : "disabled"} />`
                    : `<span class="form-hint">${kd.annual_target ? `المستهدف: ${kd.annual_target}` : "—"}</span>`
                }
              </td>
            </tr>`;
        })
        .join("");

      blocksHtml += `
        <div class="card">
          <div class="card-header"><h2 class="card-title">المؤشرات الرقمية (KPIs)</h2></div>
          <div class="alert alert-info">تنبيه: اترك الحقل فارغاً إذا لم تتوفر بيانات جديدة؛ القيمة (0) تعني صفراً فعلياً ولن يتم استبدال القيم المفقودة بصفر تلقائياً.</div>
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>المؤشر</th><th>القيمة</th><th>المقام / المستهدف</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>`;
    }

    // B. Project Status & Deliverables
    if (inputs.includes("project_status")) {
      const curSt = cur.project_status?.status_code || "on_track";
      const curDeliv = cur.project_status?.deliverables_override_ar || proj.deliverables_ar || "";
      blocksHtml += `
        <div class="card">
          <div class="card-header"><h2 class="card-title">حالة المشروع والمخرجات</h2></div>
          <div class="form-group">
            <label class="form-label" for="ed-project-status">حالة المشروع الحالية (تنعكس لونياً في العرض)</label>
            <select id="ed-project-status" class="select" ${editable ? "" : "disabled"}>
              ${STATUS_OPTIONS.map(
                (o) => `<option value="${o.code}" ${curSt === o.code ? "selected" : ""}>${o.label}</option>`
              ).join("")}
            </select>
          </div>
          ${
            inputs.includes("deliverables")
              ? `<div class="form-group">
                   <label class="form-label" for="ed-deliverables">المخرجات (كل مخرج في سطر مستقل)</label>
                   <textarea id="ed-deliverables" class="textarea" ${editable ? "" : "disabled"}>${escapeHtml(curDeliv)}</textarea>
                 </div>`
              : ""
          }
        </div>`;
    }

    // C. Previous Week's Achievements
    if (inputs.includes("achievements")) {
      const maxAch = Math.max(cfg.max_achievements || 3, ...(cur.achievements || []).map(a => a.slot_index));
      const achMap = {};
      (cur.achievements || []).forEach((a) => (achMap[a.slot_index] = a.content_ar));
      let achInputs = "";
      for (let i = 1; i <= maxAch; i++) {
        achInputs += `
          <div class="form-group">
            <label class="form-label">إنجاز الأسبوع الماضي (${i})</label>
            <textarea class="textarea ach-input" data-slot="${i}" maxlength="220" placeholder="أدخل الإنجاز الفعلي لهذا الأسبوع..." ${editable ? "" : "disabled"}>${escapeHtml(achMap[i] || "")}</textarea>
          </div>`;
      }
      blocksHtml += `
        <div class="card">
          <div class="card-header"><h2 class="card-title">إنجازات الأسبوع الماضي</h2></div>
          ${achInputs}
          ${editable ? `<button type="button" id="btn-add-achievement" class="btn btn-outline btn-sm">+ إضافة إنجاز</button>` : ""}
          <p class="form-hint">يمكن إضافة حتى ١٠ إنجازات. البنود الزائدة عن القالب تظهر في شرائح متابعة.</p>
        </div>`;
    }

    // D. Current Week's Tasks (Project Tasks)
    if (inputs.includes("upcoming_tasks")) {
      const maxT = Math.max(cfg.max_tasks || 2, ...(cur.upcoming_tasks || []).filter(t => t.task_kind === "project_task").map(t => t.sequence_no));
      const tMap = {};
      (cur.upcoming_tasks || [])
        .filter((t) => t.task_kind === "project_task")
        .forEach((t) => (tMap[t.sequence_no] = t.title_ar));
      let tInputs = "";
      for (let i = 1; i <= maxT; i++) {
        tInputs += `
          <div class="form-group">
            <label class="form-label">مهمة الأسبوع الحالي (${i})</label>
            <textarea class="textarea task-input" data-seq="${i}" maxlength="200" placeholder="أدخل المهمة المخططة للأسبوع الحالي..." ${editable ? "" : "disabled"}>${escapeHtml(tMap[i] || "")}</textarea>
          </div>`;
      }
      blocksHtml += `
        <div class="card">
          <div class="card-header"><h2 class="card-title">مهام الأسبوع الحالي</h2></div>
          ${tInputs}
          ${editable ? `<button type="button" id="btn-add-task" class="btn btn-outline btn-sm">+ إضافة مهمة</button>` : ""}
          <p class="form-hint">يمكن إضافة حتى ٢٠ مهمة. البنود الزائدة عن القالب تظهر في شرائح متابعة.</p>
        </div>`;
    }

    // E. Challenges & Required Support
    if (inputs.includes("challenges")) {
      const chText = (cur.challenges || []).map((c) => c.challenge_ar).join("\n");
      const supText = (cur.challenges || []).map((c) => c.support_needed_ar).filter(Boolean).join("\n");
      blocksHtml += `
        <div class="card">
          <div class="card-header"><h2 class="card-title">التحديات والمخاطر والدعم المطلوب</h2></div>
          <div class="form-group">
            <label class="form-label" for="ed-challenges">مخاطر وتحديات المشروع (كل تحدٍ في سطر)</label>
            <textarea id="ed-challenges" class="textarea" ${editable ? "" : "disabled"}>${escapeHtml(chText)}</textarea>
          </div>
          <div class="form-group">
            <label class="form-label" for="ed-support">الدعم المطلوب (اختياري)</label>
            <textarea id="ed-support" class="textarea" ${editable ? "" : "disabled"}>${escapeHtml(supText)}</textarea>
          </div>
        </div>`;
    }

    // F. Events Calendar
    if (inputs.includes("events")) {
      const slots = cfg.event_slots || ["CAL_2026_DEC_1", "CAL_2026_DEC_2"];
      const evMap = {};
      (cur.events || []).forEach((e) => (evMap[e.slot_key] = e));
      const evRows = slots
        .map((sk) => {
          const ev = evMap[sk] || {};
          return `
            <div class="ref-box event-row" data-slot-key="${escapeHtml(sk)}">
              <div class="form-label">فعالية الروزنامة (${escapeHtml(sk)})</div>
              <div style="display:grid;grid-template-columns:1fr 120px 160px;gap:8px;">
                <input class="input ev-title" placeholder="اسم الفعالية" value="${escapeHtml(ev.title_ar || "")}" ${editable ? "" : "disabled"} />
                <input class="input ev-date" placeholder="اليوم (مثلاً 11)" value="${escapeHtml(ev.event_date_label || "")}" ${editable ? "" : "disabled"} />
                <input class="input ev-lead" placeholder="المسؤول" value="${escapeHtml(ev.lead_names_ar || "")}" ${editable ? "" : "disabled"} />
              </div>
            </div>`;
        })
        .join("");
      blocksHtml += `
        <div class="card">
          <div class="card-header"><h2 class="card-title">روزنامة الأنشطة والفعاليات</h2></div>
          ${evRows}
        </div>`;
    }

    // G. News & Images
    if (inputs.includes("news")) {
      const nwMap = {};
      (cur.news || []).forEach((n) => (nwMap[n.slot_index] = n));
      blocksHtml += `
        <div class="card">
          <div class="card-header"><h2 class="card-title">أخبار طموح والصور المرفقة</h2></div>
          <div class="form-group">
            <label class="form-label">الخبر الأول (شريحة 38)</label>
            <textarea class="textarea news-body" data-slot="1" ${editable ? "" : "disabled"}>${escapeHtml(nwMap[1]?.body_ar || "")}</textarea>
            <div style="margin-top:8px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
              <input type="file" id="news-img-file" accept="image/png,image/jpeg" ${editable ? "" : "disabled"} />
              <input type="hidden" id="news-img-path" value="${escapeHtml(nwMap[1]?.image_path || "")}" />
              <span id="news-img-status" class="form-hint">${nwMap[1]?.image_file_name ? `الصورة المرفقة: ${escapeHtml(nwMap[1].image_file_name)}` : "اختياري: صورة PNG/JPEG بحد أقصى 5 ميجابايت"}</span>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">الخبر الثاني (شريحة 38)</label>
            <textarea class="textarea news-body" data-slot="2" ${editable ? "" : "disabled"}>${escapeHtml(nwMap[2]?.body_ar || "")}</textarea>
          </div>
        </div>`;
    }

    // H. Executive Meeting Action Items Table
    if (inputs.includes("action_items")) {
      const items = (cur.upcoming_tasks || []).filter((t) => t.task_kind === "meeting_action_item");
      const rowsHtml = (items.length ? items : [{ sequence_no: 1, title_ar: "", owner_label_ar: "", expected_due_date: "", weekly_update_ar: "", task_status: "جاري" }])
        .map((it, idx) => renderActionItemRow(idx + 1, it, editable))
        .join("");
      blocksHtml += `
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">المهام الصادرة من الاجتماع (شريحة 40)</h2>
            ${editable ? `<button type="button" id="btn-add-action-row" class="btn btn-outline btn-sm">+ إضافة صف</button>` : ""}
          </div>
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr><th>#</th><th>المهمة</th><th>المسؤول</th><th>تاريخ الإنجاز</th><th>التحديث الأسبوعي</th><th>الحالة</th></tr></thead>
              <tbody id="action-items-tbody">${rowsHtml}</tbody>
            </table>
          </div>
        </div>`;
    }

    // Previous Week Reference Panel
    let prevHtml = `<div class="ref-box">لا توجد بيانات مسجلة للأسبوع السابق.</div>`;
    if (data.previous_week && prev) {
      const pAch = (prev.achievements || []).map((a) => `<li>${escapeHtml(a.content_ar)}</li>`).join("");
      const pKpi = (prev.kpis || []).map((k) => `<li>${escapeHtml(k.label_ar)}: <strong>${k.numeric_value ?? "غير محدث"}</strong></li>`).join("");
      const pCh = (prev.challenges || []).map((c) => `<li>${escapeHtml(c.challenge_ar)}</li>`).join("");
      prevHtml = `
        <div class="ref-box">
          <strong>مرجع الأسبوع السابق (الأسبوع ${data.previous_week.week_number})</strong>
          <div class="form-hint">للاطلاع والمقارنة فقط — لا يتم نسخ إنجازات الأسبوع السابق تلقائياً.</div>
          ${pKpi ? `<p><strong>المؤشرات:</strong></p><ul>${pKpi}</ul>` : ""}
          ${pAch ? `<p><strong>الإنجازات السابقة:</strong></p><ul>${pAch}</ul>` : ""}
          ${pCh ? `<p><strong>التحديات السابقة:</strong></p><ul>${pCh}</ul>` : ""}
        </div>`;
    }

    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">${escapeHtml(proj.title_ar)}</h1>
          <p class="page-subtitle">الأسبوع ${wk.week_number} (${wk.fiscal_year}) • الشرائح: ${(cfg.slides || []).join("، ")}</p>
        </div>
        <button type="button" id="btn-back" class="btn btn-outline">عودة</button>
      </div>

      ${cur.submission?.reviewer_notes_ar ? `<div class="alert alert-warn"><strong>ملاحظة المنسق:</strong> ${escapeHtml(cur.submission.reviewer_notes_ar)}</div>` : ""}

      <div class="editor-layout">
        <div>
          ${blocksHtml}
          <div class="card" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
            <div class="btn-group">
              <button type="button" id="btn-save-draft" class="btn btn-outline" ${editable ? "" : "disabled"}>حفظ كمسودة</button>
              <button type="button" id="btn-submit-update" class="btn btn-primary" ${editable ? "" : "disabled"}>تسليم التحديث</button>
            </div>
            <span class="form-hint">${cur.submission ? `الإصدار الحالي: ${cur.submission.version} • آخر حفظ: ${formatDateShort(cur.submission.updated_at)}` : "لم يتم الحفظ بعد"}</span>
          </div>
        </div>

        <aside>
          <div class="card">
            <div class="card-header"><h3 class="card-title">البيانات الثابتة ومرجع الأسبوع السابق</h3></div>
            <div class="ref-box">
              <div><strong>رمز القسم:</strong> ${escapeHtml(proj.project_code)}</div>
              <div><strong>السنة المالية:</strong> ${proj.fiscal_year}</div>
              ${proj.estimated_budget_ar ? `<div><strong>الميزانية التقديرية:</strong> ${escapeHtml(proj.estimated_budget_ar)}</div>` : ""}
            </div>
            ${prevHtml}
          </div>

          <div class="card">
            <div class="card-header"><h3 class="card-title">مساعد الصياغة الذكي (اختياري)</h3></div>
            <div class="ai-disabled-box">
              <p style="margin:0 0 8px;"><strong>الحالة: معطّل (Feature Flag OFF)</strong></p>
              <p style="margin:0;">لا يتم إرسال أي بيانات حكومية إلى مزودي ذكاء اصطناعي خارجيين. عند تفعيل خدمة داخلية معتمدة سيتاح تحسين الصياغة العربية مع اشتراط موافقة الموظف قبل الاعتماد.</p>
            </div>
          </div>
        </aside>
      </div>
    `;

    $("btn-back").onclick = () => navigate(state.editorReturnView);
    container.querySelectorAll("input, textarea, select").forEach((el) => {
      el.addEventListener("input", () => (state.dirty = true));
    });

    function connectAddEntry(buttonId, selector, dataKey, limit, label, maxLength) {
      const button = $(buttonId);
      if (!button) return;
      const update = () => { button.disabled = container.querySelectorAll(selector).length >= limit; };
      button.onclick = () => {
        const count = container.querySelectorAll(selector).length;
        if (count >= limit) return;
        const group = document.createElement("div"); group.className = "form-group";
        const number = count + 1;
        group.innerHTML = `<label class="form-label">${label} (${number})</label><textarea class="textarea ${selector.slice(1)}" data-${dataKey}="${number}" maxlength="${maxLength}"></textarea>`;
        button.before(group);
        const input = group.querySelector("textarea");
        input.addEventListener("input", () => { state.dirty = true; });
        input.focus(); state.dirty = true; update();
      };
      update();
    }
    connectAddEntry("btn-add-achievement", ".ach-input", "slot", 10, "إنجاز الأسبوع الماضي", 220);
    connectAddEntry("btn-add-task", ".task-input", "seq", 20, "مهمة الأسبوع القادم", 200);

    const addRowBtn = $("btn-add-action-row");
    if (addRowBtn) {
      addRowBtn.onclick = () => {
        const tbody = $("action-items-tbody");
        if (tbody.children.length >= 8) {
          showToast("الحد الأقصى الآمن لصفوف الجدول في الشريحة 40 هو 8 صفوف.", "error");
          return;
        }
        const tr = document.createElement("tr");
        tr.innerHTML = renderActionItemRowInner(tbody.children.length + 1, { task_status: "جاري" }, true);
        tbody.appendChild(tr);
        state.dirty = true;
      };
    }

    const imgFile = $("news-img-file");
    if (imgFile) {
      imgFile.addEventListener("change", async () => {
        if (!imgFile.files.length) return;
        const fd = new FormData();
        fd.append("file", imgFile.files[0]);
        try {
          const up = await api("/api/v1/uploads/image", { method: "POST", body: fd });
          $("news-img-path").value = up.storage_path;
          $("news-img-status").textContent = `تم رفع الصورة بنجاح: ${up.file_name}`;
          state.dirty = true;
          showToast("تم رفع الصورة بنجاح", "success");
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    }

    async function saveForm(targetStatus) {
      const payload = {
        project_id: proj.id,
        expected_version: curVersion,
        submission_status: targetStatus,
        kpis: [],
        achievements: [],
        upcoming_tasks: [],
        challenges: [],
        events: [],
        news: [],
      };

      // Collect KPIs (explicitly preserve null vs 0!)
      container.querySelectorAll(".kpi-val-input").forEach((inp) => {
        const code = inp.dataset.code;
        const raw = inp.value.trim();
        const numVal = raw === "" ? null : Number(raw);
        let denVal = null;
        if (inp.dataset.ratio === "1") {
          const denInp = container.querySelector(`.kpi-den-input[data-code="${code}"]`);
          if (denInp && denInp.value.trim() !== "") denVal = Number(denInp.value.trim());
        }
        payload.kpis.push({ kpi_code: code, numeric_value: numVal, denominator_value: denVal });
      });

      if ($("ed-project-status")) {
        payload.project_status = $("ed-project-status").value;
      }
      if ($("ed-deliverables")) {
        payload.deliverables_override_ar = $("ed-deliverables").value.trim() || null;
      }

      container.querySelectorAll(".ach-input").forEach((ta) => {
        const txt = ta.value.trim();
        if (txt) payload.achievements.push({ slot_index: Number(ta.dataset.slot), content_ar: txt });
      });

      container.querySelectorAll(".task-input").forEach((ta) => {
        const txt = ta.value.trim();
        if (txt) payload.upcoming_tasks.push({ task_kind: "project_task", sequence_no: Number(ta.dataset.seq), title_ar: txt, task_status: "جاري" });
      });

      if ($("ed-challenges")) {
        const lines = $("ed-challenges").value.split("\n").map((l) => l.trim()).filter(Boolean);
        const sup = $("ed-support") ? $("ed-support").value.trim() : "";
        lines.forEach((line, idx) => {
          payload.challenges.push({ challenge_ar: line, support_needed_ar: idx === 0 && sup ? sup : null, is_resolved: false });
        });
      }

      container.querySelectorAll(".event-row").forEach((row) => {
        const title = row.querySelector(".ev-title").value.trim();
        if (title) {
          payload.events.push({
            slot_key: row.dataset.slotKey,
            title_ar: title,
            event_date_label: row.querySelector(".ev-date").value.trim() || null,
            lead_names_ar: row.querySelector(".ev-lead").value.trim() || null,
            event_status: "على المسار",
          });
        }
      });

      container.querySelectorAll(".news-body").forEach((ta) => {
        const txt = ta.value.trim();
        if (txt) {
          const slot = Number(ta.dataset.slot);
          payload.news.push({
            slot_index: slot,
            body_ar: txt,
            image_path: slot === 1 && $("news-img-path")?.value ? $("news-img-path").value : null,
          });
        }
      });

      const tbody = $("action-items-tbody");
      if (tbody) {
        Array.from(tbody.querySelectorAll("tr")).forEach((tr, idx) => {
          const title = tr.querySelector(".ai-title")?.value.trim();
          if (title) {
            payload.upcoming_tasks.push({
              task_kind: "meeting_action_item",
              sequence_no: idx + 1,
              title_ar: title,
              owner_label_ar: tr.querySelector(".ai-owner")?.value.trim() || null,
              expected_due_date: tr.querySelector(".ai-due")?.value.trim() || null,
              weekly_update_ar: tr.querySelector(".ai-update")?.value.trim() || null,
              task_status: tr.querySelector(".ai-status")?.value || "جاري",
            });
          }
        });
      }

      try {
        await api(`/api/v1/weeks/${encodeURIComponent(wk.id)}/submissions`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        state.dirty = false;
        showToast(targetStatus === "submitted" ? "تم تسليم التحديث بنجاح" : "تم حفظ المسودة بنجاح", "success");
        render();
      } catch (err) {
        showToast(err.message, "error");
      }
    }

    $("btn-save-draft").onclick = () => saveForm("draft");
    $("btn-submit-update").onclick = () => saveForm("submitted");
  }

  function renderActionItemRowInner(seq, it, editable) {
    return `
      <td>${seq}</td>
      <td><input class="input ai-title" value="${escapeHtml(it.title_ar || "")}" ${editable ? "" : "disabled"} /></td>
      <td><input class="input ai-owner" style="width:110px" value="${escapeHtml(it.owner_label_ar || "")}" ${editable ? "" : "disabled"} /></td>
      <td><input class="input ai-due" style="width:115px" value="${escapeHtml(it.expected_due_date || "")}" placeholder="DD-MM-YYYY" ${editable ? "" : "disabled"} /></td>
      <td><input class="input ai-update" value="${escapeHtml(it.weekly_update_ar || "")}" ${editable ? "" : "disabled"} /></td>
      <td>
        <select class="select ai-status" style="width:105px" ${editable ? "" : "disabled"}>
          ${TASK_STATUSES.map((s) => `<option value="${s}" ${it.task_status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select>
      </td>`;
  }

  function renderActionItemRow(seq, it, editable) {
    return `<tr>${renderActionItemRowInner(seq, it, editable)}</tr>`;
  }

  /* ==================== 4. COORDINATOR DASHBOARD ==================== */
  async function renderCoordinatorDashboard(container) {
    const q = state.selectedWeekId ? `?week_id=${encodeURIComponent(state.selectedWeekId)}` : "";
    const data = await api(`/api/v1/coordinator/dashboard${q}`);
    const wk = data.reporting_week;
    if (wk) state.selectedWeekId = wk.id;
    const sum = data.summary;

    const matrixRows = data.matrix
      .map(
        (m) => `
      <tr>
        <td><strong>${escapeHtml(m.owner_name_ar)}</strong></td>
        <td>
          ${escapeHtml(m.title_ar)}
          <div class="form-hint">شرائح: ${m.slides.join("، ") || "—"}</div>
        </td>
        <td><span class="badge badge-${escapeHtml(m.status)}">${escapeHtml(m.status_ar)}</span><div class="form-hint">${(m.contributors || []).map(c => `${escapeHtml(c.full_name_ar)}: ${escapeHtml(({not_started:"لم يحدث",draft:"مسودة",submitted:"تم التسليم",approved:"معتمد",changes_requested:"طلب تعديل"})[c.status] || c.status)}`).join("<br>")}</div></td>
        <td>${formatDateShort(m.last_updated)}</td>
        <td>
          <div class="btn-group">
            <button type="button" class="btn btn-outline btn-sm btn-coord-open" data-pid="${escapeHtml(m.project_id)}">فتح</button>
            ${
              m.status === "submitted" || m.status === "changes_requested" || m.status === "draft"
                ? `<button type="button" class="btn btn-success btn-sm btn-coord-approve" data-pid="${escapeHtml(m.project_id)}">اعتماد</button>`
                : ""
            }
            ${
              m.status !== "not_started"
                ? `<button type="button" class="btn btn-outline btn-sm btn-coord-revise" data-pid="${escapeHtml(m.project_id)}">طلب تعديل</button>`
                : ""
            }
          </div>
        </td>
      </tr>`
      )
      .join("");

    const genRows = (data.generations || [])
      .map(
        (g) => `
      <tr>
        <td>${formatDateShort(g.created_at)}</td>
        <td><span class="badge ${g.status === "succeeded" ? "badge-approved" : "badge-changes_requested"}">${g.status === "succeeded" ? "ناجح" : "فشل"}</span></td>
        <td><code>${escapeHtml((g.output_sha256 || "").slice(0, 12))}</code></td>
        <td><a class="btn btn-primary btn-sm" href="/api/v1/generations/${escapeHtml(g.id)}/download">تحميل PPTX</a></td>
      </tr>`
      )
      .join("");

    const hasMissing = sum.missing > 0 || sum.draft > 0;

    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">لوحة متابعة منسق التقرير</h1>
          <p class="page-subtitle">
            ${wk ? `الأسبوع رقم (${wk.week_number}) • ${escapeHtml(wk.start_date)} إلى ${escapeHtml(wk.end_date)} • الحالة: <strong>${wk.status === "locked" ? "مقفل" : "مفتوح"}</strong>` : "لم يتم إنشاء أسبوع تقرير بعد"}
          </p>
        </div>
        <div class="btn-group">
          ${
            data.weeks.length
              ? `<select id="coord-week-select" class="select" style="width:auto">
                  ${data.weeks
                    .map(
                      (w) =>
                        `<option value="${escapeHtml(w.id)}" ${wk && w.id === wk.id ? "selected" : ""}>الأسبوع ${w.week_number} (${w.fiscal_year})</option>`
                    )
                    .join("")}
                 </select>`
              : ""
          }
          <button type="button" id="btn-new-week" class="btn btn-primary">+ فتح أسبوع جديد</button>
          ${
            wk
              ? `<button type="button" id="btn-toggle-lock" class="btn btn-outline">${wk.status === "locked" ? "فتح الأسبوع للتعديل" : "قفل الأسبوع"}</button>`
              : ""
          }
        </div>
      </div>

      ${
        wk
          ? `
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">إجمالي الأقسام المطلوبة</div><div class="kpi-value">${sum.total_expected}</div></div>
        <div class="kpi-card"><div class="kpi-label">تم التسليم / تمت المراجعة</div><div class="kpi-value">${sum.submitted + sum.reviewed}</div></div>
        <div class="kpi-card"><div class="kpi-label">مسودات</div><div class="kpi-value">${sum.draft}</div></div>
        <div class="kpi-card"><div class="kpi-label">لم يبدأ (ناقص)</div><div class="kpi-value">${sum.missing}</div></div>
        <div class="kpi-card">
          <div class="kpi-label">نسبة اكتمال التسليم</div>
          <div class="kpi-value">${sum.completion_pct}%</div>
          <div class="progress-track"><div class="progress-fill" style="width:${sum.completion_pct}%"></div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h2 class="card-title">مصفوفة متابعة الأقسام والموظفين</h2></div>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>الموظف المسؤول</th><th>القسم المسند</th><th>الحالة</th><th>آخر تحديث</th><th>الإجراءات</th></tr></thead>
            <tbody>${matrixRows}</tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h2 class="card-title">توليد العرض التقديمي الأسبوعي (PowerPoint)</h2>
          <button type="button" id="btn-preview-report" class="btn btn-outline btn-sm">معاينة محتوى التقرير</button>
        </div>
        <div class="alert alert-info">
          <strong>قيود معروفة في المرحلة الحالية:</strong>
          <ul style="margin:6px 0 0;padding-right:18px;">
            ${data.unsupported_limitations.map((l) => `<li>${escapeHtml(l)}</li>`).join("")}
          </ul>
        </div>
        ${
          hasMissing
            ? `<div class="alert alert-warn">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                  <input type="checkbox" id="chk-ack-missing" />
                  <span>أقرّ بوجود أقسام ناقصة أو مسودات (${sum.missing} لم تبدأ، ${sum.draft} مسودات) وأرغب بتوليد العرض مع الحفاظ على القالب دون استبدال القيم المفقودة ببيانات قديمة.</span>
                </label>
              </div>`
            : ""
        }
        <div class="btn-group">
          <button type="button" id="btn-generate-pptx" class="btn btn-success" ${hasMissing ? "disabled" : ""}>توليد ملف PowerPoint القابل للتعديل</button>
          <span id="gen-status-msg" class="form-hint"></span>
        </div>

        ${
          genRows
            ? `<h3 style="margin:18px 0 10px;font-size:15px;">سجل النسخ المولّدة لهذا الأسبوع</h3>
               <div class="table-wrap">
                 <table class="data-table">
                   <thead><tr><th>وقت التوليد</th><th>الحالة</th><th>بصمة الملف (SHA-256)</th><th>التحميل</th></tr></thead>
                   <tbody>${genRows}</tbody>
                 </table>
               </div>`
            : ""
        }
      </div>`
          : `<div class="card">اضغط على "فتح أسبوع جديد" للبدء.</div>`
      }
    `;

    if ($("coord-week-select")) {
      $("coord-week-select").onchange = (e) => {
        state.selectedWeekId = e.target.value;
        render();
      };
    }

    $("btn-new-week").onclick = () => openNewWeekModal(data.weeks);

    if ($("btn-toggle-lock")) {
      $("btn-toggle-lock").onclick = async () => {
        const ep = wk.status === "locked" ? "unlock" : "lock";
        await api(`/api/v1/weeks/${wk.id}/${ep}`, { method: "POST" });
        showToast(ep === "lock" ? "تم قفل الأسبوع" : "تم فتح الأسبوع للتعديل", "success");
        render();
      };
    }

    async function openContributions(projectId, approve) {
      const review = await api(`/api/v1/weeks/${wk.id}/projects/${projectId}/contributions`);
      const cards = review.contributors.map(c => {
        const d=c.detail;
        const entries=[...(d.achievements||[]).map(a=>"إنجاز: "+a.content_ar),...(d.upcoming_tasks||[]).map(t=>"مهمة: "+t.title_ar),...(d.challenges||[]).map(t=>"تحدي: "+t.challenge_ar),...(d.kpis||[]).map(k=>k.label_ar+": "+(k.numeric_value??"لم يحدد")),...(d.news||[]).map(n=>n.body_ar),...(d.events||[]).map(n=>n.title_ar),...(d.project_status?["حالة المشروع: "+(({on_track:"وفق المخطط",delayed:"متأخر",critically_delayed:"متأخر جدًا",on_hold:"معلق",completed:"مكتمل",not_started:"لم يبدأ"})[d.project_status.status_code]||d.project_status.status_code),d.project_status.progress_note_ar,d.project_status.deliverables_override_ar].filter(Boolean):[])];
        return `<div class="ref-box"><h3>${escapeHtml(c.full_name_ar)}</h3><div class="form-hint">${escapeHtml(({not_started:"لم يحفظ تحديثًا",draft:"حفظ مسودة",submitted:"تم التسليم",approved:"معتمد",changes_requested:"طلب تعديل"})[c.status]||c.status)}</div><ul>${entries.map(x=>`<li style="white-space:pre-wrap">${escapeHtml(x)}</li>`).join("")}</ul></div>`;
      }).join("");
      const conflicts=review.kpi_conflicts||[];
      const choose=conflicts.length?'<div class="alert alert-warn">توجد أرقام مختلفة. اختر مصدر الرقم لكل مؤشر؛ تبقى تحديثات جميع الموظفين محفوظة.</div>'+conflicts.map(c=>`<div class="form-group"><label class="form-label">${escapeHtml(c.label_ar)}</label><select class="select kpi-source-choice" data-code="${escapeHtml(c.kpi_code)}"><option value="">اختر الرقم المعتمد</option>${c.contributors.map(u=>`<option value="${escapeHtml(u.user_id)}">${escapeHtml(u.name)}: ${u.value}${u.denominator ? '/'+u.denominator : ''}</option>`).join("")}</select></div>`).join(""):"";
      openModal(review.project.title_ar+" — تحديثات المسؤولين", cards+choose+(approve?'<button id="confirm-section-approval" class="btn btn-success" type="button">اعتماد جميع تحديثات القسم</button><p class="form-hint">بعد الاعتماد تتوقف التعديلات حتى يعيد المنسق فتح القسم.</p>':""));
      if(approve)$("confirm-section-approval").onclick=async()=>{try{
        await api(`/api/v1/weeks/${wk.id}/submissions/${projectId}/review`,{method:"POST",body:JSON.stringify({status:"approved",reviewer_notes_ar:null,expected_versions:review.expected_versions,kpi_sources:Object.fromEntries(Array.from(document.querySelectorAll(".kpi-source-choice")).map(el=>[el.dataset.code,el.value]))})});
        closeModal();showToast("تم اعتماد تحديثات جميع المسؤولين.","success");render();
      }catch(err){showToast(err.message,"error");}};
    }
    container.querySelectorAll(".btn-coord-open").forEach(btn=>{btn.onclick=()=>openContributions(btn.dataset.pid,false);});
    container.querySelectorAll(".btn-coord-approve").forEach(btn=>{btn.onclick=()=>openContributions(btn.dataset.pid,true);});

    container.querySelectorAll(".btn-coord-revise").forEach((btn) => {
      btn.onclick = () => {
        openModal(
          "طلب تعديل على القسم",
          `<div class="form-group">
             <label class="form-label">ملاحظات المنسق للموظف</label>
             <textarea id="rev-notes" class="textarea" placeholder="اكتب التعديل المطلوب بوضوح..."></textarea>
           </div>
           <button type="button" id="btn-send-rev" class="btn btn-primary">إرسال طلب التعديل</button>`
        );
        $("btn-send-rev").onclick = async () => {
          await api(`/api/v1/weeks/${wk.id}/submissions/${btn.dataset.pid}/review`, {
            method: "POST",
            body: JSON.stringify({ status: "changes_requested", reviewer_notes_ar: $("rev-notes").value.trim() }),
          });
          closeModal();
          showToast("تم تسجيل طلب التعديل", "success");
          render();
        };
      };
    });

    if ($("chk-ack-missing")) {
      $("chk-ack-missing").onchange = (e) => {
        $("btn-generate-pptx").disabled = !e.target.checked;
      };
    }

    if ($("btn-preview-report")) {
      $("btn-preview-report").onclick = async () => {
        const prev = await api(`/api/v1/weeks/${wk.id}/preview`);
        const rows = prev.mapped_fields
          .map(
            (f) => `<tr>
              <td>${f.slide_number}</td>
              <td><code>${escapeHtml(f.field_key)}</code></td>
              <td><span class="badge ${f.status === "ready" ? "badge-approved" : "badge-draft"}">${f.status === "ready" ? "جاهز" : "غير محدث"}</span></td>
              <td>${escapeHtml(typeof f.formatted_value === "object" && f.formatted_value ? JSON.stringify(f.formatted_value) : f.formatted_value || "—")}</td>
            </tr>`
          )
          .join("");
        openModal(
          `معاينة حقول التقرير الأسبوعي رقم (${wk.week_number})`,
          `<div class="table-wrap"><table class="data-table"><thead><tr><th>الشريحة</th><th>الحقل</th><th>الحالة</th><th>القيمة</th></tr></thead><tbody>${rows}</tbody></table></div>`
        );
      };
    }

    if ($("btn-generate-pptx")) {
      $("btn-generate-pptx").onclick = async () => {
        const btn = $("btn-generate-pptx");
        btn.disabled = true;
        $("gen-status-msg").textContent = "جاري معالجة القالب وتوليد ملف PowerPoint...";
        try {
          const res = await api(`/api/v1/weeks/${wk.id}/generate`, {
            method: "POST",
            body: JSON.stringify({ allow_incomplete: true, run_visual_validation: false }),
          });
          showToast(`تم توليد العرض بنجاح (${res.validation.engine.operations_updated} حقل محدث)`, "success");
          render();
        } catch (err) {
          showToast(err.message, "error");
          btn.disabled = false;
          $("gen-status-msg").textContent = "";
        }
      };
    }
  }

  function openNewWeekModal(existingWeeks) {
    const nextNum = existingWeeks.length ? existingWeeks[0].week_number + 1 : 45;
    const prevOpts = existingWeeks
      .map((w) => `<option value="${escapeHtml(w.id)}">الأسبوع ${w.week_number} (${w.fiscal_year})</option>`)
      .join("");
    openModal(
      "فتح أسبوع تقرير جديد",
      `<form id="new-week-form">
        <div class="form-group">
          <label class="form-label">رقم التقرير الأسبوعي</label>
          <input id="nw-num" type="number" class="input" value="${nextNum}" required />
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div class="form-group"><label class="form-label">تاريخ البداية</label><input id="nw-start" type="date" class="input" value="2026-11-22" required /></div>
          <div class="form-group"><label class="form-label">تاريخ النهاية</label><input id="nw-end" type="date" class="input" value="2026-11-28" required /></div>
        </div>
        <div class="form-group">
          <label class="form-label">ترحيل البيانات المستمرة من أسبوع سابق (اختياري)</label>
          <select id="nw-carry" class="select"><option value="">بدون ترحيل</option>${prevOpts}</select>
          <span class="form-hint">يتم ترحيل المهام المفتوحة والتحديات القائمة وحالات المشاريع فقط دون تكرار إنجازات الأسبوع السابق.</span>
        </div>
        <button type="submit" id="btn-create-week-submit" class="btn btn-primary">إنشاء الأسبوع</button>
      </form>`
    );
    $("new-week-form").onsubmit = async (e) => {
      e.preventDefault();
      try {
        const res = await api("/api/v1/weeks", {
          method: "POST",
          body: JSON.stringify({
            week_number: Number($("nw-num").value),
            fiscal_year: 2026,
            start_date: $("nw-start").value,
            end_date: $("nw-end").value,
            carry_forward_from_week_id: $("nw-carry").value || null,
          }),
        });
        state.selectedWeekId = res.reporting_week.id;
        closeModal();
        showToast(`تم فتح الأسبوع رقم (${res.reporting_week.week_number}) بنجاح`, "success");
        render();
      } catch (err) {
        showToast(err.message, "error");
      }
    };
  }

  /* ==================== 5. COORDINATOR REMINDERS ==================== */
  async function renderCoordinatorReminders(container) {
    const weeksData = await api("/api/v1/weeks");
    const wk = weeksData.weeks.find((w) => w.id === state.selectedWeekId) || weeksData.weeks[0];
    if (!wk) {
      container.innerHTML = `<div class="card">لا يوجد أسبوع تقرير مفتوح.</div>`;
      return;
    }
    const rem = await api(`/api/v1/weeks/${wk.id}/reminders`);
    const cards = rem.reminders
      .map(
        (r, i) => `
      <div class="card">
        <div class="card-header">
          <div>
            <strong>${escapeHtml(r.employee_name_ar)}</strong> — ${escapeHtml(r.project_title_ar)}
          </div>
          <span class="badge badge-${escapeHtml(r.status)}">${escapeHtml(r.status_ar)}</span>
        </div>
        <textarea class="textarea rem-msg" id="rem-msg-${i}" readonly>${escapeHtml(r.copyable_message_ar)}</textarea>
        <div style="margin-top:8px;">
          <button type="button" class="btn btn-outline btn-sm btn-copy-rem" data-idx="${i}">نسخ رسالة التذكير</button>
        </div>
      </div>`
      )
      .join("");

    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">التذكيرات والمواعيد النهائية</h1>
          <p class="page-subtitle">الأسبوع رقم (${wk.week_number}) • لا يتم إرسال رسائل خارجية تلقائياً دون تفعيل قناة معتمدة.</p>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><h2 class="card-title">تحديث الموعد النهائي للتسليم</h2></div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          <input id="deadline-input" class="input" style="max-width:260px" value="${escapeHtml(wk.submission_deadline || wk.end_date)}" placeholder="مثال: 2026-11-26 14:00" />
          <button type="button" id="btn-save-deadline" class="btn btn-primary btn-sm">حفظ الموعد النهائي</button>
        </div>
      </div>
      ${cards || `<div class="alert alert-success">جميع الأقسام مكتملة التسليم لهذا الأسبوع.</div>`}
    `;

    $("btn-save-deadline").onclick = async () => {
      await api(`/api/v1/weeks/${wk.id}`, {
        method: "PATCH",
        body: JSON.stringify({ submission_deadline: $("deadline-input").value.trim() }),
      });
      showToast("تم تحديث الموعد النهائي", "success");
      render();
    };

    container.querySelectorAll(".btn-copy-rem").forEach((btn) => {
      btn.onclick = () => {
        const txt = $(`rem-msg-${btn.dataset.idx}`).value;
        navigator.clipboard?.writeText(txt).catch(() => {});
        showToast("تم نسخ رسالة التذكير", "success");
      };
    });
  }

  /* ==================== 6. COORDINATOR PROJECT & ASSIGNMENT SETTINGS ==================== */
  async function renderCoordinatorSettings(container) {
    const [projRes, usersRes] = await Promise.all([api("/api/v1/projects"), api("/api/v1/admin/users")]);
    const users = usersRes.users;
    const membership = Object.fromEntries(await Promise.all(projRes.projects.map(async p => [p.id,(await api(`/api/v1/projects/${p.id}/members`)).members])));
    const rows = projRes.projects
      .map(
        (p) => `
      <tr>
        <td><strong>${escapeHtml(p.title_ar)}</strong><div class="form-hint">${escapeHtml(p.project_code)}</div></td>
        <td>
          <div class="set-owners" data-pid="${escapeHtml(p.id)}">${users.map(u=>`<label style="display:block;padding:4px"><input type="checkbox" value="${escapeHtml(u.id)}" ${p.owner_user_id===u.id || (membership[p.id]||[]).some(m=>m.user_id===u.id && m.member_role!=="viewer")?"checked":""}> ${escapeHtml(u.full_name_ar)}</label>`).join("")}</div>
        </td>
        <td>
          <label style="display:flex;align-items:center;gap:6px;">
            <input type="checkbox" class="set-enabled" data-pid="${escapeHtml(p.id)}" ${p.is_enabled !== 0 ? "checked" : ""} />
            <span>مفعّل في التقرير</span>
          </label>
        </td>
        <td>
          <button type="button" class="btn btn-primary btn-sm btn-save-proj-set" data-pid="${escapeHtml(p.id)}">حفظ</button>
        </td>
      </tr>`
      )
      .join("");

    container.innerHTML = `
      <div class="page-header">
        <div>
          <h1 class="page-title">إدارة المشاريع وتكليفات الموظفين</h1>
          <p class="page-subtitle">صفحة خاصة بالمنسق لتحديد المسؤوليات وتفعيل الأقسام مع الحفاظ الكامل على ربط شرائح PowerPoint.</p>
        </div>
      </div>
      <div class="card">
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>القسم / المشروع</th><th>المسؤول الرئيسي</th><th>الحالة في التقرير</th><th>حفظ</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `;

    container.insertAdjacentHTML("beforeend", `<div class="card"><h2>إضافة مستخدم</h2>
      <form id="create-user-form">
        <div class="form-group"><label class="form-label">الاسم</label><input class="input" id="new-user-name" required /></div>
        <div class="form-group"><label class="form-label">البريد الإلكتروني</label><input class="input" id="new-user-email" type="email" dir="ltr" required /></div>
        <div class="form-group"><label class="form-label">كلمة مرور أولية (١٢ حرفًا على الأقل)</label><input class="input" id="new-user-password" type="password" minlength="12" autocomplete="new-password" required /></div>
        <div class="form-group"><label class="form-label">الصلاحية</label><select class="select" id="new-user-role"><option value="employee">موظف</option><option value="coordinator">منسق</option></select></div>
        <button class="btn btn-primary" type="submit">إنشاء المستخدم</button>
      </form></div>`);
    $("create-user-form").onsubmit=async(e)=>{e.preventDefault();try{
      await api("/api/v1/admin/users",{method:"POST",body:JSON.stringify({full_name_ar:$("new-user-name").value,email:$("new-user-email").value,password:$("new-user-password").value,role:$("new-user-role").value})});
      showToast("تم إنشاء المستخدم، يمكنك الآن إسناد المشاريع إليه.","success");render();
    }catch(err){showToast(err.message,"error");}};

    container.querySelectorAll(".btn-save-proj-set").forEach((btn) => {
      btn.onclick = async () => {
        try {
        const pid = btn.dataset.pid;
        const owners = Array.from(container.querySelectorAll(`.set-owners[data-pid="${pid}"] input:checked`)).map(o=>o.value);
        const enabled = container.querySelector(`.set-enabled[data-pid="${pid}"]`).checked;
        await api(`/api/v1/projects/${pid}/contributors`, {method:"PUT",body:JSON.stringify({user_ids:owners})});
        await api(`/api/v1/projects/${pid}`, {
          method: "PATCH",
          body: JSON.stringify({ is_enabled: enabled }),
        });
        showToast("تم حفظ إعدادات القسم والتكليف", "success");
        } catch(err) { showToast(err.message,"error"); }
      };
    });
  }

  /* ==================== BOOTSTRAP ==================== */
  async function init() {
    try {
      const me = await api("/api/v1/auth/me");
      state.user = me.user;
      state.aiEnabled = Boolean(me.ai_assistant_enabled);
      const isCoord = me.user.role === "coordinator" || me.user.role === "admin";
      state.view = isCoord ? "coord_dashboard" : "employee_home";
    } catch (_) {
      state.user = null;
      state.view = "login";
    }
    render();
  }

  init();
})();
