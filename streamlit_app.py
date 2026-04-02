"""
CV Shortlist Agent — Streamlit Web UI
Wraps the existing CVShortlistAgent CLI agent with a browser-based interface.
"""
import pathlib
import re
import sys
import tempfile

import streamlit as st

# ── Imports: use local copies (self-contained for Railway deployment) ─────────
AGENT_DIR = pathlib.Path(__file__).parent
sys.path.insert(0, str(AGENT_DIR))

from dotenv import load_dotenv
# Load .env if present locally; on Railway env vars are set directly
load_dotenv(AGENT_DIR / ".env", override=False)

# ── Report parser ─────────────────────────────────────────────────────────────

def parse_report(md: str) -> dict:
    """Extract executive summary and per-candidate pros/cons from the markdown report."""

    result = {"title": "", "summary": "", "candidates": [], "next_steps": ""}

    # Title
    title_match = re.search(r"^#\s+(.+)$", md, re.MULTILINE)
    if title_match:
        result["title"] = title_match.group(1).strip()

    # Executive summary — everything between ## Executive Summary and the next ##
    summary_match = re.search(
        r"##\s+Executive Summary\s*\n+(.*?)(?=\n##\s|\Z)", md, re.DOTALL
    )
    if summary_match:
        result["summary"] = summary_match.group(1).strip()

    # Next steps
    next_match = re.search(
        r"##\s+Recommended Next Steps\s*\n+(.*?)(?=\n##\s|\Z)", md, re.DOTALL
    )
    if next_match:
        result["next_steps"] = next_match.group(1).strip()

    # Candidates — each starts with ### N. Name — Score: XX/100
    candidate_blocks = re.split(r"(?=###\s+\d+\.)", md)
    for block in candidate_blocks:
        header = re.match(r"###\s+\d+\.\s+(.+?)\s+[—–-]+\s+Score:\s*(\d+)/100", block)
        if not header:
            continue

        name = header.group(1).strip()
        score = int(header.group(2))

        def extract_bullets(section_title: str, text: str, limit: int = 3) -> list[str]:
            # Handles both **Title:** and **Title**:
            pattern = rf"\*\*{re.escape(section_title)}[:\s]*\*\*[:\s]*\n((?:\s*-\s+.+\n?)+)"
            m = re.search(pattern, text)
            if not m:
                return []
            bullets = re.findall(r"-\s+(.+)", m.group(1))
            return [b.strip() for b in bullets[:limit]]

        strengths = extract_bullets("Strengths", block)
        gaps = (
            extract_bullets("Gaps / Watch Points", block)
            or extract_bullets("Gaps", block)
            or extract_bullets("Watch Points", block)
        )

        # Current role
        role_match = re.search(r"\*\*Current Role:\*\*\s*(.+)", block)
        current_role = role_match.group(1).strip() if role_match else ""

        result["candidates"].append({
            "name": name,
            "score": score,
            "current_role": current_role,
            "strengths": strengths,
            "gaps": gaps,
        })

    return result


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CV Shortlist Agent",
    page_icon="📋",
    layout="wide",
)

st.title("📋 CV Shortlist Agent")
st.caption("Upload a job description and candidate CVs — the AI agent scores, ranks, and explains each candidate.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    demo_mode = st.toggle(
        "⚡ Demo mode",
        value=True,
        help="Caps CVs at 10 for faster results. Turn off for full production runs.",
    )
    if demo_mode:
        st.caption("Processing first 10 CVs only")
    top_n = st.slider("Top N candidates to shortlist", min_value=1, max_value=10, value=3 if demo_mode else 5)
    use_linkedin = st.toggle(
        "LinkedIn validation",
        value=False,
        help="Searches LinkedIn to validate each shortlisted candidate. Slower — disable for demos.",
    )
    criteria = st.text_area(
        "Additional shortlisting criteria",
        placeholder="e.g. Must have 5+ years Python, Danish-speaking preferred, no relocation",
        height=120,
    )
    st.divider()
    st.caption("Powered by Claude (Azure) · Gemini")

# ── Main inputs ───────────────────────────────────────────────────────────────
col_jd, col_cvs = st.columns([1, 2])

with col_jd:
    st.subheader("Job Description")
    jd_file = st.file_uploader(
        "Upload JD file",
        type=["docx", "pdf", "txt"],
        help="Accepts Word (.docx), PDF, or plain text",
    )

with col_cvs:
    st.subheader("Candidate CVs")
    cv_files = st.file_uploader(
        "Drag & drop CV files here, or click to browse",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        help="PDF, Word (.docx), or plain text. To select all files in a folder: open the folder in the dialog, then press Ctrl+A (Windows) or Cmd+A (Mac).",
        label_visibility="visible",
    )
    if cv_files:
        st.success(f"✅ {len(cv_files)} file(s) ready to process")
        with st.expander(f"View uploaded files ({len(cv_files)})", expanded=False):
            for f in cv_files:
                size_kb = round(f.size / 1024, 1)
                st.caption(f"📄 {f.name}  —  {size_kb} KB")
    else:
        st.caption("💡 Tip: Open your CV folder in the file dialog and press **Ctrl+A** to select all files at once, or drag and drop a selection of files directly onto this area.")

# ── Run button ────────────────────────────────────────────────────────────────
st.divider()
ready = bool(jd_file and cv_files)
if not ready:
    st.info("Upload a job description and at least one CV to begin.", icon="ℹ️")

if st.button("🚀 Run Shortlisting", type="primary", disabled=not ready, use_container_width=True):

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = pathlib.Path(tmpdir)
        cv_folder = tmpdir_path / "cvs"
        output_dir = tmpdir_path / "output"
        cv_folder.mkdir()
        output_dir.mkdir()

        # Save uploaded JD
        jd_path = tmpdir_path / jd_file.name
        jd_path.write_bytes(jd_file.getvalue())

        # Save uploaded CVs (cap at 10 in demo mode)
        files_to_process = cv_files[:10] if demo_mode else cv_files
        for cv in files_to_process:
            (cv_folder / cv.name).write_bytes(cv.getvalue())

        # Parse job description text
        suffix = jd_path.suffix.lower()
        if suffix == ".docx":
            from tools.cv_parser import _parse_docx
            job_description = _parse_docx(jd_path)
        elif suffix == ".pdf":
            from tools.cv_parser import _parse_pdf
            job_description = _parse_pdf(jd_path)
        else:
            job_description = jd_path.read_text(encoding="utf-8", errors="ignore")

        # Run agent with live log capture
        import io as _io
        import sys as _sys

        log_lines: list[str] = []

        class LiveCapture(_io.StringIO):
            """Tee stdout to both Streamlit and the real terminal."""
            def __init__(self, real_stdout, log_area):
                super().__init__()
                self._real = real_stdout
                self._area = log_area

            def write(self, text: str):
                self._real.write(text)
                if text.strip():
                    log_lines.append(text.rstrip())
                    self._area.code("\n".join(log_lines[-30:]), language=None)
                return len(text)

            def flush(self):
                self._real.flush()

        with st.status("Running agent…", expanded=True) as status_widget:
            log_placeholder = st.empty()
            _orig_stdout = _sys.stdout
            _sys.stdout = LiveCapture(_orig_stdout, log_placeholder)

            try:
                from agent import run_agent
                run_agent(
                    cv_folder=str(cv_folder),
                    job_description=job_description,
                    criteria=criteria,
                    top_n=top_n,
                    output_dir=str(output_dir),
                    use_linkedin=use_linkedin,
                )
                status_widget.update(label="✅ Shortlisting complete!", state="complete", expanded=False)
            except Exception as exc:
                status_widget.update(label=f"❌ Error: {exc}", state="error")
                st.exception(exc)
            finally:
                _sys.stdout = _orig_stdout

        # Read outputs while temp dir still exists
        md_files = list(output_dir.glob("*.md"))
        docx_files = list(output_dir.glob("*.docx"))

        report_md: str | None = md_files[0].read_text(encoding="utf-8") if md_files else None
        report_docx: bytes | None = docx_files[0].read_bytes() if docx_files else None
        report_docx_name: str = docx_files[0].name if docx_files else "shortlist_report.docx"

    # ── Results ───────────────────────────────────────────────────────────────
    if report_md:
        parsed = parse_report(report_md)

        # ── Download buttons ──────────────────────────────────────────────────
        dl_col1, dl_col2 = st.columns(2)
        if report_docx:
            dl_col1.download_button(
                label="⬇️ Download Word Report (.docx)",
                data=report_docx,
                file_name=report_docx_name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        dl_col2.download_button(
            label="⬇️ Download Markdown (.md)",
            data=report_md.encode("utf-8"),
            file_name=report_docx_name.replace(".docx", ".md"),
            mime="text/markdown",
            use_container_width=True,
        )

        st.divider()

        # ── Executive Summary ─────────────────────────────────────────────────
        if parsed["title"]:
            st.subheader(parsed["title"])
        if parsed["summary"]:
            st.info(parsed["summary"], icon="📝")

        st.divider()

        # ── Candidate cards ───────────────────────────────────────────────────
        if parsed["candidates"]:
            st.subheader(f"Shortlisted Candidates ({len(parsed['candidates'])})")

            for i, c in enumerate(parsed["candidates"]):
                rank_emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1}"
                score = c["score"]
                score_color = (
                    "#22c55e" if score >= 85
                    else "#f59e0b" if score >= 70
                    else "#ef4444"
                )

                with st.container(border=True):
                    # Header row
                    h_col, s_col = st.columns([4, 1])
                    with h_col:
                        st.markdown(f"### {rank_emoji} {c['name']}")
                        if c["current_role"]:
                            st.caption(c["current_role"])
                    with s_col:
                        st.markdown(
                            f"<div style='text-align:right; font-size:2rem; font-weight:700;"
                            f"color:{score_color}'>{score}<span style='font-size:1rem;"
                            f"color:grey'>/100</span></div>",
                            unsafe_allow_html=True,
                        )

                    # Pros / Cons columns
                    pro_col, con_col = st.columns(2)
                    with pro_col:
                        st.markdown("**✅ Strengths**")
                        for b in c["strengths"]:
                            st.markdown(f"- {b}")
                        if not c["strengths"]:
                            st.caption("—")
                    with con_col:
                        st.markdown("**⚠️ Watch Points**")
                        for b in c["gaps"]:
                            st.markdown(f"- {b}")
                        if not c["gaps"]:
                            st.caption("—")

        # ── Full report (collapsed) ───────────────────────────────────────────
        st.divider()
        with st.expander("📄 Full Report", expanded=False):
            st.markdown(report_md)

    else:
        st.error("No report was generated. Check the agent log above for errors.")
