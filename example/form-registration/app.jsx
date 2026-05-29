const { useState, useMemo, useEffect } = React;

/* ---------- Icons ---------- */
const Icon = {
  Chevron: (p) => (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" {...p}>
      <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  Bell: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M6 8a6 6 0 1112 0c0 4.5 1.5 5.5 2 6.5H4c.5-1 2-2 2-6.5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M10 18a2 2 0 004 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  Help: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9.5 9.5a2.5 2.5 0 014.7 1.1c-.2.9-1.2 1.2-1.7 1.7-.4.5-.5 1-.5 1.7M12 17h.01" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  Mail: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.7" />
      <path d="M3.5 6.5l8.5 6 8.5-6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  Phone: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
      <path d="M5 4h3.5l1.5 4-2.2 1.3a12 12 0 005.9 5.9L15 13l4 1.5V18a2 2 0 01-2.2 2A16 16 0 013 6.2 2 2 0 015 4z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  ),
  Alert: () => (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 4.5v4M8 11h.01" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  Check: () => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M3 8.5l3.2 3L13 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  // Track icons
  AI: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <rect x="5" y="5" width="14" height="14" rx="3" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="9.5" cy="10" r="1" fill="currentColor" />
      <circle cx="14.5" cy="10" r="1" fill="currentColor" />
      <path d="M9 14.5c.8.7 1.8 1 3 1s2.2-.3 3-1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  IIoT: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="2.2" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="4" cy="6" r="1.5" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="20" cy="6" r="1.5" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="4" cy="18" r="1.5" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="20" cy="18" r="1.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M5.2 6.8L10 11M18.8 6.8L14 11M5.2 17.2L10 13M18.8 17.2L14 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
  Code: () => (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M9 7l-5 5 5 5M15 7l5 5-5 5M13.5 5l-3 14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

/* ---------- Copy (TH/EN) ---------- */
const COPY = {
  en: {
    eyebrow: "Internal Program",
    title: { en: "Tech Quest 2026 Registration", th: "ลงทะเบียน Tech Quest 2026" },
    subtitle: (
      <>
        A 12-week upskilling program for engineers and operations staff to build hands-on capability in AI, IIoT, and software delivery. Register by{" "}
        <span className="deadline">June 14, 2026</span>.
      </>
    ),
    s1: { en: "Personal Information", th: "ข้อมูลส่วนตัว" },
    s2: { en: "Program Preferences", th: "ความสนใจ" },
    s3: { en: "Consent", th: "การยินยอม" },
    fullName: "Full Name (Thai) / ชื่อ-นามสกุล (ไทย)",
    employeeId: "Employee ID",
    department: "Department",
    email: "Work Email",
    phone: "Phone",
    track: "Choose your track",
    trackHint: "Pick the area you'd like to focus on for the 12 weeks.",
    level: "Experience level",
    levelHint: "Your self-assessed level in this track today.",
    motivation: "Why do you want to join?",
    motivationHint: "Optional — share what you hope to take away from the program.",
    terms: "I agree to the program terms and code of conduct",
    termsTh: "ยอมรับเงื่อนไขโปรแกรม",
    readTerms: "Read terms",
    updates: "I'd like to receive program updates by email.",
    helper: "Fields marked",
    helperEnd: "are required.",
    cancel: "Cancel",
    submit: "Submit Registration",
    submitting: "Submitting…",
    success: "Registration submitted — confirmation sent to your email.",
    emailError: "Please use your company email (@gsbattery.co.th).",
  },
  th: {
    eyebrow: "โปรแกรมภายใน",
    title: { en: "Tech Quest 2026 Registration", th: "ลงทะเบียน Tech Quest 2026" },
    subtitle: (
      <>
        โปรแกรม upskilling 12 สัปดาห์สำหรับวิศวกรและทีมปฏิบัติการ เพื่อสร้างความสามารถใน AI, IIoT และการพัฒนาซอฟต์แวร์ ลงทะเบียนภายใน{" "}
        <span className="deadline">14 มิถุนายน 2569</span>.
      </>
    ),
    s1: { en: "Personal Information", th: "ข้อมูลส่วนตัว" },
    s2: { en: "Program Preferences", th: "ความสนใจ" },
    s3: { en: "Consent", th: "การยินยอม" },
    fullName: "ชื่อ-นามสกุล (ไทย)",
    employeeId: "รหัสพนักงาน",
    department: "แผนก",
    email: "อีเมลบริษัท",
    phone: "เบอร์โทรศัพท์",
    track: "เลือกสายการเรียน",
    trackHint: "เลือกหัวข้อที่ต้องการมุ่งเน้นตลอด 12 สัปดาห์",
    level: "ระดับประสบการณ์",
    levelHint: "ประเมินระดับของคุณในสายนี้ ณ ปัจจุบัน",
    motivation: "เหตุผลที่ต้องการเข้าร่วม",
    motivationHint: "ไม่บังคับ — แบ่งปันสิ่งที่คุณคาดหวังจะได้รับ",
    terms: "ยอมรับเงื่อนไขและแนวปฏิบัติของโปรแกรม",
    termsTh: "",
    readTerms: "อ่านเงื่อนไข",
    updates: "ต้องการรับข่าวสารโปรแกรมทางอีเมล",
    helper: "ช่องที่มี",
    helperEnd: "เป็นช่องที่จำเป็นต้องกรอก",
    cancel: "ยกเลิก",
    submit: "ส่งการลงทะเบียน",
    submitting: "กำลังส่ง…",
    success: "ส่งการลงทะเบียนเรียบร้อย — ส่งอีเมลยืนยันแล้ว",
    emailError: "กรุณาใช้อีเมลบริษัท (@gsbattery.co.th)",
  },
};

const TRACKS = [
  {
    id: "ai",
    icon: <Icon.AI />,
    title: { en: "AI & Data", th: "AI และข้อมูล" },
    desc: {
      en: "Apply ML and analytics to factory and customer data.",
      th: "ประยุกต์ ML และการวิเคราะห์ข้อมูลโรงงานและลูกค้า",
    },
  },
  {
    id: "iiot",
    icon: <Icon.IIoT />,
    title: { en: "IIoT & Automation", th: "IIoT และระบบอัตโนมัติ" },
    desc: {
      en: "Connect machines, sensors, and SCADA into one stack.",
      th: "เชื่อมต่อเครื่องจักร เซ็นเซอร์ และ SCADA เข้าสู่ระบบเดียว",
    },
  },
  {
    id: "swe",
    icon: <Icon.Code />,
    title: { en: "Software Development", th: "พัฒนาซอฟต์แวร์" },
    desc: {
      en: "Ship internal tools with modern web and API stacks.",
      th: "สร้างเครื่องมือภายในด้วย web stack และ API สมัยใหม่",
    },
  },
];

const LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"];
const DEPARTMENTS = [
  "Manufacturing", "Engineering", "Quality Assurance", "R&D",
  "IT & Digital", "Supply Chain", "Sales & Marketing", "HR & Admin",
];

/* ---------- Components ---------- */
function Field({ label, required, optional, error, help, children }) {
  return (
    <div className={`field${error ? " error" : ""}`}>
      <label className="field-label">
        {label}
        {required && <span className="req" aria-hidden>*</span>}
        {optional && <span className="opt">(optional)</span>}
      </label>
      {children}
      {error ? (
        <div className="field-help error-msg">
          <Icon.Alert /> <span>{error}</span>
        </div>
      ) : help ? (
        <div className="field-help">{help}</div>
      ) : null}
    </div>
  );
}

function TrackCard({ track, selected, onSelect, lang }) {
  return (
    <button
      type="button"
      className={`track${selected ? " selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span className="track-radio" aria-hidden />
      <span className="track-icon">{track.icon}</span>
      <span className="track-title">{track.title[lang]}</span>
      <span className="track-desc">{track.desc[lang]}</span>
    </button>
  );
}

function Segmented({ value, onChange, options }) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          role="radio"
          aria-checked={value === opt}
          className={`seg-btn${value === opt ? " active" : ""}`}
          onClick={() => onChange(opt)}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

function SubmitButton({ state = "default", label, labelLoading, onClick, disabled, type = "button" }) {
  // state: default | hover | loading | disabled
  const isLoading = state === "loading";
  const isDisabled = state === "disabled" || disabled;
  const cls = [
    "btn", "btn-primary",
    state === "hover" ? "is-hover" : "",
    isDisabled ? "disabled" : "",
  ].join(" ").trim();
  const style = state === "hover" ? { background: "var(--primary-hover)" } : undefined;
  return (
    <button
      type={type}
      className={cls}
      style={style}
      disabled={isDisabled || isLoading}
      onClick={onClick}
    >
      {isLoading ? <span className="spinner" aria-hidden /> : null}
      <span>{isLoading ? labelLoading : label}</span>
    </button>
  );
}

/* ---------- App ---------- */
function App() {
  const [lang, setLang] = useState("en");
  const t = COPY[lang];

  const [form, setForm] = useState({
    fullName: "",
    employeeId: "",
    department: "",
    email: "somchai.k@gmail.com", // deliberately wrong domain to show error state
    phone: "",
    track: "iiot",
    level: "Intermediate",
    motivation: "",
    agree: false,
    updates: true,
  });
  const [submitState, setSubmitState] = useState("default"); // default | loading | success
  const [showSuccess, setShowSuccess] = useState(false);

  const set = (k) => (e) => {
    const v = e && e.target ? (e.target.type === "checkbox" ? e.target.checked : e.target.value) : e;
    setForm((f) => ({ ...f, [k]: v }));
  };

  // Email validation — error if non-empty and not @gsbattery.co.th
  const emailError = useMemo(() => {
    if (!form.email) return null;
    const ok = /@gsbattery\.co\.th$/i.test(form.email.trim());
    return ok ? null : t.emailError;
  }, [form.email, lang]);

  const motivationLen = form.motivation.length;
  const counterClass =
    motivationLen > 500 ? "over" : motivationLen > 450 ? "near" : "";

  const canSubmit =
    form.fullName && form.employeeId && form.department &&
    form.email && !emailError && form.phone && form.agree;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!canSubmit || submitState === "loading") return;
    setSubmitState("loading");
    setShowSuccess(false);
    setTimeout(() => {
      setSubmitState("default");
      setShowSuccess(true);
    }, 1600);
  };

  return (
    <>
      {/* Top nav */}
      <header className="nav">
        <img className="nav-logo" src="assets/gs-logo.png" alt="GS Battery" />
        <div className="nav-right">
          <button className="icon-btn" aria-label="Help"><Icon.Help /></button>
          <button className="icon-btn" aria-label="Notifications"><Icon.Bell /></button>
          <div className="lang-toggle" role="tablist" aria-label="Language">
            <button
              type="button"
              className={lang === "th" ? "active" : ""}
              onClick={() => setLang("th")}
              aria-pressed={lang === "th"}
            >TH</button>
            <button
              type="button"
              className={lang === "en" ? "active" : ""}
              onClick={() => setLang("en")}
              aria-pressed={lang === "en"}
            >EN</button>
          </div>
          <div className="avatar" title="Somchai K.">SK</div>
        </div>
      </header>

      {/* Page */}
      <main className="page">
        {/* Header block */}
        <span className="eyebrow"><span className="dot" /> {t.eyebrow}</span>
        <h1 className="page-title">
          <span className="th">ลงทะเบียน Tech Quest 2026</span>
          <span style={{ color: "var(--text-secondary)", fontWeight: 500, fontSize: 18, marginTop: 2, display: "block" }}>
            Tech Quest 2026 Registration
          </span>
        </h1>
        <p className="subtitle">{t.subtitle}</p>

        {/* Form */}
        <form className="card" onSubmit={handleSubmit} noValidate>
          <div className="card-body">
            {/* Section 1 */}
            <h2 className="section-title">
              <span className="section-num">01</span>
              {t.s1.en} <span className="th-label">/ {t.s1.th}</span>
            </h2>

            <div className="grid-2" style={{ marginTop: 16 }}>
              <div className="full">
                <Field label={t.fullName} required>
                  <input
                    className="input"
                    type="text"
                    placeholder="เช่น สมชาย กิตติพงษ์"
                    value={form.fullName}
                    onChange={set("fullName")}
                  />
                </Field>
              </div>
              <Field label={t.employeeId} required>
                <input
                  className="input"
                  type="text"
                  placeholder="GSB-00000"
                  value={form.employeeId}
                  onChange={set("employeeId")}
                />
              </Field>
              <Field label={t.department} required>
                <select
                  className="select"
                  value={form.department}
                  data-empty={!form.department}
                  onChange={set("department")}
                >
                  <option value="">Select department…</option>
                  {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </Field>
              <Field label={t.email} required error={emailError}>
                <div className="input-wrap">
                  <span className="input-prefix"><Icon.Mail /></span>
                  <input
                    className="input has-prefix"
                    type="email"
                    placeholder="name@gsbattery.co.th"
                    value={form.email}
                    onChange={set("email")}
                    aria-invalid={!!emailError}
                  />
                </div>
              </Field>
              <Field label={t.phone} required>
                <div className="input-wrap">
                  <span className="input-prefix"><Icon.Phone /></span>
                  <input
                    className="input has-prefix"
                    type="tel"
                    placeholder="08x xxx xxxx"
                    value={form.phone}
                    onChange={set("phone")}
                  />
                </div>
              </Field>
            </div>

            <hr className="divider" />

            {/* Section 2 */}
            <h2 className="section-title">
              <span className="section-num">02</span>
              {t.s2.en} <span className="th-label">/ {t.s2.th}</span>
            </h2>

            <Field label={t.track} required help={t.trackHint}>
              <div className="track-grid" style={{ marginTop: 4 }}>
                {TRACKS.map((tr) => (
                  <TrackCard
                    key={tr.id}
                    track={tr}
                    lang={lang}
                    selected={form.track === tr.id}
                    onSelect={() => setForm((f) => ({ ...f, track: tr.id }))}
                  />
                ))}
              </div>
            </Field>

            <div style={{ height: 20 }} />

            <Field label={t.level} required help={t.levelHint}>
              <Segmented
                value={form.level}
                onChange={(v) => setForm((f) => ({ ...f, level: v }))}
                options={LEVELS}
              />
            </Field>

            <div style={{ height: 20 }} />

            <Field
              label={t.motivation}
              optional
              help={
                <>
                  <span>{t.motivationHint}</span>
                  <span className={`char-counter ${counterClass}`}>
                    {motivationLen}/500
                  </span>
                </>
              }
            >
              <textarea
                className="textarea"
                rows={4}
                maxLength={500}
                placeholder={lang === "th"
                  ? "เขียนสั้นๆ ว่าคุณอยากเรียนรู้อะไร และจะนำไปใช้กับงานอย่างไร…"
                  : "Tell us briefly what you want to learn and how you'd apply it…"}
                value={form.motivation}
                onChange={set("motivation")}
              />
            </Field>

            <hr className="divider" />

            {/* Section 3 */}
            <h2 className="section-title">
              <span className="section-num">03</span>
              {t.s3.en} <span className="th-label">/ {t.s3.th}</span>
            </h2>

            <div style={{ marginTop: 12 }}>
              <label className="check-row">
                <input type="checkbox" className="check" checked={form.agree} onChange={set("agree")} />
                <span className="check-label">
                  {t.terms}
                  {t.termsTh && <span className="th">/ {t.termsTh}</span>}
                  <a href="#" onClick={(e) => e.preventDefault()}>{t.readTerms} →</a>
                </span>
              </label>
              <label className="check-row">
                <input type="checkbox" className="check" checked={form.updates} onChange={set("updates")} />
                <span className="check-label">{t.updates}</span>
              </label>
            </div>

            {showSuccess && (
              <div className="success-toast">
                <Icon.Check />
                <span>{t.success}</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="card-footer">
            <div className="footer-help">
              {t.helper} <span className="req">*</span> {t.helperEnd}
            </div>
            <div className="card-footer-actions">
              <button type="button" className="btn btn-ghost">{t.cancel}</button>
              <SubmitButton
                type="submit"
                state={submitState === "loading" ? "loading" : (canSubmit ? "default" : "disabled")}
                label={t.submit}
                labelLoading={t.submitting}
                onClick={handleSubmit}
              />
            </div>
          </div>
        </form>

        {/* Annotation: button states */}
        <div className="annotation" aria-label="Submit button — state reference">
          <div className="annotation-title">Submit Button — States Reference</div>
          <div className="swatches">
            <div className="swatch">
              <SubmitButton state="default" label={t.submit} />
              <span className="swatch-label">default</span>
            </div>
            <div className="swatch">
              <SubmitButton state="hover" label={t.submit} />
              <span className="swatch-label">hover</span>
            </div>
            <div className="swatch">
              <SubmitButton state="loading" label={t.submit} labelLoading={t.submitting} />
              <span className="swatch-label">loading</span>
            </div>
            <div className="swatch">
              <SubmitButton state="disabled" label={t.submit} />
              <span className="swatch-label">disabled</span>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
