"""
Generates a publication-grade PDF specification for Concat & IncuBrix.
Uses ReportLab Platypus with custom styles, tables, and page numbering.
"""
import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_header_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        
        # Draw running header on pages > 1
        if self._pageNumber > 1:
            self.drawString(36, 11 * inch - 28, "CONCAT & INCUBRIX — ARCHITECTURE & COMPLETE API SPECIFICATION")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(36, 11 * inch - 32, 8.5 * inch - 36, 11 * inch - 32)

        # Draw running footer
        self.setFont("Helvetica", 8)
        self.drawString(36, 25, "Confidential & Proprietary — IncuBrix Video Intelligence Platform")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.5 * inch - 36, 25, page_text)
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(36, 35, 8.5 * inch - 36, 35)
        
        self.restoreState()


def build_pdf():
    pdf_path = r"N:\Concat\Concat_Editor_Architecture_and_API_Reference.pdf"
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=42,
        bottomMargin=45
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#0f172a")
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#475569")
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1e293b")
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1e293b"),
        leftIndent=12,
        spaceAfter=2
    )

    code_style = ParagraphStyle(
        'Code_Custom',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#0f172a")
    )

    badge_style = ParagraphStyle(
        'Badge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white
    )

    th_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white
    )

    td_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#1e293b")
    )

    td_code = ParagraphStyle(
        'TableCellCode',
        parent=styles['Normal'],
        fontName='Courier-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#0f172a")
    )

    story = []

    # Title Banner
    meta_box = [
        [
            Paragraph("<b>CONCAT DESKTOP VIDEO EDITOR & INCUBRIX AI ENGINE</b>", title_style),
            Paragraph("<font color='#d97706'><b>TECHNICAL SPECIFICATION</b></font><br/>v0.2.7 • October 2026", ParagraphStyle('MetaRight', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, alignment=2, textColor=colors.HexColor("#475569")))
        ],
        [
            Paragraph("Comprehensive Architectural Breakdown, Complete API Endpoints, Tech Stack & Workflow Guide", subtitle_style),
            Paragraph("<b>Target Platform:</b> Win64 / GPU D3D12", ParagraphStyle('MetaSubRight', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, alignment=2, textColor=colors.HexColor("#64748b")))
        ]
    ]
    t_meta = Table(meta_box, colWidths=[410, 130])
    t_meta.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0f172a"), spaceBefore=2, spaceAfter=8))

    # Section 1: Executive Overview
    story.append(Paragraph("1. Executive Overview & Dual-Engine Architecture", h1_style))
    story.append(Paragraph(
        "Concat is a professional, high-performance desktop non-linear video editor (NLE) paired with the IncuBrix AI Editing Engine. "
        "The system decouples UI and video rendering from AI language comprehension, providing a dual-engine architecture that achieves both sub-millisecond desktop responsiveness and deterministic, audit-verifiable video transformations.",
        body_style
    ))
    story.append(Spacer(1, 4))

    # Architecture Overview Table
    arch_data = [
        [
            Paragraph("<b>Layer</b>", th_style),
            Paragraph("<b>Core Modules</b>", th_style),
            Paragraph("<b>Technology Stack</b>", th_style),
            Paragraph("<b>Key Responsibilities</b>", th_style)
        ],
        [
            Paragraph("<b>Frontend UI</b>", td_style),
            Paragraph("ai-conversation.slint<br/>media-pane.slint<br/>timeline.slint", td_code),
            Paragraph("Slint 1.18.1<br/>Skia 2D / D3D12<br/>Tailwind CSS (Dev)", td_style),
            Paragraph("Reactive 2-way property bindings, GPU window composition, fluid multi-resolution layout (260px-4K), disambiguation modals.", td_style)
        ],
        [
            Paragraph("<b>Native Core</b>", td_style),
            Paragraph("concat-host<br/>concat-render<br/>concat-media<br/>concat-speech", td_code),
            Paragraph("Rust 2021 (MSVC)<br/>WGPU / WGSL<br/>FFmpeg 6.0 (C bindings)<br/>Whisper C++ / Sherpa-ONNX", td_style),
            Paragraph("Hardware video decoding (D3D11VA/NVDEC), multi-pass fragment shader pipelines (halation, corona, LUTs), neural audio transcription.", td_style)
        ],
        [
            Paragraph("<b>AI Engine</b>", td_style),
            Paragraph("engine.api<br/>engine.core<br/>engine.parser<br/>engine.jobs", td_code),
            Paragraph("Python 3.11<br/>FastAPI / Pydantic v2<br/>OpenTimelineIO (OTIO)<br/>Pytest (79 test suite)", td_style),
            Paragraph("Natural language parsing, spoken word ID anchoring ([start, end]), 3-way clarification policy, deterministic SHA-256 state hashing.", td_style)
        ],
        [
            Paragraph("<b>IPC & Transports</b>", td_style),
            Paragraph("concat-server<br/>concat-api", td_code),
            Paragraph("JSON-RPC 2.0 lines<br/>gRPC / HTTP/2<br/>Tokens (128-bit os-random)", td_style),
            Paragraph("Process synchronization, event streaming (export progress, playback status), sandboxed access controls.", td_style)
        ]
    ]
    t_arch = Table(arch_data, colWidths=[65, 110, 115, 250])
    t_arch.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t_arch)
    story.append(Spacer(1, 8))

    # Section 2: Complete API Endpoints Reference
    story.append(Paragraph("2. IncuBrix AI Engine REST API Reference (/api/v1/)", h1_style))
    story.append(Paragraph(
        "The IncuBrix Engine exposes a RESTful interface compliant with enterprise Integration Standards: structured error envelopes (code, message), correlation tracking, asynchronous job handling with HTTP 202, and Idempotency-Key guarantees.",
        body_style
    ))
    story.append(Spacer(1, 4))

    api_data = [
        [
            Paragraph("<b>Method & Endpoint</b>", th_style),
            Paragraph("<b>Status</b>", th_style),
            Paragraph("<b>Request Payload</b>", th_style),
            Paragraph("<b>Response Structure & Purpose</b>", th_style)
        ],
        [
            Paragraph("<b>GET /health</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("None", td_style),
            Paragraph("<b>Liveness Probe:</b> <code>{\"status\": \"ok\", \"service\": \"incubrix-editing-engine\", \"version\": \"1.0.0\"}</code>", td_style)
        ],
        [
            Paragraph("<b>GET /ready</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("None", td_style),
            Paragraph("<b>Readiness Probe:</b> Confirms Whisper transcription models, FFmpeg binaries, and storage backends are operational.", td_style)
        ],
        [
            Paragraph("<b>POST /api/v1/sessions</b>", td_code),
            Paragraph("201 Created", td_style),
            Paragraph("<code>{\"video_url_or_path\": \"sample.mp4\", \"time_policy\": \"original_time\"}</code>", td_code),
            Paragraph("<b>Session Initialization:</b> Probes video streams, transcribes word IDs, computes baseline SHA-256 hash. Returns <code>session_id</code>, <code>duration_s</code>, <code>fps</code>, <code>timeline_hash</code>.", td_style)
        ],
        [
            Paragraph("<b>GET /api/v1/sessions/{id}</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("URL Parameter: session_id", td_style),
            Paragraph("<b>Session Inspection:</b> Retrieves active timeline metadata, duration, source media ID, and current revision hash.", td_style)
        ],
        [
            Paragraph("<b>POST /api/v1/sessions/{id}/step</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("<code>{\"say\": \"Cut first 30s\"}</code><br/><i>or disambiguation:</i><br/><code>{\"say\": \"Remove pricing\", \"answer\": \"2\"}</code>", td_code),
            Paragraph("<b>Conversational AI Step:</b> Executes instruction on timeline. Returns status (<code>applied</code> or <code>needs_clarification</code>), operations applied, updated duration, summary, and new SHA-256 hash.", td_style)
        ],
        [
            Paragraph("<b>POST /api/v1/jobs</b>", td_code),
            Paragraph("202 Accepted", td_style),
            Paragraph("Header: <code>Idempotency-Key</code><br/><code>{\"job_type\": \"render\", \"session_id\": \"...\", \"callback_url\": \"...\"}</code>", td_code),
            Paragraph("<b>Background Job Queue:</b> Spawns asynchronous tasks (>2s like video rendering). Prevents duplicate jobs via Idempotency-Key. Returns <code>job_id</code>, initial status, and progress=0.", td_style)
        ],
        [
            Paragraph("<b>GET /api/v1/jobs/{id}</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("URL Parameter: job_id", td_style),
            Paragraph("<b>Job Polling:</b> Returns real-time progress (0-100%). Upon completion, includes download URL, final timeline hash, and media manifest.", td_style)
        ],
        [
            Paragraph("<b>GET /api/v1/timeline/{id}</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("URL Parameter: session_id", td_style),
            Paragraph("<b>Complete Timeline Schema:</b> Returns resolved clips array, active captions, audio effects, and deterministic edit history chain.", td_style)
        ],
        [
            Paragraph("<b>POST /api/v1/timeline/{id}/otio</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("URL Parameter: session_id", td_style),
            Paragraph("<b>OpenTimelineIO Export:</b> Translates internal timeline state into industry-standard <code>.otio</code> JSON file and returns storage download link.", td_style)
        ],
        [
            Paragraph("<b>GET /api/v1/storage/download/{file}</b>", td_code),
            Paragraph("200 OK", td_style),
            Paragraph("URL Parameter: filename", td_style),
            Paragraph("<b>Static Media Server:</b> Streams rendered MP4 videos, exported OTIO projects, and generated proxies from local/S3 storage.", td_style)
        ]
    ]
    t_api = Table(api_data, colWidths=[130, 48, 142, 220])
    t_api.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e3a8a")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t_api)
    story.append(Spacer(1, 8))

    story.append(PageBreak())

    # Section 3: Concat Native Socket API
    story.append(Paragraph("3. Concat Native Socket & JSON-RPC API (`concat-server`)", h1_style))
    story.append(Paragraph(
        "The Concat native desktop core exposes a JSON-RPC 2.0 interface across local TCP/Unix sockets. "
        "It enforces 128-bit OS-random token authorization, constant-time comparisons, connection limits, and bounded render requests.",
        body_style
    ))
    story.append(Spacer(1, 4))

    socket_data = [
        [
            Paragraph("<b>JSON-RPC Method</b>", th_style),
            Paragraph("<b>Parameters</b>", th_style),
            Paragraph("<b>Category</b>", th_style),
            Paragraph("<b>Detailed Description & Return Payload</b>", th_style)
        ],
        [
            Paragraph("<code>version</code>", td_code),
            Paragraph("None", td_style),
            Paragraph("System", td_style),
            Paragraph("Returns API version (<code>0.2</code>), build capabilities (<code>[\"events\", \"grpc\"]</code>), and engine build commit hash.", td_style)
        ],
        [
            Paragraph("<code>project.create</code>", td_code),
            Paragraph("<code>location</code>, <code>name</code>, <code>video?</code>", td_code),
            Paragraph("Project", td_style),
            Paragraph("Initializes a new <code>.concat</code> project bundle with specified canvas resolution (default 1080p @ 30fps).", td_style)
        ],
        [
            Paragraph("<code>project.open</code>", td_code),
            Paragraph("<code>path</code>", td_code),
            Paragraph("Project", td_style),
            Paragraph("Loads project document, verifies file locks, and mounts media assets into memory.", td_style)
        ],
        [
            Paragraph("<code>project.get</code>", td_code),
            Paragraph("<code>path</code>", td_code),
            Paragraph("Project", td_style),
            Paragraph("Returns active document tree: audio/video tracks, transitions, markers, and clip geometry.", td_style)
        ],
        [
            Paragraph("<code>project.save</code>", td_code),
            Paragraph("<code>path</code>, <code>name?</code>", td_code),
            Paragraph("Project", td_style),
            Paragraph("Atomically writes project JSON to disk using temporary file swap semantics.", td_style)
        ],
        [
            Paragraph("<code>edit.apply</code>", td_code),
            Paragraph("<code>path</code>, <code>command</code>", td_code),
            Paragraph("Editing", td_style),
            Paragraph("Applies an atomic edit command (SplitClip, TrimIn, TrimOut, MoveClip, AddEffect, SetVolume). Returns error sentence on refusal.", td_style)
        ],
        [
            Paragraph("<code>edit.undo</code> / <code>redo</code>", td_code),
            Paragraph("<code>path</code>", td_code),
            Paragraph("Editing", td_style),
            Paragraph("Steps the project revision stack backward or forward one command state.", td_style)
        ],
        [
            Paragraph("<code>media.probe</code>", td_code),
            Paragraph("<code>path</code>", td_code),
            Paragraph("Media", td_style),
            Paragraph("Invokes FFprobe to inspect container streams, pixel format, frame count, audio channels, and bitrate.", td_style)
        ],
        [
            Paragraph("<code>media.import</code>", td_code),
            Paragraph("<code>path</code>, <code>file</code>", td_code),
            Paragraph("Media", td_style),
            Paragraph("Probes source file and registers it in the project media bin (idempotent; no-op if already imported).", td_style)
        ],
        [
            Paragraph("<code>catalogue.list</code>", td_code),
            Paragraph("<code>kind?</code>", td_code),
            Paragraph("Effects", td_style),
            Paragraph("Queries all 28+ GPU effect packages (effects, filters, audio, transitions, generators) and knob parameter schemas.", td_style)
        ],
        [
            Paragraph("<code>template.instantiate</code>", td_code),
            Paragraph("<code>template</code>, <code>location</code>, <code>fills</code>", td_code),
            Paragraph("Templates", td_style),
            Paragraph("Fills placeholder slots in a pre-made template bundle to instantiate a complete custom video project.", td_style)
        ],
        [
            Paragraph("<code>export.run</code>", td_code),
            Paragraph("<code>path</code>, <code>output</code>, <code>crf</code>, <code>codec</code>, <code>ten_bit</code>", td_code),
            Paragraph("Export", td_style),
            Paragraph("Spawns hardware-accelerated background render pipeline. Emits real-time progress events over socket.", td_style)
        ],
        [
            Paragraph("<code>preview.frame</code>", td_code),
            Paragraph("<code>path</code>, <code>time</code>, <code>output?</code>", td_code),
            Paragraph("Preview", td_style),
            Paragraph("Composites true frame at time <code>t</code> (sub-pixel accurate). Writes PNG or returns inline Base64 byte array.", td_style)
        ]
    ]
    t_socket = Table(socket_data, colWidths=[105, 115, 55, 265])
    t_socket.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t_socket)
    story.append(Spacer(1, 8))

    # Section 4: Technology Stack Deep Dive
    story.append(Paragraph("4. Comprehensive Technology Stack Deep Dive", h1_style))
    story.append(Paragraph(
        "Concat and IncuBrix combine cutting-edge systems programming in Rust with agile neural processing in Python.",
        body_style
    ))
    story.append(Spacer(1, 4))

    tech_notes = [
        ("Slint UI 1.18.1 (Native Declarative GUI)", "Compiles declarative .slint templates directly into Rust structs. Uses i-slint-renderer-skia for GPU-accelerated drawing on Direct3D 12. Implements 2-way reactive bindings (text <=> root.prompt-text) and auto-relayout without React/Electron overhead."),
        ("Rust Core (Host & Audio/Video Engine)", "Zero-cost memory safety. Houses Winit window management, multithreaded audio mixing graphs, command-pattern undo/redo histories, and asynchronous job coordinators."),
        ("WGPU & WGSL Compute / Render Pipeline", "Native hardware rendering on Direct3D 12 (Windows) and Vulkan. Executes custom multi-pass shaders (halation, film grain, corona, blur-dissolve, 3D LUTs) directly on GPU compute pipelines."),
        ("FFmpeg 6.0 & Hardware Video Acceleration", "Links ffmpeg-the-third. Features Direct3D 11 Video Acceleration (D3D11VA) and NVDEC for 4K/8K hardware decoding, custom filtergraphs, and multi-format container muxing."),
        ("Whisper C++ & Sherpa-ONNX Speech Models", "Offline, private neural speech recognition. Generates token-level transcripts with precise millisecond timestamps used by the Spoken Word Anchoring algorithm."),
        ("FastAPI & OpenTimelineIO (Python Engine)", "Stateless async microservice architecture. Validates models with Pydantic v2, enforces 3-way ambiguity clarification policies, and outputs universal OTIO project files.")
    ]
    for title, desc in tech_notes:
        story.append(Paragraph(f"• <b>{title}:</b> {desc}", bullet_style))
    story.append(Spacer(1, 8))

    story.append(PageBreak())

    # Section 5: Frontend-Backend Choreography
    story.append(Paragraph("5. Frontend-Backend Choreography & The AI Edit Lifecycle", h1_style))
    story.append(Paragraph(
        "Editing video with natural language requires handling ambiguity, non-destructive layer composition, and temporal shifts. The following diagram and principles detail how an edit flows from user intent to rendered video.",
        body_style
    ))
    story.append(Spacer(1, 4))

    flow_steps = [
        [
            Paragraph("<b>Step</b>", th_style),
            Paragraph("<b>Component</b>", th_style),
            Paragraph("<b>Action & State Transformation</b>", th_style)
        ],
        [
            Paragraph("1. User Prompt", td_style),
            Paragraph("Slint UI", td_code),
            Paragraph("User types: <i>'Cut the first 30 seconds'</i> into <code>ai-conversation.slint</code> or clicks suggestion pill.", td_style)
        ],
        [
            Paragraph("2. Dispatch", td_style),
            Paragraph("App Host -> Engine", td_code),
            Paragraph("Dispatches HTTP <code>POST /api/v1/sessions/{id}/step</code> carrying <code>{\"say\": \"Cut the first 30 seconds\"}</code>.", td_style)
        ],
        [
            Paragraph("3. Word Anchoring", td_style),
            Paragraph("InstructionEngine", td_code),
            Paragraph("Evaluates time policy (<code>original_time</code>). Identifies spoken words [0, 48] corresponding to the initial 30 seconds of audio.", td_style)
        ],
        [
            Paragraph("4. Caption Shift", td_style),
            Paragraph("TimelineCore", td_code),
            Paragraph("Captions anchored to word IDs [2, 5] ('Welcome!') automatically shift playback from 0:42 to 0:12. Audio and video remain 100% in sync.", td_style)
        ],
        [
            Paragraph("5. Ledger Hash", td_style),
            Paragraph("Hashing Engine", td_code),
            Paragraph("Computes new SHA-256 state hash (<code>87c4f92d19e0</code>). Appends operation to deterministic audit chain.", td_style)
        ],
        [
            Paragraph("6. UI Re-render", td_style),
            Paragraph("Slint GPU Pipeline", td_code),
            Paragraph("Receives StepResponse (status: <code>applied</code>). Adds conversation card, updates duration badge to <code>3:42 (-30.0s)</code>, refreshes timeline.", td_style)
        ]
    ]
    t_flow = Table(flow_steps, colWidths=[65, 115, 360])
    t_flow.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t_flow)
    story.append(Spacer(1, 8))

    # Core Invariants Callout Box
    story.append(Paragraph("6. Core System Invariants & Policies", h1_style))
    
    invariants_box = [
        [
            Paragraph("<b>INVARIANT 1: SPOKEN WORD ANCHORING</b><br/>"
                      "Edits are never bound to brittle static timestamps. Captions, sound effects, and transitions anchor directly to spoken Word IDs. "
                      "When preceding content is cut or sped up, anchors translate their playback time dynamically to maintain exact synchronization.", body_style)
        ],
        [
            Paragraph("<b>INVARIANT 2: 3-WAY AMBIGUITY DISAMBIGUATION POLICY</b><br/>"
                      "When an instruction matches multiple points (e.g., <i>'Remove pricing'</i> when pricing appears at 1:05, 2:40, and 3:15), "
                      "the engine halts execution and returns <code>status: 'needs_clarification'</code>. The UI renders a dedicated amber disambiguation card with numbered choices. Answering resolves the ambiguity non-destructively.", body_style)
        ],
        [
            Paragraph("<b>INVARIANT 3: DETERMINISTIC REVISION LEDGER (SHA-256 CHAIN)</b><br/>"
                      "Every edit computes an SHA-256 hash derived from the clip manifest, word anchor map, and active filters. "
                      "Running identical steps in order guarantees identical timeline hashes across different machines and renders.", body_style)
        ],
        [
            Paragraph("<b>INVARIANT 4: NON-DESTRUCTIVE EDIT RESTORATION</b><br/>"
                      "Instructions such as <i>'Actually, put the intro back'</i> do not perform lossy reverse operations. "
                      "The engine identifies Turn 2's cut layer in the revision ledger and non-destructively un-bypasses words [0, 48], restoring the intro while preserving subsequent cuts and speed adjustments.", body_style)
        ]
    ]
    t_inv = Table(invariants_box, colWidths=[540])
    t_inv.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f1f5f9")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#cbd5e1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('LINEBELOW', (0,0), (-1,-2), 0.5, colors.HexColor("#cbd5e1")),
    ]))
    story.append(t_inv)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF successfully generated at: {pdf_path}")

if __name__ == "__main__":
    build_pdf()
